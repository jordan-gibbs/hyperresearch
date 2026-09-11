"""Shared contract for academic and specialist discovery providers.

`core/scholar.py` ENRICHES records we already hold — citation counts, venue,
retraction status — starting from a DOI or an arXiv id. This package FINDS
them in the first place.

Until now discovery existed only as prose: `core/agent_docs.py` rendered URL
templates into the agent's instructions and trusted the model to construct
and call them by hand. That meant no retry, no rate limiting, no dedup, no
offline tests, and a corpus whose quality depended on an LLM transcribing a
docstring correctly. Every provider here is a real client sharing one cache,
one courtesy rate limiter, and one result shape.

Provider authors: subclass `SearchProvider`, set the class attributes, and
implement `search()`. Do NOT call httpx directly — go through `fetch_json`
or `fetch_text` so you inherit the cache, the per-host delay, and the
monkeypatch seam the tests rely on.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
import unicodedata
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar
from urllib.parse import urlparse

# Per-host courtesy delay between UNCACHED requests, in seconds. Hosts absent
# from this table get _DEFAULT_DELAY. Keep these honest: several of these APIs
# are free public goods and a shared anonymous pool is easy to spoil for
# everyone. See core/scholar.py for the enrichment side's equivalent table.
_HOST_DELAY: dict[str, float] = {
    "api.openalex.org": 0.15,
    "api.crossref.org": 0.15,
    "api.core.ac.uk": 0.4,
    "api.semanticscholar.org": 1.1,
    "export.arxiv.org": 3.0,  # arXiv asks for one request per three seconds
    "eutils.ncbi.nlm.nih.gov": 0.4,
    "clinicaltrials.gov": 0.3,
    "data.sec.gov": 0.15,
    "efts.sec.gov": 0.15,
    "www.sec.gov": 0.15,
    "api.stlouisfed.org": 0.3,
    "api.repec.org": 0.5,
    "directory.doabooks.org": 0.4,
}
_DEFAULT_DELAY = 0.3
_last_call: dict[str, float] = {}

DEFAULT_TTL_DAYS = 30

# Several of these APIs ask for a contact address rather than a key. We send a
# generic project UA by default; a user who sets HYPERRESEARCH_CONTACT_EMAIL
# gets the polite-pool treatment on OpenAlex and Crossref and a compliant
# User-Agent on SEC EDGAR, which requires one.
_UA = "hyperresearch (https://github.com/jordan-gibbs/hyperresearch)"


class ProviderError(RuntimeError):
    """A provider could not run at all — missing key, malformed query."""


def contact_email() -> str | None:
    """Operator contact address, if configured. Never invent a placeholder."""
    value = os.environ.get("HYPERRESEARCH_CONTACT_EMAIL", "").strip()
    return value or None


def user_agent() -> str:
    email = contact_email()
    return f"{_UA} (mailto:{email})" if email else _UA


def env_key(*names: str) -> str | None:
    """First non-empty value among `names` in the environment, else None."""
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return None


# ---------------------------------------------------------------------------
# Result shape
# ---------------------------------------------------------------------------

# Deliberately broader than "paper": this package also returns clinical trials,
# regulatory filings and economic series, which are records a research corpus
# legitimately cites but which are not articles. Consumers branch on this.
WORK_TYPES = (
    "article",
    "preprint",
    "book",
    "book-chapter",
    "thesis",
    "report",
    "dataset",
    "trial",
    "filing",
    "series",
    "patent",
    "other",
)


@dataclass(frozen=True)
class Paper:
    """One discovered record, normalized across providers.

    Only `title` and `source` are guaranteed. Everything else is absent often
    enough that consumers must handle None — half these APIs omit abstracts,
    and Crossref in particular returns none for whole publishers.
    """

    title: str
    source: str
    url: str | None = None
    doi: str | None = None
    year: int | None = None
    authors: tuple[str, ...] = ()
    venue: str | None = None
    abstract: str | None = None
    pdf_url: str | None = None
    citation_count: int | None = None
    work_type: str = "article"
    identifier: str | None = None
    extra: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "source": self.source,
            "url": self.url,
            "doi": self.doi,
            "year": self.year,
            "authors": list(self.authors),
            "venue": self.venue,
            "abstract": self.abstract,
            "pdf_url": self.pdf_url,
            "citation_count": self.citation_count,
            "work_type": self.work_type,
            "identifier": self.identifier,
            "extra": dict(self.extra),
        }


# ---------------------------------------------------------------------------
# Identity helpers — shared so dedup agrees with every provider
# ---------------------------------------------------------------------------

_DOI_PREFIX_RE = re.compile(r"^(?:https?://)?(?:dx\.)?doi\.org/", re.IGNORECASE)
_TITLE_STRIP_RE = re.compile(r"[^a-z0-9]+")


def normalize_doi(doi: str | None) -> str | None:
    """Lowercased bare DOI, or None. Accepts full doi.org URLs and `doi:` forms."""
    if not doi:
        return None
    value = _DOI_PREFIX_RE.sub("", doi.strip())
    if value.lower().startswith("doi:"):
        value = value[4:]
    value = value.strip().rstrip(".,;").lower()
    return value or None


def title_key(title: str) -> str:
    """Aggressive fingerprint for matching the same work across providers.

    Providers disagree on case, punctuation, LaTeX and trailing periods, so a
    strict comparison never matches. Accents are folded because Crossref and
    OpenAlex disagree on whether to decompose them.
    """
    folded = unicodedata.normalize("NFKD", title)
    ascii_only = "".join(c for c in folded if not unicodedata.combining(c))
    return _TITLE_STRIP_RE.sub("", ascii_only.lower())


# ---------------------------------------------------------------------------
# HTTP layer — cache-first, rate-limited, monkeypatchable
# ---------------------------------------------------------------------------


def _http_get(url: str, headers: dict[str, str] | None = None) -> str | None:
    """Raw GET returning the body as text, or None on any failure.

    The single network seam for this package. Tests monkeypatch exactly this
    function; nothing else here touches the network. Failure is always soft —
    one dead provider must not take down a multi-provider search.
    """
    import httpx

    merged = {"User-Agent": user_agent()}
    if headers:
        merged.update(headers)
    try:
        resp = httpx.get(url, follow_redirects=True, timeout=25, headers=merged)
    except Exception:
        return None
    if resp.status_code != 200:
        return None
    try:
        return resp.text
    except Exception:
        return None


def _throttle(url: str) -> None:
    host = urlparse(url).netloc.lower()
    delay = _HOST_DELAY.get(host, _DEFAULT_DELAY)
    elapsed = time.monotonic() - _last_call.get(host, 0.0)
    if elapsed < delay:
        time.sleep(delay - elapsed)
    _last_call[host] = time.monotonic()


def fetch_text(
    conn: sqlite3.Connection | None,
    url: str,
    *,
    ttl_days: int = DEFAULT_TTL_DAYS,
    fresh: bool = False,
    headers: dict[str, str] | None = None,
) -> str | None:
    """Cache-first GET returning body text. Use for XML/Atom providers.

    `conn` may be None, which skips the cache entirely — useful in tests and
    for callers with no vault open.
    """
    now = datetime.now(UTC)
    if conn is not None and not fresh:
        row = conn.execute(
            "SELECT body, fetched_at FROM api_cache WHERE url = ?", (url,)
        ).fetchone()
        if row:
            try:
                fetched: datetime | None = datetime.fromisoformat(row["fetched_at"])
            except (ValueError, TypeError):
                fetched = None
            if fetched and now - fetched < timedelta(days=ttl_days):
                body = row["body"]
                return str(body) if body is not None else None

    _throttle(url)
    text = _http_get(url, headers)
    if text is not None and conn is not None:
        conn.execute(
            "INSERT OR REPLACE INTO api_cache (url, body, fetched_at) VALUES (?, ?, ?)",
            (url, text, now.isoformat()),
        )
        conn.commit()
    return text


def fetch_json(
    conn: sqlite3.Connection | None,
    url: str,
    *,
    ttl_days: int = DEFAULT_TTL_DAYS,
    fresh: bool = False,
    headers: dict[str, str] | None = None,
) -> Any | None:
    """Cache-first GET returning parsed JSON, or None on any failure."""
    text = fetch_text(conn, url, ttl_days=ttl_days, fresh=fresh, headers=headers)
    if text is None:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------------------
# Defensive coercion — every upstream returns the wrong type somewhere
# ---------------------------------------------------------------------------


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def as_str(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def as_int(value: Any) -> int | None:
    # bool is an int subclass and would otherwise become 0/1 silently — a
    # stray `true` in a citation-count field must not turn into "1 citation".
    if isinstance(value, bool):
        return None
    return value if isinstance(value, int) else None


# ---------------------------------------------------------------------------
# Provider contract
# ---------------------------------------------------------------------------


class SearchProvider(ABC):
    """One discovery source.

    Subclasses set the class attributes and implement `search`. Keep `search`
    total: return [] rather than raising when the upstream is unreachable or
    returns something unexpected. Raise ProviderError only when the provider
    could not be attempted at all, such as a missing required key.
    """

    slug: ClassVar[str] = ""
    label: ClassVar[str] = ""
    # What this source is actually good for. Shown in `hpr scholar sources`
    # so a user picking a provider is not guessing from the name.
    covers: ClassVar[str] = ""
    needs_key: ClassVar[bool] = False
    key_env: ClassVar[tuple[str, ...]] = ()

    def api_key(self) -> str | None:
        return env_key(*self.key_env) if self.key_env else None

    def available(self) -> bool:
        """False when a required key is absent, so the registry can skip us."""
        return not self.needs_key or self.api_key() is not None

    def unavailable_reason(self) -> str | None:
        if self.available():
            return None
        names = " or ".join(self.key_env) or "an API key"
        return f"{self.label}: set {names}"

    @abstractmethod
    def search(
        self,
        conn: sqlite3.Connection | None,
        query: str,
        limit: int,
        *,
        fresh: bool = False,
    ) -> list[Paper]:
        """Return up to `limit` records for `query`, best-effort."""
        raise NotImplementedError


def clamp_limit(limit: int, ceiling: int = 200) -> int:
    return max(1, min(limit, ceiling))


def coerce_year(value: Any) -> int | None:
    """Years arrive as ints, strings, and full dates depending on the API."""
    if value is None:
        return None
    if isinstance(value, int):
        return value if 1000 <= value <= 2200 else None
    text = str(value).strip()
    if len(text) >= 4 and text[:4].isdigit():
        year = int(text[:4])
        return year if 1000 <= year <= 2200 else None
    return None
