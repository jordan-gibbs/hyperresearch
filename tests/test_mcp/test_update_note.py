"""Tests for the MCP server's update_note tool."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app

mcp = pytest.importorskip("hyperresearch.mcp.server")

runner = CliRunner()


@pytest.fixture
def mcp_vault(tmp_path: Path) -> Path:
    vault_dir = tmp_path / "kb"
    runner.invoke(app, ["init", str(vault_dir)])
    os.chdir(vault_dir)
    runner.invoke(app, ["note", "new", "Alpha Note"])
    runner.invoke(app, ["sync"])
    mcp._vault = None  # module-global cache; force rediscovery under tmp_path
    yield vault_dir
    mcp._vault = None


def test_update_note_rejects_invalid_status(mcp_vault):
    """update_note must validate status before assigning it to NoteMeta.

    Regression test: NoteMeta has no validate_assignment, so
    `meta.status = status` accepted any string and wrote it to frontmatter.
    parse_frontmatter then rejected the file, and sync dropped the note from
    the index permanently while reporting the write as successful.
    """
    out = json.loads(mcp.update_note("alpha-note", status="evergreeen"))
    assert out["ok"] is False
    assert out["error_code"] == "INVALID_STATUS"
    assert "evergreen" in out["error"]

    from hyperresearch.core.frontmatter import parse_frontmatter

    content = (mcp_vault / "research/notes/alpha-note.md").read_text(encoding="utf-8")
    meta, _ = parse_frontmatter(content)
    assert meta.status == "draft"


def test_update_note_accepts_valid_status(mcp_vault):
    out = json.loads(mcp.update_note("alpha-note", status="evergreen"))
    assert out["ok"] is True

    from hyperresearch.core.frontmatter import parse_frontmatter

    content = (mcp_vault / "research/notes/alpha-note.md").read_text(encoding="utf-8")
    meta, _ = parse_frontmatter(content)
    assert meta.status == "evergreen"
