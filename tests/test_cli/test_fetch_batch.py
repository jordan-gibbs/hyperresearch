"""fetch-batch surfaces per-URL failures in JSON output — driven offline with
a fake provider, no network."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.web.base import WebResult

runner = CliRunner()


class _FakeProvider:
    """fetch_many raises to force the batch-fallback lane; fetch then succeeds
    for one URL and fails for the other."""

    name = "fake"

    def fetch_many(self, urls):
        raise RuntimeError("batch boom")

    def fetch(self, url):
        if "bad" in url:
            raise RuntimeError("per-url boom")
        return WebResult(url=url, title="Good Page", content="hello world from the good page")


@pytest.fixture
def vault_dir(tmp_path: Path) -> Path:
    result = runner.invoke(app, ["init", str(tmp_path / "kb"), "--name", "Batch Test"])
    assert result.exit_code == 0
    return tmp_path / "kb"


def test_fetch_batch_reports_failed_urls(vault_dir: Path, monkeypatch):
    """A URL that fails inside the batch-fallback lane must appear in
    failed_urls with its phase — if it silently vanishes, a caller sees a
    short success list and never learns a source was lost."""
    os.chdir(vault_dir)
    monkeypatch.setattr("hyperresearch.web.base.get_provider", lambda *a, **k: _FakeProvider())

    result = runner.invoke(
        app,
        ["fetch-batch", "http://good.example/ok", "http://bad.example/nope", "--json"],
    )
    assert result.exit_code == 0
    data = json.loads(result.output)

    assert data["ok"] is True
    assert data["data"]["total_fetched"] == 1  # the good URL became a note

    failed = data["data"]["failed_urls"]
    assert len(failed) == 1
    assert failed[0]["url"] == "http://bad.example/nope"
    assert failed[0]["phase"] == "batch-fallback"
    assert "per-url boom" in failed[0]["error"]
