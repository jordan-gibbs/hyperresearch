"""Tests for the looot web provider: offline via the httpx transport seam."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from hyperresearch.web import looot_provider
from hyperresearch.web.looot_provider import LoootProvider

PAGE_TEXT = "Long page body about the article. " * 40


def _organic(**overrides: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "title": "Example Article",
        "link": "https://example.com/article",
        "snippet": "Snippet of the article body.",
        "position": 1,
        "date": "May 15, 2025",
    }
    item.update(overrides)
    return item


def _completed(result: dict[str, Any], run_id: str = "run_1") -> httpx.Response:
    return httpx.Response(201, json={"runId": run_id, "status": "completed", "result": result})


def _transport(
    search_result: dict[str, Any],
    fetch_response: httpx.Response,
    seen: list[httpx.Request],
) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        body = json.loads(request.content)
        if body["endpointId"] == "serper-search":
            return _completed(search_result)
        if body["endpointId"] == "serper-webpage":
            return fetch_response
        raise AssertionError(f"unexpected request: {request.url} {body}")

    return httpx.MockTransport(handler)


def test_provider_registered_via_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOOOT_TOKEN", "looot-test")

    from hyperresearch.web.base import get_provider

    prov = get_provider("looot")
    assert prov.name == "looot"


def test_missing_token_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LOOOT_TOKEN", raising=False)

    with pytest.raises(RuntimeError, match="LOOOT_TOKEN"):
        LoootProvider()


def test_search_runs_pinned_endpoint_and_fetches_pages() -> None:
    seen: list[httpx.Request] = []
    fetch = _completed({"markdown": PAGE_TEXT, "metadata": {"title": "Page"}}, "run_2")
    prov = LoootProvider(
        token="looot-test",
        transport=_transport({"organic": [_organic()]}, fetch, seen),
    )

    results = prov.search("solid state batteries", max_results=3)

    assert len(results) == 1
    assert results[0].url == "https://example.com/article"
    assert results[0].title == "Example Article"
    assert results[0].content == PAGE_TEXT.strip()
    assert results[0].metadata == {"position": 1, "published_time": "May 15, 2025"}

    search_request = seen[0]
    assert search_request.url.path == "/v1/runs"
    assert search_request.url.params["wait"] == "30"
    assert search_request.headers["authorization"] == "Bearer looot-test"
    body = json.loads(search_request.content)
    assert body["endpointId"] == "serper-search"
    assert body["input"] == {"q": "solid state batteries", "num": 3}
    assert body["idempotencyKey"]
    assert json.loads(seen[1].content)["input"] == {
        "url": "https://example.com/article",
        "includeMarkdown": True,
    }


def test_search_keeps_snippet_when_fetch_fails() -> None:
    seen: list[httpx.Request] = []
    failed = httpx.Response(
        201,
        json={"runId": "run_2", "status": "failed", "error": {"code": "provider_error", "message": "blocked"}},
    )
    prov = LoootProvider(token="t", transport=_transport({"organic": [_organic()]}, failed, seen))

    results = prov.search("q")

    assert results[0].content == "Snippet of the article body."


def test_search_without_fetch_skips_page_requests() -> None:
    seen: list[httpx.Request] = []
    prov = LoootProvider(
        token="t",
        fetch_content=False,
        transport=_transport({"organic": [_organic(), _organic(link="")]}, _completed({}), seen),
    )

    results = prov.search("q", max_results=5)

    assert [r.url for r in results] == ["https://example.com/article"]
    assert len(seen) == 1


def test_fetch_clips_to_max_characters() -> None:
    seen: list[httpx.Request] = []
    prov = LoootProvider(
        token="t",
        max_characters=100,
        transport=_transport({}, _completed({"text": PAGE_TEXT}), seen),
    )

    page = prov.fetch("https://example.com/article")

    assert len(page.content) == 100
    assert page.title == ""


def test_fetch_raises_on_empty_page() -> None:
    seen: list[httpx.Request] = []
    prov = LoootProvider(token="t", transport=_transport({}, _completed({"markdown": "  "}), seen))

    with pytest.raises(RuntimeError, match="no content"):
        prov.fetch("https://example.com/empty")


def test_failed_run_raises_with_the_api_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            201,
            json={"runId": "r", "status": "failed", "error": {"code": "validation_error", "message": "q is required"}},
        )

    prov = LoootProvider(token="t", transport=httpx.MockTransport(handler))

    with pytest.raises(RuntimeError, match="q is required"):
        prov.search("q")


def test_unfinished_run_is_polled_until_complete(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(looot_provider.time, "sleep", lambda _s: None)
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        if request.method == "POST":
            return httpx.Response(201, json={"runId": "run_9", "status": "running"})
        return _completed({"organic": [_organic()]}, "run_9")

    prov = LoootProvider(token="t", fetch_content=False, transport=httpx.MockTransport(handler))

    results = prov.search("q")

    assert calls == ["POST /v1/runs", "GET /v1/runs/run_9"]
    assert results[0].url == "https://example.com/article"


def test_http_error_propagates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"code": "unauthorized"}})

    prov = LoootProvider(token="bad", transport=httpx.MockTransport(handler))

    with pytest.raises(httpx.HTTPStatusError):
        prov.search("q")
