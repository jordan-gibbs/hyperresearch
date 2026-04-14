"""File-to-DB sync engine — the bridge between markdown files and SQLite."""

from __future__ import annotations

import hashlib
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from hyperresearch.core.note import read_note, strip_markdown
from hyperresearch.core.patterns import (
    CODE_BLOCK_RE,
    INLINE_CODE_RE,
    WIKI_LINK_RE,
    is_valid_wiki_link_target,
)


@dataclass
class SyncPlan:
    to_add: list[Path] = field(default_factory=list)
    to_update: list[Path] = field(default_factory=list)
    to_delete: list[str] = field(default_factory=list)  # relative paths
    unchanged: int = 0


@dataclass
class SyncResult:
    added: int = 0
    updated: int = 0
    deleted: int = 0
    unchanged: int = 0
    errors: list[dict] = field(default_factory=list)
    duration_ms: float = 0


def _should_exclude(rel_path: str, exclude_parts: list[str]) -> bool:
    """Fast exclusion check — match on first path component."""
    first = rel_path.split("/", 1)[0]
    return first in exclude_parts


def compute_sync_plan(vault, force: bool = False) -> SyncPlan:
    """Compare disk state against DB state. Returns a plan."""
    plan = SyncPlan()

    # Only scan inside the research directory (notes/, index/)
    # This avoids walking .git/, .venv/, src/, etc. entirely.
    #
    # Files at the research/ root (e.g. research/scaffold.md,
    # research/comparisons.md, research/synthesis.md) are STAGING files the
    # agent writes then registers as real notes via `note new --body-file`.
    # They must NOT be synced as notes themselves — otherwise every run
    # produces 4 orphan notes and the missing-title/missing-tags/missing-summary
    # lint rules spam warnings for every research session.
    kb_dir = vault.research_dir
    if not kb_dir.exists():
        return plan

    disk_files: dict[str, float] = {}
    for md_file in kb_dir.rglob("*.md"):
        # Skip staging files at the research/ root. Real notes live in
        # research/notes/** or research/index/**.
        if md_file.parent == kb_dir:
            continue
        rel = md_file.relative_to(vault.root).as_posix()
        disk_files[rel] = md_file.stat().st_mtime

    # Load DB state — only catch "table not found" on fresh vaults
    db_state: dict[str, tuple[float, str]] = {}
    try:
        for row in vault.db.execute("SELECT path, file_mtime, content_hash FROM notes"):
            db_state[row["path"]] = (row["file_mtime"], row["content_hash"])
    except sqlite3.OperationalError:
        # Table doesn't exist yet (fresh vault before schema init)
        pass

    for rel_path, mtime in disk_files.items():
        full_path = vault.root / rel_path
        if rel_path not in db_state:
            plan.to_add.append(full_path)
        elif force or abs(mtime - db_state[rel_path][0]) > 0.001:
            # mtime differs — verify with content hash (raw bytes)
            current_hash = hashlib.sha256(full_path.read_bytes()).hexdigest()
            if force or current_hash != db_state[rel_path][1]:
                plan.to_update.append(full_path)
            else:
                plan.unchanged += 1
        else:
            plan.unchanged += 1

    for db_path in db_state:
        if db_path not in disk_files:
            plan.to_delete.append(db_path)

    return plan


def execute_sync(vault, plan: SyncPlan) -> SyncResult:
    """Execute the sync plan within a single transaction for atomicity."""
    result = SyncResult(unchanged=plan.unchanged)
    start = time.monotonic()
    now_iso = datetime.now(UTC).isoformat()

    conn = vault.db
    conn.execute("BEGIN IMMEDIATE")

    changed_ids: set[str] = set()

    try:
        # Process deletes
        for rel_path in plan.to_delete:
            try:
                row = conn.execute("SELECT id FROM notes WHERE path = ?", (rel_path,)).fetchone()
                if row:
                    _delete_note_from_db(conn, row["id"])
                    changed_ids.add(row["id"])
                    result.deleted += 1
            except Exception as e:
                result.errors.append({"path": rel_path, "error": str(e)})

        # Process adds
        for file_path in plan.to_add:
            try:
                note = read_note(file_path, vault.root)
                _upsert_note_to_db(conn, note, now_iso, file_mtime=file_path.stat().st_mtime)
                changed_ids.add(note.meta.id)
                result.added += 1
            except Exception as e:
                result.errors.append({"path": str(file_path), "error": str(e)})

        # Process updates
        for file_path in plan.to_update:
            try:
                note = read_note(file_path, vault.root)
                _upsert_note_to_db(conn, note, now_iso, file_mtime=file_path.stat().st_mtime)
                changed_ids.add(note.meta.id)
                result.updated += 1
            except Exception as e:
                result.errors.append({"path": str(file_path), "error": str(e)})

        # Resolve links — only for changed notes' outgoing + incoming
        _resolve_links_incremental(conn, changed_ids)

        # Record sync timestamp
        conn.execute(
            "INSERT OR REPLACE INTO _meta (key, value) VALUES ('last_sync', ?)",
            (now_iso,),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    result.duration_ms = (time.monotonic() - start) * 1000
    return result


def _upsert_note_to_db(conn, note, synced_at: str, file_mtime: float = 0) -> None:
    """Insert or update a note and all related tables using proper UPSERT."""
    meta = note.meta
    created_iso = meta.created.isoformat() if meta.created else synced_at
    updated_iso = meta.updated.isoformat() if meta.updated else None

    reviewed_iso = meta.reviewed.isoformat() if meta.reviewed else None
    expires_iso = meta.expires.isoformat() if meta.expires else None

    # Use INSERT ... ON CONFLICT to avoid CASCADE deletes from INSERT OR REPLACE
    conn.execute(
        """
        INSERT INTO notes
            (id, title, path, status, type, tier, content_type, source, parent,
             deprecated, reviewed, expires, word_count, summary,
             created, updated, file_mtime, content_hash, synced_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            title=excluded.title, path=excluded.path, status=excluded.status,
            type=excluded.type, tier=excluded.tier, content_type=excluded.content_type,
            source=excluded.source, parent=excluded.parent,
            deprecated=excluded.deprecated,
            reviewed=excluded.reviewed, expires=excluded.expires,
            word_count=excluded.word_count, summary=excluded.summary,
            created=excluded.created, updated=excluded.updated,
            file_mtime=excluded.file_mtime, content_hash=excluded.content_hash,
            synced_at=excluded.synced_at
        """,
        (
            meta.id, meta.title, note.path, meta.status, meta.type,
            meta.tier, meta.content_type,
            meta.source, meta.parent, 1 if meta.deprecated else 0,
            reviewed_iso, expires_iso,
            note.word_count, meta.summary, created_iso, updated_iso,
            file_mtime, note.content_hash, synced_at,
        ),
    )

    # Update tags — resolve aliases before writing
    conn.execute("DELETE FROM tags WHERE note_id = ?", (meta.id,))
    alias_map = {}
    try:
        for row in conn.execute("SELECT alias, canonical FROM tag_aliases"):
            alias_map[row["alias"]] = row["canonical"]
    except Exception:
        pass
    for tag in meta.tags:
        resolved = alias_map.get(tag, tag)
        conn.execute("INSERT OR IGNORE INTO tags (note_id, tag) VALUES (?, ?)", (meta.id, resolved))

    # Update aliases
    conn.execute("DELETE FROM aliases WHERE note_id = ?", (meta.id,))
    for alias in meta.aliases:
        conn.execute("INSERT INTO aliases (note_id, alias) VALUES (?, ?)", (meta.id, alias))

    # Update content (UPSERT)
    body_plain = strip_markdown(note.body)
    conn.execute(
        """
        INSERT INTO note_content (note_id, body, body_plain) VALUES (?, ?, ?)
        ON CONFLICT(note_id) DO UPDATE SET body=excluded.body, body_plain=excluded.body_plain
        """,
        (meta.id, note.body, body_plain),
    )

    # Update FTS — delete then insert (FTS5 doesn't support ON CONFLICT)
    conn.execute("DELETE FROM notes_fts WHERE id = ?", (meta.id,))
    conn.execute(
        "INSERT INTO notes_fts (id, title, body_plain, tags, aliases) VALUES (?, ?, ?, ?, ?)",
        (meta.id, meta.title, body_plain, " ".join(meta.tags), " ".join(meta.aliases)),
    )

    # Update links — extract from original body (not stripped)
    # Uses the shared filter so this path stays in sync with core.note.read_note
    conn.execute("DELETE FROM links WHERE source_id = ?", (meta.id,))
    cleaned = CODE_BLOCK_RE.sub("", note.body)
    cleaned = INLINE_CODE_RE.sub("", cleaned)
    for line_num, line in enumerate(cleaned.split("\n"), 1):
        for m in WIKI_LINK_RE.finditer(line):
            target_ref = m.group(1).strip().rstrip("\\")  # Strip trailing backslash (shell escaping artifact)
            if not is_valid_wiki_link_target(target_ref):
                continue
            conn.execute(
                "INSERT OR IGNORE INTO links (source_id, target_ref, line_number, context) "
                "VALUES (?, ?, ?, ?)",
                (meta.id, target_ref, line_num, line.strip()[:200]),
            )


def _delete_note_from_db(conn, note_id: str) -> None:
    """Delete a note and all related data (CASCADE handles child tables)."""
    conn.execute("DELETE FROM notes_fts WHERE id = ?", (note_id,))
    conn.execute("DELETE FROM links WHERE source_id = ?", (note_id,))
    conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))


def _resolve_links_incremental(conn, changed_ids: set[str]) -> None:
    """Resolve links incrementally — only for links affected by changed notes.

    This handles two cases:
    1. Outgoing links from changed notes need resolution
    2. Unresolved links from ANY note might now resolve to a newly added note
    """
    if not changed_ids:
        return

    # Re-resolve outgoing links from changed notes
    placeholders = ",".join("?" for _ in changed_ids)
    ids = list(changed_ids)

    # Reset target_id for links from changed notes
    conn.execute(
        f"UPDATE links SET target_id = NULL WHERE source_id IN ({placeholders})", ids
    )

    # Also reset links that pointed TO deleted/changed notes (they may have moved)
    conn.execute(
        f"UPDATE links SET target_id = NULL WHERE target_id IN ({placeholders})", ids
    )

    # Now resolve all currently-NULL links (which includes the ones we just reset
    # plus any that were already broken and might now resolve)
    _resolve_null_links(conn)


def _resolve_null_links(conn) -> None:
    """Resolve all links with target_id = NULL."""
    # Exact ID match
    conn.execute("""
        UPDATE links SET target_id = (
            SELECT n.id FROM notes n WHERE n.id = links.target_ref LIMIT 1
        )
        WHERE target_id IS NULL
    """)
    # Case-insensitive ID match
    conn.execute("""
        UPDATE links SET target_id = (
            SELECT n.id FROM notes n WHERE LOWER(n.id) = LOWER(links.target_ref) LIMIT 1
        )
        WHERE target_id IS NULL
    """)
    # Alias match
    conn.execute("""
        UPDATE links SET target_id = (
            SELECT a.note_id FROM aliases a
            WHERE LOWER(a.alias) = LOWER(links.target_ref)
            LIMIT 1
        )
        WHERE target_id IS NULL
    """)
    # Title match
    conn.execute("""
        UPDATE links SET target_id = (
            SELECT n.id FROM notes n WHERE LOWER(n.title) = LOWER(links.target_ref) LIMIT 1
        )
        WHERE target_id IS NULL
    """)
