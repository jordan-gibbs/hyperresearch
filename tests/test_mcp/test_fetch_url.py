"""MCP fetch_url tool — async fetch path regression (#118)."""

from __future__ import annotations

import asyncio
import json
import os
import threading
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app

mcp = pytest.importorskip("hyperresearch.mcp.server")

runner = CliRunner()


@pytest.fixture
def mcp_vault(tmp_path: Path) -> Path:
    vault_dir = tmp_path / "kb"
    runner.invoke(app, ["init", str(vault_dir)])
    os.chdir(vault_dir)
    mcp._vault = None
    yield vault_dir
    mcp._vault = None


def _run_on_a_fresh_thread(coro):
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


def test_mcp_fetch_url_awaits_async_save_and_yields_to_event_loop(
    mcp_vault, monkeypatch
) -> None:
    """MCP fetch_url must await fetch_and_save_async, not block the loop on thread.join()."""
    proceed = asyncio.Event()
    url = "https://example.com/article"

    async def fake_fetch_and_save_async(vault, fetch_url, **kwargs):
        await proceed.wait()
        return {
            "note_id": "example-com-article",
            "title": "Example",
            "url": fetch_url,
            "domain": "example.com",
            "provider": "test",
            "path": "research/notes/example-com-article.md",
            "word_count": 2,
            "assets": [],
            "raw_file": None,
        }

    def sync_fetch_and_save_must_not_run(*args, **kwargs):
        raise AssertionError("MCP fetch_url must not call sync fetch_and_save")

    monkeypatch.setattr(
        "hyperresearch.core.fetcher.fetch_and_save_async",
        fake_fetch_and_save_async,
    )
    monkeypatch.setattr(
        "hyperresearch.core.fetcher.fetch_and_save",
        sync_fetch_and_save_must_not_run,
    )

    async def run() -> str:
        tick = asyncio.Event()

        async def ticker() -> None:
            await asyncio.sleep(0)
            tick.set()

        tool_task = asyncio.create_task(mcp.fetch_url(url, tags="demo"))
        ticker_task = asyncio.create_task(ticker())
        for _ in range(20):
            await asyncio.sleep(0)
            if tick.is_set():
                break
        assert tick.is_set(), "event loop must stay responsive while MCP fetch_url awaits"
        proceed.set()
        raw = await tool_task
        await ticker_task
        return raw

    raw = _run_on_a_fresh_thread(run())
    payload = json.loads(raw)
    assert payload["ok"] is True
    assert payload["data"]["url"] == url
    assert payload["data"]["note_id"] == "example-com-article"
