"""Tavily web provider — search API designed for LLMs and AI agents.

Tavily (https://tavily.com) provides web search and content extraction optimized
for retrieval-augmented generation workflows.

Configuration:
    export TAVILY_API_KEY="tvly-your-api-key"   # https://app.tavily.com

    # in .hyperresearch/config.toml
    [web]
    provider = "tavily"

Optional install:
    pip install "hyperresearch[tavily]"
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from hyperresearch.web.base import WebResult


class TavilyProvider:
    """Web provider backed by the Tavily search API.

    Supports both `search` (web search) and `fetch` (URL content extraction).
    """

    name = "tavily"

    def __init__(
        self,
        api_key: str | None = None,
        search_depth: str = "advanced",
        topic: str = "general",
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
    ):
        try:
            from tavily import TavilyClient
        except ImportError as exc:
            raise ImportError(
                'tavily provider requires: pip install "hyperresearch[tavily]"'
            ) from exc

        key = api_key or os.environ.get("TAVILY_API_KEY", "").strip()
        if not key:
            raise RuntimeError(
                "TAVILY_API_KEY is not set. Get a free key at "
                "https://app.tavily.com and export it."
            )

        self._client = TavilyClient(api_key=key)
        self._search_depth = search_depth
        self._topic = topic
        self._include_domains = include_domains
        self._exclude_domains = exclude_domains

    def search(self, query: str, max_results: int = 5) -> list[WebResult]:
        """Search the web via Tavily and return ranked results with content."""
        kwargs: dict[str, Any] = {
            "max_results": max_results,
            "search_depth": self._search_depth,
            "topic": self._topic,
        }
        if self._include_domains:
            kwargs["include_domains"] = self._include_domains
        if self._exclude_domains:
            kwargs["exclude_domains"] = self._exclude_domains

        response = self._client.search(query, **kwargs)
        return [_to_web_result(r) for r in response.get("results", [])]

    def fetch(self, url: str) -> WebResult:
        """Fetch a single URL via Tavily extract and return clean text."""
        response = self._client.extract(urls=[url])
        results = response.get("results", [])
        if not results:
            raise RuntimeError(f"Tavily returned no contents for {url}")
        return _to_web_result(results[0])


def _to_web_result(item: dict[str, Any]) -> WebResult:
    """Convert a Tavily result dict into a hyperresearch WebResult."""
    content = item.get("content", "") or item.get("raw_content", "") or ""

    metadata: dict[str, Any] = {}
    score = item.get("score")
    if score is not None:
        metadata["score"] = score
    published_date = item.get("published_date")
    if published_date:
        metadata["published_date"] = published_date

    return WebResult(
        url=item.get("url", ""),
        title=item.get("title", "") or "",
        content=content,
        fetched_at=datetime.now(UTC),
        metadata=metadata,
    )
