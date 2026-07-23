"""Builtin web provider — SSRF-gated fetching via safe_http, beautifulsoup4 extraction if available."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from html.parser import HTMLParser

from hyperresearch.web.base import WebResult


class _TextExtractor(HTMLParser):
    """Minimal HTML-to-text extractor (no external deps)."""

    def __init__(self):
        super().__init__()
        self._pieces: list[str] = []
        self._skip = False
        self._skip_tags = {"script", "style", "nav", "footer", "header"}
        self._title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self._skip_tags:
            self._skip = True
        if tag == "title":
            self._in_title = True
        if tag in ("p", "br", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li"):
            self._pieces.append("\n")

    def handle_endtag(self, tag):
        if tag in self._skip_tags:
            self._skip = False
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self._title = data.strip()
        if not self._skip:
            self._pieces.append(data)

    def get_text(self) -> str:
        raw = "".join(self._pieces)
        # Collapse whitespace
        lines = [line.strip() for line in raw.splitlines()]
        return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


class BuiltinProvider:
    """Minimal web fetcher using stdlib + optional httpx/bs4."""

    name = "builtin"

    def __init__(self, settings=None):
        from hyperresearch.core.config import FetchSettings

        self._settings = settings or FetchSettings()

    def fetch(self, url: str) -> WebResult:
        html, final_url = self._download(url)
        title, content = self._extract(html)
        return WebResult(
            url=final_url,
            title=title,
            content=content,
            raw_html=html,
            fetched_at=datetime.now(UTC),
        )

    def search(self, query: str, max_results: int = 5) -> list[WebResult]:
        raise NotImplementedError(
            "Builtin provider does not support web search. "
            "Use your agent's built-in search, then pipe URLs into 'hyperresearch fetch'."
        )

    def _download(self, url: str) -> tuple[str, str]:
        """Download URL, return (html, final_url). All requests go through the
        SSRF gate in :mod:`hyperresearch.web.safe_http`."""
        from hyperresearch.web.safe_http import safe_get

        resp = safe_get(url, max_bytes=self._settings.max_html_bytes)
        if resp.status_code >= 400:
            raise RuntimeError(f"HTTP {resp.status_code} fetching {url}")
        return resp.text, resp.url

    def _extract(self, html: str) -> tuple[str, str]:
        """Extract title and clean text from HTML. Tries bs4 first, falls back to stdlib."""
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html, "html.parser")
            # Remove noise
            for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                tag.decompose()
            title = soup.title.string.strip() if soup.title and soup.title.string else ""
            text = soup.get_text(separator="\n", strip=True)
            # Collapse blank lines
            text = re.sub(r"\n{3,}", "\n\n", text)
            return title, text
        except ImportError:
            pass

        # Fallback: stdlib HTML parser
        parser = _TextExtractor()
        parser.feed(html)
        return parser._title, parser.get_text()
