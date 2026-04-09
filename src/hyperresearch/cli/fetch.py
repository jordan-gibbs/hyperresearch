"""Fetch and websearch commands — save web content as research notes."""

from __future__ import annotations

import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import typer

from hyperresearch.cli._output import console, output
from hyperresearch.models.output import error, success

app = typer.Typer()


@app.command("fetch")
def fetch(
    url: str = typer.Argument(..., help="URL to fetch and save as a note"),
    tags: list[str] = typer.Option([], "--tag", "-t", help="Tags (repeatable)"),
    title: str | None = typer.Option(None, "--title", help="Override title"),
    parent: str | None = typer.Option(None, "--parent", "-p", help="Parent topic"),
    provider_name: str | None = typer.Option(None, "--provider", help="Web provider override"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Fetch a URL and save its content as a research note."""
    from hyperresearch.core.note import write_note
    from hyperresearch.core.sync import compute_sync_plan, execute_sync
    from hyperresearch.core.vault import Vault, VaultError
    from hyperresearch.web.base import get_provider

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

    # Check if URL already fetched
    existing = conn.execute("SELECT note_id FROM sources WHERE url = ?", (url,)).fetchone()
    if existing:
        note_id = existing["note_id"]
        if json_output:
            output(
                error(f"URL already fetched as note '{note_id}'", "DUPLICATE_URL"),
                json_mode=True,
            )
        else:
            console.print(f"[yellow]Already fetched:[/] {url} → note '{note_id}'")
        raise typer.Exit(1)

    # Fetch content
    prov = get_provider(provider_name or vault.config.web_provider)
    if not json_output:
        console.print(f"[dim]Fetching with {prov.name}...[/]")

    try:
        result = prov.fetch(url)
    except Exception as e:
        if json_output:
            output(error(str(e), "FETCH_ERROR"), json_mode=True)
        else:
            console.print(f"[red]Fetch failed:[/] {e}")
        raise typer.Exit(1)

    # Write note
    note_title = title or result.title or urlparse(url).path.split("/")[-1] or "Untitled"
    domain = result.domain

    extra_meta = {
        "source": url,
        "source_domain": domain,
        "fetched_at": result.fetched_at.isoformat(),
        "fetch_provider": prov.name,
    }
    if result.metadata.get("author"):
        extra_meta["author"] = result.metadata["author"]

    note_path = write_note(
        vault.notes_dir,
        title=note_title,
        body=result.content,
        tags=tags,
        status="draft",
        source=url,
        parent=parent,
        extra_frontmatter=extra_meta,
    )

    # Record source in DB
    content_hash = hashlib.sha256(result.content.encode("utf-8")).hexdigest()[:16]
    note_id = note_path.stem
    conn.execute(
        """INSERT INTO sources (url, note_id, domain, fetched_at, provider, content_hash)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (url, note_id, domain, result.fetched_at.isoformat(), prov.name, content_hash),
    )
    conn.commit()

    # Sync to index the new note
    plan = compute_sync_plan(vault)
    if plan.to_add or plan.to_update:
        execute_sync(vault, plan)

    data = {
        "note_id": note_id,
        "title": note_title,
        "url": url,
        "domain": domain,
        "provider": prov.name,
        "path": str(note_path.relative_to(vault.root)),
        "word_count": len(result.content.split()),
    }

    if json_output:
        output(success(data, vault=str(vault.root)), json_mode=True)
    else:
        console.print(f"[green]Saved:[/] {note_title}")
        console.print(f"  ID: {note_id}")
        console.print(f"  Source: {url}")
        console.print(f"  Words: {data['word_count']}")
