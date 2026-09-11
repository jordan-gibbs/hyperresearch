"""Tests for the Parallel provider — stubs the optional MCP SDK.

The test suite must collect without ``hyperresearch[parallel]`` installed.
These tests inject the small MCP surface the provider imports into
``sys.modules``, following the same isolation pattern as the Tavily tests.
"""

from __future__ import annotations

import builtins
import importlib
import json
import sys
from collections.abc import Iterator
from datetime import timedelta
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from hyperresearch.core.config import FetchSettings

_MISSING = object()


@pytest.fixture
def parallel_module(monkeypatch: pytest.MonkeyPatch) -> Iterator[ModuleType]:
    fake_mcp = ModuleType("mcp")
    fake_mcp.__path__ = []  # type: ignore[attr-defined]
    fake_client = ModuleType("mcp.client")
    fake_client.__path__ = []  # type: ignore[attr-defined]
    fake_transport = ModuleType("mcp.client.streamable_http")

    fake_mcp.ClientSession = MagicMock()  # type: ignore[attr-defined]
    fake_transport.streamablehttp_client = MagicMock()  # type: ignore[attr-defined]
    fake_mcp.client = fake_client  # type: ignore[attr-defined]
    fake_client.streamable_http = fake_transport  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "mcp", fake_mcp)
    monkeypatch.setitem(sys.modules, "mcp.client", fake_client)
    monkeypatch.setitem(sys.modules, "mcp.client.streamable_http", fake_transport)
    sys.modules.pop("hyperresearch.web.parallel_provider", None)

    yield importlib.import_module("hyperresearch.web.parallel_provider")

    sys.modules.pop("hyperresearch.web.parallel_provider", None)


def _search_item(**overrides: Any) -> dict[str, Any]:
    item: dict[str, Any] = {
        "url": "https://example.com/article",
        "title": "Example Article",
        "publish_date": "2026-07-22",
        "excerpts": ["First excerpt.", "Second excerpt."],
    }
    item.update(overrides)
    return item


def _tool_result(
    text: str = "",
    *,
    structured_content: object = _MISSING,
    is_error: bool = False,
) -> SimpleNamespace:
    content = [SimpleNamespace(type="text", text=text)] if text else []
    result = SimpleNamespace(content=content, isError=is_error)
    if structured_content is not _MISSING:
        result.structuredContent = structured_content
    return result


def test_provider_registered_via_factory(parallel_module: ModuleType) -> None:
    from hyperresearch.web.base import get_provider

    provider = get_provider("parallel", settings=FetchSettings(page_timeout_ms=4321))

    assert isinstance(provider, parallel_module.ParallelProvider)
    assert provider._timeout == timedelta(milliseconds=4321)


def test_missing_sdk_names_parallel_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    from hyperresearch.web.base import get_provider

    real_import = builtins.__import__

    def import_without_mcp(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "mcp" or name.startswith("mcp."):
            raise ImportError("No module named 'mcp'")
        return real_import(name, *args, **kwargs)

    sys.modules.pop("hyperresearch.web.parallel_provider", None)
    monkeypatch.setattr(builtins, "__import__", import_without_mcp)

    with pytest.raises(ImportError, match=r"hyperresearch\[parallel\]"):
        get_provider("parallel")


def test_search_maps_results_limits_output_and_reuses_process_session(
    parallel_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider_type = parallel_module.ParallelProvider
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_call(self: Any, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        calls.append((name, arguments))
        return {"results": [_search_item(), _search_item(url="https://example.com/second")]}

    monkeypatch.setattr(provider_type, "_call_tool", fake_call)
    results = provider_type().search("solid state batteries", max_results=1)
    provider_type().fetch("https://example.com/article")

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
    parallel_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    length: int,
    objective_length: int,
    search_query_length: int,
) -> None:
    provider_type = parallel_module.ParallelProvider
    captured: dict[str, Any] = {}

    def fake_call(self: Any, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        captured.update(arguments)
        return {"results": []}

    monkeypatch.setattr(provider_type, "_call_tool", fake_call)
    provider_type().search("x" * length)

    assert len(captured["objective"]) == objective_length
    assert len(captured["search_queries"][0]) == search_query_length


def test_search_rejects_empty_query(
    parallel_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider_type = parallel_module.ParallelProvider

    def fail_call(self: Any, name: str, arguments: dict[str, Any]) -> None:
        pytest.fail("MCP should not be called")

    monkeypatch.setattr(provider_type, "_call_tool", fail_call)

    with pytest.raises(ValueError, match="must not be empty"):
        provider_type().search("   ")


def test_fetch_requests_full_content_and_prefers_it(
    parallel_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider_type = parallel_module.ParallelProvider
    captured: dict[str, Any] = {}

    def fake_call(self: Any, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        captured.update({"name": name, "arguments": arguments})
        return {
            "results": [
                _search_item(full_content="Full page Markdown.", excerpts=["Short excerpt."])
            ],
            "errors": [],
        }

    monkeypatch.setattr(provider_type, "_call_tool", fake_call)
    result = provider_type().fetch("https://example.com/article")

    assert captured["name"] == "web_fetch"
    assert captured["arguments"]["urls"] == ["https://example.com/article"]
    assert captured["arguments"]["full_content"] is True
    assert result.content == "Full page Markdown."


def test_fetch_falls_back_to_excerpts(
    parallel_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider_type = parallel_module.ParallelProvider
    monkeypatch.setattr(
        provider_type,
        "_call_tool",
        lambda self, name, arguments: {
            "results": [_search_item(full_content=None, excerpts=["One.", "Two."])],
            "errors": [],
        },
    )

    result = provider_type().fetch("https://example.com/article")
    assert result.content == "One.\n\nTwo."


def test_fetch_surfaces_extract_error(
    parallel_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider_type = parallel_module.ParallelProvider
    monkeypatch.setattr(
        provider_type,
        "_call_tool",
        lambda self, name, arguments: {
            "results": [],
            "errors": [{"url": "https://example.com/missing", "error_type": "not_found"}],
        },
    )

    with pytest.raises(RuntimeError, match="not_found"):
        provider_type().fetch("https://example.com/missing")


def test_malformed_results_raise(
    parallel_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider_type = parallel_module.ParallelProvider
    monkeypatch.setattr(
        provider_type,
        "_call_tool",
        lambda self, name, arguments: {"results": "not-a-list"},
    )

    with pytest.raises(RuntimeError, match="results list"):
        provider_type().search("query")


def test_timeout_applies_to_transport_session_and_tool_call(
    parallel_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}

    class AsyncContext:
        def __init__(self, value: Any) -> None:
            self.value = value

        async def __aenter__(self) -> Any:
            return self.value

        async def __aexit__(self, *args: Any) -> None:
            return None

    class FakeSession:
        def __init__(self, read: object, write: object, **kwargs: Any) -> None:
            observed["session_timeout"] = kwargs["read_timeout_seconds"]

        async def __aenter__(self) -> FakeSession:
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def initialize(self) -> None:
            observed["initialized"] = True

        async def call_tool(self, name: str, **kwargs: Any) -> SimpleNamespace:
            observed["tool_timeout"] = kwargs["read_timeout_seconds"]
            return _tool_result(json.dumps({"results": []}))

    def fake_transport(endpoint: str, **kwargs: Any) -> AsyncContext:
        observed["endpoint"] = endpoint
        observed["transport_timeout"] = kwargs["timeout"]
        observed["sse_timeout"] = kwargs["sse_read_timeout"]
        return AsyncContext((object(), object(), None))

    monkeypatch.setattr(parallel_module, "streamablehttp_client", fake_transport)
    monkeypatch.setattr(parallel_module, "ClientSession", FakeSession)

    timeout = timedelta(milliseconds=1234)
    result = parallel_module.ParallelProvider(FetchSettings(page_timeout_ms=1234))._call_tool(
        "web_search", {}
    )

    assert result == {"results": []}
    assert observed == {
        "endpoint": "https://search.parallel.ai/mcp",
        "transport_timeout": timeout,
        "sse_timeout": timeout,
        "session_timeout": timeout,
        "initialized": True,
        "tool_timeout": timeout,
    }


def test_tool_result_uses_structured_content(parallel_module: ModuleType) -> None:
    result = _tool_result("ignored", structured_content={"results": []})
    assert parallel_module._decode_tool_result(result, "web_search") == {"results": []}


def test_old_tool_result_without_structured_content_uses_json_text(
    parallel_module: ModuleType,
) -> None:
    result = _tool_result(json.dumps({"results": []}))
    assert not hasattr(result, "structuredContent")
    assert parallel_module._decode_tool_result(result, "web_search") == {"results": []}


def test_tool_error_raises_with_detail(parallel_module: ModuleType) -> None:
    result = _tool_result("rate limited", is_error=True)
    with pytest.raises(RuntimeError, match="rate limited"):
        parallel_module._decode_tool_result(result, "web_search")
