"""Tests for the Keenable web provider: offline via the httpx transport seam."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from hyperresearch.web.keenable_provider import KeenableProvider

PAGE_TEXT = "Solid-state batteries replace the liquid electrolyte with a solid one.\n\n" * 3


@pytest.fixture(autouse=True)
def _no_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KEENABLE_API_KEY", raising=False)


def _search_item(**overrides: Any) -> dict[str, Any]:
    # Real responses send `description` empty and the page text in `snippet`.
    item: dict[str, Any] = {
        "title": "Example Article",
        "url": "https://example.com/article",
        "description": "",
        "snippet": PAGE_TEXT,
        "published_at": "2025-09-01T00:00:00Z",
        "acquired_at": "2026-09-03T20:25:13Z",
    }
    item.update(overrides)
    return item


def _transport(
    search_items: list[dict[str, Any]],
    fetch_response: httpx.Response,
    seen: list[httpx.Request],
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.startswith("/v1/search"):
            return httpx.Response(200, json={"query": "q", "results": search_items})
        if request.url.path.startswith("/v1/fetch"):
            return fetch_response
        raise AssertionError(f"unexpected request: {request.url}")

    return httpx.MockTransport(handler)


def test_provider_registered_via_factory() -> None:
    from hyperresearch.web.base import get_provider

    prov = get_provider("keenable")
    assert prov.name == "keenable"


def test_search_without_key_uses_public_endpoint() -> None:
    seen: list[httpx.Request] = []
    transport = _transport([_search_item()], httpx.Response(200), seen)

    KeenableProvider(transport=transport).search("q", max_results=3)

    (search,) = seen
    assert search.method == "POST"
    assert search.url.path == "/v1/search/public"
    assert search.headers["X-Keenable-Title"] == "hyperresearch"
    assert "X-API-Key" not in search.headers
    assert json.loads(search.content) == {"query": "q", "max_results": 3}


def test_api_key_switches_to_keyed_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KEENABLE_API_KEY", "keenable-test")
    seen: list[httpx.Request] = []
    fetched = httpx.Response(200, json={"url": "https://example.com/p", "content": PAGE_TEXT})
    prov = KeenableProvider(transport=_transport([_search_item()], fetched, seen))

    prov.search("q")
    prov.fetch("https://example.com/p")

    search, fetch = seen
    assert search.url.path == "/v1/search"
    assert fetch.url.path == "/v1/fetch"
    assert search.headers["X-API-Key"] == "keenable-test"
    assert fetch.headers["X-API-Key"] == "keenable-test"


def test_search_maps_snippet_to_content() -> None:
    transport = _transport([_search_item()], httpx.Response(200), [])

    results = KeenableProvider(transport=transport).search("q")

    assert len(results) == 1
    r = results[0]
    assert r.url == "https://example.com/article"
    assert r.title == "Example Article"
    assert r.content == PAGE_TEXT.strip()
    assert r.metadata == {"published_at": "2025-09-01T00:00:00Z"}


def test_search_falls_back_to_description_when_snippet_is_empty() -> None:
    item = _search_item(snippet="", description="Short description.")
    transport = _transport([item], httpx.Response(200), [])

    results = KeenableProvider(transport=transport).search("q")

    assert results[0].content == "Short description."


def test_search_clips_content_and_skips_results_without_url() -> None:
    items = [_search_item(snippet="x" * 50), _search_item(url="")]
    transport = _transport(items, httpx.Response(200), [])

    results = KeenableProvider(max_characters=20, transport=transport).search("q")

    assert [r.content for r in results] == ["x" * 20]


def test_search_caps_requested_results_at_the_api_limit() -> None:
    seen: list[httpx.Request] = []
    transport = _transport([_search_item()] * 3, httpx.Response(200), seen)

    results = KeenableProvider(transport=transport).search("q", max_results=200)

    assert json.loads(seen[0].content)["max_results"] == 50
    assert len(results) == 3


def test_fetch_maps_content_title_and_metadata() -> None:
    seen: list[httpx.Request] = []
    page = {
        "url": "https://example.com/p",
        "title": "Example Page",
        "content": PAGE_TEXT,
        "description": "",
        "author": "Jane Doe",
        "published_at": 1789821484,
    }
    transport = _transport([], httpx.Response(200, json=page), seen)

    r = KeenableProvider(transport=transport).fetch("https://example.com/p")

    assert r.url == "https://example.com/p"
    assert r.title == "Example Page"
    assert r.content == PAGE_TEXT.strip()
    assert r.metadata == {"author": "Jane Doe", "published_at": "2026-09-19T12:38:04+00:00"}

    (fetch,) = seen
    assert fetch.method == "GET"
    assert fetch.url.path == "/v1/fetch/public"
    assert fetch.url.params["url"] == "https://example.com/p"
    assert fetch.headers["X-Keenable-Title"] == "hyperresearch"


def test_fetch_no_content_raises() -> None:
    transport = _transport([], httpx.Response(200, json={"url": "https://example.com/p"}), [])

    with pytest.raises(RuntimeError, match="no content"):
        KeenableProvider(transport=transport).fetch("https://example.com/p")
