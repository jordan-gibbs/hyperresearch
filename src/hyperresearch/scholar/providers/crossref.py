"""Crossref — the DOI registry itself.

Crossref is where DOIs are minted, so its metadata is authoritative for the
bibliographic spine of a record: DOI, publisher, container title, issue dates,
and the reference counts that `is-referenced-by-count` exposes. It is the right
cross-check when OpenAlex and a publisher page disagree about what a work even
is, and it carries very recent registrations that aggregators have not ingested
yet.

No key. Setting `HYPERRESEARCH_CONTACT_EMAIL` adds `mailto=`, which is how
Crossref routes a caller into its polite pool; anonymous callers share one
best-effort bucket with no rate-limit guarantee at all.

UPSTREAM QUIRKS
---------------
* **Abstracts are publisher-deposited and frequently absent.** Depositing an
  abstract is optional, and one published audit of sampled Crossref records
  found roughly a quarter carried no abstract at all, with several large
  publishers depositing none whatsoever. So `abstract=None` here is the normal
  case rather than a parse failure, and Crossref must never be the only source
  a caller relies on for abstract text.
* **When present, the abstract is JATS XML**, not prose — typically wrapped in
  `<jats:p>` and often opening with `<jats:title>Abstract</jats:title>`.
  `_strip_jats` flattens it and drops that redundant leading label.
* **`title` is a LIST, and it is regularly empty.** Same for `container-title`,
  `ISSN`, and most other "should be scalar" fields. Indexing `[0]` blind is the
  classic Crossref crash.
* **Dates are `date-parts: [[YYYY, MM, DD]]` with variable depth** — year-only
  registrations give `[[2019]]`, and unknown dates give `[[None]]` or `[]`.
* **`is-referenced-by-count`** is the citation count. It counts inbound
  references Crossref knows about, so it trends lower than OpenAlex's
  `cited_by_count` for the same work; consumers merging the two should not
  treat a disagreement as an error.
"""

from __future__ import annotations

import html
import re
import sqlite3
from typing import Any, ClassVar
from urllib.parse import quote

from hyperresearch.scholar.base import (
    Paper,
    ProviderError,
    SearchProvider,
    as_dict,
    as_int,
    as_list,
    as_str,
    clamp_limit,
    coerce_year,
    contact_email,
    fetch_json,
    normalize_doi,
)

_BASE = "https://api.crossref.org/works"

# Crossref `type` -> our WORK_TYPES vocabulary.
_TYPE_MAP: dict[str, str] = {
    "journal-article": "article",
    "proceedings-article": "article",
    "book-chapter": "book-chapter",
    "book-part": "book-chapter",
    "book-section": "book-chapter",
    "book": "book",
    "monograph": "book",
    "edited-book": "book",
    "reference-book": "book",
    "posted-content": "preprint",
    "dissertation": "thesis",
    "report": "report",
    "report-component": "report",
    "dataset": "dataset",
}

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
# Inline tags (<jats:italic>, <jats:sup>) become a space so words do not fuse,
# which leaves a stray gap before whatever punctuation followed the close tag.
_ORPHAN_PUNCT_RE = re.compile(r"\s+([.,;:!?)\]])")
# JATS deposits overwhelmingly open with a <jats:title>Abstract</jats:title>
# label. Leaving it in makes every abstract start with the word "Abstract",
# which is noise in a digest and in any embedding.
_LEADING_LABEL_RE = re.compile(r"^(?:abstract|summary)\s*[:.—-]?\s+", re.IGNORECASE)

SORT_RELEVANCE = "relevance"
SORT_CITATIONS = "citations"



def _first_string(value: Any) -> str | None:
    """First usable string in one of Crossref's list-valued scalar fields.

    Handles all four shapes seen in the wild: a populated list, an empty list,
    a bare string (Crossref is inconsistent for a few fields), and absent.
    """
    if isinstance(value, str):
        return as_str(value)
    for item in as_list(value):
        text = as_str(item)
        if text:
            return text
    return None


def _strip_jats(raw: Any) -> str | None:
    """JATS XML abstract -> plain text, or None."""
    text = as_str(raw)
    if text is None:
        return None
    # Tags first, then entities: unescaping first would turn a deposited
    # `&lt;script&gt;` into markup that the tag strip then eats.
    flattened = _TAG_RE.sub(" ", text)
    flattened = html.unescape(flattened)
    flattened = _WS_RE.sub(" ", flattened).strip()
    flattened = _ORPHAN_PUNCT_RE.sub(r"\1", flattened)
    flattened = _LEADING_LABEL_RE.sub("", flattened).strip()
    return flattened or None


def _authors(item: dict[str, Any]) -> tuple[str, ...]:
    """Author display names.

    Crossref splits people into `given`/`family` but gives organizations a
    single `name`, so both shapes have to be handled or consortium-authored
    papers come back with no authors at all.
    """
    names: list[str] = []
    for entry in as_list(item.get("author")):
        person = as_dict(entry)
        given = as_str(person.get("given"))
        family = as_str(person.get("family"))
        if family:
            names.append(f"{given} {family}" if given else family)
            continue
        organization = as_str(person.get("name"))
        if organization:
            names.append(organization)
    return tuple(names)


def _year(item: dict[str, Any]) -> int | None:
    """Publication year from whichever date field is populated.

    `issued` is the canonical one, but it is sometimes empty on records that do
    carry `published-print` / `published-online`, and `created` (the deposit
    timestamp) is the last resort — it is the date Crossref learned about the
    work, which is not the publication date but is rarely far off.
    """
    for key in ("issued", "published", "published-print", "published-online"):
        parts = as_list(as_dict(item.get(key)).get("date-parts"))
        for group in parts:
            first = as_list(group)
            if first:
                year = coerce_year(first[0])
                if year is not None:
                    return year
    return coerce_year(as_dict(item.get("created")).get("date-time"))


def _pdf_url(item: dict[str, Any]) -> str | None:
    """A PDF link, if the publisher deposited one.

    Caveat for consumers: most `link` entries carry
    `intended-application: similarity-checking`, meaning the URL is registered
    for plagiarism services and will usually answer a plain GET with a paywall.
    We surface it anyway because it resolves for open-access publishers, but a
    fetch failure on one of these is expected, not a bug.
    """
    for entry in as_list(item.get("link")):
        link = as_dict(entry)
        if as_str(link.get("content-type")) == "application/pdf":
            url = as_str(link.get("URL"))
            if url:
                return url
    return None


class CrossrefProvider(SearchProvider):
    """Bibliographic search over the Crossref DOI registry."""

    slug: ClassVar[str] = "crossref"
    label: ClassVar[str] = "Crossref"
    covers: ClassVar[str] = (
        "The DOI registry — authoritative bibliographic metadata for ~160M "
        "registered works, including very recent registrations. Abstracts are "
        "publisher-deposited and often missing."
    )
    needs_key: ClassVar[bool] = False
    key_env: ClassVar[tuple[str, ...]] = ()

    def __init__(self, work_type: str | None = None) -> None:
        """`work_type` sets a default `filter=type:` for every search."""
        self.work_type = work_type

    # -- URL construction ---------------------------------------------------

    def _build_url(self, query: str, limit: int, sort: str, work_type: str | None) -> str:
        params = [f"query={quote(query)}", f"rows={clamp_limit(limit, 100)}"]
        if work_type:
            # Crossref filters on its OWN vocabulary and accepts only one
            # `type:` per filter, so the contract type has to round-trip
            # through the first Crossref spelling that maps back to it.
            crossref_type = next(
                (src for src, dest in _TYPE_MAP.items() if dest == work_type), None
            )
            if crossref_type is None:
                supported = ", ".join(sorted(set(_TYPE_MAP.values())))
                raise ProviderError(
                    f"Crossref cannot filter on work_type {work_type!r}; supported: {supported}"
                )
            params.append("filter=" + quote(f"type:{crossref_type}", safe=":"))
        if sort == SORT_CITATIONS:
            params.append("sort=is-referenced-by-count&order=desc")
        elif sort != SORT_RELEVANCE:
            raise ProviderError(
                f"Crossref sort must be {SORT_RELEVANCE!r} or {SORT_CITATIONS!r}, got {sort!r}"
            )
        # Relevance is Crossref's default for a `query=` search, so that branch
        # sends no `sort` — identical questions then share one cache entry.
        email = contact_email()
        if email:
            params.append(f"mailto={quote(email)}")
        return f"{_BASE}?" + "&".join(params)

    # -- Parsing ------------------------------------------------------------

    def _to_paper(self, raw: Any) -> Paper | None:
        item = as_dict(raw)
        title = _first_string(item.get("title"))
        if title is None:
            # An empty `title: []` is common on components, datasets and some
            # conference proceedings. Untitled records are unusable.
            return None
        subtitle = _first_string(item.get("subtitle"))
        if subtitle and subtitle.lower() not in title.lower():
            title = f"{title}: {subtitle}"

        doi = normalize_doi(as_str(item.get("DOI")))
        raw_type = (as_str(item.get("type")) or "").lower()

        extra: dict[str, str] = {}
        if raw_type:
            extra["crossref_type"] = raw_type
        publisher = as_str(item.get("publisher"))
        if publisher:
            extra["publisher"] = publisher

        return Paper(
            title=_WS_RE.sub(" ", title),
            source=self.slug,
            url=as_str(item.get("URL")) or (f"https://doi.org/{doi}" if doi else None),
            doi=doi,
            year=_year(item),
            authors=_authors(item),
            venue=_first_string(item.get("container-title")),
            abstract=_strip_jats(item.get("abstract")),
            pdf_url=_pdf_url(item),
            citation_count=as_int(item.get("is-referenced-by-count")),
            work_type=_TYPE_MAP.get(raw_type, "other"),
            identifier=doi,
            extra=extra,
        )

    # -- Entry point --------------------------------------------------------

    def search(
        self,
        conn: sqlite3.Connection | None,
        query: str,
        limit: int,
        *,
        fresh: bool = False,
        sort: str = SORT_RELEVANCE,
        work_type: str | None = None,
    ) -> list[Paper]:
        """Up to `limit` registered works for `query`, best-effort.

        `sort` is `"relevance"` (default) or `"citations"`
        (`is-referenced-by-count`, descending).

        Total by contract: any upstream failure or unexpected shape returns [].
        ProviderError is reserved for a request we cannot even form.
        """
        if not query.strip():
            raise ProviderError("Crossref requires a non-empty query")
        url = self._build_url(query.strip(), limit, sort, work_type or self.work_type)

        payload = fetch_json(conn, url, fresh=fresh)
        # Crossref nests everything one level down under `message`; a failure
        # response is well-formed JSON with `status: "error"` and no items, so
        # shape-checking rather than status-checking covers both.
        items = as_dict(as_dict(payload).get("message")).get("items")
        if not isinstance(items, list):
            return []

        papers: list[Paper] = []
        for item in items:
            paper = self._to_paper(item)
            if paper is not None:
                papers.append(paper)
        return papers
