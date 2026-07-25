"""Batch-fetch PDF→browser fallback (the #52 fix) — driven entirely offline
with a fake crawler, no browser or network."""

from __future__ import annotations

import asyncio

import pytest

from hyperresearch.web.base import WebResult

provider = pytest.importorskip(
    "hyperresearch.web.crawl4ai_provider",
    reason="crawl4ai extra not installed",
)


def _run(coro):
    """Run ``coro`` to completion in an isolated thread with its own loop.

    A prior test in the full suite can leave this thread's event-loop state as
    "running" (seen intermittently on Python 3.11 once crawl4ai's async
    machinery has been exercised), which makes a plain ``asyncio.run()`` here
    raise "cannot be called from a running event loop". A fresh thread has no
    running loop, so running the coroutine there is immune to that leaked state.
    """
    import threading

    box: dict = {}

    def target() -> None:
        try:
            box["result"] = asyncio.run(coro)
        except Exception as exc:
            box["error"] = exc

    thread = threading.Thread(target=target)
    thread.start()
    thread.join()
    if "error" in box:
        raise box["error"]
    return box["result"]


class _FakeCR:
    """Minimal stand-in for a crawl4ai result the fallback loop reads."""

    def __init__(self, url: str):
        self.success = True
        self.url = url
        self.markdown = f"browser text for {url}"  # str path -> content = markdown
        self.metadata = {"title": "Fallback Title"}
        self.media = {}
        self.screenshot = None
        self.html = "<html></html>"


class _FakeCrawler:
    """Async-context-manager crawler that records the URLs it was handed."""

    def __init__(self, captured: list[str]):
        self._captured = captured

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def arun_many(self, urls, config):
        self._captured.extend(urls)
        return [_FakeCR(u) for u in urls]


def _bare_provider(captured: list[str], monkeypatch) -> object:
    inst = provider.Crawl4AIProvider.__new__(provider.Crawl4AIProvider)
    inst._settings = provider.FetchSettings()
    inst._gates = provider.JunkGates()
    inst._run_config = object()
    monkeypatch.setattr(inst, "_make_crawler", lambda: _FakeCrawler(captured))
    return inst


def test_failed_pdf_falls_back_to_browser_lane(monkeypatch):
    """A .pdf whose direct fetch returns None must be retried through the
    browser lane. If this fallback regresses, batch fetches silently drop
    academic PDFs that only render behind a JS landing page."""
    monkeypatch.setattr(provider, "_fetch_pdf", lambda url, settings=None: None)
    captured: list[str] = []
    inst = _bare_provider(captured, monkeypatch)

    results = _run(inst._fetch_many_async(["http://8.8.8.8/paper.pdf"]))

    assert captured == ["http://8.8.8.8/paper.pdf"]
    assert len(results) == 1
    assert results[0].content == "browser text for http://8.8.8.8/paper.pdf"


def test_successful_pdf_does_not_reach_browser_lane(monkeypatch):
    """The mirror case: when the direct PDF fetch succeeds, the .pdf must NOT
    also be handed to the browser, or every academic PDF gets fetched twice."""
    real = WebResult(url="http://8.8.8.8/paper.pdf", title="Paper", content="pdf text")
    monkeypatch.setattr(provider, "_fetch_pdf", lambda url, settings=None: real)
    captured: list[str] = []
    inst = _bare_provider(captured, monkeypatch)

    results = _run(inst._fetch_many_async(["http://8.8.8.8/paper.pdf"]))

    assert captured == []  # browser lane never entered
    assert results == [real]
