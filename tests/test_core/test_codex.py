from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from hyperresearch.core.agent_platforms import detect_installed_agents, selected_agents
from hyperresearch.core.codex import (
    _install_from_staging,
    adapt_for_codex,
    claude_agent_to_toml,
    inject_codex_docs,
)


def test_selected_agents_supports_claude_codex_and_both() -> None:
    assert selected_agents("claude") == ("claude",)
    assert selected_agents(" CODEX ") == ("codex",)
    assert selected_agents("both") == ("claude", "codex")


def test_selected_agents_rejects_unknown_platform() -> None:
    with pytest.raises(ValueError, match="claude, codex, or both"):
        selected_agents("gemini")


def test_adapt_for_codex_rewrites_commands_without_corrupting_paths() -> None:
    source = (
        "Use Claude Code's Skill tool and Task tool.\n"
        'Invoke Skill(skill: "hyperresearch-1-decompose").\n'
        "Run /hyperresearch from .claude/skills/hyperresearch/SKILL.md.\n"
    )

    adapted = adapt_for_codex(source)

    assert "$hyperresearch-1-decompose" in adapted
    assert "$hyperresearch" in adapted
    assert "spawn_agent" in adapted
    assert ".agents/skills/hyperresearch/SKILL.md" in adapted
    assert ".agents/skills$hyperresearch" not in adapted


def test_claude_agent_to_toml_inherits_codex_model() -> None:
    markdown = """---
name: hyperresearch-example
description: >
  Reads evidence and returns a result.
model: sonnet
tools: Bash, Read, Write, Task
---
Use the Task tool, then run /hyperresearch.
"""

    parsed = tomllib.loads(claude_agent_to_toml(markdown))

    assert parsed["name"] == "hyperresearch-example"
    assert "spawn_agent" in parsed["developer_instructions"]
    assert "$hyperresearch" in parsed["developer_instructions"]
    assert "model" not in parsed
    assert "tools" not in parsed


def test_install_from_staging_writes_codex_layout_and_is_idempotent(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    target = tmp_path / "project"

    entry = staging / ".claude" / "skills" / "hyperresearch" / "SKILL.md"
    step = staging / ".claude" / "skills" / "hyperresearch-1-decompose" / "SKILL.md"
    agent = staging / ".claude" / "agents" / "hyperresearch-example.md"
    entry.parent.mkdir(parents=True)
    step.parent.mkdir(parents=True)
    agent.parent.mkdir(parents=True)

    entry.write_text("Run /hyperresearch with Claude Code.\n", encoding="utf-8")
    step.write_text('Invoke Skill(skill: "hyperresearch-1-decompose").\n', encoding="utf-8")
    agent.write_text(
        """---
name: hyperresearch-example
description: Example worker.
model: opus
tools: Read, Edit
---
Do not regenerate the report.
""",
        encoding="utf-8",
    )

    actions = _install_from_staging(
        staging,
        target,
        include_entry=True,
        include_steps=True,
        include_agents=True,
    )

    assert (target / ".agents" / "skills" / "hyperresearch" / "SKILL.md").exists()
    assert (
        target / ".agents" / "skills" / "hyperresearch-1-decompose" / "SKILL.md"
    ).exists()
    assert (target / ".codex" / "agents" / "hyperresearch-example.toml").exists()
    assert len(actions) == 3
    assert _install_from_staging(
        staging,
        target,
        include_entry=True,
        include_steps=True,
        include_agents=True,
    ) == []


def test_inject_codex_docs_preserves_user_content(tmp_path: Path) -> None:
    agents_md = tmp_path / "AGENTS.md"
    agents_md.write_text("# Project rules\n\nKeep this.\n", encoding="utf-8")

    first = inject_codex_docs(tmp_path, hpr_path="/tools/hyperresearch")
    second = inject_codex_docs(tmp_path, hpr_path="/tools/hyperresearch")
    content = agents_md.read_text(encoding="utf-8")

    assert first == ["AGENTS.md (appended)"]
    assert second == []
    assert content.startswith("# Project rules\n\nKeep this.")
    assert content.count("<!-- hyperresearch:start -->") == 1


def test_detect_installed_agents_finds_codex_layout(tmp_path: Path) -> None:
    (tmp_path / ".agents" / "skills" / "hyperresearch").mkdir(parents=True)
    assert detect_installed_agents(tmp_path) == ("codex",)
