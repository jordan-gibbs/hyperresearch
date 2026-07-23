"""Offline tests for the Parallel Search MCP web provider."""

from __future__ import annotations

import json
from typing import Any

import pytest
from mcp.types import CallToolResult, TextContent

from hyperresearch.web.parallel_provider import ParallelProvider, _decode_tool_result


def _search_item(**overrides: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "url": "https://example.com/article",
        "title": "Example Article",
        "publish_date": "2026-07-22",
        "excerpts": ["First excerpt.", "Second excerpt."],
    }
    item.update(overrides)
    return item


def test_provider_registered_via_factory() -> None:
    from hyperresearch.web.base import get_provider

    provider = get_provider("parallel")
    assert provider.name == "parallel"


def test_search_maps_results_limits_output_and_reuses_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_call(self: ParallelProvider, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        calls.append((name, arguments))
        return {"results": [_search_item(), _search_item(url="https://example.com/second")]}

    monkeypatch.setattr(ParallelProvider, "_call_tool", fake_call)
    provider = ParallelProvider()

    results = provider.search("solid state batteries", max_results=1)
    provider.fetch("https://example.com/article")

    assert len(results) == 1
    assert results[0].url == "https://example.com/article"
    assert results[0].content == "First excerpt.\n\nSecond excerpt."
    assert results[0].metadata["published_date"] == "2026-07-22"
    assert calls[0][0] == "web_search"
    assert calls[0][1]["objective"] == "solid state batteries"
    assert calls[0][1]["search_queries"] == ["solid state batteries"]
    assert calls[0][1]["session_id"] == calls[1][1]["session_id"]


@pytest.mark.parametrize(
    ("length", "objective_length", "search_query_length"),
    [(200, 200, 200), (201, 201, 200), (5000, 5000, 200), (5001, 5000, 200)],
)
def test_search_bounds_tool_arguments(
    monkeypatch: pytest.MonkeyPatch,
    length: int,
    objective_length: int,
    search_query_length: int,
) -> None:
    captured: dict[str, Any] = {}

    def fake_call(self: ParallelProvider, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        captured.update(arguments)
        return {"results": []}

    monkeypatch.setattr(ParallelProvider, "_call_tool", fake_call)
    ParallelProvider().search("x" * length)

    assert len(captured["objective"]) == objective_length
    assert len(captured["search_queries"][0]) == search_query_length


def test_search_rejects_empty_query(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_call(self: ParallelProvider, name: str, arguments: dict[str, Any]) -> None:
        pytest.fail("MCP should not be called")

    monkeypatch.setattr(ParallelProvider, "_call_tool", fail_call)

    with pytest.raises(ValueError, match="must not be empty"):
        ParallelProvider().search("   ")


def test_fetch_requests_full_content_and_prefers_it(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_call(self: ParallelProvider, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        captured.update({"name": name, "arguments": arguments})
        return {
            "results": [
                _search_item(full_content="Full page Markdown.", excerpts=["Short excerpt."])
            ],
            "errors": [],
        }

    monkeypatch.setattr(ParallelProvider, "_call_tool", fake_call)
    result = ParallelProvider().fetch("https://example.com/article")

    assert captured["name"] == "web_fetch"
    assert captured["arguments"]["urls"] == ["https://example.com/article"]
    assert captured["arguments"]["full_content"] is True
    assert result.content == "Full page Markdown."


def test_fetch_falls_back_to_excerpts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ParallelProvider,
        "_call_tool",
        lambda self, name, arguments: {
            "results": [_search_item(full_content=None, excerpts=["One.", "Two."])],
            "errors": [],
        },
    )

    result = ParallelProvider().fetch("https://example.com/article")
    assert result.content == "One.\n\nTwo."


def test_fetch_surfaces_extract_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ParallelProvider,
        "_call_tool",
        lambda self, name, arguments: {
            "results": [],
            "errors": [{"url": "https://example.com/missing", "error_type": "not_found"}],
        },
    )

    with pytest.raises(RuntimeError, match="not_found"):
        ParallelProvider().fetch("https://example.com/missing")


def test_malformed_results_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        ParallelProvider,
        "_call_tool",
        lambda self, name, arguments: {"results": "not-a-list"},
    )

    with pytest.raises(RuntimeError, match="results list"):
        ParallelProvider().search("query")


def test_tool_result_uses_structured_content() -> None:
    result = CallToolResult(
        content=[TextContent(type="text", text="ignored")],
        structuredContent={"results": []},
    )
    assert _decode_tool_result(result, "web_search") == {"results": []}


def test_tool_result_falls_back_to_json_text() -> None:
    result = CallToolResult(content=[TextContent(type="text", text=json.dumps({"results": []}))])
    assert _decode_tool_result(result, "web_search") == {"results": []}


def test_tool_error_raises_with_detail() -> None:
    result = CallToolResult(content=[TextContent(type="text", text="rate limited")], isError=True)
    with pytest.raises(RuntimeError, match="rate limited"):
        _decode_tool_result(result, "web_search")
