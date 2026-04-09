"""Tests for full-text search."""

from hyperresearch.search.fts import search_fts, preprocess_query
from hyperresearch.search.filters import SearchFilters


def test_preprocess_simple_query():
    assert '"python"*' in preprocess_query("python")


def test_preprocess_quoted_phrase():
    result = preprocess_query('"async await"')
    assert '"async await"' in result


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
