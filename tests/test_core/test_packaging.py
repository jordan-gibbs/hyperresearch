"""Packaging and release metadata regression tests."""

from __future__ import annotations

import tomllib
from pathlib import Path

import hyperresearch


def _pyproject() -> dict:
    root = Path(__file__).resolve().parents[2]
    with (root / "pyproject.toml").open("rb") as f:
        return tomllib.load(f)


def test_runtime_version_matches_project_metadata():
    """The CLI version comes from __version__, so it must track package metadata."""
    project = _pyproject()["project"]
    assert hyperresearch.__version__ == project["version"]


def test_dev_extra_covers_tested_optional_providers():
    """CI installs only .[dev], so dev must include optional providers tested by pytest."""
    optional = _pyproject()["project"]["optional-dependencies"]
    dev_deps = set(optional["dev"])

    assert "exa-py>=2.0.0" in dev_deps
    assert "mcp>=1.24,<2" in dev_deps
    assert optional["mcp"] == ["mcp>=1.24,<2"]
    assert "exa" in optional
    assert "crawl4ai" in optional
    assert "watch" in optional
