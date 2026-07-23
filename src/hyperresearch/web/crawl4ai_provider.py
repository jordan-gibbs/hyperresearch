"""Crawl4AI web provider — free, open-source, local headless browser, returns clean markdown.

Supports authenticated crawling via crawl4ai browser profiles:
  1. Run `crwl profiles` or `hyperresearch setup` to create a profile and log in
  2. Set `profile = "profile-name"` in .hyperresearch/config.toml
  3. All fetches now use your authenticated session (cookies, localStorage, etc.)
"""

from __future__ import annotations

import asyncio
import logging
import os
import pathlib
import sys
from datetime import UTC, datetime

from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, DefaultMarkdownGenerator
from crawl4ai.async_crawler_strategy import AsyncPlaywrightCrawlerStrategy
from crawl4ai.browser_adapter import UndetectedAdapter
from crawl4ai.content_filter_strategy import PruningContentFilter

from hyperresearch.core.config import FetchSettings, JunkGates
from hyperresearch.web.base import WebResult, is_binary_garbage

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


def _is_pdf_url(url: str) -> bool:
    """Check if URL likely points to a PDF."""
    from urllib.parse import urlparse

    parsed = urlparse(url.lower())
    path = parsed.path
    # Direct .pdf links
    if path.endswith(".pdf"):
        return True
    # Common academic PDF patterns
    if "/pdf/" in path or "/pdfs/" in path:
        return True
    # arXiv PDF links
    return "arxiv.org" in parsed.netloc and ("/pdf/" in path or "/abs/" in path)


def _looks_like_binary(text: str, gates: JunkGates | None = None) -> bool:
    """Check if extracted 'content' is actually binary garbage from a PDF."""
    if not text:
        return False
    gates = gates or JunkGates()
    sample = text[: gates.sample_window]
    # PDF internal structure markers — dead giveaway
    pdf_markers = ("endstream", "endobj", "/Filter", "/FlateDecode", "stream\nx", "%PDF-")
    if any(m in sample for m in pdf_markers):
        return True
    # Shared with WebResult.looks_like_junk() \u2014 keep one implementation, since these
    # two gates drifting apart is what let `ord(c) > 127` survive in base.py and
    # silently discard every non-English page.
    return is_binary_garbage(sample, gates)


def _smart_wait_js(settings: FetchSettings) -> str:
    """DOM-stability polling loop shared by the headless and visible paths.

    Waits `wait_initial_ms`, then polls every `poll_interval_ms` until body text
    length is unchanged for `stable_checks` consecutive polls, giving up after
    `max_checks` polls.
    """
    return (
        "() => new Promise(r => {"
        "  setTimeout(() => {"
        "    let last = document.body.innerText.length;"
        "    let stable = 0;"
        "    let checks = 0;"
        "    const interval = setInterval(() => {"
        "      const now = document.body.innerText.length;"
        "      if (now === last) { stable++; } else { stable = 0; }"
        f"      if (stable >= {settings.stable_checks} || checks > {settings.max_checks}) {{ clearInterval(interval); r(true); }}"
        "      last = now; checks++;"
        f"    }}, {settings.poll_interval_ms});"
        f"  }}, {settings.wait_initial_ms});"
        "})"
    )


_PYMUPDF_MISSING_LOGGED = False


def _pdf_log() -> logging.Logger:
    return logging.getLogger("hyperresearch.pdf")


def _import_pymupdf():
    """Import pymupdf, warning loudly (once) if it is unavailable.

    Without this warning a missing/broken pymupdf is invisible: every PDF falls
    through to the browser lane, arrives as binary, and is discarded as junk —
    across every domain at once, with nothing explaining why.
    """
    global _PYMUPDF_MISSING_LOGGED
    try:
        import pymupdf

        return pymupdf
    except ImportError as exc:
        if not _PYMUPDF_MISSING_LOGGED:
            _PYMUPDF_MISSING_LOGGED = True
            _pdf_log().error(
                "pymupdf could not be imported (%s) — PDF text extraction is disabled, "
                "so every PDF will be discarded as junk content. Reinstall it with "
                "`pip install --force-reinstall pymupdf`.",
                exc,
            )
        return None


_PDF_FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/pdf,application/octet-stream;q=0.9,*/*;q=0.8",
}


def _is_cert_error(exc: Exception) -> bool:
    import ssl

    # httpx nests the ssl error two causes deep (httpx.ConnectError ->
    # httpcore.ConnectError -> SSLCertVerificationError), so walk the chain
    # rather than checking only the direct cause. String match as fallback.
    cause: BaseException | None = exc
    for _ in range(5):
        if cause is None:
            break
        if isinstance(cause, ssl.SSLCertVerificationError):
            return True
        cause = cause.__cause__
    return "CERTIFICATE_VERIFY_FAILED" in str(exc)


def _safe_get_pdf(url: str, settings: FetchSettings):
    """SSRF-gated, size-capped PDF download.

    TLS verification follows ``pdf_verify_tls`` (default on) with NO
    automatic unverified retry: a MITM can serve a bad certificate
    precisely to force such a retry, which would turn verify-by-default
    into something the attacker controls. Mirrors with known-broken
    certificates are handled by the explicit, user-declared
    ``pdf_verify_tls = false`` opt-out.
    """
    from hyperresearch.web.safe_http import SafeHTTPError, safe_get

    try:
        return safe_get(url, max_bytes=settings.max_pdf_bytes,
                        timeout=settings.pdf_timeout_s,
                        headers=_PDF_FETCH_HEADERS,
                        verify=settings.pdf_verify_tls)
    except Exception as exc:
        if settings.pdf_verify_tls and _is_cert_error(exc):
            # Refuse, but say how to opt out for a trusted cert-broken mirror.
            raise SafeHTTPError(
                f"certificate verification failed for {url!r}: {exc}. "
                "If this host is a known cert-broken mirror you trust, set "
                "pdf_verify_tls = false under [fetch] in config.toml."
            ) from exc
        raise


def _fetch_pdf(url: str, settings: FetchSettings | None = None) -> WebResult | None:
    """Download a PDF and extract text using pymupdf. Returns None if extraction fails.

    Every failure path logs its reason. A silent None here is indistinguishable
    from "this URL is not a PDF", which is what made missing-PDF failures so hard
    to diagnose.
    """
    pymupdf = _import_pymupdf()
    if pymupdf is None:
        return None

    settings = settings or FetchSettings()

    from hyperresearch.web.safe_http import SafeHTTPError

    try:
        # Convert arXiv abs links to PDF links
        if "arxiv.org/abs/" in url:
            url = url.replace("/abs/", "/pdf/")
            if not url.endswith(".pdf"):
                url += ".pdf"

        try:
            resp = _safe_get_pdf(url, settings)
        except SafeHTTPError as exc:
            _pdf_log().warning("refused PDF fetch for %s: %s", url, exc)
            return None

        if resp.status_code != 200:
            _pdf_log().warning("PDF fetch for %s returned HTTP %s", url, resp.status_code)
            return None

        pdf_bytes = resp.content
        content_type = resp.headers.get("content-type", "")

        # Magic bytes are authoritative. Servers mislabel PDFs as octet-stream,
        # and plenty of PDF URLs carry no .pdf suffix, so trusting the header or
        # the URL shape alone silently drops real PDFs.
        if not pdf_bytes.startswith(b"%PDF-"):
            _pdf_log().warning(
                "PDF fetch for %s did not return PDF data (content-type=%r, first bytes=%r)",
                url, content_type, pdf_bytes[:8],
            )
            return None

        if len(pdf_bytes) < settings.min_pdf_bytes:
            _pdf_log().warning("PDF fetch for %s returned only %d bytes", url, len(pdf_bytes))
            return None

        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")

        # Extract text from all pages
        pages = []
        for page in doc:
            text = page.get_text("text")
            if text.strip():
                pages.append(text)

        page_count = doc.page_count
        doc.close()

        if not pages:
            _pdf_log().warning(
                "PDF at %s has %d page(s) but no extractable text layer — "
                "likely a scanned document requiring OCR.", url, page_count,
            )
            return None

        # Build markdown from extracted text
        full_text = "\n\n---\n\n".join(pages)
        title = ""
        # Try to get title from first page (first non-empty line)
        for line in pages[0].split("\n"):
            line = line.strip()
            if len(line) > 10:
                title = line
                break

        return WebResult(
            url=url,
            title=title or f"PDF: {url.split('/')[-1]}",
            content=full_text,
            fetched_at=datetime.now(UTC),
            metadata={"content_type": "application/pdf", "pages": len(pages)},
            raw_bytes=pdf_bytes,
            raw_content_type="application/pdf",
        )

    except Exception as e:
        _pdf_log().warning("PDF extraction failed for %s: %s", url, e)
        return None


class Crawl4AIProvider:
    name = "crawl4ai"

    def __init__(
        self,
        headless: bool = True,
        user_data_dir: str | None = None,
        profile: str | None = None,
        cookies: list[dict] | None = None,
        magic: bool = False,
        settings: FetchSettings | None = None,
        gates: JunkGates | None = None,
    ):
        # Resolve profile name to path (crawl4ai stores profiles in ~/.crawl4ai/profiles/)
        data_dir = user_data_dir
        if profile and not data_dir:
            data_dir = str(pathlib.Path.home() / ".crawl4ai" / "profiles" / profile)

        self._data_dir = data_dir
        self._headless = headless
        self._cookies = cookies
        self._settings = settings or FetchSettings()
        self._gates = gates or JunkGates()

        browser_kwargs: dict = {"headless": headless}
        if data_dir:
            browser_kwargs["use_managed_browser"] = True
            browser_kwargs["user_data_dir"] = data_dir
        if cookies:
            browser_kwargs["cookies"] = cookies

        self._browser_config = BrowserConfig(**browser_kwargs)

        # Smart wait: initial delay + poll until content stabilizes
        self._wait_js = "js:" + _smart_wait_js(self._settings)
        # Use PruningContentFilter to populate fit_markdown (strips nav/footer chrome)
        self._md_generator = DefaultMarkdownGenerator(
            content_filter=PruningContentFilter(),
        )
        self._run_config = CrawlerRunConfig(
            magic=magic,
            simulate_user=True,
            screenshot=True,
            page_timeout=self._settings.page_timeout_ms,
            wait_for=self._wait_js,
            markdown_generator=self._md_generator,
        )

    def _make_crawler(self) -> AsyncWebCrawler:
        """Build an AsyncWebCrawler wired with the stealth (patchright) adapter.

        crawl4ai's AsyncWebCrawler defaults to PlaywrightAdapter (plain
        playwright); patchright/stealth only engages when an UndetectedAdapter is
        passed via an explicit AsyncPlaywrightCrawlerStrategy. Without this the
        provider's anti-bot behavior is only simulate_user + smart-wait. The
        adapter's use_undetected flag is threaded through every BrowserManager
        launch branch (default, persistent-context, and managed-browser/CDP), so
        this is compatible with the authenticated-profile (user_data_dir) path.
        """
        strategy = AsyncPlaywrightCrawlerStrategy(
            browser_config=self._browser_config,
            browser_adapter=UndetectedAdapter(),
        )
        return AsyncWebCrawler(crawler_strategy=strategy, config=self._browser_config)

    def fetch(self, url: str) -> WebResult:
        # SSRF gate: reject private/loopback/etc. before any browser or http
        # call. Re-checked on PDF redirects via safe_get; browser hops are
        # not re-checked (Playwright drives navigation internally), so this
        # entry-point check is the primary protection for the browser path.
        from hyperresearch.web.safe_http import check_url

        check_url(url)

        # PDF detection: fetch directly with httpx, extract text with pymupdf
        if _is_pdf_url(url):
            result = _fetch_pdf(url, self._settings)
            if result is not None:
                return result
            # Fallback to browser if PDF fetch failed (might be a landing page, not actual PDF)

        # When visible + profile: use Playwright directly (crawl4ai managed browser ignores headless=False)
        if not self._headless and self._data_dir:
            return asyncio.run(self._fetch_visible(url))

        result = asyncio.run(self._fetch_async(url))

        # Post-fetch PDF detection: if the browser got binary garbage (PDF served
        # inline without proper content-type handling), re-fetch as a direct PDF download.
        if result.content and _looks_like_binary(result.content, self._gates):
            pdf_result = _fetch_pdf(url, self._settings)
            if pdf_result is not None:
                return pdf_result

        return result

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
            await page.goto(url, wait_until="domcontentloaded", timeout=self._settings.page_timeout_ms)

            # Smart wait — same logic (and same builder) as the headless config
            await page.evaluate(_smart_wait_js(self._settings))

            html = await page.content()
            title = await page.title()
            screenshot_bytes = await page.screenshot(type="png")
            final_url = page.url

            await context.close()

        # Convert HTML to markdown using crawl4ai's markdown generator
        # Prefer fit_markdown (main content, no nav/footer chrome) over raw_markdown.
        md_result = self._md_generator.generate_markdown(html, base_url=final_url)
        content = ""
        if md_result and hasattr(md_result, "fit_markdown"):
            content = md_result.fit_markdown or md_result.raw_markdown or ""
        elif md_result and hasattr(md_result, "raw_markdown"):
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
        async with self._make_crawler() as crawler:
            result = await crawler.arun(url=url, config=self._run_config)
            metadata = result.metadata or {}

            # result.markdown is a MarkdownGenerationResult with .raw_markdown,
            # .fit_markdown, .markdown_with_citations, etc.
            # Prefer fit_markdown (main content, no nav/footer chrome) over raw_markdown.
            md = result.markdown
            if md and hasattr(md, "fit_markdown"):
                content = md.fit_markdown or md.raw_markdown or ""
            elif md and hasattr(md, "raw_markdown"):
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
        # SSRF gate: same entry-point check as fetch(). Refused URLs are
        # skipped (logged), not fatal — one hostile URL must not kill the
        # whole batch.
        from hyperresearch.web.safe_http import SafeHTTPError, check_url

        allowed_urls = []
        for url in urls:
            try:
                check_url(url)
                allowed_urls.append(url)
            except SafeHTTPError as exc:
                logging.getLogger("hyperresearch.web").warning(
                    "refused batch fetch for %s: %s", url, exc
                )

        # Split: PDFs go direct, rest go through browser
        pdf_urls = [u for u in allowed_urls if _is_pdf_url(u)]
        html_urls = [u for u in allowed_urls if not _is_pdf_url(u)]

        web_results = []

        # Fetch PDFs directly (no browser needed)
        for url in pdf_urls:
            pdf_result = _fetch_pdf(url, self._settings)
            if pdf_result is not None:
                web_results.append(pdf_result)

        # Fetch HTML pages with browser
        if html_urls:
            async with self._make_crawler() as crawler:
                results = await crawler.arun_many(urls=html_urls, config=self._run_config)
                for cr, url in zip(results, html_urls, strict=False):
                    if not cr.success:
                        continue
                    metadata = cr.metadata or {}
                    md = cr.markdown
                    if md and hasattr(md, "fit_markdown"):
                        content = md.fit_markdown or md.raw_markdown or ""
                    elif md and hasattr(md, "raw_markdown"):
                        content = md.raw_markdown or ""
                    elif isinstance(md, str):
                        content = md
                    else:
                        content = ""

                    # Post-fetch binary check — browser may have fetched a PDF inline
                    if content and _looks_like_binary(content, self._gates):
                        pdf_result = _fetch_pdf(url, self._settings)
                        if pdf_result is not None:
                            web_results.append(pdf_result)
                            continue

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


