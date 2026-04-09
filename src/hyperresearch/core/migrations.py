"""Schema migration system for hyperresearch SQLite databases."""

from __future__ import annotations

import sqlite3

# Each migration is a SQL script that upgrades from version N-1 to N.
# Migrations MUST be idempotent (safe to re-run).
MIGRATIONS: dict[int, str] = {
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
        sql = MIGRATIONS.get(version)
        if sql:
            conn.executescript(sql)
        conn.execute(
            "INSERT OR REPLACE INTO _meta (key, value) VALUES ('schema_version', ?)",
            (str(version),),
        )
        applied.append(version)

    if applied:
        conn.commit()
    return applied
