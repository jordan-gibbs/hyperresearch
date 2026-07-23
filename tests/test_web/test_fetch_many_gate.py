"""fetch_many must apply the same SSRF gate as fetch().

It is the main fetch path (every wave-1 fetcher batch goes through it), so a
gate that only covered fetch() would leave the bulk of outbound traffic
unprotected. Offline: only .pdf URLs are used so the browser lane is never
touched, and _fetch_pdf is stubbed.
"""

from __future__ import annotations

import asyncio
import logging

import hyperresearch.web.crawl4ai_provider as provider


def _run(coro):
    """Run ``coro`` to completion in an isolated thread with its own loop.

    A prior test in the full suite can leave this thread's event-loop state as
    "running" (seen intermittently on Python 3.11 once crawl4ai's async
    machinery has been exercised), which makes a plain ``asyncio.run()`` here
    raise "cannot be called from a running event loop". A fresh thread has no
    running loop, so running the coroutine there is immune to that leaked state.
    Logging still lands in caplog: handlers are process-global, and the thread
    is joined inside the caplog context below.
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


def test_fetch_many_skips_refused_urls_and_fetches_the_rest(monkeypatch, caplog):
    fetched: list[str] = []

    def fake_fetch_pdf(url, settings=None):
        fetched.append(url)
        return None

    monkeypatch.setattr(provider, "_fetch_pdf", fake_fetch_pdf)

    inst = provider.Crawl4AIProvider.__new__(provider.Crawl4AIProvider)
    inst._settings = provider.FetchSettings()

    urls = [
        "http://127.0.0.1/internal.pdf",  # loopback — refused
        "http://169.254.169.254/meta.pdf",  # cloud metadata — refused
        "http://8.8.8.8/paper.pdf",  # public literal — allowed
    ]
    with caplog.at_level(logging.WARNING, logger="hyperresearch.web"):
        results = _run(inst._fetch_many_async(urls))

    assert results == []
    assert fetched == ["http://8.8.8.8/paper.pdf"], (
        "refused URLs must be skipped, allowed ones still fetched"
    )
    assert "refused batch fetch" in caplog.text
    assert "127.0.0.1" in caplog.text
