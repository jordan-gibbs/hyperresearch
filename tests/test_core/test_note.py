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
    path = write_note(
        tmp_vault.notes_dir,
        "Child Note",
        parent="parent-topic",
    )
    assert "parent-topic" in str(path)


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
