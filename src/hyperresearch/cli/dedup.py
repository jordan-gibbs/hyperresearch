"""Content deduplication — find near-duplicate notes."""

from __future__ import annotations

import typer

from hyperresearch.cli._output import console, output
from hyperresearch.core.similarity import jaccard, shingle
from hyperresearch.models.output import success


def dedup(
    threshold: float = typer.Option(0.6, "--threshold", "-t", help="Similarity threshold (0.0-1.0)"),
    limit: int = typer.Option(20, "--limit", "-l", help="Max pairs to show"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Find near-duplicate notes by content similarity."""
    from hyperresearch.core.vault import Vault, VaultError

    try:
        vault = Vault.discover()
    except VaultError as e:
        if json_output:
            output({"ok": False, "error": str(e)}, json_mode=True)
        else:
            console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)

    vault.auto_sync()

    # Load all note content
    rows = vault.db.execute(
        "SELECT n.id, n.title, n.word_count, nc.body_plain "
        "FROM notes n JOIN note_content nc ON n.id = nc.note_id "
        "WHERE n.type NOT IN ('index') AND n.word_count > 20 "
        "ORDER BY n.id"
    ).fetchall()

    if len(rows) < 2:
        if json_output:
            output(success({"pairs": [], "total_compared": 0}, vault=str(vault.root)), json_mode=True)
        else:
            console.print("[dim]Not enough notes to compare.[/]")
        return

    # Build shingle sets
    notes = []
    for row in rows:
        shingles = shingle(row["body_plain"])
        notes.append({
            "id": row["id"],
            "title": row["title"],
            "word_count": row["word_count"],
            "shingles": shingles,
        })

    # Compare all pairs
    pairs = []
    for i in range(len(notes)):
        for j in range(i + 1, len(notes)):
            sim = jaccard(notes[i]["shingles"], notes[j]["shingles"])
            if sim >= threshold:
                pairs.append({
                    "similarity": round(sim, 3),
                    "note_a": {"id": notes[i]["id"], "title": notes[i]["title"], "words": notes[i]["word_count"]},
                    "note_b": {"id": notes[j]["id"], "title": notes[j]["title"], "words": notes[j]["word_count"]},
                })

    pairs.sort(key=lambda p: p["similarity"], reverse=True)
    pairs = pairs[:limit]

    total_compared = len(notes) * (len(notes) - 1) // 2

    if json_output:
        output(
            success({"pairs": pairs, "total_compared": total_compared, "threshold": threshold},
                    count=len(pairs), vault=str(vault.root)),
            json_mode=True,
        )
    else:
        if not pairs:
            console.print(f"[green]No duplicates found (threshold {threshold:.0%}, compared {total_compared} pairs).[/]")
            return

        console.print(f"[bold]Similar notes (>{threshold:.0%}):[/]\n")
        for p in pairs:
            a, b = p["note_a"], p["note_b"]
            console.print(
                f"  [bold]{p['similarity']:.0%}[/] | "
                f"[cyan]{a['id']}[/] ({a['words']}w) "
                f"<-> [cyan]{b['id']}[/] ({b['words']}w)"
            )
        console.print(f"\n[dim]Compared {total_compared} pairs.[/]")
