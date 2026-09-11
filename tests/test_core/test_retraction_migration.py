"""The v13 cache upgrade preserves related data and restores tri-state frontmatter."""

import sqlite3

import pytest

from hyperresearch.core.db import FTS_SQL, SCHEMA_SQL, get_connection, init_schema
from hyperresearch.core.migrations import _migrate_v13_nullable_retraction, migrate
from hyperresearch.core.note import write_note
from hyperresearch.core.sync import compute_sync_plan, execute_sync


@pytest.fixture
def legacy_vault(tmp_vault):
    # Build the schema that shipped in v12, including its conflated false default.
    tmp_vault.close()
    tmp_vault.db_path.unlink()
    conn = get_connection(tmp_vault.db_path)
    conn.executescript(SCHEMA_SQL.replace(
        'is_retracted     INTEGER,', 'is_retracted     INTEGER NOT NULL DEFAULT 0,'))
    conn.executescript(FTS_SQL)
    conn.execute("INSERT INTO _meta VALUES ('schema_version', '12')")
    for name, state in [("known", False), ("retracted", True), ("unchecked", None)]:
        path = write_note(tmp_vault.notes_dir, name, body="retrieval [[known]]",
                          tags=["evidence"], extra_frontmatter={"is_retracted": state})
        conn.execute(
            "INSERT INTO notes (id, title, path, created, file_mtime, content_hash, synced_at, is_retracted) "
            "VALUES (?, ?, ?, '2026-01-01', ?, 'legacy', '2026-01-01', ?)",
            (name, name, path.relative_to(tmp_vault.root).as_posix(), path.stat().st_mtime, int(bool(state))),
        )
        conn.execute("INSERT INTO note_content VALUES (?, 'body', 'body')", (name,))
        conn.execute("INSERT INTO tags VALUES (?, 'evidence')", (name,))
        conn.execute("INSERT INTO aliases VALUES (?, 'alias')", (name,))
        conn.execute("INSERT INTO links VALUES (?, 'known', 'known', 1, 'context')", (name,))
        conn.execute("INSERT INTO embeddings VALUES (?, 'test', 1, X'00000000', '2026-01-01')", (name,))
        conn.execute("INSERT INTO claims (note_id, claim, claim_hash, ingested_at) VALUES (?, 'claim', ?, '2026-01-01')",
                     (name, name))
        conn.execute("INSERT INTO sources (url, note_id) VALUES (?, ?)", (f"https://example.org/{name}", name))
    conn.execute("CREATE INDEX custom_notes_venue ON notes(venue)")
    conn.commit()
    yield tmp_vault, conn
    conn.close()
    tmp_vault.close()


def test_upgrade_preserves_relations_and_resyncs_frontmatter(legacy_vault):
    vault, conn = legacy_vault
    files = {p: p.read_bytes() for p in vault.notes_dir.rglob('*.md')}
    tables = ['note_content', 'tags', 'aliases', 'links', 'embeddings', 'claims', 'sources']
    before = {t: [tuple(r) for r in conn.execute(f'SELECT * FROM {t}')] for t in tables}
    init_schema(conn)
    assert conn.execute('PRAGMA foreign_keys').fetchone()[0] == 1
    assert list(conn.execute('PRAGMA foreign_key_check')) == []
    assert before == {t: [tuple(r) for r in conn.execute(f'SELECT * FROM {t}')] for t in tables}
    assert conn.execute("SELECT 1 FROM sqlite_master WHERE name='custom_notes_venue'").fetchone()
    assert dict(conn.execute('SELECT id, is_retracted FROM notes')) == {
        'known': None, 'unchecked': None, 'retracted': 1,
    }
    assert migrate(conn, 13) == []
    _migrate_v13_nullable_retraction(conn)  # interrupted version stamp is harmless
    plan = compute_sync_plan(vault)  # no --force required
    assert len(plan.to_update) == 3
    assert not plan.to_add and not plan.to_delete
    result = execute_sync(vault, plan)
    assert not result.errors
    assert dict(vault.db.execute('SELECT id, is_retracted FROM notes')) == {
        'known': 0, 'unchecked': None, 'retracted': 1,
    }
    assert {p: p.read_bytes() for p in files} == files
    assert vault.db.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == 3
    assert vault.db.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0] == 3


def test_failed_upgrade_rolls_back_and_restores_foreign_keys(legacy_vault):
    _, conn = legacy_vault

    def deny_drop(action, name, *args):
        return sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_DROP_TABLE and name == 'notes' else sqlite3.SQLITE_OK

    conn.set_authorizer(deny_drop)
    with pytest.raises(sqlite3.DatabaseError):
        migrate(conn, 13)
    conn.set_authorizer(None)
    assert conn.execute('PRAGMA foreign_keys').fetchone()[0] == 1
    assert conn.execute("SELECT value FROM _meta WHERE key='schema_version'").fetchone()[0] == '12'
    assert conn.execute("SELECT COUNT(*) FROM notes WHERE is_retracted=0").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == 3
    assert not conn.execute("SELECT 1 FROM sqlite_master WHERE name='notes_v13'").fetchone()
    assert migrate(conn, 13) == [13]
