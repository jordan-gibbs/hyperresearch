"""Composite source-quality scoring.

quality_score = renormalized weighted sum of the available components:

    tier weight        (from [ranking] tier_* map; None when tier unset)
    utility_score / 18 (step-2 fetch-selection composite, when persisted)
    authority_score    (vault-relative citation percentile, when enriched)
    centrality_score   (vault PageRank, when computed)

Missing components renormalize — a source with only a tier still gets a
meaningful score instead of being zeroed for lacking a DOI. Retracted
sources are floored at `retraction_floor` regardless of everything else.

Scores live only in the DB (recomputable cache); they are never written to
frontmatter.
"""

from __future__ import annotations

from hyperresearch.core.config import RankingSettings

UTILITY_MAX = 18.0


def compute_quality_for_row(
    ranking: RankingSettings,
    tier: str | None,
    utility_score: float | None,
    authority_score: float | None,
    centrality_score: float | None,
    is_retracted: bool,
) -> float | None:
    """Composite for one note. None when no component is available at all."""
    if is_retracted:
        return ranking.retraction_floor

    components: list[tuple[float, float]] = []  # (weight, value)
    tier_w = ranking.tier_weight(tier)
    if tier_w is not None:
        components.append((ranking.w_tier, tier_w))
    if utility_score is not None:
        components.append((ranking.w_utility, min(max(utility_score / UTILITY_MAX, 0.0), 1.0)))
    if authority_score is not None:
        components.append((ranking.w_authority, min(max(authority_score, 0.0), 1.0)))
    if centrality_score is not None:
        components.append((ranking.w_centrality, min(max(centrality_score, 0.0), 1.0)))

    if not components:
        return None
    total_weight = sum(w for w, _ in components)
    if total_weight <= 0:
        return None
    return sum(w * v for w, v in components) / total_weight


def compute_quality_scores(conn, ranking: RankingSettings) -> int:
    """Recompute quality_score for every note. Returns count updated."""
    rows = conn.execute(
        "SELECT id, tier, utility_score, authority_score, centrality_score, is_retracted "
        "FROM notes"
    ).fetchall()
    updated = 0
    for row in rows:
        q = compute_quality_for_row(
            ranking,
            row["tier"],
            row["utility_score"],
            row["authority_score"],
            row["centrality_score"],
            bool(row["is_retracted"]),
        )
        conn.execute("UPDATE notes SET quality_score = ? WHERE id = ?", (q, row["id"]))
        updated += 1
    conn.commit()
    return updated
