"""Batch fetch — fetch multiple URLs in one command with batched sync."""

from __future__ import annotations

import hashlib
import sys
from urllib.parse import urlparse

import typer

from hyperresearch.cli._output import console, output
from hyperresearch.models.output import error, success


def fetch_batch(
    urls: list[str] = typer.Argument(None, help="URLs to fetch"),
    stdin: bool = typer.Option(False, "--stdin", help="Read URLs from stdin (one per line)"),
    tags: list[str] = typer.Option([], "--tag", "-t", help="Tags for all notes"),
    parent: str | None = typer.Option(None, "--parent", "-p", help="Parent topic"),
    provider_name: str | None = typer.Option(None, "--provider", help="Web provider override"),
    save_assets: bool = typer.Option(False, "--save-assets", "-a", help="Download images and screenshots"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Fetch multiple URLs and save each as a research note. Batched sync for speed."""
    from hyperresearch.core.enrich import enrich_note_file
    from hyperresearch.core.note import write_note
    from hyperresearch.core.sync import compute_sync_plan, execute_sync
    from hyperresearch.core.vault import Vault, VaultError
    from hyperresearch.web.base import get_provider

    # Collect URLs from args and/or stdin
    all_urls = list(urls or [])
    if stdin:
        for line in sys.stdin:
            line = line.strip()
            if line and line.startswith("http"):
                all_urls.append(line)

    if not all_urls:
        if json_output:
            output(error("No URLs provided", "NO_INPUT"), json_mode=True)
        else:
            console.print("[red]No URLs provided.[/] Pass URLs as arguments or use --stdin.")
        raise typer.Exit(1)

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

    _auth_aggressive = (
        "linkedin.com", "twitter.com", "x.com", "facebook.com",
        "instagram.com", "tiktok.com",
    )

    def _needs_visible(fetch_url: str) -> bool:
        if not vault.config.web_profile:
            return False
        domain = urlparse(fetch_url).netloc.lower()
        return any(d in domain for d in _auth_aggressive)

    prov = get_provider(
        provider_name or vault.config.web_provider,
        profile=vault.config.web_profile,
        magic=vault.config.web_magic,
    )

    # Filter out already-fetched URLs
    new_urls = []
    for url in all_urls:
        existing = conn.execute("SELECT note_id FROM sources WHERE url = ?", (url,)).fetchone()
        if existing:
            if not json_output:
                console.print(f"  [dim]Skip:[/] {url} (already fetched as {existing['note_id']})")
        else:
            new_urls.append(url)

    if not new_urls:
        if json_output:
            output(success({"notes_created": [], "skipped": len(all_urls)}, vault=str(vault.root)), json_mode=True)
        else:
            console.print("[dim]All URLs already fetched.[/]")
        return

    if not json_output:
        console.print(f"[bold]Fetching {len(new_urls)} URLs with {prov.name}...[/]")

    # Split URLs into normal (headless batch) and auth-aggressive (visible, sequential)
    normal_urls = [u for u in new_urls if not _needs_visible(u)]
    visible_urls = [u for u in new_urls if _needs_visible(u)]

    results = []

    # Batch fetch normal URLs
    if normal_urls:
        if hasattr(prov, "fetch_many"):
            try:
                results.extend(prov.fetch_many(normal_urls))
            except Exception as e:
                if not json_output:
                    console.print(f"[red]Batch fetch failed:[/] {e}")
        else:
            for url in normal_urls:
                try:
                    results.append(prov.fetch(url))
                except Exception as e:
                    if not json_output:
                        console.print(f"  [red]Failed:[/] {url} — {e}")

    # Fetch auth-aggressive URLs with visible browser (sequential)
    if visible_urls:
        visible_prov = get_provider(
            provider_name or vault.config.web_provider,
            profile=vault.config.web_profile,
            magic=vault.config.web_magic,
            headless=False,
        )
        for url in visible_urls:
            try:
                results.append(visible_prov.fetch(url))
            except Exception as e:
                if not json_output:
                    console.print(f"  [red]Failed (visible):[/] {url} — {e}")

    # Phase 1: Write all note files to disk (no sync yet)
    note_files = []  # (note_path, url, result, domain, content_hash)
    for result in results:
        url = result.url

        # Skip login redirects
        if result.looks_like_login_wall(url):
            if not json_output:
                console.print(
                    f"  [yellow]Auth required:[/] {url} — login page detected, skipping. "
                    "Run 'hyperresearch setup' to create a login profile."
                )
            continue

        title = result.title or urlparse(url).path.split("/")[-1] or "Untitled"
        domain = result.domain

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

        # Auto-enrich before sync
        enrich_note_file(note_path, conn, tags)

        content_hash = hashlib.sha256(result.content.encode("utf-8")).hexdigest()[:16]
        note_files.append((note_path, url, result, domain, content_hash))

        if not json_output:
            console.print(f"  [green]+[/] {title}")

    # Phase 2: ONE sync to index all notes
    plan = compute_sync_plan(vault)
    if plan.to_add or plan.to_update:
        execute_sync(vault, plan)

    # Phase 3: Bulk-insert source records
    created_notes = []
    for note_path, url, result, domain, content_hash in note_files:
        note_id = note_path.stem
        conn.execute(
            """INSERT OR IGNORE INTO sources (url, note_id, domain, fetched_at, provider, content_hash)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (url, note_id, domain, result.fetched_at.isoformat(), prov.name, content_hash),
        )

        # Save assets if requested
        if save_assets:
            from hyperresearch.cli.fetch import _save_assets

            assets_dir = vault.root / "research" / "assets" / note_id
            _save_assets(conn, result, note_id, assets_dir)

        created_notes.append({
            "note_id": note_id,
            "title": result.title or "Untitled",
            "url": url,
            "domain": domain,
            "word_count": len(result.content.split()),
        })

    conn.commit()

    # Phase 4: Auto-link across all new notes
    if created_notes:
        from hyperresearch.core.linker import auto_link

        note_ids = [n["note_id"] for n in created_notes]
        link_report = auto_link(vault, note_ids)
        if link_report:
            plan = compute_sync_plan(vault)
            if plan.to_add or plan.to_update:
                execute_sync(vault, plan)

    data = {
        "notes_created": created_notes,
        "total_fetched": len(created_notes),
        "skipped": len(all_urls) - len(new_urls),
    }

    if json_output:
        output(success(data, count=len(created_notes), vault=str(vault.root)), json_mode=True)
    else:
        console.print(
            f"\n[bold]Done:[/] {len(created_notes)} notes created, "
            f"{len(all_urls) - len(new_urls)} skipped (already fetched)."
        )
