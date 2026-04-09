"""Tag management CLI — list, alias, suggest merges, clean."""

from __future__ import annotations

from difflib import SequenceMatcher

import typer

from hyperresearch.cli._output import console, output
from hyperresearch.models.output import success

app = typer.Typer()


@app.command("list")
def tag_list(
    min_count: int = typer.Option(1, "--min", "-m", help="Only show tags with N+ notes"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """List all tags with note counts."""
    from hyperresearch.core.vault import Vault

    vault = Vault.discover()
    vault.auto_sync()
    rows = vault.db.execute(
        "SELECT tag, COUNT(*) as count FROM tags GROUP BY tag HAVING count >= ? ORDER BY count DESC",
        (min_count,),
    ).fetchall()
    tags = [{"tag": r["tag"], "count": r["count"]} for r in rows]

    if json_output:
        output(success(tags, count=len(tags), vault=str(vault.root)), json_mode=True)
    else:
        from rich.table import Table

        table = Table(title="Tags", show_header=True, header_style="bold")
        table.add_column("Tag", style="green")
        table.add_column("Notes", justify="right")
        for t in tags:
            table.add_row(t["tag"], str(t["count"]))
        console.print(table)


@app.command("alias")
def tag_alias(
    from_tag: str = typer.Argument(..., help="Tag to alias (the variant)"),
    to_tag: str = typer.Argument(..., help="Canonical tag to map to"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Create a tag alias. Notes with the variant tag will be indexed under the canonical tag."""
    from hyperresearch.core.vault import Vault

    vault = Vault.discover()
    vault.db.execute(
        "INSERT OR REPLACE INTO tag_aliases (alias, canonical) VALUES (?, ?)",
        (from_tag.lower(), to_tag.lower()),
    )
    vault.db.commit()

    if json_output:
        output(success({"alias": from_tag, "canonical": to_tag}, vault=str(vault.root)), json_mode=True)
    else:
        console.print(f"[green]Alias:[/] {from_tag} -> {to_tag}")
        console.print("[dim]Run 'hyperresearch sync --force' to apply.[/]")


@app.command("suggest")
def tag_suggest(
    threshold: float = typer.Option(0.7, "--threshold", help="Similarity threshold"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Suggest tag merges based on string similarity."""
    from hyperresearch.core.vault import Vault

    vault = Vault.discover()
    vault.auto_sync()

    rows = vault.db.execute(
        "SELECT tag, COUNT(*) as count FROM tags GROUP BY tag ORDER BY count DESC"
    ).fetchall()
    tags = [(r["tag"], r["count"]) for r in rows]

    # Find similar tag pairs
    suggestions = []
    popular = [t for t in tags if t[1] >= 3]
    singletons = [t for t in tags if t[1] == 1]

    for stag, _scount in singletons:
        for ptag, pcount in popular:
            sim = SequenceMatcher(None, stag, ptag).ratio()
            if sim >= threshold and stag != ptag:
                suggestions.append({
                    "singleton": stag,
                    "suggested_canonical": ptag,
                    "similarity": round(sim, 2),
                    "canonical_count": pcount,
                })
                break  # Best match

        # Also catch simple plurals
    tag_set = {t[0] for t in tags}
    for stag, _sc in singletons:
        if stag.endswith("s") and stag[:-1] in tag_set and stag not in [s["singleton"] for s in suggestions]:
            suggestions.append({"singleton": stag, "suggested_canonical": stag[:-1],
                "similarity": 0.95, "canonical_count": next((c for t, c in tags if t == stag[:-1]), 0)})

    suggestions.sort(key=lambda s: s["similarity"], reverse=True)

    if json_output:
        output(success(suggestions, count=len(suggestions), vault=str(vault.root)), json_mode=True)
    else:
        if not suggestions:
            console.print("[dim]No merge suggestions found.[/]")
            return
        console.print(f"[bold]Suggested merges ({len(suggestions)}):[/]\n")
        for s in suggestions[:30]:
            console.print(
                f"  {s['singleton']:30s} -> {s['suggested_canonical']:20s} "
                f"({s['similarity']:.0%} similar, {s['canonical_count']} notes)"
            )
        console.print("\n[dim]Apply with: hyperresearch tag alias <from> <to>[/]")
