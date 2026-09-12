"""Tests for the Serply web provider: offline via the httpx transport seam."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from hyperresearch.web.serply_provider import SerplyProvider

SEARCH_PATH = "/v1/search/"
FETCH_PATH = "/v1/request"


def _search_item(**overrides: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "title": "Example Article",
        "description": "Snippet of the article body.",
        "position": 1,
        "result_type": "organic",
        "metadata": {"published_time": "May 15, 2025"},
        "link": "https://example.com/article",
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
        if request.url.path == SEARCH_PATH:
            return httpx.Response(200, json={"results": search_items})
        if request.url.path == FETCH_PATH:
            return fetch_response
        raise AssertionError(f"unexpected request: {request.url}")

    return httpx.MockTransport(handler)


def test_provider_registered_via_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERPLY_API_KEY", "serply-test")

    from hyperresearch.web.base import get_provider

    prov = get_provider("serply")
    assert prov.name == "serply"


def test_missing_api_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SERPLY_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="SERPLY_API_KEY"):
        SerplyProvider()


def test_search_maps_results_and_fetches_content() -> None:
    seen: list[httpx.Request] = []
    page = "# Full page\n\n" + "Body text. " * 40
    transport = _transport([_search_item()], httpx.Response(200, text=page), seen)

    results = SerplyProvider(api_key="serply-test", transport=transport).search("q", max_results=3)

    assert len(results) == 1
    r = results[0]
    assert r.url == "https://example.com/article"
    assert r.title == "Example Article"
    assert r.content == page.strip()
    assert r.metadata == {"position": 1, "published_time": "May 15, 2025"}

    search, fetch = seen
    assert search.headers["X-Api-Key"] == "serply-test"
    assert search.url.params["q"] == "q"
    assert search.url.params["num"] == "3"
    assert json.loads(fetch.content) == {
        "url": "https://example.com/article",
        "response_type": "markdown",
    }


def test_search_falls_back_to_snippet_when_fetch_fails() -> None:
    transport = _transport([_search_item()], httpx.Response(500), [])

    results = SerplyProvider(api_key="serply-test", transport=transport).search("q")

    assert results[0].content == "Snippet of the article body."


def test_search_falls_back_to_snippet_when_fetch_is_a_bot_wall() -> None:
    wall = httpx.Response(200, text="Just a moment... Enable JavaScript and cookies to continue")
    transport = _transport([_search_item()], wall, [])

    results = SerplyProvider(api_key="serply-test", transport=transport).search("q")

    assert results[0].content == "Snippet of the article body."


def test_fetch_clips_content_to_max_characters() -> None:
    transport = _transport([], httpx.Response(200, text="x" * 50), [])

    r = SerplyProvider(api_key="serply-test", max_characters=20, transport=transport).fetch(
        "https://example.com/p"
    )

    assert r.content == "x" * 20


def test_search_without_fetch_content_makes_one_request() -> None:
    seen: list[httpx.Request] = []
    transport = _transport([_search_item(), _search_item(link="")], httpx.Response(200), seen)

    results = SerplyProvider(
        api_key="serply-test", fetch_content=False, transport=transport
    ).search("q")

    assert [r.content for r in results] == ["Snippet of the article body."]
    assert len(seen) == 1


def test_fetch_no_content_raises() -> None:
    transport = _transport([], httpx.Response(200, text="  \n"), [])

    with pytest.raises(RuntimeError, match="no content"):
        SerplyProvider(api_key="serply-test", transport=transport).fetch("https://example.com/p")
