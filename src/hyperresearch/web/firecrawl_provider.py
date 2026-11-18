"""Firecrawl web provider: web search with page Markdown, and page scraping.

Firecrawl (https://www.firecrawl.dev) searches the web and scrapes pages into
clean Markdown. `search` returns each result's page content in the same call,
so results do not need a second fetch. There is no batch fetch, so `fetch-batch`
goes one URL at a time. PDFs are extracted on Firecrawl's side, so no raw file
is saved for them.

Configuration:
    export FIRECRAWL_API_KEY="fc-your-api-key"   # https://www.firecrawl.dev/app/api-keys

    # in .hyperresearch/config.toml
    [web]
    provider = "firecrawl"

Optional install:
    pip install "hyperresearch[firecrawl]"
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from hyperresearch.web.base import WebResult

_METADATA_FIELDS = ("description", "language", "status_code", "published_time", "author")


class FirecrawlProvider:
    """Web provider backed by the Firecrawl API.

    Supports both `search` (results with page Markdown) and `fetch`
    (URL to Markdown, main content only).
    """

    name = "firecrawl"

    def __init__(
        self,
        api_key: str | None = None,
        only_main_content: bool = True,
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
    ):
        try:
            from firecrawl import Firecrawl
        except ImportError as exc:
            raise ImportError(
                'firecrawl provider requires: pip install "hyperresearch[firecrawl]"'
            ) from exc

        key = api_key or os.environ.get("FIRECRAWL_API_KEY", "").strip()
        if not key:
            raise RuntimeError(
                "FIRECRAWL_API_KEY is not set. Get a key at "
                "https://www.firecrawl.dev/app/api-keys and export it."
            )

        # Origin tag so Firecrawl can attribute traffic to this integration.
        self._client = Firecrawl(api_key=key, origin="hyperresearch")
        self._only_main_content = only_main_content
        self._include_domains = include_domains
        self._exclude_domains = exclude_domains

    def search(self, query: str, max_results: int = 5) -> list[WebResult]:
        """Search the web via Firecrawl and return results with page Markdown."""
        from firecrawl.v2.types import ScrapeOptions

        kwargs: dict[str, Any] = {
            "limit": max_results,
            "scrape_options": ScrapeOptions(
                formats=["markdown"], only_main_content=self._only_main_content
            ),
        }
        if self._include_domains:
            kwargs["include_domains"] = self._include_domains
        if self._exclude_domains:
            kwargs["exclude_domains"] = self._exclude_domains

        response = self._client.search(query, **kwargs)
        return [_to_web_result(item) for item in response.web or []]

    def fetch(self, url: str) -> WebResult:
        """Scrape a single URL via Firecrawl and return its Markdown and raw HTML."""
        doc = self._client.scrape(
            url,
            formats=["markdown", "rawHtml"],
            only_main_content=self._only_main_content,
        )
        if not (doc.markdown or "").strip():
            raise RuntimeError(f"Firecrawl returned no content for {url}")
        return _to_web_result(doc, fallback_url=url)


def _to_web_result(item: Any, fallback_url: str = "") -> WebResult:
    """Convert a Firecrawl search result or scraped document into a WebResult.

    Search results come back as scraped documents (page Markdown plus metadata)
    when scraping succeeds, or as plain hits (url, title, description) when it
    does not; the description is the content fallback for the latter.
    """
    meta = getattr(item, "metadata", None)
    url = (
        getattr(item, "url", None)
        or getattr(meta, "url", None)
        or getattr(meta, "source_url", None)
        or fallback_url
    )
    title = getattr(item, "title", None) or getattr(meta, "title", None) or ""
    description = getattr(item, "description", None) or getattr(meta, "description", None)
    content = getattr(item, "markdown", None) or description or ""

    metadata: dict[str, Any] = {}
    for field in _METADATA_FIELDS:
        value = getattr(meta, field, None)
        if value:
            metadata[field] = value
    if description and "description" not in metadata:
        metadata["description"] = description

    return WebResult(
        url=url,
        title=title.strip() if isinstance(title, str) else "",
        content=content,
        fetched_at=datetime.now(UTC),
        raw_html=getattr(item, "raw_html", None),
        metadata=metadata,
    )
