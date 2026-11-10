"""`hyperresearch import` must not destroy notes or misreport what it indexed.

import copied every source file onto research/notes/<relative path> with
shutil.copy2: a note already at that path was overwritten with exit 0 and
ok:true, and importing research/notes into itself crashed with SameFileError.
It reported every copied file as imported, though sync drops a file without
frontmatter and refuses one whose id another note holds. And --prefix was
joined verbatim, so `--prefix ../../..` wrote outside the vault.
"""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.core.vault import Vault

runner = CliRunner()

ORIGINAL = "ORIGINAL precious content"


@pytest.fixture
def vault_dir(tmp_path: Path, monkeypatch) -> Path:
    vault_dir = tmp_path / "kb"
    assert runner.invoke(app, ["init", str(vault_dir)]).exit_code == 0
    monkeypatch.chdir(vault_dir)
    created = runner.invoke(app, ["note", "new", "Foo", "-b", ORIGINAL, "--json"])
    assert created.exit_code == 0, created.output
    assert json.loads(created.output)["data"]["path"] == "research/notes/foo.md"
    return vault_dir


@pytest.fixture
def source(tmp_path: Path) -> Path:
    src = tmp_path / "src"
    src.mkdir()
    (src / "foo.md").write_text("---\ntitle: Other Foo\n---\nimported body\n", encoding="utf-8")
    return src


def _import(*args: str):
    result = runner.invoke(app, ["import", *args, "--json"])
    assert result.exception is None or isinstance(result.exception, SystemExit), result.exception
    return result, json.loads(result.output)


def _indexed_paths(vault_dir: Path) -> set[str]:
    return {row["path"] for row in Vault.discover(vault_dir).db.execute("SELECT path FROM notes")}


def test_import_never_overwrites_an_existing_note(vault_dir: Path, source: Path):
    note = vault_dir / "research" / "notes" / "foo.md"

    result, payload = _import(str(source))

    assert result.exit_code == 0, result.output
    assert ORIGINAL in note.read_text(encoding="utf-8")
    assert "imported body" not in note.read_text(encoding="utf-8")
    data = payload["data"]
    assert data["imported"] == []
    assert data["count"] == 0
    assert payload["count"] == 0
    [skipped] = data["skipped"]
    assert skipped["source"] == "foo.md"
    assert skipped["destination"] == "foo.md"
    assert skipped["error_code"] == "DESTINATION_EXISTS"
    assert "research/notes/foo.md" in skipped["error"]


def test_import_reports_the_conflict_on_the_console(vault_dir: Path, source: Path):
    result = runner.invoke(app, ["import", str(source)])

    assert result.exit_code == 0, result.output
    out = " ".join(result.output.split())
    assert "Imported 0 files" in out
    assert "foo.md" in out
    assert "already exists" in out
    assert ORIGINAL in (vault_dir / "research" / "notes" / "foo.md").read_text(encoding="utf-8")


def test_import_dry_run_previews_the_conflict(vault_dir: Path, source: Path):
    result, payload = _import(str(source), "--dry-run")

    assert result.exit_code == 0, result.output
    assert payload["data"]["would_import"] == []
    assert [s["error_code"] for s in payload["data"]["skipped"]] == ["DESTINATION_EXISTS"]


def test_import_does_not_write_through_a_symlink_at_the_destination(
    vault_dir: Path, source: Path, tmp_path: Path
):
    """A dangling symlink is an existing entry: copy2 followed it and wrote
    the import wherever it pointed."""
    target = tmp_path / "elsewhere.md"
    (vault_dir / "research" / "notes" / "bar.md").symlink_to(target)
    (source / "foo.md").rename(source / "bar.md")

    result, payload = _import(str(source))

    assert result.exit_code == 0, result.output
    assert not target.exists()
    assert [s["error_code"] for s in payload["data"]["skipped"]] == ["DESTINATION_EXISTS"]


def test_import_of_the_notes_dir_into_itself_skips_every_file(vault_dir: Path):
    result, payload = _import("research/notes")

    assert result.exit_code == 0, result.output
    assert payload["data"]["imported"] == []
    assert [s["source"] for s in payload["data"]["skipped"]] == ["foo.md"]
    assert ORIGINAL in (vault_dir / "research" / "notes" / "foo.md").read_text(encoding="utf-8")


def test_import_counts_only_the_files_that_were_indexed(vault_dir: Path, tmp_path: Path):
    src = tmp_path / "many"
    for sub in ("a", "b", "plain"):
        (src / sub).mkdir(parents=True)
    # a/note.md and b/note.md both derive the id `note`: sync indexes the
    # first and refuses the second. readme.md has no frontmatter, so sync
    # never indexes it.
    (src / "a" / "note.md").write_text("---\ntitle: In a\n---\nx\n", encoding="utf-8")
    (src / "b" / "note.md").write_text("---\ntitle: In b\n---\ny\n", encoding="utf-8")
    (src / "plain" / "readme.md").write_text("# Plain\n\ntext\n", encoding="utf-8")

    result, payload = _import(str(src))

    assert result.exit_code == 0, result.output
    data = payload["data"]
    assert data["imported"] == [{"source": "a/note.md", "destination": "a/note.md"}]
    assert data["count"] == payload["count"] == 1
    not_indexed = {item["source"]: item for item in data["not_indexed"]}
    assert set(not_indexed) == {"b/note.md", "plain/readme.md"}
    assert all(item["error_code"] == "NOTE_NOT_INDEXED" for item in not_indexed.values())
    assert "id collision" in not_indexed["b/note.md"]["error"]
    assert "frontmatter" in not_indexed["plain/readme.md"]["error"]
    indexed = _indexed_paths(vault_dir)
    assert "research/notes/a/note.md" in indexed
    assert "research/notes/b/note.md" not in indexed


@pytest.mark.parametrize(
    ("existing", "spelled"),
    [
        ("papers", "Papers"),
        (unicodedata.normalize("NFD", "café"), unicodedata.normalize("NFC", "café")),
    ],
)
def test_import_counts_a_file_copied_through_another_spelling_of_a_directory(
    vault_dir: Path, tmp_path: Path, existing: str, spelled: str
):
    """On a case- or normalization-insensitive filesystem (macOS, Windows) a
    copy to Papers/ lands in the existing papers/, and sync indexes it, and
    reports its errors, under that spelling. Matched by name, the indexed
    file was reported as not indexed, for no reason."""
    (vault_dir / "research" / "notes" / existing).mkdir()
    src = tmp_path / "spelled"
    (src / spelled).mkdir(parents=True)
    (src / spelled / "new.md").write_text("---\ntitle: New\n---\nnew\n", encoding="utf-8")
    # The id `foo` belongs to the fixture's note.
    (src / spelled / "foo.md").write_text("---\ntitle: Foo again\n---\nf\n", encoding="utf-8")

    result, payload = _import(str(src))

    assert result.exit_code == 0, result.output
    data = payload["data"]
    [imported] = data["imported"]
    assert imported["source"] == f"{spelled}/new.md"
    # The filesystem picks the reported spelling of an existing directory:
    # Windows resolves to the on-disk papers/, macOS keeps Papers/. Either
    # way the destination must name the file that was written.
    notes = vault_dir / "research" / "notes"
    assert (notes / imported["destination"]).samefile(notes / spelled / "new.md")
    assert data["count"] == payload["count"] == 1
    [not_indexed] = data["not_indexed"]
    assert not_indexed["source"] == f"{spelled}/foo.md"
    assert "id collision" in not_indexed["error"]
    assert len(_indexed_paths(vault_dir)) == 2


def test_import_reports_unindexed_files_on_the_console(vault_dir: Path, tmp_path: Path):
    src = tmp_path / "plain"
    src.mkdir()
    (src / "readme.md").write_text("# Plain\n\ntext\n", encoding="utf-8")

    result = runner.invoke(app, ["import", str(src)])

    assert result.exit_code == 0, result.output
    out = " ".join(result.output.split())
    assert "Imported 0 files" in out
    assert "not indexed" in out
    assert "readme.md" in out


@pytest.mark.parametrize("prefix", ["../../..", "..", "../../research/index", "x/../../.."])
def test_import_refuses_a_prefix_outside_the_notes_tree(
    vault_dir: Path, source: Path, prefix: str
):
    before = sorted(vault_dir.parent.rglob("*.md"))

    result, payload = _import(str(source), "--prefix", prefix)

    assert result.exit_code == 1, result.output
    assert payload["ok"] is False
    assert payload["error_code"] == "OUTSIDE_SYNCED_TREE"
    assert sorted(vault_dir.parent.rglob("*.md")) == before


def test_import_refuses_an_absolute_prefix(vault_dir: Path, source: Path, tmp_path: Path):
    outside = tmp_path / "outside"

    result, payload = _import(str(source), "--prefix", str(outside))

    assert result.exit_code == 1, result.output
    assert payload["error_code"] == "OUTSIDE_SYNCED_TREE"
    assert not outside.exists()


def test_import_refuses_a_prefix_through_a_symlink_out_of_the_tree(
    vault_dir: Path, source: Path, tmp_path: Path
):
    outside = tmp_path / "outside"
    outside.mkdir()
    (vault_dir / "research" / "notes" / "link").symlink_to(outside, target_is_directory=True)

    result, payload = _import(str(source), "--prefix", "link")

    assert result.exit_code == 1, result.output
    assert payload["error_code"] == "OUTSIDE_SYNCED_TREE"
    assert list(outside.iterdir()) == []


def test_import_refuses_a_prefix_on_the_console(vault_dir: Path, source: Path):
    result = runner.invoke(app, ["import", str(source), "--prefix", "../../.."])

    assert result.exit_code == 1, result.output
    assert "outside the synced tree" in " ".join(result.output.split())


def test_import_under_a_prefix_inside_the_tree_still_works(vault_dir: Path, source: Path):
    (source / "foo.md").write_text("---\ntitle: Bar\nid: bar\n---\nimported body\n", encoding="utf-8")

    result, payload = _import(str(source), "--prefix", "imported/ml")

    assert result.exit_code == 0, result.output
    assert payload["data"]["imported"] == [
        {"source": "foo.md", "destination": "imported/ml/foo.md"}
    ]
    assert payload["data"]["skipped"] == []
    assert payload["data"]["not_indexed"] == []
    assert "research/notes/imported/ml/foo.md" in _indexed_paths(vault_dir)
    assert ORIGINAL in (vault_dir / "research" / "notes" / "foo.md").read_text(encoding="utf-8")
