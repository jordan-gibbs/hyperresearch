"""Crawl4AI web provider — free, open-source, local headless browser, returns clean markdown.

Supports authenticated crawling via crawl4ai browser profiles:
  1. Run `crwl profiles` or `hyperresearch setup` to create a profile and log in
  2. Set `profile = "profile-name"` in .hyperresearch/config.toml
  3. All fetches now use your authenticated session (cookies, localStorage, etc.)
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import sys
from datetime import UTC, datetime

from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig

from hyperresearch.web.base import WebResult

# Fix Windows encoding before crawl4ai's managed browser tries to log Unicode
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    os.environ.setdefault("PYTHONUTF8", "1")
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            try:
                _stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


class Crawl4AIProvider:
    name = "crawl4ai"

    def __init__(
        self,
        headless: bool = True,
        user_data_dir: str | None = None,
        profile: str | None = None,
        cookies: list[dict] | None = None,
        magic: bool = False,
    ):
        # Resolve profile name to path (crawl4ai stores profiles in ~/.crawl4ai/profiles/)
        data_dir = user_data_dir
        if profile and not data_dir:
            data_dir = str(pathlib.Path.home() / ".crawl4ai" / "profiles" / profile)

        self._data_dir = data_dir
        self._headless = headless
        self._cookies = cookies

        browser_kwargs: dict = {"headless": headless}
        if data_dir:
            browser_kwargs["use_managed_browser"] = True
            browser_kwargs["user_data_dir"] = data_dir
        if cookies:
            browser_kwargs["cookies"] = cookies

        self._browser_config = BrowserConfig(**browser_kwargs)

        # Smart wait: 2s initial + poll until content stabilizes (10s ceiling)
        self._wait_js = (
            "js:() => new Promise(r => {"
            "  setTimeout(() => {"
            "    let last = document.body.innerText.length;"
            "    let stable = 0;"
            "    let checks = 0;"
            "    const interval = setInterval(() => {"
            "      const now = document.body.innerText.length;"
            "      if (now === last) { stable++; } else { stable = 0; }"
            "      if (stable >= 2 || checks > 16) { clearInterval(interval); r(true); }"
            "      last = now; checks++;"
            "    }, 500);"
            "  }, 2000);"
            "})"
        )
        self._run_config = CrawlerRunConfig(
            magic=magic,
            simulate_user=True,
            screenshot=True,
            page_timeout=30000,
            wait_for=self._wait_js,
        )

    def fetch(self, url: str) -> WebResult:
        # When visible + profile: use Playwright directly (crawl4ai managed browser ignores headless=False)
        if not self._headless and self._data_dir:
            return asyncio.run(self._fetch_visible(url))
        return asyncio.run(self._fetch_async(url))

    async def _fetch_visible(self, url: str) -> WebResult:
        """Fetch using Playwright directly with a visible browser window.

        crawl4ai's managed browser always forces headless. For sites like LinkedIn
        that detect headless mode and kill sessions, we need a truly visible browser.
        """
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            context = await pw.chromium.launch_persistent_context(
                user_data_dir=self._data_dir,
                headless=False,
                viewport={"width": 1280, "height": 900},
                ignore_https_errors=True,
            )
            page = context.pages[0] if context.pages else await context.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)

            # Smart wait — same logic as crawl4ai config
            await page.evaluate("""() => new Promise(r => {
                setTimeout(() => {
                    let last = document.body.innerText.length;
                    let stable = 0;
                    let checks = 0;
                    const interval = setInterval(() => {
                        const now = document.body.innerText.length;
                        if (now === last) { stable++; } else { stable = 0; }
                        if (stable >= 2 || checks > 16) { clearInterval(interval); r(true); }
                        last = now; checks++;
                    }, 500);
                }, 2000);
            })""")

            html = await page.content()
            title = await page.title()
            screenshot_bytes = await page.screenshot(type="png")
            final_url = page.url

            await context.close()

        # Convert HTML to markdown using crawl4ai's markdown generator
        from crawl4ai import DefaultMarkdownGenerator

        md_gen = DefaultMarkdownGenerator()
        md_result = md_gen.generate_markdown(html, base_url=final_url)
        content = ""
        if md_result and hasattr(md_result, "raw_markdown"):
            content = md_result.raw_markdown or ""
        elif isinstance(md_result, str):
            content = md_result

        return WebResult(
            url=final_url,
            title=title,
            content=content,
            raw_html=html,
            fetched_at=datetime.now(UTC),
            metadata={"title": title},
            screenshot=screenshot_bytes,
        )

    async def _fetch_async(self, url: str) -> WebResult:
        async with AsyncWebCrawler(config=self._browser_config) as crawler:
            result = await crawler.arun(url=url, config=self._run_config)
            metadata = result.metadata or {}

            # result.markdown is a MarkdownGenerationResult with .raw_markdown,
            # .fit_markdown, .markdown_with_citations, etc.
            md = result.markdown
            if md and hasattr(md, "raw_markdown"):
                content = md.raw_markdown or ""
            elif isinstance(md, str):
                content = md
            else:
                content = ""

            # Extract media (images) — crawl4ai returns dict with 'images' key
            media_raw = result.media or {}
            media = media_raw.get("images", []) if isinstance(media_raw, dict) else []

            # Extract links — crawl4ai returns dict with 'internal'/'external' keys
            links_raw = result.links or {}
            links = []
            if isinstance(links_raw, dict):
                for link in links_raw.get("internal", []):
                    links.append({**link, "type": "internal"})
                for link in links_raw.get("external", []):
                    links.append({**link, "type": "external"})

            # Decode screenshot from base64 if present
            screenshot_bytes = None
            if result.screenshot:
                import base64

                try:
                    screenshot_bytes = base64.b64decode(result.screenshot)
                except Exception:
                    pass

            return WebResult(
                url=result.url or url,
                title=metadata.get("title", ""),
                content=content,
                raw_html=result.html,
                fetched_at=datetime.now(UTC),
                metadata=metadata,
                media=media,
                links=links,
                screenshot=screenshot_bytes,
            )

    def fetch_many(self, urls: list[str]) -> list[WebResult]:
        """Fetch multiple URLs concurrently using crawl4ai's arun_many."""
        return asyncio.run(self._fetch_many_async(urls))

    async def _fetch_many_async(self, urls: list[str]) -> list[WebResult]:
        async with AsyncWebCrawler(config=self._browser_config) as crawler:
            results = await crawler.arun_many(urls=urls, config=self._run_config)
            web_results = []
            for cr, url in zip(results, urls, strict=False):
                if not cr.success:
                    continue
                metadata = cr.metadata or {}
                md = cr.markdown
                if md and hasattr(md, "raw_markdown"):
                    content = md.raw_markdown or ""
                elif isinstance(md, str):
                    content = md
                else:
                    content = ""

                media_raw = cr.media or {}
                media = media_raw.get("images", []) if isinstance(media_raw, dict) else []

                screenshot_bytes = None
                if cr.screenshot:
                    import base64

                    try:
                        screenshot_bytes = base64.b64decode(cr.screenshot)
                    except Exception:
                        pass

                web_results.append(WebResult(
                    url=cr.url or url,
                    title=metadata.get("title", ""),
                    content=content,
                    raw_html=cr.html,
                    fetched_at=datetime.now(UTC),
                    metadata=metadata,
                    media=media,
                    screenshot=screenshot_bytes,
                ))
            return web_results

    def search(self, query: str, max_results: int = 5) -> list[WebResult]:
        raise NotImplementedError(
            "crawl4ai does not support web search. "
            "Use your agent's built-in search, then pipe URLs into 'hyperresearch fetch'."
        )


