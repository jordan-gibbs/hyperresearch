"""CORE — the largest aggregator of open-access full text.

CORE harvests ~30k repositories and journals and, unlike every metadata index
in this package, it *hosts what it indexes*: a record carries a `fullText`
field and a CORE-served PDF, not merely a pointer at a publisher who may or
may not let you in. That is why `core/oa.py` also uses this API as a full-text
resolver — see `_core_candidates` there.

A key is required (self-service registration) and goes in `CORE_API_KEY`. Without one
the provider reports itself unavailable and the registry skips it, so a user
who never registers still gets every other source rather than an error.

Field shapes below were checked against the live v3 API rather than the docs,
which matters: `downloadUrl` comes back as `""` rather than absent, `journals`
entries carry `title: null`, `documentType` is frequently null with the real
classification in `fieldOfStudy`, and `fullText` is the literal string
"Not available for public API users." for unauthenticated callers. Every read
here is defensive for that reason.
"""

from __future__ import annotations

import sqlite3
from typing import Any, ClassVar
from urllib.parse import quote

from hyperresearch.scholar.base import (
    Paper,
    ProviderError,
    SearchProvider,
    clamp_limit,
    coerce_year,
    fetch_json,
    normalize_doi,
)

API_BASE = "https://api.core.ac.uk/v3"

# CORE caps a search page at 100 records.
MAX_PAGE = 100

# `fullText` is megabytes of prose and this provider only wants metadata.
# Excluding it server-side is not a micro-optimization: without it a 25-result
# search moves tens of megabytes and lands every byte of it in `api_cache`.
_EXCLUDE = "fullText"

# CORE's own vocabulary, mapped onto WORK_TYPES. Anything unlisted — including
# the null this field usually is — falls through to "article".
_WORK_TYPES = {
    "article": "article",
    "journal-article": "article",
    "conference-paper": "article",
    "research": "article",
    "preprint": "preprint",
    "thesis": "thesis",
    "dissertation": "thesis",
    "book": "book",
    "book-chapter": "book-chapter",
    "report": "report",
    "dataset": "dataset",
    "patent": "patent",
    "presentation": "other",
    "slides": "other",
    "bibliography": "other",
}


class CoreProvider(SearchProvider):
    slug: ClassVar[str] = "core"
    label: ClassVar[str] = "CORE"
    covers: ClassVar[str] = (
        "Open-access full text aggregated from ~30k repositories and journals. "
        "Strongest source for repository copies of paywalled papers; weakest on "
        "citation counts, which are sparse and often reported as zero."
    )
    needs_key: ClassVar[bool] = True
    key_env: ClassVar[tuple[str, ...]] = ("CORE_API_KEY",)

    def search(
        self,
        conn: sqlite3.Connection | None,
        query: str,
        limit: int,
        *,
        fresh: bool = False,
    ) -> list[Paper]:
        key = self.api_key()
        if key is None:
            # Per the SearchProvider contract: a missing required key means the
            # provider could not be attempted at all, which is not the same as
            # an empty result set and must not be reported as one.
            raise ProviderError("CORE requires an API key in CORE_API_KEY")

        url = search_url(query, clamp_limit(limit, MAX_PAGE))
        data = fetch_json(conn, url, fresh=fresh, headers=auth_headers(key))
        return papers_from_response(data)


# ---------------------------------------------------------------------------
# Request construction — shared with the open-access resolver
# ---------------------------------------------------------------------------


def auth_headers(key: str) -> dict[str, str]:
    """v3 authenticates by bearer token; there is no query-parameter form."""
    return {"Authorization": f"Bearer {key}"}


def search_url(query: str, limit: int) -> str:
    """Search URL for `query`.

    GET rather than the documented POST because the shared HTTP layer is
    GET-only (and cache-keyed by URL, which a POST body would defeat). The
    trailing slash is deliberate: it is the form verified against the live
    API and the one the SearXNG client ships with.

    `doi:"10.x/y"` in `q` is CORE's fielded-query syntax and returns exactly
    the work with that DOI — how `core/oa.py` resolves a paywalled paper.
    """
    return (
        f"{API_BASE}/search/works/"
        f"?q={quote(query, safe='')}&limit={limit}&exclude={_EXCLUDE}"
    )


def doi_search_url(doi: str) -> str:
    """The one work CORE holds for `doi`, metadata only."""
    return search_url(f'doi:"{doi}"', 1)


def work_url(core_id: str) -> str:
    """`GET /works/{id}` — the bare work object, `fullText` included.

    This is the endpoint the open-access resolver reads plain text from. It is
    NOT sent through `api_cache`: the note that gets written is the cache for a
    full paper, and the metadata table is not the place for 200 KB bodies.
    """
    return f"{API_BASE}/works/{quote(core_id, safe='')}"


# What CORE returns in `fullText` when the caller is not authenticated. Left
# as a case-insensitive prefix match so a wording tweak upstream still trips
# it; the length floor in `core/oa.py` is the backstop if it does not.
_NO_FULL_TEXT_SENTINEL = "not available for public api users"


def full_text_from_work(data: Any) -> str | None:
    """The plain text carried by a `/works/{id}` response, or None.

    None for a missing or empty field, and — the case that matters — for
    CORE's unauthenticated-caller placeholder, which is a real string that
    would otherwise reach the length gate as a 35-character "paper".
    """
    if not isinstance(data, dict):
        return None
    text = _text(data.get("fullText"))
    if text is None or text.lower().startswith(_NO_FULL_TEXT_SENTINEL):
        return None
    return text


def papers_from_response(data: Any) -> list[Paper]:
    """Parse a `/search/works/` envelope. Any unexpected shape yields []."""
    if not isinstance(data, dict):
        return []
    results = data.get("results")
    if not isinstance(results, list):
        return []

    papers: list[Paper] = []
    for record in results:
        if not isinstance(record, dict):
            continue
        paper = paper_from_record(record)
        if paper is not None:
            papers.append(paper)
    return papers


# ---------------------------------------------------------------------------
# Record mapping
# ---------------------------------------------------------------------------


def paper_from_record(record: dict[str, Any]) -> Paper | None:
    """One CORE work as a `Paper`, or None when it has no usable title."""
    title = _text(record.get("title"))
    if not title:
        return None

    core_id = _identifier(record)
    return Paper(
        title=title,
        source=CoreProvider.slug,
        url=_record_url(record, core_id),
        doi=normalize_doi(_text(record.get("doi"))),
        year=coerce_year(record.get("yearPublished") or record.get("publishedDate")),
        authors=_authors(record),
        venue=_venue(record),
        abstract=_text(record.get("abstract")),
        pdf_url=_pdf_url(record),
        citation_count=_citation_count(record),
        work_type=_work_type(record),
        identifier=core_id,
        extra=_extra(record, core_id),
    )


def _text(value: Any) -> str | None:
    """A non-empty stripped string, or None. CORE prefers "" to null."""
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _identifier(record: dict[str, Any]) -> str | None:
    value = record.get("id")
    if isinstance(value, int):
        return str(value)
    return _text(value)


def _authors(record: dict[str, Any]) -> tuple[str, ...]:
    """Author display names, order preserved, exact duplicates dropped.

    CORE merges several repository records into one work, so the same person
    routinely appears twice in different orderings ("Silander, Olin K." and
    "Olin K Silander"). Only byte-identical repeats are collapsed: guessing
    which orderings denote the same human is how you lose a real co-author.
    """
    names: list[str] = []
    seen: set[str] = set()
    for entry in record.get("authors") or []:
        name = _text(entry.get("name")) if isinstance(entry, dict) else _text(entry)
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return tuple(names)


def _venue(record: dict[str, Any]) -> str | None:
    """Journal title if CORE has one, else the publisher.

    `journals` is often `[{"title": null, "identifiers": []}]` — present but
    empty — so the publisher fallback has to survive a truthy-looking entry.
    """
    for journal in record.get("journals") or []:
        if isinstance(journal, dict):
            title = _text(journal.get("title"))
            if title:
                return title
    return _text(record.get("publisher"))


def _pdf_url(record: dict[str, Any]) -> str | None:
    download = _text(record.get("downloadUrl"))
    if download:
        return download
    for url in source_fulltext_urls(record):
        if looks_like_pdf(url):
            return url
    return None


def _record_url(record: dict[str, Any], core_id: str | None) -> str | None:
    """Where a human should be sent for this work."""
    display = _link_of_type(record, "display")
    if display:
        return display
    download = _text(record.get("downloadUrl"))
    if download:
        return download
    if core_id:
        return f"https://core.ac.uk/works/{quote(core_id, safe='')}"
    doi = normalize_doi(_text(record.get("doi")))
    return f"https://doi.org/{doi}" if doi else None


def _link_of_type(record: dict[str, Any], wanted: str) -> str | None:
    for link in record.get("links") or []:
        if not isinstance(link, dict):
            continue
        if _text(link.get("type")) == wanted:
            return _text(link.get("url"))
    return None


def _citation_count(record: dict[str, Any]) -> int | None:
    """CORE's count as reported, including zero.

    Zero is common and frequently wrong — CORE returned 0 for a PLOS ONE paper
    with four figures of citations. It is reported honestly rather than
    laundered into None because the registry already ranks OpenAlex and
    Crossref ahead of CORE when merging this field.
    """
    value = record.get("citationCount")
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value >= 0 else None


def _work_type(record: dict[str, Any]) -> str:
    for key in ("documentType", "fieldOfStudy"):
        raw = _text(record.get(key))
        if raw:
            mapped = _WORK_TYPES.get(raw.lower())
            if mapped:
                return mapped
    return "article"


def _extra(record: dict[str, Any], core_id: str | None) -> dict[str, str]:
    extra: dict[str, str] = {}
    if core_id:
        extra["core_id"] = core_id
    for field_name, key in (("documentType", "document_type"), ("fieldOfStudy", "field_of_study")):
        value = _text(record.get(field_name))
        if value:
            extra[key] = value
    provider = _first_data_provider(record)
    if provider:
        extra["data_provider"] = provider
    return extra


def _first_data_provider(record: dict[str, Any]) -> str | None:
    for entry in record.get("dataProviders") or []:
        if isinstance(entry, dict):
            name = _text(entry.get("name"))
            if name:
                return name
    return None


def source_fulltext_urls(record: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for value in record.get("sourceFulltextUrls") or []:
        url = _text(value)
        if url and url not in urls:
            urls.append(url)
    return urls


def looks_like_pdf(url: str) -> bool:
    """Best-effort: a path ending in .pdf, or a query that asks for one.

    Europe PMC copies arrive as `.../articles/PMC1790863?pdf=render`, where the
    path alone says nothing. Guessing wrong is cheap — the PDF extractor
    returns None and the next candidate is tried.
    """
    lowered = url.lower()
    path, _, query = lowered.partition("?")
    return path.endswith(".pdf") or "pdf" in query
