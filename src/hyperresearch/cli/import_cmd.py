"""Import notes from another vault or directory."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import typer
from rich.markup import escape

from hyperresearch.cli._output import console, output
from hyperresearch.models.output import error, success


def _copy_if_absent(src: Path, dest: Path) -> str | None:
    """Copy `src` to `dest` as shutil.copy2 does, unless `dest` is taken.

    Returns the sha256 of the bytes it wrote, or None if it copied nothing.
    The exclusive create refuses any entry already at `dest`, so a note there
    is never replaced. A symlink is refused before it: POSIX O_EXCL fails on
    a dangling one, but Windows CREATE_NEW follows it and creates the file it
    points to. A copy that fails after the create removes the file, which is
    ours: left partial, every later import would skip it as taken.
    """
    if dest.is_symlink():
        return None
    with src.open("rb") as fsrc:
        try:
            fdst = dest.open("xb")
        except FileExistsError:
            return None
        try:
            with fdst:
                shutil.copyfileobj(fsrc, fdst)
            # Hashed before copystat: it gives the copy the source's mode but
            # not the ACL or group that let this user read the source, so the
            # copy can be unreadable after it.
            digest = hashlib.sha256(dest.read_bytes()).hexdigest()
            shutil.copystat(src, dest)
        except BaseException:
            dest.unlink(missing_ok=True)
            raise
    return digest


def _print_items(header: str, lines: list[str]) -> None:
    console.print(header)
    for line in lines[:20]:
        console.print(f"  {line}")
    if len(lines) > 20:
        console.print(f"  [dim]...and {len(lines) - 20} more[/]")


def import_vault(
    source: str = typer.Argument(..., help="Source directory to import from"),
    prefix: str = typer.Option(
        "", "--prefix", "-p",
        help="Path prefix under research/notes/ for imported notes (e.g. imported/ml)",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview what would be imported"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Import markdown notes from another directory into this vault.

    A file whose destination already exists is skipped, never overwritten.
    """
    from hyperresearch.core.claims import _under
    from hyperresearch.core.vault import Vault, VaultError

    try:
        vault = Vault.discover()
    except VaultError as e:
        if json_output:
            output(error(str(e), "NO_VAULT"), json_mode=True)
        else:
            console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)

    source_path = Path(source).resolve()
    if not source_path.is_dir():
        msg = f"Source directory not found: {source}"
        if json_output:
            output(error(msg, "NOT_FOUND"), json_mode=True)
        else:
            console.print(f"[red]{msg}[/]")
        raise typer.Exit(1)

    # Find all .md files in source
    md_files = sorted(source_path.rglob("*.md"))
    # Skip .hyperresearch/, templates/ etc. from source
    skip_dirs = {".hyperresearch", ".git", ".venv", "node_modules", "templates"}
    md_files = [
        f for f in md_files
        if not any(part in skip_dirs for part in f.relative_to(source_path).parts)
    ]

    if not md_files:
        if json_output:
            output(success({"imported": [], "count": 0, "skipped": [], "not_indexed": []},
                           vault=str(vault.root)), json_mode=True)
        else:
            console.print("[dim]No markdown files found in source.[/]")
        return

    # Write into research/notes/, not vault root. Joined verbatim, a prefix
    # such as ../../.. wrote outside the vault, so every destination is held
    # to the notes tree, as `note mv` holds its own, before anything is copied.
    notes_rel = vault.notes_dir.relative_to(vault.root)
    notes_root = vault.notes_dir.resolve()
    planned = []
    for src_file in md_files:
        rel = src_file.relative_to(source_path).as_posix()
        dest_rel = f"{prefix}/{rel}" if prefix else rel
        dest = vault.notes_dir / dest_rel
        if not _under(dest.parent, vault.notes_dir):
            msg = (
                f"Destination {(notes_rel / dest_rel).as_posix()} is outside the synced "
                f"tree ({notes_rel.as_posix()}/)"
            )
            if json_output:
                output(error(msg, "OUTSIDE_SYNCED_TREE"), json_mode=True)
            else:
                console.print(f"[red]{escape(msg)}[/]")
            raise typer.Exit(1)
        # Resolved, so a `..` in the prefix still matches the path sync indexes.
        located = (dest.parent.resolve() / dest.name).relative_to(notes_root).as_posix()
        planned.append((src_file, {"source": rel, "destination": located}))

    copied = []
    skipped = []
    for src_file, item in planned:
        dest = vault.notes_dir / item["destination"]
        vault_rel = (notes_rel / item["destination"]).as_posix()
        digest = None
        if dry_run:
            taken = dest.exists() or dest.is_symlink()
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            digest = _copy_if_absent(src_file, dest)
            taken = digest is None
        if taken:
            msg = f"Destination already exists: {vault_rel}"
            skipped.append({**item, "error_code": "DESTINATION_EXISTS", "error": msg})
        else:
            copied.append((item, vault_rel, digest))

    not_indexed = []
    if dry_run:
        imported = [item for item, _, _ in copied]
    else:
        from hyperresearch.cli.note import _file_identity
        from hyperresearch.core.sync import _has_frontmatter, compute_sync_plan, execute_sync
        plan = compute_sync_plan(vault)
        result = execute_sync(vault, plan)

        # Sync leaves out a file without frontmatter and refuses one whose id
        # another note holds, so a copy counts as imported only once its path
        # is in the index with the bytes it copied. A row at the path alone
        # proves nothing: one whose file was removed without a sync stays
        # there when sync refuses the copy, or never reads it. Sync names a
        # file by its vault-relative path or, for an exception, by its full
        # path, as the filesystem spells it: on macOS and Windows a copy to
        # Papers/ lands in an existing papers/, so each copy is matched to
        # sync's file by identity, not by name.
        synced = {
            identity: file_path
            for file_path in (*plan.to_add, *plan.to_update)
            if (identity := _file_identity(file_path)) is not None
        }
        sync_errors = {e["path"]: e["error"] for e in result.errors}
        imported = []
        for item, vault_rel, digest in copied:
            path = synced.get(_file_identity(vault.root / vault_rel), vault.root / vault_rel)
            rel = path.relative_to(vault.root).as_posix()
            reason = sync_errors.get(rel) or sync_errors.get(str(path))
            if reason is None:
                row = vault.db.execute(
                    "SELECT content_hash FROM notes WHERE path = ?", (rel,)
                ).fetchone()
                if row is not None and row["content_hash"] == digest:
                    imported.append(item)
                    continue
                if row is not None:
                    reason = (
                        "the index holds different content at this path, so sync did not "
                        "index the copy: run sync --force"
                    )
                elif _has_frontmatter(path):
                    reason = "sync did not index it"
                else:
                    reason = "no YAML frontmatter: sync indexes only files that open with ---"
            not_indexed.append({**item, "error_code": "NOTE_NOT_INDEXED", "error": reason})

    if json_output:
        action = "would_import" if dry_run else "imported"
        data = {action: imported, "count": len(imported), "skipped": skipped}
        if not dry_run:
            data["not_indexed"] = not_indexed
        output(success(data, count=len(imported), vault=str(vault.root)), json_mode=True)
    else:
        verb = "Would import" if dry_run else "Imported"
        _print_items(
            f"[green]{verb} {len(imported)} files:[/]",
            [escape(f"{i['source']} -> {i['destination']}") for i in imported],
        )
        if skipped:
            _print_items(
                f"[yellow]Skipped {len(skipped)} files:[/]",
                [escape(f"{i['source']}: {i['error']}") for i in skipped],
            )
        if not_indexed:
            _print_items(
                f"[yellow]Copied but not indexed: {len(not_indexed)} files:[/]",
                [escape(f"{i['source']} -> {i['destination']}: {i['error']}") for i in not_indexed],
            )
