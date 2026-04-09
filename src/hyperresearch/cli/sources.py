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
