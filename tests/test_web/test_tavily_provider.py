"""Tests for the Tavily web provider — stubs the tavily-python SDK.

Unlike the exa tests (which patch the real `exa_py` module and therefore need
it installed), these inject a fake `tavily` module into sys.modules, so the
suite passes without `tavily-python` in the dev extra.
"""

from __future__ import annotations

import sys
from types import ModuleType
from typing import Any
from unittest.mock import MagicMock

import pytest


def _install_fake_tavily(monkeypatch: pytest.MonkeyPatch, client: MagicMock) -> None:
    fake = ModuleType("tavily")
    fake.TavilyClient = MagicMock(return_value=client)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "tavily", fake)
    # The provider module may have been imported by an earlier test; force a
    # fresh import so its `from tavily import TavilyClient` binds the fake.
    sys.modules.pop("hyperresearch.web.tavily_provider", None)


def _search_item(**overrides: Any) -> dict:
    item = {
        "url": "https://example.com/article",
        "title": "Example Article",
        "content": "Snippet of the article body.",
        "score": 0.91,
        "published_date": "2026-06-01",
    }
    item.update(overrides)
    return item


def test_provider_registered_via_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-test")
    _install_fake_tavily(monkeypatch, MagicMock())

    from hyperresearch.web.base import get_provider

    prov = get_provider("tavily")
    assert prov.name == "tavily"


def test_missing_api_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    _install_fake_tavily(monkeypatch, MagicMock())

    from hyperresearch.web.tavily_provider import TavilyProvider

    with pytest.raises(RuntimeError, match="TAVILY_API_KEY"):
        TavilyProvider()


def test_search_maps_results_to_webresult(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MagicMock()
    client.search.return_value = {"results": [_search_item()]}
    _install_fake_tavily(monkeypatch, client)

    from hyperresearch.web.tavily_provider import TavilyProvider

    results = TavilyProvider(api_key="tvly-test").search("solid state batteries")
    assert len(results) == 1
    r = results[0]
    assert r.url == "https://example.com/article"
    assert r.title == "Example Article"
    assert r.content == "Snippet of the article body."
    assert r.metadata["score"] == 0.91
    assert r.metadata["published_date"] == "2026-06-01"


def test_search_passes_configured_options(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MagicMock()
    client.search.return_value = {"results": []}
    _install_fake_tavily(monkeypatch, client)

    from hyperresearch.web.tavily_provider import TavilyProvider

    prov = TavilyProvider(
        api_key="tvly-test",
        search_depth="basic",
        include_domains=["nature.com"],
        exclude_domains=["pinterest.com"],
    )
    prov.search("q", max_results=7)

    kwargs = client.search.call_args.kwargs
    assert kwargs["max_results"] == 7
    assert kwargs["search_depth"] == "basic"
    assert kwargs["include_domains"] == ["nature.com"]
    assert kwargs["exclude_domains"] == ["pinterest.com"]


def test_fetch_uses_extract_and_raw_content(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MagicMock()
    client.extract.return_value = {
        "results": [
            {"url": "https://example.com/p", "raw_content": "Full extracted page text."}
        ]
    }
    _install_fake_tavily(monkeypatch, client)

    from hyperresearch.web.tavily_provider import TavilyProvider

    r = TavilyProvider(api_key="tvly-test").fetch("https://example.com/p")
    assert r.content == "Full extracted page text."
    assert r.title == ""


def test_fetch_no_results_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MagicMock()
    client.extract.return_value = {"results": []}
    _install_fake_tavily(monkeypatch, client)

    from hyperresearch.web.tavily_provider import TavilyProvider

    with pytest.raises(RuntimeError, match="no contents"):
        TavilyProvider(api_key="tvly-test").fetch("https://example.com/p")


def test_content_falls_back_to_raw_content(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MagicMock()
    client.search.return_value = {
        "results": [_search_item(content="", raw_content="Raw body wins.")]
    }
    _install_fake_tavily(monkeypatch, client)

    from hyperresearch.web.tavily_provider import TavilyProvider

    results = TavilyProvider(api_key="tvly-test").search("q")
    assert results[0].content == "Raw body wins."
