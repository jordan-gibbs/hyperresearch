"""MCP tools must bound how many rows one call returns."""

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
    for title in ("Alpha Note", "Beta Note", "Gamma Note"):
        runner.invoke(app, ["note", "new", title])
    runner.invoke(app, ["sync"])
    mcp._vault = None  # module-global cache; force rediscovery under tmp_path
    yield vault_dir
    mcp._vault = None


def test_search_notes_clamps_limit(mcp_vault, monkeypatch):
    """search_notes returns full bodies, and SQLite reads a negative LIMIT as
    "no limit", so an unchecked value dumps the whole vault in one call."""
    assert len(json.loads(mcp.search_notes(query="note", limit=-1))) == 1

    monkeypatch.setattr(mcp, "_MAX_RESULTS", 2)
    assert len(json.loads(mcp.search_notes(query="note", limit=1000))) == 2
