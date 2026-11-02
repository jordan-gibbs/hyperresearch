"""Outcrawl web provider: web search plus page scrape behind one key.

Outcrawl (https://outcrawl.ai) returns search hits as JSON and scrapes pages
to Markdown through a real browser. Search hits carry only a snippet, so
`search` scrapes each page through the same API and falls back to the snippet
when a page cannot be fetched or comes back as a bot wall.

Configuration:
    export OUTCRAWL_API_KEY="your-api-key"   # https://outcrawl.ai

    # in .hyperresearch/config.toml
    [web]
    provider = "outcrawl"

No extra install: uses the httpx dependency the core already carries.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

import httpx

from hyperresearch.web.base import WebResult

_SEARCH_URL = "https://api.outcrawl.ai/v1/search"
_SCRAPE_URL = "https://api.outcrawl.ai/v1/scrape"
_TIMEOUT = 60.0
_MAX_LIMIT = 20


class OutcrawlProvider:
    """Web provider backed by the Outcrawl API (https://outcrawl.ai/docs).

    Supports both `search` (web search hits) and `fetch` (URL to Markdown).
    """

    name = "outcrawl"

    def __init__(
        self,
        api_key: str | None = None,
        fetch_content: bool = True,
        max_characters: int = 8000,
        transport: httpx.BaseTransport | None = None,
    ):
        key = api_key or os.environ.get("OUTCRAWL_API_KEY", "").strip()
        if not key:
            raise RuntimeError(
                "OUTCRAWL_API_KEY is not set. Get a key at https://outcrawl.ai and export it."
            )

        self._client = httpx.Client(
            headers={"Authorization": f"Bearer {key}", "User-Agent": "hyperresearch"},
            timeout=_TIMEOUT,
            transport=transport,
        )
        self._fetch_content = fetch_content
        self._max_characters = max_characters

    def search(self, query: str, max_results: int = 5) -> list[WebResult]:
        """Search the web via Outcrawl and return ranked results with content."""
        limit = max(1, min(max_results, _MAX_LIMIT))
        resp = self._client.post(_SEARCH_URL, json={"query": query, "limit": limit})
        resp.raise_for_status()
        hits = resp.json().get("hits", [])[:max_results]

        results: list[WebResult] = []
        for hit in hits:
            result = _to_web_result(hit)
            if not result.url:
                continue
            if self._fetch_content:
                try:
                    fetched = self.fetch(result.url)
                except (httpx.HTTPError, RuntimeError):
                    fetched = None
                if fetched is not None and fetched.looks_like_junk() is None:
                    result.content = fetched.content
                    if not result.title:
                        result.title = fetched.title
            results.append(result)
        return results

    def fetch(self, url: str) -> WebResult:
        """Scrape a single URL via Outcrawl and return it as Markdown."""
        resp = self._client.post(
            _SCRAPE_URL,
            json={"url": url, "formats": ["markdown"], "onlyMainContent": True},
        )
        resp.raise_for_status()
        data = resp.json()

        status = data.get("statusCode")
        if isinstance(status, int) and status >= 400:
            raise RuntimeError(f"Outcrawl fetched {url} with HTTP status {status}")

        content = (data.get("markdown") or "").strip()[: self._max_characters]
        if not content:
            raise RuntimeError(f"Outcrawl returned no content for {url}")

        metadata = data.get("metadata") or {}
        return WebResult(
            url=data.get("url") or url,
            title=metadata.get("title", "") or "",
            content=content,
            fetched_at=datetime.now(UTC),
            metadata={"status_code": status} if status is not None else {},
        )


def _to_web_result(hit: dict[str, Any]) -> WebResult:
    """Convert an Outcrawl search hit dict into a hyperresearch WebResult."""
    metadata: dict[str, Any] = {}
    rank = hit.get("rank")
    if rank is not None:
        metadata["rank"] = rank

    return WebResult(
        url=hit.get("url", "") or "",
        title=hit.get("title", "") or "",
        content=hit.get("snippet", "") or "",
        fetched_at=datetime.now(UTC),
        metadata=metadata,
    )
