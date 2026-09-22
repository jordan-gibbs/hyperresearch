"""fetch-batch surfaces per-URL failures in JSON output — driven offline with
a fake provider, no network."""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
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


def test_anysearch_batch_preserves_requested_source_and_skips_repeat(tmp_vault, monkeypatch):
    from hyperresearch.core.frontmatter import parse_frontmatter

    requested_url = "https://original.example/article"
    final_url = "https://canonical.example/article"
    calls = []

    def handler(_transport, request):
        assert request.url.path == "/v1/extract"
        calls.append(json.loads(request.content)["url"])
        return httpx.Response(200, json={"code": 0, "data": {
            "url": final_url, "title": "Canonical Article", "content": "Primary source evidence. " * 30,
        }})

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", handler)
    monkeypatch.chdir(tmp_vault.root)
    args = ["fetch-batch", requested_url, "--provider", "anysearch", "--json"]
    first = runner.invoke(app, args)
    assert first.exit_code == 0, first.output
    row = tmp_vault.db.execute("SELECT url, note_id, domain FROM sources").fetchone()
    assert row is not None
    assert row["url"] == requested_url
    assert row["domain"] == "original.example"
    note = tmp_vault.notes_dir / f"{row['note_id']}.md"
    frontmatter, _ = parse_frontmatter(note.read_text(encoding="utf-8"))
    assert frontmatter.source == requested_url

    second = runner.invoke(app, args)
    assert second.exit_code == 0, second.output
    assert json.loads(second.output)["data"]["skipped"] == 1
    assert calls == [requested_url]


def test_anysearch_batch_login_redirect_is_not_saved(tmp_vault, monkeypatch):
    def handler(_transport, _request):
        return httpx.Response(200, json={"code": 0, "data": {
            "url": "https://example.com/login", "title": "Members", "content": "Members area. " * 50,
        }})

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", handler)
    monkeypatch.chdir(tmp_vault.root)
    result = runner.invoke(app, [
        "fetch-batch", "https://example.com/article", "--provider", "anysearch", "--json",
    ])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["data"]["notes_created"] == []
    assert tmp_vault.db.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 0
