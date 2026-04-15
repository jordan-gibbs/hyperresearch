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
