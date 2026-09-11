"""The three CLI-side note_id-truthiness call sites flagged on PR #86 review:
`fetch`, `fetch-batch`, and research's `_save_result`. All three read
`sources.note_id`, which is NULL (not row-absent) on a re-fetched, deleted
note (ON DELETE SET NULL), so a bare `if existing:` treats that as a live
duplicate forever. Mirrors tests/test_core/test_fetcher_orphan_dedup.py,
which covers the same bug in fetch_and_save itself.
"""

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
    name = "fake"

    def fetch(self, url: str) -> WebResult:
        return WebResult(url=url, title="Fake Title", content="enough content to clear the junk gate. " * 10)


@pytest.fixture
def vault_dir(tmp_path: Path) -> Path:
    result = runner.invoke(app, ["init", str(tmp_path / "kb"), "--name", "Orphan Dedup Test"])
    assert result.exit_code == 0
    return tmp_path / "kb"


def _orphan_the_note(vault_dir: Path, note_id: str) -> None:
    """Simulate `note rm`: null out sources.note_id without deleting the row,
    exactly what ON DELETE SET NULL leaves behind."""
    from hyperresearch.core.vault import Vault

    vault = Vault.discover(vault_dir)
    vault.db.execute("UPDATE sources SET note_id = NULL WHERE note_id = ?", (note_id,))
    vault.db.commit()


def test_fetch_refetches_after_note_is_orphaned(vault_dir: Path, monkeypatch):
    os.chdir(vault_dir)
    monkeypatch.setattr("hyperresearch.web.base.get_provider", lambda *a, **k: _FakeProvider())
    url = "https://example.com/cli-fetch-refetch"

    first = runner.invoke(app, ["fetch", url, "--json"])
    assert first.exit_code == 0
    note_id = json.loads(first.output)["data"]["note_id"]

    _orphan_the_note(vault_dir, note_id)

    second = runner.invoke(app, ["fetch", url, "--json"])
    assert second.exit_code == 0, second.output  # must not report DUPLICATE_URL
    assert json.loads(second.output)["data"]["note_id"] != note_id


def test_fetch_batch_does_not_skip_an_orphaned_url(vault_dir: Path, monkeypatch):
    os.chdir(vault_dir)
    monkeypatch.setattr("hyperresearch.web.base.get_provider", lambda *a, **k: _FakeProvider())
    url = "https://example.com/cli-batch-refetch"

    first = runner.invoke(app, ["fetch", url, "--json"])
    assert first.exit_code == 0
    note_id = json.loads(first.output)["data"]["note_id"]
    _orphan_the_note(vault_dir, note_id)

    batch = runner.invoke(app, ["fetch-batch", url, "--json"])
    assert batch.exit_code == 0
    data = json.loads(batch.output)["data"]
    assert data["skipped"] == 0  # a live skip here means the orphan read as a duplicate
    assert len(data["notes_created"]) == 1


def test_save_result_skips_a_live_duplicate_but_not_an_orphan(tmp_vault, monkeypatch):
    from hyperresearch.cli.research import _save_result

    monkeypatch.setattr("hyperresearch.web.base.get_provider", lambda *a, **k: _FakeProvider())
    conn = tmp_vault.db
    prov = _FakeProvider()
    url = "https://example.com/research-save-result"

    first = _save_result(tmp_vault, conn, prov, prov.fetch(url), [], None)
    assert first is not None

    # live duplicate: the row still carries a real note_id
    again = _save_result(tmp_vault, conn, prov, prov.fetch(url), [], None)
    assert again is None

    conn.execute("UPDATE sources SET note_id = NULL WHERE note_id = ?", (first["note_id"],))
    conn.commit()

    after_orphan = _save_result(tmp_vault, conn, prov, prov.fetch(url), [], None)
    assert after_orphan is not None  # must not skip an orphaned row
