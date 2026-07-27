"""Final-URL recheck + cert-refusal routing in the crawl4ai lanes.

The browser follows redirects on its own, so the entry-point SSRF gate only
vouches for where navigation started; these tests pin (a) that where it
LANDED is re-checked on every lane, and (b) that a TLS-cert refusal on a PDF
is never "retried" through the browser lane, which ignores TLS errors.
All offline: fake crawler, no browser, no network.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from hyperresearch.core.config import FetchSettings
from hyperresearch.web.safe_http import CertVerificationError, SafeHTTPError

provider = pytest.importorskip(
    "hyperresearch.web.crawl4ai_provider",
    reason="crawl4ai extra not installed",
)


def _run(coro):
    """Run ``coro`` in an isolated thread with its own loop (immune to the
    leaked running-loop state crawl4ai can leave behind on 3.11)."""
    import threading

    box: dict = {}

    def target() -> None:
        try:
            box["result"] = asyncio.run(coro)
        except Exception as exc:
            box["error"] = exc

    thread = threading.Thread(target=target)
    thread.start()
    thread.join()
    if "error" in box:
        raise box["error"]
    return box["result"]


class _FakeCR:
    """Stand-in for a crawl4ai result; ``final_url`` simulates the browser
    having been redirected away from the requested URL. Mirrors real
    crawl4ai semantics: ``url`` stays the REQUESTED url, the landing url is
    ``redirected_url`` (hermetic-tier proven)."""

    def __init__(self, requested: str, final_url: str | None = None):
        self.success = True
        self.url = requested
        self.redirected_url = final_url or requested
        self.markdown = f"browser text for {requested}"
        self.metadata = {"title": "T"}
        self.media = {}
        self.links = {}
        self.screenshot = None
        self.html = "<html></html>"


class _FakeCrawler:
    def __init__(self, captured: list[str], redirects: dict[str, str]):
        self._captured = captured
        self._redirects = redirects

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def arun(self, url, config):
        self._captured.append(url)
        return _FakeCR(url, self._redirects.get(url))

    async def arun_many(self, urls, config):
        self._captured.extend(urls)
        return [_FakeCR(u, self._redirects.get(u)) for u in urls]


def _bare_provider(
    captured: list[str],
    monkeypatch,
    redirects: dict[str, str] | None = None,
    settings: FetchSettings | None = None,
) -> object:
    inst = provider.Crawl4AIProvider.__new__(provider.Crawl4AIProvider)
    inst._settings = settings or provider.FetchSettings()
    inst._gates = provider.JunkGates()
    inst._run_config = object()
    inst._headless = True
    inst._data_dir = None
    monkeypatch.setattr(
        inst, "_make_crawler", lambda: _FakeCrawler(captured, redirects or {})
    )
    return inst


# ---------------------------------------------------------------------------
# _check_final_url — the shared helper all three lanes wire in
# ---------------------------------------------------------------------------


def test_same_host_final_url_skips_re_resolution():
    """No redirect off-host means no second getaddrinfo — the entry gate
    already vouched for this hostname."""
    with patch("hyperresearch.web.safe_http.socket.getaddrinfo") as gai:
        gai.side_effect = AssertionError("must not re-resolve same-host final URL")
        provider._check_final_url(
            "http://a.example/x", "http://a.example/y", FetchSettings()
        )


def test_unchanged_or_missing_final_url_is_a_noop():
    provider._check_final_url("http://a.example/x", "http://a.example/x", FetchSettings())
    provider._check_final_url("http://a.example/x", None, FetchSettings())


def test_cross_host_private_final_url_is_refused():
    with pytest.raises(SafeHTTPError, match="ended at refused URL"):
        provider._check_final_url(
            "http://8.8.8.8/start", "http://127.0.0.1/secret", FetchSettings()
        )


def test_final_url_recheck_honors_the_allowlist():
    provider._check_final_url(
        "http://8.8.8.8/start",
        "http://192.168.1.20/paper",
        FetchSettings(allow_private_hosts=("192.168.1.20",)),
    )


# ---------------------------------------------------------------------------
# Lane wiring — single fetch and batch
# ---------------------------------------------------------------------------


def test_single_fetch_refuses_result_that_landed_private(monkeypatch):
    captured: list[str] = []
    inst = _bare_provider(
        captured, monkeypatch,
        redirects={"http://8.8.8.8/a": "http://127.0.0.1/admin"},
    )
    with pytest.raises(SafeHTTPError, match="ended at refused URL"):
        _run(inst._fetch_async("http://8.8.8.8/a"))


def test_batch_drops_only_the_result_that_landed_private(monkeypatch):
    captured: list[str] = []
    inst = _bare_provider(
        captured, monkeypatch,
        redirects={"http://8.8.8.8/bad": "http://127.0.0.1/admin"},
    )
    results = _run(
        inst._fetch_many_async(["http://8.8.8.8/bad", "http://8.8.8.8/good"])
    )
    assert [r.url for r in results] == ["http://8.8.8.8/good"]


# ---------------------------------------------------------------------------
# Cert refusals never reach the TLS-ignoring browser lane
# ---------------------------------------------------------------------------


def _raise_cert(url, settings=None):
    raise CertVerificationError(f"certificate verification failed for {url!r}")


def test_batch_cert_refused_pdf_is_skipped_not_browsered(monkeypatch):
    """A cert-refused PDF must be a loud skip — handing it to the browser
    lane (ignore_https_errors) would be an automatic unverified retry."""
    monkeypatch.setattr(provider, "_fetch_pdf", _raise_cert)
    captured: list[str] = []
    inst = _bare_provider(captured, monkeypatch)

    results = _run(inst._fetch_many_async(["http://8.8.8.8/paper.pdf"]))

    assert results == []
    assert captured == []  # browser lane never entered


def test_single_fetch_cert_refusal_propagates_without_browser(monkeypatch):
    monkeypatch.setattr(provider, "_fetch_pdf", _raise_cert)
    captured: list[str] = []
    inst = _bare_provider(captured, monkeypatch)

    with pytest.raises(CertVerificationError):
        inst.fetch("http://8.8.8.8/paper.pdf")
    assert captured == []
