"""Batch operations — modify multiple notes at once."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import typer

from hyperresearch.cli._output import console, output
from hyperresearch.models.output import error, success

VALID_STATUSES = {"draft", "review", "evergreen", "stale", "deprecated", "archive"}


def _discover_vault(json_output: bool):
    """Discover vault with proper error handling."""
    from hyperresearch.core.vault import Vault, VaultError
    try:
        return Vault.discover()
    except VaultError as e:
        if json_output:
            output(error(str(e), "NO_VAULT"), json_mode=True)
        else:
            console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)

app = typer.Typer()


def _get_matching_notes(vault, status=None, tag=None, parent=None, note_type=None) -> list[dict]:
    """Find notes matching the given filters."""
    clauses = ["n.type NOT IN ('index')"]
    params: list = []

    if status:
        clauses.append("n.status = ?")
        params.append(status)
    if tag:
        clauses.append("n.id IN (SELECT note_id FROM tags WHERE tag = ?)")
        params.append(tag.lower())
    if parent:
        clauses.append("(n.parent = ? OR n.parent LIKE ?)")
        params.append(parent)
        params.append(parent + "/%")
    if note_type:
        clauses.append("n.type = ?")
        params.append(note_type)

    where = " AND ".join(clauses)
    rows = vault.db.execute(
        f"SELECT n.id, n.path, n.title FROM notes n WHERE {where} ORDER BY n.title",
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def _batch_update_files(vault, notes: list[dict], updates: dict) -> tuple[list[str], list[dict]]:
    """Update frontmatter on multiple files. Returns (modified_ids, errors)."""
    modified = []
    errors = []
    for n in notes:
        try:
            _update_file_frontmatter(vault.root, n["path"], updates)
            modified.append(n["id"])
        except Exception as e:
            errors.append({"id": n["id"], "path": n["path"], "error": str(e)})
    # Sync after all modifications
    if modified:
        from hyperresearch.core.sync import compute_sync_plan, execute_sync
        plan = compute_sync_plan(vault, force=True)
        execute_sync(vault, plan)
    return modified, errors


def _update_file_frontmatter(vault_root: Path, rel_path: str, updates: dict) -> None:
    """Read a note file, patch its frontmatter, write it back."""
    from hyperresearch.core.frontmatter import parse_frontmatter, serialize_frontmatter

    file_path = vault_root / rel_path
    content = file_path.read_text(encoding="utf-8-sig")
    meta, body = parse_frontmatter(content)

    for key, value in updates.items():
        if key == "add_tag":
            if value.lower() not in meta.tags:
                meta.tags.append(value.lower())
        elif key == "remove_tag":
            meta.tags = [t for t in meta.tags if t != value.lower()]
        elif hasattr(meta, key):
            setattr(meta, key, value)

    meta.updated = datetime.now(UTC)
    new_content = serialize_frontmatter(meta) + "\n" + body
    file_path.write_text(new_content, encoding="utf-8")


# --- Tag operations ---

@app.command("tag-add")
def batch_tag_add(
    tag: str = typer.Argument(..., help="Tag to add"),
    status: str | None = typer.Option(None, "--status", "-s", help="Filter by status"),
    filter_tag: str | None = typer.Option(None, "--tag", "-t", help="Filter by existing tag"),
    parent: str | None = typer.Option(None, "--parent", "-p", help="Filter by parent topic"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview changes"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Add a tag to matching notes."""
    vault = _discover_vault(json_output)
    vault.auto_sync()
    notes = _get_matching_notes(vault, status=status, tag=filter_tag, parent=parent)

    if dry_run:
        data = {"action": "tag-add", "tag": tag, "would_modify": [n["id"] for n in notes]}
        if json_output:
            output(success(data, count=len(notes), vault=str(vault.root)), json_mode=True)
        else:
            console.print(f"[bold]Would add tag '{tag}' to {len(notes)} notes:[/]")
            for n in notes:
                console.print(f"  [cyan]{n['id']}[/] — {n['title']}")
        return

    for n in notes:
        _update_file_frontmatter(vault.root, n["path"], {"add_tag": tag})

    from hyperresearch.core.sync import compute_sync_plan, execute_sync
    plan = compute_sync_plan(vault, force=True)
    execute_sync(vault, plan)

    if json_output:
        output(success({"action": "tag-add", "tag": tag, "modified": [n["id"] for n in notes]},
                        count=len(notes), vault=str(vault.root)), json_mode=True)
    else:
        console.print(f"[green]Added tag '{tag}' to {len(notes)} notes.[/]")


@app.command("tag-remove")
def batch_tag_remove(
    tag: str = typer.Argument(..., help="Tag to remove"),
    status: str | None = typer.Option(None, "--status", "-s", help="Filter by status"),
    filter_tag: str | None = typer.Option(None, "--tag", "-t", help="Filter by existing tag"),
    parent: str | None = typer.Option(None, "--parent", "-p", help="Filter by parent topic"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview changes"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Remove a tag from matching notes."""
    vault = _discover_vault(json_output)
    vault.auto_sync()
    notes = _get_matching_notes(vault, status=status, tag=filter_tag or tag, parent=parent)

    if dry_run:
        data = {"action": "tag-remove", "tag": tag, "would_modify": [n["id"] for n in notes]}
        if json_output:
            output(success(data, count=len(notes), vault=str(vault.root)), json_mode=True)
        else:
            console.print(f"[bold]Would remove tag '{tag}' from {len(notes)} notes:[/]")
            for n in notes:
                console.print(f"  [cyan]{n['id']}[/] — {n['title']}")
        return

    for n in notes:
        _update_file_frontmatter(vault.root, n["path"], {"remove_tag": tag})

    from hyperresearch.core.sync import compute_sync_plan, execute_sync
    plan = compute_sync_plan(vault, force=True)
    execute_sync(vault, plan)

    if json_output:
        output(success({"action": "tag-remove", "tag": tag, "modified": [n["id"] for n in notes]},
                        count=len(notes), vault=str(vault.root)), json_mode=True)
    else:
        console.print(f"[green]Removed tag '{tag}' from {len(notes)} notes.[/]")


# --- Status operations ---

@app.command("set-status")
def batch_set_status(
    new_status: str = typer.Argument(..., help="New status: draft|review|evergreen|stale|deprecated|archive"),
    status: str | None = typer.Option(None, "--status", "-s", help="Filter by current status"),
    tag: str | None = typer.Option(None, "--tag", "-t", help="Filter by tag"),
    parent: str | None = typer.Option(None, "--parent", "-p", help="Filter by parent topic"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview changes"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Set status on matching notes."""
    if new_status not in VALID_STATUSES:
        msg = f"Invalid status '{new_status}'. Valid: {', '.join(sorted(VALID_STATUSES))}"
        if json_output:
            output(error(msg, "INVALID_STATUS"), json_mode=True)
        else:
            console.print(f"[red]{msg}[/]")
        raise typer.Exit(1)

    vault = _discover_vault(json_output)
    vault.auto_sync()
    notes = _get_matching_notes(vault, status=status, tag=tag, parent=parent)

    if dry_run:
        if json_output:
            output(success({"action": "set-status", "status": new_status,
                            "would_modify": [n["id"] for n in notes]},
                           count=len(notes), vault=str(vault.root)), json_mode=True)
        else:
            console.print(f"[bold]Would set status '{new_status}' on {len(notes)} notes.[/]")
        return

    for n in notes:
        _update_file_frontmatter(vault.root, n["path"], {"status": new_status})

    from hyperresearch.core.sync import compute_sync_plan, execute_sync
    plan = compute_sync_plan(vault, force=True)
    execute_sync(vault, plan)

    if json_output:
        output(success({"action": "set-status", "status": new_status,
                        "modified": [n["id"] for n in notes]},
                       count=len(notes), vault=str(vault.root)), json_mode=True)
    else:
        console.print(f"[green]Set status '{new_status}' on {len(notes)} notes.[/]")


# --- Deprecate ---

@app.command("deprecate")
def batch_deprecate(
    status: str | None = typer.Option(None, "--status", "-s", help="Filter by status"),
    tag: str | None = typer.Option(None, "--tag", "-t", help="Filter by tag"),
    parent: str | None = typer.Option(None, "--parent", "-p", help="Filter by parent topic"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview changes"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Mark matching notes as deprecated."""
    vault = _discover_vault(json_output)
    vault.auto_sync()
    notes = _get_matching_notes(vault, status=status, tag=tag, parent=parent)

    if dry_run:
        if json_output:
            output(success({"action": "deprecate",
                            "would_modify": [n["id"] for n in notes]},
                           count=len(notes), vault=str(vault.root)), json_mode=True)
        else:
            console.print(f"[bold]Would deprecate {len(notes)} notes.[/]")
        return

    updates = {"status": "deprecated", "deprecated": True}

    for n in notes:
        _update_file_frontmatter(vault.root, n["path"], updates)

    from hyperresearch.core.sync import compute_sync_plan, execute_sync
    plan = compute_sync_plan(vault, force=True)
    execute_sync(vault, plan)

    if json_output:
        output(success({"action": "deprecate", "modified": [n["id"] for n in notes]},
                       count=len(notes), vault=str(vault.root)), json_mode=True)
    else:
        console.print(f"[green]Deprecated {len(notes)} notes.[/]")


# --- Parent ---

@app.command("set-parent")
def batch_set_parent(
    new_parent: str = typer.Argument(..., help="New parent topic (e.g. ml/deep-learning)"),
    status: str | None = typer.Option(None, "--status", "-s", help="Filter by status"),
    tag: str | None = typer.Option(None, "--tag", "-t", help="Filter by tag"),
    parent: str | None = typer.Option(None, "--parent", "-p", help="Filter by current parent"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview changes"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Set parent topic on matching notes."""
    vault = _discover_vault(json_output)
    vault.auto_sync()
    notes = _get_matching_notes(vault, status=status, tag=tag, parent=parent)

    if dry_run:
        if json_output:
            output(success({"action": "set-parent", "parent": new_parent,
                            "would_modify": [n["id"] for n in notes]},
                           count=len(notes), vault=str(vault.root)), json_mode=True)
        else:
            console.print(f"[bold]Would set parent '{new_parent}' on {len(notes)} notes.[/]")
        return

    for n in notes:
        _update_file_frontmatter(vault.root, n["path"], {"parent": new_parent})

    from hyperresearch.core.sync import compute_sync_plan, execute_sync
    plan = compute_sync_plan(vault, force=True)
    execute_sync(vault, plan)

    if json_output:
        output(success({"action": "set-parent", "parent": new_parent,
                        "modified": [n["id"] for n in notes]},
                       count=len(notes), vault=str(vault.root)), json_mode=True)
    else:
        console.print(f"[green]Set parent '{new_parent}' on {len(notes)} notes.[/]")
