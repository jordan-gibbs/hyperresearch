"""Tests for note mv, edit, rm CLI operations."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app

runner = CliRunner()


@pytest.fixture
def vault_with_notes(tmp_path: Path) -> Path:
    vault_dir = tmp_path / "kb"
    runner.invoke(app, ["init", str(vault_dir)])
    os.chdir(vault_dir)
    runner.invoke(app, ["note", "new", "Alpha Note", "--tag", "test"])
    runner.invoke(app, ["note", "new", "Beta Note", "--tag", "test"])
    runner.invoke(app, ["sync"])
    return vault_dir


def test_note_rm_json(vault_with_notes):
    result = runner.invoke(app, ["note", "rm", "alpha-note", "--force", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["ok"] is True
    assert data["data"]["deleted"] == "alpha-note"


def test_note_rm_nonexistent(vault_with_notes):
    result = runner.invoke(app, ["note", "rm", "nonexistent", "--force", "--json"])
    assert result.exit_code == 1


def test_note_rm_cleans_raw_file_and_assets(vault_with_notes):
    """note rm must delete the raw file and assets directory, not just the .md.

    Regression test for Batch 2.5 — prior to this, `note rm` only unlinked
    the `.md` file and raw/assets leaked on disk forever.
    """
    vault_root = vault_with_notes

    # Seed a note with raw_file in its frontmatter and an assets directory.
    from hyperresearch.core.note import write_note
    from hyperresearch.core.vault import Vault
    vault = Vault.discover()

    write_note(
        vault.notes_dir,
        "PDF Source",
        note_id="pdf-source",
        source="https://example.com/paper.pdf",
        tier="ground_truth",
        content_type="paper",
        extra_frontmatter={"raw_file": "raw/pdf-source.pdf"},
    )

    raw_dir = vault_root / "research" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_file = raw_dir / "pdf-source.pdf"
    raw_file.write_bytes(b"%PDF-1.4 test")

    assets_dir = vault_root / "research" / "assets" / "pdf-source"
    assets_dir.mkdir(parents=True, exist_ok=True)
    (assets_dir / "screenshot.png").write_bytes(b"PNG fake")
    (assets_dir / "figure-1.jpg").write_bytes(b"JPG fake")

    runner.invoke(app, ["sync"])

    # Delete it
    result = runner.invoke(app, ["note", "rm", "pdf-source", "--force", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["ok"] is True
    assert data["data"]["deleted"] == "pdf-source"
    assert data["data"].get("removed_raw") == "research/raw/pdf-source.pdf"
    assert len(data["data"].get("removed_assets", [])) == 2

    # Verify the files are actually gone from disk.
    assert not raw_file.exists(), "raw file should have been deleted"
    assert not assets_dir.exists(), "assets directory should have been removed"


def test_note_mv(vault_with_notes):
    result = runner.invoke(
        app, ["note", "mv", "beta-note", "research/notes/moved/beta-note.md", "--json"]
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["data"]["new_path"] == "research/notes/moved/beta-note.md"
    assert (vault_with_notes / "research" / "notes" / "moved" / "beta-note.md").exists()


# ---------------------------------------------------------------------------
# `note mv` destinations must stay where sync can see them. The destination
# used to be joined onto the vault root verbatim: a bare name landed at the
# vault root with no .md suffix, outside everything sync scans, so the note
# silently left the index; and an existing file was overwritten.
# ---------------------------------------------------------------------------


def _indexed_path(note_id: str) -> str | None:
    from hyperresearch.core.vault import Vault

    row = Vault.discover().db.execute(
        "SELECT path FROM notes WHERE id = ?", (note_id,)
    ).fetchone()
    return row["path"] if row else None


def test_note_mv_bare_name_lands_in_notes_dir_with_md_suffix(vault_with_notes):
    result = runner.invoke(app, ["note", "mv", "beta-note", "beta-renamed", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["data"]["new_path"] == "research/notes/beta-renamed.md"
    assert (vault_with_notes / "research" / "notes" / "beta-renamed.md").exists()
    assert not (vault_with_notes / "beta-renamed").exists()
    # The id lives in frontmatter, so the note stays indexed under it, at the new path.
    assert _indexed_path("beta-note") == "research/notes/beta-renamed.md"


def test_note_mv_refuses_a_destination_outside_the_synced_tree(vault_with_notes):
    result = runner.invoke(
        app, ["note", "mv", "beta-note", "notes/moved/beta-note.md", "--json"]
    )
    assert result.exit_code == 1, result.output
    data = json.loads(result.output)
    assert data["ok"] is False
    assert data["error_code"] == "OUTSIDE_SYNCED_TREE"
    assert (vault_with_notes / "research" / "notes" / "beta-note.md").exists()
    assert not (vault_with_notes / "notes").exists()
    assert _indexed_path("beta-note") == "research/notes/beta-note.md"


@pytest.mark.parametrize("dest", ["research/notes/alpha-note.md", "alpha-note"])
def test_note_mv_refuses_to_overwrite_an_existing_file(vault_with_notes, dest):
    result = runner.invoke(app, ["note", "mv", "beta-note", dest, "--json"])
    assert result.exit_code == 1, result.output
    data = json.loads(result.output)
    assert data["error_code"] == "DESTINATION_EXISTS"
    alpha = (vault_with_notes / "research" / "notes" / "alpha-note.md").read_text(encoding="utf-8")
    assert "id: alpha-note" in alpha
    assert _indexed_path("alpha-note") == "research/notes/alpha-note.md"
    assert _indexed_path("beta-note") == "research/notes/beta-note.md"



def test_note_mv_refuses_the_index_dir(vault_with_notes):
    # build_all() wipes research/index/*.md on every repair, so a note moved
    # there would be deleted the next time the index regenerates.
    result = runner.invoke(
        app, ["note", "mv", "beta-note", "research/index/beta-note.md", "--json"]
    )
    assert result.exit_code == 1, result.output
    assert json.loads(result.output)["error_code"] == "OUTSIDE_SYNCED_TREE"
    assert _indexed_path("beta-note") == "research/notes/beta-note.md"


def test_note_mv_allows_a_case_only_rename(vault_with_notes):
    result = runner.invoke(
        app, ["note", "mv", "beta-note", "research/notes/Beta-Note.md", "--json"]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["data"]["new_path"] == "research/notes/Beta-Note.md"
    names = [f.name for f in (vault_with_notes / "research" / "notes").iterdir()]
    assert "Beta-Note.md" in names
    assert "beta-note.md" not in names
    assert _indexed_path("beta-note") == "research/notes/Beta-Note.md"


def test_note_mv_does_not_double_an_uppercase_suffix(vault_with_notes):
    result = runner.invoke(app, ["note", "mv", "beta-note", "Renamed.MD", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["data"]["new_path"] == "research/notes/Renamed.MD"

def test_note_show_raw(vault_with_notes):
    result = runner.invoke(app, ["note", "show", "alpha-note", "--raw"])
    assert result.exit_code == 0
    assert "---" in result.output
    assert "Alpha Note" in result.output


def test_note_list_with_filters(vault_with_notes):
    result = runner.invoke(app, ["note", "list", "--tag", "test", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["count"] >= 2

    result = runner.invoke(app, ["note", "list", "--status", "draft", "--json"])
    data = json.loads(result.output)
    assert data["count"] >= 2

    result = runner.invoke(app, ["note", "list", "--sort", "title", "--limit", "1", "--json"])
    data = json.loads(result.output)
    assert data["count"] == 1


def test_note_update_rejects_invalid_status(vault_with_notes):
    """`note update --status` must validate before writing frontmatter.

    Regression test: NoteMeta is a pydantic model configured without
    validate_assignment, so `meta.status = set_status` used to accept any
    string and serialize it straight into the note. The write reported
    success, but parse_frontmatter then refused to read the note back, and
    execute_sync swallowed the ValidationError per-file — leaving the note
    permanently absent from the index while the DB served stale rows. A
    one-letter typo (`evergreeen`) was enough to orphan a note for good.
    """
    result = runner.invoke(
        app, ["note", "update", "alpha-note", "--status", "evergreeen", "--json"]
    )
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["ok"] is False
    assert data["error_code"] == "INVALID_STATUS"
    assert "evergreen" in data["error"]  # lists the valid values

    # The note on disk must be untouched and still parseable.
    from hyperresearch.core.frontmatter import parse_frontmatter

    content = (vault_with_notes / "research/notes/alpha-note.md").read_text(encoding="utf-8")
    meta, _ = parse_frontmatter(content)
    assert meta.status == "draft"


def test_note_update_accepts_valid_status_and_stays_indexed(vault_with_notes):
    """The happy path must still write, and the note must survive a resync."""
    result = runner.invoke(
        app, ["note", "update", "alpha-note", "--status", "evergreen", "--json"]
    )
    assert result.exit_code == 0
    assert json.loads(result.output)["ok"] is True

    sync = runner.invoke(app, ["sync", "--json"])
    assert sync.exit_code == 0
    assert not json.loads(sync.output)["data"]["errors"]

    listed = runner.invoke(app, ["note", "list", "--json"])
    rows = json.loads(listed.output)["data"]
    assert [n["status"] for n in rows if n["id"] == "alpha-note"] == ["evergreen"]


# ---------------------------------------------------------------------------
# The final report has no YAML header by pipeline design and is indexed from
# derived metadata. Every writer that round-trips parse -> serialize -> write
# must refuse it, or the next `note update` puts a header into the deliverable.
# ---------------------------------------------------------------------------

REPORT_ID = "final_report_kb-test-a1b2c3"


@pytest.fixture
def vault_with_report(vault_with_notes: Path) -> Path:
    report = vault_with_notes / "research" / "notes" / f"{REPORT_ID}.md"
    # Long enough (>= 100 words) and linked, so repair's promote query selects it.
    filler = " ".join(f"word{i}" for i in range(110))
    report.write_text(
        "# Report Title\n\n"
        "This first paragraph is long enough to become the derived summary of the report.\n\n"
        f"It cites [[alpha-note]] and [[beta-note]]. {filler}\n",
        encoding="utf-8",
    )
    runner.invoke(app, ["sync"])
    return report


def test_note_show_reads_a_frontmatterless_final_report(vault_with_report):
    result = runner.invoke(app, ["note", "show", REPORT_ID, "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)["data"]
    assert data["title"] == "Report Title"
    assert data["tags"] == ["final-report"]
    assert data["status"] == "review"
    assert "It cites [[alpha-note]]" in data["body"]


def test_note_update_refuses_to_write_a_header_into_the_report(vault_with_report):
    before = vault_with_report.read_bytes()
    result = runner.invoke(app, ["note", "update", REPORT_ID, "--add-tag", "x", "--json"])
    assert result.exit_code == 1, result.output
    data = json.loads(result.output)
    assert data["ok"] is False
    assert data["error_code"] == "REPORT_WITHOUT_FRONTMATTER"
    assert vault_with_report.read_bytes() == before


def test_batch_frontmatter_update_refuses_the_report(vault_with_report):
    from hyperresearch.cli.batch import _update_file_frontmatter

    assert _indexed_path(REPORT_ID) == f"research/notes/{REPORT_ID}.md"
    from hyperresearch.core.frontmatter import FrontmatterWriteRefusedError

    vault_root = vault_with_report.parents[2]
    before = vault_with_report.read_bytes()
    with pytest.raises(FrontmatterWriteRefusedError):
        _update_file_frontmatter(vault_root, f"research/notes/{REPORT_ID}.md", {"add_tag": "x"})
    assert vault_with_report.read_bytes() == before


def test_repair_leaves_the_report_byte_identical(vault_with_report):
    """The report is `review`, over 100 words and linked, so repair's promote
    step selects it for `evergreen`; the enrich step would also rewrite any note
    it finds deficient. Both must skip the header-less deliverable.
    """
    before = vault_with_report.read_bytes()
    result = runner.invoke(app, ["repair", "--no-stub", "--no-index", "--no-docs", "--json"])
    assert result.exit_code == 0, result.output
    assert vault_with_report.read_bytes() == before


def test_batch_commands_skip_the_report_instead_of_crashing(vault_with_report):
    """Every `batch` command selects through _get_matching_notes and writes in
    a bare loop. An unfiltered batch matches the indexed report, so it must be
    left out of the selection rather than raise halfway through the loop."""
    before = vault_with_report.read_bytes()
    result = runner.invoke(app, ["batch", "tag-add", "x", "--json"])
    assert result.exit_code == 0, result.output
    modified = json.loads(result.output)["data"]["modified"]
    assert sorted(modified) == ["alpha-note", "beta-note"]
    assert vault_with_report.read_bytes() == before


def test_auto_link_leaves_the_report_byte_identical(vault_with_report):
    """`link --auto` appends a Related section to any note whose prose names
    another note. The report is indexed now, so the linker must skip it: its
    body is the deliverable, not a place for generated sections."""
    runner.invoke(app, ["note", "new", "Gamma Field Measurements", "--tag", "test"])
    with vault_with_report.open("a", encoding="utf-8") as f:
        f.write("\nThe Gamma Field Measurements reach the same conclusion.\n")
    runner.invoke(app, ["sync"])
    before = vault_with_report.read_bytes()
    result = runner.invoke(app, ["link", "--auto", "--json"])
    assert result.exit_code == 0, result.output
    assert vault_with_report.read_bytes() == before


@pytest.mark.parametrize(
    "dest",
    ["renamed.md", f"research/temp/{REPORT_ID}.md", f"research/temp/notes/{REPORT_ID}.md"],
)
def test_note_mv_refuses_to_move_the_report_out_of_the_report_name(vault_with_report, dest):
    """The header-less report is indexed by its name under research/notes/
    alone, so any other destination would silently drop it from the index."""
    result = runner.invoke(app, ["note", "mv", REPORT_ID, dest, "--json"])
    assert result.exit_code == 1, result.output
    assert json.loads(result.output)["error_code"] == "DESTINATION_NOT_INDEXABLE"
    assert vault_with_report.exists()
    assert _indexed_path(REPORT_ID) == f"research/notes/{REPORT_ID}.md"


def test_note_mv_allows_a_report_name_that_stays_indexed(vault_with_report):
    result = runner.invoke(app, ["note", "mv", REPORT_ID, "final_report_renamed.md", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["data"]["new_path"] == "research/notes/final_report_renamed.md"
    # The id derives from the stem, so the note is now indexed under the new name.
    assert _indexed_path("final_report_renamed") == "research/notes/final_report_renamed.md"
    assert _indexed_path(REPORT_ID) is None


@pytest.mark.parametrize("dest", ["final_report_taken.md", "final_report_Taken.md"])
def test_note_mv_refuses_a_report_name_whose_id_another_note_has(vault_with_report, dest):
    """The report's id derives from its stem, so the rename changes it; where
    another note already has the new id, the move would drop the report from
    the index while reporting success. The id is the slugified stem, so a
    name that differs only in case lands on the same id."""
    other = vault_with_report.parent / "other.md"
    other.write_text("---\nid: final_report_taken\ntitle: Other\n---\n\nBody.\n", encoding="utf-8")
    runner.invoke(app, ["sync"])
    assert _indexed_path("final_report_taken") == "research/notes/other.md"

    result = runner.invoke(app, ["note", "mv", REPORT_ID, dest, "--json"])
    assert result.exit_code == 1, result.output
    assert json.loads(result.output)["error_code"] == "ID_TAKEN"
    assert vault_with_report.exists()
    assert _indexed_path(REPORT_ID) == f"research/notes/{REPORT_ID}.md"


def test_note_rm_deletes_the_report_when_forced(vault_with_report):
    """Deletion is not a header write and `--force` is explicit, so the
    indexed report is removable like any other note."""
    result = runner.invoke(app, ["note", "rm", REPORT_ID, "--force", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["data"]["deleted"] == REPORT_ID
    assert not vault_with_report.exists()
