"""Tests for the Outcrawl web provider: offline via the httpx transport seam."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from hyperresearch.web.outcrawl_provider import OutcrawlProvider

SEARCH_PATH = "/v1/search"
SCRAPE_PATH = "/v1/scrape"


def _hit(**overrides: Any) -> dict[str, Any]:
    hit: dict[str, Any] = {
        "url": "https://example.com/article",
        "title": "Example Article",
        "snippet": "Snippet of the article body.",
        "rank": 1,
    }
    hit.update(overrides)
    return hit


def _scrape(markdown: str, status_code: int = 200, **overrides: Any) -> httpx.Response:
    body: dict[str, Any] = {
        "url": "https://example.com/article",
        "statusCode": status_code,
        "markdown": markdown,
        "metadata": {"title": "Example Article"},
        "usage": {"credits": "1"},
    }
    body.update(overrides)
    return httpx.Response(200, json=body)


def _transport(
    hits: list[dict[str, Any]],
    scrape_response: httpx.Response,
    seen: list[httpx.Request],
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == SEARCH_PATH:
            return httpx.Response(200, json={"hits": hits, "usage": {"credits": "0.5"}})
        if request.url.path == SCRAPE_PATH:
            return scrape_response
        raise AssertionError(f"unexpected request: {request.url}")

    return httpx.MockTransport(handler)


def test_provider_registered_via_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OUTCRAWL_API_KEY", "outcrawl-test")

    from hyperresearch.web.base import get_provider

    prov = get_provider("outcrawl")
    assert prov.name == "outcrawl"


def test_missing_api_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OUTCRAWL_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="OUTCRAWL_API_KEY"):
        OutcrawlProvider()


def test_search_maps_results_and_fetches_content() -> None:
    seen: list[httpx.Request] = []
    page = "# Full page\n\n" + "Body text. " * 40
    transport = _transport([_hit()], _scrape(page), seen)

    results = OutcrawlProvider(api_key="outcrawl-test", transport=transport).search(
        "q", max_results=3
    )

    assert len(results) == 1
    r = results[0]
    assert r.url == "https://example.com/article"
    assert r.title == "Example Article"
    assert r.content == page.strip()
    assert r.metadata == {"rank": 1}

    search, scrape = seen
    assert search.headers["Authorization"] == "Bearer outcrawl-test"
    assert json.loads(search.content) == {"query": "q", "limit": 3}
    assert scrape.headers["Authorization"] == "Bearer outcrawl-test"
    assert json.loads(scrape.content) == {
        "url": "https://example.com/article",
        "formats": ["markdown"],
        "onlyMainContent": True,
    }


def test_search_clamps_limit_to_api_range() -> None:
    seen: list[httpx.Request] = []
    transport = _transport([], _scrape(""), seen)

    OutcrawlProvider(api_key="outcrawl-test", transport=transport).search("q", max_results=50)

    assert json.loads(seen[0].content)["limit"] == 20


def test_search_falls_back_to_snippet_when_fetch_fails() -> None:
    transport = _transport([_hit()], httpx.Response(500), [])

    results = OutcrawlProvider(api_key="outcrawl-test", transport=transport).search("q")

    assert results[0].content == "Snippet of the article body."


def test_search_falls_back_to_snippet_when_page_status_is_an_error() -> None:
    transport = _transport([_hit()], _scrape("# Not Found", status_code=404), [])

    results = OutcrawlProvider(api_key="outcrawl-test", transport=transport).search("q")

    assert results[0].content == "Snippet of the article body."


def test_search_falls_back_to_snippet_when_fetch_is_a_bot_wall() -> None:
    wall = _scrape("Just a moment... Enable JavaScript and cookies to continue")
    transport = _transport([_hit()], wall, [])

    results = OutcrawlProvider(api_key="outcrawl-test", transport=transport).search("q")

    assert results[0].content == "Snippet of the article body."


def test_fetch_clips_content_to_max_characters() -> None:
    transport = _transport([], _scrape("x" * 50), [])

    r = OutcrawlProvider(
        api_key="outcrawl-test", max_characters=20, transport=transport
    ).fetch("https://example.com/p")

    assert r.content == "x" * 20
    assert r.title == "Example Article"


def test_search_without_fetch_content_makes_one_request() -> None:
    seen: list[httpx.Request] = []
    transport = _transport([_hit(), _hit(url="")], _scrape(""), seen)

    results = OutcrawlProvider(
        api_key="outcrawl-test", fetch_content=False, transport=transport
    ).search("q")

    assert [r.content for r in results] == ["Snippet of the article body."]
    assert len(seen) == 1


def test_fetch_no_content_raises() -> None:
    transport = _transport([], _scrape("  \n"), [])

    with pytest.raises(RuntimeError, match="no content"):
        OutcrawlProvider(api_key="outcrawl-test", transport=transport).fetch(
            "https://example.com/p"
        )


def test_fetch_error_status_raises() -> None:
    transport = _transport([], _scrape("# Forbidden", status_code=403), [])

    with pytest.raises(RuntimeError, match="403"):
        OutcrawlProvider(api_key="outcrawl-test", transport=transport).fetch(
            "https://example.com/p"
        )
