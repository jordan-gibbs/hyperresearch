"""Embedding commands — semantic-search vector management."""

from __future__ import annotations

import typer

from hyperresearch.cli._output import console, output
from hyperresearch.models.output import error, success

app = typer.Typer()


@app.command("sync")
def embed_sync_cmd(
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Embed new/changed notes with the configured provider.

    Requires [embeddings] provider = "voyage" or "openai" in config.toml
    (plus the provider's API key env var). No-op re-runs are cheap: only
    notes whose content changed since their last embedding are re-sent.
    """
    from hyperresearch.core.embed import EmbeddingError, embed_sync
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
    try:
        result = embed_sync(vault)
    except EmbeddingError as e:
        if json_output:
            output(error(str(e), "EMBEDDINGS_DISABLED"), json_mode=True)
        else:
            console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)

    if json_output:
        output(success(result, vault=str(vault.root)), json_mode=True)
    else:
        console.print(
            f"[green]Embedded:[/] {result['embedded']} notes "
            f"({result['skipped']} up to date) via {result['provider']}/{result['model']}"
        )


@app.command("status")
def embed_status(
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Show embedding coverage for the vault."""
    from hyperresearch.core.vault import Vault, VaultError

    try:
        vault = Vault.discover()
    except VaultError as e:
        if json_output:
            output(error(str(e), "NO_VAULT"), json_mode=True)
        else:
            console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)

    conn = vault.db
    total = conn.execute("SELECT COUNT(*) AS c FROM notes").fetchone()["c"]
    embedded = conn.execute("SELECT COUNT(*) AS c FROM embeddings").fetchone()["c"]
    data = {
        "provider": vault.config.embeddings.provider,
        "notes": total,
        "embedded": embedded,
    }
    if json_output:
        output(success(data, vault=str(vault.root)), json_mode=True)
    else:
        console.print(
            f"provider: {data['provider']}  embedded: {embedded}/{total} notes"
        )
