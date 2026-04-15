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


def test_note_rm_cleans_raw_file_and_assets(vault_with_notes):
    """note rm must delete the raw file and assets directory, not just the .md.

    Regression test for Batch 2.5 — prior to this, `note rm` only unlinked
    the `.md` file and raw/assets leaked on disk forever.
    """
    vault_root = vault_with_notes

    # Seed a note with raw_file in its frontmatter and an assets directory.
    from hyperresearch.core.note import write_note
    from hyperresearch.core.vault import Vault
    vault = Vault.discover()

    write_note(
        vault.notes_dir,
        "PDF Source",
        note_id="pdf-source",
        source="https://example.com/paper.pdf",
        tier="ground_truth",
        content_type="paper",
        extra_frontmatter={"raw_file": "raw/pdf-source.pdf"},
    )

    raw_dir = vault_root / "research" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_file = raw_dir / "pdf-source.pdf"
    raw_file.write_bytes(b"%PDF-1.4 test")

    assets_dir = vault_root / "research" / "assets" / "pdf-source"
    assets_dir.mkdir(parents=True, exist_ok=True)
    (assets_dir / "screenshot.png").write_bytes(b"PNG fake")
    (assets_dir / "figure-1.jpg").write_bytes(b"JPG fake")

    runner.invoke(app, ["sync"])

    # Delete it
    result = runner.invoke(app, ["note", "rm", "pdf-source", "--force", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["ok"] is True
    assert data["data"]["deleted"] == "pdf-source"
    assert data["data"].get("removed_raw") == "research/raw/pdf-source.pdf"
    assert len(data["data"].get("removed_assets", [])) == 2

    # Verify the files are actually gone from disk.
    assert not raw_file.exists(), "raw file should have been deleted"
    assert not assets_dir.exists(), "assets directory should have been removed"


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
