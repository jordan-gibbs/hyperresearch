"""Serply web provider: Google search results plus page fetch behind one key.

Serply (https://serply.io) returns Google organic results as JSON and fetches
pages as Markdown. Search results carry only the SERP snippet, so `search`
fetches each page through the same API and falls back to the snippet when a
page cannot be fetched or comes back as a bot wall.

Configuration:
    export SERPLY_API_KEY="your-api-key"   # https://serply.io

    # in .hyperresearch/config.toml
    [web]
    provider = "serply"

No extra install: uses the httpx dependency the core already carries.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

import httpx

from hyperresearch.web.base import WebResult

_SEARCH_URL = "https://api.serply.io/v1/search/"
_FETCH_URL = "https://api.serply.io/v1/request"
_TIMEOUT = 30.0


class SerplyProvider:
    """Web provider backed by the Serply API (https://serply.io/docs).

    Supports both `search` (Google organic results) and `fetch` (URL to Markdown).
    """

    name = "serply"

    def __init__(
        self,
        api_key: str | None = None,
        fetch_content: bool = True,
        max_characters: int = 8000,
        transport: httpx.BaseTransport | None = None,
    ):
        key = api_key or os.environ.get("SERPLY_API_KEY", "").strip()
        if not key:
            raise RuntimeError(
                "SERPLY_API_KEY is not set. Get a key at https://serply.io and export it."
            )

        # Serply sits behind Cloudflare, which rejects the default httpx User-Agent.
        self._client = httpx.Client(
            headers={"X-Api-Key": key, "User-Agent": "hyperresearch"},
            timeout=_TIMEOUT,
            transport=transport,
        )
        self._fetch_content = fetch_content
        self._max_characters = max_characters

    def search(self, query: str, max_results: int = 5) -> list[WebResult]:
        """Search Google via Serply and return ranked results with content."""
        resp = self._client.get(_SEARCH_URL, params={"q": query, "num": max_results})
        resp.raise_for_status()
        items = resp.json().get("results", [])[:max_results]

        results: list[WebResult] = []
        for item in items:
            result = _to_web_result(item)
            if not result.url:
                continue
            if self._fetch_content:
                try:
                    fetched = self.fetch(result.url)
                except (httpx.HTTPError, RuntimeError):
                    fetched = None
                if fetched is not None and fetched.looks_like_junk() is None:
                    result.content = fetched.content
            results.append(result)
        return results

    def fetch(self, url: str) -> WebResult:
        """Fetch a single URL via Serply and return it as Markdown."""
        resp = self._client.post(_FETCH_URL, json={"url": url, "response_type": "markdown"})
        resp.raise_for_status()
        content = resp.text.strip()[: self._max_characters]
        if not content:
            raise RuntimeError(f"Serply returned no content for {url}")
        return WebResult(url=url, title="", content=content, fetched_at=datetime.now(UTC))


def _to_web_result(item: dict[str, Any]) -> WebResult:
    """Convert a Serply organic result dict into a hyperresearch WebResult."""
    metadata: dict[str, Any] = {}
    position = item.get("position")
    if position is not None:
        metadata["position"] = position
    published_time = (item.get("metadata") or {}).get("published_time")
    if published_time:
        metadata["published_time"] = published_time

    return WebResult(
        url=item.get("link", "") or "",
        title=item.get("title", "") or "",
        content=item.get("description", "") or "",
        fetched_at=datetime.now(UTC),
        metadata=metadata,
    )
