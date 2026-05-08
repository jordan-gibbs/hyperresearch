"""CLI integration tests using typer.testing.CliRunner."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app

runner = CliRunner()


@pytest.fixture
def vault_dir(tmp_path: Path) -> Path:
    """Init a vault and return its path."""
    result = runner.invoke(app, ["init", str(tmp_path / "kb"), "--name", "CLI Test"])
    assert result.exit_code == 0
    return tmp_path / "kb"


def test_init(tmp_path: Path):
    result = runner.invoke(app, ["init", str(tmp_path / "new-kb")])
    assert result.exit_code == 0
    assert "Initialized" in result.output


def test_init_json(tmp_path: Path):
    result = runner.invoke(app, ["init", str(tmp_path / "json-kb"), "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["ok"] is True
    assert "vault_path" in data["data"]


def test_install_codex_json_creates_agents_md_without_claude_hooks(tmp_path: Path):
    root = tmp_path / "codex-kb"
    result = runner.invoke(app, ["install", str(root), "--codex", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["ok"] is True
    assert data["data"]["vault"] == "created"
    assert data["data"]["hooks_installed"] == []
    assert data["data"]["crawl4ai"] == "skipped"
    assert data["data"]["codex_workflow"]
    assert data["data"]["codex_trust"]["required_for_project_hooks"] is True
    assert str(root).replace("\\", "/") in data["data"]["codex_trust"]["toml"]

    agents_path = root / "AGENTS.md"
    assert agents_path.exists()
    body = agents_path.read_text(encoding="utf-8")
    assert "hyperresearch for Codex" in body
    assert "hyperresearch ... --json" in body
    assert "Codex Trust And Hooks" in body
    assert "Until the project is trusted" in body
    assert "MCP is available" in body

    assert not (root / ".claude").exists()
    assert not (root / ".hyperresearch" / "hook.js").exists()
    assert (root / ".codex" / "hooks.json").exists()
    assert (root / ".codex" / "hooks" / "hyperresearch_pre_tool_use.py").exists()
    assert (root / ".codex" / "config.toml").exists()
    assert (root / ".agents" / "skills" / "hyperresearch" / "SKILL.md").exists()
    assert (root / ".agents" / "skills" / "hyperresearch-1-decompose" / "SKILL.md").exists()
    assert (root / ".codex" / "agents" / "hyperresearch-fetcher.toml").exists()


def test_install_codex_human_output_includes_trust_snippet(tmp_path: Path):
    root = tmp_path / "codex-human"
    result = runner.invoke(app, ["install", str(root), "--codex"])
    assert result.exit_code == 0

    assert "Codex trust:" in result.output
    assert '[projects."' in result.output
    assert 'codex-human"]' in result.output
    assert 'trust_level = "trusted"' in result.output


def test_install_codex_preserves_existing_agents_md(tmp_path: Path):
    root = tmp_path / "existing"
    root.mkdir()
    (root / "AGENTS.md").write_text("# Team rules\n\nDo not remove me.\n", encoding="utf-8")

    result = runner.invoke(app, ["install", str(root), "--codex", "--json"])
    assert result.exit_code == 0
    body = (root / "AGENTS.md").read_text(encoding="utf-8")
    assert "Do not remove me." in body
    assert body.count("<!-- hyperresearch-codex:start -->") == 1

    result = runner.invoke(app, ["install", str(root), "--codex", "--json"])
    assert result.exit_code == 0
    body = (root / "AGENTS.md").read_text(encoding="utf-8")
    assert "Do not remove me." in body
    assert body.count("<!-- hyperresearch-codex:start -->") == 1


def test_init_double(tmp_path: Path):
    runner.invoke(app, ["init", str(tmp_path / "dup")])
    result = runner.invoke(app, ["init", str(tmp_path / "dup")])
    assert result.exit_code == 1


def test_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "hyperresearch v" in result.output


def test_status(vault_dir: Path):
    os.chdir(vault_dir)
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "CLI Test" in result.output


def test_status_json(vault_dir: Path):
    os.chdir(vault_dir)
    result = runner.invoke(app, ["status", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["ok"] is True
    assert data["data"]["vault_name"] == "CLI Test"


def test_note_new_and_list(vault_dir: Path):
    os.chdir(vault_dir)
    result = runner.invoke(app, ["note", "new", "Test Note", "--tag", "test"])
    assert result.exit_code == 0
    assert "Created" in result.output

    result = runner.invoke(app, ["sync"])
    assert result.exit_code == 0

    result = runner.invoke(app, ["note", "list", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["ok"] is True
    assert data["count"] >= 1


def test_note_show(vault_dir: Path):
    os.chdir(vault_dir)
    runner.invoke(app, ["note", "new", "Show Me", "--tag", "demo"])
    runner.invoke(app, ["sync"])

    result = runner.invoke(app, ["note", "show", "show-me", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["data"]["title"] == "Show Me"


def test_note_tags(vault_dir: Path):
    os.chdir(vault_dir)
    runner.invoke(app, ["note", "new", "A", "--tag", "alpha"])
    runner.invoke(app, ["note", "new", "B", "--tag", "beta"])
    runner.invoke(app, ["sync"])

    result = runner.invoke(app, ["tags", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    tags = {t["tag"] for t in data["data"]}
    assert "alpha" in tags
    assert "beta" in tags


def test_search_text(vault_dir: Path):
    os.chdir(vault_dir)
    runner.invoke(app, ["note", "new", "Python Guide", "--tag", "python"])
    runner.invoke(app, ["sync"])

    result = runner.invoke(app, ["search", "python", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["data"]["total"] >= 1


def test_search_empty_query_with_tag_filter(vault_dir: Path):
    os.chdir(vault_dir)
    runner.invoke(app, ["note", "new", "Tagged Guide", "--tag", "codex-parity"])
    runner.invoke(app, ["sync"])

    result = runner.invoke(app, ["search", "", "--tag", "codex-parity", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    ids = {r["id"] for r in data["data"]["results"]}
    assert "tagged-guide" in ids


def test_graph_broken(vault_dir: Path):
    os.chdir(vault_dir)
    # Create a note with a broken link
    (vault_dir / "research" / "notes" / "linker.md").write_text(
        "---\ntitle: Linker\nid: linker\nstatus: draft\ntype: note\n---\n\nSee [[nowhere]]\n",
        encoding="utf-8",
    )
    runner.invoke(app, ["sync"])

    result = runner.invoke(app, ["graph", "broken", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["count"] >= 1


def test_lint(vault_dir: Path):
    os.chdir(vault_dir)
    runner.invoke(app, ["note", "new", "Lint Test"])
    runner.invoke(app, ["sync"])

    result = runner.invoke(app, ["lint", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "issues" in data["data"]
    assert "summary" in data["data"]


def test_sync_dry_run(vault_dir: Path):
    os.chdir(vault_dir)
    runner.invoke(app, ["note", "new", "Dry Run"])

    result = runner.invoke(app, ["sync", "--dry-run", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "to_add" in data["data"]


def test_index_build(vault_dir: Path):
    os.chdir(vault_dir)
    runner.invoke(app, ["note", "new", "Indexed Note", "--tag", "idx"])
    runner.invoke(app, ["sync"])

    result = runner.invoke(app, ["index", "build"])
    assert result.exit_code == 0
    assert "Built" in result.output

    result = runner.invoke(app, ["index", "list"])
    assert result.exit_code == 0


def test_export_json(vault_dir: Path):
    os.chdir(vault_dir)
    runner.invoke(app, ["note", "new", "Export Me"])
    runner.invoke(app, ["sync"])

    result = runner.invoke(app, ["export", "json", "--output", "exports/test.json"])
    assert result.exit_code == 0
    assert (vault_dir / "exports" / "test.json").exists()
