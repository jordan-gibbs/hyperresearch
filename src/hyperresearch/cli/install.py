"""Install command — one-step setup: vault init + agent hooks + docs injection."""

from __future__ import annotations

from pathlib import Path

import typer

from hyperresearch.cli._output import console, output
from hyperresearch.models.output import error, success


def install(
    path: str = typer.Argument(".", help="Path to install in"),
    name: str = typer.Option("Research Base", "--name", "-n", help="Vault name"),
    platforms: list[str] = typer.Option(
        ["claude"],
        "--platform",
        "-p",
        help="Agent platforms to hook: claude|codex|cursor|gemini|all",
    ),
    agents: list[str] = typer.Option(
        ["claude"],
        "--agents",
        "-a",
        help="Agent doc files: claude|agents|gemini|copilot",
    ),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Install hyperresearch: init vault + inject agent docs + install hooks."""
    from hyperresearch.core.hooks import install_hooks
    from hyperresearch.core.vault import Vault, VaultError

    root = Path(path).resolve()

    # Step 1: Init vault (skip if already exists)
    try:
        vault = Vault.discover(root)
        vault_action = "existing"
    except VaultError:
        try:
            vault = Vault.init(root, name=name, agents=agents)
            vault_action = "created"
        except VaultError as e:
            if json_output:
                output(error(str(e), "INIT_ERROR"), json_mode=True)
            else:
                console.print(f"[red]Error:[/] {e}")
            raise typer.Exit(1)

    # Step 2: Install hooks
    hook_actions = install_hooks(root, platforms=platforms)

    # Step 3: Report
    data = {
        "vault_path": str(vault.root),
        "vault": vault_action,
        "hooks_installed": hook_actions,
        "platforms": platforms,
    }

    if json_output:
        output(success(data, vault=str(vault.root)), json_mode=True)
    else:
        if vault_action == "created":
            console.print(f"[green]Vault created:[/] {vault.root}")
        else:
            console.print(f"[dim]Vault exists:[/] {vault.root}")

        if hook_actions:
            console.print("[green]Hooks installed:[/]")
            for action in hook_actions:
                console.print(f"  {action}")
        else:
            console.print("[dim]All hooks already installed.[/]")

        console.print("\n[bold]Ready.[/] Agents will now check the research base before web searches.")
