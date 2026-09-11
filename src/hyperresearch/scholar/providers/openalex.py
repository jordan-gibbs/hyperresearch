"""OpenAlex — the non-STEM backbone of discovery.

OpenAlex indexes roughly 250 million works across every field, and unlike the
incumbent stack (arXiv, PubMed, Semantic Scholar) it is not STEM-biased: books,
book chapters, dissertations and reports are first-class records carrying the
same metadata as journal articles. For a humanities or social-science query it
is frequently the only provider here that returns anything at all, which is why
the registry gives it first merge precedence.

No key, no registration. Setting `HYPERRESEARCH_CONTACT_EMAIL` adds `mailto=`
to every request, which moves us into OpenAlex's "polite pool" — a separate and
much more forgiving rate-limit bucket. Optional, but a heavy user who skips it
will meet throttling on the shared anonymous pool.

UPSTREAM QUIRKS
---------------
* **There are no plain abstracts.** OpenAlex ships `abstract_inverted_index`, a
  ``{word: [positions]}`` map, for licensing reasons — an inverted index is not
  a reproduction of the abstract. `_invert_abstract` rebuilds the prose by
  placing each word at each of its positions. Skip that step and this provider
  silently returns no abstracts at all, which is exactly the sort of failure
  that survives a green test suite, so `tests/test_scholar/test_openalex.py`
  pins the reconstructed ordering explicitly.
* **The index is often null**, especially for books and pre-2000 works. That is
  a missing abstract, not an error.
* **`type` has changed vocabulary over time.** Modern records say `article` and
  `preprint`; older ones carry the Crossref spellings `journal-article` and
  `posted-content`. `_TYPE_MAP` accepts both, and anything unrecognized becomes
  `other` rather than being guessed at.
"""

from __future__ import annotations

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

_BASE = "https://api.openalex.org/works"
_ID_PREFIX = "https://openalex.org/"

# OpenAlex `type` -> our WORK_TYPES vocabulary. Both the current spellings and
# the legacy Crossref-derived ones occur in live data, so both are listed.
_TYPE_MAP: dict[str, str] = {
    "article": "article",
    "journal-article": "article",
    "review": "article",
    "letter": "article",
    "editorial": "article",
    "book": "book",
    "monograph": "book",
    "reference-book": "book",
    "book-chapter": "book-chapter",
    "book-part": "book-chapter",
    "book-section": "book-chapter",
    "preprint": "preprint",
    "posted-content": "preprint",
    "dissertation": "thesis",
    "thesis": "thesis",
    "report": "report",
    "dataset": "dataset",
}

# The inverse, for the `work_type` filter. Values are OpenAlex `filter=type:`
# expressions; `|` is OpenAlex's OR, which is how one contract type covers both
# the modern and the legacy spelling in a single request.
_TYPE_FILTER: dict[str, str] = {
    "article": "article|journal-article",
    "book": "book|monograph|reference-book",
    "book-chapter": "book-chapter|book-part",
    "preprint": "preprint|posted-content",
    "thesis": "dissertation",
    "report": "report",
    "dataset": "dataset",
}

SORT_RELEVANCE = "relevance"
SORT_CITATIONS = "citations"



def _invert_abstract(index: Any) -> str | None:
    """Rebuild abstract prose from OpenAlex's ``{word: [positions]}`` map.

    The single most important function in this module. Positions are 0-based
    word offsets into the original abstract, and a word occurring three times
    carries three positions — so the reconstruction is "emit every
    (position, word) pair, sorted by position", not "join the keys".

    Sorting pairs rather than allocating a list of ``max(position) + 1`` slots
    is deliberate: the index arrives from a third party, positions have been
    seen sparse or absurdly large, and a slot array would happily try to
    allocate gigabytes on one malformed record.
    """
    if not isinstance(index, dict):
        return None
    slots: list[tuple[int, str]] = []
    for word, positions in index.items():
        if not isinstance(word, str):
            continue
        for position in as_list(positions):
            offset = as_int(position)
            if offset is not None:
                slots.append((offset, word))
    if not slots:
        return None
    slots.sort(key=lambda pair: pair[0])
    text = " ".join(word for _, word in slots).strip()
    return text or None


def _authors(work: dict[str, Any]) -> tuple[str, ...]:
    names: list[str] = []
    for authorship in as_list(work.get("authorships")):
        author = as_dict(as_dict(authorship).get("author"))
        name = as_str(author.get("display_name"))
        if name:
            names.append(name)
    return tuple(names)


class OpenAlexProvider(SearchProvider):
    """Relevance search over the OpenAlex works index."""

    slug: ClassVar[str] = "openalex"
    label: ClassVar[str] = "OpenAlex"
    covers: ClassVar[str] = (
        "~250M works across every discipline, including books, book chapters "
        "and theses. The broadest single source here and the right default for "
        "humanities and social-science queries."
    )
    needs_key: ClassVar[bool] = False
    key_env: ClassVar[tuple[str, ...]] = ()

    def __init__(self, work_type: str | None = None) -> None:
        """`work_type` sets a default record-type filter for every search.

        A caller after monographs rather than papers constructs
        `OpenAlexProvider("book")`; a caller holding one shared instance passes
        `work_type=` to `search` per query instead.
        """
        self.work_type = work_type

    # -- URL construction ---------------------------------------------------

    def _build_url(self, query: str, limit: int, sort: str, work_type: str | None) -> str:
        params = [f"search={quote(query)}", f"per-page={clamp_limit(limit, 200)}"]
        if work_type:
            expression = _TYPE_FILTER.get(work_type)
            if expression is None:
                supported = ", ".join(sorted(_TYPE_FILTER))
                raise ProviderError(
                    f"OpenAlex cannot filter on work_type {work_type!r}; supported: {supported}"
                )
            params.append("filter=" + quote("type:" + expression, safe=":|"))
        if sort == SORT_CITATIONS:
            params.append("sort=cited_by_count:desc")
        elif sort != SORT_RELEVANCE:
            raise ProviderError(
                f"OpenAlex sort must be {SORT_RELEVANCE!r} or {SORT_CITATIONS!r}, got {sort!r}"
            )
        # Relevance is OpenAlex's default whenever `search=` is present, so that
        # branch deliberately sends no `sort` at all — fewer URL variants means
        # more api_cache hits for the same question.
        email = contact_email()
        if email:
            params.append(f"mailto={quote(email)}")
        return f"{_BASE}?" + "&".join(params)

    # -- Parsing ------------------------------------------------------------

    def _to_paper(self, raw: Any) -> Paper | None:
        work = as_dict(raw)
        title = as_str(work.get("display_name")) or as_str(work.get("title"))
        if title is None:
            # OpenAlex does emit untitled records (some datasets, some
            # paratext). One with no title is unusable downstream.
            return None

        best_oa = as_dict(work.get("best_oa_location"))
        primary = as_dict(work.get("primary_location"))
        pdf_url = as_str(best_oa.get("pdf_url")) or as_str(primary.get("pdf_url"))
        venue = as_str(as_dict(primary.get("source")).get("display_name")) or as_str(
            as_dict(best_oa.get("source")).get("display_name")
        )

        doi = normalize_doi(as_str(work.get("doi")))
        openalex_id = as_str(work.get("id"))
        identifier = openalex_id
        if openalex_id and openalex_id.startswith(_ID_PREFIX):
            identifier = openalex_id[len(_ID_PREFIX) :]
        url = (
            as_str(primary.get("landing_page_url"))
            or as_str(best_oa.get("landing_page_url"))
            or (f"https://doi.org/{doi}" if doi else None)
            or openalex_id
        )

        raw_type = (as_str(work.get("type")) or "").lower()
        extra: dict[str, str] = {}
        if raw_type:
            extra["openalex_type"] = raw_type
        oa_status = as_str(as_dict(work.get("open_access")).get("oa_status"))
        if oa_status:
            extra["oa_status"] = oa_status

        return Paper(
            title=title,
            source=self.slug,
            url=url,
            doi=doi,
            year=coerce_year(work.get("publication_year")),
            authors=_authors(work),
            venue=venue,
            abstract=_invert_abstract(work.get("abstract_inverted_index")),
            pdf_url=pdf_url,
            citation_count=as_int(work.get("cited_by_count")),
            work_type=_TYPE_MAP.get(raw_type, "other"),
            identifier=identifier,
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
        """Up to `limit` works for `query`, best-effort.

        `sort` is `"relevance"` (default) or `"citations"` (`cited_by_count:desc`).
        `work_type` overrides the instance default and must be a contract type
        OpenAlex can express — see `_TYPE_FILTER`.

        Total by contract: any upstream failure or unexpected shape returns [].
        ProviderError is reserved for a request we cannot even form.
        """
        if not query.strip():
            raise ProviderError("OpenAlex requires a non-empty query")
        url = self._build_url(query.strip(), limit, sort, work_type or self.work_type)

        payload = fetch_json(conn, url, fresh=fresh)
        results = as_dict(payload).get("results")
        if not isinstance(results, list):
            return []

        papers: list[Paper] = []
        for item in results:
            paper = self._to_paper(item)
            if paper is not None:
                papers.append(paper)
        return papers
