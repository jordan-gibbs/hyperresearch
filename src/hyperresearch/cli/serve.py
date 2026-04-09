"""Serve CLI command — browse vault in a web browser."""

from __future__ import annotations

import typer

from hyperresearch.cli._output import console


def serve(
    port: int = typer.Option(8080, "--port", "-p", help="Port to serve on"),
    open_browser: bool = typer.Option(False, "--open", "-o", help="Open browser automatically"),
) -> None:
    """Start a web server to browse the vault."""
    from hyperresearch.core.vault import Vault, VaultError

    try:
        vault = Vault.discover()
    except VaultError as e:
        console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)

    vault.auto_sync()

    from hyperresearch.serve.server import run_server
    run_server(vault, port=port, open_browser=open_browser)
