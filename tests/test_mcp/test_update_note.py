"""Tests for the MCP server's update_note tool, and for lint_vault on the notes it refuses."""

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


def test_update_note_refuses_the_frontmatterless_final_report(mcp_vault):
    """The final report has no YAML header by pipeline design and is indexed
    from derived metadata; update_note must not serialize a header into it."""
    report = mcp_vault / "research/notes/final_report_mcp-a1b2c3.md"
    report.write_text("# Report Title\n\nThe report body.\n", encoding="utf-8")
    runner.invoke(app, ["sync"])
    before = report.read_bytes()

    out = json.loads(mcp.update_note("final_report_mcp-a1b2c3", add_tags="x"))
    assert out["ok"] is False
    assert out["error_code"] == "REPORT_WITHOUT_FRONTMATTER"
    assert report.read_bytes() == before


def test_lint_vault_does_not_ask_the_report_for_a_summary(mcp_vault):
    """The report has no header to hold a summary, and update_note refuses to
    add one, so MCP lint must not ask for it (the CLI's rule skips it too)."""
    report = mcp_vault / "research/notes/final_report_mcp-a1b2c3.md"
    report.write_text("# Report Title\n\nThe report body.\n", encoding="utf-8")
    runner.invoke(app, ["sync"])

    out = json.loads(mcp.lint_vault("missing-summary"))
    ids = [i["note_id"] for i in out["issues"]]
    assert "final_report_mcp-a1b2c3" not in ids
    assert "alpha-note" in ids  # the rule still runs
