"""Import notes from another vault or directory."""

from __future__ import annotations

import shutil
from pathlib import Path

import typer

from hyperresearch.cli._output import console, output
from hyperresearch.models.output import error, success


def import_vault(
    source: str = typer.Argument(..., help="Source directory to import from"),
    prefix: str = typer.Option("", "--prefix", "-p", help="Path prefix for imported notes (e.g. imported/ml)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview what would be imported"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Import markdown notes from another directory into this vault."""
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
            output(success({"imported": [], "count": 0}, vault=str(vault.root)), json_mode=True)
        else:
            console.print("[dim]No markdown files found in source.[/]")
        return

    imported = []
    for src_file in md_files:
        rel = src_file.relative_to(source_path).as_posix()
        dest_rel = f"{prefix}/{rel}" if prefix else rel
        # Write into research/notes/, not vault root
        dest = vault.notes_dir / dest_rel

        imported.append({"source": rel, "destination": dest_rel})

        if not dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dest)

    if not dry_run:
        from hyperresearch.core.sync import compute_sync_plan, execute_sync
        plan = compute_sync_plan(vault)
        execute_sync(vault, plan)

    if json_output:
        action = "would_import" if dry_run else "imported"
        output(success({action: imported, "count": len(imported)}, count=len(imported),
                       vault=str(vault.root)), json_mode=True)
    else:
        verb = "Would import" if dry_run else "Imported"
        console.print(f"[green]{verb} {len(imported)} files:[/]")
        for item in imported[:20]:
            console.print(f"  {item['source']} -> {item['destination']}")
        if len(imported) > 20:
            console.print(f"  [dim]...and {len(imported) - 20} more[/]")
