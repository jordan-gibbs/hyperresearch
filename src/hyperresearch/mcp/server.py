"""hyperresearch MCP server — thin protocol layer over existing hyperresearch functions.

Exposes 8 tools for agents: search, read, read_many, list, backlinks, hubs, status, lint.
Read-only by design — agents create/edit notes via file operations, hyperresearch auto-syncs.
"""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

server = FastMCP("hyperresearch", instructions=(
    "hyperresearch is an agent-driven research knowledge base. Use these tools to search, read, "
    "and navigate research notes with wiki-links, tags, and summaries. Notes live in the research/ "
    "directory as markdown files with YAML frontmatter. To create or edit notes, write "
    "files directly and they will be auto-indexed."
))

_vault = None


def _get_vault():
    global _vault
    if _vault is None:
        from hyperresearch.core.vault import Vault
        _vault = Vault.discover()
        _vault.auto_sync()
    return _vault


@server.tool()
def search_notes(query: str, tag: str = "", status: str = "", parent: str = "", limit: int = 10) -> str:
    """Search the research base by text. Returns matching notes with titles, summaries, and full bodies.

    Args:
        query: Search query (supports natural language, FTS5 with porter stemming)
        tag: Filter by tag (comma-separated for multiple, AND logic)
        status: Filter by status (draft, review, evergreen, stale, deprecated, archive)
        parent: Filter by parent topic (e.g. "ml/deep-learning")
        limit: Max results to return (default 10)
    """
    vault = _get_vault()
    vault.auto_sync()
    from hyperresearch.search.filters import SearchFilters
    from hyperresearch.search.fts import search_fts
    tags = [t.strip() for t in tag.split(",") if t.strip()] or None
    filters = SearchFilters(tags=tags, status=status or None, parent=parent or None)
    ranking = {
        "title_weight": vault.config.search_title_weight,
        "body_weight": vault.config.search_body_weight,
        "tags_weight": vault.config.search_tags_weight,
        "aliases_weight": vault.config.search_aliases_weight,
        "boost_evergreen": vault.config.search_boost_evergreen,
        "penalize_deprecated": vault.config.search_penalize_deprecated,
        "penalize_stale": vault.config.search_penalize_stale,
    }
    results = search_fts(vault.db, query, filters=filters, limit=limit, ranking=ranking)
    for r in results:
        row = vault.db.execute("SELECT body FROM note_content WHERE note_id = ?", (r["id"],)).fetchone()
        r["body"] = row["body"] if row else ""
    return json.dumps(results, default=str)


@server.tool()
def read_note(note_id: str) -> str:
    """Read a single note by ID. Returns full metadata and body content.

    Args:
        note_id: The note's slug ID (e.g. "transformer-architecture")
    """
    vault = _get_vault()
    vault.auto_sync()
    row = vault.db.execute(
        "SELECT n.*, nc.body FROM notes n JOIN note_content nc ON n.id = nc.note_id WHERE n.id = ?",
        (note_id,),
    ).fetchone()
    if not row:
        return json.dumps({"error": f"Note not found: {note_id}"})
    tag_row = vault.db.execute("SELECT GROUP_CONCAT(tag, ',') as tl FROM tags WHERE note_id = ?", (note_id,)).fetchone()
    tags = tag_row["tl"].split(",") if tag_row and tag_row["tl"] else []
    return json.dumps({
        "id": row["id"], "title": row["title"], "path": row["path"],
        "status": row["status"], "type": row["type"], "tags": tags,
        "created": row["created"], "updated": row["updated"],
        "word_count": row["word_count"], "summary": row["summary"],
        "source": row["source"], "parent": row["parent"], "body": row["body"],
    }, default=str)


@server.tool()
def read_many(note_ids: str) -> str:
    """Read multiple notes at once. Pass comma-separated IDs.

    Args:
        note_ids: Comma-separated note IDs (e.g. "auth-flow,session-mgmt,jwt-tokens")
    """
    vault = _get_vault()
    vault.auto_sync()
    ids = [nid.strip() for nid in note_ids.split(",") if nid.strip()]
    notes, not_found = [], []
    for nid in ids:
        row = vault.db.execute(
            "SELECT n.*, nc.body FROM notes n JOIN note_content nc ON n.id = nc.note_id WHERE n.id = ?", (nid,)
        ).fetchone()
        if row:
            tag_row = vault.db.execute("SELECT GROUP_CONCAT(tag, ',') as tl FROM tags WHERE note_id = ?", (nid,)).fetchone()
            tags = tag_row["tl"].split(",") if tag_row and tag_row["tl"] else []
            notes.append({"id": row["id"], "title": row["title"], "status": row["status"],
                          "tags": tags, "word_count": row["word_count"], "summary": row["summary"], "body": row["body"]})
        else:
            not_found.append(nid)
    return json.dumps({"notes": notes, "not_found": not_found}, default=str)


@server.tool()
def list_notes(status: str = "", tag: str = "", parent: str = "", sort: str = "updated", limit: int = 50) -> str:
    """List notes with optional filters. Returns summaries (no bodies).

    Args:
        status: Filter by status
        tag: Filter by tag
        parent: Filter by parent topic
        sort: Sort order (created, updated, title, words)
        limit: Max results (default 50, use 0 for all)
    """
    vault = _get_vault()
    vault.auto_sync()
    clauses, params = ["n.type NOT IN ('index')"], []
    if status:
        clauses.append("n.status = ?")
        params.append(status)
    if tag:
        clauses.append("n.id IN (SELECT note_id FROM tags WHERE tag = ?)")
        params.append(tag.lower())
    if parent:
        clauses.append("(n.parent = ? OR n.parent LIKE ?)")
        params.extend([parent, parent + "/%"])
    where = " AND ".join(clauses)
    sort_map = {"created": "n.created DESC", "updated": "COALESCE(n.updated, n.created) DESC",
                "title": "n.title ASC", "words": "n.word_count DESC"}
    order = sort_map.get(sort, "COALESCE(n.updated, n.created) DESC")
    effective_limit = 999999 if limit == 0 else limit
    rows = vault.db.execute(
        f"SELECT n.*, (SELECT GROUP_CONCAT(t.tag, ',') FROM tags t WHERE t.note_id = n.id) as tag_list "
        f"FROM notes n WHERE {where} ORDER BY {order} LIMIT ?", [*params, effective_limit]
    ).fetchall()
    notes = [{"id": r["id"], "title": r["title"], "status": r["status"],
              "tags": r["tag_list"].split(",") if r["tag_list"] else [],
              "word_count": r["word_count"], "summary": r["summary"]} for r in rows]
    return json.dumps(notes, default=str)


@server.tool()
def get_backlinks(note_id: str) -> str:
    """Get all notes that link TO a given note.

    Args:
        note_id: The target note ID
    """
    vault = _get_vault()
    vault.auto_sync()
    rows = vault.db.execute(
        "SELECT l.source_id, n.title, l.line_number, l.context "
        "FROM links l JOIN notes n ON l.source_id = n.id WHERE l.target_id = ? ORDER BY n.title",
        (note_id,),
    ).fetchall()
    backlinks = [{"source_id": r["source_id"], "title": r["title"],
                  "line": r["line_number"], "context": r["context"]} for r in rows]
    return json.dumps({"note_id": note_id, "backlinks": backlinks, "count": len(backlinks)})


@server.tool()
def get_hubs(limit: int = 20) -> str:
    """Get the most-linked-to notes in the research base (hub notes).

    Args:
        limit: Max results (default 20)
    """
    vault = _get_vault()
    vault.auto_sync()
    rows = vault.db.execute(
        "SELECT l.target_id as id, n.title, COUNT(*) as inbound "
        "FROM links l JOIN notes n ON l.target_id = n.id "
        "WHERE l.target_id IS NOT NULL GROUP BY l.target_id ORDER BY inbound DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return json.dumps([{"id": r["id"], "title": r["title"], "inbound_links": r["inbound"]} for r in rows])


@server.tool()
def vault_status() -> str:
    """Get vault health overview: note counts, tag distribution, link stats, word count."""
    vault = _get_vault()
    vault.auto_sync()
    conn = vault.db
    total = conn.execute("SELECT COUNT(*) as c FROM notes WHERE type NOT IN ('index')").fetchone()["c"]
    by_status = {r["status"]: r["c"] for r in conn.execute(
        "SELECT status, COUNT(*) as c FROM notes WHERE type NOT IN ('index') GROUP BY status")}
    tag_count = conn.execute("SELECT COUNT(DISTINCT tag) as c FROM tags").fetchone()["c"]
    top_tags = [{"tag": r["tag"], "count": r["count"]} for r in conn.execute(
        "SELECT tag, COUNT(*) as count FROM tags GROUP BY tag ORDER BY count DESC LIMIT 10")]
    total_links = conn.execute("SELECT COUNT(*) as c FROM links").fetchone()["c"]
    broken = conn.execute("SELECT COUNT(*) as c FROM links WHERE target_id IS NULL").fetchone()["c"]
    total_words = conn.execute("SELECT COALESCE(SUM(word_count), 0) as c FROM notes").fetchone()["c"]
    return json.dumps({"vault_name": vault.config.name, "total_notes": total, "by_status": by_status,
                        "unique_tags": tag_count, "top_tags": top_tags, "total_links": total_links,
                        "broken_links": broken, "total_words": total_words})


@server.tool()
def lint_vault(rule: str = "") -> str:
    """Run health checks on the vault. Returns issues found.

    Args:
        rule: Specific rule to check (leave empty for all)
    """
    vault = _get_vault()
    vault.auto_sync()
    conn = vault.db
    issues: list[dict] = []
    rules = [rule] if rule else ["missing-tags", "missing-summary", "broken-links", "orphaned-notes"]
    if "missing-tags" in rules:
        for r in conn.execute("SELECT id FROM notes WHERE type NOT IN ('index','raw') AND id NOT IN (SELECT DISTINCT note_id FROM tags)"):
            issues.append({"rule": "missing-tags", "severity": "warning", "note_id": r["id"], "message": "No tags"})
    if "missing-summary" in rules:
        for r in conn.execute("SELECT id FROM notes WHERE type NOT IN ('index','raw') AND (summary IS NULL OR LENGTH(TRIM(COALESCE(summary, ''))) = 0)"):
            issues.append({"rule": "missing-summary", "severity": "warning", "note_id": r["id"], "message": "No summary"})
    if "broken-links" in rules:
        for r in conn.execute("SELECT source_id, target_ref FROM links WHERE target_id IS NULL"):
            issues.append({"rule": "broken-links", "severity": "warning", "note_id": r["source_id"], "message": f"Broken: [[{r['target_ref']}]]"})
    if "orphaned-notes" in rules:
        for r in conn.execute("SELECT id FROM notes WHERE type NOT IN ('index','raw') AND id NOT IN (SELECT DISTINCT target_id FROM links WHERE target_id IS NOT NULL) AND id NOT IN (SELECT DISTINCT source_id FROM links)"):
            issues.append({"rule": "orphaned-notes", "severity": "info", "note_id": r["id"], "message": "No links"})
    return json.dumps({"issues": issues, "total": len(issues), "warnings": sum(1 for i in issues if i["severity"] == "warning")})


@server.tool()
def check_source(url: str) -> str:
    """Check if a URL has already been fetched into the research base.

    Args:
        url: The URL to check
    """
    vault = _get_vault()
    row = vault.db.execute(
        "SELECT url, note_id, domain, fetched_at, provider FROM sources WHERE url = ?",
        (url,),
    ).fetchone()
    if row:
        return json.dumps({"exists": True, **dict(row)})
    return json.dumps({"exists": False, "url": url})


@server.tool()
def list_sources(domain: str = "", limit: int = 50) -> str:
    """List fetched web sources, optionally filtered by domain.

    Args:
        domain: Filter by domain (e.g. "arxiv.org"). Leave empty for all.
        limit: Max results (default 50)
    """
    vault = _get_vault()
    if domain:
        rows = vault.db.execute(
            "SELECT url, note_id, domain, fetched_at, provider, status "
            "FROM sources WHERE domain = ? ORDER BY fetched_at DESC LIMIT ?",
            (domain, limit),
        ).fetchall()
    else:
        rows = vault.db.execute(
            "SELECT url, note_id, domain, fetched_at, provider, status "
            "FROM sources ORDER BY fetched_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return json.dumps([dict(r) for r in rows])
