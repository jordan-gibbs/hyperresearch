"""Tests for the Firecrawl web provider: stubs the firecrawl-py SDK.

Like the other SDK-based provider tests, these inject a fake `firecrawl` package into
sys.modules, so the suite passes without `firecrawl-py` in the dev extra.
"""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest


class _ScrapeOptions:
    def __init__(self, **kwargs: Any) -> None:
        self.__dict__.update(kwargs)


def _install_fake_firecrawl(monkeypatch: pytest.MonkeyPatch, client: MagicMock) -> MagicMock:
    factory = MagicMock(return_value=client)
    pkg = ModuleType("firecrawl")
    pkg.Firecrawl = factory  # type: ignore[attr-defined]
    v2 = ModuleType("firecrawl.v2")
    types_mod = ModuleType("firecrawl.v2.types")
    types_mod.ScrapeOptions = _ScrapeOptions  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "firecrawl", pkg)
    monkeypatch.setitem(sys.modules, "firecrawl.v2", v2)
    monkeypatch.setitem(sys.modules, "firecrawl.v2.types", types_mod)
    # Force a fresh import so `from firecrawl import Firecrawl` binds the fake.
    sys.modules.pop("hyperresearch.web.firecrawl_provider", None)
    return factory


def _metadata(**overrides: Any) -> SimpleNamespace:
    fields: dict[str, Any] = {
        "url": "https://example.com/article",
        "source_url": "https://example.com/article",
        "title": "Example Article",
        "description": "Short description of the article.",
        "language": "en",
        "status_code": 200,
        "published_time": None,
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def _document(**overrides: Any) -> SimpleNamespace:
    fields: dict[str, Any] = {
        "markdown": "# Example Article\n\nFull page body.",
        "raw_html": "<html><head><title>Example Article</title></head></html>",
        "metadata": _metadata(),
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def test_provider_registered_via_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-test")
    _install_fake_firecrawl(monkeypatch, MagicMock())

    from hyperresearch.web.base import get_provider

    prov = get_provider("firecrawl")
    assert prov.name == "firecrawl"


def test_missing_api_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
    factory = _install_fake_firecrawl(monkeypatch, MagicMock())

    from hyperresearch.web.firecrawl_provider import FirecrawlProvider

    with pytest.raises(RuntimeError, match="FIRECRAWL_API_KEY"):
        FirecrawlProvider()
    factory.assert_not_called()


def test_client_built_with_key_and_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
    factory = _install_fake_firecrawl(monkeypatch, MagicMock())

    from hyperresearch.web.firecrawl_provider import FirecrawlProvider

    FirecrawlProvider(api_key="fc-test")
    factory.assert_called_once_with(api_key="fc-test", origin="hyperresearch")


def test_missing_sdk_raises_install_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-test")
    monkeypatch.setitem(sys.modules, "firecrawl", None)
    sys.modules.pop("hyperresearch.web.firecrawl_provider", None)

    from hyperresearch.web.base import get_provider

    with pytest.raises(ImportError, match=r"hyperresearch\[firecrawl\]"):
        get_provider("firecrawl")


def test_search_maps_scraped_results(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MagicMock()
    client.search.return_value = SimpleNamespace(web=[_document()])
    _install_fake_firecrawl(monkeypatch, client)

    from hyperresearch.web.firecrawl_provider import FirecrawlProvider

    results = FirecrawlProvider(api_key="fc-test").search("solid state batteries")
    assert len(results) == 1
    r = results[0]
    assert r.url == "https://example.com/article"
    assert r.title == "Example Article"
    assert r.content.startswith("# Example Article")
    assert r.metadata["description"] == "Short description of the article."
    assert r.metadata["status_code"] == 200
    assert "published_time" not in r.metadata


def test_search_falls_back_to_description_for_unscraped_hits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hit = SimpleNamespace(
        url="https://example.com/hit", title="Hit", description="Snippet only."
    )
    client = MagicMock()
    client.search.return_value = SimpleNamespace(web=[hit])
    _install_fake_firecrawl(monkeypatch, client)

    from hyperresearch.web.firecrawl_provider import FirecrawlProvider

    [r] = FirecrawlProvider(api_key="fc-test").search("q")
    assert r.url == "https://example.com/hit"
    assert r.title == "Hit"
    assert r.content == "Snippet only."


def test_search_passes_configured_options(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MagicMock()
    client.search.return_value = SimpleNamespace(web=None)
    _install_fake_firecrawl(monkeypatch, client)

    from hyperresearch.web.firecrawl_provider import FirecrawlProvider

    prov = FirecrawlProvider(
        api_key="fc-test",
        include_domains=["nature.com"],
        exclude_domains=["pinterest.com"],
    )
    assert prov.search("q", max_results=7) == []

    kwargs = client.search.call_args.kwargs
    assert kwargs["limit"] == 7
    assert kwargs["include_domains"] == ["nature.com"]
    assert kwargs["exclude_domains"] == ["pinterest.com"]
    assert kwargs["scrape_options"].formats == ["markdown"]
    assert kwargs["scrape_options"].only_main_content is True


def test_fetch_returns_markdown_and_raw_html(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MagicMock()
    client.scrape.return_value = _document(
        metadata=_metadata(url="https://example.com/final")
    )
    _install_fake_firecrawl(monkeypatch, client)

    from hyperresearch.web.firecrawl_provider import FirecrawlProvider

    r = FirecrawlProvider(api_key="fc-test").fetch("https://example.com/p")
    assert r.url == "https://example.com/final"
    assert r.title == "Example Article"
    assert r.content.startswith("# Example Article")
    assert r.raw_html is not None and "<title>" in r.raw_html

    args, kwargs = client.scrape.call_args
    assert args == ("https://example.com/p",)
    assert kwargs["formats"] == ["markdown", "rawHtml"]
    assert kwargs["only_main_content"] is True


def test_fetch_uses_requested_url_without_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MagicMock()
    client.scrape.return_value = _document(metadata=None)
    _install_fake_firecrawl(monkeypatch, client)

    from hyperresearch.web.firecrawl_provider import FirecrawlProvider

    r = FirecrawlProvider(api_key="fc-test").fetch("https://example.com/p")
    assert r.url == "https://example.com/p"
    assert r.title == ""


def test_fetch_empty_content_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    client = MagicMock()
    client.scrape.return_value = _document(markdown="  ")
    _install_fake_firecrawl(monkeypatch, client)

    from hyperresearch.web.firecrawl_provider import FirecrawlProvider

    with pytest.raises(RuntimeError, match="no content"):
        FirecrawlProvider(api_key="fc-test").fetch("https://example.com/p")
