"""Tests for hook installer and skill file provisioning."""

from __future__ import annotations

from pathlib import Path

from hyperresearch.core.hooks import _SKILL_FILES, _install_research_skill


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
