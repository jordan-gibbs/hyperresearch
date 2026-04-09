"""Tests for frontmatter parsing and serialization."""

from hyperresearch.core.frontmatter import parse_frontmatter, serialize_frontmatter, render_note
from hyperresearch.models.note import NoteMeta


def test_parse_basic_frontmatter():
    content = '---\ntitle: "Hello World"\nid: hello-world\ntags: [python, test]\nstatus: draft\ntype: note\n---\n\n# Hello\n'
    meta, body = parse_frontmatter(content)
    assert meta.title == "Hello World"
    assert meta.id == "hello-world"
    assert meta.tags == ["python", "test"]
    assert "# Hello" in body


def test_parse_missing_frontmatter():
    content = "# Just markdown\n\nNo frontmatter here."
    meta, body = parse_frontmatter(content)
    assert meta.title == "Untitled"
    assert body == content


def test_parse_empty_frontmatter():
    content = "---\n---\n\nBody here."
    meta, body = parse_frontmatter(content)
    assert meta.title == "Untitled"


def test_serialize_roundtrip():
    meta = NoteMeta(
        title="Test Note",
        id="test-note",
        tags=["python", "test"],
        status="draft",
        type="note",
    )
    serialized = serialize_frontmatter(meta)
    assert "title: Test Note" in serialized
    assert "---" in serialized

    # Parse it back
    parsed, _ = parse_frontmatter(serialized + "\nBody text")
    assert parsed.title == "Test Note"
    assert parsed.id == "test-note"
    assert parsed.tags == ["python", "test"]


def test_render_note():
    meta = NoteMeta(title="My Note", id="my-note")
    rendered = render_note(meta, "# Content\n\nHello!")
    assert rendered.startswith("---\n")
    assert "title: My Note" in rendered
    assert "# Content" in rendered


def test_tags_lowercased():
    content = '---\ntitle: Test\ntags: [Python, ASYNC, Test]\n---\n\nBody'
    meta, _ = parse_frontmatter(content)
    assert meta.tags == ["python", "async", "test"]


def test_windows_path_in_source():
    """Ensure Windows paths with backslashes are handled correctly."""
    meta = NoteMeta(
        title="Test",
        id="test",
        source=r"C:\Users\Jordan\file.md",
    )
    serialized = serialize_frontmatter(meta)
    # Should be valid YAML
    parsed, _ = parse_frontmatter(serialized + "\nBody")
    assert "Jordan" in (parsed.source or "")
