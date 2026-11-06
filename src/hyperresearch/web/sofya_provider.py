"""Sofya web provider: web search with page content plus page fetch behind one key.

Sofya (https://sofya.co) is a search and fetch API for agents. Search returns
each result's extracted page text, not just the snippet, so `search` needs one
request. Fetch returns pages and documents (PDF, Word, Excel, ...) as Markdown.

Configuration:
    export SOFYA_API_KEY="sofya_live_..."   # https://sofya.co/dashboard

    # in .hyperresearch/config.toml
    [web]
    provider = "sofya"

No extra install: uses the httpx dependency the core already carries.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

import httpx

from hyperresearch.web.base import WebResult

_SEARCH_URL = "https://sofya.co/v1/search"
_FETCH_URL = "https://sofya.co/v1/fetch"
_TIMEOUT = 60.0


class SofyaProvider:
    """Web provider backed by the Sofya API (https://sofya.co/docs).

    Supports both `search` (results with page content) and `fetch` (URL to Markdown).
    """

    name = "sofya"

    def __init__(
        self,
        api_key: str | None = None,
        search_depth: str = "basic",
        topic: str = "general",
        transport: httpx.BaseTransport | None = None,
    ):
        key = api_key or os.environ.get("SOFYA_API_KEY", "").strip()
        if not key:
            raise RuntimeError(
                "SOFYA_API_KEY is not set. Get a key at https://sofya.co and export it."
            )

        self._client = httpx.Client(
            headers={"Authorization": f"Bearer {key}", "User-Agent": "hyperresearch"},
            timeout=_TIMEOUT,
            transport=transport,
        )
        self._search_depth = search_depth
        self._topic = topic

    def search(self, query: str, max_results: int = 5) -> list[WebResult]:
        """Search the web via Sofya and return ranked results with page content."""
        resp = self._client.post(
            _SEARCH_URL,
            json={
                "query": query,
                "max_results": max_results,
                "search_depth": self._search_depth,
                "topic": self._topic,
            },
        )
        resp.raise_for_status()
        items = resp.json().get("results", [])[:max_results]
        return [r for r in (_to_web_result(item) for item in items) if r.url]

    def fetch(self, url: str) -> WebResult:
        """Fetch a single URL via Sofya and return it as Markdown."""
        resp = self._client.post(_FETCH_URL, json={"urls": [url]})
        resp.raise_for_status()
        results = resp.json().get("results", [])
        if not results:
            raise RuntimeError(f"Sofya returned no result for {url}")
        item = results[0]
        if not item.get("success", True):
            error = item.get("error") or "unknown error"
            raise RuntimeError(f"Sofya could not fetch {url}: {error}")
        content = (item.get("content") or "").strip()
        if not content:
            raise RuntimeError(f"Sofya returned no content for {url}")

        metadata: dict[str, Any] = {}
        if item.get("published_time"):
            metadata["published_time"] = item["published_time"]
        return WebResult(
            url=item.get("url") or url,
            title=item.get("title", "") or "",
            content=content,
            fetched_at=datetime.now(UTC),
            metadata=metadata,
        )


def _to_web_result(item: dict[str, Any]) -> WebResult:
    """Convert a Sofya search result dict into a hyperresearch WebResult.

    A result whose page could not be read comes back with the snippet only, so
    `content` falls back to `description`.
    """
    metadata: dict[str, Any] = {}
    if item.get("published_date"):
        metadata["published_date"] = item["published_date"]

    return WebResult(
        url=item.get("url", "") or "",
        title=item.get("title", "") or "",
        content=item.get("content") or item.get("description", "") or "",
        fetched_at=datetime.now(UTC),
        metadata=metadata,
    )
