"""Tests for the sync engine."""

import os
import sqlite3

import pytest

from hyperresearch.core.sync import compute_sync_plan, execute_sync


def test_sync_adds_new_files(tmp_vault):
    from hyperresearch.core.note import write_note

    write_note(tmp_vault.notes_dir, "Note A", body="# A\n\nContent.", tags=["test"])
    write_note(tmp_vault.notes_dir, "Note B", body="# B\n\nMore content.", tags=["test"])

    plan = compute_sync_plan(tmp_vault)
    assert len(plan.to_add) == 2
    assert len(plan.to_delete) == 0

    result = execute_sync(tmp_vault, plan)
    assert result.added == 2
    assert result.errors == []

    # Verify in DB
    count = tmp_vault.db.execute("SELECT COUNT(*) as c FROM notes").fetchone()["c"]
    assert count == 2


def test_sync_detects_updates(tmp_vault):
    from hyperresearch.core.note import write_note

    path = write_note(tmp_vault.notes_dir, "Updatable", body="# V1\n\nOriginal.")
    plan = compute_sync_plan(tmp_vault)
    execute_sync(tmp_vault, plan)

    # Modify the file
    import time
    time.sleep(0.1)
    path.write_text(path.read_text().replace("Original", "Updated"), encoding="utf-8")

    plan2 = compute_sync_plan(tmp_vault)
    assert len(plan2.to_update) == 1


def test_sync_detects_deletes(tmp_vault):
    from hyperresearch.core.note import write_note

    path = write_note(tmp_vault.notes_dir, "Deletable", body="# Delete me")
    plan = compute_sync_plan(tmp_vault)
    execute_sync(tmp_vault, plan)

    # Delete the file
    path.unlink()

    plan2 = compute_sync_plan(tmp_vault)
    assert len(plan2.to_delete) == 1

    result = execute_sync(tmp_vault, plan2)
    assert result.deleted == 1

    count = tmp_vault.db.execute("SELECT COUNT(*) as c FROM notes").fetchone()["c"]
    assert count == 0


def test_sync_populates_fts(seeded_vault):
    rows = seeded_vault.db.execute(
        "SELECT id FROM notes_fts WHERE notes_fts MATCH 'python'"
    ).fetchall()
    assert len(rows) > 0


def test_sync_populates_tags(seeded_vault):
    rows = seeded_vault.db.execute(
        "SELECT DISTINCT tag FROM tags ORDER BY tag"
    ).fetchall()
    tags = [r["tag"] for r in rows]
    assert "python" in tags
    assert "rust" in tags
    assert "concurrency" in tags


def test_sync_lowercases_tags(tmp_vault):
    """Frontmatter tags must be stored lowercase so SearchFilters (which
    lowercases the query side) can match them. Without this, `--tag llm`
    silently returns zero rows for any note tagged `LLM`."""
    from hyperresearch.core.note import write_note

    write_note(
        tmp_vault.notes_dir,
        "Mixed-case tags note",
        body="# Body\n",
        tags=["LLM", "Mamba", "rust"],
    )
    plan = compute_sync_plan(tmp_vault, force=True)
    execute_sync(tmp_vault, plan)

    rows = tmp_vault.db.execute(
        "SELECT tag FROM tags ORDER BY tag"
    ).fetchall()
    stored = sorted(r["tag"] for r in rows)
    assert stored == ["llm", "mamba", "rust"]
    # Crucially, no uppercase variant slipped through.
    assert "LLM" not in stored
    assert "Mamba" not in stored


def test_sync_resolves_alias_for_uppercase_tag(tmp_vault):
    """Alias keys are stored lowercase (cli/tag.py), so the lookup must
    lowercase the frontmatter tag FIRST — `ML` must resolve through the
    `ml -> machine-learning` alias, not bypass it."""
    from hyperresearch.core.note import write_note

    tmp_vault.db.execute(
        "INSERT INTO tag_aliases (alias, canonical) VALUES (?, ?)",
        ("ml", "machine-learning"),
    )
    tmp_vault.db.commit()
    write_note(
        tmp_vault.notes_dir,
        "Aliased uppercase tag note",
        body="# Body\n",
        tags=["ML"],
    )
    plan = compute_sync_plan(tmp_vault, force=True)
    execute_sync(tmp_vault, plan)

    stored = [r["tag"] for r in tmp_vault.db.execute("SELECT tag FROM tags")]
    assert stored == ["machine-learning"]


def test_sync_populates_links(seeded_vault):
    rows = seeded_vault.db.execute(
        "SELECT source_id, target_ref, target_id FROM links"
    ).fetchall()
    assert len(rows) > 0

    # Check that existing notes are resolved
    resolved = [r for r in rows if r["target_id"] is not None]
    assert len(resolved) > 0

    # Check that nonexistent-topic is unresolved
    broken = [r for r in rows if r["target_ref"] == "nonexistent-topic"]
    assert len(broken) == 1
    assert broken[0]["target_id"] is None


def test_sync_excludes_hyperresearch_dir(tmp_vault):
    """Files in .hyperresearch/ should never be synced."""
    (tmp_vault.root / ".hyperresearch" / "test.md").write_text("---\ntitle: Bad\n---\nShould not sync")
    plan = compute_sync_plan(tmp_vault)
    assert all(".hyperresearch" not in str(p) for p in plan.to_add)


def test_sync_excludes_research_root_staging_files(tmp_vault):
    """Files at research/ root (scaffold.md, comparisons.md, synthesis.md)
    are staging files the agent writes then registers via `note new`. They
    must NOT appear as orphan notes in the vault index — the current
    behavior would produce missing-title/tags/summary lint spam on every run.
    """
    from hyperresearch.core.note import write_note

    # Real notes under research/notes/
    write_note(tmp_vault.notes_dir, "Real Note", body="# Real\n")

    # Staging files at research/ root
    research_root = tmp_vault.research_dir
    (research_root / "scaffold.md").write_text("# Scaffold staging\n")
    (research_root / "comparisons.md").write_text("# Comparisons staging\n")
    (research_root / "synthesis.md").write_text("# Synthesis staging\n")

    plan = compute_sync_plan(tmp_vault)

    # Only the real note should be added.
    added_names = [p.name for p in plan.to_add]
    assert "real-note.md" in added_names
    assert "scaffold.md" not in added_names
    assert "comparisons.md" not in added_names
    assert "synthesis.md" not in added_names


def test_sync_skips_frontmatterless_scratch_files(tmp_vault):
    """Issue #25: agent subagents write plain-markdown scratch body files
    under research/temp/ (e.g. interim-report-<locus>.md) before passing
    them to `note new --body-file`. Those files MUST NOT enter the note
    index — they collide on derived id with the canonical notes created
    from them and silently smash the canonical row's path.
    """
    from hyperresearch.core.note import write_note

    # Canonical note (frontmatter present).
    write_note(tmp_vault.notes_dir, "Interim Report Foo", body="# Real\n", note_id="interim-report-foo")

    # Scratch body file at research/temp/ (no frontmatter).
    tmp_vault.temp_dir.mkdir(parents=True, exist_ok=True)
    (tmp_vault.temp_dir / "interim-report-foo.md").write_text("# Interim report: foo\n\nbody\n")

    # Also: nested temp/ inside an arbitrary sub-tree (e.g. run-dir layout).
    nested = tmp_vault.research_dir / "runs" / "abc" / "temp"
    nested.mkdir(parents=True)
    (nested / "scratch.md").write_text("body without frontmatter\n")

    plan = compute_sync_plan(tmp_vault)

    added_rels = [str(p.relative_to(tmp_vault.root)).replace("\\", "/") for p in plan.to_add]
    assert "research/notes/interim-report-foo.md" in added_rels
    assert all("temp/" not in r for r in added_rels)

    result = execute_sync(tmp_vault, plan)
    assert result.added == 1
    assert result.errors == []

    # The canonical note's path is what's in the DB, not the scratch path.
    row = tmp_vault.db.execute(
        "SELECT path FROM notes WHERE id = ?", ("interim-report-foo",)
    ).fetchone()
    assert row["path"] == "research/notes/interim-report-foo.md"


def test_sync_includes_stub_notes_in_temp(tmp_vault):
    """research/temp/ doubles as the home for stub notes the `graph stub`
    command creates to resolve broken wiki-links. Those notes carry full
    YAML frontmatter and MUST continue to sync — the issue #25 fix is
    content-based, not path-based, precisely to keep this working.
    """
    from hyperresearch.core.note import write_note

    write_note(
        tmp_vault.temp_dir,
        "Stub Topic",
        body="# Stub Topic\n\n*Stub — created to resolve a broken link.*\n",
        note_id="stub-topic",
        status="draft",
        summary="Stub for [[stub-topic]]",
    )

    plan = compute_sync_plan(tmp_vault)
    added_names = [p.name for p in plan.to_add]
    assert "stub-topic.md" in added_names

    result = execute_sync(tmp_vault, plan)
    assert result.added == 1
    assert result.errors == []
    row = tmp_vault.db.execute("SELECT id FROM notes WHERE id = ?", ("stub-topic",)).fetchone()
    assert row is not None


def test_sync_surfaces_duplicate_id_collision_as_error(tmp_vault):
    """Defense-in-depth (#25): if a new file claims an id already owned by
    another file in the vault, the second one must NOT silently smash the
    first's row. Surface it as a result.errors entry instead.
    """
    from hyperresearch.core.note import write_note

    # Establish the canonical first.
    write_note(tmp_vault.notes_dir, "Topic", note_id="topic", body="# Topic A\n")
    plan1 = compute_sync_plan(tmp_vault)
    result1 = execute_sync(tmp_vault, plan1)
    assert result1.added == 1
    assert result1.errors == []

    # Drop a second file elsewhere that hand-rolls the same id in frontmatter.
    tmp_vault.temp_dir.mkdir(parents=True, exist_ok=True)
    (tmp_vault.temp_dir / "duplicate.md").write_text(
        "---\nid: topic\ntitle: Topic Duplicate\n---\n\n# Topic B\n"
    )

    plan2 = compute_sync_plan(tmp_vault)
    result2 = execute_sync(tmp_vault, plan2)

    assert result2.added == 0
    assert len(result2.errors) == 1
    assert "id collision" in result2.errors[0]["error"]

    # The canonical path is preserved.
    row = tmp_vault.db.execute("SELECT path FROM notes WHERE id = ?", ("topic",)).fetchone()
    assert row["path"] == "research/notes/topic.md"


def test_sync_cleans_up_stale_collided_row(tmp_vault):
    """Pre-fix vaults can have a DB row whose `path` points into research/temp/
    (the scratch file won the UPSERT race). After the fix lands, that file no
    longer enters the sync plan as an add/update; instead it appears in
    `to_delete` so the bad row goes away on the next sync. The canonical
    file then re-adds cleanly.
    """
    from hyperresearch.core.note import write_note

    # Simulate the pre-fix DB state directly.
    write_note(tmp_vault.notes_dir, "Foo", note_id="foo", body="# Foo\n")
    plan = compute_sync_plan(tmp_vault)
    execute_sync(tmp_vault, plan)

    # Stamp the DB row's path onto a scratch location, as the old race would.
    tmp_vault.db.execute(
        "UPDATE notes SET path = ? WHERE id = ?",
        ("research/temp/foo.md", "foo"),
    )
    tmp_vault.db.commit()
    tmp_vault.temp_dir.mkdir(parents=True, exist_ok=True)
    (tmp_vault.temp_dir / "foo.md").write_text("scratch body without frontmatter\n")

    plan2 = compute_sync_plan(tmp_vault)
    # The scratch file is not in to_add (no frontmatter); the stale db path
    # is in to_delete; the canonical file is in to_add.
    to_delete_paths = list(plan2.to_delete)
    to_add_rels = [str(p.relative_to(tmp_vault.root)).replace("\\", "/") for p in plan2.to_add]
    assert "research/temp/foo.md" in to_delete_paths
    assert "research/notes/foo.md" in to_add_rels

    result = execute_sync(tmp_vault, plan2)
    assert result.errors == []
    row = tmp_vault.db.execute("SELECT path FROM notes WHERE id = ?", ("foo",)).fetchone()
    assert row["path"] == "research/notes/foo.md"


# ---------------------------------------------------------------------------
# An id rewrite on an existing path. A file whose path already has a row and
# whose `id:` now differs used to go through the upsert as an INSERT of the new
# id: UNIQUE(notes.path) refused it, the stale row kept the old id, and on the
# next run the OTHER file that legitimately owns the old id was reported as an
# id collision against the stale path, on every sync, until the rewritten file
# was renamed or moved away and back, which drops the rows only the database
# holds (its claims, embeddings and assets).
# ---------------------------------------------------------------------------


def _note_with_id(path, note_id: str, title: str, body: str, extra: str = ""):
    """Write a note with an explicit id; `extra` is more frontmatter lines."""
    rewrite = path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nid: {note_id}\ntitle: {title}\n{extra}---\n\n{body}\n", encoding="utf-8")
    if rewrite:
        # A rewrite within one filesystem timestamp tick keeps the old mtime,
        # and the sync plan skips a file whose mtime did not move. Step it
        # forward so the plan sees the edit, as it would for a real one.
        st = path.stat()
        os.utime(path, (st.st_atime, st.st_mtime + 5))


SOURCE_B = "source: https://ex.org/b\n"


def test_sync_rewrites_a_note_id_in_place_and_frees_the_old_one(tmp_vault):
    notes = tmp_vault.notes_dir
    loser = notes / "topic-2.md"
    winner = notes / "topic.md"

    # The shadowed-id state: the `-2` file won the row for id `topic`, so the
    # real owner collides on every sync.
    _note_with_id(loser, "topic", "Topic (dup)", "Second body [[other]].", extra=SOURCE_B)
    assert execute_sync(tmp_vault, compute_sync_plan(tmp_vault)).errors == []
    tmp_vault.db.execute(
        "INSERT INTO sources (url, note_id, domain, fetched_at, provider) VALUES (?, ?, ?, ?, ?)",
        ("https://ex.org/b", "topic", "ex.org", "2026-09-15T00:00:00", "builtin"),
    )
    tmp_vault.db.execute(
        "INSERT INTO claims (note_id, claim, claim_hash, ingested_at) VALUES (?, ?, ?, ?)",
        ("topic", "a claim", "h1", "2026-09-15T00:00:00"),
    )
    tmp_vault.db.commit()
    _note_with_id(winner, "topic", "Topic", "First body.")
    r = execute_sync(tmp_vault, compute_sync_plan(tmp_vault))
    assert len(r.errors) == 1 and "id collision" in r.errors[0]["error"]

    # The repair a user would make: rewrite only the loser's `id:` line.
    _note_with_id(loser, "topic-2", "Topic (dup)", "Second body [[other]].", extra=SOURCE_B)

    result = execute_sync(tmp_vault, compute_sync_plan(tmp_vault))
    assert result.errors == []
    rows = {
        r["id"]: r["path"]
        for r in tmp_vault.db.execute("SELECT id, path FROM notes ORDER BY id")
    }
    assert rows == {"topic": "research/notes/topic.md", "topic-2": "research/notes/topic-2.md"}

    # Children the markdown cannot rebuild moved with the row: the fetch dedup
    # map still knows the URL, under the new id, and the extracted claim survived.
    src = tmp_vault.db.execute("SELECT note_id FROM sources WHERE url = ?", ("https://ex.org/b",)).fetchone()
    assert src["note_id"] == "topic-2"
    claim = tmp_vault.db.execute("SELECT note_id FROM claims WHERE claim_hash = ?", ("h1",)).fetchone()
    assert claim["note_id"] == "topic-2"
    # Rebuilt children carry the right id on each side: `topic` is now the
    # winner's row, `topic-2` the loser's, and no FTS or link row dangles.
    body = tmp_vault.db.execute("SELECT body FROM note_content WHERE note_id = ?", ("topic",)).fetchone()
    assert "First body" in body["body"]
    body2 = tmp_vault.db.execute("SELECT body FROM note_content WHERE note_id = ?", ("topic-2",)).fetchone()
    assert "Second body" in body2["body"]
    links = {
        (r["source_id"], r["target_ref"])
        for r in tmp_vault.db.execute("SELECT source_id, target_ref FROM links")
    }
    assert links == {("topic-2", "other")}
    fts_ids = sorted(r["id"] for r in tmp_vault.db.execute("SELECT id FROM notes_fts"))
    assert fts_ids == ["topic", "topic-2"]

    # And the second pass is a no-op with no errors.
    plan2 = compute_sync_plan(tmp_vault)
    assert plan2.to_add == [] and plan2.to_update == [] and plan2.to_delete == []
    assert execute_sync(tmp_vault, plan2).errors == []


def test_sync_id_rewrite_moves_every_child_row_when_nothing_takes_the_old_id(tmp_vault):
    """A plain id rewrite with no other file claiming the old id. Nothing
    later in the pass touches rows under the old id, so the rename itself
    has to leave none behind: it moves the rows only the database holds and
    drops the ones the upsert rebuilds under the new id, the two without a
    foreign key (notes_fts and links) included. The asset file stays where
    it is: its row names it by full path and keeps resolving."""
    notes = tmp_vault.notes_dir
    extra = "tags: [t1]\naliases: [Dup]\n"
    _note_with_id(notes / "other.md", "other", "Other", "Points at [[topic]].")
    _note_with_id(notes / "topic-2.md", "topic", "Topic (dup)", "Second body [[other]].", extra=extra)
    assert execute_sync(tmp_vault, compute_sync_plan(tmp_vault)).errors == []
    # Rows only the database holds. `escalations.note_id` has no foreign key,
    # so nothing but the rename would notice it staying behind.
    now = "2026-09-15T00:00:00"
    tmp_vault.db.execute(
        "INSERT INTO embeddings (note_id, model, dimensions, vector, created_at) VALUES (?, ?, ?, ?, ?)",
        ("topic", "m", 1, b"\x00", now),
    )
    shot = tmp_vault.root / "research" / "assets" / "topic" / "screenshot.png"
    shot.parent.mkdir(parents=True)
    shot.write_bytes(b"png")
    tmp_vault.db.execute(
        "INSERT INTO assets (note_id, type, filename, created_at) VALUES (?, ?, ?, ?)",
        ("topic", "screenshot", str(shot), now),
    )
    tmp_vault.db.execute(
        "INSERT INTO escalations (url, reason, note_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        ("https://ex.org/e", "login_wall", "topic", now, now),
    )
    tmp_vault.db.commit()

    _note_with_id(notes / "topic-2.md", "topic-2", "Topic (dup)", "Second body [[other]].", extra=extra)
    result = execute_sync(tmp_vault, compute_sync_plan(tmp_vault))
    assert result.errors == [] and result.updated == 1

    rows = {r["id"]: r["path"] for r in tmp_vault.db.execute("SELECT id, path FROM notes")}
    assert rows == {"other": "research/notes/other.md", "topic-2": "research/notes/topic-2.md"}
    for table, column in (
        ("notes_fts", "id"), ("note_content", "note_id"), ("tags", "note_id"),
        ("aliases", "note_id"), ("links", "source_id"), ("embeddings", "note_id"),
        ("assets", "note_id"), ("escalations", "note_id"),
    ):
        ids = {r[0] for r in tmp_vault.db.execute(f"SELECT {column} FROM {table}")}
        assert "topic" not in ids and "topic-2" in ids, table
    # The FTS row was rebuilt under the new id: the body is searchable under
    # it, and the incoming [[topic]] link no longer resolves to anything.
    hit = tmp_vault.db.execute("SELECT id FROM notes_fts WHERE notes_fts MATCH 'second'").fetchall()
    assert [r["id"] for r in hit] == ["topic-2"]
    link = tmp_vault.db.execute("SELECT target_id FROM links WHERE source_id = 'other'").fetchone()
    assert link["target_id"] is None
    assets = [tuple(r) for r in tmp_vault.db.execute("SELECT note_id, filename FROM assets")]
    assert assets == [("topic-2", str(shot))] and shot.read_bytes() == b"png"


def test_sync_id_rewrite_covers_every_table_with_a_foreign_key_to_notes(tmp_vault):
    """A child table added to the schema later has to be added to the rename
    too: rows it left behind would fail the commit of every pass that holds
    an id rewrite."""
    from hyperresearch.core.sync import (
        _NOTE_ID_MOVED_TABLES,
        _NOTE_ID_REBUILT_TABLES,
        _NOTE_ID_URL_TABLES,
    )

    conn = tmp_vault.db
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
    referencing = {
        table for table in tables
        for fk in conn.execute(f"PRAGMA foreign_key_list('{table}')")
        if fk["table"] == "notes"
    }
    handled = {*_NOTE_ID_MOVED_TABLES, *_NOTE_ID_REBUILT_TABLES, *_NOTE_ID_URL_TABLES}
    assert referencing and referencing <= handled


def test_sync_id_rewrite_whose_upsert_fails_leaves_the_row_and_its_children_alone(tmp_vault):
    """The rename and the upsert succeed or fail together. `a.md` rewrites
    its id from `xid` to `yid` and, in the same edit, carries a duplicate
    alias that the aliases primary key refuses inside the upsert. Its row
    stays under `xid` with its claims and sources rows, a new file that
    claims `xid` in the same pass is still a collision, and a new file that
    claims `yid`, which nothing owns, indexes. `d.md`, an ordinary edit with
    the same bad alias, fails the same way. Both failed files keep their old
    content hash, so the next run reports them again rather than counting
    them as synced."""
    notes = tmp_vault.notes_dir
    _note_with_id(notes / "a.md", "xid", "A", "A body.")
    _note_with_id(notes / "d.md", "dee", "D", "D body.")
    assert execute_sync(tmp_vault, compute_sync_plan(tmp_vault)).errors == []
    tmp_vault.db.execute(
        "INSERT INTO sources (url, note_id, domain, fetched_at, provider) VALUES (?, ?, ?, ?, ?)",
        ("https://ex.org/a", "xid", "ex.org", "2026-09-15T00:00:00", "builtin"),
    )
    tmp_vault.db.execute(
        "INSERT INTO claims (note_id, claim, claim_hash, ingested_at) VALUES (?, ?, ?, ?)",
        ("xid", "a claim", "h1", "2026-09-15T00:00:00"),
    )
    tmp_vault.db.commit()

    _note_with_id(notes / "a.md", "yid", "A", "A body.", extra="aliases: [dup, dup]\n")
    _note_with_id(notes / "b.md", "yid", "B", "B body.")
    _note_with_id(notes / "c.md", "xid", "C", "C body.")
    _note_with_id(notes / "d.md", "dee", "D", "D body, edited.", extra="aliases: [dup, dup]\n")
    result = execute_sync(tmp_vault, compute_sync_plan(tmp_vault))

    errors = {os.path.basename(e["path"]): e["error"] for e in result.errors}
    assert set(errors) == {"a.md", "c.md", "d.md"}
    assert "aliases" in errors["a.md"] and "aliases" in errors["d.md"]
    assert "id collision: 'xid' already belongs to 'research/notes/a.md'" in errors["c.md"]
    assert result.added == 1 and result.updated == 0
    rows = {r["id"]: r["path"] for r in tmp_vault.db.execute("SELECT id, path FROM notes")}
    assert rows == {"xid": "research/notes/a.md", "yid": "research/notes/b.md", "dee": "research/notes/d.md"}
    assert [r["note_id"] for r in tmp_vault.db.execute("SELECT note_id FROM claims")] == ["xid"]
    assert [r["note_id"] for r in tmp_vault.db.execute("SELECT note_id FROM sources")] == ["xid"]
    assert tmp_vault.db.execute("SELECT COUNT(*) FROM aliases").fetchone()[0] == 0
    fts_ids = sorted(r["id"] for r in tmp_vault.db.execute("SELECT id FROM notes_fts"))
    assert fts_ids == ["dee", "xid", "yid"]
    body = tmp_vault.db.execute("SELECT body FROM note_content WHERE note_id = 'dee'").fetchone()
    assert "edited" not in body["body"]
    assert tmp_vault.db.execute("PRAGMA foreign_key_check").fetchall() == []

    # The next run reports both again (`a.md` now as the ordinary collision
    # with `b.md`); nothing moves.
    result2 = execute_sync(tmp_vault, compute_sync_plan(tmp_vault))
    errors2 = {os.path.basename(e["path"]): e["error"] for e in result2.errors}
    assert set(errors2) == {"a.md", "c.md", "d.md"} and "aliases" in errors2["d.md"]
    rows2 = {r["id"]: r["path"] for r in tmp_vault.db.execute("SELECT id, path FROM notes")}
    assert rows2 == rows


def test_sync_stops_the_pass_once_the_transaction_is_lost(tmp_vault):
    """A whole-transaction rollback takes the pass's earlier writes with it,
    a delete and a rename included, while the collision maps still describe
    them. `z.md` is gone from disk, `a.md` rewrites its id from `xid` to
    `yid`, `b.md` then fills the capped database, `d.md` is an ordinary
    edit, and new `c.md` and `e.md` claim `xid` and `zed`, which the maps
    call free. Neither may land on a restored row and take its claims and
    sources rows: the pass stops at the rollback and keeps nothing, and the
    next sync does all six files."""
    notes = tmp_vault.notes_dir
    _note_with_id(notes / "a.md", "xid", "A", "A body.")
    _note_with_id(notes / "b.md", "bee", "B", "B body.")
    _note_with_id(notes / "d.md", "dee", "D", "D body.")
    _note_with_id(notes / "z.md", "zed", "Z", "Z body.")
    assert execute_sync(tmp_vault, compute_sync_plan(tmp_vault)).errors == []
    tmp_vault.db.execute(
        "INSERT INTO sources (url, note_id, domain, fetched_at, provider) VALUES (?, ?, ?, ?, ?)",
        ("https://ex.org/a", "xid", "ex.org", "2026-09-15T00:00:00", "builtin"),
    )
    for note_id, claim_hash in (("xid", "h1"), ("zed", "h2")):
        tmp_vault.db.execute(
            "INSERT INTO claims (note_id, claim, claim_hash, ingested_at) VALUES (?, ?, ?, ?)",
            (note_id, "a claim", claim_hash, "2026-09-15T00:00:00"),
        )
    tmp_vault.db.commit()
    before = {r["id"]: r["path"] for r in tmp_vault.db.execute("SELECT id, path FROM notes")}
    pages = tmp_vault.db.execute("PRAGMA page_count").fetchone()[0]
    tmp_vault.db.execute(f"PRAGMA max_page_count = {pages}")

    (notes / "z.md").unlink()
    _note_with_id(notes / "a.md", "yid", "A", "A body.")
    _note_with_id(notes / "b.md", "bee", "B", "B body, grown. " + "lorem ipsum " * 10000)
    _note_with_id(notes / "c.md", "xid", "C", "C body.")
    _note_with_id(notes / "d.md", "dee", "D", "D body, edited.")
    _note_with_id(notes / "e.md", "zed", "E", "E body.")
    plan = compute_sync_plan(tmp_vault)
    # The scan order is the filesystem's. Fix it, so the rename comes first.
    plan.to_update.sort(key=lambda p: p.name)
    plan.to_add.sort(key=lambda p: p.name)
    assert [p.name for p in plan.to_update] == ["a.md", "b.md", "d.md"]
    assert [p.name for p in plan.to_add] == ["c.md", "e.md"]
    assert plan.to_delete == ["research/notes/z.md"]
    result = execute_sync(tmp_vault, plan)

    rows = {r["id"]: r["path"] for r in tmp_vault.db.execute("SELECT id, path FROM notes")}
    assert rows == before
    assert rows["xid"] == "research/notes/a.md"
    claims = sorted(r["note_id"] for r in tmp_vault.db.execute("SELECT note_id FROM claims"))
    assert claims == ["xid", "zed"]
    assert [r["note_id"] for r in tmp_vault.db.execute("SELECT note_id FROM sources")] == ["xid"]
    body = tmp_vault.db.execute("SELECT body FROM note_content WHERE note_id = 'dee'").fetchone()
    assert "edited" not in body["body"]
    assert len(result.errors) == 1
    assert result.errors[0]["path"].endswith("b.md")
    assert "disk is full" in result.errors[0]["error"]
    # Nothing was kept, and the summary says so.
    assert (result.added, result.updated, result.deleted) == (0, 0, 0)
    assert not tmp_vault.db.in_transaction

    # With room again, the next sync does the whole plan: the delete goes
    # first and takes `zed`'s claim with it, the rename moves the row with
    # its children, and `c.md` and `e.md` get rows of their own.
    tmp_vault.db.execute("PRAGMA max_page_count = 1073741823")
    plan2 = compute_sync_plan(tmp_vault)
    assert sorted(p.name for p in plan2.to_update) == ["a.md", "b.md", "d.md"]
    assert sorted(p.name for p in plan2.to_add) == ["c.md", "e.md"]
    result2 = execute_sync(tmp_vault, plan2)
    assert result2.errors == []
    assert (result2.added, result2.updated, result2.deleted) == (2, 3, 1)
    rows2 = {r["id"]: r["path"] for r in tmp_vault.db.execute("SELECT id, path FROM notes")}
    assert rows2 == {
        "yid": "research/notes/a.md",
        "bee": "research/notes/b.md",
        "xid": "research/notes/c.md",
        "dee": "research/notes/d.md",
        "zed": "research/notes/e.md",
    }
    assert [r["note_id"] for r in tmp_vault.db.execute("SELECT note_id FROM claims")] == ["yid"]
    assert [r["note_id"] for r in tmp_vault.db.execute("SELECT note_id FROM sources")] == ["yid"]
    assert tmp_vault.db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_sync_stops_the_pass_when_a_delete_loses_the_transaction(tmp_vault, monkeypatch):
    """The same rule in the delete loop. SQLite's own rollback is stood in
    for by a delete that rolls the transaction back and raises, because a
    delete cannot be made to fill the database."""
    notes = tmp_vault.notes_dir
    for name in ("gone-1", "gone-2", "kept"):
        _note_with_id(notes / f"{name}.md", name, name, f"{name} body.")
    assert execute_sync(tmp_vault, compute_sync_plan(tmp_vault)).errors == []
    (notes / "gone-1.md").unlink()
    (notes / "gone-2.md").unlink()
    _note_with_id(notes / "kept.md", "kept", "kept", "kept body, edited.")
    _note_with_id(notes / "new.md", "new", "new", "new body.")
    calls = []

    def losing_delete(conn, note_id):
        calls.append(note_id)
        conn.rollback()
        raise sqlite3.OperationalError("database or disk is full")

    monkeypatch.setattr("hyperresearch.core.sync._delete_note_from_db", losing_delete)
    result = execute_sync(tmp_vault, compute_sync_plan(tmp_vault))

    assert len(calls) == 1
    assert len(result.errors) == 1 and "disk is full" in result.errors[0]["error"]
    assert (result.added, result.updated, result.deleted) == (0, 0, 0)
    ids = sorted(r["id"] for r in tmp_vault.db.execute("SELECT id FROM notes"))
    assert ids == ["gone-1", "gone-2", "kept"]
    body = tmp_vault.db.execute("SELECT body FROM note_content WHERE note_id = 'kept'").fetchone()
    assert "edited" not in body["body"]


def test_sync_registers_capped_collision_notes_separately(tmp_vault):
    """Two notes whose titles collide on the slug length cap must land as two
    DB rows — the orphan-note bug collapsed the second into the first id and
    sync then refused it, so the note existed on disk but never in the DB."""
    from hyperresearch.core.note import write_note

    long_title = "y" * 120
    p1 = write_note(tmp_vault.notes_dir, long_title, body="Eerste.")
    p2 = write_note(tmp_vault.notes_dir, long_title, body="Tweede.")

    plan = compute_sync_plan(tmp_vault)
    result = execute_sync(tmp_vault, plan)
    assert result.errors == []

    rows = tmp_vault.db.execute("SELECT id FROM notes ORDER BY id").fetchall()
    ids = {r["id"] for r in rows}
    assert ids == {p1.stem, p2.stem}


def test_sync_skips_bracketed_markdown_link_labels(tmp_vault):
    """`[[Foo]](https://x)` is a markdown link with a bracketed label, not a
    wiki-link. It must produce NO row in `links` — otherwise `repair --stub`
    (the default) mints a stub note named `Foo` for it (issue #93).
    """
    from hyperresearch.core.note import write_note

    write_note(
        tmp_vault.notes_dir,
        "Awesome List",
        body=(
            "# Awesome List\n\n"
            "- [[Foo]](https://x.example/foo) — a bracketed markdown label\n"
            "- [[Bar|Display]](https://x.example/bar)\n"
            "- [[real-target]] (2024) — a real wiki-link with a parenthetical\n"
        ),
        note_id="awesome-list",
    )

    plan = compute_sync_plan(tmp_vault, force=True)
    result = execute_sync(tmp_vault, plan)
    assert result.errors == []

    refs = sorted(
        r["target_ref"]
        for r in tmp_vault.db.execute(
            "SELECT target_ref FROM links WHERE source_id = ?", ("awesome-list",)
        ).fetchall()
    )
    assert refs == ["real-target"]


def test_sync_does_not_rekey_a_note_whose_frontmatter_lost_its_id(tmp_vault):
    """A file whose frontmatter stops parsing (a lost closing `---`, or a
    watch read mid-write) reads with the filename as its id. That is not an
    id edit: the row, its claims and the links to it stay as they were."""
    notes = tmp_vault.notes_dir
    _note_with_id(notes / "renamed.md", "topic", "Topic", "Body.")
    _note_with_id(notes / "other.md", "other", "Other", "See [[topic]].")
    assert execute_sync(tmp_vault, compute_sync_plan(tmp_vault)).errors == []
    tmp_vault.db.execute(
        "INSERT INTO claims (note_id, claim, claim_hash, ingested_at) VALUES (?, ?, ?, ?)",
        ("topic", "a claim", "h1", "2026-09-15T00:00:00"),
    )
    tmp_vault.db.commit()

    path = notes / "renamed.md"
    path.write_text("---\nid: topic\ntitle: Topic\n\nBody, edited.\n", encoding="utf-8")
    st = path.stat()
    os.utime(path, (st.st_atime, st.st_mtime + 5))
    result = execute_sync(tmp_vault, compute_sync_plan(tmp_vault))

    assert len(result.errors) == 1 and "declares no id" in result.errors[0]["error"]
    rows = {r["id"]: r["path"] for r in tmp_vault.db.execute("SELECT id, path FROM notes")}
    assert rows == {"topic": "research/notes/renamed.md", "other": "research/notes/other.md"}
    assert [r["note_id"] for r in tmp_vault.db.execute("SELECT note_id FROM claims")] == ["topic"]
    link = tmp_vault.db.execute("SELECT target_id FROM links WHERE source_id = 'other'").fetchone()
    assert link["target_id"] == "topic"


@pytest.mark.parametrize("id_line", ["id: topic\n", ""], ids=["declared", "from-the-file-name"])
def test_sync_id_rewrite_leaves_the_claimants_url_and_asset_rows_under_the_old_id(tmp_vault, id_line):
    """While `topic-2.md` held the id `topic`, the fetch that wrote the new
    `topic.md` recorded that file's URL under `topic`, the file's stem, and
    saved its assets in research/assets/topic/ under it too; sync refused
    `topic.md` as a collision. Those rows stay with the id and its new
    owner, whether `topic.md` declares the id or takes it from its file
    name; the renamed note's own URL and asset rows, which point into its
    own directory, move with it. No file moves."""
    notes = tmp_vault.notes_dir
    assets = tmp_vault.root / "research" / "assets"
    _note_with_id(notes / "topic-2.md", "topic", "Topic dup", "Second.", SOURCE_B)
    assert execute_sync(tmp_vault, compute_sync_plan(tmp_vault)).errors == []
    own = assets / "topic-2" / "figure.png"
    theirs = assets / "topic" / "screenshot.png"
    for path in (own, theirs):
        path.parent.mkdir(parents=True)
        path.write_bytes(path.name.encode())
        tmp_vault.db.execute(
            "INSERT INTO assets (note_id, type, filename, created_at) VALUES ('topic', 'image', ?, 't')",
            (str(path),),
        )
    for url in ("https://ex.org/a", "https://ex.org/b"):
        tmp_vault.db.execute("INSERT INTO sources (url, note_id) VALUES (?, 'topic')", (url,))
    tmp_vault.db.commit()
    (notes / "topic.md").write_text(
        f"---\n{id_line}title: Topic\nsource: https://ex.org/a\n---\n\nFirst.\n", encoding="utf-8"
    )
    assert len(execute_sync(tmp_vault, compute_sync_plan(tmp_vault)).errors) == 1

    _note_with_id(notes / "topic-2.md", "topic-2", "Topic dup", "Second.", SOURCE_B)
    result = execute_sync(tmp_vault, compute_sync_plan(tmp_vault))

    assert result.errors == [] and (result.added, result.updated) == (1, 1)
    rows = sorted((r["note_id"], r["filename"]) for r in tmp_vault.db.execute("SELECT note_id, filename FROM assets"))
    assert rows == [("topic", str(theirs)), ("topic-2", str(own))]
    owners = dict(tmp_vault.db.execute("SELECT url, note_id FROM sources").fetchall())
    assert owners == {"https://ex.org/a": "topic", "https://ex.org/b": "topic-2"}
    assert own.read_bytes() == b"figure.png" and theirs.read_bytes() == b"screenshot.png"
    files = sorted(p.relative_to(assets).as_posix() for p in assets.rglob("*") if p.is_file())
    assert files == ["topic-2/figure.png", "topic/screenshot.png"]


def test_sync_id_rewrite_of_the_file_named_after_the_old_id_takes_all_its_rows(tmp_vault):
    """`topic.md` is the file fetch recorded `topic`'s rows for, so when its
    own `id:` changes, every row under `topic` is its own, even while a new
    file elsewhere named `topic.md` claims the id: the URL and the asset row
    in research/assets/topic/ move with the renamed note."""
    notes = tmp_vault.notes_dir
    shot = tmp_vault.root / "research" / "assets" / "topic" / "screenshot.png"
    source_t = "source: https://ex.org/t\n"
    _note_with_id(notes / "topic.md", "topic", "Topic", "Fetched.", source_t)
    assert execute_sync(tmp_vault, compute_sync_plan(tmp_vault)).errors == []
    shot.parent.mkdir(parents=True)
    shot.write_bytes(b"png")
    tmp_vault.db.execute(
        "INSERT INTO assets (note_id, type, filename, created_at) VALUES ('topic', 'screenshot', ?, 't')",
        (str(shot),),
    )
    tmp_vault.db.execute("INSERT INTO sources (url, note_id) VALUES ('https://ex.org/t', 'topic')")
    tmp_vault.db.commit()

    _note_with_id(notes / "topic.md", "topic-x", "Topic", "Fetched.", source_t)
    _note_with_id(tmp_vault.temp_dir / "topic.md", "topic", "Topic stub", "Stub.", source_t)
    result = execute_sync(tmp_vault, compute_sync_plan(tmp_vault))

    assert result.errors == [] and (result.added, result.updated) == (1, 1)
    rows = {r["id"]: r["path"] for r in tmp_vault.db.execute("SELECT id, path FROM notes")}
    assert rows == {"topic-x": "research/notes/topic.md", "topic": "research/temp/topic.md"}
    assert [tuple(r) for r in tmp_vault.db.execute("SELECT note_id FROM sources")] == [("topic-x",)]
    assets = [tuple(r) for r in tmp_vault.db.execute("SELECT note_id, filename FROM assets")]
    assert assets == [("topic-x", str(shot))]


def test_sync_orphans_the_rows_a_failed_claimant_left_under_the_freed_id(tmp_vault):
    """`topic-2.md` renames itself away from `topic` while new `topic.md`
    claims that id, so the rename leaves the claimant's URL and asset rows
    under `topic`. The claimant then fails its own upsert (a duplicate
    alias) and no row holds `topic` when the pass commits. The rows kept
    for it must be orphaned as a delete of `topic` would orphan them, or the
    deferred foreign-key check fails the commit and the whole pass with it."""
    notes = tmp_vault.notes_dir
    assets = tmp_vault.root / "research" / "assets"
    _note_with_id(notes / "topic-2.md", "topic", "Topic dup", "Second.", SOURCE_B)
    assert execute_sync(tmp_vault, compute_sync_plan(tmp_vault)).errors == []
    shot = assets / "topic" / "screenshot.png"
    shot.parent.mkdir(parents=True)
    shot.write_bytes(b"png")
    for url in ("https://ex.org/a", "https://ex.org/b"):
        tmp_vault.db.execute("INSERT INTO sources (url, note_id) VALUES (?, 'topic')", (url,))
    tmp_vault.db.execute(
        "INSERT INTO assets (note_id, type, filename, created_at) VALUES ('topic', 'screenshot', ?, 't')",
        (str(shot),),
    )
    tmp_vault.db.commit()

    _note_with_id(
        notes / "topic.md", "topic", "Topic", "First.",
        "source: https://ex.org/a\naliases: [dup, dup]\n",
    )
    _note_with_id(notes / "topic-2.md", "topic-2", "Topic dup", "Second.", SOURCE_B)
    raised = result = None
    try:
        result = execute_sync(tmp_vault, compute_sync_plan(tmp_vault))
    except sqlite3.IntegrityError as exc:
        raised = exc
    assert raised is None, f"the pass raised instead of orphaning the kept rows: {raised}"

    assert len(result.errors) == 1 and result.errors[0]["path"].endswith("topic.md")
    assert "aliases" in result.errors[0]["error"]
    assert (result.added, result.updated) == (0, 1)
    assert not tmp_vault.db.in_transaction
    rows = {r["id"]: r["path"] for r in tmp_vault.db.execute("SELECT id, path FROM notes")}
    assert rows == {"topic-2": "research/notes/topic-2.md"}
    owners = dict(tmp_vault.db.execute("SELECT url, note_id FROM sources").fetchall())
    assert owners == {"https://ex.org/a": None, "https://ex.org/b": "topic-2"}
    assert tmp_vault.db.execute("SELECT COUNT(*) FROM assets").fetchone()[0] == 0
    assert shot.exists()
    assert tmp_vault.db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_sync_id_edit_does_not_take_the_id_of_a_new_file_named_after_it(tmp_vault):
    """`foo.md` (id `foo`) is new in this pass, and fetch records its URL
    under `foo`. An id edit of `foo-2.md` to `foo` in the same pass must not
    win the id just because updates run before adds."""
    notes = tmp_vault.notes_dir
    _note_with_id(notes / "foo-2.md", "foo-2", "Foo dup", "Second.")
    assert execute_sync(tmp_vault, compute_sync_plan(tmp_vault)).errors == []

    _note_with_id(notes / "foo-2.md", "foo", "Foo dup", "Second.")
    _note_with_id(notes / "foo.md", "foo", "Foo", "Fetched.")
    result = execute_sync(tmp_vault, compute_sync_plan(tmp_vault))

    assert len(result.errors) == 1
    assert result.errors[0]["path"] == "research/notes/foo-2.md"
    assert "claimed by new file 'research/notes/foo.md'" in result.errors[0]["error"]
    rows = {r["id"]: r["path"] for r in tmp_vault.db.execute("SELECT id, path FROM notes")}
    assert rows == {"foo": "research/notes/foo.md", "foo-2": "research/notes/foo-2.md"}


def test_sync_reports_a_tag_aliases_read_error(tmp_vault):
    """The upsert's tag_aliases read used to ignore every error, so a failure
    there was invisible, or surfaced later as a lost savepoint without its
    cause."""
    _note_with_id(tmp_vault.notes_dir / "a.md", "a", "A", "A body.")
    tmp_vault.db.execute("DROP TABLE tag_aliases")
    tmp_vault.db.commit()
    result = execute_sync(tmp_vault, compute_sync_plan(tmp_vault))
    assert len(result.errors) == 1 and "tag_aliases" in result.errors[0]["error"]


def test_sync_id_edit_proceeds_when_the_file_named_after_the_id_declares_another(tmp_vault):
    """A new `foo.md` whose frontmatter says `id: bar` is the note `bar`,
    not a claim on `foo`: the rename of `foo-2.md` to `foo` goes through in
    the same pass, and `foo.md` indexes as `bar`."""
    notes = tmp_vault.notes_dir
    _note_with_id(notes / "foo-2.md", "foo-2", "Foo dup", "Second.")
    assert execute_sync(tmp_vault, compute_sync_plan(tmp_vault)).errors == []

    _note_with_id(notes / "foo-2.md", "foo", "Foo dup", "Second.")
    _note_with_id(notes / "foo.md", "bar", "Bar", "Not foo.")
    result = execute_sync(tmp_vault, compute_sync_plan(tmp_vault))

    assert result.errors == []
    assert (result.added, result.updated) == (1, 1)
    rows = {r["id"]: r["path"] for r in tmp_vault.db.execute("SELECT id, path FROM notes")}
    assert rows == {"foo": "research/notes/foo-2.md", "bar": "research/notes/foo.md"}


@pytest.mark.parametrize("temp_first", [False, True])
def test_sync_id_rewrite_keeps_the_urls_of_every_new_file_named_after_the_old_id(tmp_vault, temp_first):
    """Two new files named `topic.md`, one in research/notes/ and one in
    research/temp/, both claim `topic` while `topic-2.md` renames away from
    it. Whichever is listed first gets the id and the other collides, but
    the URL rows fetch recorded for both stay under `topic` either way."""
    notes = tmp_vault.notes_dir
    _note_with_id(notes / "topic-2.md", "topic", "Topic dup", "Second.", SOURCE_B)
    assert execute_sync(tmp_vault, compute_sync_plan(tmp_vault)).errors == []
    _note_with_id(notes / "topic.md", "topic", "Topic", "First.", "source: https://ex.org/a\n")
    _note_with_id(tmp_vault.temp_dir / "topic.md", "topic", "Topic stub", "Stub.", "source: https://ex.org/c\n")
    for url in ("https://ex.org/a", "https://ex.org/b", "https://ex.org/c"):
        tmp_vault.db.execute("INSERT INTO sources (url, note_id) VALUES (?, 'topic')", (url,))
    tmp_vault.db.commit()

    _note_with_id(notes / "topic-2.md", "topic-2", "Topic dup", "Second.", SOURCE_B)
    plan = compute_sync_plan(tmp_vault)
    # The scan order is the filesystem's. Fix it, both ways round.
    plan.to_add.sort(key=lambda p: (p.parent.name == "temp") != temp_first)
    assert [p.name for p in plan.to_add] == ["topic.md", "topic.md"]
    first, second = (p.relative_to(tmp_vault.root).as_posix() for p in plan.to_add)
    result = execute_sync(tmp_vault, plan)

    assert [e["path"] for e in result.errors] == [second]
    assert "id collision" in result.errors[0]["error"]
    rows = {r["id"]: r["path"] for r in tmp_vault.db.execute("SELECT id, path FROM notes")}
    assert rows == {"topic": first, "topic-2": "research/notes/topic-2.md"}
    owners = dict(tmp_vault.db.execute("SELECT url, note_id FROM sources").fetchall())
    assert owners == {"https://ex.org/a": "topic", "https://ex.org/b": "topic-2", "https://ex.org/c": "topic"}


@pytest.mark.parametrize(
    ("rel", "text"),
    [
        (
            "notes/topic.md",
            "---\nid: topic\ntitle: Topic\nsource: https://ex.org/a\nstatus: [bad\n---\n\nFirst.\n",
        ),
        ("notes/topic.md", "---\nid: topic\ntitle: Topic\nsource: https://ex.org/a\n\nFirst.\n"),
        ("temp/topic-2.md", "---\nid: topic-2\ntitle: Stub\nstatus: [bad\n---\n\nStub.\n"),
    ],
    ids=["old-id-does-not-parse", "old-id-caught-mid-write", "new-id-does-not-parse"],
)
def test_sync_id_rewrite_waits_while_a_new_file_named_after_either_id_does_not_parse(
    tmp_vault, rel, text
):
    """`topic-2.md` rewrites its id from `topic` to `topic-2` while a new
    file named after one of the two ids has frontmatter that does not parse,
    or no closing `---` yet (a file caught mid-write). Whether it claims
    that id is unknown, so the rename waits: the
    row and the URL rows under `topic` stay as they are, and the error
    names the file. A wrong guess would move the new file's URL to the
    renamed note for good, or take an id that is that file's."""
    notes = tmp_vault.notes_dir
    _note_with_id(notes / "topic-2.md", "topic", "Topic dup", "Second.", SOURCE_B)
    assert execute_sync(tmp_vault, compute_sync_plan(tmp_vault)).errors == []
    for url in ("https://ex.org/a", "https://ex.org/b"):
        tmp_vault.db.execute("INSERT INTO sources (url, note_id) VALUES (?, 'topic')", (url,))
    tmp_vault.db.commit()

    (tmp_vault.root / "research" / rel).write_text(text, encoding="utf-8")
    _note_with_id(notes / "topic-2.md", "topic-2", "Topic dup", "Second.", SOURCE_B)
    result = execute_sync(tmp_vault, compute_sync_plan(tmp_vault))

    errors = [e["error"] for e in result.errors if e["path"] == "research/notes/topic-2.md"]
    assert len(errors) == 1
    assert f"new file 'research/{rel}'" in errors[0] and "run sync again" in errors[0]
    assert (result.added, result.updated) == (0, 0)
    rows = {r["id"]: r["path"] for r in tmp_vault.db.execute("SELECT id, path FROM notes")}
    assert rows == {"topic": "research/notes/topic-2.md"}
    owners = dict(tmp_vault.db.execute("SELECT url, note_id FROM sources").fetchall())
    assert owners == {"https://ex.org/a": "topic", "https://ex.org/b": "topic"}


def test_sync_id_rewrite_takes_a_new_file_without_frontmatter_as_a_claimant(tmp_vault):
    """A new `topic.md` with no frontmatter at all has the id of its file
    name, like any note without an `id:` line, and is not a broken one: the
    rename of `topic-2.md` away from `topic` goes through in the same pass.
    Sync's own plan skips such a file, so the test admits it by hand, as a
    plan that indexes header-less files would."""
    notes = tmp_vault.notes_dir
    _note_with_id(notes / "topic-2.md", "topic", "Topic dup", "Second.", SOURCE_B)
    assert execute_sync(tmp_vault, compute_sync_plan(tmp_vault)).errors == []

    (notes / "topic.md").write_text("# Topic\n\nNo header.\n", encoding="utf-8")
    _note_with_id(notes / "topic-2.md", "topic-2", "Topic dup", "Second.", SOURCE_B)
    plan = compute_sync_plan(tmp_vault)
    assert plan.to_add == []
    plan.to_add.append(notes / "topic.md")
    result = execute_sync(tmp_vault, plan)

    assert result.errors == [] and (result.added, result.updated) == (1, 1)
    rows = {r["id"]: r["path"] for r in tmp_vault.db.execute("SELECT id, path FROM notes")}
    assert rows == {"topic": "research/notes/topic.md", "topic-2": "research/notes/topic-2.md"}
