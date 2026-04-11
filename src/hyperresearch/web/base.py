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

    raise ValueError(f"Unknown web provider: {name!r}. Available: builtin, crawl4ai")
