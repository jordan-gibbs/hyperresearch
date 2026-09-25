"""CLI: `hyperresearch install --target`, `run stop-gate`, and `run resume` Codex hint."""

from __future__ import annotations

import json
import tomllib

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app

runner = CliRunner()


def _json(result) -> dict:
    return json.loads(result.stdout)


def test_install_target_codex(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)
    result = runner.invoke(app, ["install", str(tmp_vault.root), "--target", "codex", "--json"])
    assert result.exit_code == 0, result.stdout
    data = _json(result)["data"]
    assert data["targets"] == ["codex"]
    # Existing keys are kept
    for key in ("vault_path", "vault", "agent_docs", "hooks_installed", "crawl4ai"):
        assert key in data
    assert "AGENTS.md (created)" in data["agent_docs"]

    root = tmp_vault.root
    assert not (root / ".claude").exists()
    assert (root / ".agents" / "skills" / "hyperresearch" / "SKILL.md").is_file()
    assert (root / ".codex" / "hooks.json").is_file()
    for toml in (root / ".codex" / "agents").glob("*.toml"):
        parsed = tomllib.loads(toml.read_text(encoding="utf-8"))
        assert {"name", "description", "developer_instructions"} <= set(parsed)

    again = runner.invoke(app, ["install", str(root), "--target", "codex", "--json"])
    assert again.exit_code == 0
    assert _json(again)["data"]["hooks_installed"] == []


def test_codex_only_install_on_fresh_dir_writes_no_claude_files(tmp_path, monkeypatch):
    root = tmp_path / "fresh"
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["install", str(root), "--target", "codex", "--json"])
    assert result.exit_code == 0, result.stdout
    assert _json(result)["data"]["vault"] == "created"
    assert (root / "AGENTS.md").is_file()
    assert not (root / "CLAUDE.md").exists()
    assert not (root / ".claude").exists()


def test_fresh_all_install_writes_both_docs(tmp_path, monkeypatch):
    root = tmp_path / "fresh"
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["install", str(root), "--target", "all", "--json"])
    assert result.exit_code == 0, result.stdout
    assert (root / "AGENTS.md").is_file()
    assert (root / "CLAUDE.md").is_file()


def test_install_target_all(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)
    result = runner.invoke(app, ["install", str(tmp_vault.root), "--target", "all", "--json"])
    assert result.exit_code == 0, result.stdout
    data = _json(result)["data"]
    assert data["targets"] == ["claude", "codex"]
    root = tmp_vault.root
    assert (root / ".claude" / "skills" / "hyperresearch" / "SKILL.md").is_file()
    assert (root / ".claude" / "agents" / "hyperresearch-browser-fetcher.md").is_file()
    assert (root / ".agents" / "skills" / "hyperresearch" / "SKILL.md").is_file()
    assert not (root / ".codex" / "agents" / "hyperresearch-browser-fetcher.toml").exists()
    assert (root / "AGENTS.md").is_file()
    assert (root / "CLAUDE.md").is_file()


def test_install_default_target_is_claude(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)
    result = runner.invoke(app, ["install", str(tmp_vault.root), "--json"])
    assert result.exit_code == 0
    assert _json(result)["data"]["targets"] == ["claude"]
    assert not (tmp_vault.root / ".codex").exists()
    assert not (tmp_vault.root / ".agents").exists()
    assert not (tmp_vault.root / "AGENTS.md").exists()


def test_install_unknown_target_fails_before_writing(tmp_path, monkeypatch):
    target = tmp_path / "fresh"
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["install", str(target), "--target", "gemini", "--json"])
    assert result.exit_code == 1
    assert _json(result)["error_code"] == "UNKNOWN_TARGET"
    assert not target.exists()


def test_install_steps_only_codex(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)
    result = runner.invoke(
        app, ["install", str(tmp_vault.root), "--steps-only", "--target", "codex", "--json"]
    )
    assert result.exit_code == 0, result.stdout
    data = _json(result)["data"]
    assert data["targets"] == ["codex"]
    assert data["steps_installed"]
    root = tmp_vault.root
    assert (root / ".hyperresearch" / "codex" / "steps" / "hyperresearch-1-decompose.md").is_file()
    assert (root / ".codex" / "hooks.json").is_file()
    assert not (root / ".claude").exists()
    assert not (root / ".codex" / "agents").exists()

    again = runner.invoke(
        app, ["install", str(root), "--steps-only", "--target", "codex", "--json"]
    )
    assert _json(again)["data"]["steps_installed"] is None


def test_install_global_codex(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr("pathlib.Path.home", lambda: home)
    result = runner.invoke(app, ["install", "--global", "--target", "codex", "--json"])
    assert result.exit_code == 0, result.stdout
    data = _json(result)["data"]
    assert data["global"] is True and data["targets"] == ["codex"]
    assert (home / ".agents" / "skills" / "hyperresearch" / "SKILL.md").is_file()
    assert (home / ".codex" / "agents" / "hyperresearch-fetcher.toml").is_file()
    assert not (home / ".codex" / "config.toml").exists()
    assert not (home / ".codex" / "hooks.json").exists()
    assert not (home / ".claude").exists()


def test_install_codex_console_mentions_exec_flags(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)
    result = runner.invoke(app, ["install", str(tmp_vault.root), "--target", "codex"])
    assert result.exit_code == 0
    out = " ".join(result.stdout.split())
    assert "$hyperresearch" in out
    assert "sandbox_workspace_write.network_access=true" in out
    assert "--dangerously-bypass-hook-trust" in out


def test_profile_use_rerenders_codex_install(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)
    runner.invoke(app, ["install", str(tmp_vault.root), "--target", "all", "--json"])
    result = runner.invoke(app, ["profile", "use", "premier", "--json"])
    assert result.exit_code == 0, result.stdout
    step = tmp_vault.root / ".hyperresearch" / "codex" / "steps" / "hyperresearch-2-width-sweep.md"
    assert 'rendered from profile "premier"' in step.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# run stop-gate
# ---------------------------------------------------------------------------


def _gate(stdin: str = "{}", env: dict | None = None):
    return runner.invoke(app, ["run", "stop-gate"], input=stdin, env=env)


def test_stop_gate_silent_without_vault(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = _gate()
    assert result.exit_code == 0
    assert result.stdout == ""


def test_stop_gate_silent_without_runs(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)
    result = _gate()
    assert result.exit_code == 0
    assert result.stdout == ""


@pytest.fixture
def running_vault(tmp_vault, monkeypatch):
    from hyperresearch.core.runs import init_run

    monkeypatch.chdir(tmp_vault.root)
    monkeypatch.delenv("HYPERRESEARCH_STOP_GATE", raising=False)
    init_run(tmp_vault, "gate-run")
    return tmp_vault


def test_stop_gate_blocks_in_progress_run(running_vault):
    result = _gate('{"stop_hook_active": false, "cwd": "."}')
    assert result.exit_code == 0
    decision = json.loads(result.stdout)
    assert decision["decision"] == "block"
    assert "gate-run is at step 1 (hyperresearch-1-decompose)" in decision["reason"]
    assert ".hyperresearch/codex/steps/hyperresearch-1-decompose.md" in decision["reason"]
    assert result.stdout.count("\n") == 1  # exactly one JSON object


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
    result = _gate("{}", env={"HYPERRESEARCH_STOP_GATE": "0"})
    assert result.exit_code == 0
    assert result.stdout == ""


def test_stop_gate_silent_for_finished_run(running_vault):
    from hyperresearch.core.runs import set_status

    set_status(running_vault, "gate-run", "done")
    result = _gate()
    assert result.exit_code == 0
    assert result.stdout == ""


def test_stop_gate_follows_cwd_from_hook_input(running_vault, tmp_path, monkeypatch):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    payload = json.dumps({"cwd": str(running_vault.root)})
    assert json.loads(_gate(payload).stdout)["decision"] == "block"


def test_stop_gate_hidden_from_help():
    result = runner.invoke(app, ["run", "--help"])
    assert "stop-gate" not in result.stdout


def test_run_resume_includes_codex_step_file(running_vault):
    result = runner.invoke(app, ["run", "resume", "--json"])
    assert result.exit_code == 0
    data = _json(result)["data"]
    assert data["skill_to_invoke"] == "hyperresearch-1-decompose"
    assert data["codex_step_file"] == ".hyperresearch/codex/steps/hyperresearch-1-decompose.md"
