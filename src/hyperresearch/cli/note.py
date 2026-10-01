"""Note CRUD CLI commands."""

from __future__ import annotations

import os
import stat
from datetime import UTC
from pathlib import Path

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

    # Sync the new file into the DB so type/tags are indexed immediately
    from hyperresearch.core.sync import compute_sync_plan, execute_sync
    plan = compute_sync_plan(vault)
    execute_sync(vault, plan)

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
        # Open-access substitution. Surfaced structurally, not just as the
        # banner in the body, so a reader checking a quotation can tell it is
        # looking at a preprint without having to parse prose. `source` above
        # is still the URL that was requested; `oa_url` is where the body came
        # from. See core/oa.py.
        if "oa_url" in row.keys() and row["oa_url"]:  # noqa: SIM118
            kind = (
                row["oa_recovery_kind"]
                if "oa_recovery_kind" in row.keys()  # noqa: SIM118
                else None
            )
            data["oa"] = {
                "url": row["oa_url"],
                "resolver": row["oa_source"],
                "version": row["oa_version"],
                "license": row["oa_license"],
                "body_is_not_from_source": True,
                # "rescued" is the stronger claim: the source URL was never
                # read, so the title and authors are the open-access copy's
                # too. "substituted" means only the body was replaced.
                "kind": kind,
                "nothing_from_source": kind == "rescued",
            }
        if not meta:
            body = row["body"]
            from hyperresearch.core.untrusted import is_untrusted, wrap_body
            if is_untrusted(data.get("source"), data.get("type")):
                data["body"] = wrap_body(body, data["source"])
                data["untrusted"] = True
            else:
                data["body"] = body
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
    tag: list[str] = typer.Option([], "--tag", "-t", help="Filter by tag (repeatable, AND logic)"),
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
    for t in tag:
        clauses.append("n.id IN (SELECT note_id FROM tags WHERE tag = ?)")
        params.append(t.lower())
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
    from hyperresearch.models.note import ContentType, NoteStatus, Tier

    # Validate enums up-front
    if set_status is not None:
        try:
            NoteStatus(set_status)
        except ValueError:
            valid = ", ".join(s.value for s in NoteStatus)
            if json_output:
                output(error(f"Invalid --status '{set_status}'. Must be one of: {valid}", "INVALID_STATUS"), json_mode=True)
            else:
                console.print(f"[red]Invalid --status '{set_status}'.[/] Must be one of: {valid}")
            raise typer.Exit(1)
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
    new_path: str = typer.Argument(
        ...,
        help=(
            "Destination relative to the vault root, e.g. research/notes/renamed.md. "
            "A bare name lands in research/notes/ and a missing .md is added. The note "
            "keeps its id (it lives in frontmatter, not the filename), so wiki-links to "
            "it stay valid and nothing else is rewritten."
        ),
    ),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Move a note file within the tree sync scans (research/notes or research/temp).

    The id is unchanged: `mv` moves the file, it does not rename the note.
    """
    from pathlib import Path

    from hyperresearch.core.claims import _under
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

    # Resolve the destination into something sync will see. Joined verbatim, a
    # bare name landed at the vault root with no suffix, where sync never
    # looks, so the note silently left the index; and rename() replaced an
    # existing note file without a word. research/index/ is synced but not a
    # destination: IndexGenerator.build_all() deletes every .md there on the
    # next repair, so a note moved in would be lost.
    dest = Path(new_path)
    if dest.name and dest.suffix.lower() != ".md":
        dest = dest.with_name(dest.name + ".md")
    if dest.parent == Path("."):
        dest = vault.notes_dir.relative_to(vault.root) / dest
    new_file = vault.root / dest
    synced_roots = (vault.notes_dir, vault.temp_dir)
    if not any(_under(new_file, r) and new_file.resolve() != r.resolve() for r in synced_roots):
        allowed = ", ".join(r.relative_to(vault.root).as_posix() + "/" for r in synced_roots)
        msg = f"Destination {dest.as_posix()} is outside the synced tree ({allowed})"
        if json_output:
            output(error(msg, "OUTSIDE_SYNCED_TREE"), json_mode=True)
        else:
            console.print(f"[red]{msg}[/]")
        raise typer.Exit(1)
    # samefile: on a case-insensitive filesystem a case-only rename
    # (n-f -> N-F.md) "exists" because it is the note's own file.
    if new_file.exists() and not new_file.samefile(old_file):
        msg = f"Destination already exists: {dest.as_posix()}"
        if json_output:
            output(error(msg, "DESTINATION_EXISTS"), json_mode=True)
        else:
            console.print(f"[red]{msg}[/]")
        raise typer.Exit(1)
    # Resolve the parent only: on a case-insensitive filesystem resolve() on the
    # file itself returns the old spelling during a case-only rename.
    rel_new = (
        (new_file.parent.resolve() / new_file.name).relative_to(vault.root.resolve()).as_posix()
    )

    new_file.parent.mkdir(parents=True, exist_ok=True)
    old_file.rename(new_file)

    # Re-sync
    plan = compute_sync_plan(vault, force=True)
    execute_sync(vault, plan)

    if json_output:
        output(success({"old_path": row["path"], "new_path": rel_new}, vault=str(vault.root)), json_mode=True)
    else:
        console.print(f"[green]Moved:[/] {row['path']} → {rel_new}")


def _file_identity(path: Path) -> tuple | None:
    """What makes `path` the same file as another spelling of it, or None
    when no regular file is there.

    The device and inode, so case, symlinks and `..` do not matter.
    """
    try:
        st = os.stat(path)
    except OSError:
        return None
    if not stat.S_ISREG(st.st_mode):
        return None
    return (st.st_dev, st.st_ino)


def _located(path: Path) -> Path:
    """`path` with its directory resolved; a symlink stays where it sits."""
    return path.parent.resolve() / path.name


def _is_below(path: Path, root: Path) -> bool:
    """Whether `path`, symlinks resolved, lies strictly below the directory `root`."""
    where, root = path.resolve(), root.resolve()
    return where != root and where.is_relative_to(root)


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
      - the files under `research/assets/` that the note's rows in the
        `assets` table name, and the rest of `research/assets/<id>/` unless
        that is a symlink, except a file another note's row names; nothing
        outside `research/assets/` is removed
    A file that cannot be removed does not stop the delete; it is reported
    under `assets_not_removed`.
    """
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
                # Resolve and guard against path traversal — a malicious or
                # corrupted frontmatter could set raw_file to "../../etc/passwd".
                # Refuse to unlink anything outside <vault>/research/.
                research_root = (vault.root / "research").resolve()
                raw_path = (vault.root / "research" / meta.raw_file).resolve()
                try:
                    raw_path.relative_to(research_root)
                    inside_vault = True
                except ValueError:
                    inside_vault = False
                if inside_vault and raw_path.exists() and raw_path.is_file():
                    raw_path.unlink()
                    removed_raw = str(raw_path.relative_to(vault.root).as_posix())
        except Exception:
            pass

    # Assets. A row names its file by full path, and the file need not sit
    # under research/assets/<note_id>/: fetch saves a note's files under the
    # stem of its file at the time, and sync renames a row in place when the
    # file's `id:` is rewritten, leaving the files where they are. So the
    # files to remove are the ones this note's own rows name anywhere under
    # research/assets/, plus whatever research/assets/<note_id>/ holds that
    # no other note's row names (fetch can write a file it records no row
    # for). A file another note's row names stays, in whichever directory it
    # is. Files are compared by identity, not by spelling. Nothing is removed
    # whose path, symlinks resolved, is not below this vault's
    # research/assets/: a row naming a file elsewhere (a copy of the vault
    # still holds the original's paths) is reported and its file left alone.
    assets_root = vault.root / "research" / "assets"
    assets_dir = assets_root / note_id
    own_files: list[Path] = []
    others: set[tuple] = set()
    # Where other notes' rows point, as spelled: a symlink a row names is
    # that note's, whatever it points at.
    other_paths: set[Path] = set()
    for r in vault.db.execute("SELECT note_id, filename FROM assets"):
        if r["note_id"] == note_id:
            own_files.append(Path(r["filename"]))
        else:
            other_paths.add(_located(Path(r["filename"])))
            ident = _file_identity(Path(r["filename"]))
            if ident is not None:
                others.add(ident)
    seen: set[tuple] = set()
    seen_links: set[Path] = set()
    assets_not_removed: list[str] = []
    # The directories a removal may have emptied.
    dirs: set[Path] = set()

    def _label(path: Path) -> str:
        # Vault-relative; a symlink is named where it sits, not by its target.
        try:
            return _located(path).relative_to(vault.root.resolve()).as_posix()
        except ValueError:
            return str(path)

    def _remove_link(path: Path) -> None:
        # A symlink is removed as itself, dangling or not: unlinking it never
        # touches its target, wherever that is. Only a link that sits below
        # research/assets/ goes, and not one another note's row names.
        where = _located(path)
        if where in other_paths or where in seen_links:
            return
        seen_links.add(where)
        if not where.parent.is_relative_to(assets_root.resolve()):
            assets_not_removed.append(f"{path}: outside research/assets/, left in place")
            return
        label = _label(path)
        try:
            path.unlink()
        except OSError as exc:
            assets_not_removed.append(f"{label}: {exc.strerror or exc}")
            return
        removed_assets.append(label)
        dirs.add(path.parent)

    def _remove_file(path: Path) -> None:
        if path.is_symlink():
            _remove_link(path)
            return
        ident = _file_identity(path)
        if ident is None or ident in others or ident in seen:
            return
        seen.add(ident)
        if not _is_below(path, assets_root):
            assets_not_removed.append(f"{path}: outside research/assets/, left in place")
            return
        label = _label(path)
        try:
            path.unlink()
        except OSError as exc:
            assets_not_removed.append(f"{label}: {exc.strerror or exc}")
            return
        removed_assets.append(label)
        dirs.add(path.parent)

    for path in own_files:
        _remove_file(path)
    # A symlinked research/assets/<note_id> points at a directory that is not
    # this note's to empty or remove, inside the vault or not; the link stays,
    # as before.
    if assets_dir.is_dir() and not assets_dir.is_symlink():
        dirs.add(assets_dir)
        for path in sorted(assets_dir.rglob("*")):
            if path.is_dir() and not path.is_symlink():
                dirs.add(path)
            else:
                _remove_file(path)
    # An empty one goes, deepest first: never a symlink, and only below
    # research/assets/.
    for d in sorted({_located(d) for d in dirs}, key=lambda d: len(d.parts), reverse=True):
        if d.is_symlink() or not _is_below(d, assets_root):
            continue
        try:
            if not d.is_dir() or any(d.iterdir()):
                continue
            d.rmdir()
        except OSError as exc:
            assets_not_removed.append(f"{_label(d)}/: {exc.strerror or exc}")

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
    if assets_not_removed:
        payload["assets_not_removed"] = assets_not_removed

    if json_output:
        output(success(payload, vault=str(vault.root)), json_mode=True)
    else:
        msg = f"[red]Deleted:[/] {note_id}"
        if removed_raw:
            msg += f"\n  raw: {removed_raw}"
        if removed_assets:
            msg += f"\n  assets: {len(removed_assets)} file(s)"
        if assets_not_removed:
            msg += "\n  assets not removed: " + "; ".join(assets_not_removed)
        console.print(msg)


