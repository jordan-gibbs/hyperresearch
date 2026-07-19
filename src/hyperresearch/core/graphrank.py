"""Vault centrality — PageRank over the note link graph.

The graph is the `links` table: wiki-links plus the `--suggested-by`
provenance breadcrumbs (which land in `links` because breadcrumbs are body
wiki-links). Centrality in THIS graph means "many independent research
chains converged on this source" — a strong load-bearing signal precisely
because fetcher chasing is citation-driven.

Pure-Python power iteration; vaults are thousands of nodes, not millions.
Scores are normalized by the maximum (top note = 1.0) and stored to
`notes.centrality_score` (DB-cache only, recomputable).
"""

from __future__ import annotations

DAMPING = 0.85
MAX_ITERATIONS = 50
CONVERGENCE = 1e-6


def pagerank(
    nodes: list[str],
    edges: list[tuple[str, str]],
    damping: float = DAMPING,
    max_iterations: int = MAX_ITERATIONS,
    convergence: float = CONVERGENCE,
) -> dict[str, float]:
    """Standard PageRank with dangling-node handling. Returns raw scores."""
    if not nodes:
        return {}
    n = len(nodes)
    node_set = set(nodes)

    # Deduplicate edges; drop self-loops and edges to unknown nodes
    out: dict[str, set[str]] = {node: set() for node in nodes}
    for src, dst in edges:
        if src in node_set and dst in node_set and src != dst:
            out[src].add(dst)

    incoming: dict[str, list[str]] = {node: [] for node in nodes}
    for src, targets in out.items():
        for dst in targets:
            incoming[dst].append(src)

    rank = dict.fromkeys(nodes, 1.0 / n)
    base = (1.0 - damping) / n

    for _ in range(max_iterations):
        dangling_mass = sum(rank[node] for node in nodes if not out[node])
        new_rank = {}
        for node in nodes:
            incoming_sum = sum(rank[src] / len(out[src]) for src in incoming[node])
            new_rank[node] = base + damping * (incoming_sum + dangling_mass / n)
        delta = sum(abs(new_rank[node] - rank[node]) for node in nodes)
        rank = new_rank
        if delta < convergence:
            break
    return rank


def compute_centrality(conn) -> int:
    """Compute and store normalized centrality for all notes. Returns count."""
    nodes = [row["id"] for row in conn.execute("SELECT id FROM notes").fetchall()]
    if not nodes:
        return 0
    edges = [
        (row["source_id"], row["target_id"])
        for row in conn.execute(
            "SELECT source_id, target_id FROM links WHERE target_id IS NOT NULL"
        ).fetchall()
    ]
    scores = pagerank(nodes, edges)
    max_score = max(scores.values()) if scores else 0.0
    if max_score <= 0:
        return 0
    for note_id, score in scores.items():
        conn.execute(
            "UPDATE notes SET centrality_score = ? WHERE id = ?",
            (score / max_score, note_id),
        )
    conn.commit()
    return len(scores)
