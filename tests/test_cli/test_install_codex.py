"""CLI coverage for --platform codex and --platform both."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _skip_browser_setup(monkeypatch):
    """Codex installer coverage does not need to install a browser binary."""
    monkeypatch.setattr(
        "hyperresearch.cli.install._setup_crawl4ai",
        lambda _vault: "not_installed",
    )


def test_install_default_remains_claude_only(tmp_path):
    root = tmp_path / "default-project"
    result = runner.invoke(app, ["install", str(root), "--json"])

    assert result.exit_code == 0, result.stdout
    data = json.loads(result.stdout)["data"]
    assert data["platform"] == "claude"
    assert (root / "CLAUDE.md").exists()
    assert (root / ".claude" / "skills" / "hyperresearch" / "SKILL.md").exists()
    assert not (root / "AGENTS.md").exists()
    assert not (root / ".agents").exists()


def test_steps_only_default_preserves_string_json_shape(tmp_vault):
    result = runner.invoke(
        app,
        ["install", str(tmp_vault.root), "--steps-only", "--json"],
    )

    assert result.exit_code == 0, result.stdout
    value = json.loads(result.stdout)["data"]["steps_installed"]
    assert value is None or isinstance(value, str)


def test_steps_only_codex_installs_only_codex_steps(tmp_path):
    root = tmp_path / "steps-only"
    result = runner.invoke(
        app,
        [
            "install",
            str(root),
            "--steps-only",
            "--platform",
            "codex",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert (root / ".agents" / "skills" / "hyperresearch-1-decompose" / "SKILL.md").exists()
    assert not (root / ".agents" / "skills" / "hyperresearch" / "SKILL.md").exists()
    assert not (root / ".claude").exists()
    assert not (root / ".hyperresearch").exists()


def test_global_codex_installs_router_without_project_state(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    result = runner.invoke(
        app,
        ["install", "--global", "--platform", "codex", "--json"],
    )

    assert result.exit_code == 0, result.stdout
    assert (tmp_path / ".agents" / "skills" / "hyperresearch" / "SKILL.md").exists()
    assert (tmp_path / ".codex" / "agents" / "hyperresearch_fetcher.toml").exists()
    assert not (tmp_path / ".codex" / "hooks.json").exists()
    assert not (tmp_path / ".agents" / "skills" / "hyperresearch-1-decompose" / "SKILL.md").exists()
    assert not (tmp_path / ".hyperresearch").exists()
    assert not (tmp_path / "AGENTS.md").exists()


def test_install_codex_platform(tmp_path):
    root = tmp_path / "codex-project"
    result = runner.invoke(
        app,
        ["install", str(root), "--platform", "codex", "--json"],
    )

    assert result.exit_code == 0, result.stdout
    assert (root / "AGENTS.md").exists()
    assert not (root / "CLAUDE.md").exists()
    assert (root / ".agents" / "skills" / "hyperresearch" / "SKILL.md").exists()
    assert (root / ".codex" / "agents" / "hyperresearch_fetcher.toml").exists()
    assert (root / ".codex" / "hooks.json").exists()
    assert not (root / ".claude").exists()


def test_install_both_platforms(tmp_path):
    root = tmp_path / "both-project"
    result = runner.invoke(
        app,
        ["install", str(root), "--platform", "both", "--json"],
    )

    assert result.exit_code == 0, result.stdout
    assert (root / "AGENTS.md").exists()
    assert (root / "CLAUDE.md").exists()
    assert (root / ".agents" / "skills" / "hyperresearch" / "SKILL.md").exists()
    assert (root / ".claude" / "skills" / "hyperresearch" / "SKILL.md").exists()


def test_install_rejects_unknown_platform(tmp_path):
    result = runner.invoke(
        app,
        ["install", str(tmp_path), "--platform", "other", "--json"],
    )
    assert result.exit_code == 1
    assert "UNKNOWN_PLATFORM" in result.stdout
