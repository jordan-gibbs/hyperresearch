"""Tests for note mv, edit, rm CLI operations."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app

runner = CliRunner()


@pytest.fixture
def vault_with_notes(tmp_path: Path) -> Path:
    vault_dir = tmp_path / "kb"
    runner.invoke(app, ["init", str(vault_dir)])
    os.chdir(vault_dir)
    runner.invoke(app, ["note", "new", "Alpha Note", "--tag", "test"])
    runner.invoke(app, ["note", "new", "Beta Note", "--tag", "test"])
    runner.invoke(app, ["sync"])
    return vault_dir


def test_note_rm_json(vault_with_notes):
    result = runner.invoke(app, ["note", "rm", "alpha-note", "--force", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["ok"] is True
    assert data["data"]["deleted"] == "alpha-note"


def test_note_rm_nonexistent(vault_with_notes):
    result = runner.invoke(app, ["note", "rm", "nonexistent", "--force", "--json"])
    assert result.exit_code == 1


def test_note_mv(vault_with_notes):
    result = runner.invoke(
        app, ["note", "mv", "beta-note", "notes/moved/beta-note.md", "--json"]
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["data"]["new_path"] == "notes/moved/beta-note.md"
    assert (vault_with_notes / "notes" / "moved" / "beta-note.md").exists()


def test_note_show_raw(vault_with_notes):
    result = runner.invoke(app, ["note", "show", "alpha-note", "--raw"])
    assert result.exit_code == 0
    assert "---" in result.output
    assert "Alpha Note" in result.output


def test_note_list_with_filters(vault_with_notes):
    result = runner.invoke(app, ["note", "list", "--tag", "test", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["count"] >= 2

    result = runner.invoke(app, ["note", "list", "--status", "draft", "--json"])
    data = json.loads(result.output)
    assert data["count"] >= 2

    result = runner.invoke(app, ["note", "list", "--sort", "title", "--limit", "1", "--json"])
    data = json.loads(result.output)
    assert data["count"] == 1
