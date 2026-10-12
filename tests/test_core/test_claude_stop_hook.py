"""The stop-gate Stop hook in the Claude Code install.

`hyperresearch install` merges the same `run stop-gate` command a Codex
vault gets into `.claude/settings.json`; the gate tells the two runtimes
apart by the hook input, and under Claude Code the block reason names the
next step's skill rather than a Codex step file.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.core import codex
from hyperresearch.core.hooks import install_hooks

runner = CliRunner()

CLAUDE_TRANSCRIPT = "/home/u/.claude/projects/-home-u-vault/0b1c.jsonl"


def _settings(root):
    return json.loads((root / ".claude" / "settings.json").read_text(encoding="utf-8"))


def test_claude_install_adds_the_stop_hook_beside_pretooluse(tmp_vault):
    actions = install_hooks(tmp_vault.root, "hyperresearch")
    assert "Claude Code: .claude/settings.json (Stop hook: run stop-gate)" in actions
    hooks = _settings(tmp_vault.root)["hooks"]
    assert set(hooks) == {"PreToolUse", "Stop"}
    (entry,) = hooks["Stop"]
    assert entry["hooks"] == [{"type": "command", "command": "hyperresearch run stop-gate"}]
    # A second install changes nothing in settings.json.
    assert not [a for a in install_hooks(tmp_vault.root, "hyperresearch") if "settings.json" in a]


def test_claude_stop_hook_keeps_foreign_hooks_and_replaces_only_ours(tmp_vault):
    from hyperresearch.core.hooks import _install_claude_stop_hook

    path = tmp_vault.root / ".claude" / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    foreign = {
        "permissions": {"allow": ["Bash(ls:*)"]},
        "hooks": {
            "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "lint"}]}],
            "Stop": [
                {"hooks": [{"type": "command", "command": "notify-done"}]},
                {"hooks": [{"type": "command", "command": "/old/hpr run stop-gate"}]},
            ],
        },
    }
    path.write_text(json.dumps(foreign), encoding="utf-8")

    assert _install_claude_stop_hook(tmp_vault.root, "/new venv/hpr")
    merged = _settings(tmp_vault.root)
    assert merged["permissions"] == foreign["permissions"]
    assert merged["hooks"]["PreToolUse"] == foreign["hooks"]["PreToolUse"]
    commands = [e["hooks"][0]["command"] for e in merged["hooks"]["Stop"]]
    assert commands == ["notify-done", '"/new venv/hpr" run stop-gate']


def test_claude_stop_hook_leaves_an_unparseable_settings_file_alone(tmp_vault):
    from hyperresearch.core.hooks import _install_claude_stop_hook

    path = tmp_vault.root / ".claude" / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ not json", encoding="utf-8")
    result = _install_claude_stop_hook(tmp_vault.root, "hyperresearch")
    assert result and "NOT installed" in result
    assert path.read_text(encoding="utf-8") == "{ not json"


def test_claude_reason_names_the_step_skill_not_a_codex_file(tmp_vault):
    from hyperresearch.core.runs import init_run, set_step

    init_run(tmp_vault, "gate-run")
    set_step(tmp_vault, "gate-run", "1", "done")
    reason = codex.stop_gate_decision(tmp_vault, platform="claude")["reason"]
    assert "gate-run is at step 2 (hyperresearch-2-width-sweep)" in reason
    assert 'invoke Skill(skill: "hyperresearch-2-width-sweep")' in reason
    # Waiting on the step's own subagents, and on the user, both come before
    # the instruction to run the step again.
    assert reason.index("still running") < reason.index("invoke Skill")
    assert "wait for them with a tool call" in reason
    assert reason.index("waiting for the user") < reason.index("invoke Skill")
    assert "end your turn again" in reason
    assert reason.endswith("Ending the turn mid-pipeline for any other reason is a failure.")
    assert ".hyperresearch/codex" not in reason


@pytest.mark.parametrize(
    ("payload", "platform"),
    [
        ({"transcript_path": CLAUDE_TRANSCRIPT}, "claude"),
        ({"transcript_path": "C:\\Users\\u\\.claude\\projects\\v\\0b1c.jsonl"}, "claude"),
        ({"transcript_path": "/home/u/.codex/sessions/2026/10/06/rollout.jsonl"}, "codex"),
        ({"transcript_path": "/home/u/claude/notes.jsonl"}, "codex"),
        ({"transcript_path": "/home/u/my.claude.notes/x.jsonl"}, "codex"),
        ({"transcript_path": None}, "codex"),
        ({}, "codex"),
    ],
)
def test_stop_gate_platform_from_hook_input(payload, platform):
    assert codex.stop_gate_platform(payload, environ={}) == platform


def test_stop_gate_platform_from_the_hook_environment():
    payload = {"transcript_path": "/home/u/.codex/sessions/rollout.jsonl"}
    assert codex.stop_gate_platform(payload, environ={"CLAUDE_PROJECT_DIR": "/v"}) == "claude"
    assert codex.stop_gate_platform(payload, environ={"CLAUDE_PROJECT_DIR": ""}) == "codex"


def test_stop_gate_platform_from_the_vault_shape(tmp_path):
    (tmp_path / ".claude" / "skills").mkdir(parents=True)
    assert codex.stop_gate_platform({}, environ={}, vault_root=tmp_path) == "claude"
    (tmp_path / ".hyperresearch" / "codex" / "steps").mkdir(parents=True)
    assert codex.stop_gate_platform({}, environ={}, vault_root=tmp_path) == "codex"


def _gate_in_running_vault(tmp_vault, monkeypatch, payload):
    from hyperresearch.core.runs import init_run

    monkeypatch.chdir(tmp_vault.root)
    monkeypatch.delenv("HYPERRESEARCH_STOP_GATE", raising=False)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    init_run(tmp_vault, "gate-run")
    result = runner.invoke(app, ["run", "stop-gate"], input=json.dumps(payload))
    assert result.exit_code == 0
    return json.loads(result.stdout)


def test_cli_gate_under_claude_code(tmp_vault, monkeypatch):
    decision = _gate_in_running_vault(tmp_vault, monkeypatch, {"transcript_path": CLAUDE_TRANSCRIPT})
    assert decision["decision"] == "block"
    assert 'invoke Skill(skill: "hyperresearch-1-decompose")' in decision["reason"]


def test_cli_gate_without_a_claude_transcript_keeps_the_codex_reason(tmp_vault, monkeypatch):
    decision = _gate_in_running_vault(tmp_vault, monkeypatch, {"cwd": "."})
    assert ".hyperresearch/codex/steps/hyperresearch-1-decompose.md" in decision["reason"]
    assert "Skill(" not in decision["reason"]


def test_global_install_writes_no_stop_hook(tmp_path):
    from hyperresearch.core.hooks import install_global_hooks

    install_global_hooks(tmp_path, hpr_path="hyperresearch")
    settings = tmp_path / ".claude" / "settings.json"
    assert not settings.exists() or "stop-gate" not in settings.read_text(encoding="utf-8")


def test_steps_only_install_adds_the_claude_stop_hook(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["install", "--steps-only", ".", "--target", "claude"])
    assert result.exit_code == 0, result.output
    (entry,) = _settings(tmp_path)["hooks"]["Stop"]
    assert entry["hooks"][0]["command"].endswith("run stop-gate")


def test_full_install_on_an_unparseable_settings_file(tmp_vault):
    # The PreToolUse installer runs first and rewrites a file it cannot parse
    # (unchanged behaviour), so the Stop installer then finds a valid file.
    path = tmp_vault.root / ".claude" / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ not json", encoding="utf-8")
    install_hooks(tmp_vault.root, "hyperresearch")
    assert set(_settings(tmp_vault.root)["hooks"]) == {"PreToolUse", "Stop"}
