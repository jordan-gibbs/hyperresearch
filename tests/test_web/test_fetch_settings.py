"""Tests for FetchSettings threading into the crawl4ai provider internals."""

from __future__ import annotations

import pytest

from hyperresearch.core.config import FetchSettings, JunkGates

crawl4ai_provider = pytest.importorskip(
    "hyperresearch.web.crawl4ai_provider",
    reason="crawl4ai extra not installed",
)


class TestSmartWaitJs:
    def test_defaults_match_pre_20_literals(self):
        js = crawl4ai_provider._smart_wait_js(FetchSettings())
        assert "}, 2000);" in js  # initial delay
        assert "}, 500);" in js  # poll interval
        assert "stable >= 2" in js
        assert "checks > 16" in js

    def test_custom_settings_rendered(self):
        js = crawl4ai_provider._smart_wait_js(
            FetchSettings(wait_initial_ms=100, poll_interval_ms=50, stable_checks=5, max_checks=99)
        )
        assert "}, 100);" in js
        assert "}, 50);" in js
        assert "stable >= 5" in js
        assert "checks > 99" in js

    def test_js_is_well_formed(self):
        js = crawl4ai_provider._smart_wait_js(FetchSettings())
        assert js.startswith("() => new Promise")
        assert js.count("{") == js.count("}")
        assert js.count("(") == js.count(")")


class TestLooksLikeBinary:
    def test_pdf_markers_always_binary(self):
        assert crawl4ai_provider._looks_like_binary("endstream endobj blah") is True

    def test_ratio_uses_gates(self):
        text = ("real words all over the place here " * 20) + "\x01\x02" * 60
        assert crawl4ai_provider._looks_like_binary(text) is True
        assert crawl4ai_provider._looks_like_binary(text, JunkGates(binary_garbage_ratio=0.9)) is False

    def test_empty_is_not_binary(self):
        assert crawl4ai_provider._looks_like_binary("") is False


class TestProviderConstruction:
    def test_settings_reach_run_config(self):
        prov = crawl4ai_provider.Crawl4AIProvider(
            settings=FetchSettings(page_timeout_ms=77777, stable_checks=7)
        )
        assert prov._run_config.page_timeout == 77777
        assert "stable >= 7" in prov._wait_js
        assert prov._wait_js.startswith("js:")

    def test_default_construction_matches_pre_20(self):
        prov = crawl4ai_provider.Crawl4AIProvider()
        assert prov._run_config.page_timeout == 30000
        assert "stable >= 2" in prov._wait_js
        assert "checks > 16" in prov._wait_js


class TestGetProviderThreading:
    def test_get_provider_passes_settings(self):
        from hyperresearch.web.base import get_provider

        prov = get_provider(
            "crawl4ai",
            settings=FetchSettings(page_timeout_ms=12345),
            gates=JunkGates(binary_garbage_ratio=0.9),
        )
        assert prov._run_config.page_timeout == 12345
        assert prov._gates.binary_garbage_ratio == 0.9
