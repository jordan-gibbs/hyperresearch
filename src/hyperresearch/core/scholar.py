"""Scholarly metadata — DOI extraction and citation-graph enrichment.

Two responsibilities:

1. `extract_doi(url, raw_html, content)` — best-effort DOI / arXiv-id capture
   at fetch time (URL patterns, `citation_doi` meta tags, in-body "DOI:"
   markers). Stored in note frontmatter as `doi:`.

2. `score_sources(vault, ...)` — batch enrichment of DOI-bearing notes from
   free scholarly APIs (OpenAlex primary, Semantic Scholar for arXiv ids and
   fallback). Populates `citation_count`, `venue`, `is_retracted` in BOTH the
   note frontmatter (markdown stays truth) and the DB row, then recomputes
   `authority_score` as a vault-relative log-scaled percentile.

All HTTP goes through `_fetch_json`, which consults the `api_cache` table
(TTL from `[ranking] api_cache_ttl_days`) before touching the network —
re-scoring a vault is cheap and offline-friendly. Tests monkeypatch
`_http_get_json`; no test ever hits the network.
"""

from __future__ import annotations

import json
import math
import re
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import quote, urlparse

DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"'<>\])}]+)", re.IGNORECASE)
ARXIV_URL_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5}(?:v\d+)?)", re.IGNORECASE)
META_DOI_RE = re.compile(
    r"<meta[^>]+(?:name|property)=[\"'](?:citation_doi|dc\.identifier)[\"'][^>]+"
    r"content=[\"']\s*(?:doi:)?\s*(10\.[^\"']+)[\"']",
    re.IGNORECASE,
)
BODY_DOI_RE = re.compile(r"\bDOI:?\s*(10\.\d{4,9}/[^\s\"'<>\])}]+)", re.IGNORECASE)

# Per-host courtesy delay between UNCACHED requests, seconds.
_HOST_DELAY = {
    "api.openalex.org": 0.15,
    "api.semanticscholar.org": 1.1,
    "api.crossref.org": 0.15,
}
_last_call: dict[str, float] = {}


def _clean_doi(doi: str) -> str:
    return doi.strip().rstrip(".,;")


def extract_doi(
    url: str,
    raw_html: str | None = None,
    content: str | None = None,
) -> str | None:
    """Best-effort DOI or arXiv-id extraction. Returns None when nothing found.

    Priority: URL DOI > arXiv URL > citation_doi meta tag > in-body DOI marker.
    arXiv ids are returned as "arXiv:<id>" so downstream code can route them
    to Semantic Scholar (OpenAlex has no arXiv-id lookup scheme).
    """
    parsed = urlparse(url)
    if "doi.org" in parsed.netloc.lower():
        m = DOI_RE.search(parsed.path)
        if m:
            return _clean_doi(m.group(1))
    m = ARXIV_URL_RE.search(url)
    if m:
        return f"arXiv:{m.group(1)}"
    if raw_html:
        m = META_DOI_RE.search(raw_html)
        if m:
            return _clean_doi(m.group(1))
    if content:
        m = BODY_DOI_RE.search(content[:20000])
        if m:
            return _clean_doi(m.group(1))
    return None


# ---------------------------------------------------------------------------
# HTTP layer — cache-first, monkeypatchable
# ---------------------------------------------------------------------------


def _http_get_json(url: str) -> dict | None:
    """Raw HTTP GET returning parsed JSON, or None on any failure.

    Isolated so tests can monkeypatch it; every failure is soft — partial
    enrichment beats a crashed scoring run.
    """
    import httpx

    try:
        resp = httpx.get(
            url,
            follow_redirects=True,
            timeout=20,
            headers={"User-Agent": "hyperresearch (mailto:research@example.com)"},
        )
        if resp.status_code != 200:
            return None
        return resp.json()
    except Exception:
        return None


def _fetch_json(conn, url: str, ttl_days: int, fresh: bool = False) -> dict | None:
    """Cache-first JSON fetch through the api_cache table."""
    now = datetime.now(UTC)
    if not fresh:
        row = conn.execute("SELECT body, fetched_at FROM api_cache WHERE url = ?", (url,)).fetchone()
        if row:
            try:
                fetched = datetime.fromisoformat(row["fetched_at"])
            except ValueError:
                fetched = None
            if fetched and now - fetched < timedelta(days=ttl_days):
                try:
                    return json.loads(row["body"])
                except json.JSONDecodeError:
                    pass

    # Courtesy rate limit per host, only for real network calls
    host = urlparse(url).netloc.lower()
    delay = _HOST_DELAY.get(host, 0.2)
    elapsed = time.monotonic() - _last_call.get(host, 0.0)
    if elapsed < delay:
        time.sleep(delay - elapsed)
    _last_call[host] = time.monotonic()

    data = _http_get_json(url)
    if data is not None:
        conn.execute(
            "INSERT OR REPLACE INTO api_cache (url, body, fetched_at) VALUES (?, ?, ?)",
            (url, json.dumps(data), now.isoformat()),
        )
        conn.commit()
    return data


# ---------------------------------------------------------------------------
# Per-identifier metadata lookup
# ---------------------------------------------------------------------------


def lookup_metadata(conn, doi: str, ttl_days: int, fresh: bool = False) -> dict | None:
    """Resolve one DOI/arXiv id to {citation_count, venue, is_retracted}.

    OpenAlex is primary for DOIs (it carries is_retracted directly);
    Semantic Scholar handles arXiv ids and serves as DOI fallback.
    """
    if doi.lower().startswith("arxiv:"):
        arxiv_id = doi.split(":", 1)[1]
        data = _fetch_json(
            conn,
            "https://api.semanticscholar.org/graph/v1/paper/arXiv:"
            f"{quote(arxiv_id)}?fields=citationCount,venue,externalIds",
            ttl_days,
            fresh,
        )
        if data is None:
            return None
        return {
            "citation_count": data.get("citationCount"),
            "venue": data.get("venue") or None,
            "is_retracted": False,  # S2 has no retraction flag
        }

    data = _fetch_json(
        conn,
        f"https://api.openalex.org/works/doi:{quote(doi, safe='')}"
        "?select=cited_by_count,primary_location,is_retracted",
        ttl_days,
        fresh,
    )
    if data is not None:
        venue = None
        loc = data.get("primary_location") or {}
        src = loc.get("source") or {}
        venue = src.get("display_name")
        return {
            "citation_count": data.get("cited_by_count"),
            "venue": venue,
            "is_retracted": bool(data.get("is_retracted", False)),
        }

    # Fallback: Semantic Scholar by DOI
    data = _fetch_json(
        conn,
        "https://api.semanticscholar.org/graph/v1/paper/DOI:"
        f"{quote(doi, safe='')}?fields=citationCount,venue",
        ttl_days,
        fresh,
    )
    if data is None:
        return None
    return {
        "citation_count": data.get("citationCount"),
        "venue": data.get("venue") or None,
        "is_retracted": False,
    }


# ---------------------------------------------------------------------------
# Batch scoring
# ---------------------------------------------------------------------------


def backfill_dois(vault, tag: str | None = None) -> int:
    """Regex source URLs + bodies of existing notes for missed DOIs.

    Updates note frontmatter + DB. Returns count of notes that gained a doi.
    """
    from hyperresearch.core.frontmatter import parse_frontmatter, render_note

    conn = vault.db
    query = (
        "SELECT n.id, n.path, n.source FROM notes n "
        "WHERE n.doi IS NULL AND n.source IS NOT NULL"
    )
    params: tuple = ()
    if tag:
        query += " AND n.id IN (SELECT note_id FROM tags WHERE tag = ?)"
        params = (tag,)

    gained = 0
    for row in conn.execute(query, params).fetchall():
        note_path = vault.root / row["path"]
        if not note_path.exists():
            continue
        text = note_path.read_text(encoding="utf-8-sig")
        meta, body = parse_frontmatter(text)
        doi = extract_doi(row["source"] or "", content=body)
        if not doi:
            continue
        meta.doi = doi
        note_path.write_text(render_note(meta, body), encoding="utf-8")
        conn.execute("UPDATE notes SET doi = ? WHERE id = ?", (doi, row["id"]))
        gained += 1
    if gained:
        conn.commit()
    return gained


def compute_authority_scores(conn) -> int:
    """Vault-relative authority: percentile rank of log(1+citation_count).

    Percentile within the set of notes that HAVE a citation count, so a
    50-citation niche paper isn't crushed by a 10k-citation classic from
    another field. Notes without citation data keep authority NULL (the
    quality composite renormalizes around it).
    """
    rows = conn.execute(
        "SELECT id, citation_count FROM notes WHERE citation_count IS NOT NULL"
    ).fetchall()
    if not rows:
        return 0
    scored = sorted(rows, key=lambda r: math.log1p(r["citation_count"] or 0))
    n = len(scored)
    for rank, row in enumerate(scored):
        pct = (rank + 1) / n if n > 1 else 1.0
        conn.execute("UPDATE notes SET authority_score = ? WHERE id = ?", (pct, row["id"]))
    conn.commit()
    return n


def score_sources(
    vault,
    tag: str | None = None,
    fresh: bool = False,
    limit: int | None = None,
) -> dict:
    """Enrich DOI-bearing notes with citation metadata, then recompute
    authority percentiles and composite quality scores.

    Returns a summary dict: {scored, retracted, missing, authority_ranked}.
    """
    from hyperresearch.core.frontmatter import parse_frontmatter, render_note
    from hyperresearch.core.quality import compute_quality_scores

    conn = vault.db
    ttl = vault.config.ranking.api_cache_ttl_days

    query = "SELECT n.id, n.path, n.doi FROM notes n WHERE n.doi IS NOT NULL"
    params: tuple = ()
    if tag:
        query += " AND n.id IN (SELECT note_id FROM tags WHERE tag = ?)"
        params = (tag,)
    if not fresh:
        # Skip notes already enriched (still refreshed when --fresh)
        query += " AND n.citation_count IS NULL"
    if limit:
        query += f" LIMIT {int(limit)}"

    scored = 0
    retracted: list[str] = []
    missing: list[str] = []

    for row in conn.execute(query, params).fetchall():
        meta_result = lookup_metadata(conn, row["doi"], ttl, fresh)
        if meta_result is None:
            missing.append(row["id"])
            continue

        # DB update
        conn.execute(
            "UPDATE notes SET citation_count = ?, venue = ?, is_retracted = ? WHERE id = ?",
            (
                meta_result["citation_count"],
                meta_result["venue"],
                1 if meta_result["is_retracted"] else 0,
                row["id"],
            ),
        )

        # Frontmatter mirror (markdown stays truth; survives DB rebuild)
        note_path = vault.root / row["path"]
        if note_path.exists():
            text = note_path.read_text(encoding="utf-8-sig")
            fm, body = parse_frontmatter(text)
            fm.citation_count = meta_result["citation_count"]
            fm.venue = meta_result["venue"]
            fm.is_retracted = bool(meta_result["is_retracted"])
            note_path.write_text(render_note(fm, body), encoding="utf-8")

        scored += 1
        if meta_result["is_retracted"]:
            retracted.append(row["id"])

    conn.commit()
    authority_ranked = compute_authority_scores(conn)
    compute_quality_scores(conn, vault.config.ranking)

    return {
        "scored": scored,
        "retracted": retracted,
        "missing": missing,
        "authority_ranked": authority_ranked,
    }
