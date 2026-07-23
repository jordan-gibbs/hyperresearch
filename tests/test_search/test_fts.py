"""Tests for full-text search."""

import sqlite3

import pytest

from hyperresearch.search.filters import SearchFilters
from hyperresearch.search.fts import SearchQueryError, preprocess_query, search_fts


def test_preprocess_simple_query():
    assert '"python"*' in preprocess_query("python")


def test_preprocess_quoted_phrase():
    result = preprocess_query('"async await"')
    assert '"async await"' in result


def test_preprocess_hyphenated_word_stays_a_phrase():
    """Bare tokens are emitted inside double quotes, where FTS5 reads `-` as
    a plain character, not the NOT operator — so `foo-bar` is a valid phrase
    query as-is. It must NOT be split into AND'd tokens, which would loosen
    phrase matching."""
    result = preprocess_query("foo-bar")
    assert '"foo-bar"*' in result


def test_preprocess_mixed_hyphen_query():
    result = preprocess_query("python 3-async")
    assert '"python"*' in result
    assert '"3-async"*' in result


def test_preprocess_strips_stray_quote():
    """Quoted phrases survive whole, but a single unbalanced `"` inside a
    bare word would otherwise break FTS5 syntax."""
    result = preprocess_query('foo"bar')
    assert '"foobar"*' in result


def test_preprocess_passthrough_operators():
    query = "python AND async"
    assert preprocess_query(query) == query


def test_search_returns_results(seeded_vault):
    results = search_fts(seeded_vault.db, "python")
    assert len(results) > 0
    assert any(r["id"] == "python-async-patterns" for r in results)


def test_search_with_tag_filter(seeded_vault):
    filters = SearchFilters(tags=["rust"])
    results = search_fts(seeded_vault.db, "memory", filters=filters)
    assert all("rust" in r["tags"] for r in results)


def test_search_with_status_filter(seeded_vault):
    filters = SearchFilters(status="draft")
    results = search_fts(seeded_vault.db, "orphan", filters=filters)
    assert all(r["status"] == "draft" for r in results)


def test_search_no_results(seeded_vault):
    results = search_fts(seeded_vault.db, "zzzznonexistenttermzzzz")
    assert len(results) == 0


def test_search_limit(seeded_vault):
    results = search_fts(seeded_vault.db, "concurrency", limit=1)
    assert len(results) <= 1


def test_filter_by_date(seeded_vault):
    filters = SearchFilters(after="2020-01-01")
    results = search_fts(seeded_vault.db, "python", filters=filters)
    assert len(results) > 0


def test_filter_by_path_glob(seeded_vault):
    filters = SearchFilters(path_glob="notes/python/*")
    results = search_fts(seeded_vault.db, "python", filters=filters)
    assert all("python" in r["path"] for r in results)


# --- Degenerate queries must not masquerade as "no results" -------------------
# Previously every sqlite3.OperationalError was swallowed and [] returned, so an
# invalid query and a corrupt index both looked identical to an empty topic.


@pytest.mark.parametrize("query", ["", "   ", "***", "()", "^^^", "{}"])
def test_degenerate_query_raises_rather_than_returning_empty(seeded_vault, query):
    """A query with no searchable terms is an error, not zero results."""
    with pytest.raises(SearchQueryError):
        search_fts(seeded_vault.db, query)


def test_no_results_is_still_empty_not_an_error(seeded_vault):
    """A valid query that matches nothing must stay a normal empty result."""
    assert search_fts(seeded_vault.db, "zzzznonexistenttermzzzz") == []


def test_broken_index_surfaces_instead_of_returning_empty(seeded_vault):
    """A missing FTS table must raise, not look like a topic with no notes."""
    seeded_vault.db.execute("DROP TABLE IF EXISTS notes_fts")
    with pytest.raises(sqlite3.OperationalError, match="notes_fts"):
        search_fts(seeded_vault.db, "python")
