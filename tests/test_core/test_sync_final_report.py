"""Tests for indexing the header-less final report.

research/notes/final_report_<vault_tag>.md carries no YAML frontmatter by
pipeline design (steps 10, 11 and 15 forbid a header), so the #25 scratch-file
probe skipped it and every report was on disk yet invisible to search, note
show, status and the note-level lint rules. It now indexes from metadata
derived at read time, and no writer may put a header into it.
"""

import pytest

from hyperresearch.core.sync import compute_sync_plan, execute_sync


def _write_report(notes_dir, name: str, text: str):
    notes_dir.mkdir(parents=True, exist_ok=True)
    p = notes_dir / name
    p.write_text(text, encoding="utf-8")
    return p


def test_sync_indexes_a_frontmatterless_final_report(tmp_vault):
    report = _write_report(
        tmp_vault.notes_dir,
        "final_report_efield-dft-sac-a3f9b7.md",
        "# Electric-field control of DFT single-atom catalysts\n\n"
        "This report weighs the evidence that an applied field shifts the active "
        "site, drawing on [[source-one]] and [[source-two]].\n\n"
        "## Findings\n\nMore body.\n",
    )
    raw_before = report.read_bytes()

    plan = compute_sync_plan(tmp_vault)
    assert [p.name for p in plan.to_add] == [report.name]

    result = execute_sync(tmp_vault, plan)
    assert result.added == 1
    assert result.errors == []

    row = tmp_vault.db.execute(
        "SELECT id, title, status, type, summary FROM notes WHERE path = ?",
        ("research/notes/final_report_efield-dft-sac-a3f9b7.md",),
    ).fetchone()
    assert row["id"] == "final_report_efield-dft-sac-a3f9b7"
    assert row["title"] == "Electric-field control of DFT single-atom catalysts"
    assert row["status"] == "review"
    assert row["type"] == "note"
    assert row["summary"].startswith("This report weighs the evidence")
    tags = {
        r["tag"]
        for r in tmp_vault.db.execute("SELECT tag FROM tags WHERE note_id = ?", (row["id"],))
    }
    assert tags == {"final-report"}

    # Reachable through search and the link graph like any other note.
    hits = tmp_vault.db.execute(
        "SELECT id FROM notes_fts WHERE notes_fts MATCH 'catalysts'"
    ).fetchall()
    assert [h["id"] for h in hits] == [row["id"]]
    links = {
        r["target_ref"]
        for r in tmp_vault.db.execute("SELECT target_ref FROM links WHERE source_id = ?", (row["id"],))
    }
    assert links == {"source-one", "source-two"}

    # The deliverable on disk is byte-identical: no header was written into it,
    # and the second pass sees an unchanged note, not an update.
    assert report.read_bytes() == raw_before
    plan2 = compute_sync_plan(tmp_vault)
    assert plan2.to_add == []
    assert plan2.to_update == []


def test_sync_report_without_a_heading_falls_back_to_the_stem_title(tmp_vault):
    report = _write_report(
        tmp_vault.notes_dir, "final_report_bare-tag.md", "Body that opens with prose.\n"
    )
    execute_sync(tmp_vault, compute_sync_plan(tmp_vault))
    row = tmp_vault.db.execute(
        "SELECT title FROM notes WHERE id = ?", ("final_report_bare-tag",)
    ).fetchone()
    assert row is not None
    assert row["title"] == report.stem


def test_sync_still_skips_frontmatterless_files_that_are_not_the_report(tmp_vault):
    """The exemption is by name AND location. A frontmatter-less body file under
    research/notes/ with any other name, the bare `final_report.md`, and a
    `final_report_*` copy outside research/notes/ (another directory named
    `notes` included) all stay out of the index exactly as before: this is
    the #25 failure path, retained.
    """
    _write_report(tmp_vault.notes_dir, "evidence-digest.md", "# Digest\n\nscratch body\n")
    _write_report(tmp_vault.notes_dir, "final_report.md", "# Legacy bare name\n\nbody\n")
    tmp_vault.temp_dir.mkdir(parents=True, exist_ok=True)
    (tmp_vault.temp_dir / "final_report_copy.md").write_text("# Copy in temp\n\nbody\n")
    _write_report(tmp_vault.temp_dir / "notes", "final_report_copy.md", "# Copy\n\nbody\n")
    _write_report(tmp_vault.notes_dir / "sub" / "notes", "final_report_copy.md", "# Copy\n\nbody\n")

    plan = compute_sync_plan(tmp_vault)
    assert plan.to_add == []


def test_sync_refuses_a_report_whose_derived_id_is_already_taken(tmp_vault):
    """A derived id goes through the same #25 collision guard as a frontmatter
    id: when another file already owns `final_report_<tag>`, the report is
    skipped with an error instead of smashing that row's path.
    """
    tmp_vault.notes_dir.mkdir(parents=True, exist_ok=True)
    (tmp_vault.notes_dir / "squatter.md").write_text(
        "---\nid: final_report_dup\ntitle: Squatter\n---\n\n# S\n", encoding="utf-8"
    )
    result1 = execute_sync(tmp_vault, compute_sync_plan(tmp_vault))
    assert result1.errors == []

    _write_report(tmp_vault.notes_dir, "final_report_dup.md", "# The report\n\nbody\n")
    result2 = execute_sync(tmp_vault, compute_sync_plan(tmp_vault))
    assert result2.added == 0
    assert len(result2.errors) == 1
    assert "id collision" in result2.errors[0]["error"]
    row = tmp_vault.db.execute(
        "SELECT path FROM notes WHERE id = ?", ("final_report_dup",)
    ).fetchone()
    assert row["path"] == "research/notes/squatter.md"


def test_write_frontmatter_refuses_only_the_frontmatterless_report(tmp_vault):
    """Every parse -> mutate -> serialize -> write path goes through
    write_frontmatter, which is where the header-less deliverable is refused;
    an ordinary note, and a report that carries a header, write as before."""
    from hyperresearch.core.frontmatter import parse_frontmatter, render_note
    from hyperresearch.core.note import write_note

    bare = _write_report(tmp_vault.notes_dir, "final_report_t.md", "# T\n\nbody\n")
    raw_before = bare.read_bytes()
    execute_sync(tmp_vault, compute_sync_plan(tmp_vault))
    row = tmp_vault.db.execute("SELECT id FROM notes WHERE id = 'final_report_t'").fetchone()
    assert row is not None  # indexed, so every writer can now select it

    from hyperresearch.core.frontmatter import FrontmatterWriteRefusedError, write_frontmatter

    meta, body = parse_frontmatter(bare.read_text(encoding="utf-8-sig"))
    meta.tags = ["x"]
    with pytest.raises(FrontmatterWriteRefusedError) as exc_info:
        write_frontmatter(bare, meta, body, tmp_vault.root)
    assert "research/notes/final_report_t.md" in str(exc_info.value)
    assert bare.read_bytes() == raw_before

    # A report that DOES carry a header is an ordinary note, and so is any
    # other file: both are written exactly as the inline writers did.
    for p in (
        write_note(tmp_vault.notes_dir, "Old report", note_id="final_report_old", body="# Old\n"),
        write_note(tmp_vault.notes_dir, "Digest", body="# D\n"),
    ):
        meta, body = parse_frontmatter(p.read_text(encoding="utf-8-sig"))
        meta.tags = ["x"]
        write_frontmatter(p, meta, body, tmp_vault.root)
        assert p.read_text(encoding="utf-8") == render_note(meta, body)


def test_sync_keeps_the_report_created_across_edits(tmp_vault):
    """The report has no header to carry timestamps, so both derive from the
    file's mtime: `updated` follows every edit, `created` keeps the value from
    the first indexing (the polish and cite-check passes all edit the file)."""
    import os
    from datetime import UTC, datetime

    report = _write_report(tmp_vault.notes_dir, "final_report_ts.md", "# R\n\nFirst body.\n")
    t0 = datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC).timestamp()
    os.utime(report, (t0, t0))
    execute_sync(tmp_vault, compute_sync_plan(tmp_vault))
    row = tmp_vault.db.execute(
        "SELECT created, updated FROM notes WHERE id = 'final_report_ts'"
    ).fetchone()
    assert row is not None
    assert row["created"] == row["updated"] == datetime.fromtimestamp(t0, tz=UTC).isoformat()

    report.write_text("# R\n\nEdited body.\n", encoding="utf-8")
    t1 = t0 + 86400
    os.utime(report, (t1, t1))
    result = execute_sync(tmp_vault, compute_sync_plan(tmp_vault))
    assert result.updated == 1
    row = tmp_vault.db.execute(
        "SELECT created, updated FROM notes WHERE id = 'final_report_ts'"
    ).fetchone()
    assert row["created"] == datetime.fromtimestamp(t0, tz=UTC).isoformat()
    assert row["updated"] == datetime.fromtimestamp(t1, tz=UTC).isoformat()


@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
@pytest.mark.parametrize(("heading", "title"), [("# C#", "C#"), ("# Title ##", "Title")])
def test_sync_report_title_trims_only_a_closing_hash_sequence(tmp_vault, heading, title, newline):
    """CommonMark: a closing `#` run counts only after whitespace. Written as
    bytes, so each line ending is tested as given on every platform (text
    mode on Windows writes CRLF)."""
    tmp_vault.notes_dir.mkdir(parents=True, exist_ok=True)
    report = tmp_vault.notes_dir / "final_report_h.md"
    report.write_bytes(f"{heading}{newline}{newline}body{newline}".encode())
    execute_sync(tmp_vault, compute_sync_plan(tmp_vault))
    row = tmp_vault.db.execute("SELECT title FROM notes WHERE id = 'final_report_h'").fetchone()
    assert row is not None
    assert row["title"] == title
