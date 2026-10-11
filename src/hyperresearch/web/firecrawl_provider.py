"""Firecrawl web provider: hosted scraping and search, with crawl4ai as the fallback.

Firecrawl (https://firecrawl.dev) renders pages in its own browsers and returns
Markdown. It cannot use a local login profile, so some fetches are handed to the
crawl4ai provider, built with the same profile, stealth and TLS settings it would
get as the configured provider:

- the visible-browser lane (`--visible`, and `visible_browser_domains` when a
  profile is set),
- hosts reachable only through `[fetch] allow_private_hosts` (Firecrawl's cloud
  cannot reach them, and the URL should not leave the machine),
- a Firecrawl API error, including an exhausted credit or rate limit,
- a page Firecrawl got blocked on: an HTTP 401/403/407/429/5xx status, a login
  wall, or a bot-detection page.

PDF URLs go through the shared PDF lane first, as on the other providers, so the
raw file is kept; Firecrawl parses a PDF only when that lane declines it.

Configuration:
    export FIRECRAWL_API_KEY="fc-..."   # https://firecrawl.dev

    # in .hyperresearch/config.toml
    [web]
    provider = "firecrawl"

Without a key, single fetches and search use Firecrawl's keyless tier (capped
per IP address per day) and batch fetches go one URL at a time. No extra
install: uses the httpx dependency the core already carries.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx

from hyperresearch.core.config import FetchSettings, JunkGates
from hyperresearch.web.base import SERVED_BY_KEY, WebProvider, WebResult
from hyperresearch.web.pdf import PDF_FAILURE_KEY, failure_reason, fetch_pdf, is_pdf_url

_API_URL = "https://api.firecrawl.dev/v2"
_FORMATS = ["markdown", "rawHtml", "images", "screenshot"]
# Firecrawl's own per-page timeout bounds, in ms.
_MIN_PAGE_TIMEOUT_MS = 1000
_MAX_PAGE_TIMEOUT_MS = 300_000
# Seconds added to the page timeout for the HTTP round trip to the API.
_HTTP_SLACK_S = 30.0
_BATCH_POLL_INTERVAL_S = 2.0
_BATCH_DEADLINE_S = 600.0
# Target statuses that mean "blocked here", worth one try from the local browser.
# A 404 or 410 is the page's real answer and is raised as such.
_BLOCKED_STATUSES = frozenset({401, 403, 407, 429})

log = logging.getLogger("hyperresearch.web")


class FirecrawlError(RuntimeError):
    """The Firecrawl API refused or failed a request."""


class FirecrawlProvider:
    """Web provider backed by the Firecrawl v2 API (https://docs.firecrawl.dev)."""

    name = "firecrawl"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        profile: str | None = None,
        magic: bool = False,
        headless: bool = True,
        settings: FetchSettings | None = None,
        gates: JunkGates | None = None,
        fallback: Callable[[], WebProvider] | None = None,
        transport: httpx.BaseTransport | None = None,
        poll_interval_s: float = _BATCH_POLL_INTERVAL_S,
    ):
        """``fallback`` builds the provider used when Firecrawl cannot serve a
        URL; the default is crawl4ai with this provider's profile and settings.
        ``transport`` is a test seam; production callers leave it None."""
        self._settings = settings or FetchSettings()
        self._gates = gates or JunkGates()
        self._headless = headless
        self._key = (api_key or os.environ.get("FIRECRAWL_API_KEY", "")).strip()
        self._poll_interval_s = poll_interval_s
        self._page_timeout_ms = min(
            max(self._settings.page_timeout_ms, _MIN_PAGE_TIMEOUT_MS), _MAX_PAGE_TIMEOUT_MS
        )

        headers = {"Content-Type": "application/json"}
        if self._key:
            headers["Authorization"] = f"Bearer {self._key}"
        self._client = httpx.Client(
            base_url=_API_URL,
            headers=headers,
            timeout=self._page_timeout_ms / 1000 + _HTTP_SLACK_S,
            transport=transport,
        )

        if fallback is None:
            def fallback() -> WebProvider:
                from hyperresearch.web.crawl4ai_provider import Crawl4AIProvider

                return Crawl4AIProvider(
                    profile=profile or None,
                    magic=magic,
                    headless=headless,
                    settings=self._settings,
                    gates=self._gates,
                )

        self._make_fallback = fallback
        self._fallback: WebProvider | None = None

    # ── fetch ────────────────────────────────────────────────────────────

    def fetch(self, url: str) -> WebResult:
        """Fetch one URL through Firecrawl, falling back to crawl4ai when it can't."""
        local_reason = self._local_only_reason(url)
        if local_reason:
            return self._fallback_fetch(url, local_reason)

        pdf_failure: str | None = None
        if is_pdf_url(url):
            pdf = fetch_pdf(url, self._settings)
            if pdf is not None:
                return pdf
            pdf_failure = failure_reason(url)

        try:
            data = self._post("/scrape", {"url": url, **self._scrape_options()})["data"]
        except FirecrawlError as exc:
            return self._fallback_fetch(url, str(exc))

        result = self._to_web_result(url, data)
        if pdf_failure:
            result.metadata[PDF_FAILURE_KEY] = pdf_failure
        blocked = self._blocked_reason(url, result)
        if blocked:
            return self._fallback_fetch(url, blocked, firecrawl_result=result)
        return result

    def fetch_many(self, urls: list[str]) -> list[WebResult]:
        """Fetch URLs through one Firecrawl batch job; crawl4ai takes the rest.

        Refused URLs (SSRF gate, bad PDF certificate) are logged and skipped,
        as on crawl4ai's ``fetch_many``: one bad URL must not sink the batch.
        """
        from hyperresearch.web.safe_http import CertVerificationError, SafeHTTPError

        results: list[WebResult] = []
        local: list[str] = []
        remote: list[str] = []
        for url in urls:
            try:
                reason = self._local_only_reason(url)
            except SafeHTTPError as exc:
                log.warning("refused batch fetch for %s: %s", url, exc)
                continue
            (local if reason else remote).append(url)

        to_scrape: list[str] = []
        for url in remote:
            if not is_pdf_url(url):
                to_scrape.append(url)
                continue
            try:
                pdf = fetch_pdf(url, self._settings)
            except CertVerificationError as exc:
                log.warning(
                    "SKIPPED (TLS certificate invalid): %s -- a potentially "
                    "valuable source was not fetched. To include it, set "
                    "pdf_verify_tls = false under [fetch] in config.toml. (%s)",
                    url, exc,
                )
                continue
            if pdf is not None:
                results.append(pdf)
            else:
                to_scrape.append(url)

        scraped: dict[str, dict[str, Any]] = {}
        if to_scrape and not self._key:
            # Batch scrape has no keyless tier; go one URL at a time.
            for url in to_scrape:
                try:
                    scraped[url] = self._post("/scrape", {"url": url, **self._scrape_options()})["data"]
                except FirecrawlError as exc:
                    log.warning("Firecrawl failed for %s, using crawl4ai: %s", url, exc)
        elif to_scrape:
            try:
                pages = self._batch_scrape(to_scrape)
            except FirecrawlError as exc:
                log.warning("Firecrawl batch failed, using crawl4ai for %d URLs: %s",
                            len(to_scrape), exc)
                pages = []
            for page in pages:
                source = (page.get("metadata") or {}).get("sourceURL")
                if source:
                    scraped[source] = page

        # Anything Firecrawl did not return, or returned blocked, goes to
        # crawl4ai's own batch, which drops the URLs it cannot fetch either.
        for url in to_scrape:
            data = scraped.get(url)
            if data is None:
                local.append(url)
                continue
            result = self._to_web_result(url, data)
            try:
                blocked = self._blocked_reason(url, result)
            except RuntimeError as exc:
                log.warning("batch fetch failed for %s: %s", url, exc)
                continue
            if blocked:
                local.append(url)
            else:
                results.append(result)

        if local:
            results.extend(self._fallback_many(local))
        return results

    # ── search ───────────────────────────────────────────────────────────

    def search(self, query: str, max_results: int = 5) -> list[WebResult]:
        """Search the web via Firecrawl and return results with page Markdown."""
        options = self._scrape_options()
        options["formats"] = ["markdown"]
        payload = self._post("/search", {
            "query": query,
            "limit": max_results,
            "scrapeOptions": options,
        })
        items = (payload.get("data") or {}).get("web") or []
        results = []
        for item in items:
            url = item.get("url") or ""
            metadata = dict(item.get("metadata") or {})
            if item.get("description"):
                metadata["snippet"] = item["description"]
            results.append(WebResult(
                url=url,
                title=_first(item.get("title")) or _first(metadata.get("title")),
                content=item.get("markdown") or item.get("description") or "",
                fetched_at=datetime.now(UTC),
                metadata=metadata,
            ))
        return results

    # ── internals ────────────────────────────────────────────────────────

    def _scrape_options(self) -> dict[str, Any]:
        return {
            "formats": list(_FORMATS),
            "onlyMainContent": True,
            "timeout": self._page_timeout_ms,
            # Firecrawl skips TLS verification unless told not to; match the
            # browser lane's setting (#137).
            "skipTlsVerification": not self._settings.browser_verify_tls,
        }

    def _local_only_reason(self, url: str) -> str | None:
        """Why ``url`` must be fetched locally, or None. Raises if the SSRF gate refuses it."""
        from hyperresearch.web.safe_http import SafeHTTPError, check_url

        allowed = self._settings.allow_private_hosts
        check_url(url, allowed)
        if not self._headless:
            return "visible browser requested"
        if allowed:
            try:
                check_url(url)
            except SafeHTTPError:
                return "private host from allow_private_hosts"
        return None

    def _blocked_reason(self, url: str, result: WebResult) -> str | None:
        status = result.metadata.get("statusCode")
        if isinstance(status, int):
            if status in _BLOCKED_STATUSES or status >= 500:
                return f"target returned HTTP {status}"
            if status >= 400:
                raise RuntimeError(f"HTTP {status} fetching {url}")
        if result.looks_like_login_wall(url, self._gates):
            return f"login wall: {result.title}"
        junk = result.looks_like_junk(self._gates)
        if junk and junk.startswith("Bot detection"):
            return junk
        return None

    def _fallback_provider(self) -> WebProvider:
        if self._fallback is None:
            self._fallback = self._make_fallback()
        return self._fallback

    def _fallback_fetch(
        self, url: str, reason: str, firecrawl_result: WebResult | None = None,
    ) -> WebResult:
        log.info("firecrawl: using crawl4ai for %s (%s)", url, reason)
        try:
            result = self._fallback_provider().fetch(url)
        except Exception as exc:
            if firecrawl_result is not None:
                # The caller's login-wall / junk gates and escalation queue
                # take it from here.
                log.warning("crawl4ai fallback failed for %s: %s", url, exc)
                return firecrawl_result
            raise RuntimeError(
                f"Firecrawl could not fetch {url} ({reason}); crawl4ai fallback failed: {exc}"
            ) from exc
        result.metadata[SERVED_BY_KEY] = self._fallback_provider().name
        result.metadata["fallback_reason"] = reason
        return result

    def _fallback_many(self, urls: list[str]) -> list[WebResult]:
        provider = self._fallback_provider()
        fetch_many = getattr(provider, "fetch_many", None)
        if fetch_many is not None:
            results = list(fetch_many(urls))
        else:
            results = []
            for url in urls:
                try:
                    results.append(provider.fetch(url))
                except Exception as exc:
                    log.warning("crawl4ai fallback failed for %s: %s", url, exc)
        for result in results:
            result.metadata[SERVED_BY_KEY] = provider.name
        return results

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            resp = self._client.post(path, json=body)
        except httpx.HTTPError as exc:
            raise FirecrawlError(f"Firecrawl request failed: {exc}") from exc
        return _payload(resp)

    def _get(self, url: str) -> dict[str, Any]:
        try:
            resp = self._client.get(url)
        except httpx.HTTPError as exc:
            raise FirecrawlError(f"Firecrawl request failed: {exc}") from exc
        return _payload(resp)

    def _batch_scrape(self, urls: list[str]) -> list[dict[str, Any]]:
        job = self._post("/batch/scrape", {
            "urls": urls,
            "ignoreInvalidURLs": True,
            **self._scrape_options(),
        })
        job_id = job.get("id")
        if not job_id:
            raise FirecrawlError("Firecrawl batch scrape returned no job id")

        deadline = time.monotonic() + _BATCH_DEADLINE_S
        status = self._get(f"/batch/scrape/{job_id}")
        while status.get("status") == "scraping":
            if time.monotonic() > deadline:
                raise FirecrawlError(f"Firecrawl batch {job_id} still running after "
                                     f"{_BATCH_DEADLINE_S:.0f}s")
            time.sleep(self._poll_interval_s)
            status = self._get(f"/batch/scrape/{job_id}")
        if status.get("status") != "completed":
            raise FirecrawlError(f"Firecrawl batch {job_id} ended as {status.get('status')!r}")

        pages = list(status.get("data") or [])
        next_url = status.get("next")
        while next_url:
            more = self._get(next_url)
            pages.extend(more.get("data") or [])
            next_url = more.get("next")
        return pages

    def _to_web_result(self, url: str, data: dict[str, Any]) -> WebResult:
        metadata = dict(data.get("metadata") or {})
        title = _first(metadata.get("title")) or _first(metadata.get("ogTitle"))
        if "author" in metadata:
            metadata["author"] = _first(metadata["author"])
        final_url = metadata.get("url") or metadata.get("sourceURL") or url
        media = [{"src": src} for src in data.get("images") or [] if isinstance(src, str)]
        return WebResult(
            url=final_url,
            title=title,
            content=data.get("markdown") or "",
            fetched_at=datetime.now(UTC),
            raw_html=data.get("rawHtml") or data.get("html"),
            metadata=metadata,
            media=media,
            screenshot=self._download_screenshot(data.get("screenshot")),
        )

    def _download_screenshot(self, screenshot_url: str | None) -> bytes | None:
        """Firecrawl returns the screenshot as a URL that expires in 24 hours."""
        if not screenshot_url or not screenshot_url.startswith("https://"):
            return None
        from hyperresearch.web.safe_http import safe_get

        try:
            resp = safe_get(
                screenshot_url,
                max_bytes=self._settings.max_image_bytes,
                timeout=float(self._settings.image_timeout_s),
            )
        except Exception as exc:
            log.info("firecrawl screenshot not saved (%s): %s", screenshot_url, exc)
            return None
        return resp.content if resp.status_code == 200 else None


def _payload(resp: httpx.Response) -> dict[str, Any]:
    try:
        payload = resp.json()
    except ValueError:
        payload = None
    if not isinstance(payload, dict):
        payload = {}
    if resp.status_code >= 400 or payload.get("success") is False:
        detail = payload.get("error") or resp.text[:200]
        raise FirecrawlError(f"Firecrawl API HTTP {resp.status_code}: {detail}")
    return payload


def _first(value: Any) -> str:
    """Firecrawl metadata fields may be a string or a list of strings."""
    if isinstance(value, list):
        value = next((v for v in value if isinstance(v, str) and v), "")
    return value if isinstance(value, str) else ""
