"""Tests for the sync engine."""

from importlib import resources

import pytest

from hyperresearch.core.sync import (
    _TEMP_WORKFLOW_ARTIFACT_NAMES,
    _TEMP_WORKFLOW_ARTIFACT_PREFIXES,
    compute_sync_plan,
    execute_sync,
)


def _workflow_contract_text() -> str:
    skills_dir = resources.files("hyperresearch").joinpath("skills")
    skill_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(skills_dir.iterdir(), key=lambda item: item.name)
        if path.name.endswith(".md")
    )
    core_dir = resources.files("hyperresearch").joinpath("core")
    return "\n".join(
        [
            skill_text,
            core_dir.joinpath("hooks.py").read_text(encoding="utf-8"),
            core_dir.joinpath("codex.py").read_text(encoding="utf-8"),
        ]
    )


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


def test_sync_excludes_temp_workflow_staging_files(tmp_vault):
    """Workflow markdown under research/temp/ is addressed directly by path.

    It should not become a note just because repair/sync ran. This preserves
    durable progress files without polluting them with auto-generated
    frontmatter, tags, summaries, or promotion status.
    """
    from hyperresearch.core.note import write_note

    write_note(tmp_vault.notes_dir, "Real Note", body="# Real\n")

    temp = tmp_vault.temp_dir
    (temp / "orchestrator-progress.md").write_text(
        "# Orchestrator Progress\n\n- [x] Step 1\n",
        encoding="utf-8",
    )
    (temp / "evidence-digest.md").write_text("# Evidence Digest\n", encoding="utf-8")
    (temp / "source-analysis-example.md").write_text("# Source Analysis\n", encoding="utf-8")
    (temp / "scratch.md").write_text("# Plain temp scratch\n", encoding="utf-8")

    plan = compute_sync_plan(tmp_vault)
    added_names = [p.name for p in plan.to_add]

    assert "real-note.md" in added_names
    assert "orchestrator-progress.md" not in added_names
    assert "evidence-digest.md" not in added_names
    assert "source-analysis-example.md" not in added_names
    assert "scratch.md" not in added_names


@pytest.mark.parametrize("artifact_name", sorted(_TEMP_WORKFLOW_ARTIFACT_NAMES))
def test_sync_excludes_all_known_temp_workflow_artifact_names(tmp_vault, artifact_name):
    """Every fixed workflow markdown name stays out of the note DB.

    The frontmatter forces this test to exercise the explicit name denylist,
    not the broader "frontmatter-less temp scratch" fallback.
    """
    artifact = tmp_vault.temp_dir / artifact_name
    artifact_id = artifact_name.removesuffix(".md")
    artifact.write_text(
        "---\n"
        f"title: {artifact_id}\n"
        f"id: {artifact_id}\n"
        "status: evergreen\n"
        "type: note\n"
        "---\n\n"
        f"# {artifact_id}\n",
        encoding="utf-8",
    )

    plan = compute_sync_plan(tmp_vault)
    added_names = [p.name for p in plan.to_add]

    assert artifact_name not in added_names


@pytest.mark.parametrize("artifact_prefix", _TEMP_WORKFLOW_ARTIFACT_PREFIXES)
def test_sync_excludes_all_known_temp_workflow_artifact_prefixes(tmp_vault, artifact_prefix):
    """Every fixed workflow markdown prefix stays out of the note DB."""
    artifact_name = f"{artifact_prefix}example.md"
    artifact = tmp_vault.temp_dir / artifact_name
    artifact_id = artifact_name.removesuffix(".md")
    artifact.write_text(
        "---\n"
        f"title: {artifact_id}\n"
        f"id: {artifact_id}\n"
        "status: evergreen\n"
        "type: note\n"
        "---\n\n"
        f"# {artifact_id}\n",
        encoding="utf-8",
    )

    plan = compute_sync_plan(tmp_vault)
    added_names = [p.name for p in plan.to_add]

    assert artifact_name not in added_names


def test_temp_workflow_artifact_denylist_matches_workflow_contracts():
    """Hardcoded sync exclusions must correspond to workflow-authored paths."""
    contract_text = _workflow_contract_text()
    expected_refs = sorted(_TEMP_WORKFLOW_ARTIFACT_NAMES) + list(_TEMP_WORKFLOW_ARTIFACT_PREFIXES)

    missing = [artifact for artifact in expected_refs if artifact not in contract_text]

    assert missing == []


def test_sync_keeps_frontmatter_temp_notes(tmp_vault):
    """Temp stubs are real notes and must still sync for link resolution."""
    from hyperresearch.core.note import write_note

    write_note(
        tmp_vault.temp_dir,
        "Stub Topic",
        body="# Stub Topic\n\nTemporary note.",
        note_id="stub-topic",
        status="draft",
        summary="Stub note.",
    )

    plan = compute_sync_plan(tmp_vault)
    added_names = [p.name for p in plan.to_add]

    assert "stub-topic.md" in added_names


def test_sync_excludes_known_temp_workflow_artifacts_even_with_frontmatter(tmp_vault):
    """Existing polluted workflow artifacts should age out of the DB."""
    progress = tmp_vault.temp_dir / "orchestrator-progress.md"
    progress.write_text(
        "---\n"
        "title: Untitled\n"
        "id: orchestrator-progress\n"
        "status: evergreen\n"
        "type: note\n"
        "---\n\n"
        "# Orchestrator Progress\n\n- [x] Step 1\n",
        encoding="utf-8",
    )

    plan = compute_sync_plan(tmp_vault)
    added_names = [p.name for p in plan.to_add]

    assert "orchestrator-progress.md" not in added_names
