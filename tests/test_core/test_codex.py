"""Tests for the additive Codex integration."""

from __future__ import annotations

from pathlib import Path

from hyperresearch.core.agent_docs import (
    HYPERRESEARCH_SECTION_MARKER,
    inject_agent_docs,
)
from hyperresearch.core.codex import install_codex
from hyperresearch.core.hooks import _HYPERRESEARCH_STEP_SKILLS
from hyperresearch.core.vault import Vault


def test_codex_vault_init_creates_only_agents_md(tmp_path: Path):
    vault = Vault.init(tmp_path / "codex-vault", agent_platform="codex")
    assert (vault.root / "AGENTS.md").exists()
    assert not (vault.root / "CLAUDE.md").exists()


def test_both_vault_init_creates_both_instruction_files(tmp_path: Path):
    vault = Vault.init(tmp_path / "both-vault", agent_platform="both")
    assert (vault.root / "AGENTS.md").exists()
    assert (vault.root / "CLAUDE.md").exists()


def test_codex_agent_docs_preserve_user_content_and_are_idempotent(tmp_path: Path):
    agents_md = tmp_path / "AGENTS.md"
    agents_md.write_text("# User rules\n\nKeep this.\n", encoding="utf-8")

    first = inject_agent_docs(tmp_path, platform="codex")
    second = inject_agent_docs(tmp_path, platform="codex")

    content = agents_md.read_text(encoding="utf-8")
    assert first == ["AGENTS.md (appended)"]
    assert second == []
    assert content.startswith("# User rules\n\nKeep this.")
    assert content.count(HYPERRESEARCH_SECTION_MARKER) == 1


def test_install_codex_writes_native_skill_layout(tmp_vault):
    actions = install_codex(tmp_vault.root, hpr_path="/opt/bin/hyperresearch")
    skills_root = tmp_vault.root / ".agents" / "skills"

    assert actions
    assert (skills_root / "hyperresearch" / "SKILL.md").exists()
    for name in _HYPERRESEARCH_STEP_SKILLS:
        assert (skills_root / name / "SKILL.md").exists()

    entry = (skills_root / "hyperresearch" / "SKILL.md").read_text(encoding="utf-8")
    assert ".agents/skills/hyperresearch-1-decompose/SKILL.md" in entry
    assert "Skill(skill:" not in entry
    assert "TodoWrite" not in entry
    assert "--platform codex" in entry
    for skill_file in skills_root.glob("hyperresearch-*/SKILL.md"):
        assert "subagent_type:" not in skill_file.read_text(encoding="utf-8")


def test_install_codex_writes_reusable_role_prompts(tmp_vault):
    install_codex(tmp_vault.root, hpr_path="/opt/bin/hyperresearch")
    roles = (
        tmp_vault.root
        / ".agents"
        / "skills"
        / "hyperresearch"
        / "references"
        / "agents"
    )

    files = sorted(roles.glob("hyperresearch-*.md"))
    assert len(files) == 16
    fetcher = (roles / "hyperresearch-fetcher.md").read_text(encoding="utf-8")
    assert "/opt/bin/hyperresearch" in fetcher
    assert "Use this as the complete role prompt for a Codex subagent" in fetcher


def test_install_codex_is_idempotent(tmp_vault):
    first = install_codex(tmp_vault.root)
    second = install_codex(tmp_vault.root)
    assert first
    assert second == []
