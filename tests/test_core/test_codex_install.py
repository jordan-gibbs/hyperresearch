"""Regression coverage for the Codex installation adapter."""

from __future__ import annotations

import json
import shutil
import subprocess
import tomllib

import pytest

from hyperresearch.core.hooks import _install_codex_hook, install_hooks


def test_install_hooks_provisions_codex_alongside_claude(tmp_vault):
    install_hooks(tmp_vault.root, "hyperresearch")

    skill = tmp_vault.root / ".agents" / "skills" / "hyperresearch" / "SKILL.md"
    step = tmp_vault.root / ".agents" / "skills" / "hyperresearch-1-decompose" / "SKILL.md"
    agent = tmp_vault.root / ".codex" / "agents" / "hyperresearch-fetcher.toml"
    hooks = tmp_vault.root / ".codex" / "hooks.json"

    assert skill.exists()
    assert step.exists()
    assert "$hyperresearch-1-decompose" in skill.read_text(encoding="utf-8")

    agent_config = tomllib.loads(agent.read_text(encoding="utf-8"))
    assert agent_config["name"] == "hyperresearch-fetcher"
    assert agent_config["description"]
    assert "proportional" in agent_config["developer_instructions"].lower()

    hook_config = json.loads(hooks.read_text(encoding="utf-8"))
    command = hook_config["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert "hyperresearch" in command
    assert "--codex" in command

    node = shutil.which("node")
    if node:
        hook_script = tmp_vault.root / ".hyperresearch" / "hook.js"
        completed = subprocess.run(
            [node, str(hook_script), "--codex"],
            cwd=tmp_vault.root,
            capture_output=True,
            check=True,
            text=True,
        )
        payload = json.loads(completed.stdout)
        output = payload["hookSpecificOutput"]
        assert output["hookEventName"] == "PreToolUse"
        assert "check existing research" in output["additionalContext"]

    assert install_hooks(tmp_vault.root, "hyperresearch") == []


def test_codex_hook_refuses_to_overwrite_invalid_user_config(tmp_vault):
    hooks = tmp_vault.root / ".codex" / "hooks.json"
    hooks.parent.mkdir(parents=True)
    hooks.write_text("{ user-owned but invalid", encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid Codex hooks file"):
        _install_codex_hook(tmp_vault.root, "hyperresearch")

    assert hooks.read_text(encoding="utf-8") == "{ user-owned but invalid"
