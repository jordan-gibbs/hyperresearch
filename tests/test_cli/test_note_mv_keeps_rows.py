"""`note mv`, and a plain `mv` followed by `sync`, keep a note's database rows.

The note keeps its id, so its claims, its fetch dedup row and its asset rows
stay with it. Sync used to handle the move as a delete and an add: the claims
and asset rows were cascaded away, the sources row kept the URL with note_id
NULL, and the next fetch of that URL wrote a duplicate note.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.core.vault import Vault
from hyperresearch.web.base import WebResult

runner = CliRunner()

URL = "https://a.example.org/paper"


class _FakeProvider:
    name = "fake"

    def fetch(self, url: str) -> WebResult:
        return WebResult(
            url=url,
            title="Topic",
            content="enough content to clear the junk gate. " * 10,
            screenshot=b"screenshot of " + url.encode(),
        )

    def fetch_many(self, urls):
        return [self.fetch(u) for u in urls]


@pytest.fixture
def vault_dir(tmp_path: Path, monkeypatch) -> Path:
    result = runner.invoke(app, ["init", str(tmp_path / "kb"), "--name", "Mv Keeps Rows"])
    assert result.exit_code == 0
    os.chdir(tmp_path / "kb")
    monkeypatch.setattr("hyperresearch.web.base.get_provider", lambda *a, **k: _FakeProvider())
    return tmp_path / "kb"


def _db(vault_dir: Path):
    return Vault.discover(vault_dir).db


def _claims(note_id: str) -> int:
    result = runner.invoke(app, ["claims", "list", "--note", note_id, "--json"])
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)["count"]


def test_note_mv_keeps_the_notes_claims(vault_dir: Path):
    made = runner.invoke(app, ["note", "new", "Source Paper", "-b", "A paper body.", "--json"])
    assert made.exit_code == 0, made.output
    claims_file = vault_dir / "claims-source-paper.json"
    claims_file.write_text('[{"claim": "Water boils at 100C at sea level"}]', encoding="utf-8")
    ingested = runner.invoke(app, ["claims", "ingest", str(claims_file), "--json"])
    assert json.loads(ingested.stdout)["data"]["ingested"] == 1
    assert _claims("source-paper") == 1

    moved = runner.invoke(app, ["note", "mv", "source-paper", "renamed-paper", "--json"])
    assert moved.exit_code == 0, moved.output
    assert json.loads(moved.stdout)["data"]["new_path"] == "research/notes/renamed-paper.md"

    assert _claims("source-paper") == 1


def test_note_mv_beside_a_refused_copy_keeps_the_note_on_its_own_file(vault_dir: Path):
    """An edited copy of the note, refused as an id collision, does not take
    the moved note's row, text and claims."""
    made = runner.invoke(app, ["note", "new", "Source Paper", "-b", "The original body.", "--json"])
    assert made.exit_code == 0, made.output
    claims_file = vault_dir / "claims-source-paper.json"
    claims_file.write_text('[{"claim": "Water boils at 100C at sea level"}]', encoding="utf-8")
    assert runner.invoke(app, ["claims", "ingest", str(claims_file), "--json"]).exit_code == 0
    original = vault_dir / "research" / "notes" / "source-paper.md"
    copy = vault_dir / "research" / "temp" / "m-copy.md"
    copy.parent.mkdir(parents=True, exist_ok=True)
    copy.write_text(original.read_text(encoding="utf-8").replace("The original", "A copied"), encoding="utf-8")

    moved = runner.invoke(app, ["note", "mv", "source-paper", "research/temp/aa-moved", "--json"])
    assert moved.exit_code == 0, moved.output

    db = _db(vault_dir)
    assert [tuple(r) for r in db.execute("SELECT id, path FROM notes")] == [
        ("source-paper", "research/temp/aa-moved.md")
    ]
    body = db.execute("SELECT body FROM note_content WHERE note_id = 'source-paper'").fetchone()[0]
    assert "The original body." in body
    assert _claims("source-paper") == 1


def _fetch_topic(vault_dir: Path) -> list[tuple]:
    fetched = runner.invoke(app, ["fetch", URL, "--save-assets", "--json"])
    assert fetched.exit_code == 0, fetched.output
    assert json.loads(fetched.stdout)["data"]["note_id"] == "topic"
    assets = sorted(tuple(r) for r in _db(vault_dir).execute("SELECT note_id, filename FROM assets"))
    assert assets and {a[0] for a in assets} == {"topic"}
    return assets


def _assert_still_the_notes(vault_dir: Path, assets: list[tuple], path: str) -> None:
    db = _db(vault_dir)
    assert [tuple(r) for r in db.execute("SELECT id, path FROM notes")] == [("topic", path)]
    assert [tuple(r) for r in db.execute("SELECT url, note_id FROM sources")] == [(URL, "topic")]
    assert sorted(tuple(r) for r in db.execute("SELECT note_id, filename FROM assets")) == assets
    again = runner.invoke(app, ["fetch", URL, "--json"])
    assert again.exit_code == 1, again.output
    payload = json.loads(again.stdout)
    assert payload["error_code"] == "DUPLICATE_URL"
    assert payload["error"] == "URL already fetched as note 'topic'"
    notes = sorted(p.name for p in (vault_dir / "research").rglob("*.md") if p.parent.name != "research")
    assert notes == [Path(path).name]


def test_note_mv_keeps_a_fetched_notes_source_and_asset_rows(vault_dir: Path):
    assets = _fetch_topic(vault_dir)

    moved = runner.invoke(app, ["note", "mv", "topic", "moved", "--json"])
    assert moved.exit_code == 0, moved.output

    _assert_still_the_notes(vault_dir, assets, "research/notes/moved.md")


def test_mv_on_disk_and_sync_keep_a_fetched_notes_source_and_asset_rows(vault_dir: Path):
    """The same move done outside the CLI, into research/temp/."""
    assets = _fetch_topic(vault_dir)
    temp = vault_dir / "research" / "temp"
    temp.mkdir(parents=True, exist_ok=True)
    os.rename(vault_dir / "research" / "notes" / "topic.md", temp / "topic.md")

    synced = runner.invoke(app, ["sync", "--json"])
    assert synced.exit_code == 0, synced.output
    data = json.loads(synced.stdout)["data"]
    assert data["errors"] == []
    assert (data["added"], data["updated"], data["deleted"]) == (0, 1, 0)

    _assert_still_the_notes(vault_dir, assets, "research/temp/topic.md")
