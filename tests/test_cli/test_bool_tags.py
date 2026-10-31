"""YAML 1.1 booleans (`no`, `on`, `yes`, `true`) in tags or id are rejected,
not rewritten: the note stays out of the index and its file is left alone.

Numbers and dates are still read as strings, because a year tag or a numeric
id means the same thing either way. `tags: [no, on, yes]` turned into
`['false', 'true', 'true']` does not, so the user gets an error instead of a
silent rewrite of their tags."""

# The hyphenated filename is this fix's unit key; pytest imports it by path.

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.core.frontmatter import parse_frontmatter

runner = CliRunner()


@pytest.fixture
def vault_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    result = runner.invoke(app, ["init", str(tmp_path / "v")])
    assert result.exit_code == 0, result.output
    root = tmp_path / "v"
    monkeypatch.chdir(root)
    return root


@pytest.mark.parametrize("yaml_tags", ["[no, on, yes]", "[ml, true]", "yes", "off"])
def test_boolean_tags_are_rejected(yaml_tags):
    with pytest.raises(ValidationError, match=r"tags"):
        parse_frontmatter(f"---\ntitle: T\ntags: {yaml_tags}\n---\nBody\n")


@pytest.mark.parametrize("yaml_id", ["yes", "no", "true", "off"])
def test_boolean_id_is_rejected(yaml_id):
    with pytest.raises(ValidationError, match=r"\bid\b"):
        parse_frontmatter(f"---\ntitle: T\nid: {yaml_id}\n---\nBody\n")


@pytest.mark.parametrize(
    ("yaml_tags", "expected"),
    [
        ("[2024, 1.5, 2024-01-01]", ["2024", "1.5", "2024-01-01"]),
        ("['yes', 'No']", ["yes", "no"]),
        ("a, b", ["a", "b"]),
        ("", []),
        ("[ml, null, '']", ["ml"]),
    ],
)
def test_numbers_dates_and_quoted_words_still_parse(yaml_tags, expected):
    meta, _ = parse_frontmatter(f"---\ntitle: T\ntags: {yaml_tags}\n---\nBody\n")
    assert meta.tags == expected


@pytest.mark.parametrize(("yaml_id", "expected"), [("2024-01-01", "2024-01-01"), ("'yes'", "yes")])
def test_date_and_quoted_word_ids_still_parse(yaml_id, expected):
    meta, _ = parse_frontmatter(f"---\ntitle: T\nid: {yaml_id}\n---\nBody\n")
    assert meta.id == expected


def test_boolean_tags_and_id_fail_sync_and_no_command_rewrites_them(vault_root):
    notes = vault_root / "research" / "notes"
    bools = notes / "bools.md"
    bools.write_text("---\ntitle: Bools\nid: bools\ntags: [no, on, yes]\n---\n\nbody text\n")
    boolid = notes / "boolid.md"
    boolid.write_text("---\ntitle: Bool id\nid: yes\n---\n\nbody text\n")
    before = {p: p.read_bytes() for p in (bools, boolid)}

    result = runner.invoke(app, ["sync", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)["data"]
    assert data["added"] == 0
    errors = {Path(e["path"]).name: e["error"] for e in data["errors"]}
    assert set(errors) == {"bools.md", "boolid.md"}
    assert "tags" in errors["bools.md"]
    # \b, because every pydantic message says "valid string".
    assert re.search(r"\bid\b", errors["boolid.md"])

    update = runner.invoke(app, ["note", "update", "bools", "--status", "review", "--json"])
    assert json.loads(update.output)["ok"] is False

    repair = runner.invoke(app, ["repair", "--json"])
    assert repair.exit_code == 0, repair.output
    assert json.loads(repair.output)["data"]["sync"]["errors"] == 2

    assert {p: p.read_bytes() for p in before} == before


def test_indexed_note_edited_to_boolean_tags_is_not_rewritten(vault_root):
    # The usual way in: a note sync already indexed is edited to `tags: [no,
    # yes]`. Its old row stays, so `note update` finds the note by id and
    # must still refuse to write the booleans back as 'false' and 'true'.
    note = vault_root / "research" / "notes" / "later.md"
    note.write_text("---\ntitle: Later\nid: later\ntags: [ml]\n---\n\nbody text\n")
    assert runner.invoke(app, ["sync"]).exit_code == 0
    note.write_text("---\ntitle: Later\nid: later\ntags: [no, yes]\n---\n\nbody text\n")
    before = note.read_bytes()

    result = runner.invoke(app, ["sync", "--json"])
    errors = json.loads(result.output)["data"]["errors"]
    assert [Path(e["path"]).name for e in errors] == ["later.md"]

    runner.invoke(app, ["note", "update", "later", "--add-tag", "x", "--json"])
    runner.invoke(app, ["repair", "--json"])

    assert note.read_bytes() == before
