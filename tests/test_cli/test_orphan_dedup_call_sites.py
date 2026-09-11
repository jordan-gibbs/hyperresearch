"""The three CLI-side duplicate-url call sites: `fetch`, `fetch-batch`, and
research's `_save_result`. All three read `sources.note_id`, which is NULL
(not row-absent) once the note is deleted (ON DELETE SET NULL), so a bare
`if existing:` treated that as a live duplicate forever.

All three also record the source with `INSERT OR IGNORE`, which is a no-op on
the orphaned row too — so passing the read-side check alone left the new note
with no source record, and in `fetch` tripped the duplicate-url race detector
into deleting the note it had just written. Every test here drives the real
deletion path (the note is actually removed and the vault re-synced) rather
than faking a NULL, and asserts that the row ends up pointing at the new note.
Mirrors tests/test_core/test_fetcher_orphan_dedup.py for fetch_and_save.
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


def _source_row(vault_dir: Path, url: str):
    from hyperresearch.core.vault import Vault

    return Vault.discover(vault_dir).db.execute(
        "SELECT note_id FROM sources WHERE url = ?", (url,)
    ).fetchone()


def _delete_note_for_real(vault_dir: Path, note_id: str, url: str) -> None:
    """`note rm` — the real path: the notes row goes, and ON DELETE SET NULL
    leaves the sources row behind with note_id = NULL."""
    result = runner.invoke(app, ["note", "rm", note_id, "--force", "--json"])
    assert result.exit_code == 0, result.output
    row = _source_row(vault_dir, url)
    assert row is not None and row["note_id"] is None  # orphaned, not deleted


def test_fetch_refetches_after_note_is_deleted(vault_dir: Path, monkeypatch):
    os.chdir(vault_dir)
    monkeypatch.setattr("hyperresearch.web.base.get_provider", lambda *a, **k: _FakeProvider())
    url = "https://example.com/cli-fetch-refetch"

    first = runner.invoke(app, ["fetch", url, "--json"])
    assert first.exit_code == 0
    note_id = json.loads(first.output)["data"]["note_id"]

    _delete_note_for_real(vault_dir, note_id, url)

    second = runner.invoke(app, ["fetch", url, "--json"])
    assert second.exit_code == 0, second.output  # must not report DUPLICATE_URL
    data = json.loads(second.output)["data"]
    # A None here means the race detector mistook the orphan for a lost race
    # and deleted the note it had just written.
    assert data["note_id"] is not None
    assert (vault_dir / data["path"]).exists()
    assert _source_row(vault_dir, url)["note_id"] == data["note_id"]


def test_fetch_with_suggested_by_refetches_rather_than_breadcrumbing_none(
    vault_dir: Path, monkeypatch
):
    """--suggested-by on a live duplicate appends a breadcrumb to the existing
    note; on an orphan there is no note to breadcrumb, so it must re-fetch."""
    os.chdir(vault_dir)
    monkeypatch.setattr("hyperresearch.web.base.get_provider", lambda *a, **k: _FakeProvider())
    url = "https://example.com/cli-fetch-suggested"

    first = runner.invoke(app, ["fetch", url, "--json"])
    assert first.exit_code == 0
    note_id = json.loads(first.output)["data"]["note_id"]

    live = runner.invoke(app, ["fetch", url, "--suggested-by", "some-note", "--json"])
    assert live.exit_code == 0, live.output
    assert json.loads(live.output)["data"]["duplicate"] is True

    _delete_note_for_real(vault_dir, note_id, url)

    second = runner.invoke(app, ["fetch", url, "--suggested-by", "some-note", "--json"])
    assert second.exit_code == 0, second.output
    data = json.loads(second.output)["data"]
    assert "duplicate" not in data
    assert data["note_id"] is not None
    assert _source_row(vault_dir, url)["note_id"] == data["note_id"]


def test_fetch_batch_does_not_skip_a_deleted_note_url(vault_dir: Path, monkeypatch):
    os.chdir(vault_dir)
    monkeypatch.setattr("hyperresearch.web.base.get_provider", lambda *a, **k: _FakeProvider())
    url = "https://example.com/cli-batch-refetch"

    first = runner.invoke(app, ["fetch", url, "--json"])
    assert first.exit_code == 0
    note_id = json.loads(first.output)["data"]["note_id"]
    _delete_note_for_real(vault_dir, note_id, url)

    batch = runner.invoke(app, ["fetch-batch", url, "--json"])
    assert batch.exit_code == 0, batch.output
    data = json.loads(batch.output)["data"]
    assert data["skipped"] == 0  # a skip here means the orphan read as a duplicate
    assert len(data["notes_created"]) == 1
    new_id = data["notes_created"][0]["note_id"]
    assert _source_row(vault_dir, url)["note_id"] == new_id  # row re-linked, not left orphaned


def test_fetch_batch_still_skips_a_live_duplicate(vault_dir: Path, monkeypatch):
    os.chdir(vault_dir)
    monkeypatch.setattr("hyperresearch.web.base.get_provider", lambda *a, **k: _FakeProvider())
    url = "https://example.com/cli-batch-live"

    assert runner.invoke(app, ["fetch", url, "--json"]).exit_code == 0

    batch = runner.invoke(app, ["fetch-batch", url, "--json"])
    assert batch.exit_code == 0, batch.output
    data = json.loads(batch.output)["data"]
    assert data["skipped"] == 1
    assert data["notes_created"] == []


def test_save_result_skips_a_live_duplicate_but_not_a_deleted_note(tmp_vault, monkeypatch):
    from hyperresearch.cli.research import _save_result
    from hyperresearch.core.sync import compute_sync_plan, execute_sync

    monkeypatch.setattr("hyperresearch.web.base.get_provider", lambda *a, **k: _FakeProvider())
    conn = tmp_vault.db
    prov = _FakeProvider()
    url = "https://example.com/research-save-result"

    first = _save_result(tmp_vault, conn, prov, prov.fetch(url), [], None)
    assert first is not None

    # live duplicate: the row still carries a real note_id
    again = _save_result(tmp_vault, conn, prov, prov.fetch(url), [], None)
    assert again is None

    # delete the note for real: unlink + sync drops the notes row, and
    # ON DELETE SET NULL orphans the sources row
    (tmp_vault.root / first["path"]).unlink()
    execute_sync(tmp_vault, compute_sync_plan(tmp_vault))
    row = conn.execute("SELECT note_id FROM sources WHERE url = ?", (url,)).fetchone()
    assert row is not None and row["note_id"] is None

    after_delete = _save_result(tmp_vault, conn, prov, prov.fetch(url), [], None)
    assert after_delete is not None  # must not skip an orphaned row
    assert (tmp_vault.root / after_delete["path"]).exists()
    row = conn.execute("SELECT note_id FROM sources WHERE url = ?", (url,)).fetchone()
    assert row["note_id"] == after_delete["note_id"]  # row re-linked, not left orphaned
