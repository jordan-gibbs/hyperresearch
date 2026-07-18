"""Tests for the crawl4ai provider's stealth (patchright) wiring.

Deterministic and offline: asserts the crawler is built with an explicit
UndetectedAdapter so patchright engages. crawl4ai's AsyncWebCrawler otherwise
defaults to PlaywrightAdapter (plain Playwright) and stealth never runs. No
browser is launched — only in-memory object construction is exercised.
"""

from __future__ import annotations

import pytest

# crawl4ai is a core dependency, but guard so the suite degrades gracefully if a
# minimal install lacks the browser_adapter API (introduced in crawl4ai 0.7.3).
pytest.importorskip("crawl4ai.browser_adapter")

from crawl4ai.async_crawler_strategy import AsyncPlaywrightCrawlerStrategy
from crawl4ai.browser_adapter import UndetectedAdapter

from hyperresearch.web.crawl4ai_provider import Crawl4AIProvider


def test_make_crawler_uses_undetected_adapter() -> None:
    """_make_crawler() must wire an UndetectedAdapter via AsyncPlaywrightCrawlerStrategy."""
    crawler = Crawl4AIProvider(headless=True)._make_crawler()
    strategy = crawler.crawler_strategy

    assert isinstance(strategy, AsyncPlaywrightCrawlerStrategy)
    assert isinstance(strategy.adapter, UndetectedAdapter)


def test_browser_manager_marked_undetected() -> None:
    """The adapter choice must propagate to BrowserManager.use_undetected.

    This is the flag crawl4ai checks to import patchright instead of plain
    playwright at launch — the actual engagement point.
    """
    crawler = Crawl4AIProvider(headless=True)._make_crawler()

    assert crawler.crawler_strategy.browser_manager.use_undetected is True


def test_undetected_wiring_survives_profile_path() -> None:
    """The stealth adapter must also be wired when an authenticated profile
    (user_data_dir / managed browser) is configured — the two are compatible."""
    crawler = Crawl4AIProvider(headless=True, user_data_dir="/tmp/does-not-matter")._make_crawler()

    assert isinstance(crawler.crawler_strategy.adapter, UndetectedAdapter)
    assert crawler.crawler_strategy.browser_manager.use_undetected is True
