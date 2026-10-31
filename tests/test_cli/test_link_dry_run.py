"""`link --dry-run` must not write, and an empty --tag/--note selection must link nothing.

--dry-run only skipped the follow-up sync: auto_link had no dry-run mode, so
every note it matched was rewritten with a `## Related` section. And the tag
lookup's empty result reached auto_link as `[]`, which it read as "no filter",
so `link --auto --tag <unused tag>` linked every note in the vault.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.core.linker import auto_link
from hyperresearch.core.vault import Vault

runner = CliRunner()

SURVEY = Path("research/notes/survey.md")
EXPECTED_LINKS = {"survey": ["attention-is-all-you-need"]}


@pytest.fixture
def vault_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A vault where `survey` mentions the title of `attention-is-all-you-need`,
    so a real `link --auto` adds exactly one link."""
    result = runner.invoke(app, ["init", str(tmp_path / "v"), "--name", "Link Test"])
    assert result.exit_code == 0, result.output
    root = tmp_path / "v"
    monkeypatch.chdir(root)
    for title, tag, body in [
        ("Attention Is All You Need", "ml", "The transformer paper."),
        ("Survey", "physics", "The paper Attention Is All You Need introduced transformers."),
    ]:
        result = runner.invoke(app, ["note", "new", title, "-t", tag, "-b", body, "--json"])
        assert result.exit_code == 0, result.output
    return root


def _snapshot(root: Path) -> dict[str, object]:
    """Content hash and mtime of every file in the vault, and the database's rows.

    The database is compared by its rows, not its bytes: in-process, an
    earlier command's still-open connection leaves WAL frames that the next
    connection checkpoints, which rewrites hyperresearch.db and its -shm
    without changing a row.
    """
    db_path = Vault(root).db_path
    snap: dict[str, object] = {
        p.relative_to(root).as_posix(): (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
        for p in sorted(root.rglob("*"))
        if p.is_file() and not p.name.startswith(db_path.name)
    }
    conn = sqlite3.connect(db_path)
    try:
        snap["<database rows>"] = list(conn.iterdump())
    finally:
        conn.close()
    return snap


def _link_json(*args: str) -> dict:
    result = runner.invoke(app, ["link", *args, "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    return payload["data"]


def test_dry_run_json_changes_no_file(vault_root: Path):
    before = _snapshot(vault_root)

    data = _link_json("--auto", "--dry-run")

    assert _snapshot(vault_root) == before
    assert "[[attention-is-all-you-need]]" not in (vault_root / SURVEY).read_text(encoding="utf-8")
    assert data["links_added"] == EXPECTED_LINKS
    assert data["notes_modified"] == 1
    assert data["total_links"] == 1
    assert data["dry_run"] is True


def test_dry_run_human_changes_no_file(vault_root: Path):
    before = _snapshot(vault_root)

    result = runner.invoke(app, ["link", "--auto", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert _snapshot(vault_root) == before
    assert "survey → attention-is-all-you-need" in result.output
    assert "would be added" in result.output
    assert "No new links found" not in result.output


def test_dry_run_with_note_selection_changes_no_file(vault_root: Path):
    """The README's documented preview: `link --note <id> --dry-run -j`."""
    before = _snapshot(vault_root)

    data = _link_json("--note", "survey", "--dry-run")

    assert _snapshot(vault_root) == before
    assert data["links_added"] == EXPECTED_LINKS


def test_dry_run_reports_exactly_what_a_real_run_adds(vault_root: Path):
    preview = _link_json("--auto", "--dry-run")
    real = _link_json("--auto")

    assert preview.keys() == real.keys()
    assert real["dry_run"] is False
    assert {k: v for k, v in preview.items() if k != "dry_run"} == {
        k: v for k, v in real.items() if k != "dry_run"
    }
    survey = (vault_root / SURVEY).read_text(encoding="utf-8")
    assert survey.rstrip().endswith("## Related\n\n- [[attention-is-all-you-need]]")
    # The real run's links are now in the files, so a second preview finds none.
    assert _link_json("--auto", "--dry-run")["links_added"] == {}


@pytest.mark.parametrize("auto", [["--auto"], []], ids=["auto", "no-auto"])
def test_tag_matching_no_notes_links_nothing(vault_root: Path, auto: list[str]):
    before = _snapshot(vault_root)

    result = runner.invoke(app, ["link", *auto, "--tag", "no-such-tag"])

    assert result.exit_code == 0, result.output
    assert _snapshot(vault_root) == before
    assert "No notes match --tag no-such-tag" in result.output
    assert "links added" not in result.output
    assert "Use --auto" not in result.output


@pytest.mark.parametrize("auto", [["--auto"], []], ids=["auto", "no-auto"])
def test_tag_matching_no_notes_links_nothing_json(vault_root: Path, auto: list[str]):
    before = _snapshot(vault_root)

    data = _link_json(*auto, "--tag", "no-such-tag")

    assert _snapshot(vault_root) == before
    assert data["links_added"] == {}
    assert data["notes_modified"] == 0
    assert data["total_links"] == 0
    assert "No notes match --tag no-such-tag" in data["message"]


def test_note_matching_no_notes_links_nothing(vault_root: Path):
    before = _snapshot(vault_root)

    data = _link_json("--auto", "--note", "no-such-note")

    assert _snapshot(vault_root) == before
    assert data["links_added"] == {}
    assert "No notes match --note no-such-note" in data["message"]


def test_tag_selection_still_links_its_notes(vault_root: Path):
    """The fix narrows only the empty case: a tag that has notes links them."""
    assert _link_json("--tag", "physics")["links_added"] == EXPECTED_LINKS
    assert "[[attention-is-all-you-need]]" in (vault_root / SURVEY).read_text(encoding="utf-8")


def test_auto_link_empty_selection_processes_no_note(vault_root: Path):
    before = _snapshot(vault_root)
    with Vault.discover(vault_root) as vault:
        assert auto_link(vault, []) == {}
    assert _snapshot(vault_root) == before


def test_auto_link_dry_run_writes_nothing(vault_root: Path):
    """fetch-batch and research call auto_link directly; their default still writes."""
    before = _snapshot(vault_root)
    with Vault.discover(vault_root) as vault:
        assert auto_link(vault, None, dry_run=True) == EXPECTED_LINKS
        assert _snapshot(vault_root) == before
        assert auto_link(vault, ["survey"]) == EXPECTED_LINKS
    assert "[[attention-is-all-you-need]]" in (vault_root / SURVEY).read_text(encoding="utf-8")
