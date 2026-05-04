"""Exa web provider — AI-native neural search returning ranked URLs with content.

Exa (https://exa.ai) is a search API designed for agents: results are ranked by
semantic relevance to the query and contents (text, highlights, summary) can be
returned in a single request.

Configuration:
    export EXA_API_KEY="your-api-key"     # https://dashboard.exa.ai/api-keys

    # in .hyperresearch/config.toml
    [web]
    provider = "exa"

Optional install:
    pip install "hyperresearch[exa]"
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from hyperresearch.web.base import WebResult


class ExaProvider:
    """Web provider backed by the Exa search API.

    Supports both `search` (neural ranking) and `fetch` (URL → contents).
    Content is returned as plain text (Exa's extracted main-page text);
    when text is empty, falls back to highlights, then summary.
    """

    name = "exa"

    def __init__(
        self,
        api_key: str | None = None,
        search_type: str = "auto",
        text_max_characters: int = 8000,
        category: str | None = None,
        include_domains: list[str] | None = None,
        exclude_domains: list[str] | None = None,
    ):
        try:
            from exa_py import Exa
        except ImportError as exc:
            raise ImportError(
                'exa provider requires: pip install "hyperresearch[exa]"'
            ) from exc

        key = api_key or os.environ.get("EXA_API_KEY", "").strip()
        if not key:
            raise RuntimeError(
                "EXA_API_KEY is not set. Get a free key at "
                "https://dashboard.exa.ai/api-keys and export it."
            )

        self._client = Exa(api_key=key)
        # Tracking header so Exa can attribute traffic to this integration.
        self._client.headers["x-exa-integration"] = "hyperresearch"

        self._search_type = search_type
        self._text_max_characters = text_max_characters
        self._category = category
        self._include_domains = include_domains
        self._exclude_domains = exclude_domains

    def search(self, query: str, max_results: int = 5) -> list[WebResult]:
        """Search the web via Exa and return ranked results with content."""
        kwargs: dict[str, Any] = {
            "num_results": max_results,
            "type": self._search_type,
            "contents": {
                "text": {"max_characters": self._text_max_characters},
                "highlights": True,
            },
        }
        if self._category:
            kwargs["category"] = self._category
        if self._include_domains:
            kwargs["include_domains"] = self._include_domains
        if self._exclude_domains:
            kwargs["exclude_domains"] = self._exclude_domains

        response = self._client.search(query, **kwargs)
        return [_to_web_result(r) for r in response.results]

    def fetch(self, url: str) -> WebResult:
        """Fetch a single URL via Exa /contents and return clean text."""
        response = self._client.get_contents(
            [url],
            text={"max_characters": self._text_max_characters},
        )
        if not response.results:
            raise RuntimeError(f"Exa returned no contents for {url}")
        return _to_web_result(response.results[0])


def _to_web_result(item: Any) -> WebResult:
    """Convert an exa-py Result into a hyperresearch WebResult.

    Cascades through text → highlights → summary so the caller always gets
    something usable in `content`, regardless of which content modes Exa
    populated for this row.
    """
    text = getattr(item, "text", None) or ""
    highlights = getattr(item, "highlights", None) or []
    summary = getattr(item, "summary", None) or ""

    if text.strip():
        content = text
    elif highlights:
        content = "\n\n".join(h for h in highlights if h)
    else:
        content = summary

    metadata: dict[str, Any] = {}
    for field in ("author", "published_date", "score", "favicon", "image"):
        value = getattr(item, field, None)
        if value:
            metadata[field] = value
    if highlights:
        metadata["highlights"] = list(highlights)
    if summary and summary != content:
        metadata["summary"] = summary

    return WebResult(
        url=getattr(item, "url", "") or "",
        title=getattr(item, "title", None) or "",
        content=content,
        fetched_at=datetime.now(UTC),
        metadata=metadata,
    )
