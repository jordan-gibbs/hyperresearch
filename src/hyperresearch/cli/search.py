"""Search CLI — full-text search across all notes."""

from __future__ import annotations

import typer

from hyperresearch.cli._output import console, output
from hyperresearch.models.output import error, success


def search(
    query: str = typer.Argument(..., help="Search query"),
    tag: list[str] = typer.Option([], "--tag", "-t", help="Filter by tag (AND logic)"),
    status: str | None = typer.Option(None, "--status", "-s", help="Filter by status"),
    note_type: str | None = typer.Option(None, "--type", help="Filter by type"),
    parent: str | None = typer.Option(None, "--parent", "-p", help="Filter by parent topic"),
    after: str | None = typer.Option(None, "--after", help="Created after date (YYYY-MM-DD)"),
    before: str | None = typer.Option(None, "--before", help="Created before date (YYYY-MM-DD)"),
    path_glob: str | None = typer.Option(None, "--path", help="Glob filter on path"),
    min_words: int | None = typer.Option(None, "--min-words", help="Minimum word count"),
    max_words: int | None = typer.Option(None, "--max-words", help="Maximum word count"),
    linked_from: str | None = typer.Option(None, "--linked-from", help="Only notes linked FROM this note ID"),
    linked_to: str | None = typer.Option(None, "--linked-to", help="Only notes that link TO this note ID"),
    min_inbound: int | None = typer.Option(None, "--min-inbound", help="Minimum inbound link count"),
    has_backlinks: bool = typer.Option(False, "--has-backlinks", help="Only notes with backlinks"),
    include_body: bool = typer.Option(False, "--include-body", help="Include full note body (auto-enabled with --json)"),
    no_body: bool = typer.Option(False, "--no-body", help="Disable auto body inclusion in JSON mode"),
    limit: int = typer.Option(20, "--limit", "-l", help="Max results"),
    offset: int = typer.Option(0, "--offset", help="Offset for pagination"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Full-text search across all notes."""
    from hyperresearch.core.vault import Vault, VaultError
    from hyperresearch.search.filters import SearchFilters
    from hyperresearch.search.fts import search_fts

    try:
        vault = Vault.discover()
    except VaultError as e:
        if json_output:
            output(error(str(e), "NO_VAULT"), json_mode=True)
        else:
            console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)
    vault.auto_sync()

    filters = SearchFilters(
        tags=tag or None,
        status=status,
        note_type=note_type,
        parent=parent,
        after=after,
        before=before,
        path_glob=path_glob,
        min_words=min_words,
        max_words=max_words,
        linked_from=linked_from,
        linked_to=linked_to,
        min_inbound=min_inbound,
        has_backlinks=has_backlinks or None,
    )

    ranking = {
        "title_weight": vault.config.search_title_weight,
        "body_weight": vault.config.search_body_weight,
        "tags_weight": vault.config.search_tags_weight,
        "aliases_weight": vault.config.search_aliases_weight,
        "boost_evergreen": vault.config.search_boost_evergreen,
        "penalize_deprecated": vault.config.search_penalize_deprecated,
        "penalize_stale": vault.config.search_penalize_stale,
    }
    results = search_fts(vault.db, query, filters=filters, limit=limit, offset=offset, ranking=ranking)

    # Auto-include body in JSON mode (agents almost always need it)
    want_body = include_body or (json_output and not no_body)
    if want_body and results:
        for r in results:
            row = vault.db.execute(
                "SELECT body FROM note_content WHERE note_id = ?", (r["id"],)
            ).fetchone()
            r["body"] = row["body"] if row else ""

    if json_output:
        output(
            success(
                {"query": query, "results": results, "total": len(results)},
                count=len(results),
                vault=str(vault.root),
            ),
            json_mode=True,
        )
    else:
        if not results:
            console.print("[dim]No results found.[/]")
            return
        for r in results:
            tags_str = ", ".join(r.get("tags", []))
            console.print(
                f"  [cyan]{r['id']}[/] [bold]{r['title']}[/] "
                f"[dim]({r['status']})[/] [green]{tags_str}[/]"
            )
            if r.get("snippet"):
                console.print(f"    [dim]{r['snippet'][:200]}[/]")
            console.print()
