"""Claims persistence — fetcher-extracted claims as queryable DB rows.

Fetchers write `research/temp/claims-<note-id>.json` files during step 2.
This module ingests them into the `claims` (+ `claims_fts`) tables, keyed to
their source notes, so downstream consumers can ask "which source best
supports X" as a query instead of re-parsing JSON files. This is the
substrate for phase-5 cite-checking and numeric-consistency lints.

Ingest is idempotent: rows are keyed by (note_id, sha256(claim)[:16]), so
re-running over the same files is a no-op.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path


def _claim_hash(claim: str) -> str:
    return hashlib.sha256(claim.strip().encode("utf-8")).hexdigest()[:16]


def _note_id_from_filename(path: Path) -> str | None:
    """claims-<note-id>.json -> <note-id>."""
    stem = path.stem
    if stem.startswith("claims-"):
        return stem[len("claims-"):]
    return None


def _iter_claim_dicts(data) -> list[dict]:
    """Accept both bare-list files and {claims: [...]} wrappers."""
    if isinstance(data, list):
        return [c for c in data if isinstance(c, dict)]
    if isinstance(data, dict):
        inner = data.get("claims", [])
        if isinstance(inner, list):
            return [c for c in inner if isinstance(c, dict)]
    return []


def ingest_claims_file(conn, path: Path, vault_tag: str | None = None) -> dict:
    """Ingest one claims JSON file. Returns {ingested, skipped, errors}."""
    note_id = _note_id_from_filename(path)
    result = {"file": str(path), "note_id": note_id, "ingested": 0, "skipped": 0, "errors": []}
    if note_id is None:
        result["errors"].append("filename does not match claims-<note-id>.json")
        return result

    note_row = conn.execute("SELECT id FROM notes WHERE id = ?", (note_id,)).fetchone()
    if note_row is None:
        result["errors"].append(f"note '{note_id}' not in vault (sync first?)")
        return result

    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError) as e:
        result["errors"].append(f"unreadable JSON: {e}")
        return result

    now = datetime.now(UTC).isoformat()
    for c in _iter_claim_dicts(data):
        claim_text = (c.get("claim") or c.get("text") or "").strip()
        if not claim_text:
            result["skipped"] += 1
            continue
        h = _claim_hash(claim_text)
        numbers = c.get("numbers")
        cur = conn.execute(
            """INSERT OR IGNORE INTO claims
               (note_id, claim, claim_hash, quoted_support, numbers, confidence,
                evidence_type, stance_target, stance, vault_tag, ingested_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                note_id,
                claim_text,
                h,
                c.get("quoted_support"),
                json.dumps(numbers) if numbers else None,
                c.get("confidence"),
                c.get("evidence_type"),
                c.get("stance_target"),
                c.get("stance"),
                vault_tag,
                now,
            ),
        )
        if cur.rowcount:
            claim_id = cur.lastrowid
            conn.execute(
                "INSERT INTO claims_fts (claim_id, claim, quoted_support) VALUES (?, ?, ?)",
                (claim_id, claim_text, c.get("quoted_support") or ""),
            )
            result["ingested"] += 1
        else:
            result["skipped"] += 1
    return result


def ingest_claims_dir(vault, temp_dir: Path | None = None, vault_tag: str | None = None) -> dict:
    """Ingest every claims-*.json under research/temp/. Returns a summary."""
    conn = vault.db
    if temp_dir is None:
        temp_dir = vault.root / "research" / "temp"
    files = sorted(temp_dir.glob("claims-*.json")) if temp_dir.is_dir() else []
    summary = {"files": len(files), "ingested": 0, "skipped": 0, "errors": []}
    for f in files:
        r = ingest_claims_file(conn, f, vault_tag)
        summary["ingested"] += r["ingested"]
        summary["skipped"] += r["skipped"]
        for e in r["errors"]:
            summary["errors"].append(f"{f.name}: {e}")
    conn.commit()
    return summary


def search_claims(conn, query: str, limit: int = 20) -> list[dict]:
    """FTS search over claims + quoted support."""
    rows = conn.execute(
        """SELECT c.id, c.note_id, c.claim, c.quoted_support, c.numbers,
                  c.confidence, c.evidence_type, c.stance_target, c.stance, c.vault_tag
           FROM claims_fts f JOIN claims c ON c.id = f.claim_id
           WHERE claims_fts MATCH ?
           ORDER BY rank LIMIT ?""",
        (query, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def list_claims(
    conn,
    note_id: str | None = None,
    vault_tag: str | None = None,
    limit: int = 100,
) -> list[dict]:
    query = (
        "SELECT id, note_id, claim, quoted_support, numbers, confidence, "
        "evidence_type, stance_target, stance, vault_tag FROM claims"
    )
    conds, params = [], []
    if note_id:
        conds.append("note_id = ?")
        params.append(note_id)
    if vault_tag:
        conds.append("vault_tag = ?")
        params.append(vault_tag)
    if conds:
        query += " WHERE " + " AND ".join(conds)
    query += " ORDER BY id LIMIT ?"
    params.append(limit)
    return [dict(r) for r in conn.execute(query, params).fetchall()]


def literature_matrix(conn, vault_tag: str | None = None) -> list[dict]:
    """Per-source literature-review rows: source metadata + claim digest.

    The dissertation-scale artifact: one row per source note that has claims,
    carrying tier/quality/venue plus a digest of what its claims establish.
    Sorted by quality_score (best evidence first), None-quality last.
    """
    query = """
        SELECT n.id, n.title, n.tier, n.content_type, n.venue,
               n.citation_count, n.is_retracted, n.quality_score,
               n.created, n.source,
               COUNT(c.id) AS n_claims,
               SUM(CASE WHEN c.evidence_type IN ('empirical','statistical') THEN 1 ELSE 0 END) AS n_empirical,
               SUM(CASE WHEN c.numbers IS NOT NULL THEN 1 ELSE 0 END) AS n_quantified
        FROM claims c JOIN notes n ON n.id = c.note_id
    """
    params: list = []
    if vault_tag:
        query += " WHERE c.vault_tag = ?"
        params.append(vault_tag)
    query += " GROUP BY n.id"
    rows = [dict(r) for r in conn.execute(query, params).fetchall()]

    # Attach each source's single highest-signal claim (empirical + quantified first)
    for row in rows:
        top = conn.execute(
            """SELECT claim FROM claims WHERE note_id = ?
               ORDER BY (CASE WHEN evidence_type IN ('empirical','statistical') THEN 0 ELSE 1 END),
                        (CASE WHEN numbers IS NOT NULL THEN 0 ELSE 1 END),
                        (CASE WHEN confidence = 'high' THEN 0 ELSE 1 END),
                        id
               LIMIT 1""",
            (row["id"],),
        ).fetchone()
        row["key_claim"] = top["claim"] if top else None

    rows.sort(key=lambda r: (r["quality_score"] is None, -(r["quality_score"] or 0.0)))
    return rows


def render_matrix_markdown(rows: list[dict]) -> str:
    """Render literature_matrix rows as a markdown table."""
    lines = [
        "| Source | Tier | Type | Venue | Cites | Quality | Claims (emp/quant) | Key finding |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        quality = f"{r['quality_score']:.2f}" if r["quality_score"] is not None else "-"
        retracted = " **RETRACTED**" if r["is_retracted"] else ""
        key = (r["key_claim"] or "").replace("|", "/")[:140]
        lines.append(
            f"| [[{r['id']}]]{retracted} | {r['tier'] or '-'} | {r['content_type'] or '-'} "
            f"| {r['venue'] or '-'} | {r['citation_count'] if r['citation_count'] is not None else '-'} "
            f"| {quality} | {r['n_claims']} ({r['n_empirical'] or 0}/{r['n_quantified'] or 0}) | {key} |"
        )
    return "\n".join(lines) + "\n"


def group_by_target(conn, vault_tag: str | None = None, min_sources: int = 2) -> list[dict]:
    """Group claims by stance_target across sources — the meta-analysis substrate.

    Returns targets addressed by >= min_sources distinct sources, with stance
    split and every quantified value (source-attributed) so the orchestrator
    can build comparison tables and flag outliers.
    """
    query = """
        SELECT stance_target,
               COUNT(DISTINCT note_id) AS n_sources,
               COUNT(*) AS n_claims
        FROM claims
        WHERE stance_target IS NOT NULL AND stance_target != ''
    """
    params: list = []
    if vault_tag:
        query += " AND vault_tag = ?"
        params.append(vault_tag)
    query += " GROUP BY stance_target HAVING COUNT(DISTINCT note_id) >= ? ORDER BY n_sources DESC"
    params.append(min_sources)

    groups = []
    for row in conn.execute(query, params).fetchall():
        target = row["stance_target"]
        detail_params: list = [target]
        detail_query = (
            "SELECT note_id, stance, numbers, claim FROM claims WHERE stance_target = ?"
        )
        if vault_tag:
            detail_query += " AND vault_tag = ?"
            detail_params.append(vault_tag)
        details = conn.execute(detail_query, detail_params).fetchall()
        stances: dict[str, int] = {}
        values = []
        for d in details:
            s = d["stance"] or "unspecified"
            stances[s] = stances.get(s, 0) + 1
            if d["numbers"]:
                try:
                    values.append({"note_id": d["note_id"], "numbers": json.loads(d["numbers"])})
                except json.JSONDecodeError:
                    pass
        groups.append({
            "stance_target": target,
            "n_sources": row["n_sources"],
            "n_claims": row["n_claims"],
            "stances": stances,
            "quantified": values,
        })
    return groups
