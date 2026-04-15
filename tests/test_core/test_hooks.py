"""Tests for hook installer and skill file provisioning."""

from __future__ import annotations

from hyperresearch.core.hooks import (
    _SKILL_FILES,
    _install_ensemble_skill,
    _install_merger_agent,
    _install_research_skill,
    _install_subrun_agent,
)


def test_install_skill_writes_expected_files(tmp_vault):
    result = _install_research_skill(tmp_vault.root)
    skill_dir = tmp_vault.root / ".claude" / "skills" / "hyperresearch"
    assert skill_dir.is_dir()

    expected = {dest_name for _, dest_name in _SKILL_FILES}
    present = {p.name for p in skill_dir.glob("SKILL*.md")}
    assert expected.issubset(present)
    assert result is not None


def test_install_skill_prunes_stale_files(tmp_vault):
    skill_dir = tmp_vault.root / ".claude" / "skills" / "hyperresearch"
    skill_dir.mkdir(parents=True, exist_ok=True)

    # Simulate a pre-refactor vault with the old modality files present.
    stale_names = [
        "SKILL-humanities.md",
        "SKILL-academic.md",
        "SKILL-landscape.md",
        "SKILL-technical.md",
    ]
    for name in stale_names:
        (skill_dir / name).write_text("stale content\n", encoding="utf-8")

    result = _install_research_skill(tmp_vault.root)

    remaining = {p.name for p in skill_dir.glob("SKILL*.md")}
    expected = {dest_name for _, dest_name in _SKILL_FILES}
    assert remaining == expected
    for name in stale_names:
        assert not (skill_dir / name).exists(), f"stale file {name} still present"
    assert result is not None
    assert "pruned" in result


def test_install_skill_idempotent_second_run(tmp_vault):
    first = _install_research_skill(tmp_vault.root)
    assert first is not None
    second = _install_research_skill(tmp_vault.root)
    assert second is None, "second run should report no changes"


def test_install_ensemble_skill_creates_separate_skill_dir(tmp_vault):
    """The ensemble skill MUST install as its own .claude/skills/<name>/SKILL.md
    directory so Claude Code registers `/research-ensemble` as a slash-command
    trigger. A sibling file inside .claude/skills/hyperresearch/ does NOT get
    registered as a separate trigger — the harness discovers skills by
    directory, not by SKILL-*.md filename variation."""
    result = _install_ensemble_skill(tmp_vault.root)
    # Must live at its own dir, NOT alongside hyperresearch/SKILL.md
    own_dir_path = tmp_vault.root / ".claude" / "skills" / "research-ensemble" / "SKILL.md"
    assert own_dir_path.exists()
    sibling_path = tmp_vault.root / ".claude" / "skills" / "hyperresearch" / "SKILL-ensemble.md"
    assert not sibling_path.exists(), "ensemble must NOT install as a sibling of SKILL.md"

    body = own_dir_path.read_text(encoding="utf-8")
    assert "name: research-ensemble" in body
    assert "hyperresearch-subrun" in body
    assert "hyperresearch-merger" in body
    assert result is not None


def test_install_ensemble_skill_idempotent(tmp_vault):
    first = _install_ensemble_skill(tmp_vault.root)
    assert first is not None
    second = _install_ensemble_skill(tmp_vault.root)
    assert second is None


def test_install_research_skill_prunes_stale_ensemble_sibling(tmp_vault):
    """Pre-refactor vaults had SKILL-ensemble.md inside the hyperresearch dir.
    After the fix, that path must be pruned on reinstall so users don't end
    up with both old and new files (confusing — two sources of truth)."""
    hyperresearch_skill_dir = tmp_vault.root / ".claude" / "skills" / "hyperresearch"
    hyperresearch_skill_dir.mkdir(parents=True, exist_ok=True)
    stale_ensemble = hyperresearch_skill_dir / "SKILL-ensemble.md"
    stale_ensemble.write_text("pre-refactor ensemble content\n", encoding="utf-8")

    _install_research_skill(tmp_vault.root)

    assert not stale_ensemble.exists(), "stale SKILL-ensemble.md in hyperresearch dir was not pruned"


def test_install_subrun_agent_writes_file(tmp_vault):
    result = _install_subrun_agent(tmp_vault.root, "hyperresearch")
    agent_path = tmp_vault.root / ".claude" / "agents" / "hyperresearch-subrun.md"
    assert agent_path.exists()
    body = agent_path.read_text(encoding="utf-8")
    assert "model: sonnet" in body
    assert "Task" in body  # tools list must include Task for nested spawning
    assert "framing_nudge" in body
    assert "minimum_fetch_target" in body
    assert "run_id" in body
    assert result is not None


def test_install_subrun_agent_idempotent(tmp_vault):
    first = _install_subrun_agent(tmp_vault.root, "hyperresearch")
    assert first is not None
    second = _install_subrun_agent(tmp_vault.root, "hyperresearch")
    assert second is None


def test_install_merger_agent_writes_file(tmp_vault):
    result = _install_merger_agent(tmp_vault.root, "hyperresearch")
    agent_path = tmp_vault.root / ".claude" / "agents" / "hyperresearch-merger.md"
    assert agent_path.exists()
    body = agent_path.read_text(encoding="utf-8")
    assert "model: opus" in body
    assert "scores" in body
    assert "splice" in body.lower()
    assert "merger-failed" in body
    assert "parent_final_report_path" in body
    assert result is not None


def test_install_merger_agent_idempotent(tmp_vault):
    first = _install_merger_agent(tmp_vault.root, "hyperresearch")
    assert first is not None
    second = _install_merger_agent(tmp_vault.root, "hyperresearch")
    assert second is None
