"""Tests for the Exa web provider — mocks the exa-py SDK."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from hyperresearch.web.base import WebResult, get_provider


def _make_result(
    *,
    url: str = "https://example.com/article",
    title: str = "Example Article",
    text: str | None = "Full article body text.",
    highlights: list[str] | None = None,
    summary: str | None = None,
    score: float | None = 0.83,
    author: str | None = "Jane Doe",
    published_date: str | None = "2026-04-01",
) -> SimpleNamespace:
    return SimpleNamespace(
        url=url,
        id="abc",
        title=title,
        text=text,
        highlights=highlights or [],
        summary=summary,
        score=score,
        author=author,
        published_date=published_date,
        favicon=None,
        image=None,
    )


def _make_response(results: list[Any]) -> SimpleNamespace:
    return SimpleNamespace(results=results)


def _patch_sdk(monkeypatch: pytest.MonkeyPatch, client: MagicMock) -> None:
    """Patch `exa_py.Exa` at the source module — that's where the provider imports from."""
    import exa_py

    factory = MagicMock(return_value=client)
    monkeypatch.setattr(exa_py, "Exa", factory)


def test_provider_registered_via_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_provider('exa') returns an ExaProvider instance."""
    monkeypatch.setenv("EXA_API_KEY", "test-key")
    client = MagicMock()
    client.headers = {}
    _patch_sdk(monkeypatch, client)

    prov = get_provider("exa")

    assert prov.name == "exa"


def test_missing_api_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EXA_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="EXA_API_KEY"):
        get_provider("exa")


def test_integration_header_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """The x-exa-integration header must be set so Exa can attribute traffic."""
    monkeypatch.setenv("EXA_API_KEY", "test-key")
    client = MagicMock()
    client.headers = {}
    _patch_sdk(monkeypatch, client)

    get_provider("exa")

    assert client.headers["x-exa-integration"] == "hyperresearch"


def test_search_returns_web_results(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXA_API_KEY", "test-key")
    client = MagicMock()
    client.headers = {}
    client.search.return_value = _make_response([
        _make_result(url="https://a.test", title="A", text="Body A"),
        _make_result(url="https://b.test", title="B", text="Body B"),
    ])
    _patch_sdk(monkeypatch, client)

    prov = get_provider("exa")
    results = prov.search("transformers", max_results=2)

    assert len(results) == 2
    assert all(isinstance(r, WebResult) for r in results)
    assert results[0].url == "https://a.test"
    assert results[0].title == "A"
    assert results[0].content == "Body A"
    assert results[0].metadata["author"] == "Jane Doe"
    assert results[0].metadata["score"] == 0.83


def test_search_passes_num_results_and_contents(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify the call shape matches Exa's current API (contents object, not deprecated kwargs)."""
    monkeypatch.setenv("EXA_API_KEY", "test-key")
    client = MagicMock()
    client.headers = {}
    client.search.return_value = _make_response([])
    _patch_sdk(monkeypatch, client)

    prov = get_provider("exa")
    prov.search("foo", max_results=7)

    args, kwargs = client.search.call_args
    assert args == ("foo",)
    assert kwargs["num_results"] == 7
    assert kwargs["type"] == "auto"
    assert "text" in kwargs["contents"]
    assert kwargs["contents"]["highlights"] is True


def test_content_falls_back_to_highlights(monkeypatch: pytest.MonkeyPatch) -> None:
    """When text is empty, content should be joined highlights."""
    monkeypatch.setenv("EXA_API_KEY", "test-key")
    client = MagicMock()
    client.headers = {}
    client.search.return_value = _make_response([
        _make_result(text="", highlights=["snippet 1", "snippet 2"]),
    ])
    _patch_sdk(monkeypatch, client)

    prov = get_provider("exa")
    results = prov.search("q")

    assert results[0].content == "snippet 1\n\nsnippet 2"
    assert results[0].metadata["highlights"] == ["snippet 1", "snippet 2"]


def test_content_falls_back_to_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    """When text and highlights are missing, content should be the summary."""
    monkeypatch.setenv("EXA_API_KEY", "test-key")
    client = MagicMock()
    client.headers = {}
    client.search.return_value = _make_response([
        _make_result(text=None, highlights=[], summary="A short summary."),
    ])
    _patch_sdk(monkeypatch, client)

    prov = get_provider("exa")
    results = prov.search("q")

    assert results[0].content == "A short summary."


def test_content_handles_all_fields_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """No text / highlights / summary should yield empty content, not crash."""
    monkeypatch.setenv("EXA_API_KEY", "test-key")
    client = MagicMock()
    client.headers = {}
    client.search.return_value = _make_response([
        _make_result(text=None, highlights=[], summary=None),
    ])
    _patch_sdk(monkeypatch, client)

    prov = get_provider("exa")
    results = prov.search("q")

    assert results[0].content == ""


def test_fetch_uses_get_contents(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXA_API_KEY", "test-key")
    client = MagicMock()
    client.headers = {}
    client.get_contents.return_value = _make_response([
        _make_result(url="https://x.test", title="X", text="Body"),
    ])
    _patch_sdk(monkeypatch, client)

    prov = get_provider("exa")
    result = prov.fetch("https://x.test")

    assert isinstance(result, WebResult)
    assert result.url == "https://x.test"
    assert result.content == "Body"
    args, _ = client.get_contents.call_args
    assert args[0] == ["https://x.test"]


def test_fetch_raises_when_no_results(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EXA_API_KEY", "test-key")
    client = MagicMock()
    client.headers = {}
    client.get_contents.return_value = _make_response([])
    _patch_sdk(monkeypatch, client)

    prov = get_provider("exa")

    with pytest.raises(RuntimeError, match="no contents"):
        prov.fetch("https://nope.test")


def test_unknown_provider_lists_exa_in_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """The error message for unknown providers should advertise 'exa' as available."""
    with pytest.raises(ValueError, match="exa"):
        get_provider("not-a-real-provider")


def test_provider_disabled_when_module_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """If exa-py isn't installed, instantiating the provider raises ImportError."""
    monkeypatch.setenv("EXA_API_KEY", "test-key")

    import builtins

    real_import = builtins.__import__

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "exa_py":
            raise ImportError("No module named 'exa_py'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(ImportError, match="hyperresearch\\[exa\\]"):
        get_provider("exa")
