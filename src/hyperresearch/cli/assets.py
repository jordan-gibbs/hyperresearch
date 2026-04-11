"""Assets CLI — list and view downloaded images, screenshots, and other media."""

from __future__ import annotations

import typer

from hyperresearch.cli._output import console, output
from hyperresearch.models.output import error, success

app = typer.Typer()


@app.command("list")
def assets_list(
    note_id: str | None = typer.Option(None, "--note", "-n", help="Filter by note ID"),
    asset_type: str | None = typer.Option(None, "--type", "-t", help="Filter by type: image|screenshot|pdf"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """List downloaded assets (images, screenshots, PDFs)."""
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
    conn = vault.db

    query = "SELECT * FROM assets WHERE 1=1"
    params: list = []
    if note_id:
        query += " AND note_id = ?"
        params.append(note_id)
    if asset_type:
        query += " AND type = ?"
        params.append(asset_type)
    query += " ORDER BY created_at DESC"

    rows = conn.execute(query, params).fetchall()
    assets = [
        {
            "id": row["id"],
            "note_id": row["note_id"],
            "type": row["type"],
            "filename": row["filename"],
            "url": row["url"],
            "alt_text": row["alt_text"],
            "content_type": row["content_type"],
            "size_bytes": row["size_bytes"],
        }
        for row in rows
    ]

    if json_output:
        output(success(assets, count=len(assets), vault=str(vault.root)), json_mode=True)
    else:
        if not assets:
            console.print("[dim]No assets found.[/]")
            return
        for a in assets:
            size = f"{a['size_bytes'] / 1024:.0f}KB" if a["size_bytes"] else "?"
            alt = f" — {a['alt_text'][:60]}" if a["alt_text"] else ""
            console.print(
                f"  [{a['type']}] {a['note_id']}: {a['filename']} ({size}){alt}"
            )
        console.print(f"\n[dim]{len(assets)} assets total[/]")


@app.command("path")
def asset_path(
    note_id: str = typer.Argument(..., help="Note ID"),
    asset_type: str = typer.Option("screenshot", "--type", "-t", help="Asset type: screenshot|image"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Get the file path for a note's asset (for viewing with Read tool)."""
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
    rows = conn.execute(
        "SELECT filename, alt_text, size_bytes FROM assets WHERE note_id = ? AND type = ? ORDER BY id",
        (note_id, asset_type),
    ).fetchall()

    if not rows:
        if json_output:
            output(error(f"No {asset_type} assets for note '{note_id}'", "NOT_FOUND"), json_mode=True)
        else:
            console.print(f"[yellow]No {asset_type} assets for note '{note_id}'[/]")
        raise typer.Exit(1)

    paths = [
        {"path": row["filename"], "alt_text": row["alt_text"], "size_bytes": row["size_bytes"]}
        for row in rows
    ]

    if json_output:
        output(success(paths, count=len(paths), vault=str(vault.root)), json_mode=True)
    else:
        for p in paths:
            console.print(p["path"])
