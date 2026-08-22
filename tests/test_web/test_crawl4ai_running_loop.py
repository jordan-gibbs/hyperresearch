"""fetch() must work when called on a thread that already has a running event loop.

The MCP server's fastmcp tool dispatch calls synchronous tool functions directly on
its own running event-loop thread (it does not offload them to a worker thread), so
fetch_url's call chain into Crawl4AIProvider.fetch() lands there too. A plain
asyncio.run() inside fetch() would raise "cannot be called from a running event
loop" in that case; the CLI's plain synchronous invocation has no such loop and must
keep working exactly as before.
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


def test_fetch_succeeds_when_called_from_a_running_event_loop(monkeypatch) -> None:
    async def fake_fetch_async(self, url):
        return WebResult(url=url, title="ok", content="fetched content")

    monkeypatch.setattr(Crawl4AIProvider, "_fetch_async", fake_fetch_async)
    provider = Crawl4AIProvider(headless=True)

    async def call_fetch_on_the_running_loop():
        return provider.fetch("https://example.com")

    result = _run_on_a_fresh_thread(call_fetch_on_the_running_loop())

    assert result.title == "ok"
    assert result.content == "fetched content"


def test_fetch_still_succeeds_with_no_running_loop(monkeypatch) -> None:
    """The CLI's plain synchronous call path (no event loop on the thread)."""
    async def fake_fetch_async(self, url):
        return WebResult(url=url, title="ok", content="fetched content")

    monkeypatch.setattr(Crawl4AIProvider, "_fetch_async", fake_fetch_async)
    provider = Crawl4AIProvider(headless=True)

    result = provider.fetch("https://example.com")

    assert result.title == "ok"
    assert result.content == "fetched content"
