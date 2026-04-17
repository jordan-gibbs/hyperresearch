"""SQLite database management — schema, connection, migrations."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 7

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS _meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notes (
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
    file_mtime   REAL NOT NULL,
    content_hash TEXT NOT NULL,
    synced_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_notes_status ON notes(status);
CREATE INDEX IF NOT EXISTS idx_notes_type ON notes(type);
CREATE INDEX IF NOT EXISTS idx_notes_parent ON notes(parent);
CREATE INDEX IF NOT EXISTS idx_notes_created ON notes(created);
CREATE INDEX IF NOT EXISTS idx_notes_updated ON notes(updated);
CREATE INDEX IF NOT EXISTS idx_notes_word_count ON notes(word_count);
CREATE INDEX IF NOT EXISTS idx_notes_status_type ON notes(status, type);
CREATE INDEX IF NOT EXISTS idx_notes_parent_status ON notes(parent, status);

CREATE TABLE IF NOT EXISTS note_content (
    note_id    TEXT PRIMARY KEY REFERENCES notes(id) ON DELETE CASCADE,
    body       TEXT NOT NULL,
    body_plain TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tags (
    note_id TEXT NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    tag     TEXT NOT NULL,
    PRIMARY KEY (note_id, tag)
);

CREATE INDEX IF NOT EXISTS idx_tags_tag ON tags(tag);

CREATE TABLE IF NOT EXISTS aliases (
    note_id TEXT NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    alias   TEXT NOT NULL,
    PRIMARY KEY (note_id, alias)
);

CREATE INDEX IF NOT EXISTS idx_aliases_alias ON aliases(alias COLLATE NOCASE);

CREATE TABLE IF NOT EXISTS links (
    source_id   TEXT NOT NULL,
    target_ref  TEXT NOT NULL,
    target_id   TEXT,
    line_number INTEGER NOT NULL DEFAULT 0,
    context     TEXT,
    PRIMARY KEY (source_id, target_ref, line_number)
);

CREATE INDEX IF NOT EXISTS idx_links_target ON links(target_id);
CREATE INDEX IF NOT EXISTS idx_links_source ON links(source_id);

CREATE TABLE IF NOT EXISTS embeddings (
    note_id    TEXT PRIMARY KEY REFERENCES notes(id) ON DELETE CASCADE,
    model      TEXT NOT NULL,
    dimensions INTEGER NOT NULL,
    vector     BLOB NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tag_aliases (
    alias     TEXT PRIMARY KEY,
    canonical TEXT NOT NULL
);

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

"""

FTS_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
    id UNINDEXED,
    title,
    body_plain,
    tags,
    aliases,
    tokenize='porter unicode61'
);
"""

# Indexes on columns added by migrations — must run AFTER migrate() so that
# existing DBs have had the columns added by ALTER TABLE before we index them.
POST_MIGRATE_INDEXES_SQL = """
CREATE INDEX IF NOT EXISTS idx_notes_tier ON notes(tier);
CREATE INDEX IF NOT EXISTS idx_notes_content_type ON notes(content_type);
"""


def get_connection(db_path: Path) -> sqlite3.Connection:
    """Open a SQLite connection with WAL mode and FK enforcement."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """Create all tables if they don't exist, then run pending migrations."""
    conn.executescript(SCHEMA_SQL)
    conn.executescript(FTS_SQL)
    conn.execute(
        "INSERT OR IGNORE INTO _meta (key, value) VALUES ('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()

    # Run any pending migrations (may ALTER TABLE to add new columns)
    from hyperresearch.core.migrations import migrate
    migrate(conn, SCHEMA_VERSION)

    # Indexes that depend on migration-added columns run last
    conn.executescript(POST_MIGRATE_INDEXES_SQL)
    conn.commit()
