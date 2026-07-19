"""Escalation commands — the browser-lane work queue.

Blocked fetches land here (login walls, bot blocks, captchas); the
hyperresearch-browser-fetcher agent drains the queue via `claim` →
(`ingest` | `human` | `abandon`). `ingest` is the one-shot completion:
it writes the note, records the source row, syncs, and resolves the item —
the agent supplies content, Python does the bookkeeping.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import typer

from hyperresearch.cli._output import console, output
from hyperresearch.models.output import error, success

app = typer.Typer()


def _vault_or_exit(json_output: bool):
    from hyperresearch.core.vault import Vault, VaultError

    try:
        return Vault.discover()
    except VaultError as e:
        if json_output:
            output(error(str(e), "NO_VAULT"), json_mode=True)
        else:
            console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)


@app.command("list")
def escalation_list(
    status: str | None = typer.Option(None, "--status", "-s", help="queued|in_progress|fetched|needs_human|abandoned"),
    tag: str | None = typer.Option(None, "--tag", "-t", help="Only items for this vault_tag"),
    limit: int = typer.Option(100, "--limit", "-n", help="Max items"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """List escalation queue items (highest utility first)."""
    from hyperresearch.core.escalation import list_items, queue_stats

    vault = _vault_or_exit(json_output)
    items = list_items(vault.db, status=status, vault_tag=tag, limit=limit)
    stats = queue_stats(vault.db, vault_tag=tag)

    if json_output:
        output(success({"items": items, "stats": stats}, count=len(items), vault=str(vault.root)), json_mode=True)
    else:
        for it in items:
            score = f"u{it['utility_score']:g}" if it["utility_score"] is not None else "u?"
            console.print(f"  #{it['id']} [{it['status']}] ({it['reason']}, {score}) {it['url']}")
        console.print(f"[dim]{stats}[/]")


@app.command("add")
def escalation_add(
    url: str = typer.Argument(..., help="URL (or Scholar query for --reason scholar_search)"),
    reason: str = typer.Option(..., "--reason", "-r", help="login_wall|bot_block|captcha|fetch_failed|interactive_needed|scholar_search"),
    tag: str | None = typer.Option(None, "--tag", "-t", help="vault_tag"),
    utility: float | None = typer.Option(None, "--utility", help="Utility score (drives drain priority)"),
    suggested_by: str | None = typer.Option(None, "--suggested-by", help="Note id that surfaced this URL"),
    detail: str | None = typer.Option(None, "--detail", help="One-line context"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Manually queue an item (e.g. an interactive-only page or a Scholar search)."""
    from hyperresearch.core.escalation import EscalationError, enqueue

    vault = _vault_or_exit(json_output)
    try:
        item_id = enqueue(
            vault.db, url, reason, vault_tag=tag, requested_by="manual",
            suggested_by=suggested_by, utility_score=utility, detail=detail,
        )
    except EscalationError as e:
        if json_output:
            output(error(str(e), "ESCALATION_ERROR"), json_mode=True)
        else:
            console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)

    data = {"id": item_id, "already_queued": item_id is None}
    if json_output:
        output(success(data, vault=str(vault.root)), json_mode=True)
    else:
        console.print(f"  queued #{item_id}" if item_id else "  already queued")


@app.command("claim")
def escalation_claim(
    claimed_by: str = typer.Option("browser-fetcher", "--by", help="Claimer id"),
    tag: str | None = typer.Option(None, "--tag", "-t", help="Only claim items for this vault_tag"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Atomically claim the next queued item (empty result when queue is drained)."""
    from hyperresearch.core.escalation import claim_next

    vault = _vault_or_exit(json_output)
    item = claim_next(vault.db, claimed_by, vault_tag=tag)

    if json_output:
        output(success({"item": item, "queue_empty": item is None}, vault=str(vault.root)), json_mode=True)
    else:
        if item is None:
            console.print("[dim]Queue empty.[/]")
        else:
            console.print(f"  claimed #{item['id']} ({item['reason']}) {item['url']}")


@app.command("ingest")
def escalation_ingest(
    item_id: int = typer.Argument(..., help="Claimed escalation item id"),
    title: str = typer.Option(..., "--title", help="Page title"),
    body_file: str = typer.Option(..., "--body-file", help="File containing the extracted page content (markdown/plain text)"),
    tags: list[str] = typer.Option([], "--tag", "-t", help="Tags (repeatable; the item's vault_tag is added automatically)"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Complete a claimed item: write the note + source row, sync, resolve.

    One command so the browser agent can't half-finish the bookkeeping.
    Notes carry `fetch_provider: chrome` — browser-lane provenance is visible.
    """
    from hyperresearch.core.escalation import EscalationError, list_items, resolve
    from hyperresearch.core.note import write_note
    from hyperresearch.core.scholar import extract_doi
    from hyperresearch.core.sync import compute_sync_plan, execute_sync

    vault = _vault_or_exit(json_output)
    conn = vault.db

    matching = [it for it in list_items(conn, limit=10000) if it["id"] == item_id]
    if not matching:
        if json_output:
            output(error(f"no escalation item #{item_id}", "NOT_FOUND"), json_mode=True)
        else:
            console.print(f"[red]Error:[/] no escalation item #{item_id}")
        raise typer.Exit(1)
    item = matching[0]

    body = Path(body_file).read_text(encoding="utf-8-sig")
    url = item["url"]
    domain = urlparse(url).netloc
    now = datetime.now(UTC)

    all_tags = list(tags)
    if item["vault_tag"] and item["vault_tag"] not in all_tags:
        all_tags.insert(0, item["vault_tag"])

    extra_meta: dict = {
        "source": url,
        "source_domain": domain,
        "fetched_at": now.isoformat(),
        "fetch_provider": "chrome",
    }
    detected_doi = extract_doi(url, content=body)
    if detected_doi:
        extra_meta["doi"] = detected_doi
    if item["utility_score"] is not None:
        extra_meta["utility_score"] = item["utility_score"]

    if item["suggested_by"]:
        body = f"*Suggested by [[{item['suggested_by']}]]*\n\n" + body

    note_path = write_note(
        vault.notes_dir, title=title, body=body, tags=all_tags,
        status="draft", source=url, extra_frontmatter=extra_meta,
    )
    note_id = note_path.stem

    plan = compute_sync_plan(vault)
    if plan.to_add or plan.to_update:
        execute_sync(vault, plan)

    content_hash = hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]
    conn.execute(
        """INSERT OR IGNORE INTO sources (url, note_id, domain, fetched_at, provider, content_hash)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (url, note_id, domain, now.isoformat(), "chrome", content_hash),
    )
    conn.commit()

    try:
        resolved = resolve(conn, item_id, "fetched", note_id=note_id)
    except EscalationError as e:
        if json_output:
            output(error(str(e), "ESCALATION_ERROR"), json_mode=True)
        else:
            console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)

    data = {
        "note_id": note_id,
        "path": str(note_path.relative_to(vault.root)),
        "word_count": len(body.split()),
        "item": resolved,
    }
    if json_output:
        output(success(data, vault=str(vault.root)), json_mode=True)
    else:
        console.print(f"[green]Ingested:[/] #{item_id} -> note '{note_id}'")


@app.command("human")
def escalation_human(
    item_id: int = typer.Argument(..., help="Item id"),
    detail: str = typer.Option(..., "--detail", help="One line: what the human must do (e.g. 'solve CAPTCHA on nature.com')"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Mark an item as needing the human (CAPTCHA / 2FA / login). NEVER solve these automatically."""
    from hyperresearch.core.escalation import EscalationError, resolve

    vault = _vault_or_exit(json_output)
    try:
        item = resolve(vault.db, item_id, "needs_human", detail=detail)
    except EscalationError as e:
        if json_output:
            output(error(str(e), "ESCALATION_ERROR"), json_mode=True)
        else:
            console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)
    if json_output:
        output(success(item, vault=str(vault.root)), json_mode=True)
    else:
        console.print(f"  #{item_id} needs human: {detail}")


@app.command("retry")
def escalation_retry(
    item_id: int = typer.Argument(..., help="Item id"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Re-queue a needs_human item after the human completed the challenge."""
    from hyperresearch.core.escalation import EscalationError, resolve

    vault = _vault_or_exit(json_output)
    try:
        item = resolve(vault.db, item_id, "queued")
    except EscalationError as e:
        if json_output:
            output(error(str(e), "ESCALATION_ERROR"), json_mode=True)
        else:
            console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)
    if json_output:
        output(success(item, vault=str(vault.root)), json_mode=True)
    else:
        console.print(f"  #{item_id} re-queued")


@app.command("abandon")
def escalation_abandon(
    item_id: int = typer.Argument(..., help="Item id"),
    detail: str | None = typer.Option(None, "--detail", help="Why (optional)"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Give up on an item. The floor is the pre-4.0 status quo: the source is lost."""
    from hyperresearch.core.escalation import EscalationError, resolve

    vault = _vault_or_exit(json_output)
    try:
        item = resolve(vault.db, item_id, "abandoned", detail=detail)
    except EscalationError as e:
        if json_output:
            output(error(str(e), "ESCALATION_ERROR"), json_mode=True)
        else:
            console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)
    if json_output:
        output(success(item, vault=str(vault.root)), json_mode=True)
    else:
        console.print(f"  #{item_id} abandoned")
