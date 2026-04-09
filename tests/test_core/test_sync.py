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
