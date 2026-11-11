"""Claims persistence — fetcher-extracted claims as queryable DB rows.

Fetchers write `research/runs/<vault_tag>/temp/claims-<note-id>.json` files
during step 2 (and step 13's gap fetch); the legacy flat location
`research/temp/claims-*.json` is still honoured. This module ingests them
into the `claims` (+ `claims_fts`) tables, keyed to their source notes, so
downstream consumers can ask "which source best supports X" as a query
instead of re-parsing JSON files. This is the substrate for phase-5
cite-checking and numeric-consistency lints.

Ingest is idempotent: rows are keyed by (note_id, sha256(claim)[:16]), so
re-running over the same files is a no-op.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

# Claims files are written by agents from fetched (hostile) page content.
# Bound what one file can cost: a size cap before it is read into memory,
# and a per-field cap so one claim cannot bloat a row or the FTS index.
MAX_CLAIMS_FILE_BYTES = 8 * 1024 * 1024
MAX_CLAIM_FIELD_CHARS = 20_000


def _claim_hash(claim: str) -> str:
    return hashlib.sha256(claim.strip().encode("utf-8")).hexdigest()[:16]


def _text_field(value) -> str:
    """Coerce an untrusted claim field to bounded text ('' when absent).

    A claim JSON is agent-written from hostile page content, so a field
    can be any JSON type; sqlite3 refuses to bind lists/dicts and `.strip()`
    on a non-string would abort the whole ingest. Only strings count as
    text — a number, list or dict where prose belongs is dropped.
    """
    if not isinstance(value, str):
        return ""
    return value.strip()[:MAX_CLAIM_FIELD_CHARS]


def _scalar_field(value):
    """Numbers and short strings pass; anything else becomes None."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        return value[:MAX_CLAIM_FIELD_CHARS]
    return None


def _under(path: Path, root: Path) -> bool:
    """True if `path` resolves to `root` or somewhere below it."""
    try:
        path.resolve().relative_to(root.resolve())
    except (ValueError, OSError):
        return False
    return True


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
        size = path.stat().st_size
    except OSError as e:
        result["errors"].append(f"unreadable JSON: {e}")
        return result
    if size > MAX_CLAIMS_FILE_BYTES:
        result["errors"].append(
            f"claims file is {size} bytes (limit {MAX_CLAIMS_FILE_BYTES}); skipped"
        )
        return result
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError, RecursionError) as e:
        result["errors"].append(f"unreadable JSON: {e}")
        return result

    now = datetime.now(UTC).isoformat()
    for c in _iter_claim_dicts(data):
        claim_text = _text_field(c.get("claim")) or _text_field(c.get("text"))
        if not claim_text:
            result["skipped"] += 1
            continue
        h = _claim_hash(claim_text)
        numbers = c.get("numbers")
        try:
            cur = conn.execute(
                """INSERT OR IGNORE INTO claims
                   (note_id, claim, claim_hash, quoted_support, numbers, confidence,
                    evidence_type, stance_target, stance, vault_tag, ingested_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    note_id,
                    claim_text,
                    h,
                    _text_field(c.get("quoted_support")) or None,
                    json.dumps(numbers)[:MAX_CLAIM_FIELD_CHARS] if numbers else None,
                    _scalar_field(c.get("confidence")),
                    _text_field(c.get("evidence_type")) or None,
                    _text_field(c.get("stance_target")) or None,
                    _text_field(c.get("stance")) or None,
                    vault_tag,
                    now,
                ),
            )
            if cur.rowcount:
                claim_id = cur.lastrowid
                conn.execute(
                    "INSERT INTO claims_fts (claim_id, claim, quoted_support) VALUES (?, ?, ?)",
                    (claim_id, claim_text, _text_field(c.get("quoted_support"))),
                )
                result["ingested"] += 1
            else:
                result["skipped"] += 1
        except sqlite3.Error as e:
            # One malformed claim (agent-written from fetched, hostile page
            # content) must not abort the whole ingest.
            result["errors"].append(f"claim {h} not stored: {e}")
            result["skipped"] += 1
    return result


def _glob_claims(directory: Path) -> list[Path]:
    return sorted(directory.glob("claims-*.json")) if directory.is_dir() else []


def default_claims_dirs(vault, vault_tag: str | None = None) -> list[Path]:
    """Directories a default (no explicit `temp_dir`) ingest scans.

    With a `vault_tag` whose run workspace exists, exactly that run's
    `research/runs/<vault_tag>/temp/`. Otherwise the union of the legacy
    flat `research/temp/` and every `research/runs/*/temp/` — the fetcher
    contract writes claims into the run workspace, so a scan limited to
    the flat directory sees nothing in a real run.
    """
    research = vault.root / "research"
    runs = research / "runs"
    if vault_tag:
        # `vault_tag` is a CLI argument (an agent may have been talked into
        # it): a tag like `../../..` or an absolute path must not point the
        # scan outside research/runs/. Only a tag that resolves under the
        # runs directory narrows the scan; anything else falls through to
        # the default union.
        run_temp = runs / vault_tag / "temp"
        if _under(run_temp, runs) and run_temp.is_dir():
            return [run_temp]
    dirs = [research / "temp"]
    if runs.is_dir():
        dirs.extend(sorted(d / "temp" for d in runs.iterdir() if d.is_dir()))
    return dirs


def discover_claims_files(vault, vault_tag: str | None = None) -> list[Path]:
    """Every claims-*.json a default ingest would read, deduplicated by
    resolved path and sorted. Files that resolve outside the vault (a
    symlink planted in a run workspace) are skipped."""
    seen: set[Path] = set()
    files: list[Path] = []
    for d in default_claims_dirs(vault, vault_tag):
        for f in _glob_claims(d):
            if not _under(f, vault.root):
                continue
            key = f.resolve()
            if key in seen:
                continue
            seen.add(key)
            files.append(f)
    return sorted(files)


def ingest_claims_dir(vault, temp_dir: Path | None = None, vault_tag: str | None = None) -> dict:
    """Ingest claims-*.json files. Returns a summary.

    `temp_dir` given: scan exactly that directory (no recursion). Otherwise
    scan `default_claims_dirs(vault, vault_tag)` — the run workspace for
    `vault_tag` when it exists, else legacy `research/temp/` plus every
    `research/runs/*/temp/`. `vault_tag` is also stamped on every row.
    """
    conn = vault.db
    if temp_dir is None:
        scanned = default_claims_dirs(vault, vault_tag)
        files = discover_claims_files(vault, vault_tag)
    else:
        scanned = [temp_dir]
        files = _glob_claims(temp_dir)
    summary = {
        "files": len(files),
        "ingested": 0,
        "skipped": 0,
        "errors": [],
        "scanned": [str(d) for d in scanned],
    }
    if not files:
        summary["hint"] = (
            "no claims-*.json found under "
            + ", ".join(summary["scanned"])
            + "; fetchers write research/runs/<vault_tag>/temp/claims-<note-id>.json "
            "-- pass --tag <vault_tag> or the files explicitly"
        )
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
    claim_scope = " AND vault_tag = ?" if vault_tag else ""
    for row in rows:
        top = conn.execute(
            f"""SELECT claim FROM claims WHERE note_id = ?{claim_scope}
               ORDER BY (CASE WHEN evidence_type IN ('empirical','statistical') THEN 0 ELSE 1 END),
                        (CASE WHEN numbers IS NOT NULL THEN 0 ELSE 1 END),
                        (CASE WHEN confidence = 'high' THEN 0 ELSE 1 END),
                        id
               LIMIT 1""",
            (row["id"], *params),
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
