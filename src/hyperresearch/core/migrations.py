"""Schema migration system for hyperresearch SQLite databases."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

# Each migration upgrades from version N-1 to N. May be either:
#   - a SQL string (executed via executescript)
#   - a callable(conn) for migrations that need conditional logic (e.g. ADD COLUMN)
# Migrations MUST be idempotent (safe to re-run).


def _migrate_v6_tier_content_type(conn: sqlite3.Connection) -> None:
    """Add tier and content_type columns to notes (idempotent)."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(notes)")}
    if "tier" not in existing:
        conn.execute("ALTER TABLE notes ADD COLUMN tier TEXT")
    if "content_type" not in existing:
        conn.execute("ALTER TABLE notes ADD COLUMN content_type TEXT")
    conn.executescript("""
        CREATE INDEX IF NOT EXISTS idx_notes_tier ON notes(tier);
        CREATE INDEX IF NOT EXISTS idx_notes_content_type ON notes(content_type);
    """)


def _migrate_v7_interim_note_type(conn: sqlite3.Connection) -> None:
    """Add 'interim' to the notes.type CHECK constraint.

    SQLite can't alter a CHECK constraint in place — we rebuild the table.
    Hyperresearch step 3 depth-investigator writes type='interim' notes, so
    pre-v7 vaults would reject those on sync.
    """
    # Cheap pre-check: if the table already accepts 'interim', skip.
    try:
        with conn:
            conn.execute("SAVEPOINT check_interim_type")
            try:
                conn.execute(
                    "INSERT INTO notes (id, title, path, type, created) "
                    "VALUES ('__migrate_probe__', 'probe', '__migrate_probe__', 'interim', '1970-01-01T00:00:00Z')"
                )
                conn.execute("DELETE FROM notes WHERE id = '__migrate_probe__'")
                conn.execute("RELEASE check_interim_type")
                return  # already compatible
            except sqlite3.IntegrityError:
                conn.execute("ROLLBACK TO check_interim_type")
                conn.execute("RELEASE check_interim_type")
    except sqlite3.OperationalError:
        pass

    # Rebuild the table with the expanded CHECK. Preserve all data.
    conn.executescript("""
        CREATE TABLE notes_v7 (
            id           TEXT PRIMARY KEY,
            title        TEXT NOT NULL,
            path         TEXT NOT NULL UNIQUE,
            status       TEXT NOT NULL DEFAULT 'draft'
                             CHECK (status IN ('draft','review','evergreen','stale','deprecated','archive')),
            type         TEXT NOT NULL DEFAULT 'note'
                             CHECK (type IN ('note','raw','index','moc','interim')),
            tier         TEXT
                             CHECK (tier IS NULL OR tier IN ('ground_truth','institutional','practitioner','commentary','unknown')),
            content_type TEXT
                             CHECK (content_type IS NULL OR content_type IN ('paper','docs','article','blog','forum','dataset','policy','code','book','transcript','review','unknown')),
            source       TEXT,
            parent       TEXT,
            deprecated   INTEGER NOT NULL DEFAULT 0,
            reviewed     TEXT,
            expires      TEXT,
            word_count   INTEGER NOT NULL DEFAULT 0,
            summary      TEXT,
            created      TEXT NOT NULL,
            updated      TEXT,
            file_mtime   REAL NOT NULL DEFAULT 0,
            content_hash TEXT NOT NULL DEFAULT '',
            synced_at    TEXT NOT NULL DEFAULT ''
        );
    """)
    # Copy preserving only columns that exist in the old table — defensive
    # against any schema drift between versions.
    old_cols = {row[1] for row in conn.execute("PRAGMA table_info(notes)")}
    new_cols = {row[1] for row in conn.execute("PRAGMA table_info(notes_v7)")}
    shared = sorted(old_cols & new_cols)
    col_list = ", ".join(shared)
    conn.execute(
        f"INSERT INTO notes_v7 ({col_list}) SELECT {col_list} FROM notes"
    )
    conn.executescript("""
        DROP TABLE notes;
        ALTER TABLE notes_v7 RENAME TO notes;
    """)


def _migrate_v8_source_analysis_note_type(conn: sqlite3.Connection) -> None:
    """Add 'source-analysis' to the notes.type CHECK constraint.

    Same pattern as v7: SQLite can't alter a CHECK in place, so we rebuild
    the table when the existing one rejects the new type. Pre-v8 vaults
    would fail on sync once the source-analyst subagent starts writing
    type='source-analysis' notes.
    """
    try:
        with conn:
            conn.execute("SAVEPOINT check_source_analysis_type")
            try:
                conn.execute(
                    "INSERT INTO notes (id, title, path, type, created) "
                    "VALUES ('__migrate_probe_v8__', 'probe', '__migrate_probe_v8__', "
                    "'source-analysis', '1970-01-01T00:00:00Z')"
                )
                conn.execute("DELETE FROM notes WHERE id = '__migrate_probe_v8__'")
                conn.execute("RELEASE check_source_analysis_type")
                return  # already compatible
            except sqlite3.IntegrityError:
                conn.execute("ROLLBACK TO check_source_analysis_type")
                conn.execute("RELEASE check_source_analysis_type")
    except sqlite3.OperationalError:
        pass

    conn.executescript("""
        CREATE TABLE notes_v8 (
            id           TEXT PRIMARY KEY,
            title        TEXT NOT NULL,
            path         TEXT NOT NULL UNIQUE,
            status       TEXT NOT NULL DEFAULT 'draft'
                             CHECK (status IN ('draft','review','evergreen','stale','deprecated','archive')),
            type         TEXT NOT NULL DEFAULT 'note'
                             CHECK (type IN ('note','raw','index','moc','interim','source-analysis')),
            tier         TEXT
                             CHECK (tier IS NULL OR tier IN ('ground_truth','institutional','practitioner','commentary','unknown')),
            content_type TEXT
                             CHECK (content_type IS NULL OR content_type IN ('paper','docs','article','blog','forum','dataset','policy','code','book','transcript','review','unknown')),
            source       TEXT,
            parent       TEXT,
            deprecated   INTEGER NOT NULL DEFAULT 0,
            reviewed     TEXT,
            expires      TEXT,
            word_count   INTEGER NOT NULL DEFAULT 0,
            summary      TEXT,
            created      TEXT NOT NULL,
            updated      TEXT,
            file_mtime   REAL NOT NULL DEFAULT 0,
            content_hash TEXT NOT NULL DEFAULT '',
            synced_at    TEXT NOT NULL DEFAULT ''
        );
    """)
    old_cols = {row[1] for row in conn.execute("PRAGMA table_info(notes)")}
    new_cols = {row[1] for row in conn.execute("PRAGMA table_info(notes_v8)")}
    shared = sorted(old_cols & new_cols)
    col_list = ", ".join(shared)
    conn.execute(
        f"INSERT INTO notes_v8 ({col_list}) SELECT {col_list} FROM notes"
    )
    conn.executescript("""
        DROP TABLE notes;
        ALTER TABLE notes_v8 RENAME TO notes;
    """)


MIGRATIONS: dict[int, str | Callable[[sqlite3.Connection], None]] = {
    2: """
CREATE TABLE IF NOT EXISTS tag_aliases (
    alias     TEXT PRIMARY KEY,
    canonical TEXT NOT NULL
);
""",
    3: """
CREATE TABLE IF NOT EXISTS sources (
    url          TEXT PRIMARY KEY,
    note_id      TEXT REFERENCES notes(id) ON DELETE SET NULL,
    domain       TEXT,
    fetched_at   TEXT,
    provider     TEXT,
    content_hash TEXT,
    status       TEXT NOT NULL DEFAULT 'active'
                     CHECK (status IN ('active', 'dead', 'redirected'))
);
CREATE INDEX IF NOT EXISTS idx_sources_domain ON sources(domain);
CREATE INDEX IF NOT EXISTS idx_sources_note ON sources(note_id);
""",
    4: """
CREATE TABLE IF NOT EXISTS assets (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    note_id      TEXT NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    type         TEXT NOT NULL CHECK (type IN ('image', 'screenshot', 'pdf', 'other')),
    filename     TEXT NOT NULL,
    url          TEXT,
    alt_text     TEXT,
    content_type TEXT,
    size_bytes   INTEGER,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_assets_note ON assets(note_id);
CREATE INDEX IF NOT EXISTS idx_assets_type ON assets(type);
""",
    5: """
-- Dead fields (confidence, superseded_by, llm_compiled, llm_model, compile_source)
-- removed from code. Left as vestigial columns in existing DBs for compatibility.
-- New vaults won't have them. No structural changes needed.
""",
    6: _migrate_v6_tier_content_type,
    7: _migrate_v7_interim_note_type,
    8: _migrate_v8_source_analysis_note_type,
}


def get_schema_version(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute("SELECT value FROM _meta WHERE key = 'schema_version'").fetchone()
        return int(row[0] if isinstance(row, tuple) else row["value"]) if row else 0
    except sqlite3.OperationalError:
        return 0


def migrate(conn: sqlite3.Connection, target_version: int) -> list[int]:
    """Run pending migrations. Returns list of versions applied."""
    current = get_schema_version(conn)
    if current >= target_version:
        return []

    applied = []
    for version in range(current + 1, target_version + 1):
        migration = MIGRATIONS.get(version)
        if migration:
            if callable(migration):
                migration(conn)
            else:
                conn.executescript(migration)
        conn.execute(
            "INSERT OR REPLACE INTO _meta (key, value) VALUES ('schema_version', ?)",
            (str(version),),
        )
        applied.append(version)

    if applied:
        conn.commit()
    return applied
