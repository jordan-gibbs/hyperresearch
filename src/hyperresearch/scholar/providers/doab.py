"""DOAB — the Directory of Open Access Books.

DOAB is a curated index of peer-reviewed open-access scholarly books and
chapters, run by the OAPEN Foundation and OpenEdition. It exists to close the
gap that every article-shaped API in this package leaves open: in the
humanities and much of the social sciences the monograph is the unit of
publication, and a search stack built on OpenAlex, Crossref and arXiv will
return the book reviews and skip the book. Listing in DOAB requires a
publisher-level peer-review policy check, so a hit here is a real scholarly
book rather than a self-published PDF, and every record is open access by
construction.

No key, no registration. Records carry a DOAB handle, usually a DOI, the
publisher, and a link to the full text on OAPEN or the publisher's site.

WHICH ENDPOINT, AND WHY
-----------------------
DOAB runs on DSpace and exposes three interfaces. Only one is usable here,
verified live on 2026-09-11:

* **`/rest/search?query=` — USED.** The legacy DSpace REST search that DOAB's
  own "API: Search DOAB" page documents. Returns a bare JSON array of items.
  Honours `limit`, `offset` and `expand`; an unmatched query returns `[]`.
* **`/oai/request` — live but not a search.** OAI-PMH supports date- and
  set-scoped harvesting only; there is no keyword query, so it cannot serve a
  discovery call. (Its `Identify` reports OAPEN's base URL, a hint that both
  directories share one DSpace deployment.)
* **`/server/api/discover/search/objects` — NOT usable.** The DSpace 7 REST
  API answers programmatic callers with a Cloudflare interstitial (HTTP 403
  "Just a moment..."). Do not "upgrade" to it.

UPSTREAM QUIRKS
---------------
* **Nothing useful comes back without `expand=metadata`.** The bare item has
  `name: null` and no metadata list at all; every bibliographic field lives
  in a DSpace `metadata: [{key, value, language}]` list keyed by dotted
  qualified Dublin Core names. `_metadata` folds that into a multimap.
* **Response time scales with `limit`, roughly 0.6 s per record.** Measured:
  25 records in ~8 s, 100 in ~49 s. The shared HTTP layer times out at 25 s,
  so we page at `_PAGE` records per request rather than asking for
  everything at once. Do not raise the page size without re-measuring.
* **`expand=bitstreams` is not worth it.** It roughly triples both payload
  and latency (25 records took 47 s), and DOAB hosts no files anyway: it is a
  directory. Its bitstreams are thumbnails and MARC/ONIX exports; the actual
  full-text link rides on the THUMBNAIL record as `oapen.identifier.downloadUrl`
  and is sometimes a DOI or publisher landing page rather than a PDF. We
  take that key from item-level metadata when it appears there and otherwise
  rely on the DOI, which `core/oa.py` already resolves to open full text.
* **The query is passed straight to Solr.** A bare `AND`, an unbalanced
  parenthesis or a stray `*` produce an HTTP 500, and `word:word` is parsed
  as a field search that matches nothing. `_sanitize` strips the operator
  characters so a natural-language query cannot trip either failure.
* **`dc.identifier` is a grab bag** — OAPEN handles, OCLC numbers, ONIX batch
  ids, occasionally a DOI. The DOI proper is `oapen.identifier.doi`; the
  grab bag is scanned only as a fallback.
* **Edited volumes list `dc.contributor.editor` and no author.** We fall back
  to the editors so the record is not authorless, and flag it in `extra`.
* **`dc.type` is `book` or `chapter`**, lower-case. Chapter records exist for
  publishers that deposit at chapter granularity and carry their own DOI.
"""

from __future__ import annotations

import re
import sqlite3
from collections import defaultdict
from typing import Any, ClassVar
from urllib.parse import quote

from hyperresearch.scholar.base import (
    Paper,
    ProviderError,
    SearchProvider,
    as_dict,
    as_list,
    as_str,
    clamp_limit,
    coerce_year,
    fetch_json,
    normalize_doi,
)

_BASE = "https://directory.doabooks.org/rest/search"
_HANDLE_BASE = "https://directory.doabooks.org/handle/"

# Records per upstream request. See "Response time scales with `limit`" above:
# 20 records is comfortably inside the 25 s client timeout with headroom for
# a slow day.
_PAGE = 20
# Hard ceiling per search — five pages. Beyond this the caller is harvesting,
# and OAI-PMH is the right tool for that.
_MAX = 100

# DOAB `dc.type` -> our WORK_TYPES vocabulary. Anything else DOAB might add
# is still a book-shaped object, hence the default in `_to_paper`.
_TYPE_MAP: dict[str, str] = {
    "book": "book",
    "chapter": "book-chapter",
}

# Solr query-syntax characters. Every one of these either errors (unbalanced
# grouping, wildcards) or silently changes the query's meaning (field
# prefixes, boosts, fuzz). Hyphen is deliberately kept: it is a NOT only at
# term start and is common inside words ("post-colonial").
_SOLR_SPECIAL_RE = re.compile(r"[:()\[\]{}^~*?\\/!|+]")
# Bare boolean operators are only operators when upper-case; folding them
# turns `war AND peace` into a plain three-word query instead of a 500.
_SOLR_OPERATOR_RE = re.compile(r"\b(AND|OR|NOT)\b")
_WS_RE = re.compile(r"\s+")
_DOI_RE = re.compile(r"\b(10\.\d{4,9}/\S+)", re.IGNORECASE)



def _sanitize(query: str) -> str:
    """Natural-language query -> something Solr will not choke on.

    Quotes survive only when balanced, since an odd quote is another route
    to an HTTP 500.
    """
    text = _SOLR_SPECIAL_RE.sub(" ", query)
    text = _SOLR_OPERATOR_RE.sub(lambda m: m.group(1).lower(), text)
    if text.count('"') % 2:
        text = text.replace('"', " ")
    return _WS_RE.sub(" ", text).strip()


def _metadata(item: dict[str, Any]) -> dict[str, list[str]]:
    """DSpace's `[{key, value}]` list folded into key -> values, order kept.

    Repeated keys are the norm (several authors, many subjects), and a value
    may be null on a half-migrated record, so this cannot be a plain dict
    comprehension.
    """
    folded: dict[str, list[str]] = defaultdict(list)
    for entry in as_list(item.get("metadata")):
        pair = as_dict(entry)
        key = as_str(pair.get("key"))
        value = as_str(pair.get("value"))
        if key and value:
            folded[key].append(value)
    return folded


def _first(meta: dict[str, list[str]], key: str) -> str | None:
    values = meta.get(key)
    return values[0] if values else None


def _doi(meta: dict[str, list[str]]) -> str | None:
    """`oapen.identifier.doi` first; the `dc.identifier` grab bag as fallback."""
    doi = normalize_doi(_first(meta, "oapen.identifier.doi"))
    if doi:
        return doi
    for candidate in meta.get("dc.identifier", []):
        match = _DOI_RE.search(candidate)
        if match:
            return normalize_doi(match.group(1))
    return None


def _oapen_url(meta: dict[str, list[str]]) -> str | None:
    """The OAPEN Library landing page, when DOAB cross-references one.

    OAPEN is the repository that actually hosts the files for most DOAB
    records; its landing page has the PDF one click away, which is the best
    full-text lead we can give a consumer short of a direct link.
    """
    for candidate in meta.get("dc.identifier", []):
        if "library.oapen.org/handle/" in candidate.lower():
            return candidate
    return None


def _is_pdf_url(url: str) -> bool:
    path = url.split("?", 1)[0].split("#", 1)[0]
    return path.lower().endswith(".pdf")


class DoabProvider(SearchProvider):
    """Keyword search over the Directory of Open Access Books."""

    slug: ClassVar[str] = "doab"
    label: ClassVar[str] = "DOAB"
    covers: ClassVar[str] = (
        "Peer-reviewed open-access scholarly books and chapters — over 100k "
        "records from academic publishers worldwide. The only source here that "
        "finds the book rather than the review of it; strongest in the "
        "humanities and social sciences. Every record is open access."
    )
    needs_key: ClassVar[bool] = False
    key_env: ClassVar[tuple[str, ...]] = ()

    # -- URL construction ---------------------------------------------------

    def _build_url(self, query: str, limit: int, offset: int) -> str:
        params = [
            f"query={quote(query)}",
            "expand=metadata",
            f"limit={limit}",
            f"offset={offset}",
        ]
        return f"{_BASE}?" + "&".join(params)

    # -- Parsing ------------------------------------------------------------

    def _to_paper(self, raw: Any) -> Paper | None:
        item = as_dict(raw)
        # Search results are items in practice, but the same REST shape is
        # shared with communities and collections and a withdrawn item is
        # still returned with the flag set. Neither is a book.
        item_type = as_str(item.get("type"))
        if item_type is not None and item_type != "item":
            return None
        if as_str(item.get("withdrawn")) == "true":
            return None

        meta = _metadata(item)
        title = _first(meta, "dc.title") or as_str(item.get("name"))
        if title is None:
            return None

        handle = as_str(item.get("handle"))
        doi = _doi(meta)
        raw_type = (_first(meta, "dc.type") or "").lower()

        authors = tuple(meta.get("dc.contributor.author", []))
        editors = tuple(meta.get("dc.contributor.editor", []))
        extra: dict[str, str] = {}
        if editors:
            extra["editors"] = "; ".join(editors)
        if not authors and editors:
            authors = editors
            extra["authors_are_editors"] = "true"
        if raw_type:
            extra["doab_type"] = raw_type

        language = _first(meta, "dc.language")
        if language:
            extra["language"] = language
        series = _first(meta, "dc.relation.ispartofseries")
        if series:
            extra["series"] = series
        isbn = _first(meta, "dc.identifier.isbn")
        if isbn:
            extra["isbn"] = isbn
        oapen_url = _oapen_url(meta)
        if oapen_url:
            extra["oapen_url"] = oapen_url

        pdf_url: str | None = None
        download = _first(meta, "oapen.identifier.downloadUrl")
        if download:
            if _is_pdf_url(download):
                pdf_url = download
            else:
                # A DOI or publisher page: full text is there, but a consumer
                # expecting bytes from `pdf_url` would be misled.
                extra["fulltext_url"] = download

        url = _first(meta, "dc.identifier.uri")
        if url is None and handle:
            url = f"{_HANDLE_BASE}{handle}"

        abstract = _first(meta, "dc.description.abstract")
        return Paper(
            title=_WS_RE.sub(" ", title),
            source=self.slug,
            url=url,
            doi=doi,
            year=coerce_year(_first(meta, "dc.date.issued")),
            authors=authors,
            venue=_first(meta, "publisher.name") or _first(meta, "dc.publisher"),
            abstract=_WS_RE.sub(" ", abstract).strip() if abstract else None,
            pdf_url=pdf_url,
            citation_count=None,
            work_type=_TYPE_MAP.get(raw_type, "book"),
            identifier=handle or doi,
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
    ) -> list[Paper]:
        """Up to `limit` books and chapters for `query`, best-effort.

        Pages `_PAGE` at a time and stops at the first short page, so a
        query with three hits costs one request and a broad one costs at
        most `_MAX / _PAGE`. Total by contract: any upstream failure or
        unexpected shape ends the walk and returns what was collected.
        """
        cleaned = _sanitize(query)
        if not cleaned:
            raise ProviderError("DOAB requires a non-empty query")
        wanted = clamp_limit(limit, _MAX)
        headers = {"Accept": "application/json"}

        papers: list[Paper] = []
        offset = 0
        while len(papers) < wanted:
            page = min(_PAGE, wanted - len(papers))
            url = self._build_url(cleaned, page, offset)
            payload = fetch_json(conn, url, fresh=fresh, headers=headers)
            # A bare JSON array is the only success shape. DSpace reports
            # errors as an HTML page (already None by the time it gets here)
            # or, for some routes, a JSON object — neither is a result list.
            if not isinstance(payload, list):
                break
            for raw in payload:
                paper = self._to_paper(raw)
                if paper is not None:
                    papers.append(paper)
            if len(payload) < page:
                break
            offset += len(payload)
        return papers[:wanted]
