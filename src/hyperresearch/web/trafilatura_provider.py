"""Trafilatura web provider — lightweight text extraction, no JS rendering."""

from __future__ import annotations

from datetime import datetime, timezone

import trafilatura

from hyperresearch.web.base import WebResult


class TrafilaturaProvider:
    name = "trafilatura"

    def fetch(self, url: str) -> WebResult:
        downloaded = trafilatura.fetch_url(url)
        if downloaded is None:
            raise RuntimeError(f"Failed to download {url}")

        content = trafilatura.extract(
            downloaded,
            output_format="txt",
            include_links=True,
            include_tables=True,
        ) or ""

        metadata = trafilatura.extract_metadata(downloaded)
        title = metadata.title if metadata and metadata.title else ""
        meta_dict = {}
        if metadata:
            if metadata.author:
                meta_dict["author"] = metadata.author
            if metadata.date:
                meta_dict["date"] = metadata.date

        return WebResult(
            url=url,
            title=title,
            content=content,
            raw_html=downloaded,
            fetched_at=datetime.now(timezone.utc),
            metadata=meta_dict,
        )

    def search(self, query: str, max_results: int = 5) -> list[WebResult]:
        raise NotImplementedError(
            "Trafilatura does not support web search. "
            "Use tavily for search: pip install hyperresearch[tavily]"
        )
