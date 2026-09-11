"""A sources row survives note deletion (ON DELETE SET NULL); fetch_and_save's
duplicate-URL check and its own INSERT must both handle that orphaned row rather
than treat it as a live duplicate forever."""

from __future__ import annotations

from hyperresearch.core.fetcher import fetch_and_save
from hyperresearch.core.sync import compute_sync_plan, execute_sync
from hyperresearch.web.base import WebResult


class _FakeProvider:
    name = "fake"

    def fetch(self, url: str) -> WebResult:
        return WebResult(url=url, title="Fake Title", content="enough content to clear the junk gate. " * 10)


def test_refetch_succeeds_after_the_note_is_deleted(tmp_vault, monkeypatch):
    monkeypatch.setattr(
        "hyperresearch.web.base.get_provider", lambda *a, **k: _FakeProvider()
    )
    url = "https://example.com/refetch-me"

    first = fetch_and_save(tmp_vault, url)
    note_path = tmp_vault.root / first["path"]
    assert note_path.exists()

    note_path.unlink()
    plan = compute_sync_plan(tmp_vault)
    execute_sync(tmp_vault, plan)

    row = tmp_vault.db.execute(
        "SELECT note_id FROM sources WHERE url = ?", (url,)
    ).fetchone()
    assert row is not None and row["note_id"] is None  # orphaned, not deleted

    second = fetch_and_save(tmp_vault, url)  # must not raise ValueError
    assert (tmp_vault.root / second["path"]).exists()
    row = tmp_vault.db.execute(
        "SELECT note_id FROM sources WHERE url = ?", (url,)
    ).fetchone()
    assert row["note_id"] == second["note_id"]  # the upsert re-linked the row


def test_live_duplicate_is_still_rejected(tmp_vault, monkeypatch):
    monkeypatch.setattr(
        "hyperresearch.web.base.get_provider", lambda *a, **k: _FakeProvider()
    )
    url = "https://example.com/still-a-duplicate"

    fetch_and_save(tmp_vault, url)

    try:
        fetch_and_save(tmp_vault, url)
        raise AssertionError("expected ValueError for a URL with a live note")
    except ValueError as exc:
        assert "already fetched" in str(exc)
