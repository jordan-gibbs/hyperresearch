"""Tests for note read/write operations."""


from hyperresearch.core.note import read_note, strip_markdown, write_note
from hyperresearch.models.note import slugify


def test_slugify_basic():
    assert slugify("Hello World") == "hello-world"
    assert slugify("Python 3.12 Features!") == "python-312-features"
    assert slugify("  spaces  ") == "spaces"
    assert slugify("CamelCase") == "camelcase"
    assert slugify("dashes--double") == "dashes-double"


def test_write_and_read_roundtrip(tmp_vault):
    path = write_note(
        tmp_vault.notes_dir,
        "Roundtrip Test",
        body="# Content\n\nSome text here.\n",
        tags=["test", "roundtrip"],
        status="evergreen",
    )
    assert path.exists()

    note = read_note(path, tmp_vault.root)
    assert note.meta.title == "Roundtrip Test"
    assert note.meta.id == "roundtrip-test"
    assert note.meta.tags == ["test", "roundtrip"]
    assert note.meta.status == "evergreen"
    assert "# Content" in note.body
    assert note.word_count > 0


def test_write_avoids_collision(tmp_vault):
    p1 = write_note(tmp_vault.notes_dir, "Same Title")
    p2 = write_note(tmp_vault.notes_dir, "Same Title")
    assert p1 != p2
    assert p1.exists()
    assert p2.exists()


def test_write_with_parent(tmp_vault):
    """`parent:` is frontmatter metadata (DB-indexed), NOT a filesystem dir."""
    path = write_note(
        tmp_vault.notes_dir,
        "Child Note",
        parent="parent-topic",
    )
    # Flat layout: note lives directly under notes_dir, not in a parent-slug subdir.
    assert path.parent == tmp_vault.notes_dir
    assert path.name == "child-note.md"
    # parent still appears in the YAML frontmatter for DB filtering.
    assert "parent: parent-topic" in path.read_text(encoding="utf-8")


def test_read_extracts_links(tmp_vault):
    path = write_note(
        tmp_vault.notes_dir,
        "Linking Note",
        body="See [[note-a]] and [[note-b|display text]].\n",
    )
    note = read_note(path, tmp_vault.root)
    assert "note-a" in note.outgoing_links
    assert "note-b" in note.outgoing_links


def test_read_ignores_code_links(tmp_vault):
    path = write_note(
        tmp_vault.notes_dir,
        "Code Note",
        body="Real: [[real-link]]\n\n```python\nfake: [[fake-link]]\n```\n\nAlso `[[inline-fake]]`\n",
    )
    note = read_note(path, tmp_vault.root)
    assert "real-link" in note.outgoing_links
    assert "fake-link" not in note.outgoing_links
    assert "inline-fake" not in note.outgoing_links


def test_strip_markdown():
    md = "# Header\n\n**Bold** and *italic*. See [[link|display]] and [url](http://example.com).\n\n```python\ncode\n```\n"
    plain = strip_markdown(md)
    assert "Header" in plain
    assert "Bold" in plain
    assert "display" in plain
    assert "url" in plain
    assert "```" not in plain
    assert "**" not in plain
    assert "[[" not in plain


def test_raw_file_persists_on_roundtrip(tmp_vault):
    """raw_file must survive parse + re-serialize (regression test for wipe bug).

    Before Batch 1.2 fix: raw_file was injected into frontmatter as a string
    AFTER write_note; NoteMeta.model_config = {"extra": "ignore"} silently
    dropped the field on the next parse, and any re-serialization (repair,
    note update) wiped it from disk.
    """
    from hyperresearch.core.frontmatter import parse_frontmatter, render_note

    path = write_note(
        tmp_vault.notes_dir,
        "PDF Note",
        body="# PDF content\n",
        extra_frontmatter={"raw_file": "raw/pdf-note.pdf"},
    )
    # First read — does NoteMeta capture the field?
    note = read_note(path, tmp_vault.root)
    assert note.meta.raw_file == "raw/pdf-note.pdf"

    # Re-serialize (simulates repair.py enrichment or note update).
    text = path.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(text)
    path.write_text(render_note(meta, body), encoding="utf-8")

    # Second read — raw_file must still be present.
    note2 = read_note(path, tmp_vault.root)
    assert note2.meta.raw_file == "raw/pdf-note.pdf", (
        "raw_file was wiped on re-serialize — Batch 1.2 regression"
    )


def test_read_utf8_content(tmp_vault):
    path = write_note(
        tmp_vault.notes_dir,
        "Unicode Note",
        body="# Umlaute: Aaou. CJK: . Emoji: .\n",
    )
    note = read_note(path, tmp_vault.root)
    assert "Aaou" in note.body


def test_read_empty_body(tmp_vault):
    path = tmp_vault.notes_dir / "empty.md"
    path.parent.mkdir(exist_ok=True)
    path.write_text("---\ntitle: Empty\nid: empty\nstatus: draft\ntype: note\n---\n", encoding="utf-8")

    note = read_note(path, tmp_vault.root)
    assert note.meta.title == "Empty"
    assert note.body.strip() == ""
