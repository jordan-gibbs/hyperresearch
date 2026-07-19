"""Independence audit — syndicated copies must not multiply consensus.

"3+ independent sources agree" is the pipeline's consensus rule, but a wire
story republished by five outlets is ONE source wearing five outfits.
This module clusters derivative sources three ways:

  url     — identical canonical URL (scheme/www/trailing-slash/UTM stripped)
  body    — near-duplicate bodies (>=0.7 MinHash-verified Jaccard, reusing
            core/similarity.py)
  wire    — shared wire-service boilerplate (PRNewswire, Business Wire, ...)
            in the opening of the text, same story cluster by title overlap

Scores: cluster root (earliest fetched) keeps independence 1.0; members get
1/cluster_size. Unclustered notes get 1.0. Stored on notes.independence
(DB-cache, recomputable) and consumed by step 3's consensus counting and
the quality composite.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from hyperresearch.core.similarity import jaccard, shingle

WIRE_MARKERS = (
    "prnewswire", "pr newswire", "business wire", "businesswire",
    "globe newswire", "globenewswire", "(reuters)", "(ap)", "associated press",
    "accesswire", "newsfile corp",
)

_TRACKING_PARAMS_RE = re.compile(r"^(utm_|fbclid|gclid|ref$|source$)")
NEAR_DUP_THRESHOLD = 0.7


def canonical_url(url: str) -> str:
    """Normalize scheme/host/path/query so syndication mirrors collide."""
    p = urlparse(url.strip().lower())
    host = p.netloc.removeprefix("www.")
    path = p.path.rstrip("/")
    query = urlencode(sorted(
        (k, v) for k, v in parse_qsl(p.query) if not _TRACKING_PARAMS_RE.match(k)
    ))
    return urlunparse(("https", host, path, "", query, ""))


def _wire_signature(body: str, title: str) -> str | None:
    """Wire-marker + body-opening signature for press-release clustering.

    Keyed on the body head, NOT the title — outlets retitle syndicated
    copy, but the wire text itself opens identically.
    """
    head = (body or "")[:1500].lower()
    marker = next((m for m in WIRE_MARKERS if m in head), None)
    if marker is None:
        return None
    tokens = re.findall(r"[a-z0-9]{4,}", head)[:10]
    return f"{marker}|{' '.join(tokens)}"


def compute_independence(vault, tag: str | None = None) -> dict:
    """Cluster derivative sources, write independence scores. Returns summary."""
    conn = vault.db
    query = (
        "SELECT n.id, n.source, n.title, n.created, nc.body_plain "
        "FROM notes n JOIN note_content nc ON nc.note_id = n.id "
        "WHERE n.source IS NOT NULL AND n.type NOT IN ('index')"
    )
    params: tuple = ()
    if tag:
        query += " AND n.id IN (SELECT note_id FROM tags WHERE tag = ?)"
        params = (tag,)
    rows = [dict(r) for r in conn.execute(query, params).fetchall()]

    # Union-find over note ids
    parent: dict[str, str] = {r["id"]: r["id"] for r in rows}
    cluster_kind: dict[frozenset, str] = {}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str, kind: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra
        cluster_kind[frozenset((a, b))] = kind

    # 1. Canonical-URL identity
    by_url: dict[str, list[dict]] = {}
    for r in rows:
        by_url.setdefault(canonical_url(r["source"]), []).append(r)
    for group in by_url.values():
        for other in group[1:]:
            union(group[0]["id"], other["id"], "url")

    # 2. Wire-service signature
    by_wire: dict[str, list[dict]] = {}
    for r in rows:
        sig = _wire_signature(r["body_plain"], r["title"])
        if sig:
            by_wire.setdefault(sig, []).append(r)
    for group in by_wire.values():
        for other in group[1:]:
            union(group[0]["id"], other["id"], "wire")

    # 3. Near-duplicate bodies (pairwise Jaccard on shingles; vaults are
    # small enough per-tag, and dedup's MinHash/LSH path exists for scale)
    shingles = {r["id"]: shingle(r["body_plain"] or "", n=vault.config.dedup.shingle_size) for r in rows}
    ids = [r["id"] for r in rows]
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            if find(ids[i]) == find(ids[j]):
                continue
            if jaccard(shingles[ids[i]], shingles[ids[j]]) >= NEAR_DUP_THRESHOLD:
                union(ids[i], ids[j], "body")

    # Materialize clusters; root = earliest fetched (the upstream original)
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(find(r["id"]), []).append(r)

    clusters = []
    scored = 0
    for members in groups.values():
        if len(members) == 1:
            conn.execute("UPDATE notes SET independence = 1.0 WHERE id = ?", (members[0]["id"],))
            scored += 1
            continue
        members.sort(key=lambda r: r["created"] or "")
        root = members[0]
        share = round(1.0 / len(members), 4)
        conn.execute("UPDATE notes SET independence = 1.0 WHERE id = ?", (root["id"],))
        kinds = {
            cluster_kind.get(frozenset((a["id"], b["id"])))
            for a in members for b in members
            if cluster_kind.get(frozenset((a["id"], b["id"])))
        }
        for m in members[1:]:
            conn.execute("UPDATE notes SET independence = ? WHERE id = ?", (share, m["id"]))
        scored += len(members)
        clusters.append({
            "root": root["id"],
            "members": [m["id"] for m in members[1:]],
            "size": len(members),
            "kind": "+".join(sorted(k for k in kinds if k)) or "mixed",
        })
    conn.commit()
    return {"scored": scored, "clusters": clusters}
