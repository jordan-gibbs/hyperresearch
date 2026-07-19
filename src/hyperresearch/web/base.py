"""Base protocol and data types for web providers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from hyperresearch.core.config import FetchSettings, JunkGates

# Whitespace that is legitimate in extracted text.
_TEXT_WHITESPACE = "\t\n\r\f\v"

# Default thresholds — used when no vault config is in play (e.g. direct
# provider usage in tests/scripts). Matches VaultConfig defaults.
DEFAULT_GATES = JunkGates()


def is_binary_garbage_char(c: str) -> bool:
    """True if `c` indicates binary or mis-decoded content rather than real text.

    Deliberately NOT `ord(c) > 127`. Treating all non-ASCII as binary rejects
    valid CJK, Arabic, Cyrillic, Greek, Hebrew, Thai, and accented Latin text —
    i.e. most of the non-English web. Only genuine markers of binary data or a
    failed decode count here.
    """
    o = ord(c)
    if o < 0x20 and c not in _TEXT_WHITESPACE:
        return True  # C0 control characters
    if c == "�":
        return True  # replacement character — decoding already failed
    return 0x80 <= o <= 0x9F  # C1 control characters


def binary_garbage_ratio(text: str) -> float:
    """Fraction of `text` that looks like binary or mis-decoded content."""
    if not text:
        return 0.0
    return sum(1 for c in text if is_binary_garbage_char(c)) / len(text)


def is_binary_garbage(sample: str, gates: JunkGates | None = None) -> bool:
    """Shared threshold check for binary/mis-decoded content.

    Single implementation for both fetch gates (WebResult.looks_like_junk and
    the crawl4ai post-fetch PDF re-check) so the threshold can't drift apart
    between them again.
    """
    gates = gates or DEFAULT_GATES
    return binary_garbage_ratio(sample) > gates.binary_garbage_ratio


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

    def looks_like_login_wall(self, original_url: str, gates: JunkGates | None = None) -> bool:
        """Check if the result appears to be a login/signup redirect rather than real content."""
        gates = gates or DEFAULT_GATES
        login_signals = (
            "sign in", "sign up", "log in", "login", "create account",
            "auth", "register", "sso", "verify your identity",
            *gates.extra_login_signals,
        )
        title_lower = (self.title or "").lower()
        content_lower = (self.content or "")[: gates.login_sample_chars].lower()

        # Title contains login language
        title_match = any(s in title_lower for s in login_signals)

        # Content is mostly login form (very short with login keywords)
        content_match = (
            len(self.content or "") < gates.login_wall_max_chars
            and any(s in content_lower for s in login_signals)
        )

        # URL changed to a login/auth path
        from urllib.parse import urlparse

        result_path = urlparse(self.url).path.lower()
        auth_paths = ("/login", "/signin", "/signup", "/auth", "/sso", "/register")
        url_redirected = any(p in result_path for p in auth_paths)

        return title_match or content_match or url_redirected

    def looks_like_junk(self, gates: JunkGates | None = None) -> str | None:
        """Check if the result is junk that shouldn't be saved.

        Returns a reason string if junk, None if OK.
        """
        gates = gates or DEFAULT_GATES
        content = self.content or ""
        title_lower = (self.title or "").lower()
        content_lower = content[: gates.sample_window].lower()

        # Empty or near-empty content
        if len(content.strip()) < gates.min_content_chars:
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
        if any(s in title_lower or s in content_lower for s in cf_signals + tuple(gates.extra_junk_signals)):
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
        sample = content[: gates.sample_window]
        if any(m in sample for m in pdf_binary_signals):
            return "Binary PDF garbage in content"

        if is_binary_garbage(sample, gates):
            return "High ratio of binary/non-printable content"

        # Cookie consent / boilerplate pages (short with mostly nav/cookie text)
        if len(content.strip()) < gates.cookie_wall_max_chars:
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
    settings: FetchSettings | None = None,
    gates: JunkGates | None = None,
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
                settings=settings,
                gates=gates,
            )
        except ImportError:
            raise ImportError("crawl4ai provider requires: pip install hyperresearch[crawl4ai]")

    if name == "exa":
        from hyperresearch.web.exa_provider import ExaProvider

        return ExaProvider()

    if name == "tavily":
        try:
            from hyperresearch.web.tavily_provider import TavilyProvider

            return TavilyProvider()
        except ImportError:
            raise ImportError("tavily provider requires: pip install \"hyperresearch[tavily]\"")

    raise ValueError(f"Unknown web provider: {name!r}. Available: builtin, crawl4ai, exa, tavily")
