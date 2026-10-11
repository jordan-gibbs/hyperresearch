"""Tests for the Firecrawl web provider: offline via the httpx transport seam.

The crawl4ai fallback is replaced by a recording fake, and DNS is stubbed so
the SSRF gate runs without the network.
"""

from __future__ import annotations

import ipaddress
import json
from typing import Any

import httpx
import pytest

import hyperresearch.web.firecrawl_provider as fc
from hyperresearch.core.config import FetchSettings
from hyperresearch.web.base import SERVED_BY_KEY, WebResult, served_by
from hyperresearch.web.firecrawl_provider import FirecrawlProvider

ARTICLE = "A long article body about measured results. " * 20


@pytest.fixture(autouse=True)
def _stub_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    def resolve(host: str):
        if host == "intranet.example":
            return [ipaddress.ip_address("10.0.0.5")]
        return [ipaddress.ip_address("93.184.215.14")]

    monkeypatch.setattr("hyperresearch.web.safe_http._resolve", resolve)


class FakeFallback:
    name = "crawl4ai"

    def __init__(self, fail: bool = False):
        self.fetched: list[str] = []
        self.batches: list[list[str]] = []
        self.fail = fail

    def fetch(self, url: str) -> WebResult:
        self.fetched.append(url)
        if self.fail:
            raise RuntimeError("browser crashed")
        return WebResult(url=url, title="From browser", content=ARTICLE)

    def fetch_many(self, urls: list[str]) -> list[WebResult]:
        self.batches.append(list(urls))
        return [WebResult(url=u, title="From browser", content=ARTICLE) for u in urls]

    def search(self, query: str, max_results: int = 5) -> list[WebResult]:
        raise NotImplementedError


def _page(url: str, *, status: int = 200, title: Any = "Article", markdown: str = ARTICLE,
          final_url: str | None = None) -> dict[str, Any]:
    return {
        "markdown": markdown,
        "rawHtml": "<html><head><title>Article</title></head></html>",
        "images": ["https://cdn.example.com/fig1.png"],
        "metadata": {
            "title": title,
            "sourceURL": url,
            "url": final_url or url,
            "statusCode": status,
        },
    }


class Api:
    """Scripted Firecrawl API: route (method, path) to a response factory."""

    def __init__(self, routes: dict[tuple[str, str], Any]):
        self.routes = routes
        self.requests: list[httpx.Request] = []

    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            route = self.routes.get((request.method, request.url.path))
            if route is None:
                return httpx.Response(404, json={"success": False, "error": "no route"})
            return route(request) if callable(route) else route
        return httpx.MockTransport(handler)

    def paths(self) -> list[str]:
        return [r.url.path for r in self.requests]


def _provider(api: Api, fallback: FakeFallback | None = None, **kwargs: Any) -> FirecrawlProvider:
    fallback = fallback or FakeFallback()
    kwargs.setdefault("api_key", "fc-test")
    return FirecrawlProvider(
        fallback=lambda: fallback, transport=api.transport(), poll_interval_s=0, **kwargs,
    )


def _scrape_ok(page: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json={"success": True, "data": page})


def test_fetch_maps_scrape_and_verifies_tls() -> None:
    url = "https://example.com/a"
    page = _page(url, title=["Article", "Other"], final_url="https://example.com/a-final")
    api = Api({("POST", "/v2/scrape"): _scrape_ok(page)})

    result = _provider(api).fetch(url)

    assert result.url == "https://example.com/a-final"
    assert result.title == "Article"
    assert result.content == ARTICLE
    assert result.raw_html and "<title>Article</title>" in result.raw_html
    assert result.media == [{"src": "https://cdn.example.com/fig1.png"}]
    assert SERVED_BY_KEY not in result.metadata
    body = json.loads(api.requests[0].content)
    assert body["url"] == url
    assert body["skipTlsVerification"] is False
    assert api.requests[0].headers["Authorization"] == "Bearer fc-test"


def test_tls_opt_out_follows_browser_setting() -> None:
    url = "https://example.com/a"
    api = Api({("POST", "/v2/scrape"): _scrape_ok(_page(url))})
    _provider(api, settings=FetchSettings(browser_verify_tls=False)).fetch(url)
    assert json.loads(api.requests[0].content)["skipTlsVerification"] is True


def test_keyless_sends_no_authorization(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
    url = "https://example.com/a"
    api = Api({("POST", "/v2/scrape"): _scrape_ok(_page(url))})
    _provider(api, api_key="").fetch(url)
    assert "Authorization" not in api.requests[0].headers


@pytest.mark.parametrize("status", [403, 429, 503])
def test_blocked_target_status_falls_back_to_crawl4ai(status: int) -> None:
    url = "https://example.com/a"
    api = Api({("POST", "/v2/scrape"): _scrape_ok(_page(url, status=status))})
    fallback = FakeFallback()

    result = _provider(api, fallback).fetch(url)

    assert fallback.fetched == [url]
    assert result.title == "From browser"
    assert result.metadata[SERVED_BY_KEY] == "crawl4ai"
    assert served_by(_provider(api, fallback), result) == "crawl4ai"


def test_not_found_is_raised_without_fallback() -> None:
    url = "https://example.com/gone"
    api = Api({("POST", "/v2/scrape"): _scrape_ok(_page(url, status=404))})
    fallback = FakeFallback()
    with pytest.raises(RuntimeError, match="HTTP 404"):
        _provider(api, fallback).fetch(url)
    assert fallback.fetched == []


def test_login_wall_falls_back_to_crawl4ai() -> None:
    url = "https://example.com/paper"
    wall = _page(url, title="Sign in to continue", markdown="Please log in to read.")
    api = Api({("POST", "/v2/scrape"): _scrape_ok(wall)})
    fallback = FakeFallback()

    result = _provider(api, fallback).fetch(url)

    assert fallback.fetched == [url]
    assert result.content == ARTICLE


def test_bot_wall_with_failed_fallback_returns_firecrawl_result() -> None:
    """The caller's junk gate and escalation queue must still see the wall."""
    url = "https://example.com/a"
    wall = _page(url, title="Just a moment...", markdown="Checking your browser " * 30)
    api = Api({("POST", "/v2/scrape"): _scrape_ok(wall)})

    result = _provider(api, FakeFallback(fail=True)).fetch(url)

    assert result.title == "Just a moment..."
    assert result.looks_like_junk().startswith("Bot detection")


def test_api_error_falls_back_and_reports_both_failures() -> None:
    url = "https://example.com/a"
    api = Api({("POST", "/v2/scrape"): httpx.Response(
        402, json={"success": False, "error": "Insufficient credits"})})

    ok = _provider(api, FakeFallback()).fetch(url)
    assert ok.metadata["fallback_reason"].startswith("Firecrawl API HTTP 402")

    with pytest.raises(RuntimeError, match=r"Insufficient credits.*browser crashed"):
        _provider(api, FakeFallback(fail=True)).fetch(url)


def test_visible_lane_never_calls_the_api() -> None:
    api = Api({})
    fallback = FakeFallback()
    _provider(api, fallback, headless=False).fetch("https://linkedin.com/in/x")
    assert api.requests == []
    assert fallback.fetched == ["https://linkedin.com/in/x"]


def test_allowlisted_private_host_stays_local() -> None:
    url = "https://intranet.example/wiki"
    api = Api({})
    fallback = FakeFallback()
    settings = FetchSettings(allow_private_hosts=("10.0.0.0/8",))

    _provider(api, fallback, settings=settings).fetch(url)

    assert api.requests == []
    assert fallback.fetched == [url]


def test_private_host_without_allowlist_is_refused() -> None:
    from hyperresearch.web.safe_http import SafeHTTPError

    api = Api({})
    with pytest.raises(SafeHTTPError):
        _provider(api).fetch("https://intranet.example/wiki")
    assert api.requests == []


def test_pdf_lane_serves_pdfs_before_firecrawl(monkeypatch: pytest.MonkeyPatch) -> None:
    url = "https://example.com/paper.pdf"
    pdf = WebResult(url=url, title="Paper", content=ARTICLE, raw_bytes=b"%PDF-1.7",
                    raw_content_type="application/pdf")
    monkeypatch.setattr(fc, "fetch_pdf", lambda u, s=None: pdf)
    api = Api({})

    assert _provider(api).fetch(url) is pdf
    assert api.requests == []


def test_fetch_many_batches_polls_pages_and_falls_back() -> None:
    urls = [f"https://example.com/{n}" for n in ("ok1", "ok2", "blocked", "missing", "gone")]
    polls = iter([
        {"status": "scraping", "data": []},
        {"status": "completed", "data": [_page(urls[0])],
         "next": "https://api.firecrawl.dev/v2/batch/scrape/job1?skip=1"},
    ])

    def status(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("skip"):
            return httpx.Response(200, json={"status": "completed", "data": [
                _page(urls[1]), _page(urls[2], status=403), _page(urls[4], status=404),
            ]})
        return httpx.Response(200, json=next(polls))

    api = Api({
        ("POST", "/v2/batch/scrape"): httpx.Response(200, json={"success": True, "id": "job1"}),
        ("GET", "/v2/batch/scrape/job1"): status,
    })
    fallback = FakeFallback()

    results = _provider(api, fallback).fetch_many(urls)

    assert json.loads(api.requests[0].content)["urls"] == urls
    assert fallback.batches == [[urls[2], urls[3]]]
    by_url = {r.url: r for r in results}
    assert set(by_url) == {urls[0], urls[1], urls[2], urls[3]}
    assert SERVED_BY_KEY not in by_url[urls[0]].metadata
    assert by_url[urls[2]].metadata[SERVED_BY_KEY] == "crawl4ai"


def test_fetch_many_failed_batch_goes_to_crawl4ai() -> None:
    urls = ["https://example.com/a", "https://example.com/b"]
    api = Api({("POST", "/v2/batch/scrape"): httpx.Response(429, json={"error": "rate limited"})})
    fallback = FakeFallback()

    results = _provider(api, fallback).fetch_many(urls)

    assert fallback.batches == [urls]
    assert [r.url for r in results] == urls


def test_fetch_many_keyless_scrapes_one_by_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
    urls = ["https://example.com/a", "https://example.com/b"]

    def scrape(request: httpx.Request) -> httpx.Response:
        return _scrape_ok(_page(json.loads(request.content)["url"]))

    api = Api({("POST", "/v2/scrape"): scrape})

    results = _provider(api, api_key="").fetch_many(urls)

    assert api.paths() == ["/v2/scrape", "/v2/scrape"]
    assert [r.url for r in results] == urls


def test_search_maps_web_results() -> None:
    api = Api({("POST", "/v2/search"): httpx.Response(200, json={"success": True, "data": {"web": [
        {"url": "https://example.com/a", "title": "A", "description": "Snippet A",
         "markdown": ARTICLE},
        {"url": "https://example.com/b", "title": "B", "description": "Snippet B"},
    ]}})})

    results = _provider(api).search("measured results", max_results=2)

    body = json.loads(api.requests[0].content)
    assert body["query"] == "measured results"
    assert body["limit"] == 2
    assert [r.title for r in results] == ["A", "B"]
    assert results[0].content == ARTICLE
    assert results[1].content == "Snippet B"
