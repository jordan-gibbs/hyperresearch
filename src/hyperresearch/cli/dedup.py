"""Content deduplication — find near-duplicate notes using MinHash+LSH."""

from __future__ import annotations

import typer

from hyperresearch.cli._output import console, output
from hyperresearch.core.similarity import (
    jaccard,
    lsh_candidates,
    minhash_signature,
    shingle,
)
from hyperresearch.models.output import success

# Use MinHash+LSH for vaults above this size, O(n^2) below
LSH_THRESHOLD = 200


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
    notes = {}
    for row in rows:
        shingles = shingle(row["body_plain"])
        notes[row["id"]] = {
            "id": row["id"],
            "title": row["title"],
            "word_count": row["word_count"],
            "shingles": shingles,
        }

    # Choose algorithm based on vault size
    if len(notes) >= LSH_THRESHOLD:
        pairs = _dedup_lsh(notes, threshold)
        method = "minhash+lsh"
    else:
        pairs = _dedup_brute(notes, threshold)
        method = "brute-force"

    pairs.sort(key=lambda p: p["similarity"], reverse=True)
    pairs = pairs[:limit]

    total_compared = len(notes) * (len(notes) - 1) // 2

    if json_output:
        output(
            success(
                {"pairs": pairs, "total_compared": total_compared, "threshold": threshold, "method": method},
                count=len(pairs), vault=str(vault.root),
            ),
            json_mode=True,
        )
    else:
        if not pairs:
            console.print(f"[green]No duplicates found (threshold {threshold:.0%}, {method}).[/]")
            return

        console.print(f"[bold]Similar notes (>{threshold:.0%}, {method}):[/]\n")
        for p in pairs:
            a, b = p["note_a"], p["note_b"]
            console.print(
                f"  [bold]{p['similarity']:.0%}[/] | "
                f"[cyan]{a['id']}[/] ({a['words']}w) "
                f"<-> [cyan]{b['id']}[/] ({b['words']}w)"
            )
        console.print(f"\n[dim]{len(notes)} notes, {method}.[/]")


def _dedup_brute(notes: dict, threshold: float) -> list[dict]:
    """O(n^2) brute-force comparison for small vaults."""
    note_list = list(notes.values())
    pairs = []
    for i in range(len(note_list)):
        for j in range(i + 1, len(note_list)):
            sim = jaccard(note_list[i]["shingles"], note_list[j]["shingles"])
            if sim >= threshold:
                pairs.append(_make_pair(note_list[i], note_list[j], sim))
    return pairs


def _dedup_lsh(notes: dict, threshold: float) -> list[dict]:
    """MinHash+LSH for large vaults — approximate but O(n)."""
    # Compute signatures
    signatures = {}
    for nid, note in notes.items():
        signatures[nid] = minhash_signature(note["shingles"])

    # Find candidate pairs via LSH
    candidates = lsh_candidates(signatures)

    # Verify candidates with exact Jaccard
    pairs = []
    for id_a, id_b in candidates:
        sim = jaccard(notes[id_a]["shingles"], notes[id_b]["shingles"])
        if sim >= threshold:
            pairs.append(_make_pair(notes[id_a], notes[id_b], sim))
    return pairs


def _make_pair(a: dict, b: dict, sim: float) -> dict:
    return {
        "similarity": round(sim, 3),
        "note_a": {"id": a["id"], "title": a["title"], "words": a["word_count"]},
        "note_b": {"id": b["id"], "title": b["title"], "words": b["word_count"]},
    }
