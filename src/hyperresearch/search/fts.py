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


# Quoted phrases (with an optional prefix star), punctuation FTS5 gives meaning
# to in an operator query, and everything else as a bare word. A lone '"' is
# skipped, as the plain path strips it.
_OPERATOR_TOKEN_RE = re.compile(r'"[^"]*"\*?|[(),]|[^\s(),"]+')
# FTS5 barewords: ASCII letters, digits and '_', plus any non-ASCII character.
# Anything else ('-', ':', '.', '/', '^', '+', ...) is FTS5 syntax, so a term
# containing it must be quoted or FTS5 reads 'covid-19' as column '19'.
_BAREWORD_RE = re.compile(r"[0-9A-Za-z_\u0080-\U0010ffff]+")
# A letter or digit. A term without one is an empty phrase to the tokenizer,
# which matches nothing and so empties any explicit AND around it.
_TOKEN_CHAR_RE = re.compile(r"[^\W_]")
# FTS5 operators are case-sensitive: lowercase and/or/not are ordinary terms,
# which is how natural-language queries use them.
_BINARY_OPERATORS = ("AND", "OR", "NOT")


def _is_operator_query(tokens: list[str]) -> bool:
    for i, tok in enumerate(tokens):
        if tok in _BINARY_OPERATORS and 0 < i < len(tokens) - 1:
            return True
        if tok == "NEAR" and tokens[i + 1:i + 2] == ["("]:
            return True
    return False


def _operator_term(word: str) -> str | None:
    """Pass an FTS5 bareword through unchanged; quote anything else as a phrase."""
    core = word.rstrip("*")
    star = "*" if core != word else ""
    if not _TOKEN_CHAR_RE.search(core):
        return None
    if _BAREWORD_RE.fullmatch(core):
        return core + star
    return f'"{core}"{star}'


def _preprocess_operator_query(tokens: list[str]) -> str:
    out: list[str] = []
    in_near = False
    for tok in tokens:
        if tok.startswith('"') or tok in _BINARY_OPERATORS:
            out.append(tok)
        elif tok == "(":
            in_near = bool(out) and out[-1] == "NEAR"
            out.append(tok)
        elif tok == ")":
            in_near = False
            out.append(tok)
        elif tok == ",":
            # Only NEAR(a b, N) gives a comma meaning; elsewhere it is punctuation.
            if in_near:
                out.append(tok)
        else:
            term = _operator_term(tok)
            if term:
                out.append(term)
    return " ".join(out)


def preprocess_query(raw: str) -> str:
    """Transform user query into FTS5 query syntax.

    - Simple words get prefix matching: 'python async' -> 'python* async*'
    - Glued alphanumeric also matches split: 'mamba3' -> 'mamba3' or 'mamba 3'
    - Quoted phrases stay exact: '"async await"' stays as-is
    - Handles special FTS5 operators: AND, OR, NOT, NEAR (uppercase only).
      Barewords pass through; other terms are quoted ('covid-19' -> '"covid-19"')
    """
    tokens = _OPERATOR_TOKEN_RE.findall(raw)
    if _is_operator_query(tokens):
        return _preprocess_operator_query(tokens)

    parts = re.split(r'(".*?")', raw)
    processed = []
    for part in parts:
        if part.startswith('"'):
            if _TOKEN_CHAR_RE.search(part):
                processed.append(part)
        else:
            words = part.strip().split()
            for word in words:
                if word:
                    # Strip FTS5-special chars that would break syntax. The
                    # double-quote is included because quoted phrases were
                    # already extracted by the outer split — any quote left
                    # here is an unbalanced fragment.
                    clean = re.sub(r'[*^():{}"]', '', word)
                    if not _TOKEN_CHAR_RE.search(clean):
                        continue
                    # Split glued alphanumeric (mamba3 -> mamba + 3) so 'Mamba 3'
                    # matches. unicode61 indexes 'mamba3' as one token, which
                    # the split alone can never match, so accept either form.
                    subwords = _split_alphanum(clean)
                    if len(subwords) > 1:
                        split = " ".join(f'"{sw}"*' for sw in subwords)
                        processed.append(f'("{clean}"* OR ({split}))')
                    else:
                        processed.append(f'"{clean}"*')
    # Explicit AND: FTS5 only allows implicit AND between phrases, not next to
    # a parenthesized group. Implicit AND skipped an empty phrase ('-', '&');
    # explicit AND does not, which is why tokenless terms are dropped above.
    return " AND ".join(processed)


def _fts_rejects(conn: sqlite3.Connection, fts_query: str) -> bool:
    """True when FTS5 rejects this MATCH expression on an index that works.

    FTS5 reports query errors under many messages ('no such column: 19',
    'expected integer, got ...', 'unknown special query'), some shared with a
    broken vault, so the message alone cannot classify them. A trivial MATCH
    that succeeds proves the index is readable and the expression is at fault.
    """
    probe = "SELECT 1 FROM notes_fts WHERE notes_fts MATCH ? LIMIT 1"
    try:
        conn.execute(probe, ("a",)).fetchall()
    except sqlite3.OperationalError:
        return False
    try:
        conn.execute(probe, (fts_query,)).fetchall()
    except sqlite3.OperationalError:
        return True
    return False


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
        SearchQueryError: the query has no searchable terms, unless it is blank
            and at least one metadata filter is supplied.
        sqlite3.OperationalError: the FTS index is missing or unreadable. This is
            deliberately not swallowed — a broken index must not look like a
            topic with no results.
    """
    fts_query = preprocess_query(query)

    where, filter_params = filters.to_sql("n") if filters else ("1=1", [])
    filter_only = not query.strip() and where != "1=1"
    if not fts_query.strip() and not filter_only:
        raise SearchQueryError(
            f"Search query {query!r} contains no searchable terms. "
            "Provide at least one word, quoted phrase, or a filter without a text query."
        )
    filter_clause = f"AND {where}"

    # Exclude auto-generated index pages by default
    index_clause = "" if include_index else "AND n.type != 'index'"

    # BM25 column weights from config (id=unindexed=0, title, body, tags, aliases)
    w = ranking or {}
    tw = w.get("title_weight", 10.0)
    bw = w.get("body_weight", 1.0)
    tgw = w.get("tags_weight", 5.0)
    aw = w.get("aliases_weight", 3.0)

    source = "notes n" if filter_only else "notes_fts fts JOIN notes n ON fts.id = n.id"
    match = "1=1" if filter_only else "notes_fts MATCH ?"
    snippet = "COALESCE(n.summary, '')" if filter_only else "snippet(notes_fts, 2, '>>>', '<<<', '...', 64)"
    score = "0.0" if filter_only else f"bm25(notes_fts, 0.0, {tw}, {bw}, {tgw}, {aw})"
    order = "n.created DESC, n.id" if filter_only else "score"
    sql = f"""
        SELECT
            n.id, n.title, n.path, n.status, n.type, n.tier, n.content_type,
            n.quality_score, n.doi, n.venue, n.citation_count, n.is_retracted, n.oa_version,
            n.created, n.updated, n.word_count, n.summary,
            {snippet} as snippet,
            {score} as score,
            (SELECT GROUP_CONCAT(t.tag, ',') FROM tags t WHERE t.note_id = n.id) as tag_list
        FROM {source}
        WHERE {match}
        {filter_clause}
        {index_clause}
        ORDER BY {order}
        LIMIT ? OFFSET ?
    """

    params = [*([fts_query] if not filter_only else []), *filter_params, limit, offset]

    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError as exc:
        if not filter_only and _fts_rejects(conn, fts_query):
            raise SearchQueryError(f"Invalid search query {query!r}: {exc}") from exc
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
            "doi": row["doi"],
            "venue": row["venue"],
            "citation_count": row["citation_count"],
            "is_retracted": None if row["is_retracted"] is None else bool(row["is_retracted"]),
            "oa_version": row["oa_version"],
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
