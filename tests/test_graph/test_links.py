"""Tests for link parsing and graph operations."""

from hyperresearch.core.patterns import WIKI_LINK_RE, strip_code


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
    cleaned = strip_code(text)
    matches = WIKI_LINK_RE.findall(cleaned)
    assert len(matches) == 1
    assert "real-link" in matches[0]


def test_wiki_link_not_in_inline_code():
    text = "Use `[[not-a-link]]` but also [[real-link]]"
    cleaned = strip_code(text)
    matches = WIKI_LINK_RE.findall(cleaned)
    assert len(matches) == 1
    assert "real-link" in matches[0]


def _links(text: str) -> list[str]:
    return WIKI_LINK_RE.findall(strip_code(text))


# --- Fence length is honoured (#140) ------------------------------------------


def test_issue_140_odd_inner_fence_does_not_leak():
    # The #129 builtin provider fences a <pre> holding ``` with ````.
    text = "````\n```\n[[ -n y ]]\n````\n\n[[real-link]]"
    assert _links(text) == ["real-link"]


def test_longer_outer_fence_holds_inner_fenced_block():
    text = (
        "`````markdown\n"
        "```bash\n[[ -f x ]]\n```\n"
        "````\n[[inside-too]]\n"
        "`````\n"
        "after [[real-link]]"
    )
    assert _links(text) == ["real-link"]


def test_closing_fence_may_be_longer_than_opening():
    text = "```\n[[code]]\n`````\n[[real-link]]"
    assert _links(text) == ["real-link"]


def test_fence_line_with_trailing_text_does_not_close():
    text = "```\n``` not a closer [[code]]\n```\n[[real-link]]"
    assert _links(text) == ["real-link"]


def test_indented_fence_in_list_item():
    text = "- step:\n    ```bash\n    [[ -n y ]]\n    ```\n- see [[real-link]]"
    assert _links(text) == ["real-link"]


def test_unclosed_fence_runs_to_end_of_text():
    # CommonMark: an unclosed fence runs to the end of the document. Losing
    # the links after a broken fence beats parsing the code as links.
    text = "[[before]]\n```\n[[ -n y ]]\n[[swallowed]]"
    assert _links(text) == ["before"]


def test_double_backtick_span_holding_single_backtick():
    text = "Run `` echo `x` [[x]] `` then read [[real-link]]"
    assert _links(text) == ["real-link"]


def test_inline_span_closes_only_on_equal_length_run():
    text = "`a``[[x]]` and ``b`[[y]]`` and [[real-link]]"
    assert _links(text) == ["real-link"]


def test_mid_line_triple_backticks_are_an_inline_span():
    # Not a fence (not at line start), so it is an inline span of length 3,
    # stripped as the old regex did.
    text = "Use ```[[x]]``` or [[real-link]]"
    assert _links(text) == ["real-link"]


def test_unmatched_backtick_run_is_literal():
    text = "a stray ` backtick, then [[real-link]] and ``` more [[other]]"
    assert _links(text) == ["real-link", "other"]


def test_stripped_span_cannot_fuse_brackets():
    assert _links("[`x`[y]]") == []


def test_strip_keeps_line_numbers():
    text = "a\n```\none\ntwo\n```\n`multi\nline`\n[[real-link]]"
    cleaned = strip_code(text)
    assert cleaned.count("\n") == text.count("\n")
    assert cleaned.split("\n")[7] == "[[real-link]]"

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
