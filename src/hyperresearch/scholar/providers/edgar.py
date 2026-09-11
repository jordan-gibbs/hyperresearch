"""SEC EDGAR — full-text search over U.S. regulatory filings.

What a company tells its regulator is a different evidentiary class from what
it tells a journalist. A 10-K risk factor, an 8-K disclosure or a proxy
statement is a signed, dated, legally-consequential claim, and a corpus about
an industry is weaker for citing only the press coverage of one. These records
are `work_type="filing"`.

ENDPOINT
--------
`https://efts.sec.gov/LATEST/search-index?q=<query>` — the JSON backend behind
the EDGAR full-text search UI, covering filings from 2001 onward. No key. This
path has moved before, so it was reconfirmed live on 2026-09-11: it answers
200 with an Elasticsearch-shaped body (`hits.hits[]._source`).

THE CONTACT-ADDRESS REQUIREMENT
-------------------------------
The SEC's fair-access policy requires every automated request to declare a
User-Agent identifying the requester with a contact address, and the block is
real rather than advisory: verified on 2026-09-11, the endpoint returns 403
for a request with no User-Agent, 403 for a generic library User-Agent, and
403 for this project's own default User-Agent, which carries no address. Only
the `mailto:`-bearing form gets a 200.

`base.user_agent()` appends that mailto only when HYPERRESEARCH_CONTACT_EMAIL
is set, so without it this provider cannot work at all. It therefore reports
itself unavailable (the registry then skips it and surfaces the reason) and
`search()` returns [] without making a request. Hammering an endpoint that is
guaranteed to 403 is exactly the behavior the policy exists to stop.

UPSTREAM QUIRKS
---------------
* EFTS indexes DOCUMENTS, not filings. One 10-K with a dozen exhibits is a
  dozen hits sharing one accession number, so a raw result list is mostly the
  same filing repeated. Results are deduplicated by accession below, keeping
  the highest-scoring document — that is the one whose text actually matched.
* Page size is fixed at 100 and there is no size parameter (`size=` and
  `hits=` are ignored). Larger limits would need `from=` offset paging; see
  `_MAX_RESULTS`.
* `_id` is `"<accession>:<filename>"`. The filename is the only route to the
  document itself — `_source` names the filing but not the file.
"""

from __future__ import annotations

import re
import sqlite3
from typing import Any, ClassVar
from urllib.parse import quote

from hyperresearch.scholar.base import (
    Paper,
    SearchProvider,
    clamp_limit,
    coerce_year,
    contact_email,
    fetch_json,
)

_FTS_URL = "https://efts.sec.gov/LATEST/search-index"

# One EFTS page is 100 documents and the endpoint exposes no page-size knob.
# Discovery never needs more than one page of filings, so we take the ceiling
# rather than add an offset-paging loop that would multiply requests against a
# rate-limited public endpoint.
_MAX_RESULTS = 100

_WS_RE = re.compile(r"\s+")


def _first_string(value: Any) -> str | None:
    """First non-empty string from a scalar or a list. EFTS uses both shapes."""
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str) and item.strip():
                return item.strip()
    return None


def _tidy(value: str) -> str:
    """Collapse runs of whitespace.

    `display_names` arrives with doubled spaces around the ticker and CIK
    parentheticals, which survive into a title and look like a bug.
    """
    return _WS_RE.sub(" ", value).strip()


def _archive_url(accession: str, cik: str | None, document: str | None) -> str | None:
    """Canonical URL for a filing document, or its index page as a fallback.

    The archive path wants the CIK with leading zeros stripped and the
    accession number with its dashes stripped — but the index filename keeps
    the dashes. Getting either wrong yields a 404, so both forms are built
    here rather than at the call sites.
    """
    if not cik:
        return None
    try:
        cik_number = int(cik)
    except ValueError:
        return None
    folder = accession.replace("-", "")
    base = f"https://www.sec.gov/Archives/edgar/data/{cik_number}/{folder}"
    if document:
        return f"{base}/{document}"
    return f"{base}/{accession}-index.htm"


class EdgarProvider(SearchProvider):
    """Full-text search over EDGAR filings. Needs a contact address, not a key."""

    slug: ClassVar[str] = "edgar"
    label: ClassVar[str] = "SEC EDGAR"
    covers: ClassVar[str] = (
        "Full text of U.S. SEC filings since 2001 — 10-K, 10-Q, 8-K, S-1, "
        "proxies, exhibits. No key, but requires HYPERRESEARCH_CONTACT_EMAIL."
    )
    # No API key exists for this endpoint; the gate is a contact address, so
    # availability is overridden below rather than expressed through key_env.
    needs_key: ClassVar[bool] = False
    key_env: ClassVar[tuple[str, ...]] = ()

    def available(self) -> bool:
        return contact_email() is not None

    def unavailable_reason(self) -> str | None:
        if self.available():
            return None
        return (
            "SEC EDGAR: set HYPERRESEARCH_CONTACT_EMAIL — the SEC rejects "
            "requests whose User-Agent carries no contact address (HTTP 403)"
        )

    def search(
        self,
        conn: sqlite3.Connection | None,
        query: str,
        limit: int,
        *,
        fresh: bool = False,
    ) -> list[Paper]:
        term = query.strip()
        if not term or not self.available():
            return []
        ceiling = clamp_limit(limit, _MAX_RESULTS)
        url = f"{_FTS_URL}?q={quote(term)}"
        payload = fetch_json(conn, url, fresh=fresh)
        if not isinstance(payload, dict):
            return []
        hits = payload.get("hits")
        rows = hits.get("hits") if isinstance(hits, dict) else None
        if not isinstance(rows, list):
            return []

        papers: list[Paper] = []
        seen: set[str] = set()
        for row in rows:
            paper = self._to_paper(row)
            if paper is None or paper.identifier in seen:
                continue
            # identifier is the accession number and is never None here; the
            # guard above already dropped rows without one.
            seen.add(str(paper.identifier))
            papers.append(paper)
            if len(papers) >= ceiling:
                break
        return papers

    def _to_paper(self, row: Any) -> Paper | None:
        if not isinstance(row, dict):
            return None
        source = row.get("_source")
        if not isinstance(source, dict):
            return None

        # `_id` is "<accession>:<filename>". `_source.adsh` carries the same
        # accession and is preferred; the `_id` prefix is the fallback for
        # rows where it is missing.
        document: str | None = None
        raw_id = row.get("_id")
        id_accession: str | None = None
        if isinstance(raw_id, str) and raw_id.strip():
            head, _, tail = raw_id.strip().partition(":")
            id_accession = head or None
            document = tail or None
        accession = _first_string(source.get("adsh")) or id_accession
        if not accession:
            return None

        company = _first_string(source.get("display_names"))
        company = _tidy(company) if company else None
        form = _first_string(source.get("form")) or _first_string(source.get("root_forms"))
        filed = _first_string(source.get("file_date"))
        cik = _first_string(source.get("ciks"))
        description = _first_string(source.get("file_description"))

        # EDGAR filings have no titles, so one is composed. Company plus form
        # plus date is what a reader needs to recognize the citation; without
        # it the entry reads as a bare accession number.
        parts = [p for p in (company, form) if p]
        title = " — ".join(parts) if parts else f"SEC filing {accession}"
        if filed:
            title = f"{title} (filed {filed})"

        extra: dict[str, str] = {"accession": accession}
        if form:
            extra["form"] = form
        if company:
            extra["company"] = company
        if cik:
            extra["cik"] = cik
        if filed:
            extra["filed"] = filed
        if description:
            extra["file_description"] = description
        period = _first_string(source.get("period_ending"))
        if period:
            extra["period_ending"] = period

        return Paper(
            title=title,
            source=self.slug,
            url=_archive_url(accession, cik, document),
            year=coerce_year(filed),
            venue="U.S. Securities and Exchange Commission (EDGAR)",
            # EFTS returns matched metadata, never a text snippet, so there is
            # no honest abstract to report. The document itself is at `url`.
            abstract=None,
            work_type="filing",
            identifier=accession,
            extra=extra,
        )
