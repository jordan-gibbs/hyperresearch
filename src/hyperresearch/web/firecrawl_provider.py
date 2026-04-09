"""Firecrawl web provider — AI-optimized scraping, returns clean markdown."""

from __future__ import annotations

import os
from datetime import UTC, datetime

from firecrawl import FirecrawlApp

from hyperresearch.web.base import WebResult


class FirecrawlProvider:
    name = "firecrawl"

    def __init__(self, api_key: str | None = None, api_url: str | None = None):
        key = api_key or os.environ.get("FIRECRAWL_API_KEY", "")
        url = api_url or os.environ.get("FIRECRAWL_API_URL")
        kwargs = {}
        if key:
            kwargs["api_key"] = key
        if url:
            kwargs["api_url"] = url
        self._app = FirecrawlApp(**kwargs)

    def fetch(self, url: str) -> WebResult:
        result = self._app.scrape_url(url, params={"formats": ["markdown"]})
        return WebResult(
            url=url,
            title=result.get("metadata", {}).get("title", ""),
            content=result.get("markdown", ""),
            raw_html=result.get("html"),
            fetched_at=datetime.now(UTC),
            metadata=result.get("metadata", {}),
        )

    def search(self, query: str, max_results: int = 5) -> list[WebResult]:
        raise NotImplementedError(
            "Firecrawl does not support web search directly. "
            "Use tavily for search: pip install hyperresearch[tavily]"
        )
