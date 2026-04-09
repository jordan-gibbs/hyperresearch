"""Tavily web provider — search + extract API for LLM agents."""

from __future__ import annotations

import os
from datetime import datetime, timezone

from tavily import TavilyClient

from hyperresearch.web.base import WebResult


class TavilyProvider:
    name = "tavily"

    def __init__(self, api_key: str | None = None):
        key = api_key or os.environ.get("TAVILY_API_KEY", "")
        if not key:
            raise ValueError(
                "Tavily API key required. Set TAVILY_API_KEY env var "
                "or configure in .hyperresearch/config.toml"
            )
        self._client = TavilyClient(api_key=key)

    def fetch(self, url: str) -> WebResult:
        result = self._client.extract(urls=[url])
        if result and result.get("results"):
            r = result["results"][0]
            return WebResult(
                url=url,
                title=r.get("title", ""),
                content=r.get("raw_content", r.get("text", "")),
                fetched_at=datetime.now(timezone.utc),
                metadata={"source": "tavily-extract"},
            )
        raise RuntimeError(f"Tavily extract returned no results for {url}")

    def search(self, query: str, max_results: int = 5) -> list[WebResult]:
        response = self._client.search(
            query=query,
            max_results=max_results,
            include_raw_content=True,
        )
        results = []
        for r in response.get("results", []):
            results.append(
                WebResult(
                    url=r["url"],
                    title=r.get("title", ""),
                    content=r.get("raw_content", r.get("content", "")),
                    fetched_at=datetime.now(timezone.utc),
                    metadata={"score": r.get("score", 0), "source": "tavily-search"},
                )
            )
        return results
