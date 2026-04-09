"""Tests for link parsing and graph operations."""

from hyperresearch.core.note import WIKI_LINK_RE, CODE_BLOCK_RE, INLINE_CODE_RE


def test_wiki_link_regex_simple():
    matches = WIKI_LINK_RE.findall("See [[python-async]] for details.")
    assert len(matches) == 1
    assert matches[0] == "python-async"


def test_wiki_link_regex_with_display():
    text = "Check [[python-async|Python Async Guide]] here."
    matches = WIKI_LINK_RE.findall(text)
    assert len(matches) == 1
    # Group 1 is the target
    assert "python-async" in matches[0]


def test_wiki_link_regex_multiple():
    text = "See [[note-a]], [[note-b]], and [[note-c|Note C]]."
    matches = WIKI_LINK_RE.findall(text)
    assert len(matches) == 3


def test_wiki_link_not_in_code_block():
    text = "```python\n[[not-a-link]]\n```\n\n[[real-link]]"
    cleaned = CODE_BLOCK_RE.sub("", text)
    matches = WIKI_LINK_RE.findall(cleaned)
    assert len(matches) == 1
    assert "real-link" in matches[0]


def test_wiki_link_not_in_inline_code():
    text = "Use `[[not-a-link]]` but also [[real-link]]"
    cleaned = INLINE_CODE_RE.sub("", text)
    matches = WIKI_LINK_RE.findall(cleaned)
    assert len(matches) == 1
    assert "real-link" in matches[0]


def test_backlinks_populated(seeded_vault):
    """Concurrency links to python-async-patterns, so python-async-patterns should have a backlink."""
    rows = seeded_vault.db.execute(
        "SELECT source_id FROM links WHERE target_id = 'python-async-patterns'"
    ).fetchall()
    source_ids = [r["source_id"] for r in rows]
    assert "concurrency" in source_ids


def test_broken_links_detected(seeded_vault):
    """The concurrency note links to nonexistent-topic which should be broken."""
    rows = seeded_vault.db.execute(
        "SELECT target_ref FROM links WHERE target_id IS NULL"
    ).fetchall()
    broken_refs = [r["target_ref"] for r in rows]
    assert "nonexistent-topic" in broken_refs


def test_orphan_detection(seeded_vault):
    """The orphan note should have no links in or out."""
    rows = seeded_vault.db.execute("""
        SELECT n.id FROM notes n
        WHERE n.type NOT IN ('index', 'raw')
          AND n.id NOT IN (SELECT DISTINCT target_id FROM links WHERE target_id IS NOT NULL)
          AND n.id NOT IN (SELECT DISTINCT source_id FROM links)
    """).fetchall()
    orphan_ids = [r["id"] for r in rows]
    assert "orphan-note" in orphan_ids


def test_hub_detection(seeded_vault):
    """python-async-patterns should be a hub (linked from multiple notes)."""
    row = seeded_vault.db.execute(
        "SELECT COUNT(*) as c FROM links WHERE target_id = 'python-async-patterns'"
    ).fetchone()
    assert row["c"] >= 2
