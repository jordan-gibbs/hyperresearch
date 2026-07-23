"""Parallel Search MCP provider — no-account web search and page extraction.

Configuration:
    # in .hyperresearch/config.toml
    [web]
    provider = "parallel"

Optional install:
    pip install "hyperresearch[mcp]"
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult

from hyperresearch.web.base import WebResult

_ENDPOINT = "https://search.parallel.ai/mcp"
_MAX_OBJECTIVE_CHARS = 5000
_MAX_SEARCH_QUERY_CHARS = 200


class ParallelProvider:
    """Web provider backed by Parallel's free Search MCP endpoint.

    Each operation uses a short-lived MCP connection while the provider keeps
    one stable session identifier for free-tier request correlation. Transport,
    tool arguments, and result validation stay behind the synchronous
    ``WebProvider`` interface used by Hyperresearch's CLI.
    """

    name = "parallel"

    def __init__(self) -> None:
        self._session_id = uuid4().hex

    def search(self, query: str, max_results: int = 5) -> list[WebResult]:
        """Search the web and return ranked results with Markdown excerpts."""
        objective, search_query = _normalize_query(query)
        payload = self._call_tool(
            "web_search",
            {
                "objective": objective,
                "search_queries": [search_query],
                "session_id": self._session_id,
            },
        )
        results = _result_items(payload, "web_search")
        return [_to_web_result(item) for item in results[: max(0, max_results)]]

    def fetch(self, url: str) -> WebResult:
        """Fetch one URL as clean Markdown."""
        payload = self._call_tool(
            "web_fetch",
            {
                "urls": [url],
                "full_content": True,
                "session_id": self._session_id,
            },
        )
        results = _result_items(payload, "web_fetch")
        if not results:
            raise RuntimeError(_fetch_error(payload, url))
        return _to_web_result(results[0])

    def _call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return asyncio.run(self._call_tool_async(name, arguments))

    async def _call_tool_async(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        async with (
            streamable_http_client(_ENDPOINT) as (read_stream, write_stream, _),
            ClientSession(read_stream, write_stream) as session,
        ):
            await session.initialize()
            result = await session.call_tool(name, arguments=arguments)
        return _decode_tool_result(result, name)


def _normalize_query(query: str) -> tuple[str, str]:
    value = query.strip()
    if not value:
        raise ValueError("search query must not be empty")
    return (
        _truncate_at_word_boundary(value, _MAX_OBJECTIVE_CHARS),
        _truncate_at_word_boundary(value, _MAX_SEARCH_QUERY_CHARS),
    )


def _truncate_at_word_boundary(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    truncated = value[:limit]
    head, separator, _ = truncated.rpartition(" ")
    return head.rstrip() if separator and head.strip() else truncated


def _decode_tool_result(result: CallToolResult, tool_name: str) -> dict[str, Any]:
    text_blocks = [block.text for block in result.content if block.type == "text"]
    text = "\n".join(text_blocks).strip()

    if result.isError:
        detail = text or "unknown MCP error"
        raise RuntimeError(f"Parallel {tool_name} failed: {detail}")

    if result.structuredContent is not None:
        return dict(result.structuredContent)

    if not text:
        raise RuntimeError(f"Parallel {tool_name} returned no structured or text content")

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Parallel {tool_name} returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"Parallel {tool_name} returned a non-object payload")
    return payload


def _result_items(payload: Mapping[str, Any], tool_name: str) -> list[Mapping[str, Any]]:
    results = payload.get("results")
    if not isinstance(results, list):
        raise RuntimeError(f"Parallel {tool_name} response is missing a results list")
    if not all(isinstance(item, dict) for item in results):
        raise RuntimeError(f"Parallel {tool_name} returned a malformed result")
    return results


def _fetch_error(payload: Mapping[str, Any], url: str) -> str:
    errors = payload.get("errors")
    if isinstance(errors, list) and errors and isinstance(errors[0], dict):
        error_type = errors[0].get("error_type")
        if isinstance(error_type, str) and error_type:
            return f"Parallel could not fetch {url}: {error_type}"
    return f"Parallel returned no contents for {url}"


def _to_web_result(item: Mapping[str, Any]) -> WebResult:
    url = item.get("url")
    if not isinstance(url, str) or not url:
        raise RuntimeError("Parallel returned a result without a URL")

    title = item.get("title")
    if title is None:
        title = ""
    if not isinstance(title, str):
        raise RuntimeError(f"Parallel returned an invalid title for {url}")

    full_content = item.get("full_content")
    excerpts = item.get("excerpts")
    if isinstance(full_content, str) and full_content.strip():
        content = full_content
    elif isinstance(excerpts, list) and all(isinstance(excerpt, str) for excerpt in excerpts):
        content = "\n\n".join(excerpts)
    else:
        raise RuntimeError(f"Parallel returned invalid content for {url}")
    if not content.strip():
        raise RuntimeError(f"Parallel returned no content for {url}")

    metadata: dict[str, Any] = {}
    publish_date = item.get("publish_date")
    if isinstance(publish_date, str) and publish_date:
        metadata["published_date"] = publish_date

    return WebResult(
        url=url,
        title=title,
        content=content,
        fetched_at=datetime.now(UTC),
        metadata=metadata,
    )
