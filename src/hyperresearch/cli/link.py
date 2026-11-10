"""Link command — auto-discover and insert wiki-links between related notes."""

from __future__ import annotations

import typer
from rich.markup import escape

from hyperresearch.cli._output import console, output
from hyperresearch.models.output import error, success

app = typer.Typer()


@app.callback(invoke_without_command=True)
def link(
    ctx: typer.Context,
    auto: bool = typer.Option(False, "--auto", "-a", help="Auto-link all notes"),
    tag: str | None = typer.Option(None, "--tag", "-t", help="Only process notes with this tag"),
    note_ids: list[str] = typer.Option([], "--note", "-n", help="Only process specific notes"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what links would be added"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Auto-discover and insert wiki-links between related notes."""
    if ctx.invoked_subcommand is not None:
        return

    from hyperresearch.core.linker import auto_link
    from hyperresearch.core.sync import compute_sync_plan, execute_sync
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

    # Determine which notes to process. None means every note; a --note/--tag
    # selection is resolved to the notes it matches, so one that matches none
    # links nothing and says so.
    ids_to_process: list[str] | None = None
    selection = ""
    if note_ids:
        placeholders = ",".join("?" for _ in note_ids)
        rows = vault.db.execute(
            f"SELECT id FROM notes WHERE id IN ({placeholders})", list(note_ids)
        ).fetchall()
        ids_to_process = [r["id"] for r in rows]
        selection = f"--note {', '.join(note_ids)}"
    elif tag:
        rows = vault.db.execute(
            "SELECT note_id FROM tags WHERE tag = ?", (tag.lower(),)
        ).fetchall()
        ids_to_process = [r["note_id"] for r in rows]
        selection = f"--tag {tag}"

    if not auto and ids_to_process is None:
        if json_output:
            output(error("Use --auto to link all notes, or --note/--tag to filter", "NO_INPUT"), json_mode=True)
        else:
            console.print("[yellow]Use --auto to link all notes, or --note/--tag to filter.[/]")
        raise typer.Exit(1)

    report = auto_link(vault, ids_to_process, dry_run=dry_run)

    # Sync to pick up the modified files
    if report and not dry_run:
        plan = compute_sync_plan(vault)
        if plan.to_add or plan.to_update:
            execute_sync(vault, plan)

    total_links = sum(len(v) for v in report.values())
    data = {
        "links_added": report,
        "notes_modified": len(report),
        "total_links": total_links,
        "dry_run": dry_run,
    }
    no_match = ids_to_process == []
    if no_match:
        data["message"] = f"No notes match {selection}; nothing linked."

    if json_output:
        output(success(data, vault=str(vault.root)), json_mode=True)
    else:
        if no_match:
            console.print(f"[yellow]{escape(data['message'])}[/]")
        elif report:
            for nid, linked in report.items():
                console.print(f"  [green]+[/] {nid} → {', '.join(linked)}")
            verb = "would be added" if dry_run else "added"
            console.print(f"\n[bold]{total_links} links {verb} across {len(report)} notes.[/]")
        else:
            console.print("[dim]No new links found.[/]")
