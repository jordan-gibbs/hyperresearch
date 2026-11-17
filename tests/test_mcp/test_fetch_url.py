"""The MCP fetch_url tool must not block the server's event loop (#118).

The fake provider's fetch blocks until another coroutine on the same loop
releases it. If fetch_url ran the fetch on the loop thread, that coroutine
could never run and the fetch would time out.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.web.base import WebResult

mcp = pytest.importorskip("hyperresearch.mcp.server")

runner = CliRunner()


@pytest.fixture
def mcp_vault(tmp_path: Path) -> Path:
    vault_dir = tmp_path / "kb"
    runner.invoke(app, ["init", str(vault_dir)])
    os.chdir(vault_dir)
    mcp._vault = None  # module-global cache; force rediscovery under tmp_path
    yield vault_dir
    mcp._vault = None


class _BlockingProvider:
    name = "fake"

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.fetch_thread: int | None = None

    def fetch(self, url: str) -> WebResult:
        self.fetch_thread = threading.get_ident()
        self.started.set()
        if not self.release.wait(timeout=5):
            raise RuntimeError("fetch was never released: the event loop was blocked")
        return WebResult(url=url, title="Fake Title", content="enough content to clear the junk gate. " * 10)


def _run_on_a_fresh_thread(coro):
    """Run ``coro`` on a new thread with its own loop.

    See tests/test_web/test_fetch_many_fallback.py's ``_run``: an earlier test
    can leave the main thread's asyncio state marked running. The vault is
    opened inside ``coro`` too, so its sqlite connection belongs to that loop's
    thread, as it does in the server.
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


def test_fetch_url_keeps_the_event_loop_responsive(mcp_vault, monkeypatch):
    prov = _BlockingProvider()
    monkeypatch.setattr("hyperresearch.web.base.get_provider", lambda *a, **k: prov)
    url = "https://example.com/slow-page"

    async def scenario():
        loop_thread = threading.get_ident()

        async def release_once_started() -> None:
            # Polls on the loop; only runs at all if fetch_url yielded it.
            for _ in range(500):
                if prov.started.is_set():
                    prov.release.set()
                    return
                await asyncio.sleep(0.01)
            raise AssertionError("fetch never started")

        out, _ = await asyncio.gather(mcp.fetch_url(url), release_once_started())
        return loop_thread, out

    loop_thread, out = _run_on_a_fresh_thread(scenario())
    out = json.loads(out)

    assert out["ok"] is True, out
    assert prov.fetch_thread != loop_thread
    assert (mcp_vault / out["data"]["path"]).exists()


def test_fetch_url_saves_the_source_row_on_the_loop_thread(mcp_vault, monkeypatch):
    """The sources INSERT uses the loop thread's sqlite connection; a second
    fetch of the same URL sees it and is refused before any network call."""
    prov = _BlockingProvider()
    prov.release.set()
    monkeypatch.setattr("hyperresearch.web.base.get_provider", lambda *a, **k: prov)
    url = "https://example.com/once"

    async def fetch_twice():
        first = json.loads(await mcp.fetch_url(url))
        prov.started.clear()
        second = json.loads(await mcp.fetch_url(url))
        return first, second

    first, second = _run_on_a_fresh_thread(fetch_twice())
    assert first["ok"] is True, first
    assert second["ok"] is False
    assert second["error_code"] == "DUPLICATE_URL"
    assert not prov.started.is_set()
