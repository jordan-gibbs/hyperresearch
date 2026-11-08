"""Tests for the SpecStream web provider: offline via the httpx transport seam."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from hyperresearch.web.specstream_provider import SpecStreamProvider

SEARCH_PATH = "/v1/web-search"
EXTRACT_PATH = "/v1/extract"


def _source(**overrides: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "url": "https://example.com/article",
        "title": "Example Article",
        "site": "example.com",
        "snippet": "Snippet of the article body.",
        "published": "2026-04-01",
        "cited": True,
    }
    item.update(overrides)
    return item


def _page(url: str = "https://example.com/article", **overrides: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "url": url,
        "status": "ok",
        "title": "Example Article",
        "text": "# Full page\n\n" + "Body text. " * 40,
        "read_from": "live",
    }
    item.update(overrides)
    return item


def _transport(
    search_data: dict[str, Any],
    extract_response: httpx.Response,
    seen: list[httpx.Request],
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == SEARCH_PATH:
            return httpx.Response(200, json={"data": search_data})
        if request.url.path == EXTRACT_PATH:
            return extract_response
        raise AssertionError(f"unexpected request: {request.url}")

    return httpx.MockTransport(handler)


def _ok(*pages: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json={"data": {"results": list(pages)}})


def test_provider_registered_via_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SPECSTREAM_API_KEY", "ss-test")

    from hyperresearch.web.base import get_provider

    prov = get_provider("specstream")
    assert prov.name == "specstream"


def test_missing_api_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SPECSTREAM_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="SPECSTREAM_API_KEY"):
        SpecStreamProvider()


def test_search_maps_sources_rows_answer_and_reads_pages() -> None:
    seen: list[httpx.Request] = []
    data = {
        "kind": "fact",
        "answer": {"value": "42", "page": "https://example.com/article"},
        "sources": [_source()],
        "rows": [
            {"name": "Example", "page": "https://example.com/article", "probability": 0.9},
            {
                "name": "Other",
                "page": "https://other.org/x",
                "snippet": "Other snippet.",
                "probability": 0.5,
            },
        ],
    }
    page = _page()
    transport = _transport(data, _ok(page, _page("https://other.org/x", status="empty", text="")), seen)

    results = SpecStreamProvider(api_key="ss-test", transport=transport).search("q", max_results=3)

    assert [r.url for r in results] == ["https://example.com/article", "https://other.org/x"]
    first, second = results
    assert first.title == "Example Article"
    assert first.content == page["text"].strip()
    assert first.metadata == {
        "published_date": "2026-04-01",
        "cited": True,
        "probability": 0.9,
        "row_name": "Example",
        "answer": "42",
    }
    assert second.content == "Other snippet."

    search, extract = seen
    assert search.headers["Authorization"] == "Bearer ss-test"
    assert search.url.params["q"] == "q"
    assert search.url.params["num"] == "3"
    assert json.loads(extract.content) == {
        "urls": ["https://example.com/article", "https://other.org/x"],
        "format": "markdown",
    }


def test_search_falls_back_to_snippet_when_extract_fails() -> None:
    transport = _transport({"sources": [_source()]}, httpx.Response(500), [])

    results = SpecStreamProvider(api_key="ss-test", transport=transport).search("q")

    assert results[0].content == "Snippet of the article body."


def test_search_falls_back_to_snippet_when_page_is_a_bot_wall() -> None:
    wall = _page(text="Just a moment... Enable JavaScript and cookies to continue")
    transport = _transport({"sources": [_source()]}, _ok(wall), [])

    results = SpecStreamProvider(api_key="ss-test", transport=transport).search("q")

    assert results[0].content == "Snippet of the article body."


def test_search_without_fetch_content_makes_one_request() -> None:
    seen: list[httpx.Request] = []
    data = {"sources": [_source(), _source(url=""), _source()]}
    transport = _transport(data, _ok(), seen)

    results = SpecStreamProvider(
        api_key="ss-test", fetch_content=False, transport=transport
    ).search("q")

    assert [r.content for r in results] == ["Snippet of the article body."]
    assert len(seen) == 1


def test_search_trims_to_max_results() -> None:
    sources = [_source(url=f"https://example.com/{i}") for i in range(5)]
    transport = _transport({"sources": sources}, _ok(), [])

    results = SpecStreamProvider(
        api_key="ss-test", fetch_content=False, transport=transport
    ).search("q", max_results=2)

    assert len(results) == 2


def test_fetch_returns_markdown_clipped_to_max_characters() -> None:
    seen: list[httpx.Request] = []
    transport = _transport({}, _ok(_page("https://example.com/p", text="x" * 50)), seen)

    r = SpecStreamProvider(api_key="ss-test", max_characters=20, transport=transport).fetch(
        "https://example.com/p"
    )

    assert r.content == "x" * 20
    assert r.metadata == {"read_from": "live"}
    assert json.loads(seen[0].content) == {"urls": ["https://example.com/p"], "format": "markdown"}


def test_fetch_without_text_raises() -> None:
    page = _page("https://example.com/p", status="blocked", text="")
    transport = _transport({}, _ok(page), [])

    with pytest.raises(RuntimeError, match="blocked"):
        SpecStreamProvider(api_key="ss-test", transport=transport).fetch("https://example.com/p")
