"""Rewriting a note's frontmatter keeps keys NoteMeta does not model, and the
NoteMeta validators accept the tag and id shapes hand-written YAML produces."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
import yaml

from hyperresearch.core.frontmatter import parse_frontmatter, render_note, serialize_frontmatter
from hyperresearch.core.note import read_note, write_note
from hyperresearch.models.note import NoteMeta

PAPER = (
    "---\n"
    "title: Paper\n"
    "authors: [Vaswani, Shazeer]\n"
    "year: 2017\n"
    "created: '2024-01-01T00:00:00Z'\n"
    "url: https://arxiv.org/abs/1706.03762\n"
    "status: draft\n"
    "published: 2017-06-12\n"
    "---\n"
    "The Transformer relies entirely on attention mechanisms.\n"
)


def _frontmatter(text: str) -> dict:
    return yaml.safe_load(text.split("---\n")[1])


def test_rewrite_keeps_unmodeled_keys_values_and_positions():
    meta, body = parse_frontmatter(PAPER)
    meta.status = "review"
    meta.updated = datetime(2024, 2, 1, tzinfo=UTC)

    fm = _frontmatter(render_note(meta, body))

    assert fm["authors"] == ["Vaswani", "Shazeer"]
    assert fm["year"] == 2017
    assert fm["url"] == "https://arxiv.org/abs/1706.03762"
    assert fm["published"] == date(2017, 6, 12)
    assert fm["status"] == "review"
    # Each extra key stays after the key it followed in the file; the modeled
    # keys keep the order serialize_frontmatter has always written.
    assert list(fm) == [
        "title", "authors", "year", "created", "url", "updated",
        "status", "published", "type", "deprecated",
    ]


def test_extra_key_before_title_stays_first():
    meta, body = parse_frontmatter("---\nauthors: [A]\ntitle: T\n---\nBody\n")
    assert list(_frontmatter(render_note(meta, body)))[:2] == ["authors", "title"]


def test_extra_keys_survive_repeated_rewrites():
    meta, body = parse_frontmatter(PAPER)
    once = render_note(meta, body)
    assert _frontmatter(once)["year"] == 2017
    meta2, body2 = parse_frontmatter(once)
    assert render_note(meta2, body2) == once


def test_extra_null_value_is_kept():
    meta, body = parse_frontmatter("---\ntitle: T\nreviewer:\n---\nBody\n")
    fm = _frontmatter(render_note(meta, body))
    assert "reviewer" in fm
    assert fm["reviewer"] is None


def test_note_without_extra_keys_serializes_byte_identically():
    content = (
        "---\n"
        "title: Plain\n"
        "id: plain\n"
        "tags: [python, test]\n"
        "created: '2024-01-01T00:00:00Z'\n"
        "status: draft\n"
        "type: note\n"
        "summary: A summary\n"
        "---\n"
        "Body\n"
    )
    meta, _ = parse_frontmatter(content)
    assert serialize_frontmatter(meta) == (
        "---\n"
        "title: Plain\n"
        "id: plain\n"
        "tags:\n"
        "- python\n"
        "- test\n"
        "created: '2024-01-01T00:00:00Z'\n"
        "status: draft\n"
        "type: note\n"
        "deprecated: false\n"
        "summary: A summary\n"
        "---\n"
    )


def test_constructed_meta_still_drops_unknown_keys(tmp_vault):
    """Fetch passes scraped metadata (e.g. `author`) through write_note's
    extra_frontmatter; keys NoteMeta does not model are not persisted."""
    assert "author" not in serialize_frontmatter(NoteMeta(title="T", author="Scraper"))

    path = write_note(
        tmp_vault.notes_dir,
        "Fetched",
        body="x\n",
        extra_frontmatter={"source": "https://example.com", "author": "Scraper"},
    )
    assert "author" not in _frontmatter(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("yaml_tags", "expected"),
    [
        ("research", ["research"]),
        ("a, b", ["a", "b"]),
        ("Machine-Learning, AI", ["machine-learning", "ai"]),
        ("", []),
        ("''", []),
        ("[2024, ml]", ["2024", "ml"]),
        ("2024", ["2024"]),
        ("[ML, null, '', ' x ']", ["ml", "x"]),
        ("[Python, ASYNC, Test]", ["python", "async", "test"]),
    ],
)
def test_tags_yaml_shapes(yaml_tags, expected):
    meta, _ = parse_frontmatter(f"---\ntitle: T\ntags: {yaml_tags}\n---\nBody\n")
    assert meta.tags == expected


def test_scalar_tags_are_written_back_as_one_tag():
    meta, body = parse_frontmatter("---\ntitle: T\ntags: research\n---\nBody\n")
    assert _frontmatter(render_note(meta, body))["tags"] == ["research"]


@pytest.mark.parametrize(("yaml_id", "expected"), [("2017", "2017"), ("12345", "12345")])
def test_numeric_id_becomes_string_slug(yaml_id, expected):
    meta, _ = parse_frontmatter(f"---\ntitle: T\nid: {yaml_id}\n---\nBody\n")
    assert meta.id == expected


def test_empty_id_falls_back_to_filename(tmp_vault):
    path = tmp_vault.notes_dir / "from-stem.md"
    path.write_text("---\ntitle: T\nid:\n---\nBody\n", encoding="utf-8")
    note = read_note(path, tmp_vault.root)
    assert note.meta.id == "from-stem"
    assert note.id_declared is False
