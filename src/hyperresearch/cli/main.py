"""Root-level commands: init, status, sync."""

from __future__ import annotations

from pathlib import Path

import typer

from hyperresearch.cli._output import console, output, print_vault_status
from hyperresearch.models.output import error, success

app = typer.Typer()


@app.command()
def init(
    path: str = typer.Argument(".", help="Path to initialize vault in"),
    name: str = typer.Option("Research Base", "--name", "-n", help="Vault name"),
    research_dir: str = typer.Option("research", "--dir", "-d", help="Research directory name"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Initialize a new hyperresearch vault (Claude Code integration)."""
    from hyperresearch.core.vault import Vault, VaultError

    try:
        vault = Vault.init(Path(path).resolve(), name=name, research_dir=research_dir)
        data = {"vault_path": str(vault.root), "name": name}
        if json_output:
            output(success(data), json_mode=True)
        else:
            console.print(f"[green]Initialized vault:[/] {vault.root}")
    except VaultError as e:
        if json_output:
            output(error(str(e), "VAULT_EXISTS"), json_mode=True)
        else:
            console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)


@app.command()
def status(
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Show vault health and statistics."""
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

    # Gather stats
    total = conn.execute("SELECT COUNT(*) as c FROM notes").fetchone()["c"]
    by_status = {}
    for row in conn.execute("SELECT status, COUNT(*) as c FROM notes GROUP BY status"):
        by_status[row["status"]] = row["c"]
    by_type = {}
    for row in conn.execute("SELECT type, COUNT(*) as c FROM notes GROUP BY type"):
        by_type[row["type"]] = row["c"]

    tag_count = conn.execute("SELECT COUNT(DISTINCT tag) as c FROM tags").fetchone()["c"]
    top_tags = []
    for row in conn.execute(
        "SELECT tag, COUNT(*) as c FROM tags GROUP BY tag ORDER BY c DESC LIMIT 10"
    ):
        top_tags.append({"tag": row["tag"], "count": row["c"]})

    total_links = conn.execute("SELECT COUNT(*) as c FROM links").fetchone()["c"]
    broken = conn.execute(
        "SELECT COUNT(*) as c FROM links WHERE target_id IS NULL"
    ).fetchone()["c"]
    orphans = conn.execute("""
        SELECT COUNT(*) as c FROM notes n
        WHERE n.type NOT IN ('index', 'raw')
          AND n.id NOT IN (SELECT DISTINCT target_id FROM links WHERE target_id IS NOT NULL)
          AND n.id NOT IN (SELECT DISTINCT source_id FROM links)
    """).fetchone()["c"]

    total_words = conn.execute(
        "SELECT COALESCE(SUM(word_count), 0) as c FROM notes"
    ).fetchone()["c"]

    last_sync = conn.execute(
        "SELECT value FROM _meta WHERE key = 'last_sync'"
    ).fetchone()
    last_sync_val = last_sync["value"] if last_sync else "never"

    data = {
        "vault_name": vault.config.name,
        "vault_path": str(vault.root),
        "notes": {"total": total, "by_status": by_status, "by_type": by_type},
        "tags": {"total_unique": tag_count, "top": top_tags},
        "graph": {"total_links": total_links, "broken_links": broken, "orphan_notes": orphans},
        "total_words": total_words,
        "last_sync": last_sync_val,
    }

    if json_output:
        output(success(data, vault=str(vault.root)), json_mode=True)
    else:
        print_vault_status(data)


@app.command()
def sync(
    force: bool = typer.Option(False, "--force", "-f", help="Full rescan ignoring mtime/hash"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would change"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Sync database with markdown files on disk."""
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

    plan = compute_sync_plan(vault, force=force)

    if dry_run:
        data = {
            "to_add": [str(p.relative_to(vault.root)) for p in plan.to_add],
            "to_update": [str(p.relative_to(vault.root)) for p in plan.to_update],
            "to_delete": plan.to_delete,
            "unchanged": plan.unchanged,
        }
        if json_output:
            output(success(data, vault=str(vault.root)), json_mode=True)
        else:
            console.print("[bold]Sync plan:[/]")
            console.print(f"  Add: {len(plan.to_add)}")
            console.print(f"  Update: {len(plan.to_update)}")
            console.print(f"  Delete: {len(plan.to_delete)}")
            console.print(f"  Unchanged: {plan.unchanged}")
        return

    result = execute_sync(vault, plan)
    data = {
        "added": result.added,
        "updated": result.updated,
        "deleted": result.deleted,
        "unchanged": result.unchanged,
        "errors": result.errors,
        "duration_ms": round(result.duration_ms, 1),
    }

    if json_output:
        output(success(data, vault=str(vault.root)), json_mode=True)
    else:
        console.print(
            f"[green]Synced:[/] +{result.added} ~{result.updated} "
            f"-{result.deleted} ={result.unchanged} "
            f"({result.duration_ms:.0f}ms)"
        )
        if result.errors:
            for err in result.errors:
                console.print(f"  [red]Error:[/] {err['path']}: {err['error']}")
