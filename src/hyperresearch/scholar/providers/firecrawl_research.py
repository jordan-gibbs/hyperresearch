"""Firecrawl Research Index — natural-language search over ~43M paper abstracts.

The index (https://docs.firecrawl.dev/features/research) holds PubMed, PMC,
bioRxiv and medRxiv for the life sciences plus arXiv for physics, mathematics
and computer science. It is built for agent retrieval: the query is a question
in prose, not a keyword string. It is not a replacement for OpenAlex. It has no
humanities, social science or books, and its hits are thin (see below), so it
runs alongside the metadata indexes and merges into them by DOI.

No key is needed. When `FIRECRAWL_API_KEY` is set it is sent as a bearer token,
which moves requests from the per-IP keyless allowance to the account's limits.

UPSTREAM QUIRKS
---------------
* **Search hits carry no authors, year or venue**: only ids, title, abstract and
  a relevance score. Fetching every hit's metadata would multiply requests by
  the result count, so this provider returns what the hit holds and the merge
  fills the rest from OpenAlex and Crossref, which match on DOI. The year is
  recovered where an identifier encodes it: arXiv ids (YYMM) and dated
  bioRxiv/medRxiv DOIs (`10.1101/YYYY.MM.DD.…`).
* **A record can carry two DOIs**, the bioRxiv/medRxiv preprint (`10.1101/…`)
  and the published article, in either order. The published DOI is what every
  other provider reports, and the merge never joins records whose DOIs differ,
  so the published one wins and the preprint DOI goes to `extra`.
* **`primaryId` is namespaced** (`arxiv:`, `pmid:`, `pmcid:`, `doi:`) and is kept
  as `identifier`: it is what the index's paper-read and related-paper
  endpoints accept.
* **PubMed abstracts arrive truncated**, ending in an ellipsis.
"""

from __future__ import annotations

import re
import sqlite3
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
    fetch_json,
    normalize_doi,
)

_BASE = "https://api.firecrawl.dev/v2/search/research/papers"

# The endpoint's `k` ceiling.
MAX_K = 500

# Cold Spring Harbor's prefix, shared by bioRxiv and medRxiv.
_PREPRINT_DOI_PREFIX = "10.1101/"
_DATED_PREPRINT_DOI = re.compile(r"^10\.1101/(\d{4})\.\d{2}\.\d{2}\.")
_ARXIV_NEW_ID = re.compile(r"^(\d{2})(\d{2})\.\d{4,5}(?:v\d+)?$")
_ARXIV_OLD_ID = re.compile(r"^[a-z][a-z.-]*/(\d{2})(\d{2})\d{3}(?:v\d+)?$", re.IGNORECASE)


def _ids(record: dict[str, Any], namespace: str) -> list[str]:
    """Every id in one namespace, `primaryId` first when it is in that namespace."""
    values = [
        text for text in (as_str(v) for v in as_list(as_dict(record.get("ids")).get(namespace)))
        if text
    ]
    primary = as_str(record.get("primaryId"))
    if primary and primary.lower().startswith(namespace + ":"):
        value = primary.split(":", 1)[1].strip()
        if value:
            values = [value] + [v for v in values if v != value]
    return values


def _arxiv_year(arxiv_id: str) -> int | None:
    """Submission year encoded in an arXiv id: `YYMM.NNNNN`, or `archive/YYMMNNN` before 2007."""
    match = _ARXIV_NEW_ID.match(arxiv_id)
    if match:
        return 2000 + int(match.group(1))
    match = _ARXIV_OLD_ID.match(arxiv_id)
    if match:
        yy = int(match.group(1))
        # The old scheme ran from August 1991 to March 2007.
        return 1900 + yy if yy >= 91 else 2000 + yy
    return None


class FirecrawlResearchProvider(SearchProvider):
    """Paper search over the Firecrawl Research Index."""

    slug: ClassVar[str] = "firecrawl"
    label: ClassVar[str] = "Firecrawl Research Index"
    covers: ClassVar[str] = (
        "~43M paper abstracts: PubMed, PMC, bioRxiv and medRxiv for the life sciences, "
        "arXiv for physics, mathematics and computer science. Natural-language queries. "
        "Hits carry no authors or venue and merge into OpenAlex/Crossref records by DOI; "
        "no humanities, social science or books."
    )
    needs_key: ClassVar[bool] = False
    key_env: ClassVar[tuple[str, ...]] = ("FIRECRAWL_API_KEY",)

    def _to_paper(self, raw: Any) -> Paper | None:
        record = as_dict(raw)
        title = as_str(record.get("title"))
        if title is None:
            return None

        dois = [d for d in (normalize_doi(v) for v in _ids(record, "doi")) if d]
        published = [d for d in dois if not d.startswith(_PREPRINT_DOI_PREFIX)]
        preprints = [d for d in dois if d.startswith(_PREPRINT_DOI_PREFIX)]
        doi = published[0] if published else (preprints[0] if preprints else None)
        arxiv = _ids(record, "arxiv")
        pmcids = [v if v.upper().startswith("PMC") else f"PMC{v}" for v in _ids(record, "pmcid")]
        pmids = _ids(record, "pmid")

        is_preprint = bool(arxiv) or (not published and bool(preprints))
        year = _arxiv_year(arxiv[0]) if arxiv else None
        if year is None and not published:
            for candidate in preprints:
                match = _DATED_PREPRINT_DOI.match(candidate)
                if match:
                    year = int(match.group(1))
                    break

        pdf_url = None
        if arxiv:
            url: str | None = f"https://arxiv.org/abs/{arxiv[0]}"
            pdf_url = f"https://arxiv.org/pdf/{arxiv[0]}"
        elif pmcids:
            url = f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcids[0]}/"
        elif doi:
            url = f"https://doi.org/{doi}"
        elif pmids:
            url = f"https://pubmed.ncbi.nlm.nih.gov/{pmids[0]}/"
        else:
            url = None

        extra: dict[str, str] = {}
        paper_id = as_str(record.get("paperId"))
        if paper_id:
            extra["firecrawl_paper_id"] = paper_id
        score = record.get("score")
        if isinstance(score, (int, float)) and not isinstance(score, bool):
            extra["relevance"] = f"{score:.4f}"
        if arxiv:
            extra["arxiv_id"] = arxiv[0]
        if pmids:
            extra["pmid"] = pmids[0]
        if pmcids:
            extra["pmcid"] = pmcids[0]
        if published and preprints:
            extra["preprint_doi"] = preprints[0]

        return Paper(
            title=title,
            source=self.slug,
            url=url,
            doi=doi,
            year=year,
            venue="arXiv" if arxiv and not published else None,
            abstract=as_str(record.get("abstract")),
            pdf_url=pdf_url,
            work_type="preprint" if is_preprint else "article",
            identifier=as_str(record.get("primaryId")),
            extra=extra,
        )

    def search(
        self,
        conn: sqlite3.Connection | None,
        query: str,
        limit: int,
        *,
        fresh: bool = False,
    ) -> list[Paper]:
        """Up to `limit` papers for `query`, best-effort; [] on any upstream failure."""
        if not query.strip():
            raise ProviderError("Firecrawl Research Index requires a non-empty query")
        url = f"{_BASE}?query={quote(query.strip())}&k={clamp_limit(limit, MAX_K)}"
        key = self.api_key()
        headers = {"Authorization": f"Bearer {key}"} if key else None

        payload = as_dict(fetch_json(conn, url, fresh=fresh, headers=headers))
        if payload.get("success") is False:
            return []
        results = payload.get("results")
        if not isinstance(results, list):
            return []

        papers: list[Paper] = []
        for item in results:
            paper = self._to_paper(item)
            if paper is not None:
                papers.append(paper)
        return papers
