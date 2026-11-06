"""Tests for the Sofya web provider: offline via the httpx transport seam."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from hyperresearch.web.sofya_provider import SofyaProvider

SEARCH_PATH = "/v1/search"
FETCH_PATH = "/v1/fetch"


def _search_item(**overrides: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "title": "Example Article",
        "url": "https://example.com/article",
        "content": "# Example Article\n\nFull page text.",
        "description": "Snippet of the article body.",
        "fetched": True,
        "published_date": "2026-03-08",
        "sublinks": [],
        "table": {},
    }
    item.update(overrides)
    return item


def _fetch_item(**overrides: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "title": "Example Page",
        "url": "https://example.com/p",
        "content": "# Example Page\n\nBody text.",
        "raw_html": None,
        "published_time": None,
        "success": True,
        "error": None,
        "low_content": False,
        "notice": None,
    }
    item.update(overrides)
    return item


def _transport(
    seen: list[httpx.Request],
    search_items: list[dict[str, Any]] | None = None,
    fetch_items: list[dict[str, Any]] | None = None,
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == SEARCH_PATH:
            return httpx.Response(200, json={"results": search_items or []})
        if request.url.path == FETCH_PATH:
            return httpx.Response(200, json={"results": fetch_items or []})
        raise AssertionError(f"unexpected request: {request.url}")

    return httpx.MockTransport(handler)


def test_provider_registered_via_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOFYA_API_KEY", "sofya-test")

    from hyperresearch.web.base import get_provider

    prov = get_provider("sofya")
    assert prov.name == "sofya"


def test_missing_api_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SOFYA_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="SOFYA_API_KEY"):
        SofyaProvider()


def test_search_maps_results_in_one_request() -> None:
    seen: list[httpx.Request] = []
    transport = _transport(seen, search_items=[_search_item()])

    results = SofyaProvider(api_key="sofya-test", transport=transport).search("q", max_results=3)

    assert len(results) == 1
    r = results[0]
    assert r.url == "https://example.com/article"
    assert r.title == "Example Article"
    assert r.content == "# Example Article\n\nFull page text."
    assert r.metadata == {"published_date": "2026-03-08"}

    (search,) = seen
    assert search.method == "POST"
    assert search.headers["Authorization"] == "Bearer sofya-test"
    assert json.loads(search.content) == {
        "query": "q",
        "max_results": 3,
        "search_depth": "basic",
        "topic": "general",
    }


def test_search_falls_back_to_snippet_and_skips_missing_urls() -> None:
    items = [
        _search_item(content="", fetched=False, published_date=None),
        _search_item(url=""),
    ]
    transport = _transport([], search_items=items)

    results = SofyaProvider(api_key="sofya-test", transport=transport).search("q")

    assert [r.content for r in results] == ["Snippet of the article body."]
    assert results[0].metadata == {}


def test_search_passes_depth_and_topic() -> None:
    seen: list[httpx.Request] = []
    transport = _transport(seen)

    SofyaProvider(
        api_key="sofya-test", search_depth="snippets", topic="news", transport=transport
    ).search("q")

    body = json.loads(seen[0].content)
    assert body["search_depth"] == "snippets"
    assert body["topic"] == "news"


def test_search_http_error_raises() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(401))

    with pytest.raises(httpx.HTTPStatusError):
        SofyaProvider(api_key="sofya-test", transport=transport).search("q")


def test_fetch_returns_markdown() -> None:
    seen: list[httpx.Request] = []
    item = _fetch_item(published_time="2026-01-02")
    transport = _transport(seen, fetch_items=[item])

    r = SofyaProvider(api_key="sofya-test", transport=transport).fetch("https://example.com/p")

    assert r.url == "https://example.com/p"
    assert r.title == "Example Page"
    assert r.content == "# Example Page\n\nBody text."
    assert r.metadata == {"published_time": "2026-01-02"}
    assert json.loads(seen[0].content) == {"urls": ["https://example.com/p"]}


def test_fetch_failure_raises_with_error() -> None:
    item = _fetch_item(success=False, content="", error="HTTP 404")
    transport = _transport([], fetch_items=[item])

    with pytest.raises(RuntimeError, match="HTTP 404"):
        SofyaProvider(api_key="sofya-test", transport=transport).fetch("https://example.com/p")


def test_fetch_no_content_raises() -> None:
    transport = _transport([], fetch_items=[_fetch_item(content="  \n")])

    with pytest.raises(RuntimeError, match="no content"):
        SofyaProvider(api_key="sofya-test", transport=transport).fetch("https://example.com/p")


def test_fetch_empty_results_raises() -> None:
    transport = _transport([], fetch_items=[])

    with pytest.raises(RuntimeError, match="no result"):
        SofyaProvider(api_key="sofya-test", transport=transport).fetch("https://example.com/p")
