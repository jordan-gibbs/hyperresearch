"""`install` must never overwrite a hook config it cannot parse.

A `.claude/settings.json` with a comment or a trailing comma failed to parse,
was treated as `{}`, and was written back holding only our PreToolUse hook, so
the user's permissions, deny rules and model were lost with exit 0. A file we
cannot merge into is now left byte-for-byte as it is, the hook is reported as
NOT installed with the parse error position, and the rest of install goes on,
the same way a read-only `.codex/` is reported.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.core.hooks import _install_claude_hook, _install_codex_stop_hook

runner = CliRunner()

# JSONC as people write it by hand: Claude Code's own docs show comments, and
# a trailing comma is the usual leftover after deleting the last key.
COMMENTED = (
    '{\n  // keep secrets out\n  "permissions": {"deny": ["Read(./.env)"]},\n'
    '  "model": "opus",\n}\n'
)


@pytest.fixture(autouse=True)
def _no_browser_setup(monkeypatch):
    # install probes for crawl4ai and may launch or install Chromium; that is
    # unrelated to the hook config and slow.
    monkeypatch.setattr(
        "hyperresearch.cli.install._setup_crawl4ai", lambda vault: "not_installed"
    )


def _write_settings(root, text: str):
    path = root / ".claude" / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return path


def test_install_json_leaves_unparseable_settings_untouched(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    settings_path = _write_settings(root, COMMENTED)
    monkeypatch.chdir(root)

    result = runner.invoke(app, ["install", str(root), "--json"])

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert settings_path.read_bytes() == COMMENTED.encode("utf-8")
    actions = payload["data"]["hooks_installed"]
    [report] = [a for a in actions if ".claude/settings.json" in a]
    assert "NOT installed" in report
    assert "line 2, column 3" in report
    # The rest of the install still happened.
    assert (root / ".claude" / "skills" / "hyperresearch" / "SKILL.md").is_file()


def test_install_console_reports_unparseable_settings(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    settings_path = _write_settings(root, COMMENTED)
    # An existing vault skips the interactive setup route.
    runner.invoke(app, ["init", str(root), "--json"])
    monkeypatch.chdir(root)

    result = runner.invoke(app, ["install", str(root)])

    assert result.exit_code == 0, result.stdout
    out = " ".join(result.stdout.split())
    assert ".claude/settings.json is not valid JSON (line 2, column 3" in out
    assert "PreToolUse hook was NOT installed" in out
    assert settings_path.read_bytes() == COMMENTED.encode("utf-8")


def test_profile_use_console_reports_unparseable_settings(tmp_vault, monkeypatch):
    # `profile use` runs the same installers but reports only a count, which
    # took the refusal for a re-rendered file and never showed it.
    settings_path = _write_settings(tmp_vault.root, COMMENTED)
    monkeypatch.chdir(tmp_vault.root)

    first = runner.invoke(app, ["profile", "use", "premier"])
    again = runner.invoke(app, ["profile", "use", "premier"])

    for result in (first, again):
        assert result.exit_code == 0, result.stdout
        out = " ".join(result.stdout.split())
        assert ".claude/settings.json is not valid JSON (line 2, column 3" in out
        assert "PreToolUse hook was NOT installed" in out
    assert "all installed prompts already at this gear" in again.stdout
    assert settings_path.read_bytes() == COMMENTED.encode("utf-8")


@pytest.mark.parametrize(
    "content",
    [b"[]", b"null", b'"hooks"', b"", b'\xff{"model": "opus"}'],
    ids=["array", "null", "string", "empty", "not-utf8"],
)
def test_claude_hook_refuses_settings_it_cannot_merge_into(tmp_path, content):
    path = tmp_path / ".claude" / "settings.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(content)

    result = _install_claude_hook(tmp_path, "hyperresearch")

    assert result and "NOT installed" in result and ".claude/settings.json" in result
    assert path.read_bytes() == content
    assert not (tmp_path / ".hyperresearch" / "hook.js").exists()


def test_claude_hook_reports_unreadable_settings(tmp_path):
    path = tmp_path / ".claude" / "settings.json"
    path.mkdir(parents=True)

    result = _install_claude_hook(tmp_path, "hyperresearch")

    assert result and "NOT installed" in result and "could not be read" in result
    assert path.is_dir()


def test_codex_hook_reports_parse_position(tmp_vault):
    # A comment, not a trailing comma: Python 3.13 moved the reported position
    # of a trailing comma, and the comment's position is the same everywhere.
    original = '{\n  "hooks": {}\n  // ours\n}\n'
    hooks_path = tmp_vault.root / ".codex" / "hooks.json"
    hooks_path.parent.mkdir(parents=True)
    hooks_path.write_text(original, encoding="utf-8")

    result = _install_codex_stop_hook(tmp_vault.root, "hyperresearch")

    assert result and "NOT installed" in result
    assert ".codex/hooks.json is not valid JSON (line 3, column 3" in result
    assert hooks_path.read_text(encoding="utf-8") == original


def test_codex_hook_reports_non_utf8_hooks_json(tmp_vault):
    hooks_path = tmp_vault.root / ".codex" / "hooks.json"
    hooks_path.parent.mkdir(parents=True)
    hooks_path.write_bytes(b"\xff{}")

    result = _install_codex_stop_hook(tmp_vault.root, "hyperresearch")

    assert result and "NOT installed" in result
    assert hooks_path.read_bytes() == b"\xff{}"


def test_valid_settings_are_still_merged_and_rerun_is_a_noop(tmp_path):
    foreign_pre = {"matcher": "Bash", "hooks": [{"type": "command", "command": "lint"}]}
    original = {
        "permissions": {"deny": ["Read(./.env)"]},
        "model": "opus",
        "hooks": {
            "PreToolUse": [foreign_pre],
            "Stop": [{"hooks": [{"type": "command", "command": "notify-done"}]}],
        },
    }
    path = tmp_path / ".claude" / "settings.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(original), encoding="utf-8")

    assert _install_claude_hook(tmp_path, "hyperresearch") == (
        "Claude Code: .claude/settings.json (PreToolUse hook)"
    )
    merged = json.loads(path.read_text(encoding="utf-8"))
    assert merged["permissions"] == original["permissions"]
    assert merged["model"] == "opus"
    assert merged["hooks"]["Stop"] == original["hooks"]["Stop"]
    pre = merged["hooks"]["PreToolUse"]
    assert pre[0] == foreign_pre
    assert pre[1]["matcher"] == "WebSearch|WebFetch"
    assert len(pre) == 2

    after_first = path.read_bytes()
    assert _install_claude_hook(tmp_path, "hyperresearch") is None
    assert path.read_bytes() == after_first
