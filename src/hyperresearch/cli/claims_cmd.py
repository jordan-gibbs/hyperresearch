"""Claims commands — ingest and query fetcher-extracted claims."""

from __future__ import annotations

from pathlib import Path

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


@app.command("ingest")
def claims_ingest(
    paths: list[str] = typer.Argument(None, help="claims-*.json files (default: all under research/temp/)"),
    vault_tag: str | None = typer.Option(None, "--tag", "-t", help="vault_tag to stamp on ingested claims"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Ingest claims JSON files into the claims table (idempotent)."""
    from hyperresearch.core.claims import ingest_claims_dir, ingest_claims_file

    vault = _vault_or_exit(json_output)
    vault.auto_sync()

    if paths:
        summary = {"files": len(paths), "ingested": 0, "skipped": 0, "errors": []}
        for p in paths:
            r = ingest_claims_file(vault.db, Path(p), vault_tag)
            summary["ingested"] += r["ingested"]
            summary["skipped"] += r["skipped"]
            summary["errors"].extend(f"{Path(p).name}: {e}" for e in r["errors"])
        vault.db.commit()
    else:
        summary = ingest_claims_dir(vault, vault_tag=vault_tag)

    if json_output:
        output(success(summary, vault=str(vault.root)), json_mode=True)
    else:
        console.print(
            f"[green]Ingested:[/] {summary['ingested']} claims "
            f"({summary['skipped']} already present) from {summary['files']} file(s)"
        )
        for e in summary["errors"]:
            console.print(f"  [yellow]{e}[/]")


@app.command("list")
def claims_list(
    note: str | None = typer.Option(None, "--note", help="Only claims from this source note"),
    vault_tag: str | None = typer.Option(None, "--tag", "-t", help="Only claims with this vault_tag"),
    limit: int = typer.Option(100, "--limit", "-n", help="Max claims"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """List stored claims, optionally filtered by source note or vault_tag."""
    from hyperresearch.core.claims import list_claims

    vault = _vault_or_exit(json_output)
    rows = list_claims(vault.db, note_id=note, vault_tag=vault_tag, limit=limit)

    if json_output:
        output(success({"claims": rows}, count=len(rows), vault=str(vault.root)), json_mode=True)
    else:
        for r in rows:
            console.print(f"  [cyan]{r['note_id']}[/] {r['claim'][:120]}")
        console.print(f"[dim]{len(rows)} claims[/]")


@app.command("search")
def claims_search(
    query: str = typer.Argument(..., help="FTS query over claims + quoted support"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max results"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Full-text search over claims — 'which source supports X' as a query."""
    from hyperresearch.core.claims import search_claims

    vault = _vault_or_exit(json_output)
    rows = search_claims(vault.db, query, limit=limit)

    if json_output:
        output(success({"claims": rows}, count=len(rows), vault=str(vault.root)), json_mode=True)
    else:
        if not rows:
            console.print("[dim]No matching claims.[/]")
            return
        for r in rows:
            console.print(f"  [cyan]{r['note_id']}[/] {r['claim'][:120]}")
            if r.get("quoted_support"):
                console.print(f"    [dim]\"{r['quoted_support'][:160]}\"[/]")


@app.command("matrix")
def claims_matrix(
    vault_tag: str | None = typer.Option(None, "--tag", "-t", help="Only claims with this vault_tag"),
    out: str | None = typer.Option(None, "--out", "-o", help="Write the markdown table to this file"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Literature-review matrix: one row per claimed source (tier, quality, key finding).

    The dissertation-scale appendix artifact — weeks of human table-building,
    generated from the claims table.
    """
    from hyperresearch.core.claims import literature_matrix, render_matrix_markdown

    vault = _vault_or_exit(json_output)
    rows = literature_matrix(vault.db, vault_tag=vault_tag)

    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(render_matrix_markdown(rows), encoding="utf-8")

    if json_output:
        output(success({"rows": rows, "written_to": out}, count=len(rows), vault=str(vault.root)), json_mode=True)
    else:
        console.print(render_matrix_markdown(rows))
        if out:
            console.print(f"[green]Written:[/] {out}")


@app.command("targets")
def claims_targets(
    vault_tag: str | None = typer.Option(None, "--tag", "-t", help="Only claims with this vault_tag"),
    min_sources: int = typer.Option(2, "--min-sources", help="Only targets addressed by >= N distinct sources"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Group claims by stance_target across sources — meta-analysis substrate.

    Surfaces where multiple sources address the same quantity/question, with
    stance splits and source-attributed numbers for comparison tables.
    """
    from hyperresearch.core.claims import group_by_target

    vault = _vault_or_exit(json_output)
    groups = group_by_target(vault.db, vault_tag=vault_tag, min_sources=min_sources)

    if json_output:
        output(success({"targets": groups}, count=len(groups), vault=str(vault.root)), json_mode=True)
    else:
        for g in groups:
            console.print(f"  [cyan]{g['stance_target']}[/] {g['n_sources']} sources, {g['n_claims']} claims, stances={g['stances']}")
