"""CLI coverage for --platform codex and --platform both."""

from __future__ import annotations

from typer.testing import CliRunner

from hyperresearch.cli import app

runner = CliRunner()


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
