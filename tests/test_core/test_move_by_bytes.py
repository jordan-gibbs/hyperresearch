"""A new file takes the row of a note whose file is gone only with its bytes.

Sync sees a moved file (`note mv`, or a plain `mv`) as its old path deleted
and a new file that declares the same id, and moves the row in place so the
rows only the database holds stay with the note. The id alone said too
little: any file that was never indexed and declares the id (a collision
copy every sync refuses, an import, a `note new --template` copy) took a
removed note's claims, embeddings, asset rows and sources row. A move keeps
the bytes, so only a new file with the bytes the row was indexed from takes
it; anything else is a delete and an add, as before the move handling.
"""

from __future__ import annotations

import os

import pytest

from hyperresearch.core.note import read_note
from hyperresearch.core.sync import compute_sync_plan, execute_sync

NOW = "2026-09-15T00:00:00"
URL = "https://ex.org/paper"


def _note(path, note_id: str, title: str, body: str, extra: str = "") -> None:
    rewrite = path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nid: {note_id}\ntitle: {title}\n{extra}---\n\n{body}\n", encoding="utf-8")
    if rewrite:
        # A rewrite within one filesystem timestamp tick keeps the old mtime,
        # and the sync plan skips a file whose mtime did not move.
        st = path.stat()
        os.utime(path, (st.st_atime, st.st_mtime + 5))


def _sync(vault):
    return execute_sync(vault, compute_sync_plan(vault))


def _rows(vault) -> dict[str, str]:
    return {r["id"]: r["path"] for r in vault.db.execute("SELECT id, path FROM notes")}


def _seed_db_only_rows(vault, note_id: str) -> None:
    """A claim, an embedding, an asset row and the fetch dedup row: rows a
    markdown file cannot rebuild."""
    shot = vault.root / "research" / "assets" / note_id / "screenshot.png"
    shot.parent.mkdir(parents=True, exist_ok=True)
    shot.write_bytes(b"png")
    db = vault.db
    db.execute(
        "INSERT INTO claims (note_id, claim, claim_hash, ingested_at) VALUES (?, 'a claim', 'h1', ?)",
        (note_id, NOW),
    )
    db.execute(
        "INSERT INTO embeddings (note_id, model, dimensions, vector, created_at) VALUES (?, 'm', 1, ?, ?)",
        (note_id, b"\x00", NOW),
    )
    db.execute(
        "INSERT INTO assets (note_id, type, filename, created_at) VALUES (?, 'screenshot', ?, ?)",
        (note_id, str(shot), NOW),
    )
    db.execute(
        "INSERT INTO sources (url, note_id, domain, fetched_at, provider) VALUES (?, ?, 'ex.org', ?, 'builtin')",
        (URL, note_id, NOW),
    )
    db.commit()


def _db_only_rows(vault) -> dict[str, list]:
    db = vault.db
    return {
        table: [r[0] for r in db.execute(f"SELECT note_id FROM {table}")]
        for table in ("claims", "embeddings", "assets", "sources")
    }


KEPT = {"claims": ["paper"], "embeddings": ["paper"], "assets": ["paper"], "sources": ["paper"]}
GONE = {"claims": [], "embeddings": [], "assets": [], "sources": [None]}


@pytest.mark.parametrize(
    ("copy", "id_line"),
    [("temp/copy.md", "paper"), ("notes/paper-2.md", '"paper"')],
    ids=["refused-collision-copy", "template-collision-copy"],
)
def test_sync_does_not_give_a_removed_notes_rows_to_a_file_with_other_bytes(tmp_vault, copy, id_line):
    """`note rm paper` unlinks the file and syncs. A file that declares
    `paper` but was never indexed, because every sync refused it as an id
    collision, does not inherit the removed note's claims, embedding, asset
    row and sources row: the note is deleted and the file indexes as a note
    of its own."""
    notes = tmp_vault.notes_dir
    _note(notes / "paper.md", "paper", "Paper", "The paper body.")
    assert _sync(tmp_vault).errors == []
    _seed_db_only_rows(tmp_vault, "paper")
    copy_file = tmp_vault.root / "research" / copy
    _note(copy_file, id_line, "Paper", "Another body that declares the same id.")
    assert [e["path"] for e in _sync(tmp_vault).errors] == [f"research/{copy}"]

    (notes / "paper.md").unlink()
    result = _sync(tmp_vault)

    assert result.errors == []
    assert (result.added, result.updated, result.deleted) == (1, 0, 1)
    assert _rows(tmp_vault) == {"paper": f"research/{copy}"}
    assert _db_only_rows(tmp_vault) == GONE
    assert tmp_vault.db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_sync_treats_a_move_with_an_edit_as_a_delete_and_an_add(tmp_vault):
    """A file moved and edited in the same pass no longer holds the bytes
    the row was indexed from, so sync cannot tell it from any other file
    that declares the id: the row is deleted and the file added, as before
    the move handling."""
    notes = tmp_vault.notes_dir
    _note(notes / "paper.md", "paper", "Paper", "The paper body.")
    assert _sync(tmp_vault).errors == []
    _seed_db_only_rows(tmp_vault, "paper")

    os.rename(notes / "paper.md", notes / "moved.md")
    _note(notes / "moved.md", "paper", "Paper", "The paper body, edited.")
    result = _sync(tmp_vault)

    assert result.errors == []
    assert (result.added, result.updated, result.deleted) == (1, 0, 1)
    assert _rows(tmp_vault) == {"paper": "research/notes/moved.md"}
    body = tmp_vault.db.execute("SELECT body FROM note_content WHERE note_id = 'paper'").fetchone()
    assert "edited" in body["body"]
    assert _db_only_rows(tmp_vault) == GONE
    assert tmp_vault.db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_sync_reads_each_new_file_once_when_a_row_is_gone(tmp_vault, monkeypatch):
    """The scan for moved files reads every new file of a pass in which a
    row's file is gone; the moved file's update and the other files' adds
    use what it read instead of reading each file again."""
    notes = tmp_vault.notes_dir
    _note(notes / "paper.md", "paper", "Paper", "The paper body.")
    assert _sync(tmp_vault).errors == []
    os.rename(notes / "paper.md", notes / "moved.md")
    _note(notes / "one.md", "one", "One", "One body.")
    _note(notes / "two.md", "two", "Two", "Two body.")
    reads: list[str] = []

    def counting_read_note(file_path, vault_root):
        reads.append(file_path.name)
        return read_note(file_path, vault_root)

    monkeypatch.setattr("hyperresearch.core.sync.read_note", counting_read_note)
    result = _sync(tmp_vault)

    assert result.errors == []
    assert (result.added, result.updated, result.deleted) == (2, 1, 0)
    assert sorted(reads) == ["moved.md", "one.md", "two.md"]


def test_sync_undoes_a_move_with_the_rest_of_a_lost_pass(tmp_vault):
    """The moved row's new path is written inside the pass's transaction.
    `z.md` moves to `e.md` with its bytes and `b.md` then fills the capped
    database: SQLite rolls the whole pass back, so the row is at `z.md`
    again with its claim, nothing is counted, and the next sync, with room,
    moves it."""
    notes = tmp_vault.notes_dir
    _note(notes / "b.md", "bee", "B", "B body.")
    _note(notes / "z.md", "zed", "Z", "Z body.")
    assert _sync(tmp_vault).errors == []
    tmp_vault.db.execute(
        "INSERT INTO claims (note_id, claim, claim_hash, ingested_at) VALUES ('zed', 'a claim', 'h1', ?)",
        (NOW,),
    )
    tmp_vault.db.commit()
    before = _rows(tmp_vault)
    pages = tmp_vault.db.execute("PRAGMA page_count").fetchone()[0]
    tmp_vault.db.execute(f"PRAGMA max_page_count = {pages}")

    os.rename(notes / "z.md", notes / "e.md")
    _note(notes / "b.md", "bee", "B", "B body, grown. " + "lorem ipsum " * 10000)
    result = _sync(tmp_vault)

    assert len(result.errors) == 1 and "disk is full" in result.errors[0]["error"]
    assert (result.added, result.updated, result.deleted) == (0, 0, 0)
    assert not tmp_vault.db.in_transaction
    assert _rows(tmp_vault) == before == {"bee": "research/notes/b.md", "zed": "research/notes/z.md"}
    assert [r[0] for r in tmp_vault.db.execute("SELECT note_id FROM claims")] == ["zed"]

    tmp_vault.db.execute("PRAGMA max_page_count = 1073741823")
    result2 = _sync(tmp_vault)
    assert result2.errors == []
    assert (result2.added, result2.updated, result2.deleted) == (0, 2, 0)
    assert _rows(tmp_vault) == {"bee": "research/notes/b.md", "zed": "research/notes/e.md"}
    assert [r[0] for r in tmp_vault.db.execute("SELECT note_id FROM claims")] == ["zed"]
    assert tmp_vault.db.execute("PRAGMA foreign_key_check").fetchall() == []
