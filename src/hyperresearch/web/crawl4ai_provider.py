"""Crawl4AI web provider — free, open-source, handles JS rendering."""

from __future__ import annotations

from datetime import datetime, timezone

from crawl4ai import CrawlerStrategy, WebCrawler

from hyperresearch.web.base import WebResult


class Crawl4AIProvider:
    name = "crawl4ai"

    def __init__(self):
        self._crawler = WebCrawler()
        self._crawler.warmup()

    def fetch(self, url: str) -> WebResult:
        result = self._crawler.run(url=url)
        return WebResult(
            url=url,
            title=result.metadata.get("title", "") if result.metadata else "",
            content=result.markdown or result.extracted_content or "",
            raw_html=result.html,
            fetched_at=datetime.now(timezone.utc),
            metadata=result.metadata or {},
        )

    def search(self, query: str, max_results: int = 5) -> list[WebResult]:
        raise NotImplementedError(
            "crawl4ai does not support web search directly. "
            "Use tavily for search: pip install hyperresearch[tavily]"
        )
