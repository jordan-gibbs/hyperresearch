"""A new note must not be written under an id another file already holds.

`note mv` keeps a note's id while renaming its file, so after
`note mv topic topic-moved` the filename `topic.md` is free on disk but the id
`topic` is not. write_note only checked for an existing FILE, so the next note
titled "Topic" was written to `topic.md` and sync refused it as an id collision.
Each fetch path then recorded the URL (and its assets) under `note_id = "topic"`,
the moved note: the duplicate-url check answered "already fetched" with that
note from then on, and the fetched text was never indexed. `note new`, MCP
`create_note` and the research map-of-content reported the moved note's id for
a file that was never indexed.

The callers now pass the indexed ids to write_note, and the fetch paths, after
sync, record nothing unless the notes row for the id is the new file (the race
in which another file takes the id between write_note and sync). The fetch
paths are covered at all five call sites: `fetch`, `fetch-batch`, research's
`_save_result`, `escalation ingest` and `fetch_and_save`; the other callers
below them.
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

FIRST_URL = "https://a.example.org/x"
URL = "https://b.example.org/y"


class _FakeProvider:
    """Every page has the same title, so every note's id starts as `topic`."""

    name = "fake"

    def fetch(self, url: str) -> WebResult:
        return WebResult(
            url=url,
            title="Topic",
            content="enough content to clear the junk gate. " * 10,
            screenshot=b"screenshot of " + url.encode(),
            raw_bytes=b"%PDF-1.4 stand-in for " + url.encode(),
            raw_content_type="application/pdf",
        )

    def fetch_many(self, urls):
        return [self.fetch(u) for u in urls]


@pytest.fixture
def vault_dir(tmp_path: Path, monkeypatch) -> Path:
    result = runner.invoke(app, ["init", str(tmp_path / "kb"), "--name", "Id Taken Test"])
    assert result.exit_code == 0
    os.chdir(tmp_path / "kb")
    monkeypatch.setattr("hyperresearch.web.base.get_provider", lambda *a, **k: _FakeProvider())
    return tmp_path / "kb"


@pytest.fixture
def moved_topic(vault_dir: Path) -> Path:
    """Fetch a page titled "Topic", then `note mv` it: the id `topic` stays
    taken while the filename `topic.md` is free again."""
    first = runner.invoke(app, ["fetch", FIRST_URL, "--json"])
    assert first.exit_code == 0, first.output
    assert json.loads(first.stdout)["data"]["note_id"] == "topic"
    moved = runner.invoke(app, ["note", "mv", "topic", "topic-moved", "--json"])
    assert moved.exit_code == 0, moved.output
    assert not (vault_dir / "research" / "notes" / "topic.md").exists()
    assert _note_path(vault_dir, "topic") == "research/notes/topic-moved.md"
    return vault_dir


@pytest.fixture
def id_taken_before_sync(monkeypatch):
    """Force the race: right after write_note returns, another file claiming
    the new note's id is written and indexed (alone: the new note stays
    unindexed), before the caller's own sync."""
    import hyperresearch.core.note as note_mod
    from hyperresearch.core.sync import SyncPlan, execute_sync

    real_write_note = note_mod.write_note
    raced: list[Path] = []

    def write_note_then_race(notes_dir, *args, **kwargs):
        path = real_write_note(notes_dir, *args, **kwargs)
        if not raced:
            rival = notes_dir / "rival.md"
            rival.write_text(
                f"---\ntitle: Rival\nid: {path.stem}\n---\n\nRival body.\n", encoding="utf-8"
            )
            with Vault.discover(notes_dir) as other:
                execute_sync(other, SyncPlan(to_add=[rival]))
            raced.append(path)
        return path

    monkeypatch.setattr(note_mod, "write_note", write_note_then_race)
    return raced


def _db(vault_dir: Path):
    return Vault.discover(vault_dir).db


def _note_path(vault_dir: Path, note_id: str) -> str | None:
    row = _db(vault_dir).execute("SELECT path FROM notes WHERE id = ?", (note_id,)).fetchone()
    return row["path"] if row else None


def _source_note_id(vault_dir: Path, url: str):
    row = _db(vault_dir).execute("SELECT note_id FROM sources WHERE url = ?", (url,)).fetchone()
    return row["note_id"] if row else "<no row>"


def _assert_recorded_under_own_note(vault_dir: Path, note_id: str) -> None:
    """The url's source row names the new note, and that id's notes row is the
    new note's own file rather than the moved one."""
    assert note_id != "topic"
    assert _note_path(vault_dir, note_id) == f"research/notes/{note_id}.md"
    assert _source_note_id(vault_dir, URL) == note_id
    assert _note_path(vault_dir, "topic") == "research/notes/topic-moved.md"
    sync = runner.invoke(app, ["sync", "--json"])
    assert json.loads(sync.stdout)["data"]["errors"] == []  # no file left unindexed


def _assert_nothing_recorded(vault_dir: Path, raced: list[Path]) -> None:
    """Refused by the guard: no source row, no assets, the stray file removed,
    and the id still belongs to the file that took it."""
    assert raced, "the race fixture never ran"
    stray = raced[0]
    assert not stray.exists()
    assert _source_note_id(vault_dir, URL) == "<no row>"
    assert _note_path(vault_dir, stray.stem) == "research/notes/rival.md"
    assets = _db(vault_dir).execute("SELECT COUNT(*) FROM assets").fetchone()[0]
    assert assets == 0


# --- the ordinary case: an id held by a moved note is skipped ---------------


def test_fetch_after_note_mv_records_the_new_note(moved_topic: Path):
    result = runner.invoke(app, ["fetch", URL, "--save-assets", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)["data"]
    _assert_recorded_under_own_note(moved_topic, data["note_id"])

    asset_ids = {r["note_id"] for r in _db(moved_topic).execute("SELECT note_id FROM assets")}
    assert asset_ids == {data["note_id"]}  # the screenshot is not filed under the moved note

    again = runner.invoke(app, ["fetch", URL, "--json"])
    assert again.exit_code == 1
    assert json.loads(again.stdout)["error"] == f"URL already fetched as note '{data['note_id']}'"


def test_fetch_batch_after_note_mv_records_the_new_note(moved_topic: Path):
    result = runner.invoke(app, ["fetch-batch", URL, "--json"])
    assert result.exit_code == 0, result.output
    created = json.loads(result.stdout)["data"]["notes_created"]
    assert len(created) == 1
    _assert_recorded_under_own_note(moved_topic, created[0]["note_id"])


def test_save_result_after_note_mv_records_the_new_note(moved_topic: Path):
    from hyperresearch.cli.research import _save_result

    vault = Vault.discover(moved_topic)
    prov = _FakeProvider()
    data = _save_result(vault, vault.db, prov, prov.fetch(URL), [], None)
    assert data is not None
    _assert_recorded_under_own_note(moved_topic, data["note_id"])


def _claimed_escalation_item(vault_dir: Path) -> tuple[int, Path]:
    added = runner.invoke(
        app, ["escalation", "add", URL, "--reason", "interactive_needed", "--json"]
    )
    assert added.exit_code == 0, added.output
    item_id = json.loads(added.stdout)["data"]["id"]
    assert runner.invoke(app, ["escalation", "claim", "--json"]).exit_code == 0
    body = vault_dir / "scratch-body.md"
    body.write_text("Extracted page content with plenty of real words in it.", encoding="utf-8")
    return item_id, body


def test_escalation_ingest_after_note_mv_records_the_new_note(moved_topic: Path):
    item_id, body = _claimed_escalation_item(moved_topic)
    result = runner.invoke(
        app,
        ["escalation", "ingest", str(item_id), "--title", "Topic", "--body-file", str(body), "--json"],
    )
    assert result.exit_code == 0, result.output
    _assert_recorded_under_own_note(moved_topic, json.loads(result.stdout)["data"]["note_id"])


def test_fetch_and_save_after_note_mv_records_the_new_note(moved_topic: Path):
    from hyperresearch.core.fetcher import fetch_and_save

    data = fetch_and_save(Vault.discover(moved_topic), URL)
    _assert_recorded_under_own_note(moved_topic, data["note_id"])


# --- the race: another file takes the id between write_note and sync --------


def test_fetch_records_nothing_when_the_id_is_taken_before_sync(
    vault_dir: Path, id_taken_before_sync
):
    result = runner.invoke(app, ["fetch", URL, "--save-assets", "--json"])
    assert result.exit_code == 1, result.output
    payload = json.loads(result.stdout)
    assert payload["error_code"] == "NOTE_NOT_INDEXED"
    assert "research/notes/topic.md" in payload["error"]  # the refused file
    assert "research/notes/rival.md" in payload["error"]  # the id's owner
    _assert_nothing_recorded(vault_dir, id_taken_before_sync)
    assert not (vault_dir / "research" / "raw" / "topic.pdf").exists()  # its raw artifact too

    retry = runner.invoke(app, ["fetch", URL, "--json"])  # the race does not repeat
    assert retry.exit_code == 0, retry.output
    data = json.loads(retry.stdout)["data"]
    assert _source_note_id(vault_dir, URL) == data["note_id"] != "topic"
    assert data["raw_file"] == f"raw/{data['note_id']}.pdf"


def test_fetch_batch_records_nothing_when_the_id_is_taken_before_sync(
    vault_dir: Path, id_taken_before_sync
):
    result = runner.invoke(app, ["fetch-batch", URL, "--save-assets", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)["data"]
    assert data["notes_created"] == []
    assert [(f["url"], f["phase"]) for f in data["failed_urls"]] == [(URL, "index")]
    assert "research/notes/rival.md" in data["failed_urls"][0]["error"]
    _assert_nothing_recorded(vault_dir, id_taken_before_sync)


def test_save_result_records_nothing_when_the_id_is_taken_before_sync(
    vault_dir: Path, id_taken_before_sync
):
    from hyperresearch.cli.research import _save_result

    vault = Vault.discover(vault_dir)
    prov = _FakeProvider()
    assert _save_result(vault, vault.db, prov, prov.fetch(URL), [], None) is None
    _assert_nothing_recorded(vault_dir, id_taken_before_sync)


def test_escalation_ingest_records_nothing_when_the_id_is_taken_before_sync(
    vault_dir: Path, id_taken_before_sync
):
    from hyperresearch.core.escalation import list_items

    item_id, body = _claimed_escalation_item(vault_dir)
    result = runner.invoke(
        app,
        ["escalation", "ingest", str(item_id), "--title", "Topic", "--body-file", str(body), "--json"],
    )
    assert result.exit_code == 1, result.output
    assert json.loads(result.stdout)["error_code"] == "NOTE_NOT_INDEXED"
    _assert_nothing_recorded(vault_dir, id_taken_before_sync)
    assert list_items(_db(vault_dir))[0]["status"] == "in_progress"  # still claimed

    again = runner.invoke(
        app,
        ["escalation", "ingest", str(item_id), "--title", "Topic", "--body-file", str(body), "--json"],
    )
    assert again.exit_code == 0, again.output
    assert _source_note_id(vault_dir, URL) == json.loads(again.stdout)["data"]["note_id"] != "topic"


def test_fetch_and_save_records_nothing_when_the_id_is_taken_before_sync(
    vault_dir: Path, id_taken_before_sync
):
    from hyperresearch.core.fetcher import fetch_and_save

    with pytest.raises(RuntimeError, match="was not indexed"):
        fetch_and_save(Vault.discover(vault_dir), URL, save_assets=True)
    _assert_nothing_recorded(vault_dir, id_taken_before_sync)
    assert not (vault_dir / "research" / "raw" / "topic.pdf").exists()


# --- the other callers that mint a new note under a derived id ---------------


def _sync_errors() -> list:
    return json.loads(runner.invoke(app, ["sync", "--json"]).stdout)["data"]["errors"]


@pytest.fixture
def moved_note(vault_dir: Path) -> Path:
    """`note new` "Topic", then `note mv` it to topic-moved.md."""
    assert runner.invoke(app, ["note", "new", "Topic", "--json"]).exit_code == 0
    moved = runner.invoke(app, ["note", "mv", "topic", "topic-moved", "--json"])
    assert moved.exit_code == 0, moved.output
    return vault_dir


def _assert_new_note_indexed(vault_dir: Path, note_id: str) -> None:
    assert note_id != "topic"
    assert _note_path(vault_dir, note_id) == f"research/notes/{note_id}.md"
    assert _note_path(vault_dir, "topic") == "research/notes/topic-moved.md"
    assert _sync_errors() == []


def test_note_new_after_note_mv_gets_a_free_id(moved_note: Path):
    result = runner.invoke(app, ["note", "new", "Topic", "--json"])
    assert result.exit_code == 0, result.output
    _assert_new_note_indexed(moved_note, json.loads(result.stdout)["data"]["id"])


def test_mcp_create_note_after_note_mv_gets_a_free_id(moved_note: Path):
    mcp = pytest.importorskip("hyperresearch.mcp.server")
    mcp._vault = None  # module-global cache; force rediscovery under tmp_path
    try:
        out = json.loads(mcp.create_note("Topic", "Body of the new note."))
    finally:
        mcp._vault = None
    assert out["ok"] is True
    _assert_new_note_indexed(moved_note, out["data"]["note_id"])


@pytest.fixture
def broken_ref_on_a_taken_slug(vault_dir: Path) -> Path:
    """[[foo bar]] is broken (the resolver matches ids, aliases and titles,
    never slugs), but its slug `foo-bar` is another note's id."""
    notes = vault_dir / "research" / "notes"
    (notes / "foo-bar.md").write_text(
        "---\ntitle: Something Else\nid: foo-bar\n---\n\nBody.\n", encoding="utf-8"
    )
    (notes / "linker.md").write_text(
        "---\ntitle: Linker\nid: linker\n---\n\nSee [[foo bar]].\n", encoding="utf-8"
    )
    assert _sync_errors() == []
    assert _link_target(vault_dir, "foo bar") is None
    return vault_dir


def _link_target(vault_dir: Path, ref: str):
    row = _db(vault_dir).execute(
        "SELECT target_id FROM links WHERE target_ref = ?", (ref,)
    ).fetchone()
    return row["target_id"]


def _assert_stub_resolves(vault_dir: Path) -> None:
    stub_id = _link_target(vault_dir, "foo bar")
    assert stub_id not in (None, "foo-bar")
    assert _note_path(vault_dir, stub_id) == f"research/temp/{stub_id}.md"
    assert _note_path(vault_dir, "foo-bar") == "research/notes/foo-bar.md"
    assert _sync_errors() == []


def test_graph_stub_for_a_broken_ref_whose_slug_is_taken(broken_ref_on_a_taken_slug: Path):
    result = runner.invoke(app, ["graph", "stub", "--json"])
    assert result.exit_code == 0, result.output
    _assert_stub_resolves(broken_ref_on_a_taken_slug)


def test_repair_stub_for_a_broken_ref_whose_slug_is_taken(broken_ref_on_a_taken_slug: Path):
    result = runner.invoke(app, ["repair", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["data"]["stubs"] == 1
    _assert_stub_resolves(broken_ref_on_a_taken_slug)


class _SearchProvider(_FakeProvider):
    """Two fresh results per search, so a second `research` run creates notes
    (and therefore a map-of-content) again."""

    searches = 0

    def search(self, topic: str, max_results: int = 5):
        type(self).searches += 1
        n = self.searches
        return [
            WebResult(url=f"https://s{n}.example.org/{i}", title=f"Result {n} {i}",
                      content="enough content to clear the junk gate. " * 10)
            for i in range(2)
        ]


def test_research_map_of_content_after_note_mv_gets_a_free_id(vault_dir: Path, monkeypatch):
    monkeypatch.setattr("hyperresearch.web.base.get_provider", lambda *a, **k: _SearchProvider())
    assert runner.invoke(app, ["research", "topic", "--json"]).exit_code == 0
    moved = runner.invoke(app, ["note", "mv", "research-topic", "moc-moved", "--json"])
    assert moved.exit_code == 0, moved.output

    result = runner.invoke(app, ["research", "topic", "--json"])
    assert result.exit_code == 0, result.output
    created = json.loads(result.stdout)["data"]["notes_created"]
    moc = [n for n in created if n.get("type") == "moc"]
    assert len(moc) == 1
    moc_id = moc[0]["note_id"]
    assert moc_id != "research-topic"  # the moved map-of-content keeps that id
    assert _note_path(vault_dir, moc_id) == f"research/notes/{moc_id}.md"
    assert Path(moc[0]["path"]).as_posix() == f"research/notes/{moc_id}.md"  # OS separators
    assert _note_path(vault_dir, "research-topic") == "research/notes/moc-moved.md"
    assert _sync_errors() == []
