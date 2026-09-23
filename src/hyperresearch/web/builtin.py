"""Builtin web provider — SSRF-gated fetching via safe_http, beautifulsoup4 extraction if available.

PDFs go through the shared lane in :mod:`hyperresearch.web.pdf`, the same one
the crawl4ai provider uses. Before that, a vault on this provider had no PDF
handling at all: the bytes were decoded as HTML and every PDF on every host
was rejected by the junk gate with the same generic message (#82).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from html.parser import HTMLParser

from hyperresearch.web.base import WebResult
from hyperresearch.web.pdf import (
    PDF_FAILURE_KEY,
    extract_pdf,
    failure_reason,
    fetch_pdf,
    is_pdf_url,
)

# Code in fetched pages must reach the vault as markdown code, not prose.
# Flattened <pre> content passes the extractor's code-strip untouched and
# hits WIKI_LINK_RE, where bash test syntax ([[ -n "$kernel" ]]) is lexically
# a wiki-link; repair/graph then materialise junk stub notes named after
# shell fragments (40 such notes in one real vault from one Arch wiki page).
# Both extraction branches below share these helpers.


def _longest_backtick_run(text: str) -> int:
    return max((len(m.group(0)) for m in re.finditer(r"`+", text)), default=0)


def _fence_for(code: str) -> str:
    """Return a backtick fence longer than any backtick run inside the code."""
    return "`" * max(3, _longest_backtick_run(code) + 1)


def _fenced(code: str) -> str:
    """Wrap a code block in a fence it cannot break out of."""
    fence = _fence_for(code)
    body = code.strip("\n")
    return f"\n{fence}\n{body}\n{fence}\n"


def _inline_code(text: str) -> str:
    """Wrap inline code in a backtick run no run inside the text can close.

    A span of N backticks closes at the next run of exactly N, so the
    delimiter must outrun every run inside; a fixed ```` `` ```` let text
    holding ```` `` ```` end the span early and leak what followed (#140).
    """
    if "`" in text:
        ticks = "`" * (_longest_backtick_run(text) + 1)
        return f"{ticks} {text} {ticks}"
    return f"`{text}`"


class _TextExtractor(HTMLParser):
    """Minimal HTML-to-text extractor (no external deps).

    Emits <pre> blocks as fenced code and inline <code> as backtick spans;
    see the module comment for why that is load-bearing, not cosmetic.
    """

    def __init__(self):
        super().__init__()
        # (kind, text) where kind is "text" or "code"; code segments skip the
        # per-line strip in get_text() so indentation survives.
        self._segments: list[tuple[str, str]] = []
        self._skip = False
        self._skip_tags = {"script", "style", "nav", "footer", "header"}
        self._title = ""
        self._in_title = False
        self._in_pre = False
        self._pre_buf: list[str] = []
        self._in_inline_code = False

    def handle_starttag(self, tag, attrs):
        if tag in self._skip_tags:
            self._skip = True
            return
        if self._in_pre:
            if tag == "br":
                self._pre_buf.append("\n")
            return
        if tag == "title":
            self._in_title = True
            return
        if tag == "pre":
            self._in_pre = True
            self._pre_buf = []
            return
        if tag == "code":
            self._in_inline_code = True
            return
        if tag in ("p", "br", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li"):
            self._segments.append(("text", "\n"))

    def handle_endtag(self, tag):
        if tag in self._skip_tags:
            self._skip = False
            return
        if tag == "pre" and self._in_pre:
            self._in_pre = False
            code = "".join(self._pre_buf)
            self._pre_buf = []
            if code.strip():
                self._segments.append(("code", code))
            return
        if tag == "title":
            self._in_title = False
            return
        if tag == "code":
            self._in_inline_code = False

    def handle_data(self, data):
        if self._in_title:
            self._title = data.strip()
        if self._skip:
            return
        if self._in_pre:
            self._pre_buf.append(data)
            return
        if self._in_inline_code:
            if data.strip():
                self._segments.append(("text", _inline_code(data)))
            return
        self._segments.append(("text", data))

    def get_text(self) -> str:
        out: list[str] = []
        buf: list[str] = []

        def flush() -> None:
            raw = "".join(buf)
            lines = [line.strip() for line in raw.splitlines()]
            cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
            if cleaned:
                out.append(cleaned)
            buf.clear()

        for kind, text in self._segments:
            if kind == "text":
                buf.append(text)
            else:
                flush()
                out.append(_fenced(text).strip("\n"))
        flush()
        return "\n\n".join(out)


class BuiltinProvider:
    """Minimal web fetcher using stdlib + optional httpx/bs4."""

    name = "builtin"

    def __init__(self, settings=None):
        from hyperresearch.core.config import FetchSettings

        self._settings = settings or FetchSettings()

    def fetch(self, url: str) -> WebResult:
        # PDF detection by URL shape: download directly, extract with pymupdf.
        # A miss falls through to the HTML lane (the URL may be a landing page)
        # and the reason travels with the result for the junk gate to report.
        pdf_failure: str | None = None
        if is_pdf_url(url):
            result = fetch_pdf(url, self._settings)
            if result is not None:
                return result
            pdf_failure = failure_reason(url)

        resp = self._get(url)
        # Post-download PDF detection: a PDF behind a URL that does not look
        # like one (download?id=…, a redirect) is decoded here as text and
        # would otherwise be reported as binary garbage.
        if resp.content.startswith(b"%PDF-") or "application/pdf" in resp.headers.get("content-type", "").lower():
            result, pdf_failure = extract_pdf(
                resp.url, resp.content, self._settings, resp.headers.get("content-type", "")
            )
            if result is not None:
                return result

        html = resp.text
        title, content = self._extract(html)
        result = WebResult(
            url=resp.url,
            title=title,
            content=content,
            raw_html=html,
            fetched_at=datetime.now(UTC),
        )
        if pdf_failure:
            result.metadata[PDF_FAILURE_KEY] = pdf_failure
        return result

    def search(self, query: str, max_results: int = 5) -> list[WebResult]:
        raise NotImplementedError(
            "Builtin provider does not support web search. "
            "Use your agent's built-in search, then pipe URLs into 'hyperresearch fetch'."
        )

    def _get(self, url: str):
        """Download URL through the SSRF gate in :mod:`hyperresearch.web.safe_http`."""
        from hyperresearch.web.pdf import _is_cert_error
        from hyperresearch.web.safe_http import CertVerificationError, safe_get

        try:
            resp = safe_get(
                url,
                max_bytes=self._settings.max_html_bytes,
                allow_private_hosts=self._settings.allow_private_hosts,
            )
        except Exception as exc:
            # Raise a certificate failure as its own type, the way the PDF lane
            # and the crawl4ai provider do, instead of letting the raw
            # httpx.ConnectError through looking like any other failed fetch.
            # This lane always verifies TLS; pdf_verify_tls covers PDFs only.
            if _is_cert_error(exc):
                raise CertVerificationError(
                    f"certificate verification failed for {url!r}: {exc}"
                ) from exc
            raise
        if resp.status_code >= 400:
            raise RuntimeError(f"HTTP {resp.status_code} fetching {url}")
        return resp

    def _download(self, url: str) -> tuple[str, str]:
        """Download URL, return (html, final_url)."""
        resp = self._get(url)
        return resp.text, resp.url

    def _extract(self, html: str) -> tuple[str, str]:
        """Extract title and clean text from HTML. Tries bs4 first, falls back to stdlib."""
        try:
            from bs4 import BeautifulSoup, NavigableString

            soup = BeautifulSoup(html, "html.parser")
            # Remove noise
            for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                tag.decompose()
            title = soup.title.string.strip() if soup.title and soup.title.string else ""
            # Preserve code as markdown BEFORE get_text() flattens the markup
            # (module comment has the why). <pre> first, so nested <code>
            # inside it is consumed with it; then the remaining inline <code>.
            # Rewrite each element's contents in place: replace_with() and
            # decompose() look the element up in its parent's child list, which
            # is quadratic on a page with thousands of sibling <code> tags.
            for pre in soup.find_all("pre"):
                code_text = pre.get_text()
                pre.clear()
                if code_text.strip():
                    pre.append(NavigableString(_fenced(code_text)))
            for code in soup.find_all("code"):
                code_text = code.get_text()
                code.clear()
                if code_text.strip():
                    code.append(NavigableString(_inline_code(code_text)))
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
