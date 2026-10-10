"""CLI: `hyperresearch install --target omp`, `run stop-gate --platform`, `run resume`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app

runner = CliRunner()


def _json(result) -> dict:
    return json.loads(result.stdout)


def test_install_target_omp(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)
    result = runner.invoke(app, ["install", str(tmp_vault.root), "--target", "omp", "--json"])
    assert result.exit_code == 0, result.stdout
    data = _json(result)["data"]
    assert data["targets"] == ["omp"]
    for key in ("vault_path", "vault", "agent_docs", "hooks_installed", "crawl4ai"):
        assert key in data
    assert "AGENTS.md (created)" in data["agent_docs"]

    root = tmp_vault.root
    assert not (root / ".claude").exists()
    assert not (root / ".codex").exists()
    assert not (root / ".agents").exists()
    assert (root / ".omp" / "skills" / "hyperresearch" / "SKILL.md").is_file()
    assert (root / ".omp" / "commands" / "hyperresearch.md").is_file()
    assert (root / ".omp" / "extensions" / "hyperresearch.ts").is_file()
    assert len(list((root / ".omp" / "agents").glob("*.md"))) == 16
    assert len(list((root / ".hyperresearch" / "omp" / "steps").glob("*.md"))) == 18
    assert "/hyperresearch" in (root / "AGENTS.md").read_text(encoding="utf-8")

    again = runner.invoke(app, ["install", str(root), "--target", "omp", "--json"])
    assert again.exit_code == 0
    assert _json(again)["data"]["hooks_installed"] == []


def test_install_target_all_excludes_omp(tmp_path, monkeypatch):
    root = tmp_path / "fresh"
    root.mkdir()
    monkeypatch.chdir(root)
    result = runner.invoke(app, ["install", str(root), "--target", "all", "--json"])
    assert result.exit_code == 0, result.stdout
    assert _json(result)["data"]["targets"] == ["claude", "codex"]
    assert not (root / ".omp").exists()


def test_install_steps_only_omp(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)
    result = runner.invoke(
        app, ["install", str(tmp_vault.root), "--steps-only", "--target", "omp", "--json"]
    )
    assert result.exit_code == 0, result.stdout
    data = _json(result)["data"]
    assert data["targets"] == ["omp"]
    assert data["steps_installed"]
    root = tmp_vault.root
    assert (root / ".hyperresearch" / "omp" / "steps" / "hyperresearch-1-decompose.md").is_file()
    # The per-project trigger and gate come along, like Codex's Stop hook.
    assert (root / ".omp" / "commands" / "hyperresearch.md").is_file()
    assert (root / ".omp" / "extensions" / "hyperresearch.ts").is_file()
    assert not (root / ".omp" / "agents").exists()
    assert not (root / ".claude").exists()

    again = runner.invoke(
        app, ["install", str(root), "--steps-only", "--target", "omp", "--json"]
    )
    assert _json(again)["data"]["steps_installed"] is None


def test_install_global_omp(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr("pathlib.Path.home", lambda: home)
    result = runner.invoke(app, ["install", "--global", "--target", "omp", "--json"])
    assert result.exit_code == 0, result.stdout
    data = _json(result)["data"]
    assert data["global"] is True and data["targets"] == ["omp"]
    assert (home / ".omp" / "agent" / "skills" / "hyperresearch" / "SKILL.md").is_file()
    assert (home / ".omp" / "agent" / "commands" / "hyperresearch.md").is_file()
    assert (home / ".omp" / "agent" / "agents" / "hyperresearch-fetcher.md").is_file()
    assert not (home / ".omp" / "skills").exists()
    assert not (home / ".hyperresearch").exists()
    assert not (home / ".claude").exists()


def test_install_omp_console_mentions_the_slash_command(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)
    result = runner.invoke(app, ["install", str(tmp_vault.root), "--target", "omp"])
    assert result.exit_code == 0
    out = " ".join(result.stdout.split())
    assert "Ready (OMP)" in out
    assert "/hyperresearch <query>" in out


def test_install_unknown_target_lists_omp(tmp_path, monkeypatch):
    target = tmp_path / "fresh"
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["install", str(target), "--target", "gemini", "--json"])
    assert result.exit_code != 0
    assert "claude, codex, omp, all" in _json(result)["error"]
    assert not target.exists()


def test_profile_use_rerenders_omp_install(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)
    runner.invoke(app, ["install", str(tmp_vault.root), "--target", "omp", "--json"])
    result = runner.invoke(app, ["profile", "use", "premier", "--json"])
    assert result.exit_code == 0, result.stdout
    step = tmp_vault.root / ".hyperresearch" / "omp" / "steps" / "hyperresearch-2-width-sweep.md"
    assert 'rendered from profile "premier"' in step.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# run stop-gate --platform / run resume
# ---------------------------------------------------------------------------


@pytest.fixture
def running_vault(tmp_vault, monkeypatch):
    from hyperresearch.core.runs import init_run

    monkeypatch.chdir(tmp_vault.root)
    init_run(tmp_vault, "gate-run", profile="full")
    return tmp_vault


def _gate(stdin: str = "{}", platform: str = "omp", env: dict | None = None):
    args = ["run", "stop-gate", "--platform", platform]
    return runner.invoke(app, args, input=stdin, env=env)


def test_stop_gate_platform_omp(running_vault):
    result = _gate()
    assert result.exit_code == 0
    reason = json.loads(result.stdout)["reason"]
    assert ".hyperresearch/omp/steps/hyperresearch-1-decompose.md" in reason


@pytest.mark.parametrize("stdin", ["", "not json", "[1, 2]"])
def test_stop_gate_tolerates_bad_stdin(running_vault, stdin):
    result = _gate(stdin)
    assert result.exit_code == 0
    assert json.loads(result.stdout)["decision"] == "block"


def test_stop_gate_silent_when_stop_hook_active(running_vault):
    result = _gate('{"stop_hook_active": true}')
    assert result.exit_code == 0
    assert result.stdout == ""


def test_stop_gate_env_opt_out(running_vault):
    """The extension's documented kill switch: HYPERRESEARCH_STOP_GATE=0."""
    result = _gate(env={"HYPERRESEARCH_STOP_GATE": "0"})
    assert result.exit_code == 0
    assert result.stdout == ""


def test_stop_gate_defaults_to_codex(running_vault):
    default = runner.invoke(app, ["run", "stop-gate"], input="{}")
    codex = runner.invoke(app, ["run", "stop-gate", "--platform", "codex"], input="{}")
    assert default.stdout == codex.stdout
    assert ".hyperresearch/codex/steps/" in json.loads(default.stdout)["reason"]


def test_stop_gate_unknown_platform_stays_silent(running_vault):
    result = runner.invoke(app, ["run", "stop-gate", "--platform", "gemini"], input="{}")
    assert result.exit_code == 0
    assert result.stdout == ""


def test_stop_gate_hidden_from_help():
    result = runner.invoke(app, ["run", "--help"])
    assert "stop-gate" not in result.stdout


def test_run_resume_includes_omp_step_file(running_vault):
    result = runner.invoke(app, ["run", "resume", "--json"])
    assert result.exit_code == 0, result.stdout
    data = _json(result)["data"]
    assert data["omp_step_file"] == ".hyperresearch/omp/steps/hyperresearch-1-decompose.md"
    assert data["codex_step_file"] == ".hyperresearch/codex/steps/hyperresearch-1-decompose.md"


def test_install_omp_writes_no_step_skill_dirs(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)
    runner.invoke(app, ["install", str(tmp_vault.root), "--target", "omp", "--json"])
    skills = tmp_vault.root / ".omp" / "skills"
    assert {p.name for p in skills.iterdir()} == {"hyperresearch"}
    assert not Path(skills / "hyperresearch-1-decompose").exists()
