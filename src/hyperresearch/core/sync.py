"""File-to-DB sync engine — the bridge between markdown files and SQLite."""

from __future__ import annotations

import hashlib
import re
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from hyperresearch.core.note import read_note, strip_markdown
from hyperresearch.core.patterns import (
    WIKI_LINK_RE,
    is_valid_wiki_link_target,
    strip_code,
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


class _TransactionLostError(Exception):
    """SQLite rolled the whole sync transaction back in the middle of a pass."""


class _UnreadableNewFileError(Exception):
    """A new file named after an id in play has no id sync can read, so
    whether it claims that id is unknown."""

    def __init__(self, rel_path: str, reason: str) -> None:
        super().__init__(f"{rel_path}: {reason}")
        self.rel_path = rel_path
        self.reason = reason


def _should_exclude(rel_path: str, exclude_parts: list[str]) -> bool:
    """Fast exclusion check — match on first path component."""
    first = rel_path.split("/", 1)[0]
    return first in exclude_parts


_FRONTMATTER_PROBE = re.compile(rb"^---[ \t]*\r?\n")


def _has_frontmatter(path: Path) -> bool:
    """Cheap content probe — true iff the file opens with a YAML frontmatter
    delimiter (matching parse_frontmatter's regex, with optional UTF-8 BOM).

    Real notes — including stub notes under research/temp/ — always carry
    frontmatter (write_note() in core/note.py emits it unconditionally).
    Files without it are agent scratch artifacts that should never enter the
    note index (see issue #25): interim-report body files written before
    `note new --body-file`, evidence-digest.md, draft-{a,b,c}.md, and similar.
    Ingesting them produces same-id collisions with the canonical notes
    derived from them.
    """
    try:
        with path.open("rb") as f:
            head = f.read(16)
    except OSError:
        return False
    if head.startswith(b"\xef\xbb\xbf"):
        head = head[3:]
    return _FRONTMATTER_PROBE.match(head) is not None


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

    runs_dir = kb_dir / "runs"
    disk_files: dict[str, float] = {}
    for md_file in kb_dir.rglob("*.md"):
        # Skip staging files at the research/ root. Real notes live in
        # research/notes/** or research/index/**.
        if md_file.parent == kb_dir:
            continue
        # Skip per-run workspaces entirely (research/runs/<vault_tag>/**) —
        # run-scoped pipeline artifacts are never vault notes.
        if runs_dir in md_file.parents:
            continue
        # Skip scratch artifacts without YAML frontmatter.
        if not _has_frontmatter(md_file):
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
    assets_root = vault.root / "research" / "assets"

    # Defense-in-depth (#25): refuse to silently smash an existing row's path
    # field when a second file in the same pass derives the same id, or when
    # a new file claims an id that's already in the DB at a different path.
    # The collision would otherwise be order-dependent and lose data on the
    # next `note update`.
    #
    # The reverse map gives the id the row at a path carries, so a file whose
    # `id:` changed is renamed in place; inserted as a new id, it was refused
    # by UNIQUE(notes.path) on every run.
    deleted_paths = set(plan.to_delete)
    id_to_path: dict[str, str] = {}
    path_to_id: dict[str, str] = {}
    for row in conn.execute("SELECT id, path FROM notes"):
        if row["path"] in deleted_paths:
            continue
        id_to_path[row["id"]] = row["path"]
        path_to_id[row["path"]] = row["id"]
    # Every new file by stem: a stem can be new in more than one directory
    # (research/notes/ and research/temp/).
    new_files_by_stem: dict[str, list[Path]] = {}
    for p in plan.to_add:
        new_files_by_stem.setdefault(p.stem, []).append(p)
    renamed_from: set[str] = set()

    def _new_files_claiming(note_id: str) -> list:
        """The new files named after `note_id` whose id is `note_id`.

        Fetch writes <id>.md and records its source and assets under the
        stem, so a new file named after an id is that id's owner unless it
        declares another. One whose frontmatter is there but does not parse
        (a file caught mid-write) raises: its id is unknown.
        """
        claimants = []
        for candidate in new_files_by_stem.get(note_id, ()):
            rel = candidate.relative_to(vault.root).as_posix()
            try:
                claimant = read_note(candidate, vault.root)
            except Exception as exc:
                raise _UnreadableNewFileError(rel, str(exc)) from exc
            if claimant.frontmatter_broken:
                raise _UnreadableNewFileError(rel, "its frontmatter does not parse")
            if claimant.meta.id == note_id:
                claimants.append(claimant)
        return claimants

    def _upsert_with_collision_check(file_path: Path) -> str | None:
        note = read_note(file_path, vault.root)
        rel = file_path.relative_to(vault.root).as_posix()
        existing = id_to_path.get(note.meta.id)
        if existing is not None and existing != rel:
            result.errors.append({
                "path": rel,
                "error": (
                    f"id collision: '{note.meta.id}' already belongs to "
                    f"'{existing}'. Skipped to avoid silent overwrite."
                ),
            })
            return None
        old_id = path_to_id.get(rel)
        rename = old_id is not None and old_id != note.meta.id
        if rename and not note.id_declared:
            # A broken, half-written or id-less frontmatter is no reason to
            # move the note's rows and free its id for another file.
            result.errors.append({
                "path": rel,
                "error": (
                    f"the indexed id is '{old_id}' but the frontmatter declares no id "
                    "(missing, or the frontmatter does not parse). Not re-indexed: "
                    "fix the frontmatter and run sync again."
                ),
            })
            return None
        keep_urls: set[str] = set()
        keep_assets_dir: Path | None = None
        if rename:
            try:
                new_id_claimants = _new_files_claiming(note.meta.id)
                # Rows under the old id were recorded for the file with that
                # stem: this one, or a new file named after the old id.
                old_id_claimants = [] if file_path.stem == old_id else _new_files_claiming(old_id)
            except _UnreadableNewFileError as exc:
                # A guess could take that file's id or move its URL rows.
                result.errors.append({
                    "path": rel,
                    "error": (
                        f"the id changed from '{old_id}' to '{note.meta.id}', but new "
                        f"file '{exc.rel_path}' is named after one of them and its id "
                        f"cannot be read ({exc.reason}). Not re-indexed: fix that file "
                        "and run sync again."
                    ),
                })
                return None
            if new_id_claimants:
                # Fetch recorded that file's URL under its stem, so the id is that file's.
                result.errors.append({
                    "path": rel,
                    "error": (
                        f"id collision: '{note.meta.id}' is claimed by new file "
                        f"'{new_id_claimants[0].path}'. Skipped to avoid silent overwrite."
                    ),
                })
                return None
            # Their URLs, and their assets in research/assets/<old_id>/, stay.
            keep_urls = {c.meta.source for c in old_id_claimants if c.meta.source}
            if old_id_claimants:
                keep_assets_dir = assets_root / old_id
        # A file's rename and upsert succeed or fail together, and the maps
        # change only after both: a rename left behind by a failed upsert
        # would park the row under an id a later file could take.
        conn.execute("SAVEPOINT sync_note")
        try:
            if rename:
                _rename_note_id(conn, old_id, note.meta.id, keep_urls, keep_assets_dir)
            _upsert_note_to_db(conn, note, now_iso, file_mtime=file_path.stat().st_mtime)
        except Exception:
            # On some errors (SQLITE_FULL among them) SQLite has already
            # rolled back the whole transaction, savepoints included, and a
            # ROLLBACK TO or RELEASE would raise "no such savepoint" in place
            # of the real error.
            if conn.in_transaction:
                conn.execute("ROLLBACK TO sync_note")
                conn.execute("RELEASE sync_note")
            raise
        conn.execute("RELEASE sync_note")
        if rename:
            # Free the old id for a later file in this pass.
            id_to_path.pop(old_id, None)
            changed_ids.add(old_id)
            renamed_from.add(old_id)
        id_to_path[note.meta.id] = rel
        path_to_id[rel] = note.meta.id
        changed_ids.add(note.meta.id)
        return note.meta.id

    def _record_error(path: str, exc: Exception) -> None:
        result.errors.append({"path": path, "error": str(exc)})
        if not conn.in_transaction:
            # SQLite rolled back the whole transaction (SQLITE_FULL among
            # others), but the maps still free the ids of undone deletes and
            # renames: a later file would land on a restored row and take its
            # children. Stop the pass, and say so in the error.
            result.errors[-1]["error"] += (
                "; nothing from this sync pass was kept: fix that error and run sync again"
            )
            raise _TransactionLostError from exc

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
                _record_error(rel_path, e)

        # Updates before adds: a rename frees an id that a new file in the
        # same pass may own, so this converges in one run. It also means that
        # when an id edit and a new file claim the same id, the edit wins and
        # the new file is refused as a collision, unless the new file is named
        # after that id (see _new_files_claiming).
        for file_path in plan.to_update:
            try:
                if _upsert_with_collision_check(file_path) is not None:
                    result.updated += 1
            except Exception as e:
                _record_error(str(file_path), e)

        # Process adds
        for file_path in plan.to_add:
            try:
                if _upsert_with_collision_check(file_path) is not None:
                    result.added += 1
            except Exception as e:
                _record_error(str(file_path), e)

        # Rows a rename kept for a claimant that then failed its own upsert
        # would fail the deferred foreign-key check: orphan them as a delete
        # of that id would (sources to NULL, assets rows gone, files kept).
        for old_id in renamed_from - set(id_to_path):
            conn.execute("UPDATE sources SET note_id = NULL WHERE note_id = ?", (old_id,))
            conn.execute("DELETE FROM assets WHERE note_id = ?", (old_id,))

        # Resolve links — only for changed notes' outgoing + incoming
        _resolve_links_incremental(conn, changed_ids)

        # Record sync timestamp
        conn.execute(
            "INSERT OR REPLACE INTO _meta (key, value) VALUES ('last_sync', ?)",
            (now_iso,),
        )
        conn.commit()
    except _TransactionLostError:
        # Nothing was kept, so nothing is counted; also discard whatever a
        # statement after the rollback opened on this connection.
        conn.rollback()
        result.added = result.updated = result.deleted = 0
    except Exception:
        conn.rollback()
        raise

    result.duration_ms = (time.monotonic() - start) * 1000
    return result


# Child tables keyed by note_id. A rename drops the rows the upsert rebuilds
# from the markdown, and moves the rows only the DB holds, which a delete and
# re-insert would cascade away, null out (`sources`) or leave pointing at a
# dead id (`escalations` has no foreign key).
_NOTE_ID_REBUILT_TABLES = ("note_content", "tags", "aliases")
_NOTE_ID_MOVED_TABLES = ("embeddings", "claims", "assets")
_NOTE_ID_URL_TABLES = ("sources", "escalations")


def _rename_note_id(
    conn,
    old_id: str,
    new_id: str,
    keep_urls: set[str],
    keep_assets_dir: Path | None = None,
) -> None:
    """Move a note row to a new id in place, with the rows only the DB holds.

    No foreign key declares ON UPDATE, so the parent-key change and the
    child re-pointing cannot both pass an immediate check: the check is
    deferred to commit. The pragma lasts until the transaction ends, not
    the savepoint; no other statement in a sync pass can violate a foreign
    key (each inserts a child after its parent or deletes through the
    cascade), so that changes nothing for them. `sources` and
    `escalations` rows whose URL is in `keep_urls`, and `assets` rows whose
    file lies in `keep_assets_dir`, stay under the old id for the new file
    that owns it; the caller orphans them if no row holds that id at commit.
    Asset files never move: their rows name them by full path.

    Caller guarantees `new_id` is not in use.
    """
    from hyperresearch.core.claims import _under

    conn.execute("PRAGMA defer_foreign_keys = ON")
    for table in _NOTE_ID_REBUILT_TABLES:
        conn.execute(f"DELETE FROM {table} WHERE note_id = ?", (old_id,))
    conn.execute("DELETE FROM links WHERE source_id = ?", (old_id,))
    conn.execute("DELETE FROM notes_fts WHERE id = ?", (old_id,))
    conn.execute("UPDATE notes SET id = ? WHERE id = ?", (new_id, old_id))
    kept_assets: list[int] = []
    if keep_assets_dir is not None:
        kept_assets = [
            row["id"]
            for row in conn.execute("SELECT id, filename FROM assets WHERE note_id = ?", (old_id,))
            if _under(Path(row["filename"]), keep_assets_dir)
        ]
    for table in _NOTE_ID_MOVED_TABLES:
        not_kept = ""
        params: tuple = (new_id, old_id)
        if table == "assets" and kept_assets:
            not_kept = f" AND id NOT IN ({','.join('?' for _ in kept_assets)})"
            params += tuple(kept_assets)
        conn.execute(f"UPDATE {table} SET note_id = ? WHERE note_id = ?{not_kept}", params)
    keep = sorted(keep_urls)
    not_kept = f" AND url NOT IN ({','.join('?' for _ in keep)})" if keep else ""
    for table in _NOTE_ID_URL_TABLES:
        conn.execute(
            f"UPDATE {table} SET note_id = ? WHERE note_id = ?{not_kept}",
            (new_id, old_id, *keep),
        )


def _upsert_note_to_db(conn, note, synced_at: str, file_mtime: float = 0) -> None:
    """Insert or update a note and all related tables using proper UPSERT."""
    meta = note.meta
    created_iso = meta.created.isoformat() if meta.created else synced_at
    updated_iso = meta.updated.isoformat() if meta.updated else None

    reviewed_iso = meta.reviewed.isoformat() if meta.reviewed else None
    expires_iso = meta.expires.isoformat() if meta.expires else None

    # Use INSERT ... ON CONFLICT to avoid CASCADE deletes from INSERT OR REPLACE
    # NOTE: the derived score columns (authority_score, centrality_score,
    # independence, quality_score) are deliberately absent — they are DB-cache
    # values computed by `hpr sources score` / `hpr graph rank` and must
    # survive re-syncs. Frontmatter-mirrored ranking fields (doi,
    # utility_score, citation_count, venue, is_retracted) sync normally.
    conn.execute(
        """
        INSERT INTO notes
            (id, title, path, status, type, tier, content_type, source, parent,
             deprecated, reviewed, expires, word_count, summary,
             created, updated, file_mtime, content_hash, synced_at,
             doi, utility_score, citation_count, venue, is_retracted,
             oa_url, oa_source, oa_version, oa_license, oa_recovery_kind)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            title=excluded.title, path=excluded.path, status=excluded.status,
            type=excluded.type, tier=excluded.tier, content_type=excluded.content_type,
            source=excluded.source, parent=excluded.parent,
            deprecated=excluded.deprecated,
            reviewed=excluded.reviewed, expires=excluded.expires,
            word_count=excluded.word_count, summary=excluded.summary,
            created=excluded.created, updated=excluded.updated,
            file_mtime=excluded.file_mtime, content_hash=excluded.content_hash,
            synced_at=excluded.synced_at,
            doi=excluded.doi, utility_score=excluded.utility_score,
            citation_count=excluded.citation_count, venue=excluded.venue,
            is_retracted=excluded.is_retracted,
            oa_url=excluded.oa_url, oa_source=excluded.oa_source,
            oa_version=excluded.oa_version, oa_license=excluded.oa_license,
            oa_recovery_kind=excluded.oa_recovery_kind
        """,
        (
            meta.id, meta.title, note.path, meta.status, meta.type,
            meta.tier, meta.content_type,
            meta.source, meta.parent, 1 if meta.deprecated else 0,
            reviewed_iso, expires_iso,
            note.word_count, meta.summary, created_iso, updated_iso,
            file_mtime, note.content_hash, synced_at,
            meta.doi, meta.utility_score, meta.citation_count, meta.venue,
            None if meta.is_retracted is None else int(meta.is_retracted),
            meta.oa_url, meta.oa_source, meta.oa_version, meta.oa_license,
            meta.oa_recovery_kind,
        ),
    )

    # Update tags — resolve aliases before writing
    conn.execute("DELETE FROM tags WHERE note_id = ?", (meta.id,))
    alias_map = {
        row["alias"]: row["canonical"]
        for row in conn.execute("SELECT alias, canonical FROM tag_aliases")
    }
    for tag in meta.tags:
        # Lowercase the frontmatter tag for BOTH the lookup and the fallback:
        # alias keys and canonicals are stored lowercase (cli/tag.py), and
        # SearchFilters lowercases query-side tags, so the stored value must
        # be lowercase to match. Without this, a frontmatter tag like `LLM`
        # misses its alias mapping and is invisible to `--tag llm` filtering.
        resolved = alias_map.get(tag.lower(), tag.lower())
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
    cleaned = strip_code(note.body)
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
