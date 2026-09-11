"""RePEcProvider — an honestly-unavailable slot.

RePEc's API has no search function (https://ideas.repec.org/api.html), so
the provider must report itself unavailable whether or not `REPEC_API_KEY`
is set, must explain why in words a user can act on, and must never touch
the network. These tests pin all three, and pin the registry contract
(`slug`, `needs_key`, `key_env`) that the rest of the package imports.
"""

from __future__ import annotations

import pytest

from hyperresearch.scholar import base
from hyperresearch.scholar.providers import repec
from hyperresearch.scholar.providers.repec import RePEcProvider

KEY = "not-a-real-code"


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Fail loudly if anything reaches the HTTP seam."""
    calls: list[str] = []

    def fake_get(url: str, headers: dict[str, str] | None = None) -> str | None:
        calls.append(url)
        raise AssertionError(f"RePEcProvider must not make requests, got {url}")

    monkeypatch.setattr(base, "_http_get", fake_get)
    monkeypatch.setattr(base, "_throttle", lambda url: None)
    return calls


@pytest.fixture
def with_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPEC_API_KEY", KEY)


@pytest.fixture
def without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("REPEC_API_KEY", raising=False)


def test_registry_contract() -> None:
    provider = RePEcProvider()
    assert provider.slug == "repec"
    assert provider.label == "RePEc"
    assert provider.needs_key is True
    assert provider.key_env == ("REPEC_API_KEY",)
    # The user-facing blurb must not promise a search the upstream lacks.
    assert "NOT searchable" in provider.covers


def test_unavailable_without_key(without_key: None) -> None:
    provider = RePEcProvider()
    assert provider.api_key() is None
    assert provider.available() is False
    reason = provider.unavailable_reason()
    assert reason is not None
    assert reason.startswith("RePEc:")
    assert "no search function" in reason
    assert "ideas.repec.org/api.html" in reason


def test_still_unavailable_with_key(with_key: None) -> None:
    # The key is real and readable, but it does not unlock a search, and the
    # reason must say so rather than the base-class "set REPEC_API_KEY".
    provider = RePEcProvider()
    assert provider.api_key() == KEY
    assert provider.available() is False
    reason = provider.unavailable_reason()
    assert reason is not None
    assert "no search function" in reason
    assert "set REPEC_API_KEY" not in reason


def test_search_is_total_and_offline(no_network: list[str], with_key: None) -> None:
    provider = RePEcProvider()
    assert provider.search(None, "minimum wage employment effects", 20) == []
    assert provider.search(None, "", 5) == []
    assert provider.search(None, "q", 5, fresh=True) == []
    assert no_network == []


def test_search_is_total_without_key(no_network: list[str], without_key: None) -> None:
    assert RePEcProvider().search(None, "inflation expectations", 10) == []
    assert no_network == []


def test_future_search_method_reverts_to_key_gating(
    monkeypatch: pytest.MonkeyPatch, without_key: None
) -> None:
    """The one-line unlock documented in the module: once RePEc ships a search
    method, availability falls back to the ordinary needs-a-key rule."""
    monkeypatch.setattr(repec, "_SEARCH_METHOD", "search")
    provider = RePEcProvider()
    assert provider.available() is False
    reason = provider.unavailable_reason()
    assert reason == "RePEc: set REPEC_API_KEY"

    monkeypatch.setenv("REPEC_API_KEY", KEY)
    assert provider.available() is True
    assert provider.unavailable_reason() is None
