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
        app, ["note", "mv", "beta-note", "research/notes/moved/beta-note.md", "--json"]
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["data"]["new_path"] == "research/notes/moved/beta-note.md"
    assert (vault_with_notes / "research" / "notes" / "moved" / "beta-note.md").exists()


# ---------------------------------------------------------------------------
# `note mv` destinations must stay where sync can see them. The destination
# used to be joined onto the vault root verbatim: a bare name landed at the
# vault root with no .md suffix, outside everything sync scans, so the note
# silently left the index; and an existing file was overwritten.
# ---------------------------------------------------------------------------


def _indexed_path(note_id: str) -> str | None:
    from hyperresearch.core.vault import Vault

    row = Vault.discover().db.execute(
        "SELECT path FROM notes WHERE id = ?", (note_id,)
    ).fetchone()
    return row["path"] if row else None


def test_note_mv_bare_name_lands_in_notes_dir_with_md_suffix(vault_with_notes):
    result = runner.invoke(app, ["note", "mv", "beta-note", "beta-renamed", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["data"]["new_path"] == "research/notes/beta-renamed.md"
    assert (vault_with_notes / "research" / "notes" / "beta-renamed.md").exists()
    assert not (vault_with_notes / "beta-renamed").exists()
    # The id lives in frontmatter, so the note stays indexed under it, at the new path.
    assert _indexed_path("beta-note") == "research/notes/beta-renamed.md"


def test_note_mv_refuses_a_destination_outside_the_synced_tree(vault_with_notes):
    result = runner.invoke(
        app, ["note", "mv", "beta-note", "notes/moved/beta-note.md", "--json"]
    )
    assert result.exit_code == 1, result.output
    data = json.loads(result.output)
    assert data["ok"] is False
    assert data["error_code"] == "OUTSIDE_SYNCED_TREE"
    assert (vault_with_notes / "research" / "notes" / "beta-note.md").exists()
    assert not (vault_with_notes / "notes").exists()
    assert _indexed_path("beta-note") == "research/notes/beta-note.md"


@pytest.mark.parametrize("dest", ["research/notes/alpha-note.md", "alpha-note"])
def test_note_mv_refuses_to_overwrite_an_existing_file(vault_with_notes, dest):
    result = runner.invoke(app, ["note", "mv", "beta-note", dest, "--json"])
    assert result.exit_code == 1, result.output
    data = json.loads(result.output)
    assert data["error_code"] == "DESTINATION_EXISTS"
    alpha = (vault_with_notes / "research" / "notes" / "alpha-note.md").read_text(encoding="utf-8")
    assert "id: alpha-note" in alpha
    assert _indexed_path("alpha-note") == "research/notes/alpha-note.md"
    assert _indexed_path("beta-note") == "research/notes/beta-note.md"


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


def test_note_update_rejects_invalid_status(vault_with_notes):
    """`note update --status` must validate before writing frontmatter.

    Regression test: NoteMeta is a pydantic model configured without
    validate_assignment, so `meta.status = set_status` used to accept any
    string and serialize it straight into the note. The write reported
    success, but parse_frontmatter then refused to read the note back, and
    execute_sync swallowed the ValidationError per-file — leaving the note
    permanently absent from the index while the DB served stale rows. A
    one-letter typo (`evergreeen`) was enough to orphan a note for good.
    """
    result = runner.invoke(
        app, ["note", "update", "alpha-note", "--status", "evergreeen", "--json"]
    )
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["ok"] is False
    assert data["error_code"] == "INVALID_STATUS"
    assert "evergreen" in data["error"]  # lists the valid values

    # The note on disk must be untouched and still parseable.
    from hyperresearch.core.frontmatter import parse_frontmatter

    content = (vault_with_notes / "research/notes/alpha-note.md").read_text(encoding="utf-8")
    meta, _ = parse_frontmatter(content)
    assert meta.status == "draft"


def test_note_update_accepts_valid_status_and_stays_indexed(vault_with_notes):
    """The happy path must still write, and the note must survive a resync."""
    result = runner.invoke(
        app, ["note", "update", "alpha-note", "--status", "evergreen", "--json"]
    )
    assert result.exit_code == 0
    assert json.loads(result.output)["ok"] is True

    sync = runner.invoke(app, ["sync", "--json"])
    assert sync.exit_code == 0
    assert not json.loads(sync.output)["data"]["errors"]

    listed = runner.invoke(app, ["note", "list", "--json"])
    rows = json.loads(listed.output)["data"]
    assert [n["status"] for n in rows if n["id"] == "alpha-note"] == ["evergreen"]
