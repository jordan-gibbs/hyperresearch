"""FTS5 full-text search engine."""

from __future__ import annotations

import re
import sqlite3

from hyperresearch.search.filters import SearchFilters


class SearchQueryError(ValueError):
    """The search query could not be turned into a valid FTS5 query.

    Raised instead of returning an empty result set, so a malformed query is
    never indistinguishable from a topic with no matching notes.
    """


def _split_alphanum(word: str) -> list[str]:
    """Split words where letters meet digits: 'mamba3' -> ['mamba', '3'],
    'gpt4o' -> ['gpt', '4', 'o'], 'llama3.1' -> ['llama', '3', '1'].
    """
    # Insert space at letter/digit boundaries
    split = re.sub(r'([a-zA-Z])(\d)', r'\1 \2', word)
    split = re.sub(r'(\d)([a-zA-Z])', r'\1 \2', split)
    # Also split on dots/hyphens between digits (3.1 -> 3 1)
    split = re.sub(r'(\d)[.\-](\d)', r'\1 \2', split)
    return split.split()


def preprocess_query(raw: str) -> str:
    """Transform user query into FTS5 query syntax.

    - Simple words get prefix matching: 'python async' -> 'python* async*'
    - Glued alphanumeric split: 'mamba3' -> 'mamba 3', 'gpt4o' -> 'gpt 4 o'
    - Quoted phrases stay exact: '"async await"' stays as-is
    - Handles special FTS5 operators: AND, OR, NOT, NEAR
    """
    if any(op in raw.upper() for op in (" AND ", " OR ", " NOT ", " NEAR(")):
        return raw

    parts = re.split(r'(".*?")', raw)
    processed = []
    for part in parts:
        if part.startswith('"'):
            processed.append(part)
        else:
            words = part.strip().split()
            for word in words:
                if word:
                    clean = re.sub(r'[*^():{}]', '', word)
                    if not clean:
                        continue
                    # Split glued alphanumeric (mamba3 -> mamba + 3)
                    subwords = _split_alphanum(clean)
                    for sw in subwords:
                        if sw:
                            processed.append(f'"{sw}"*')
    return " ".join(processed)


def search_fts(
    conn: sqlite3.Connection,
    query: str,
    *,
    filters: SearchFilters | None = None,
    limit: int = 20,
    offset: int = 0,
    include_index: bool = False,
    ranking: dict | None = None,
    quality_ranked: bool = False,
) -> list[dict]:
    """Execute a full-text search against the notes_fts table.

    Raises:
        SearchQueryError: the query is empty or has no searchable terms.
        sqlite3.OperationalError: the FTS index is missing or unreadable. This is
            deliberately not swallowed — a broken index must not look like a
            topic with no results.
    """
    fts_query = preprocess_query(query)

    if not fts_query.strip():
        raise SearchQueryError(
            f"Search query {query!r} contains no searchable terms. "
            "Provide at least one word or quoted phrase."
        )

    filter_clause = ""
    filter_params: list = []
    if filters:
        where, filter_params = filters.to_sql("n")
        if where != "1=1":
            filter_clause = f"AND {where}"

    # Exclude auto-generated index pages by default
    index_clause = "" if include_index else "AND n.type != 'index'"

    # BM25 column weights from config (id=unindexed=0, title, body, tags, aliases)
    w = ranking or {}
    tw = w.get("title_weight", 10.0)
    bw = w.get("body_weight", 1.0)
    tgw = w.get("tags_weight", 5.0)
    aw = w.get("aliases_weight", 3.0)

    sql = f"""
        SELECT
            n.id, n.title, n.path, n.status, n.type, n.tier, n.content_type,
            n.quality_score,
            n.created, n.updated, n.word_count, n.summary,
            snippet(notes_fts, 2, '>>>', '<<<', '...', 64) as snippet,
            bm25(notes_fts, 0.0, {tw}, {bw}, {tgw}, {aw}) as score,
            (SELECT GROUP_CONCAT(t.tag, ',') FROM tags t WHERE t.note_id = n.id) as tag_list
        FROM notes_fts fts
        JOIN notes n ON fts.id = n.id
        WHERE notes_fts MATCH ?
        {filter_clause}
        {index_clause}
        ORDER BY score
        LIMIT ? OFFSET ?
    """

    params = [fts_query, *filter_params, limit, offset]

    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError as exc:
        msg = str(exc)
        if "syntax error" in msg or "malformed MATCH" in msg or "unterminated" in msg:
            raise SearchQueryError(f"Invalid search query {query!r}: {msg}") from exc
        # Missing table, corrupt index, locked database — surface it. Returning []
        # here previously made a broken vault indistinguishable from an empty one.
        raise

    results = []
    for row in rows:
        tag_list = row["tag_list"].split(",") if row["tag_list"] else []
        results.append({
            "id": row["id"],
            "title": row["title"],
            "path": row["path"],
            "status": row["status"],
            "type": row["type"],
            # sqlite3.Row.__contains__ is broken; row.keys() is reliable.
            "tier": row["tier"] if "tier" in row.keys() else None,  # noqa: SIM118
            "content_type": row["content_type"] if "content_type" in row.keys() else None,  # noqa: SIM118
            "tags": tag_list,
            "created": row["created"],
            "updated": row["updated"],
            "word_count": row["word_count"],
            "summary": row["summary"],
            "quality_score": row["quality_score"] if "quality_score" in row.keys() else None,  # noqa: SIM118
            "score": abs(row["score"]),
            "snippet": row["snippet"] or "",
        })

    # Apply status-based ranking adjustments
    if ranking:
        boost_evergreen = ranking.get("boost_evergreen", 1.0)
        penalize_deprecated = ranking.get("penalize_deprecated", 1.0)
        penalize_stale = ranking.get("penalize_stale", 1.0)
        for r in results:
            if r["status"] == "evergreen":
                r["score"] *= boost_evergreen
            elif r["status"] == "deprecated":
                r["score"] *= penalize_deprecated
            elif r["status"] == "stale":
                r["score"] *= penalize_stale
        results.sort(key=lambda x: x["score"], reverse=True)

    # Quality-weighted re-rank (opt-in): fold the composite source-quality
    # score into relevance. (0.5 + quality) keeps unscored notes (quality
    # NULL -> neutral 1.0x via fallback 0.5) competitive while a
    # ground-truth-tier, high-authority source (~1.0) roughly triples a
    # retracted one (~0.05).
    if quality_ranked:
        for r in results:
            q = r.get("quality_score")
            r["score"] *= 0.5 + (q if q is not None else 0.5)
        results.sort(key=lambda x: x["score"], reverse=True)

    return results
