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

    @property
    def domain(self) -> str:
        from urllib.parse import urlparse

        return urlparse(self.url).netloc


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


def get_provider(name: str | None = None) -> WebProvider:
    """Load a web provider by name. Falls back to builtin if none specified."""
    if name is None or name == "builtin":
        from hyperresearch.web.builtin import BuiltinProvider

        return BuiltinProvider()

    if name == "crawl4ai":
        try:
            from hyperresearch.web.crawl4ai_provider import Crawl4AIProvider

            return Crawl4AIProvider()
        except ImportError:
            raise ImportError("crawl4ai provider requires: pip install hyperresearch[crawl4ai]")

    if name == "tavily":
        try:
            from hyperresearch.web.tavily_provider import TavilyProvider

            return TavilyProvider()
        except ImportError:
            raise ImportError("tavily provider requires: pip install hyperresearch[tavily]")

    if name == "firecrawl":
        try:
            from hyperresearch.web.firecrawl_provider import FirecrawlProvider

            return FirecrawlProvider()
        except ImportError:
            raise ImportError("firecrawl provider requires: pip install hyperresearch[firecrawl]")

    if name == "trafilatura":
        try:
            from hyperresearch.web.trafilatura_provider import TrafilaturaProvider

            return TrafilaturaProvider()
        except ImportError:
            raise ImportError(
                "trafilatura provider requires: pip install hyperresearch[trafilatura]"
            )

    raise ValueError(f"Unknown web provider: {name!r}")
