"""The crawl4ai headless lane verifies TLS certificates by default (#137).

crawl4ai defaults ``BrowserConfig.ignore_https_errors`` to True AND launches
Chromium with ``--ignore-certificate-errors`` unconditionally, so verifying
takes both a config value and stripping those launch flags. These tests pin
both halves, the ``[fetch] browser_verify_tls = false`` opt-out, and the
refusal message. All offline: object construction and fake crawlers only,
no browser launch, no network.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path

import pytest

from hyperresearch.core.config import FetchSettings, VaultConfig
from hyperresearch.web.safe_http import CertVerificationError

provider = pytest.importorskip(
    "hyperresearch.web.crawl4ai_provider",
    reason="crawl4ai extra not installed",
)

CERT_FLAGS = {"--ignore-certificate-errors", "--ignore-certificate-errors-spki-list"}

# What crawl4ai 0.8.6 put in result.error_message against a self-signed server.
REAL_CERT_ERROR = (
    "Unexpected error in _crawl_web at line 500 in wrap_api_call (...):\n"
    "Error: Page.goto: net::ERR_CERT_AUTHORITY_INVALID at https://self-signed.example/\n"
    "Call log:\n  - navigating to \"https://self-signed.example/\", waiting until "
    "\"domcontentloaded\"\n"
)


def _run(coro):
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


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def test_browser_verify_tls_defaults_true():
    assert FetchSettings().browser_verify_tls is True


def test_browser_verify_tls_loads_and_round_trips(tmp_path: Path):
    p = tmp_path / "config.toml"
    p.write_text("[fetch]\nbrowser_verify_tls = false\n", encoding="utf-8")
    cfg = VaultConfig.load(p)
    assert cfg.fetch.browser_verify_tls is False
    assert cfg.fetch.pdf_verify_tls is True  # independent knobs

    out = tmp_path / "saved.toml"
    cfg.save(out)
    assert "browser_verify_tls = false" in out.read_text(encoding="utf-8")
    assert VaultConfig.load(out).fetch.browser_verify_tls is False


# ---------------------------------------------------------------------------
# BrowserConfig + launch flags
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("profile_dir", [None, "/tmp/does-not-matter"])
def test_browser_config_verifies_by_default(profile_dir):
    inst = provider.Crawl4AIProvider(headless=True, user_data_dir=profile_dir)
    assert inst._browser_config.ignore_https_errors is False


@pytest.mark.parametrize("profile_dir", [None, "/tmp/does-not-matter"])
def test_browser_config_opt_out_ignores_errors(profile_dir):
    inst = provider.Crawl4AIProvider(
        headless=True,
        user_data_dir=profile_dir,
        settings=FetchSettings(browser_verify_tls=False),
    )
    assert inst._browser_config.ignore_https_errors is True


def test_default_launch_drops_cert_ignore_flags():
    """ignore_https_errors=False alone is not enough: crawl4ai's own launch
    args carry --ignore-certificate-errors, which Chromium obeys over the
    context setting. This runs against the installed crawl4ai, so a release
    that moves the flag builder fails here rather than in the field."""
    bm = provider.Crawl4AIProvider(headless=True)._make_crawler().crawler_strategy.browser_manager
    args = bm._build_browser_args()["args"]
    assert not CERT_FLAGS & set(args)
    assert "--disable-blink-features=AutomationControlled" in args  # rest intact


def test_managed_browser_launch_drops_cert_ignore_flags():
    """The profile path launches Chromium as a subprocess and attaches over
    CDP; its flags come from ManagedBrowser.build_browser_flags."""
    inst = provider.Crawl4AIProvider(headless=True, user_data_dir="/tmp/does-not-matter")
    bm = inst._make_crawler().crawler_strategy.browser_manager
    assert bm.managed_browser is not None
    flags = bm.managed_browser.build_browser_flags(inst._browser_config)
    assert not CERT_FLAGS & set(flags)
    assert "--no-sandbox" in flags


def test_stripping_is_per_instance_not_global():
    """The override must not leak into crawl4ai's classes or other crawlers."""
    from crawl4ai.browser_manager import ManagedBrowser

    inst = provider.Crawl4AIProvider(headless=True, user_data_dir="/tmp/does-not-matter")
    inst._make_crawler()
    assert set(ManagedBrowser.build_browser_flags(inst._browser_config)) >= CERT_FLAGS


def test_opt_out_keeps_crawl4ai_launch_flags():
    inst = provider.Crawl4AIProvider(
        headless=True, settings=FetchSettings(browser_verify_tls=False)
    )
    args = inst._make_crawler().crawler_strategy.browser_manager._build_browser_args()["args"]
    assert set(args) >= CERT_FLAGS


def test_missing_flag_builder_fails_closed():
    """If crawl4ai moves the builder, refuse rather than fetch unverified."""

    class _Strategy:
        browser_manager = object()

    with pytest.raises(RuntimeError, match="browser_verify_tls = false"):
        provider._strip_cert_ignore_flags(_Strategy())


# ---------------------------------------------------------------------------
# Refusal mapping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("message", "code"),
    [
        (REAL_CERT_ERROR, "ERR_CERT_AUTHORITY_INVALID"),
        ("Page.goto: net::ERR_CERT_COMMON_NAME_INVALID at https://x/", "ERR_CERT_COMMON_NAME_INVALID"),
        ("Page.goto: net::ERR_CERT_DATE_INVALID at https://x/", "ERR_CERT_DATE_INVALID"),
        ("net::ERR_CERTIFICATE_TRANSPARENCY_REQUIRED", "ERR_CERTIFICATE_TRANSPARENCY_REQUIRED"),
        ("net::ERR_SSL_PINNED_KEY_NOT_IN_CERT_CHAIN", "ERR_SSL_PINNED_KEY_NOT_IN_CERT_CHAIN"),
        ("Page.goto: net::ERR_NAME_NOT_RESOLVED at https://x/", None),
        ("Page.goto: net::ERR_SSL_PROTOCOL_ERROR at https://x/", None),
        ("", None),
        (None, None),
    ],
)
def test_cert_error_code(message, code):
    assert provider._cert_error_code(message) == code


class _FailedCR:
    def __init__(self, url: str, error_message: str):
        self.success = False
        self.url = url
        self.redirected_url = url
        self.error_message = error_message
        self.markdown = ""
        self.metadata = {}
        self.media = {}
        self.links = {}
        self.screenshot = None
        self.html = ""


class _OkCR(_FailedCR):
    def __init__(self, url: str):
        super().__init__(url, "")
        self.success = True
        self.markdown = f"browser text for {url}"
        self.metadata = {"title": "T"}
        self.html = "<html></html>"


class _FakeCrawler:
    def __init__(self, results: dict):
        self._results = results

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def arun(self, url, config):
        return self._results[url]

    async def arun_many(self, urls, config):
        # Completion order, like the real dispatcher: reversed here.
        return [self._results[u] for u in reversed(urls)]


def _bare_provider(monkeypatch, results: dict, settings: FetchSettings | None = None):
    inst = provider.Crawl4AIProvider.__new__(provider.Crawl4AIProvider)
    inst._settings = settings or FetchSettings()
    inst._gates = provider.JunkGates()
    inst._run_config = object()
    inst._headless = True
    inst._data_dir = None
    monkeypatch.setattr(inst, "_make_crawler", lambda: _FakeCrawler(results))
    return inst


def test_single_fetch_cert_failure_is_a_clear_refusal(monkeypatch):
    url = "https://self-signed.example/"
    inst = _bare_provider(monkeypatch, {url: _FailedCR(url, REAL_CERT_ERROR)})

    with pytest.raises(CertVerificationError) as info:
        _run(inst._fetch_async(url))

    msg = str(info.value)
    assert "certificate verification failed" in msg
    assert "ERR_CERT_AUTHORITY_INVALID" in msg
    assert "browser_verify_tls = false under [fetch]" in msg


def test_single_fetch_non_cert_failure_unchanged(monkeypatch):
    """Other navigation failures keep their old path (empty result -> junk gate)."""
    url = "https://gone.example/"
    inst = _bare_provider(
        monkeypatch, {url: _FailedCR(url, "Page.goto: net::ERR_NAME_NOT_RESOLVED")}
    )
    result = _run(inst._fetch_async(url))
    assert result.content == ""


def test_batch_cert_failure_is_a_loud_skip_naming_the_right_url(monkeypatch, caplog):
    # IP literals: the batch entry gate resolves hostnames.
    bad, good = "https://8.8.8.8/self-signed", "https://8.8.8.8/fine"
    inst = _bare_provider(
        monkeypatch, {bad: _FailedCR(bad, REAL_CERT_ERROR), good: _OkCR(good)}
    )
    with caplog.at_level(logging.WARNING, logger="hyperresearch.web"):
        results = _run(inst._fetch_many_async([bad, good]))

    assert [r.url for r in results] == [good]
    skips = [r.getMessage() for r in caplog.records if "SKIPPED" in r.getMessage()]
    assert len(skips) == 1
    assert bad in skips[0] and good not in skips[0]
    assert "browser_verify_tls = false" in skips[0]
