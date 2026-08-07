"""Tests for the additive Codex integration."""

from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path

from hyperresearch.core.agent_docs import (
    HYPERRESEARCH_SECTION_MARKER,
    detect_agent_platform,
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


def test_unrelated_agents_md_does_not_enable_codex(tmp_vault):
    (tmp_vault.root / "AGENTS.md").write_text(
        "# User-authored Codex instructions\n",
        encoding="utf-8",
    )
    assert detect_agent_platform(tmp_vault.root) == "claude"


def test_install_codex_writes_native_skill_layout(tmp_vault):
    actions = install_codex(tmp_vault.root, hpr_path="/opt/bin/hyperresearch")
    skills_root = tmp_vault.root / ".agents" / "skills"

    assert actions
    assert (skills_root / "hyperresearch" / "SKILL.md").exists()
    for name in _HYPERRESEARCH_STEP_SKILLS:
        assert (skills_root / name / "SKILL.md").exists()

    entry_path = skills_root / "hyperresearch" / "SKILL.md"
    entry = entry_path.read_text(encoding="utf-8")
    assert ".agents/skills/hyperresearch-1-decompose/SKILL.md" in entry
    assert "--platform codex" in entry
    width = (skills_root / "hyperresearch-2-width-sweep" / "SKILL.md").read_text(encoding="utf-8")
    assert "custom_agent: hyperresearch_fetcher" in width
    forbidden = (
        "Skill(skill:",
        "Skill tool",
        "Skill invocation",
        "TodoWrite",
        "Task call",
        "Task result",
        "Task tool",
        "`Skill` tool",
        "via Skill",
        "invoke a Skill",
        "which Skill to invoke",
        "skill file tool",
        "tool-locked",
        "tool-lock",
        "tool lock",
        "Write tool",
        "Edit tool",
        "Read tool",
        "cannot Write",
        "subagent_type:",
        ".claude/skills",
        "Claude-in-Chrome",
        "mcp__claude-in-chrome",
        "tabs_context_mcp",
    )
    generated_files = list(skills_root.rglob("*.md"))
    generated_files.append(entry_path)
    for skill_file in generated_files:
        text = skill_file.read_text(encoding="utf-8")
        for phrase in forbidden:
            assert phrase not in text, f"{phrase!r} remains in {skill_file}"


def test_install_codex_writes_reusable_role_prompts(tmp_vault):
    install_codex(tmp_vault.root, hpr_path="/opt/bin/hyperresearch")
    roles = tmp_vault.root / ".agents" / "skills" / "hyperresearch" / "references" / "agents"

    files = sorted(roles.glob("hyperresearch-*.md"))
    assert len(files) == 16
    fetcher = (roles / "hyperresearch-fetcher.md").read_text(encoding="utf-8")
    assert "/opt/bin/hyperresearch" in fetcher
    assert "Use this as the complete role prompt for a Codex subagent" in fetcher

    browser = (roles / "hyperresearch-browser-fetcher.md").read_text(encoding="utf-8")
    assert "Browser Use" in browser
    assert "mcp__claude-in-chrome" not in browser
    assert "tabs_context_mcp" not in browser


def test_install_codex_writes_native_custom_agents(tmp_vault):
    install_codex(tmp_vault.root, hpr_path="/opt/bin/hyperresearch")
    agents_root = tmp_vault.root / ".codex" / "agents"
    files = sorted(agents_root.glob("hyperresearch_*.toml"))

    assert len(files) == 16
    parsed = {path.stem: tomllib.loads(path.read_text(encoding="utf-8")) for path in files}
    fetcher = parsed["hyperresearch_fetcher"]
    synthesizer = parsed["hyperresearch_synthesizer"]
    assert fetcher["model"] == "gpt-5.6-terra"
    assert fetcher["model_reasoning_effort"] == "medium"
    assert synthesizer["model"] == "gpt-5.6-sol"
    assert synthesizer["model_reasoning_effort"] == "high"
    for config in parsed.values():
        assert set(("name", "description", "developer_instructions")) <= config.keys()
        assert "sonnet" not in config["developer_instructions"].lower()
        assert "opus" not in config["developer_instructions"].lower()


def test_install_codex_merges_and_executes_session_start_hook(tmp_vault):
    hooks_path = tmp_vault.root / ".codex" / "hooks.json"
    hooks_path.parent.mkdir(parents=True)
    hooks_path.write_text(
        json.dumps(
            {
                "description": "User hooks",
                "hooks": {
                    "Stop": [{"hooks": [{"type": "command", "command": "python user-stop.py"}]}]
                },
            }
        ),
        encoding="utf-8",
    )

    install_codex(tmp_vault.root, hpr_path="/opt/bin/hyperresearch")
    install_codex(tmp_vault.root, hpr_path="/opt/bin/hyperresearch")

    config = json.loads(hooks_path.read_text(encoding="utf-8"))
    assert config["description"] == "User hooks"
    assert len(config["hooks"]["Stop"]) == 1
    assert len(config["hooks"]["SessionStart"]) == 1

    script = tmp_vault.root / ".hyperresearch" / "codex-hook.py"
    result = subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps({"cwd": str(tmp_vault.root)}),
        text=True,
        capture_output=True,
        check=True,
    )
    output = json.loads(result.stdout)
    context = output["hookSpecificOutput"]["additionalContext"]
    assert output["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "/opt/bin/hyperresearch search" in context


def test_install_codex_preserves_invalid_user_hook_config(tmp_vault):
    hooks_path = tmp_vault.root / ".codex" / "hooks.json"
    hooks_path.parent.mkdir(parents=True)
    hooks_path.write_text("{ user-owned invalid json", encoding="utf-8")

    actions = install_codex(tmp_vault.root)

    assert hooks_path.read_text(encoding="utf-8") == "{ user-owned invalid json"
    assert not (tmp_vault.root / ".hyperresearch" / "codex-hook.py").exists()
    assert any("invalid JSON; left unchanged" in action for action in actions)


def test_install_codex_is_idempotent(tmp_vault):
    first = install_codex(tmp_vault.root)
    second = install_codex(tmp_vault.root)
    assert first
    assert second == []
