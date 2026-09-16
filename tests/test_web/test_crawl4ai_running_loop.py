"""Crawl4AI fetch async/sync entry points and event-loop behavior (#118).

Sync ``Crawl4AIProvider.fetch()`` is for CLI callers with no running loop; it
delegates via ``asyncio.run(fetch_url(...))``. Async callers (including the MCP
server) must ``await provider.fetch_url(...)`` — calling ``fetch()`` on a thread
that already has a running event loop raises ``RuntimeError``.
"""

from __future__ import annotations

import asyncio
import threading

import pytest

pytest.importorskip("crawl4ai.browser_adapter")

from hyperresearch.web.base import WebResult
from hyperresearch.web.crawl4ai_provider import Crawl4AIProvider


def _run_on_a_fresh_thread(coro):
    """Run ``coro`` to completion on a brand-new thread, guaranteeing a real,
    isolated running event loop for the duration of the call.

    See tests/test_web/test_fetch_many_fallback.py's ``_run`` for why: a prior
    test in the full suite can leave the main thread's asyncio state marked
    "running" (observed once crawl4ai's sync Playwright bridge has been
    exercised), which makes a plain ``asyncio.run()`` here raise regardless of
    what this test is trying to isolate. A fresh thread has no such leftover
    state.
    """
    box: dict = {}

    def target() -> None:
        try:
            box["result"] = asyncio.run(coro)
        except BaseException as exc:
            box["error"] = exc

    thread = threading.Thread(target=target)
    thread.start()
    thread.join()
    if "error" in box:
        raise box["error"]
    return box["result"]


def test_fetch_url_succeeds_when_awaited_on_running_event_loop(monkeypatch) -> None:
    """Async entry point for callers on the MCP server's event loop."""
    async def fake_fetch_async(self, url):
        return WebResult(url=url, title="ok", content="fetched content")

    monkeypatch.setattr(Crawl4AIProvider, "_fetch_async", fake_fetch_async)
    provider = Crawl4AIProvider(headless=True)

    async def call_fetch_on_the_running_loop():
        return await provider.fetch_url("https://example.com")

    result = _run_on_a_fresh_thread(call_fetch_on_the_running_loop())

    assert result.title == "ok"
    assert result.content == "fetched content"


def test_fetch_raises_when_called_sync_from_running_event_loop(monkeypatch) -> None:
    """Sync fetch() must not be used on a running loop; use ``await fetch_url()`` instead."""
    async def fake_fetch_async(self, url):
        return WebResult(url=url, title="ok", content="fetched content")

    monkeypatch.setattr(Crawl4AIProvider, "_fetch_async", fake_fetch_async)
    provider = Crawl4AIProvider(headless=True)

    async def call_sync_fetch_on_the_running_loop() -> None:
        with pytest.raises(RuntimeError, match="running event loop"):
            provider.fetch("https://example.com")

    _run_on_a_fresh_thread(call_sync_fetch_on_the_running_loop())


def test_fetch_still_succeeds_with_no_running_loop(monkeypatch) -> None:
    """The CLI's plain synchronous call path (no event loop on the thread)."""
    async def fake_fetch_async(self, url):
        return WebResult(url=url, title="ok", content="fetched content")

    monkeypatch.setattr(Crawl4AIProvider, "_fetch_async", fake_fetch_async)
    provider = Crawl4AIProvider(headless=True)

    result = provider.fetch("https://example.com")

    assert result.title == "ok"
    assert result.content == "fetched content"


def test_fetch_many_succeeds_when_called_from_a_running_event_loop(monkeypatch) -> None:
    """fetch_many() is async; MCP callers await it on the server loop."""
    async def fake_fetch_many_async(self, urls):
        return [WebResult(url=u, title="ok", content="fetched content") for u in urls]

    monkeypatch.setattr(Crawl4AIProvider, "fetch_many", fake_fetch_many_async)
    provider = Crawl4AIProvider(headless=True)
    urls = ["https://example.com/a", "https://example.com/b"]

    async def call_fetch_many_on_the_running_loop():
        return await provider.fetch_many(urls)

    results = _run_on_a_fresh_thread(call_fetch_many_on_the_running_loop())

    assert [r.url for r in results] == urls
    assert all(r.content == "fetched content" for r in results)


def test_fetch_url_yields_to_event_loop_while_waiting(monkeypatch) -> None:
    """Regression for #118: fetch_url must not block the loop with thread.join()."""
    proceed = asyncio.Event()

    async def fake_fetch_async(self, url):
        await proceed.wait()
        return WebResult(url=url, title="ok", content="fetched content")

    monkeypatch.setattr(Crawl4AIProvider, "_fetch_async", fake_fetch_async)
    monkeypatch.setattr(
        "hyperresearch.web.safe_http.check_url",
        lambda *args, **kwargs: None,
    )
    provider = Crawl4AIProvider(headless=True)

    async def run() -> None:
        tick = asyncio.Event()

        async def ticker() -> None:
            await asyncio.sleep(0)
            tick.set()

        fetch_task = asyncio.create_task(provider.fetch_url("https://example.com"))
        ticker_task = asyncio.create_task(ticker())
        for _ in range(20):
            await asyncio.sleep(0)
            if tick.is_set():
                break
        assert tick.is_set(), "event loop must stay responsive while fetch_url awaits"
        proceed.set()
        await fetch_task
        await ticker_task

    _run_on_a_fresh_thread(run())
