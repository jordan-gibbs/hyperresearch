"""SQLite database management — schema, connection, migrations."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 2

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
                     CHECK (type IN ('note','raw','index','moc')),
    source       TEXT,
    parent       TEXT,
    confidence   REAL,
    superseded_by TEXT,
    deprecated   INTEGER NOT NULL DEFAULT 0,
    reviewed     TEXT,
    expires      TEXT,
    llm_compiled INTEGER NOT NULL DEFAULT 0,
    llm_model    TEXT,
    compile_source TEXT,
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

    # Run any pending migrations
    from hyperresearch.core.migrations import migrate
    migrate(conn, SCHEMA_VERSION)
