"""Git integration — changelog, blame, changed files."""

from __future__ import annotations

import subprocess
from pathlib import Path

import typer

from hyperresearch.cli._output import console, output
from hyperresearch.models.output import error, success

app = typer.Typer()


def _run_git(vault_root: Path, args: list[str]) -> tuple[int, str]:
    """Run a git command and return (returncode, stdout)."""
    result = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        cwd=str(vault_root),
    )
    return result.returncode, result.stdout


@app.command("log")
def git_log(
    limit: int = typer.Option(20, "--limit", "-l", help="Max commits"),
    since: str | None = typer.Option(None, "--since", help="Since date (YYYY-MM-DD)"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Show notes changed in recent commits."""
    from hyperresearch.core.vault import Vault, VaultError

    try:
        vault = Vault.discover()
    except VaultError as e:
        if json_output:
            output(error(str(e), "NO_VAULT"), json_mode=True)
        else:
            console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)

    # Use \x00 as delimiter to avoid pipe characters in commit messages
    args = ["log", f"--max-count={limit}", "--name-only", "--pretty=format:%H%x00%s%x00%ai"]
    if since:
        args.append(f"--since={since}")
    args.append("-- *.md")

    rc, out = _run_git(vault.root, args)
    if rc != 0:
        if json_output:
            output(error("Not a git repository", "NOT_GIT"), json_mode=True)
        else:
            console.print("[red]Not a git repository.[/]")
        raise typer.Exit(1)

    # Parse git log output
    commits = []
    current_commit = None
    for line in out.strip().split("\n"):
        if not line:
            continue
        if "\x00" in line and len(line.split("\x00")) >= 3:
            parts = line.split("\x00", 2)
            current_commit = {
                "hash": parts[0][:8],
                "message": parts[1],
                "date": parts[2].strip()[:10],
                "files": [],
            }
            commits.append(current_commit)
        elif current_commit and line.endswith(".md"):
            current_commit["files"].append(line.strip())

    if json_output:
        output(success(commits, count=len(commits), vault=str(vault.root)), json_mode=True)
    else:
        if not commits:
            console.print("[dim]No commits found with .md changes.[/]")
            return
        for c in commits:
            console.print(f"[dim]{c['date']}[/] [bold]{c['hash']}[/] {c['message']}")
            for f in c["files"]:
                console.print(f"    [cyan]{f}[/]")


@app.command("blame")
def git_blame(
    note_id: str = typer.Argument(..., help="Note ID"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Show git blame for a note file."""
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

    rc, out = _run_git(vault.root, ["blame", "--porcelain", row["path"]])
    if rc != 0:
        if json_output:
            output(error("Git blame failed", "GIT_ERROR"), json_mode=True)
        else:
            console.print("[red]Git blame failed.[/]")
        raise typer.Exit(1)

    if json_output:
        output(success({"note_id": note_id, "path": row["path"], "blame": out}, vault=str(vault.root)), json_mode=True)
    else:
        # Simplified blame output
        _rc2, simple = _run_git(vault.root, ["blame", "--date=short", row["path"]])
        console.print(simple)


@app.command("changed")
def git_changed(
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Show notes with uncommitted changes."""
    from hyperresearch.core.vault import Vault

    vault = Vault.discover()

    rc, out = _run_git(vault.root, ["status", "--porcelain"])
    if rc != 0:
        if json_output:
            output(error("Not a git repository", "NOT_GIT"), json_mode=True)
        else:
            console.print("[red]Not a git repository.[/]")
        raise typer.Exit(1)

    changes = []
    for line in out.strip().split("\n"):
        if not line:
            continue
        status_code = line[:2].strip()
        file_path = line[3:].strip()
        if file_path.endswith(".md"):
            change_type = {"M": "modified", "A": "added", "D": "deleted", "?": "untracked"}.get(
                status_code, status_code
            )
            changes.append({"status": change_type, "path": file_path})

    if json_output:
        output(success(changes, count=len(changes), vault=str(vault.root)), json_mode=True)
    else:
        if not changes:
            console.print("[green]No uncommitted changes to .md files.[/]")
            return
        for c in changes:
            style = {"modified": "yellow", "added": "green", "deleted": "red", "untracked": "dim"}.get(c["status"], "")
            console.print(f"  [{style}]{c['status']:10s}[/] {c['path']}")
