"""Research command — deep research: search → fetch → follow links → save → synthesize."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from urllib.parse import urlparse

import typer

from hyperresearch.cli._output import console, output
from hyperresearch.models.output import error, success


def research(
    topic: str = typer.Argument(..., help="Research topic or question"),
    max_results: int = typer.Option(5, "--max", "-m", help="Max search results to fetch"),
    depth: int = typer.Option(0, "--depth", "-d", help="Link-follow depth (0 = no following)"),
    max_pages: int = typer.Option(10, "--max-pages", help="Max total pages to fetch"),
    tags: list[str] = typer.Option([], "--tag", "-t", help="Tags for all created notes"),
    parent: str | None = typer.Option(None, "--parent", "-p", help="Parent topic"),
    provider_name: str | None = typer.Option(None, "--provider", help="Web provider override"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Deep research: search the web, fetch results, save as linked notes, generate synthesis."""
    from hyperresearch.core.note import write_note
    from hyperresearch.core.sync import compute_sync_plan, execute_sync
    from hyperresearch.core.vault import Vault, VaultError
    from hyperresearch.models.note import slugify
    from hyperresearch.web.base import get_provider

    try:
        vault = Vault.discover()
    except VaultError as e:
        if json_output:
            output(error(str(e), "NO_VAULT"), json_mode=True)
        else:
            console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)

    vault.auto_sync()
    conn = vault.db
    prov = get_provider(provider_name or vault.config.web_provider)

    # Step 1: Search
    if not json_output:
        console.print(f"[bold]Researching:[/] {topic}")
        console.print(f"[dim]Provider: {prov.name}, max results: {max_results}, depth: {depth}[/]")

    try:
        search_results = prov.search(topic, max_results=max_results)
    except NotImplementedError:
        if json_output:
            output(
                error(
                    f"Provider '{prov.name}' does not support web search. "
                    "Use --provider tavily or let your agent search and use 'hyperresearch fetch' instead.",
                    "NO_SEARCH",
                ),
                json_mode=True,
            )
        else:
            console.print(
                f"[red]Provider '{prov.name}' cannot search.[/] "
                "Use --provider tavily, or have your agent search and 'hyperresearch fetch' each URL."
            )
        raise typer.Exit(1)

    if not search_results:
        if json_output:
            output(success({"notes_created": [], "topic": topic}, vault=str(vault.root)), json_mode=True)
        else:
            console.print("[yellow]No results found.[/]")
        return

    if not json_output:
        console.print(f"[green]Found {len(search_results)} results[/]")

    # Step 2: Fetch and save each result
    created_notes: list[dict] = []
    fetched_urls: set[str] = set()
    pages_fetched = 0

    for result in search_results:
        if pages_fetched >= max_pages:
            break
        note_data = _save_result(vault, conn, prov, result, tags, parent)
        if note_data:
            created_notes.append(note_data)
            fetched_urls.add(result.url)
            pages_fetched += 1
            if not json_output:
                console.print(f"  [green]+[/] {note_data['title']}")

    # Step 3: Follow links (depth > 0)
    if depth > 0 and pages_fetched < max_pages:
        links_to_follow = _extract_links_from_results(search_results)
        for d in range(depth):
            if pages_fetched >= max_pages:
                break
            next_links: list[str] = []
            for link_url in links_to_follow:
                if pages_fetched >= max_pages:
                    break
                if link_url in fetched_urls:
                    continue
                # Check if already in DB
                existing = conn.execute(
                    "SELECT note_id FROM sources WHERE url = ?", (link_url,)
                ).fetchone()
                if existing:
                    fetched_urls.add(link_url)
                    continue

                try:
                    result = prov.fetch(link_url)
                    note_data = _save_result(vault, conn, prov, result, tags, parent)
                    if note_data:
                        created_notes.append(note_data)
                        fetched_urls.add(link_url)
                        pages_fetched += 1
                        if not json_output:
                            console.print(f"  [dim]+[/] {note_data['title']} [dim](depth {d + 1})[/]")
                        # Collect links from this page for next depth
                        next_links.extend(_extract_links_from_results([result]))
                except Exception:
                    continue
            links_to_follow = [u for u in next_links if u not in fetched_urls]

    # Step 4: Sync to index everything
    plan = compute_sync_plan(vault)
    if plan.to_add or plan.to_update:
        execute_sync(vault, plan)

    # Step 5: Generate synthesis note (map-of-content)
    if created_notes:
        moc_id = slugify(f"research-{topic}")
        wiki_links = "\n".join(
            f"- [[{n['note_id']}]] — {n.get('summary', n['title'])}"
            for n in created_notes
        )
        moc_body = (
            f"# Research: {topic}\n\n"
            f"**{len(created_notes)} sources collected** "
            f"on {datetime.now(UTC).strftime('%Y-%m-%d')}.\n\n"
            f"## Sources\n\n{wiki_links}\n"
        )

        moc_tags = list(set([*tags, "research", "moc"]))
        moc_path = write_note(
            vault.notes_dir,
            title=f"Research: {topic}",
            body=moc_body,
            note_id=moc_id,
            tags=moc_tags,
            status="review",
            note_type="moc",
            parent=parent,
            summary=f"Research synthesis: {topic} ({len(created_notes)} sources)",
        )

        # Final sync to pick up the MOC
        plan = compute_sync_plan(vault)
        if plan.to_add or plan.to_update:
            execute_sync(vault, plan)

        created_notes.append({
            "note_id": moc_id,
            "title": f"Research: {topic}",
            "type": "moc",
            "path": str(moc_path.relative_to(vault.root)),
        })

        if not json_output:
            console.print(f"\n[bold green]Synthesis:[/] [[{moc_id}]]")

    # Output
    data = {
        "topic": topic,
        "provider": prov.name,
        "notes_created": created_notes,
        "total_fetched": pages_fetched,
        "depth": depth,
    }

    if json_output:
        output(success(data, count=len(created_notes), vault=str(vault.root)), json_mode=True)
    else:
        console.print(
            f"\n[bold]Done:[/] {len(created_notes)} notes created. "
            f"Start with: hyperresearch note show {created_notes[-1]['note_id']} -j"
        )


def _save_result(vault, conn, prov, result, tags, parent) -> dict | None:
    """Save a single WebResult as a note. Returns note data dict or None if skipped."""
    from hyperresearch.core.note import write_note

    url = result.url

    # Skip if already fetched
    existing = conn.execute("SELECT note_id FROM sources WHERE url = ?", (url,)).fetchone()
    if existing:
        return None

    title = result.title or urlparse(url).path.split("/")[-1] or "Untitled"
    domain = result.domain
    content_hash = hashlib.sha256(result.content.encode("utf-8")).hexdigest()[:16]

    extra_meta = {
        "source": url,
        "source_domain": domain,
        "fetched_at": result.fetched_at.isoformat(),
        "fetch_provider": prov.name,
    }

    note_path = write_note(
        vault.notes_dir,
        title=title,
        body=result.content,
        tags=tags,
        status="draft",
        source=url,
        parent=parent,
        extra_frontmatter=extra_meta,
    )

    note_id = note_path.stem
    conn.execute(
        """INSERT OR IGNORE INTO sources (url, note_id, domain, fetched_at, provider, content_hash)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (url, note_id, domain, result.fetched_at.isoformat(), prov.name, content_hash),
    )
    conn.commit()

    return {
        "note_id": note_id,
        "title": title,
        "url": url,
        "domain": domain,
        "path": str(note_path.relative_to(vault.root)),
        "word_count": len(result.content.split()),
        "summary": result.content[:120].replace("\n", " ").strip(),
    }


def _extract_links_from_results(results) -> list[str]:
    """Extract outbound HTTP links from result content."""
    urls = []
    url_re = re.compile(r'https?://[^\s<>\[\]"\']+')
    for r in results:
        for match in url_re.finditer(r.content):
            url = match.group(0).rstrip(".,;:)")
            # Skip common noise
            parsed = urlparse(url)
            if parsed.netloc and not any(
                skip in parsed.netloc
                for skip in ["google.com", "facebook.com", "twitter.com", "youtube.com"]
            ):
                urls.append(url)
    return list(dict.fromkeys(urls))  # Dedupe, preserve order
