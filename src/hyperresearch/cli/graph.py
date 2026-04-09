"""Knowledge graph CLI commands."""

from __future__ import annotations

import typer

from hyperresearch.cli._output import console, output
from hyperresearch.models.output import success

app = typer.Typer()


@app.command("backlinks")
def graph_backlinks(
    note_id: str = typer.Argument(..., help="Note ID"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Show what links TO this note."""
    from hyperresearch.core.vault import Vault

    vault = Vault.discover()
    vault.auto_sync()

    rows = vault.db.execute(
        """
        SELECT l.source_id, n.title as source_title, n.path as source_path,
               l.line_number, l.context
        FROM links l
        JOIN notes n ON l.source_id = n.id
        WHERE l.target_id = ?
        ORDER BY n.title
        """,
        (note_id,),
    ).fetchall()

    backlinks = [
        {
            "source_id": r["source_id"],
            "source_title": r["source_title"],
            "source_path": r["source_path"],
            "line_number": r["line_number"],
            "context": r["context"],
        }
        for r in rows
    ]

    if json_output:
        output(
            success({"note_id": note_id, "backlinks": backlinks}, count=len(backlinks), vault=str(vault.root)),
            json_mode=True,
        )
    else:
        if not backlinks:
            console.print(f"[dim]No backlinks to {note_id}[/]")
            return
        console.print(f"[bold]Backlinks to {note_id}:[/]")
        for bl in backlinks:
            console.print(
                f"  [cyan]{bl['source_id']}[/] — {bl['source_title']} "
                f"[dim](line {bl['line_number']})[/]"
            )


@app.command("outlinks")
def graph_outlinks(
    note_id: str = typer.Argument(..., help="Note ID"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Show what this note links TO."""
    from hyperresearch.core.vault import Vault

    vault = Vault.discover()
    vault.auto_sync()

    rows = vault.db.execute(
        """
        SELECT l.target_ref, l.target_id, n.title as target_title,
               l.line_number, l.context
        FROM links l
        LEFT JOIN notes n ON l.target_id = n.id
        WHERE l.source_id = ?
        ORDER BY l.line_number
        """,
        (note_id,),
    ).fetchall()

    outlinks = [
        {
            "target_ref": r["target_ref"],
            "target_id": r["target_id"],
            "target_title": r["target_title"],
            "line_number": r["line_number"],
            "resolved": r["target_id"] is not None,
        }
        for r in rows
    ]

    if json_output:
        output(
            success({"note_id": note_id, "outlinks": outlinks}, count=len(outlinks), vault=str(vault.root)),
            json_mode=True,
        )
    else:
        if not outlinks:
            console.print(f"[dim]No outgoing links from {note_id}[/]")
            return
        console.print(f"[bold]Links from {note_id}:[/]")
        for ol in outlinks:
            status = "[green]OK[/]" if ol["resolved"] else "[red]BROKEN[/]"
            title = ol.get("target_title") or ol["target_ref"]
            console.print(f"  {status} [[{ol['target_ref']}]] → {title}")


@app.command("orphans")
def graph_orphans(
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Find notes with no inbound or outbound links."""
    from hyperresearch.core.vault import Vault

    vault = Vault.discover()
    vault.auto_sync()

    rows = vault.db.execute("""
        SELECT n.id, n.title, n.path, n.status
        FROM notes n
        WHERE n.type NOT IN ('index', 'raw')
          AND n.id NOT IN (SELECT DISTINCT target_id FROM links WHERE target_id IS NOT NULL)
          AND n.id NOT IN (SELECT DISTINCT source_id FROM links)
        ORDER BY n.title
    """).fetchall()

    orphans = [{"id": r["id"], "title": r["title"], "path": r["path"], "status": r["status"]} for r in rows]

    if json_output:
        output(success(orphans, count=len(orphans), vault=str(vault.root)), json_mode=True)
    else:
        if not orphans:
            console.print("[green]No orphan notes.[/]")
            return
        console.print(f"[bold]Orphan notes ({len(orphans)}):[/]")
        for o in orphans:
            console.print(f"  [cyan]{o['id']}[/] — {o['title']}")


@app.command("broken")
def graph_broken(
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Find broken [[links]] that don't resolve."""
    from hyperresearch.core.vault import Vault

    vault = Vault.discover()
    vault.auto_sync()

    rows = vault.db.execute("""
        SELECT l.source_id, n.title as source_title, l.target_ref, l.line_number
        FROM links l
        JOIN notes n ON l.source_id = n.id
        WHERE l.target_id IS NULL
        ORDER BY n.title, l.line_number
    """).fetchall()

    broken = [
        {
            "source_id": r["source_id"],
            "source_title": r["source_title"],
            "target_ref": r["target_ref"],
            "line_number": r["line_number"],
        }
        for r in rows
    ]

    if json_output:
        output(success(broken, count=len(broken), vault=str(vault.root)), json_mode=True)
    else:
        if not broken:
            console.print("[green]No broken links.[/]")
            return
        console.print(f"[bold red]Broken links ({len(broken)}):[/]")
        for b in broken:
            console.print(
                f"  [cyan]{b['source_id']}[/] line {b['line_number']}: "
                f"[[{b['target_ref']}]]"
            )


@app.command("stub")
def graph_stub(
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview what would be created"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Create stub notes for all broken [[links]]."""
    from hyperresearch.core.note import write_note
    from hyperresearch.core.vault import Vault

    vault = Vault.discover()
    vault.auto_sync()

    rows = vault.db.execute(
        "SELECT DISTINCT l.target_ref FROM links l WHERE l.target_id IS NULL ORDER BY l.target_ref"
    ).fetchall()

    targets = [r["target_ref"] for r in rows]

    if not targets:
        if json_output:
            output(success({"stubbed": [], "count": 0}, vault=str(vault.root)), json_mode=True)
        else:
            console.print("[green]No broken links to stub.[/]")
        return

    if dry_run:
        if json_output:
            output(success({"would_stub": targets, "count": len(targets)}, vault=str(vault.root)), json_mode=True)
        else:
            console.print(f"[bold]Would create {len(targets)} stub notes:[/]")
            for t in targets:
                console.print(f"  [cyan]{t}[/]")
        return

    created = []
    for target in targets:
        # Create a minimal stub note
        title = target.replace("-", " ").replace("_", " ").title()
        path = write_note(
            vault.notes_dir,
            title,
            body=f"# {title}\n\n*Stub — created to resolve a broken link. Expand this note.*\n",
            note_id=target,
            status="draft",
            summary=f"Stub for [[{target}]]",
        )
        created.append({"id": target, "title": title, "path": path.relative_to(vault.root).as_posix()})

    # Sync to resolve the links
    from hyperresearch.core.sync import compute_sync_plan, execute_sync
    plan = compute_sync_plan(vault)
    execute_sync(vault, plan)

    if json_output:
        output(success({"stubbed": created, "count": len(created)}, vault=str(vault.root)), json_mode=True)
    else:
        console.print(f"[green]Created {len(created)} stub notes:[/]")
        for c in created:
            console.print(f"  [cyan]{c['id']}[/] — {c['title']}")


@app.command("hubs")
def graph_hubs(
    limit: int = typer.Option(20, "--limit", "-l", help="Max results"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Show most-linked-to notes."""
    from hyperresearch.core.vault import Vault

    vault = Vault.discover()
    vault.auto_sync()

    rows = vault.db.execute(
        """
        SELECT l.target_id, n.title, COUNT(*) as inbound
        FROM links l
        JOIN notes n ON l.target_id = n.id
        WHERE l.target_id IS NOT NULL
        GROUP BY l.target_id
        ORDER BY inbound DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    hubs = [{"id": r["target_id"], "title": r["title"], "inbound_links": r["inbound"]} for r in rows]

    if json_output:
        output(success(hubs, count=len(hubs), vault=str(vault.root)), json_mode=True)
    else:
        from rich.table import Table

        table = Table(title="Hub Notes", show_header=True, header_style="bold")
        table.add_column("ID", style="cyan")
        table.add_column("Title")
        table.add_column("Inbound Links", justify="right", style="green")
        for h in hubs:
            table.add_row(h["id"], h["title"], str(h["inbound_links"]))
        console.print(table)
