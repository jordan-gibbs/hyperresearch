"""A note whose file moves keeps its row and the rows only the database holds.

`note mv`, or a plain `mv` followed by sync, shows up in the sync plan as the
old path deleted and a new file that declares the same id. Sync deleted the
old row first and inserted the id again from the new path: the delete
cascaded the note's claims, embeddings and assets rows away and set its
sources row to NULL, so a refetch of the URL made a duplicate note. The row
now moves in place, as an id edit at the same path does since #159, when the
new file holds the bytes the row was indexed from: a move keeps them.
"""

from __future__ import annotations

import os
import sqlite3

import pytest

from hyperresearch.core.sync import _upsert_note_to_db, compute_sync_plan, execute_sync

NOW = "2026-09-15T00:00:00"
URL = "https://ex.org/paper"


def _note(path, note_id: str | None, title: str, body: str, extra: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    id_line = f"id: {note_id}\n" if note_id else ""
    path.write_text(f"---\n{id_line}title: {title}\n{extra}---\n\n{body}\n", encoding="utf-8")


def _sync(vault):
    return execute_sync(vault, compute_sync_plan(vault))


def _rows(vault) -> dict[str, str]:
    return {r["id"]: r["path"] for r in vault.db.execute("SELECT id, path FROM notes")}


def _seed_db_only_rows(vault, note_id: str):
    """The rows a markdown file cannot rebuild: a claim, an embedding, an
    asset, the fetch dedup row, an escalation and a cached score."""
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
    db.execute(
        "INSERT INTO escalations (url, reason, note_id, created_at, updated_at) "
        "VALUES ('https://ex.org/e', 'login_wall', ?, ?, ?)",
        (note_id, NOW, NOW),
    )
    db.execute("UPDATE notes SET authority_score = 0.75 WHERE id = ?", (note_id,))
    db.commit()
    return shot


def _db_only_rows(vault) -> dict[str, list]:
    db = vault.db
    return {
        "claims": [r[0] for r in db.execute("SELECT note_id FROM claims")],
        "embeddings": [r[0] for r in db.execute("SELECT note_id FROM embeddings")],
        "assets": [r[0] for r in db.execute("SELECT note_id FROM assets")],
        "sources": [r[0] for r in db.execute("SELECT note_id FROM sources")],
        "escalations": [r[0] for r in db.execute("SELECT note_id FROM escalations")],
        "authority_score": [
            r[0] for r in db.execute("SELECT authority_score FROM notes WHERE authority_score IS NOT NULL")
        ],
    }


def _kept(note_id: str) -> dict[str, list]:
    return {
        "claims": [note_id],
        "embeddings": [note_id],
        "assets": [note_id],
        "sources": [note_id],
        "escalations": [note_id],
        "authority_score": [0.75],
    }


@pytest.mark.parametrize(
    ("old", "new", "declared"),
    [
        ("notes/paper.md", "notes/renamed.md", True),
        ("notes/paper.md", "notes/moved/paper.md", True),
        ("notes/paper.md", "temp/paper.md", True),
        ("temp/paper.md", "notes/paper.md", True),
        ("notes/paper.md", "temp/paper.md", False),
    ],
    ids=["rename", "into-a-subdir", "notes-to-temp", "temp-to-notes", "id-from-the-file-name"],
)
def test_sync_moves_a_moved_notes_row_in_place(tmp_vault, old, new, declared):
    research = tmp_vault.root / "research"
    _note(tmp_vault.notes_dir / "other.md", "other", "Other", "Points at [[paper]].")
    _note(research / old, "paper" if declared else None, "Paper", "Moved body [[other]].", "tags: [t1]\n")
    assert _sync(tmp_vault).errors == []
    shot = _seed_db_only_rows(tmp_vault, "paper")

    (research / new).parent.mkdir(parents=True, exist_ok=True)
    os.rename(research / old, research / new)
    result = _sync(tmp_vault)

    assert result.errors == []
    assert (result.added, result.updated, result.deleted) == (0, 1, 0)
    assert _rows(tmp_vault) == {"paper": f"research/{new}", "other": "research/notes/other.md"}
    assert _db_only_rows(tmp_vault) == _kept("paper")
    assert shot.read_bytes() == b"png"
    # The rows the markdown rebuilds are the moved file's.
    db = tmp_vault.db
    body = db.execute("SELECT body FROM note_content WHERE note_id = 'paper'").fetchone()["body"]
    assert "Moved body" in body
    assert [r[0] for r in db.execute("SELECT tag FROM tags WHERE note_id = 'paper'")] == ["t1"]
    hits = db.execute("SELECT id FROM notes_fts WHERE notes_fts MATCH 'moved'").fetchall()
    assert [r["id"] for r in hits] == ["paper"]
    links = {
        (r["source_id"], r["target_id"]) for r in db.execute("SELECT source_id, target_id FROM links")
    }
    assert links == {("paper", "other"), ("other", "paper")}
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []

    plan = compute_sync_plan(tmp_vault)
    assert plan.to_add == [] and plan.to_update == [] and plan.to_delete == []


def test_sync_still_deletes_a_note_whose_file_is_gone_and_unclaimed(tmp_vault):
    """A removed file that no file in the pass claims the id of is a real
    delete, as before: its rows go and its sources row keeps the URL with
    note_id NULL. A new file with an id of its own indexes beside it."""
    notes = tmp_vault.notes_dir
    _note(notes / "paper.md", "paper", "Paper", "Body.")
    assert _sync(tmp_vault).errors == []
    shot = _seed_db_only_rows(tmp_vault, "paper")

    (notes / "paper.md").unlink()
    _note(notes / "fresh.md", "fresh", "Fresh", "Body.")
    result = _sync(tmp_vault)

    assert result.errors == []
    assert (result.added, result.updated, result.deleted) == (1, 0, 1)
    assert _rows(tmp_vault) == {"fresh": "research/notes/fresh.md"}
    rows = _db_only_rows(tmp_vault)
    assert rows["claims"] == rows["embeddings"] == rows["assets"] == []
    assert rows["sources"] == [None]
    assert shot.exists()
    assert tmp_vault.db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_sync_treats_an_id_change_with_the_move_as_a_delete_and_an_add(tmp_vault):
    """A file that moves and declares another id in the same edit is not
    the old note to sync: nothing claims the old id, so its row is deleted
    as before and the new id is a note of its own."""
    notes = tmp_vault.notes_dir
    _note(notes / "paper.md", "paper", "Paper", "Body.")
    assert _sync(tmp_vault).errors == []
    _seed_db_only_rows(tmp_vault, "paper")

    os.rename(notes / "paper.md", notes / "essay.md")
    _note(notes / "essay.md", "essay", "Paper", "Body.")
    result = _sync(tmp_vault)

    assert result.errors == []
    assert (result.added, result.updated, result.deleted) == (1, 0, 1)
    assert _rows(tmp_vault) == {"essay": "research/notes/essay.md"}
    rows = _db_only_rows(tmp_vault)
    assert rows["claims"] == [] and rows["sources"] == [None]
    assert tmp_vault.db.execute("PRAGMA foreign_key_check").fetchall() == []


@pytest.mark.parametrize("copy_first", [False, True])
def test_sync_gives_a_moved_row_to_the_byte_identical_claimant_first_by_path(tmp_vault, copy_first):
    """The file moved and a byte-identical copy of it appeared too: two new
    files hold the bytes of the row whose file is gone. The one first by
    path takes the row with its children whatever order the scan lists them
    in, so every platform picks the same file, and the other collides with
    it."""
    notes = tmp_vault.notes_dir
    _note(notes / "paper.md", "paper", "Paper", "Body.")
    assert _sync(tmp_vault).errors == []
    _seed_db_only_rows(tmp_vault, "paper")

    os.rename(notes / "paper.md", notes / "moved.md")
    _note(tmp_vault.temp_dir / "copy.md", "paper", "Paper", "Body.")
    plan = compute_sync_plan(tmp_vault)
    # The scan order is the filesystem's. Fix it, both ways round.
    plan.to_add.sort(key=lambda p: (p.name == "copy.md") != copy_first)
    first, second = "research/notes/moved.md", "research/temp/copy.md"
    result = execute_sync(tmp_vault, plan)

    assert [e["path"] for e in result.errors] == [second]
    assert f"id collision: 'paper' already belongs to '{first}'" in result.errors[0]["error"]
    assert (result.added, result.updated, result.deleted) == (0, 1, 0)
    assert _rows(tmp_vault) == {"paper": first}
    assert _db_only_rows(tmp_vault) == _kept("paper")
    assert tmp_vault.db.execute("PRAGMA foreign_key_check").fetchall() == []


@pytest.mark.parametrize("copy_first", [False, True])
def test_sync_gives_a_moved_row_to_the_file_that_moved_over_an_edited_copy(tmp_vault, copy_first):
    """An edited copy of the note, refused as an id collision on every sync,
    sits in research/temp/ when the note's own file moves. Both new files
    claim the id; the moved file holds the bytes the row was indexed from,
    so it takes the row and its children whatever the scan order, and the
    copy is refused as before. Given to the copy, the note's claims and
    sources row would describe another file's text and `note mv` would
    leave its own file unindexed."""
    notes = tmp_vault.notes_dir
    _note(notes / "paper.md", "paper", "Paper", "Body.")
    assert _sync(tmp_vault).errors == []
    _seed_db_only_rows(tmp_vault, "paper")
    _note(tmp_vault.temp_dir / "copy.md", "paper", "Paper", "Body, edited in the copy.")
    assert [e["path"] for e in _sync(tmp_vault).errors] == ["research/temp/copy.md"]

    os.rename(notes / "paper.md", notes / "moved.md")
    plan = compute_sync_plan(tmp_vault)
    plan.to_add.sort(key=lambda p: (p.name == "copy.md") != copy_first)
    result = execute_sync(tmp_vault, plan)

    assert [e["path"] for e in result.errors] == ["research/temp/copy.md"]
    assert "id collision: 'paper' already belongs to 'research/notes/moved.md'" in result.errors[0]["error"]
    assert (result.added, result.updated, result.deleted) == (0, 1, 0)
    assert _rows(tmp_vault) == {"paper": "research/notes/moved.md"}
    body = tmp_vault.db.execute("SELECT body FROM note_content WHERE note_id = 'paper'").fetchone()
    assert "edited" not in body["body"]
    assert _db_only_rows(tmp_vault) == _kept("paper")
    assert tmp_vault.db.execute("PRAGMA foreign_key_check").fetchall() == []


@pytest.mark.parametrize("dest", ["paper.md", "moved.md"])
def test_sync_refuses_an_id_edit_that_claims_a_moved_notes_id(tmp_vault, dest):
    """`paper.md` moves to research/temp/ while `essay.md` rewrites its own
    id to `paper` in the same pass. The moved note keeps its id, its row and
    its children, whatever its new file is named; the id edit collides with
    it and `essay.md` stays as it was, rather than taking the id and the
    moved note losing its rows."""
    notes = tmp_vault.notes_dir
    _note(notes / "paper.md", "paper", "Paper", "Body.")
    _note(notes / "essay.md", "essay", "Essay", "Essay body.")
    assert _sync(tmp_vault).errors == []
    _seed_db_only_rows(tmp_vault, "paper")
    tmp_vault.db.execute(
        "INSERT INTO claims (note_id, claim, claim_hash, ingested_at) VALUES ('essay', 'e', 'h2', ?)",
        (NOW,),
    )
    tmp_vault.db.commit()

    tmp_vault.temp_dir.mkdir(parents=True, exist_ok=True)
    os.rename(notes / "paper.md", tmp_vault.temp_dir / dest)
    _note(notes / "essay.md", "paper", "Essay", "Essay body, edited.")
    st = (notes / "essay.md").stat()
    os.utime(notes / "essay.md", (st.st_atime, st.st_mtime + 5))
    result = _sync(tmp_vault)

    assert [e["path"] for e in result.errors] == ["research/notes/essay.md"]
    assert (
        f"id collision: 'paper' already belongs to 'research/temp/{dest}'"
        in result.errors[0]["error"]
    )
    assert _rows(tmp_vault) == {"paper": f"research/temp/{dest}", "essay": "research/notes/essay.md"}
    claims = dict(tmp_vault.db.execute("SELECT claim_hash, note_id FROM claims").fetchall())
    assert claims == {"h1": "paper", "h2": "essay"}
    assert [r[0] for r in tmp_vault.db.execute("SELECT note_id FROM sources")] == ["paper"]
    assert tmp_vault.db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_sync_keeps_the_row_of_a_moved_file_whose_upsert_fails(tmp_vault, monkeypatch):
    """A moved file whose upsert fails leaves its row at the new path with
    its children, the error is reported and the pass commits the rest.
    Deleting the row, as a delete of the old path would, cascaded the
    claims, embedding and asset rows away for good. The row already holds
    the file's bytes, so the next sync has nothing left to do."""
    notes = tmp_vault.notes_dir
    _note(notes / "paper.md", "paper", "Paper", "Body.", "tags: [t1]\n")
    assert _sync(tmp_vault).errors == []
    _seed_db_only_rows(tmp_vault, "paper")

    os.rename(notes / "paper.md", notes / "moved.md")
    _note(notes / "fresh.md", "fresh", "Fresh", "Fresh body.")

    def failing_upsert(conn, note, *args, **kwargs):
        # Fail after the writes, so the savepoint has them to undo.
        _upsert_note_to_db(conn, note, *args, **kwargs)
        if note.meta.id == "paper":
            raise sqlite3.IntegrityError("simulated upsert failure")

    monkeypatch.setattr("hyperresearch.core.sync._upsert_note_to_db", failing_upsert)
    result = _sync(tmp_vault)

    assert len(result.errors) == 1 and result.errors[0]["path"].endswith("moved.md")
    assert "simulated upsert failure" in result.errors[0]["error"]
    assert (result.added, result.updated, result.deleted) == (1, 0, 0)
    assert not tmp_vault.db.in_transaction
    assert _rows(tmp_vault) == {"paper": "research/notes/moved.md", "fresh": "research/notes/fresh.md"}
    assert _db_only_rows(tmp_vault) == _kept("paper")
    db = tmp_vault.db
    assert [r[0] for r in db.execute("SELECT tag FROM tags WHERE note_id = 'paper'")] == ["t1"]
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []

    monkeypatch.undo()
    result2 = _sync(tmp_vault)
    assert result2.errors == []
    assert (result2.added, result2.updated, result2.deleted) == (0, 0, 0)
    assert _rows(tmp_vault) == {"paper": "research/notes/moved.md", "fresh": "research/notes/fresh.md"}
    assert _db_only_rows(tmp_vault) == _kept("paper")
