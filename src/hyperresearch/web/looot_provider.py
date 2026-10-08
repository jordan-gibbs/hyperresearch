"""looot web provider: Google search results plus page fetch behind one key.

looot (https://looot.ai) runs third-party data APIs through one prepaid key and
bills per call; a failed call is not charged. This provider pins two endpoints
so the response shape never changes under it: Serper's Google search
(`serper-search`) and Serper's page scrape (`serper-webpage`), both run through
looot's `POST /v1/runs`. Search results carry only the SERP snippet, so
`search` fetches each page through the same key and keeps the snippet when a
page cannot be fetched or comes back as a bot wall.

Configuration:
    export LOOOT_TOKEN="your-token"   # https://looot.ai

    # in .hyperresearch/config.toml
    [web]
    provider = "looot"

No extra install: uses the httpx dependency the core already carries.
"""

from __future__ import annotations

import os
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx

from hyperresearch.web.base import WebResult

_BASE_URL = "https://api.looot.ai"
_SEARCH_ENDPOINT = "serper-search"
_FETCH_ENDPOINT = "serper-webpage"
_TIMEOUT = 45.0
_WAIT_SECONDS = 30
_POLL_INTERVAL = 1.0
_TERMINAL = {"completed", "failed", "blocked", "stopped"}


class LoootProvider:
    """Web provider backed by the looot API (https://docs.looot.ai).

    Supports both `search` (Google organic results) and `fetch` (URL to Markdown).
    """

    name = "looot"

    def __init__(
        self,
        token: str | None = None,
        fetch_content: bool = True,
        max_characters: int = 8000,
        transport: httpx.BaseTransport | None = None,
    ):
        key = token or os.environ.get("LOOOT_TOKEN", "").strip()
        if not key:
            raise RuntimeError(
                "LOOOT_TOKEN is not set. Create a token at https://looot.ai and export it."
            )

        self._client = httpx.Client(
            base_url=_BASE_URL,
            headers={"Authorization": f"Bearer {key}", "User-Agent": "hyperresearch"},
            timeout=_TIMEOUT,
            transport=transport,
        )
        self._fetch_content = fetch_content
        self._max_characters = max_characters

    def search(self, query: str, max_results: int = 5) -> list[WebResult]:
        """Search Google via looot and return ranked results with content."""
        output = self._run(_SEARCH_ENDPOINT, {"q": query, "num": max_results})
        items = output.get("organic", [])[:max_results]

        results: list[WebResult] = []
        for item in items:
            result = _to_web_result(item)
            if not result.url:
                continue
            if self._fetch_content:
                try:
                    fetched = self.fetch(result.url)
                except (httpx.HTTPError, RuntimeError):
                    fetched = None
                if fetched is not None and fetched.looks_like_junk() is None:
                    result.content = fetched.content
            results.append(result)
        return results

    def fetch(self, url: str) -> WebResult:
        """Fetch a single URL via looot and return it as Markdown."""
        output = self._run(_FETCH_ENDPOINT, {"url": url, "includeMarkdown": True})
        content = str(output.get("markdown") or output.get("text") or "").strip()
        content = content[: self._max_characters]
        if not content:
            raise RuntimeError(f"looot returned no content for {url}")
        title = (output.get("metadata") or {}).get("title") or ""
        return WebResult(url=url, title=str(title), content=content, fetched_at=datetime.now(UTC))

    def _run(self, endpoint_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Run one endpoint and return its output, polling if it outlives the wait."""
        resp = self._client.post(
            "/v1/runs",
            params={"wait": _WAIT_SECONDS},
            json={"endpointId": endpoint_id, "input": payload, "idempotencyKey": str(uuid.uuid4())},
        )
        resp.raise_for_status()
        run = resp.json()

        deadline = time.monotonic() + _TIMEOUT
        while run.get("status") not in _TERMINAL:
            if time.monotonic() >= deadline:
                raise RuntimeError(f"looot run {run.get('runId')} did not finish in time")
            time.sleep(_POLL_INTERVAL)
            poll = self._client.get(f"/v1/runs/{run['runId']}")
            poll.raise_for_status()
            run = poll.json()

        if run.get("status") != "completed":
            error = run.get("error") or {}
            message = error.get("message") or error.get("code") or run.get("status")
            raise RuntimeError(f"looot {endpoint_id} run failed: {message}")

        result = run.get("result")
        return result if isinstance(result, dict) else {}


def _to_web_result(item: dict[str, Any]) -> WebResult:
    """Convert a Google organic result dict into a hyperresearch WebResult."""
    metadata: dict[str, Any] = {}
    position = item.get("position")
    if position is not None:
        metadata["position"] = position
    date = item.get("date")
    if date:
        metadata["published_time"] = date

    return WebResult(
        url=item.get("link", "") or "",
        title=item.get("title", "") or "",
        content=item.get("snippet", "") or "",
        fetched_at=datetime.now(UTC),
        metadata=metadata,
    )
