"""Note CRUD CLI commands."""

from __future__ import annotations

from datetime import UTC

import typer

from hyperresearch.cli._output import console, output, print_note_summary
from hyperresearch.models.output import error, success

app = typer.Typer()


@app.command("new")
def note_new(
    title: str = typer.Argument(..., help="Note title"),
    body_text: str | None = typer.Option(None, "--body", "-b", help="Note body content (markdown)"),
    body_file: str | None = typer.Option(None, "--body-file", "-B", help="Read body from file path"),
    body_stdin: bool = typer.Option(False, "--body-stdin", help="Read body from stdin"),
    tags: list[str] = typer.Option([], "--tag", "-t", help="Tags"),
    parent: str | None = typer.Option(None, "--parent", "-p", help="Parent topic"),
    note_type: str = typer.Option("note", "--type", help="Note type"),
    status: str = typer.Option("draft", "--status", "-s", help="Initial status"),
    summary: str | None = typer.Option(None, "--summary", help="One-line summary"),
    source: str | None = typer.Option(None, "--source", help="Source URL or path"),
    tier: str | None = typer.Option(None, "--tier", help="Epistemic tier: ground_truth|institutional|practitioner|commentary|unknown"),
    content_type: str | None = typer.Option(None, "--content-type", help="Artifact kind: paper|docs|article|blog|forum|dataset|policy|code|book|transcript|review|unknown"),
    template: str | None = typer.Option(None, "--template", "-T", help="Template: note|concept|reference|guide|comparison|moc"),
    edit: bool = typer.Option(False, "--edit", "-e", help="Open in $EDITOR"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Create a new note.

    Body content: use --body for short text, --body-file for longer content
    (avoids shell escaping), or --body-stdin to pipe it in.
    """
    import sys
    from pathlib import Path as P

    from hyperresearch.core.note import write_note
    from hyperresearch.core.vault import Vault
    from hyperresearch.models.note import ContentType, Tier, slugify

    # Validate enums up-front so invalid values fail clearly
    if tier is not None:
        try:
            Tier(tier)
        except ValueError:
            valid = ", ".join(t.value for t in Tier)
            if json_output:
                output(error(f"Invalid --tier '{tier}'. Must be one of: {valid}", "INVALID_TIER"), json_mode=True)
            else:
                console.print(f"[red]Invalid --tier '{tier}'.[/] Must be one of: {valid}")
            raise typer.Exit(1)
    if content_type is not None:
        try:
            ContentType(content_type)
        except ValueError:
            valid = ", ".join(c.value for c in ContentType)
            if json_output:
                output(error(f"Invalid --content-type '{content_type}'. Must be one of: {valid}", "INVALID_CONTENT_TYPE"), json_mode=True)
            else:
                console.print(f"[red]Invalid --content-type '{content_type}'.[/] Must be one of: {valid}")
            raise typer.Exit(1)

    vault = Vault.discover()
    vault.auto_sync()

    # Determine body content
    if body_file:
        body = P(body_file).read_text(encoding="utf-8")
    elif body_stdin:
        body = sys.stdin.read()
    elif body_text:
        body = body_text
    else:
        body = f"# {title}\n\n"

    nid = slugify(title)

    # Check for duplicate before creating
    similar = vault.db.execute(
        "SELECT id, title FROM notes WHERE id = ? OR LOWER(title) = LOWER(?)",
        (nid, title),
    ).fetchall()
    if similar:
        existing = [{"id": r["id"], "title": r["title"]} for r in similar]
        if json_output:
            # Warn but still create — agent can decide
            pass  # Will include warning in response below
        else:
            for s in existing:
                console.print(f"[yellow]Similar note exists:[/] {s['id']} — {s['title']}")

    # Use template if specified
    if template:
        from hyperresearch.core.templates import get_template, render_template

        tpl = get_template(template, vault.templates_dir)
        if tpl:
            rendered = render_template(tpl, title, nid, tags)
            target_dir = vault.notes_dir
            if parent:
                target_dir = target_dir / slugify(parent)
            target_dir.mkdir(parents=True, exist_ok=True)
            file_path = target_dir / f"{nid}.md"
            counter = 2
            while file_path.exists():
                file_path = target_dir / f"{nid}-{counter}.md"
                nid = f"{nid}-{counter}"
                counter += 1
            file_path.write_text(rendered, encoding="utf-8")
            path = file_path
        else:
            console.print(f"[yellow]Template '{template}' not found, using default.[/]")
            path = write_note(vault.notes_dir, title, body=body, tags=tags, status=status,
                              note_type=note_type, parent=parent, summary=summary,
                              source=source, tier=tier, content_type=content_type)
    else:
        path = write_note(vault.notes_dir, title, body=body, tags=tags, status=status,
                          note_type=note_type, parent=parent, summary=summary,
                          source=source, tier=tier, content_type=content_type)

    # Read back the note ID (may have been collision-adjusted)
    from hyperresearch.core.note import read_note
    note = read_note(path, vault.root)
    nid = note.meta.id

    rel = path.relative_to(vault.root).as_posix()

    if json_output:
        data = {"id": nid, "path": rel, "title": title}
        if similar:
            data["warning"] = f"Similar note already exists: {similar[0]['id']}"
            data["similar"] = [{"id": r["id"], "title": r["title"]} for r in similar]
        top_tags = vault.db.execute(
            "SELECT tag, COUNT(*) as c FROM tags GROUP BY tag ORDER BY c DESC LIMIT 30"
        ).fetchall()
        if top_tags:
            data["existing_tags"] = [r["tag"] for r in top_tags]
        output(success(data, vault=str(vault.root)), json_mode=True)
    else:
        console.print(f"[green]Created:[/] {rel}")

    if edit:
        import os
        import subprocess

        editor = os.environ.get("EDITOR", "vim")
        subprocess.run([editor, str(path)])


@app.command("show")
def note_show(
    note_ids: list[str] = typer.Argument(..., help="Note ID(s) — pass multiple to read several at once"),
    raw: bool = typer.Option(False, "--raw", "-r", help="Show raw markdown"),
    meta: bool = typer.Option(False, "--meta", "-m", help="Show only frontmatter"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Display one or more notes. Pass multiple IDs for batch read."""
    from hyperresearch.core.vault import Vault

    vault = Vault.discover()
    vault.auto_sync()

    def _fetch_note(nid: str) -> dict | None:
        row = vault.db.execute(
            "SELECT n.*, nc.body FROM notes n JOIN note_content nc ON n.id = nc.note_id WHERE n.id = ?",
            (nid,),
        ).fetchone()
        if not row:
            return None
        tag_list = vault.db.execute(
            "SELECT GROUP_CONCAT(tag, ',') as tl FROM tags WHERE note_id = ?", (nid,)
        ).fetchone()
        tags = tag_list["tl"].split(",") if tag_list and tag_list["tl"] else []
        data = {
            "id": row["id"], "title": row["title"], "path": row["path"],
            "status": row["status"], "type": row["type"], "tags": tags,
            # sqlite3.Row.__contains__ is broken (returns False even for present keys),
            # so use row.keys() explicitly. SIM118 + SIM401 are noqa'd accordingly.
            "tier": row["tier"] if "tier" in row.keys() else None,  # noqa: SIM118
            "content_type": row["content_type"] if "content_type" in row.keys() else None,  # noqa: SIM118
            "created": row["created"], "updated": row["updated"],
            "word_count": row["word_count"], "source": row["source"],
            "parent": row["parent"], "summary": row["summary"],
        }
        if not meta:
            data["body"] = row["body"]
        return data

    # Single note — original behavior
    if len(note_ids) == 1:
        note_id = note_ids[0]
        if raw:
            row = vault.db.execute("SELECT path FROM notes WHERE id = ?", (note_id,)).fetchone()
            if not row:
                if json_output:
                    output(error(f"Note not found: {note_id}", "NOT_FOUND"), json_mode=True)
                else:
                    console.print(f"[red]Note not found:[/] {note_id}")
                raise typer.Exit(1)
            console.print((vault.root / row["path"]).read_text(encoding="utf-8"))
            return

        data = _fetch_note(note_id)
        if not data:
            if json_output:
                output(error(f"Note not found: {note_id}", "NOT_FOUND"), json_mode=True)
            else:
                console.print(f"[red]Note not found:[/] {note_id}")
            raise typer.Exit(1)

        if json_output:
            output(success(data, vault=str(vault.root)), json_mode=True)
        else:
            if meta:
                for k, v in data.items():
                    if v is not None:
                        console.print(f"  [dim]{k}:[/] {v}")
            else:
                tags = data.get("tags", [])
                console.print(f"[bold]{data['title']}[/]  [dim]({data['id']})[/]")
                console.print(f"[dim]Status: {data['status']} | Tags: {', '.join(tags)}[/]")
                console.print()
                from rich.markdown import Markdown
                console.print(Markdown(data.get("body", "")))
        return

    # Multi-note — batch read
    notes = []
    not_found = []
    for nid in note_ids:
        data = _fetch_note(nid)
        if data:
            notes.append(data)
        else:
            not_found.append(nid)

    if json_output:
        result = {"notes": notes, "not_found": not_found}
        output(success(result, count=len(notes), vault=str(vault.root)), json_mode=True)
    else:
        for data in notes:
            tags = data.get("tags", [])
            console.print(f"\n[bold]{data['title']}[/]  [dim]({data['id']})[/]")
            console.print(f"[dim]Status: {data['status']} | Tags: {', '.join(tags)}[/]")
            if not meta:
                console.print()
                from rich.markdown import Markdown
                console.print(Markdown(data.get("body", "")))
        if not_found:
            console.print(f"\n[red]Not found:[/] {', '.join(not_found)}")


@app.command("list")
def note_list(
    status: str | None = typer.Option(None, "--status", "-s", help="Filter by status"),
    note_type: str | None = typer.Option(None, "--type", help="Filter by type"),
    tag: str | None = typer.Option(None, "--tag", "-t", help="Filter by tag"),
    parent: str | None = typer.Option(None, "--parent", "-p", help="Filter by parent"),
    tier: str | None = typer.Option(None, "--tier", help="Filter by epistemic tier: ground_truth|institutional|practitioner|commentary|unknown"),
    content_type: str | None = typer.Option(None, "--content-type", help="Filter by artifact kind: paper|docs|article|blog|forum|dataset|policy|code|book|transcript|review|unknown"),
    sort: str = typer.Option("updated", "--sort", help="Sort: created|updated|title|words"),
    limit: int = typer.Option(20, "--limit", "-l", help="Max results"),
    all_notes: bool = typer.Option(False, "--all", "-a", help="Return all notes (no limit)"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """List notes with optional filters."""
    from hyperresearch.core.vault import Vault
    from hyperresearch.models.note import ContentType, Tier

    # Validate enums up-front
    if tier is not None:
        try:
            Tier(tier)
        except ValueError:
            valid = ", ".join(t.value for t in Tier)
            if json_output:
                output(error(f"Invalid --tier '{tier}'. Must be one of: {valid}", "INVALID_TIER"), json_mode=True)
            else:
                console.print(f"[red]Invalid --tier '{tier}'.[/] Must be one of: {valid}")
            raise typer.Exit(1)
    if content_type is not None:
        try:
            ContentType(content_type)
        except ValueError:
            valid = ", ".join(c.value for c in ContentType)
            if json_output:
                output(error(f"Invalid --content-type '{content_type}'. Must be one of: {valid}", "INVALID_CONTENT_TYPE"), json_mode=True)
            else:
                console.print(f"[red]Invalid --content-type '{content_type}'.[/] Must be one of: {valid}")
            raise typer.Exit(1)

    vault = Vault.discover()
    vault.auto_sync()

    clauses = []
    params: list = []

    if status:
        clauses.append("n.status = ?")
        params.append(status)
    if note_type:
        clauses.append("n.type = ?")
        params.append(note_type)
    if parent:
        clauses.append("n.parent = ?")
        params.append(parent)
    if tag:
        clauses.append("n.id IN (SELECT note_id FROM tags WHERE tag = ?)")
        params.append(tag.lower())
    if tier:
        clauses.append("n.tier = ?")
        params.append(tier)
    if content_type:
        clauses.append("n.content_type = ?")
        params.append(content_type)

    where = " AND ".join(clauses) if clauses else "1=1"

    sort_map = {
        "created": "n.created DESC",
        "updated": "COALESCE(n.updated, n.created) DESC",
        "title": "n.title ASC",
        "words": "n.word_count DESC",
    }
    order = sort_map.get(sort, "COALESCE(n.updated, n.created) DESC")

    effective_limit = 999999 if all_notes else limit
    rows = vault.db.execute(
        f"""SELECT n.*,
            (SELECT GROUP_CONCAT(t.tag, ',') FROM tags t WHERE t.note_id = n.id) as tag_list
        FROM notes n WHERE {where} ORDER BY {order} LIMIT ?""",
        [*params, effective_limit],
    ).fetchall()

    notes = []
    for row in rows:
        tag_list = row["tag_list"].split(",") if row["tag_list"] else []
        notes.append({
            "id": row["id"],
            "title": row["title"],
            "path": row["path"],
            "status": row["status"],
            "type": row["type"],
            # sqlite3.Row.__contains__ is broken; row.keys() is reliable.
            "tier": row["tier"] if "tier" in row.keys() else None,  # noqa: SIM118
            "content_type": row["content_type"] if "content_type" in row.keys() else None,  # noqa: SIM118
            "tags": tag_list,
            "word_count": row["word_count"],
            "summary": row["summary"],
            "created": row["created"],
            "updated": row["updated"],
        })

    if json_output:
        output(
            success(notes, count=len(notes), vault=str(vault.root)),
            json_mode=True,
        )
    else:
        print_note_summary(notes)


@app.command("edit")
def note_edit(
    note_id: str = typer.Argument(..., help="Note ID to edit"),
) -> None:
    """Open a note in $EDITOR."""
    import os
    import subprocess

    from hyperresearch.core.vault import Vault

    vault = Vault.discover()
    vault.auto_sync()

    row = vault.db.execute("SELECT path FROM notes WHERE id = ?", (note_id,)).fetchone()
    if not row:
        console.print(f"[red]Not found:[/] {note_id}")
        raise typer.Exit(1)

    file_path = vault.root / row["path"]
    editor = os.environ.get("EDITOR", os.environ.get("VISUAL", "notepad" if os.name == "nt" else "vim"))
    subprocess.run([editor, str(file_path)])


@app.command("update")
def note_update(
    note_id: str = typer.Argument(..., help="Note ID"),
    set_status: str | None = typer.Option(None, "--status", "-s", help="Set status"),
    add_tag: list[str] = typer.Option([], "--add-tag", help="Add tag(s)"),
    remove_tag: list[str] = typer.Option([], "--remove-tag", help="Remove tag(s)"),
    set_summary: str | None = typer.Option(None, "--summary", help="Set summary"),
    set_parent: str | None = typer.Option(None, "--parent", "-p", help="Set parent topic"),
    set_source: str | None = typer.Option(None, "--source", help="Set source URL/path"),
    set_tier: str | None = typer.Option(None, "--tier", help="Set epistemic tier: ground_truth|institutional|practitioner|commentary|unknown"),
    set_content_type: str | None = typer.Option(None, "--content-type", help="Set artifact kind: paper|docs|article|blog|forum|dataset|policy|code|book|transcript|review|unknown"),
    deprecate: bool = typer.Option(False, "--deprecate", help="Mark as deprecated"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Update frontmatter fields on a single note."""
    from datetime import datetime

    from hyperresearch.core.frontmatter import parse_frontmatter, serialize_frontmatter
    from hyperresearch.core.sync import compute_sync_plan, execute_sync
    from hyperresearch.core.vault import Vault
    from hyperresearch.models.note import ContentType, Tier

    # Validate enums up-front
    if set_tier is not None:
        try:
            Tier(set_tier)
        except ValueError:
            valid = ", ".join(t.value for t in Tier)
            if json_output:
                output(error(f"Invalid --tier '{set_tier}'. Must be one of: {valid}", "INVALID_TIER"), json_mode=True)
            else:
                console.print(f"[red]Invalid --tier '{set_tier}'.[/] Must be one of: {valid}")
            raise typer.Exit(1)
    if set_content_type is not None:
        try:
            ContentType(set_content_type)
        except ValueError:
            valid = ", ".join(c.value for c in ContentType)
            if json_output:
                output(error(f"Invalid --content-type '{set_content_type}'. Must be one of: {valid}", "INVALID_CONTENT_TYPE"), json_mode=True)
            else:
                console.print(f"[red]Invalid --content-type '{set_content_type}'.[/] Must be one of: {valid}")
            raise typer.Exit(1)

    vault = Vault.discover()
    vault.auto_sync()

    row = vault.db.execute("SELECT path FROM notes WHERE id = ?", (note_id,)).fetchone()
    if not row:
        if json_output:
            output(error(f"Note not found: {note_id}", "NOT_FOUND"), json_mode=True)
        else:
            console.print(f"[red]Not found:[/] {note_id}")
        raise typer.Exit(1)

    file_path = vault.root / row["path"]
    content = file_path.read_text(encoding="utf-8-sig")
    meta, body = parse_frontmatter(content)

    changed = []
    if set_status:
        meta.status = set_status
        changed.append(f"status={set_status}")
    for t in add_tag:
        if t.lower() not in meta.tags:
            meta.tags.append(t.lower())
            changed.append(f"+tag:{t}")
    for t in remove_tag:
        if t.lower() in meta.tags:
            meta.tags.remove(t.lower())
            changed.append(f"-tag:{t}")
    if set_summary is not None:
        meta.summary = set_summary
        changed.append("summary")
    if set_parent is not None:
        meta.parent = set_parent
        changed.append(f"parent={set_parent}")
    if set_source is not None:
        meta.source = set_source
        changed.append("source")
    if set_tier is not None:
        meta.tier = set_tier
        changed.append(f"tier={set_tier}")
    if set_content_type is not None:
        meta.content_type = set_content_type
        changed.append(f"content_type={set_content_type}")
    if deprecate:
        meta.deprecated = True
        meta.status = "deprecated"
        changed.append("deprecated")

    if not changed:
        if json_output:
            output(success({"id": note_id, "changed": []}, vault=str(vault.root)), json_mode=True)
        else:
            console.print("[dim]Nothing to update.[/]")
        return

    meta.updated = datetime.now(UTC)
    new_content = serialize_frontmatter(meta) + "\n" + body
    file_path.write_text(new_content, encoding="utf-8")

    plan = compute_sync_plan(vault)
    execute_sync(vault, plan)

    if json_output:
        output(success({"id": note_id, "changed": changed}, vault=str(vault.root)), json_mode=True)
    else:
        console.print(f"[green]Updated {note_id}:[/] {', '.join(changed)}")


@app.command("mv")
def note_mv(
    note_id: str = typer.Argument(..., help="Note ID to move"),
    new_path: str = typer.Argument(..., help="New relative path (e.g. notes/python/renamed.md)"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Move/rename a note, updating all references."""
    from hyperresearch.core.sync import compute_sync_plan, execute_sync
    from hyperresearch.core.vault import Vault

    vault = Vault.discover()
    vault.auto_sync()

    row = vault.db.execute("SELECT path FROM notes WHERE id = ?", (note_id,)).fetchone()
    if not row:
        if json_output:
            output(error(f"Note not found: {note_id}", "NOT_FOUND"), json_mode=True)
        else:
            console.print(f"[red]Not found:[/] {note_id}")
        raise typer.Exit(1)

    old_file = vault.root / row["path"]
    new_file = vault.root / new_path

    new_file.parent.mkdir(parents=True, exist_ok=True)
    old_file.rename(new_file)

    # Re-sync
    plan = compute_sync_plan(vault, force=True)
    execute_sync(vault, plan)

    if json_output:
        output(success({"old_path": row["path"], "new_path": new_path}, vault=str(vault.root)), json_mode=True)
    else:
        console.print(f"[green]Moved:[/] {row['path']} → {new_path}")


@app.command("rm")
def note_rm(
    note_id: str = typer.Argument(..., help="Note ID to delete"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Delete a note and its associated raw file and assets.

    Previous versions only unlinked the `.md` file, leaving raw PDFs under
    `research/raw/` and assets under `research/assets/<id>/` as orphans.
    Every fetch-then-delete cycle leaked disk. The current implementation
    also removes:
      - the raw file referenced in the note's `raw_file` frontmatter field
      - any entries in the `assets` table and their files on disk
    """
    import shutil

    from hyperresearch.core.vault import Vault

    vault = Vault.discover()
    row = vault.db.execute(
        "SELECT path FROM notes WHERE id = ?", (note_id,)
    ).fetchone()
    if not row:
        if json_output:
            output(error(f"Note not found: {note_id}", "NOT_FOUND"), json_mode=True)
        else:
            console.print(f"[red]Not found:[/] {note_id}")
        raise typer.Exit(1)

    file_path = vault.root / row["path"]
    if not force and not json_output:
        typer.confirm(f"Delete {row['path']}?", abort=True)

    removed_raw: str | None = None
    removed_assets: list[str] = []

    # Read raw_file straight from the markdown frontmatter — the DB row
    # may not carry that field if the schema was synced before the column
    # existed. File parsing is authoritative.
    if file_path.exists():
        try:
            from hyperresearch.core.frontmatter import parse_frontmatter
            text = file_path.read_text(encoding="utf-8-sig")
            meta, _ = parse_frontmatter(text)
            if meta.raw_file:
                raw_path = vault.root / "research" / meta.raw_file
                if raw_path.exists():
                    raw_path.unlink()
                    removed_raw = str(raw_path.relative_to(vault.root).as_posix())
        except Exception:
            pass

    # Assets directory
    assets_dir = vault.root / "research" / "assets" / note_id
    if assets_dir.exists() and assets_dir.is_dir():
        for asset_file in assets_dir.iterdir():
            if asset_file.is_file():
                removed_assets.append(asset_file.name)
        shutil.rmtree(assets_dir, ignore_errors=True)

    # Finally, unlink the .md file
    if file_path.exists():
        file_path.unlink()

    # Re-sync to update DB
    from hyperresearch.core.sync import compute_sync_plan, execute_sync

    plan = compute_sync_plan(vault)
    execute_sync(vault, plan)

    payload: dict = {"deleted": note_id}
    if removed_raw:
        payload["removed_raw"] = removed_raw
    if removed_assets:
        payload["removed_assets"] = removed_assets

    if json_output:
        output(success(payload, vault=str(vault.root)), json_mode=True)
    else:
        msg = f"[red]Deleted:[/] {note_id}"
        if removed_raw:
            msg += f"\n  raw: {removed_raw}"
        if removed_assets:
            msg += f"\n  assets: {len(removed_assets)} file(s)"
        console.print(msg)


