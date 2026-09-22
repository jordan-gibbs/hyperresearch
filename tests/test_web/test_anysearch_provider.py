"""Exercise AnySearch's documented REST contract with an offline HTTP transport."""

from __future__ import annotations

import json
import threading
from typing import Any

import httpx
import pytest

from hyperresearch.core.config import JunkGates
from hyperresearch.web.base import get_provider


def _provider(handler, **kwargs):
    from hyperresearch.web.anysearch_provider import AnySearchProvider

    # Request-shape tests exercise discovery only; extraction has its own cases.
    kwargs.setdefault("fetch_content", False)
    return AnySearchProvider(transport=httpx.MockTransport(handler), **kwargs)


def _ok(data: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json={
        "code": 0, "message": "success", "request_id": "test-request", "data": data,
    })


def _item(**overrides: Any) -> dict[str, Any]:
    return {
        "url": "https://example.com/article", "title": "Research result",
        "snippet": "Search excerpt", "content": "Search content", **overrides,
    }


def test_factory_selects_anonymous_provider(monkeypatch):
    monkeypatch.delenv("ANYSEARCH_API_KEY", raising=False)
    assert get_provider("anysearch").name == "anysearch"


@pytest.mark.parametrize("key,expected", [(None, None), (" key-123 ", "Bearer key-123")])
def test_search_uses_optional_bearer_auth_and_maps_results(monkeypatch, key, expected):
    monkeypatch.delenv("ANYSEARCH_API_KEY", raising=False)
    seen = []

    def handler(request):
        seen.append(request)
        return _ok({"results": [_item(score=0.9), _item(url="")], "metadata": {
            "total_results": 2, "search_time_ms": 10,
        }})

    results = _provider(handler, api_key=key).search("  research query  ", max_results=2)
    assert [(r.url, r.title, r.content) for r in results] == [
        ("https://example.com/article", "Research result", "Search content"),
    ]
    assert results[0].metadata["score"] == 0.9
    assert results[0].metadata["anysearch_request_id"] == "test-request"
    assert results[0].fetched_at.tzinfo is not None
    assert str(seen[0].url) == "https://api.anysearch.com/v1/search"
    assert json.loads(seen[0].content) == {"query": "research query", "max_results": 2}
    assert seen[0].headers.get("Authorization") == expected
    assert seen[0].headers["X-Anysearch-Client"] == "hyperresearch"


def test_environment_key_and_explicit_anonymous_override(monkeypatch):
    monkeypatch.setenv("ANYSEARCH_API_KEY", " env-key ")
    auth = []

    def handler(request):
        auth.append(request.headers.get("Authorization"))
        return _ok({"results": []})

    _provider(handler).search("one")
    _provider(handler, api_key="").search("two")
    assert auth == ["Bearer env-key", None]


def test_search_falls_back_to_snippet_and_respects_limit():
    provider = _provider(lambda _: _ok({"results": [
        _item(content=None), _item(url="https://example.com/second"),
    ]}))
    results = provider.search("query", max_results=1)
    assert len(results) == 1
    assert results[0].content == "Search excerpt"


@pytest.mark.parametrize("fetch_content", [False, True])
@pytest.mark.parametrize("batch", [False, True])
def test_search_preserves_response_metadata_separately_from_result_metadata(fetch_content, batch):
    def handler(request):
        if request.url.path == "/v1/extract":
            return _ok({"url": "https://example.com/article", "content": "Page evidence. " * 40})
        return _ok({
            "results": [_item(score=0.9, metadata={"language": "en"})],
            "metadata": {"total_results": 8, "search_time_ms": 123, "routing": {"domain": "general"}},
        })

    provider = _provider(handler, fetch_content=fetch_content)
    results = (
        provider.batch_search([{"query": "q"}])[0]["results"]
        if batch else provider.search("q")
    )
    metadata = results[0].metadata
    assert metadata["anysearch_metadata"] == {
        "total_results": 8, "search_time_ms": 123, "routing": {"domain": "general"},
    }
    assert metadata["metadata"] == {"language": "en"}
    assert metadata["score"] == 0.9
    assert metadata["anysearch_request_id"] == "test-request"


def _search_and_extract_transport(extracted, seen):
    def handler(request):
        seen.append(request)
        if request.url.path == "/v1/search":
            return _ok({"results": [_item(score=0.9)]})
        assert request.url.path == "/v1/extract"
        assert json.loads(request.content) == {"url": "https://example.com/article"}
        return extracted

    return httpx.MockTransport(handler)


def test_default_search_fetches_page_text_and_preserves_search_metadata():
    from hyperresearch.web.anysearch_provider import AnySearchProvider

    seen = []
    text = "# Source page\n\n" + "Detailed primary evidence. " * 25
    transport = _search_and_extract_transport(
        _ok({"url": "https://example.com/article", "title": "Full page", "content": text}), seen,
    )
    result = AnySearchProvider(transport=transport).search("query")[0]
    assert result.content == text
    assert result.title == "Research result"
    assert result.metadata["score"] == 0.9
    assert [request.url.path for request in seen] == ["/v1/search", "/v1/extract"]


@pytest.mark.parametrize("batch", [False, True])
@pytest.mark.parametrize("gates,page_text,use_extracted", [
    (JunkGates(min_content_chars=5), "Short usable text.", True),
    (JunkGates(min_content_chars=1000), "Research evidence. " * 30, False),
    (JunkGates(extra_junk_signals=("custom block",)), "custom block " + "Evidence. " * 40, False),
    (JunkGates(extra_login_signals=("members only",)), "members only " + "Evidence. " * 40, False),
], ids=["short-page", "stricter-minimum", "custom-junk", "custom-login"])
def test_factory_passes_configured_gates_to_search(monkeypatch, batch, gates, page_text, use_extracted):
    def handler(_transport, request):
        if request.url.path == "/v1/search":
            return _ok({"results": [_item()]})
        assert request.url.path == "/v1/extract"
        return _ok({"url": "https://example.com/article", "title": "Page", "content": page_text})

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", handler)
    provider = get_provider("anysearch", gates=gates)
    results = provider.batch_search([{"query": "q"}])[0]["results"] if batch else provider.search("q")
    assert results[0].content == (page_text if use_extracted else "Search content")


@pytest.mark.parametrize("response", [
    httpx.Response(500, text="Unavailable"),
    _ok({"url": "https://example.com/article", "content": ""}),
    _ok({"url": "https://example.com/article", "content": "Just a moment... " * 30}),
    _ok({"url": "https://example.com/login", "content": "Members area " * 50}),
])
def test_search_keeps_excerpt_when_page_is_unavailable_or_unusable(response):
    from hyperresearch.web.anysearch_provider import AnySearchProvider

    seen = []
    transport = _search_and_extract_transport(response, seen)
    results = AnySearchProvider(transport=transport).search("query")
    assert len(results) == 1
    assert results[0].content == "Search content"
    assert results[0].metadata["score"] == 0.9
    assert len(seen) == 2


def test_search_can_skip_extraction_entirely():
    seen = []

    def handler(request):
        seen.append(request)
        assert request.url.path == "/v1/search"
        return _ok({"results": [_item()]})

    results = _provider(handler, fetch_content=False).search("query")
    assert results[0].content == "Search content"
    assert len(seen) == 1


@pytest.mark.parametrize("maximum", [20, 8000])
def test_extract_clips_page_text_to_configured_limit(maximum):
    from hyperresearch.web.anysearch_provider import AnySearchProvider

    body = "Page text. " * 1000
    transport = httpx.MockTransport(lambda _: _ok({"url": "https://example.com", "content": body}))
    kwargs = {} if maximum == 8000 else {"max_characters": maximum}
    result = AnySearchProvider(transport=transport, **kwargs).fetch("https://example.com")
    assert result.content == body[:maximum]


@pytest.mark.parametrize("maximum", [0, -1, True])
def test_extract_limit_must_be_positive_integer(maximum):
    with pytest.raises(ValueError, match="max_characters"):
        _provider(lambda _: pytest.fail("invalid limit made a request"), max_characters=maximum)


def test_vertical_search_preserves_structured_empty_parameters():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return _ok({"results": []})

    _provider(handler).search(
        "library docs", tag="code.doc", params={"library": "httpx", "optional": ""},
        zone="intl", language="en",
    )
    assert seen == [{
        "query": "library docs", "max_results": 5, "tag": "code.doc",
        "params": {"library": "httpx", "optional": ""}, "zone": "intl", "language": "en",
    }]


def test_discover_sub_domains_uses_repeated_query_parameters():
    seen = []
    domains = [{"domain": "code", "sub_domains": [{
        "sub_domain": "code.doc", "description": "Developer documentation",
        "params": {"library": {"description": "Library name", "required": True}},
    }]}]

    def handler(request):
        seen.append(request)
        return _ok({"domains": domains})

    assert _provider(handler).get_sub_domains(["code", "academic"]) == domains
    assert seen[0].method == "GET"
    assert seen[0].url.path == "/v1/sub-domains"
    assert seen[0].url.params.get_list("domain") == ["code", "academic"]


def test_extract_uses_returned_canonical_url_and_content():
    seen = []

    def handler(request):
        seen.append(request)
        return _ok({
            "url": "https://example.com/final", "title": "Page", "content": "# Full text",
            "requested_url": "https://unrelated.example/spoofed",
        })

    result = _provider(handler).fetch("https://example.com/start")
    assert (result.url, result.title, result.content) == (
        "https://example.com/final", "Page", "# Full text",
    )
    assert result.metadata["requested_url"] == "https://example.com/start"
    assert seen[0].url.path == "/v1/extract"
    assert json.loads(seen[0].content) == {"url": "https://example.com/start"}


@pytest.mark.parametrize("content", [None, "", "   "])
def test_extract_rejects_empty_content(content):
    provider = _provider(lambda _: _ok({"url": "https://example.com", "content": content}))
    with pytest.raises(RuntimeError, match="content"):
        provider.fetch("https://example.com")


@pytest.mark.parametrize("body", [[], {"code": 0, "data": []}, {"code": 0, "data": {}},
                                 {"code": 0, "data": {"results": "not a list"}},
                                 {"code": 0, "data": {"results": ["not an object"]}}])
def test_search_rejects_malformed_responses(body):
    provider = _provider(lambda _: httpx.Response(200, json=body))
    with pytest.raises(RuntimeError, match="AnySearch"):
        provider.search("query")


@pytest.mark.parametrize("operation", ["search", "fetch", "get_sub_domains"])
def test_valid_response_can_omit_code(operation):
    responses = {
        "search": {"results": [_item()]},
        "fetch": {"url": "https://example.com/article", "title": "Page", "content": "Full text"},
        "get_sub_domains": {"domains": [{"domain": "code", "sub_domains": []}]},
    }
    provider = _provider(lambda _: httpx.Response(200, json={"data": responses[operation]}))
    if operation == "search":
        assert provider.search("q")[0].content == "Search content"
    elif operation == "fetch":
        assert provider.fetch("https://example.com/article").content == "Full text"
    else:
        assert provider.get_sub_domains(["code"]) == [{"domain": "code", "sub_domains": []}]


@pytest.mark.parametrize("status,body", [
    (429, {"data": {"results": [_item()]}}),
    (200, {"code": -1, "data": {"results": [_item()]}}),
    (200, {"code": None, "data": {"results": [_item()]}}),
    (200, {"data": []}),
])
def test_optional_code_does_not_hide_errors_or_malformed_data(status, body):
    with pytest.raises(RuntimeError, match="AnySearch"):
        _provider(lambda _: httpx.Response(status, json=body)).search("q")


@pytest.mark.parametrize("status,code", [(200, -1), (401, -1), (429, -1), (503, 0)])
def test_api_failures_include_request_id_without_retrying(status, code):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={
            "code": code, "message": "Service unavailable", "request_id": "req-error", "data": None,
        })

    with pytest.raises(RuntimeError, match="req-error"):
        _provider(handler, api_key="invalid-key").search("query")
    assert len(calls) == 1


def test_non_json_failure_is_readable():
    with pytest.raises(RuntimeError, match="502"):
        _provider(lambda _: httpx.Response(502, text="Bad Gateway")).search("query")


def test_timeout_is_readable():
    def handler(request):
        raise httpx.ReadTimeout("timed out", request=request)

    with pytest.raises(RuntimeError, match="timed out"):
        _provider(handler).search("query")


@pytest.mark.parametrize("kwargs", [
    {"query": " "}, {"query": "q", "max_results": 0}, {"query": "q", "max_results": 11},
    {"query": "q", "max_results": True}, {"query": "q", "params": {"library": "x"}},
    {"query": "q", "zone": "invalid"}, {"query": "q", "params": "bad", "tag": "code.doc"},
])
def test_bad_search_input_never_reaches_network(kwargs):
    def handler(_):
        pytest.fail("invalid inputs must not make a request")

    with pytest.raises(ValueError):
        _provider(handler).search(**kwargs)


@pytest.mark.parametrize("url", ["file:///tmp/private", "not-a-url", "https://u:secret@example.com"])
def test_extract_rejects_non_web_or_credential_urls(url):
    with pytest.raises(ValueError):
        _provider(lambda _: pytest.fail("invalid URL was sent")).fetch(url)


@pytest.mark.parametrize("queries", [[], [{}] * 6, [{"query": "ok"}, {"query": ""}],
                                    [{"query": "ok", "typo": 1}], {"query": "not a list"}])
def test_invalid_batch_is_rejected_before_any_requests(queries):
    with pytest.raises(ValueError):
        _provider(lambda _: pytest.fail("invalid batch was sent")).batch_search(queries)


@pytest.mark.parametrize("value", [float("inf"), float("nan"), {"not JSON"}])
def test_non_json_parameters_reject_entire_batch_before_requests(value):
    queries = [
        {"query": "good"},
        {"query": "bad", "tag": "code.doc", "params": {"library": value}},
    ]
    with pytest.raises(ValueError, match="JSON"):
        _provider(lambda _: pytest.fail("invalid batch was sent")).batch_search(queries)


def test_batch_runs_concurrently_preserving_order_and_partial_failures():
    # All requests must enter the transport before any finishes: sequential
    # implementations break the barrier. No timing/speed assertions needed.
    barrier = threading.Barrier(3, timeout=5)

    def handler(request):
        query = json.loads(request.content)["query"]
        barrier.wait()
        if query == "broken":
            return httpx.Response(429, json={"code": -1, "message": "Rate limited"})
        return _ok({"results": [_item(title=query)]})

    results = _provider(handler).batch_search([
        {"query": "first", "max_results": 1}, {"query": "broken"}, {"query": "third"},
    ])
    assert [r["query"] for r in results] == ["first", "broken", "third"]
    assert results[0]["results"][0].title == "first"
    assert results[1]["results"] == []
    assert "Rate limited" in results[1]["error"]
    assert results[2]["results"][0].title == "third"
