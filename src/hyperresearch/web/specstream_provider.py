"""SpecStream web provider: Search API and Extract API behind one key.

SpecStream (https://specstream.ai) answers a web search with ranked sources,
result rows and, for a question with one answer, the answer with the page it
was read from. The Extract API reads pages as Markdown. `search` reads the
sources of one Search API call and, by default, reads their pages in a single
Extract API call, falling back to the snippet for a page that cannot be read.

Configuration:
    export SPECSTREAM_API_KEY="your-api-key"   # https://specstream.ai

    # in .hyperresearch/config.toml
    [web]
    provider = "specstream"

No extra install: uses the httpx dependency the core already carries.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

import httpx

from hyperresearch.web.base import WebResult

_SEARCH_URL = "https://api.specstream.ai/v1/web-search"
_EXTRACT_URL = "https://api.specstream.ai/v1/extract"
_TIMEOUT = 60.0
_EXTRACT_BATCH = 20  # the Extract API reads at most 20 URLs per call


class SpecStreamProvider:
    """Web provider backed by the SpecStream Search API and Extract API.

    Supports both `search` (ranked sources and rows) and `fetch` (URL to Markdown).
    """

    name = "specstream"

    def __init__(
        self,
        api_key: str | None = None,
        fetch_content: bool = True,
        max_characters: int = 20000,
        transport: httpx.BaseTransport | None = None,
    ):
        key = api_key or os.environ.get("SPECSTREAM_API_KEY", "").strip()
        if not key:
            raise RuntimeError(
                "SPECSTREAM_API_KEY is not set. Get a key at https://specstream.ai and export it."
            )

        self._client = httpx.Client(
            headers={"Authorization": f"Bearer {key}", "User-Agent": "hyperresearch"},
            timeout=_TIMEOUT,
            transport=transport,
        )
        self._fetch_content = fetch_content
        self._max_characters = max_characters

    def search(self, query: str, max_results: int = 5) -> list[WebResult]:
        """Search the web via SpecStream and return ranked results with content."""
        resp = self._client.get(_SEARCH_URL, params={"q": query, "num": max_results})
        resp.raise_for_status()
        data = resp.json().get("data") or {}

        results = _results_from_search(data)[:max_results]
        if self._fetch_content and results:
            pages = self._extract([r.url for r in results])
            for result in results:
                item = pages.get(result.url)
                if item is None:
                    continue
                fetched = _page_to_web_result(item, self._max_characters)
                if fetched is not None and fetched.looks_like_junk() is None:
                    result.content = fetched.content
        return results

    def fetch(self, url: str) -> WebResult:
        """Fetch a single URL via SpecStream Extract and return it as Markdown."""
        item = self._extract([url]).get(url)
        if item is None:
            raise RuntimeError(f"SpecStream returned no contents for {url}")
        result = _page_to_web_result(item, self._max_characters)
        if result is None:
            status = item.get("status", "unknown")
            raise RuntimeError(f"SpecStream returned no content for {url} (status: {status})")
        return result

    def _extract(self, urls: list[str]) -> dict[str, dict[str, Any]]:
        """Read pages through the Extract API; map each requested URL to its item."""
        pages: dict[str, dict[str, Any]] = {}
        for start in range(0, len(urls), _EXTRACT_BATCH):
            batch = urls[start : start + _EXTRACT_BATCH]
            try:
                resp = self._client.post(_EXTRACT_URL, json={"urls": batch, "format": "markdown"})
                resp.raise_for_status()
            except httpx.HTTPError:
                continue
            items = (resp.json().get("data") or {}).get("results") or []
            # One item per URL sent, in the order sent.
            for url, item in zip(batch, items, strict=False):
                pages[url] = item
        return pages


def _results_from_search(data: dict[str, Any]) -> list[WebResult]:
    """Turn a Search API `data` object into WebResults: sources first, then row pages."""
    answer = data.get("answer") or {}
    answer_page = answer.get("page") if isinstance(answer, dict) else None

    results: list[WebResult] = []
    by_url: dict[str, WebResult] = {}

    for source in data.get("sources") or []:
        url = source.get("url") or ""
        if not url or url in by_url:
            continue
        metadata: dict[str, Any] = {}
        if source.get("published"):
            metadata["published_date"] = source["published"]
        if source.get("cited"):
            metadata["cited"] = True
        result = WebResult(
            url=url,
            title=source.get("title", "") or "",
            content=source.get("snippet", "") or "",
            fetched_at=datetime.now(UTC),
            metadata=metadata,
        )
        by_url[url] = result
        results.append(result)

    for row in data.get("rows") or []:
        page = row.get("page") or ""
        if not page:
            continue
        row_result = by_url.get(page)
        if row_result is None:
            row_result = WebResult(
                url=page,
                title=row.get("name", "") or "",
                content=row.get("snippet", "") or "",
                fetched_at=datetime.now(UTC),
            )
            by_url[page] = row_result
            results.append(row_result)
        if row.get("probability") is not None:
            row_result.metadata["probability"] = row["probability"]
        if row.get("name"):
            row_result.metadata["row_name"] = row["name"]

    if answer_page and answer_page in by_url and answer.get("value") is not None:
        by_url[answer_page].metadata["answer"] = answer["value"]

    return results


def _page_to_web_result(item: dict[str, Any], max_characters: int) -> WebResult | None:
    """Convert an Extract API result into a WebResult, or None when the page gave no text."""
    text = (item.get("text") or "").strip()
    if item.get("status") != "ok" or not text:
        return None

    metadata: dict[str, Any] = {}
    if item.get("published"):
        metadata["published_date"] = item["published"]
    if item.get("read_from"):
        metadata["read_from"] = item["read_from"]

    return WebResult(
        url=item.get("url", "") or "",
        title=item.get("title", "") or "",
        content=text[:max_characters],
        fetched_at=datetime.now(UTC),
        metadata=metadata,
    )
