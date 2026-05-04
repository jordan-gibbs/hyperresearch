"""Base protocol and data types for web providers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable


@dataclass
class WebResult:
    """A single web fetch or search result."""

    url: str
    title: str
    content: str  # clean markdown or plain text
    fetched_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    raw_html: str | None = None
    metadata: dict = field(default_factory=dict)  # author, date, domain, etc.
    media: list[dict] = field(default_factory=list)  # images: {src, alt, score, ...}
    links: list[dict] = field(default_factory=list)  # {href, text, type}
    screenshot: bytes | None = None  # PNG screenshot of the rendered page
    raw_bytes: bytes | None = None  # Raw file bytes (PDF, etc.)
    raw_content_type: str | None = None  # MIME type of raw file (application/pdf, etc.)

    @property
    def domain(self) -> str:
        from urllib.parse import urlparse

        return urlparse(self.url).netloc

    def looks_like_login_wall(self, original_url: str) -> bool:
        """Check if the result appears to be a login/signup redirect rather than real content."""
        login_signals = (
            "sign in", "sign up", "log in", "login", "create account",
            "auth", "register", "sso", "verify your identity",
        )
        title_lower = (self.title or "").lower()
        content_lower = (self.content or "")[:500].lower()

        # Title contains login language
        title_match = any(s in title_lower for s in login_signals)

        # Content is mostly login form (very short with login keywords)
        content_match = (
            len(self.content or "") < 1000
            and any(s in content_lower for s in login_signals)
        )

        # URL changed to a login/auth path
        from urllib.parse import urlparse

        result_path = urlparse(self.url).path.lower()
        auth_paths = ("/login", "/signin", "/signup", "/auth", "/sso", "/register")
        url_redirected = any(p in result_path for p in auth_paths)

        return title_match or content_match or url_redirected

    def looks_like_junk(self) -> str | None:
        """Check if the result is junk that shouldn't be saved.

        Returns a reason string if junk, None if OK.
        """
        content = self.content or ""
        title_lower = (self.title or "").lower()
        content_lower = content[:2000].lower()

        # Empty or near-empty content
        if len(content.strip()) < 300:
            return "Empty or near-empty content"

        # Cloudflare / bot detection pages
        cf_signals = (
            "just a moment", "checking your browser", "ray id", "cloudflare",
            "please wait while we verify", "unusual activity", "captcha",
            "recaptcha", "verify you are human", "verify you are not a robot",
            "please complete the security check", "access denied",
            "enable javascript and cookies", "browser check",
            "ddos protection", "attention required",
        )
        if any(s in title_lower or s in content_lower for s in cf_signals):
            return f"Bot detection page: {self.title}"

        # Error pages
        error_signals = (
            "404 not found", "page not found", "403 forbidden",
            "500 internal server error", "502 bad gateway",
            "an error occurred", "this page isn't available",
            "the page you requested", "sorry, we couldn't find",
        )
        if any(s in title_lower or s in content_lower for s in error_signals):
            return f"Error page: {self.title}"

        # Search result / index pages (not actual content)
        search_signals = ("search results for", "results for query")
        if any(s in title_lower for s in search_signals):
            return f"Search results page: {self.title}"

        # Binary garbage from PDFs that weren't properly extracted
        pdf_binary_signals = ("endstream", "endobj", "/FlateDecode", "%PDF-")
        sample = content[:2000]
        if any(m in sample for m in pdf_binary_signals):
            return "Binary PDF garbage in content"

        non_printable = sum(1 for c in sample if ord(c) > 127 or c in '\x00\x01\x02\x03\x04\x05')
        if non_printable > len(sample) * 0.15:
            return "High ratio of binary/non-printable content"

        # Cookie consent / boilerplate pages (short with mostly nav/cookie text)
        if len(content.strip()) < 1500:
            cookie_signals = (
                "we use cookies", "cookie policy", "accept cookies", "cookie consent",
                "there appears to be a technical issue", "please enable javascript",
            )
            if any(s in content_lower for s in cookie_signals):
                return "Cookie/boilerplate page"

        return None


@runtime_checkable
class WebProvider(Protocol):
    """Protocol for web content providers.

    Implementations must support at least fetch(). search() is optional —
    providers that don't support search raise NotImplementedError.
    """

    name: str

    def fetch(self, url: str) -> WebResult:
        """Fetch a single URL and return clean content."""
        ...

    def search(self, query: str, max_results: int = 5) -> list[WebResult]:
        """Search the web and return results with content."""
        ...


def get_provider(
    name: str | None = None,
    profile: str | None = None,
    magic: bool = False,
    headless: bool = True,
) -> WebProvider:
    """Load a web provider by name. Falls back to builtin if none specified."""
    if name is None or name == "builtin":
        from hyperresearch.web.builtin import BuiltinProvider

        return BuiltinProvider()

    if name == "crawl4ai":
        try:
            from hyperresearch.web.crawl4ai_provider import Crawl4AIProvider

            return Crawl4AIProvider(
                profile=profile or None,
                magic=magic,
                headless=headless,
            )
        except ImportError:
            raise ImportError("crawl4ai provider requires: pip install hyperresearch[crawl4ai]")

    if name == "exa":
        from hyperresearch.web.exa_provider import ExaProvider

        return ExaProvider()

    raise ValueError(f"Unknown web provider: {name!r}. Available: builtin, crawl4ai, exa")
