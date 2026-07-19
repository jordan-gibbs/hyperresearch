"""Sources command — list and manage fetched web sources."""

from __future__ import annotations

import typer

from hyperresearch.cli._output import console, output
from hyperresearch.models.output import error, success

app = typer.Typer()


@app.command("list")
def source_list(
    domain: str | None = typer.Option(None, "--domain", help="Filter by domain"),
    limit: int = typer.Option(50, "--limit", "-n", help="Max results"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """List all fetched web sources."""
    from hyperresearch.core.vault import Vault, VaultError

    try:
        vault = Vault.discover()
    except VaultError as e:
        if json_output:
            output(error(str(e), "NO_VAULT"), json_mode=True)
        else:
            console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)

    conn = vault.db

    if domain:
        rows = conn.execute(
            "SELECT url, note_id, domain, fetched_at, provider, status "
            "FROM sources WHERE domain = ? ORDER BY fetched_at DESC LIMIT ?",
            (domain, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT url, note_id, domain, fetched_at, provider, status "
            "FROM sources ORDER BY fetched_at DESC LIMIT ?",
            (limit,),
        ).fetchall()

    sources = [dict(row) for row in rows]

    if json_output:
        output(success(sources, count=len(sources), vault=str(vault.root)), json_mode=True)
    else:
        if not sources:
            console.print("[dim]No sources fetched yet. Use 'hyperresearch fetch <url>' to start.[/]")
            return
        for s in sources:
            status_color = "green" if s["status"] == "active" else "red"
            console.print(
                f"[{status_color}]{s['status']}[/] {s['url']}"
                f" → [cyan]{s['note_id'] or '(deleted)'}[/]"
                f" [dim]({s['provider']}, {s['fetched_at']})[/]"
            )
        console.print(f"\n[dim]{len(sources)} sources[/]")


@app.command("check")
def source_check(
    url: str = typer.Argument(..., help="URL to check"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Check if a URL has already been fetched."""
    from hyperresearch.core.vault import Vault, VaultError

    try:
        vault = Vault.discover()
    except VaultError as e:
        if json_output:
            output(error(str(e), "NO_VAULT"), json_mode=True)
        else:
            console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)

    row = vault.db.execute(
        "SELECT url, note_id, domain, fetched_at, provider FROM sources WHERE url = ?",
        (url,),
    ).fetchone()

    if row:
        data = {"exists": True, **dict(row)}
        if json_output:
            output(success(data, vault=str(vault.root)), json_mode=True)
        else:
            console.print(f"[green]Found:[/] {url} → note '{row['note_id']}'")
    else:
        data = {"exists": False, "url": url}
        if json_output:
            output(success(data, vault=str(vault.root)), json_mode=True)
        else:
            console.print(f"[dim]Not fetched:[/] {url}")


@app.command("score")
def sources_score(
    tag: str | None = typer.Option(None, "--tag", "-t", help="Only notes with this tag (e.g. vault_tag)"),
    fresh: bool = typer.Option(False, "--fresh", help="Bypass the api_cache TTL and re-check already-enriched notes"),
    limit: int | None = typer.Option(None, "--limit", "-n", help="Max notes to enrich this run"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Enrich DOI-bearing notes with citation metadata (OpenAlex/Semantic Scholar).

    Populates citation_count / venue / is_retracted in frontmatter + DB, then
    recomputes authority percentiles and composite quality scores. Responses
    are cached in the api_cache table ([ranking] api_cache_ttl_days).
    """
    from hyperresearch.core.scholar import score_sources
    from hyperresearch.core.vault import Vault, VaultError

    try:
        vault = Vault.discover()
    except VaultError as e:
        if json_output:
            output(error(str(e), "NO_VAULT"), json_mode=True)
        else:
            console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)

    vault.auto_sync()
    result = score_sources(vault, tag=tag, fresh=fresh, limit=limit)

    if json_output:
        output(success(result, vault=str(vault.root)), json_mode=True)
    else:
        console.print(f"[green]Scored:[/] {result['scored']} notes enriched")
        console.print(f"  Authority percentiles ranked: {result['authority_ranked']}")
        if result["retracted"]:
            console.print(f"  [red]RETRACTED:[/] {', '.join(result['retracted'])}")
        if result["missing"]:
            console.print(f"  [yellow]No metadata found:[/] {len(result['missing'])} notes")


@app.command("backfill-doi")
def sources_backfill_doi(
    tag: str | None = typer.Option(None, "--tag", "-t", help="Only notes with this tag"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Extract DOIs from existing notes' source URLs and bodies (back-catalog)."""
    from hyperresearch.core.scholar import backfill_dois
    from hyperresearch.core.vault import Vault, VaultError

    try:
        vault = Vault.discover()
    except VaultError as e:
        if json_output:
            output(error(str(e), "NO_VAULT"), json_mode=True)
        else:
            console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)

    vault.auto_sync()
    gained = backfill_dois(vault, tag=tag)

    if json_output:
        output(success({"dois_added": gained}, vault=str(vault.root)), json_mode=True)
    else:
        console.print(f"[green]DOIs added:[/] {gained} notes")


@app.command("retractions")
def sources_retractions(
    tag: str | None = typer.Option(None, "--tag", "-t", help="Only notes with this tag"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Ship-time retraction sweep: re-check every DOI-bearing note fresh.

    Bypasses the api_cache TTL so a retraction published yesterday is caught
    today. Run before the step-15 integrity gate; the `retracted-citations`
    lint rule then blocks any unacknowledged retracted citation.
    """
    from hyperresearch.core.scholar import score_sources
    from hyperresearch.core.vault import Vault, VaultError

    try:
        vault = Vault.discover()
    except VaultError as e:
        if json_output:
            output(error(str(e), "NO_VAULT"), json_mode=True)
        else:
            console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)

    vault.auto_sync()
    result = score_sources(vault, tag=tag, fresh=True)

    data = {"checked": result["scored"], "retracted": result["retracted"], "unresolved": len(result["missing"])}
    if json_output:
        output(success(data, vault=str(vault.root)), json_mode=True)
    else:
        console.print(f"[green]Retraction sweep:[/] {data['checked']} DOI-bearing notes re-checked")
        if data["retracted"]:
            console.print(f"  [red]RETRACTED:[/] {', '.join(data['retracted'])}")
        else:
            console.print("  no retractions found")


@app.command("independence")
def sources_independence(
    tag: str | None = typer.Option(None, "--tag", "-t", help="Only notes with this tag"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Cluster derivative sources and score independence.

    Five syndicated copies of one press release should count as ONE voice in
    consensus math, not five. Clusters via canonical-URL identity, near-
    duplicate bodies (MinHash), and shared wire-service boilerplate; writes
    notes.independence (root 1.0, members 1/cluster_size).
    """
    from hyperresearch.core.independence import compute_independence
    from hyperresearch.core.vault import Vault, VaultError

    try:
        vault = Vault.discover()
    except VaultError as e:
        if json_output:
            output(error(str(e), "NO_VAULT"), json_mode=True)
        else:
            console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)

    vault.auto_sync()
    result = compute_independence(vault, tag=tag)

    if json_output:
        output(success(result, count=len(result["clusters"]), vault=str(vault.root)), json_mode=True)
    else:
        console.print(
            f"[green]Independence:[/] {result['scored']} notes scored, "
            f"{len(result['clusters'])} derivative cluster(s)"
        )
        for c in result["clusters"]:
            console.print(f"  [{c['kind']}] root [cyan]{c['root']}[/] <- {', '.join(c['members'])}")
