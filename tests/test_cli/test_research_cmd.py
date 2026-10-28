"""`research` command robustness — driven offline with a fake provider, no network."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.web.base import WebResult

runner = CliRunner()

_BODY = "A long enough article body about the research topic. " * 40


class _FakeProvider:
    name = "fake"

    def __init__(self, results):
        self._results = results

    def search(self, query, max_results=5):
        return self._results

    def fetch(self, url):
        raise RuntimeError("no fetch in tests")


@pytest.fixture
def vault_dir(tmp_path: Path) -> Path:
    result = runner.invoke(app, ["init", str(tmp_path / "kb"), "--name", "Research Test"])
    assert result.exit_code == 0
    return tmp_path / "kb"


def _use_provider(monkeypatch, results) -> list[dict]:
    calls: list[dict] = []

    def fake_get_provider(*args, **kwargs):
        calls.append(kwargs)
        return _FakeProvider(results)

    monkeypatch.setattr("hyperresearch.web.base.get_provider", fake_get_provider)
    return calls


def test_research_all_results_skipped_does_not_crash(vault_dir: Path, monkeypatch):
    """Every search result filtered out (here: login walls) used to hit
    created_notes[-1] and raise IndexError in the human-readable summary."""
    os.chdir(vault_dir)
    _use_provider(
        monkeypatch,
        [WebResult(url="https://example.com/login", title="Sign in", content="Please log in")],
    )

    result = runner.invoke(app, ["research", "some topic"])
    assert result.exit_code == 0, result.output
    assert result.exception is None
    assert "No notes created" in result.output

    result = runner.invoke(app, ["research", "some topic", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["ok"] is True
    assert data["data"]["notes_created"] == []


def test_research_login_wall_honours_vault_junk_config(vault_dir: Path, monkeypatch):
    """A vault-specific [junk] extra_login_signals entry must make research skip
    the page, as fetch and fetch-batch already do."""
    os.chdir(vault_dir)
    cfg = vault_dir / ".hyperresearch" / "config.toml"
    existing = cfg.read_text(encoding="utf-8")
    assert "extra_login_signals = []" in existing
    cfg.write_text(
        existing.replace("extra_login_signals = []", 'extra_login_signals = ["mitgliedsbereich"]'),
        encoding="utf-8",
    )
    _use_provider(
        monkeypatch,
        [WebResult(url="https://example.de/artikel", title="Mitgliedsbereich", content=_BODY)],
    )

    result = runner.invoke(app, ["research", "some topic", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["data"]["notes_created"] == []


def test_research_threads_fetch_settings_and_gates(vault_dir: Path, monkeypatch):
    """research must build its provider with the vault's [fetch] settings and
    [junk] gates (TLS verification, SSRF allowlist, ...), like fetch does."""
    os.chdir(vault_dir)
    calls = _use_provider(monkeypatch, [])

    result = runner.invoke(app, ["research", "some topic", "--json"])
    assert result.exit_code == 0, result.output

    from hyperresearch.core.vault import Vault

    vault = Vault.discover()
    assert len(calls) == 1
    assert calls[0]["settings"] == vault.config.fetch
    assert calls[0]["gates"] == vault.config.junk
