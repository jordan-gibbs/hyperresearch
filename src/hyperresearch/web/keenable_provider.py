"""Keenable web provider: web search and page fetch, with or without a key.

Keenable (https://keenable.ai) returns search results with the page text in
each result's snippet, so `search` is a single request with no per-result
fetch. Without a key it uses the public endpoints, which are rate limited per
IP (10 requests per second, 1000 per hour); a key lifts those limits.

Configuration:
    # in .hyperresearch/config.toml
    [web]
    provider = "keenable"

    export KEENABLE_API_KEY="your-api-key"   # optional, https://keenable.ai

No extra install: uses the httpx dependency the core already carries.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

import httpx

from hyperresearch.web.base import WebResult

_BASE_URL = "https://api.keenable.ai/v1"
_TIMEOUT = 30.0
_MAX_RESULTS = 50  # the API accepts 1 to 50 per request


class KeenableProvider:
    """Web provider backed by the Keenable API (https://docs.keenable.ai).

    Supports both `search` (ranked results with page text) and `fetch` (URL to text).
    """

    name = "keenable"

    def __init__(
        self,
        api_key: str | None = None,
        max_characters: int = 8000,
        transport: httpx.BaseTransport | None = None,
    ):
        key = api_key or os.environ.get("KEENABLE_API_KEY", "").strip()

        # Keyless requests must name the calling app or the API answers 400.
        headers = {"X-Keenable-Title": "hyperresearch"}
        if key:
            headers["X-API-Key"] = key
        self._client = httpx.Client(headers=headers, timeout=_TIMEOUT, transport=transport)
        self._search_url = f"{_BASE_URL}/search" if key else f"{_BASE_URL}/search/public"
        self._fetch_url = f"{_BASE_URL}/fetch" if key else f"{_BASE_URL}/fetch/public"
        self._max_characters = max_characters

    def search(self, query: str, max_results: int = 5) -> list[WebResult]:
        """Search the web via Keenable and return ranked results with page text."""
        count = min(max(max_results, 1), _MAX_RESULTS)
        resp = self._client.post(self._search_url, json={"query": query, "max_results": count})
        resp.raise_for_status()
        items = resp.json().get("results", [])[: max(0, max_results)]

        results: list[WebResult] = []
        for item in items:
            result = self._to_web_result(item)
            if result.url:
                results.append(result)
        return results

    def fetch(self, url: str) -> WebResult:
        """Fetch a single URL via Keenable and return its main text."""
        resp = self._client.get(self._fetch_url, params={"url": url})
        resp.raise_for_status()
        item = resp.json()
        content = (item.get("content") or "").strip()[: self._max_characters]
        if not content:
            raise RuntimeError(f"Keenable returned no content for {url}")

        metadata: dict[str, Any] = {}
        if item.get("author"):
            metadata["author"] = item["author"]
        published_at = _published_at(item.get("published_at"))
        if published_at:
            metadata["published_at"] = published_at

        return WebResult(
            url=url,
            title=item.get("title", "") or "",
            content=content,
            fetched_at=datetime.now(UTC),
            metadata=metadata,
        )

    def _to_web_result(self, item: dict[str, Any]) -> WebResult:
        """Convert a Keenable search result dict into a hyperresearch WebResult."""
        # `snippet` carries the page text; `description` is normally empty.
        text = (item.get("snippet") or "").strip() or (item.get("description") or "").strip()

        metadata: dict[str, Any] = {}
        published_at = _published_at(item.get("published_at"))
        if published_at:
            metadata["published_at"] = published_at

        return WebResult(
            url=item.get("url", "") or "",
            title=item.get("title", "") or "",
            content=text[: self._max_characters],
            fetched_at=datetime.now(UTC),
            metadata=metadata,
        )


def _published_at(value: Any) -> str | None:
    """Normalize a publish date to ISO 8601: search sends a string, fetch Unix seconds."""
    if isinstance(value, str) and value:
        return value
    if isinstance(value, int | float) and not isinstance(value, bool):
        return datetime.fromtimestamp(value, UTC).isoformat()
    return None
