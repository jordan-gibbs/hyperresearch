"""Tests for the sync engine."""

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
