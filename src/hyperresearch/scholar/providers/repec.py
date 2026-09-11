"""RePEc — Research Papers in Economics. Registered here; not searchable.

RePEc is the canonical index of economics working papers: the NBER, CEPR,
IZA, central-bank and departmental series that the discipline circulates
years before (and often instead of) journal publication. It is exactly the
corpus the article-shaped APIs in this package index worst, which is why the
registry reserves a slot for it. This module holds that slot honestly.

WHAT ACCESS ACTUALLY EXISTS (verified 2026-09-11)
-------------------------------------------------
* **`https://api.repec.org/call.cgi?code=<code>&<method>=<id>`** is the one
  programmatic interface. It is live (the bare host answers with a pointer to
  the docs; a bad code answers `[{"error": 2}]`). An access code is granted
  by emailing the RePEc maintainer with a stated purpose, IP address and call
  frequency; it is IP-bound and expires. The CRAN `repec` package establishes
  `REPEC_API_KEY` as the conventional environment variable, which we adopt.
* **Every documented method is a lookup by identifier** — `getref` and
  `getauthorsforitem` by RePEc handle, `getauthorrecordfull`, `gethindex`
  and friends by author Short-ID, `getinstrecord` by institution handle,
  `getpubsfromwpseries` by series. The documentation states it outright:
  *"Note that there is no search function through the API."*
  (https://ideas.repec.org/api.html)
* **Bulk routes exist; none of them search.** RePEc's "getting the data"
  page (https://ideas.repec.org/getdata.html) lists ReDIF and AMF dumps over
  FTP, rsync, and an OAI-PMH host at `oai.repec.org` that the page itself
  labels "sometimes flaky" (it answered 502 when checked). OAI-PMH is a
  harvesting protocol with date and set selectors only, so even when it is
  up it cannot serve a keyword query. The IDEAS and EconPapers front ends
  have HTML search forms and no API, and both disallow robots on the paths
  those forms post to (`/cgi-bin/` and `/scripts/` respectively).

So a keyword search — the only operation `SearchProvider` exists to serve —
cannot be built on RePEc today, with or without a key. This provider
therefore reports itself unavailable unconditionally and explains why, so
`hpr scholar sources` tells the user the truth rather than "set a key" that
would not help. `search()` returns [] by the total-function contract; the
registry never routes a query here because `available()` is False.

WHY KEEP THE MODULE AT ALL
--------------------------
The registry imports it, the coverage gap it names is real, and the IDEAS
page says functions are added "as demand for them materializes". If RePEc
ships a search method, `_SEARCH_METHOD` is the one line that unlocks the
availability check, and the call shape and key handling are already right.
The response shape of that future method is unknown, so no parser is
written for it — a parser for an invented payload would be worse than none.

For economics discovery in the meantime, OpenAlex and Crossref cover the
DOI-bearing working-paper series (NBER, most central banks); CORE covers
repository-deposited copies. The genuinely RePEc-only tail — series with no
DOI and no institutional repository — remains a known gap.
"""

from __future__ import annotations

import sqlite3
from typing import ClassVar

from hyperresearch.scholar.base import Paper, SearchProvider

_BASE = "https://api.repec.org/call.cgi"
_DOCS = "https://ideas.repec.org/api.html"

# Name of the RePEc API method that performs a keyword search. None because
# no such method exists — see the module docstring. Set this (and write the
# parser against the real payload) when RePEc adds one.
_SEARCH_METHOD: str | None = None


class RePEcProvider(SearchProvider):
    """Economics working papers via RePEc — currently not searchable upstream."""

    slug: ClassVar[str] = "repec"
    label: ClassVar[str] = "RePEc"
    covers: ClassVar[str] = (
        "Economics working papers (NBER, CEPR, IZA, central banks, departmental "
        "series) — the canonical index for the field. NOT searchable: RePEc's "
        "API offers per-identifier lookups only and documents that it has no "
        "search function, so this source cannot answer queries yet."
    )
    needs_key: ClassVar[bool] = True
    key_env: ClassVar[tuple[str, ...]] = ("REPEC_API_KEY",)

    def available(self) -> bool:
        """False until RePEc exposes a search method, key or no key.

        The base-class rule (available iff the key is present) would tell a
        user that setting `REPEC_API_KEY` unlocks this source. It does not,
        and a false promise here costs the user an email to the RePEc
        maintainer for nothing.
        """
        return _SEARCH_METHOD is not None and super().available()

    def unavailable_reason(self) -> str | None:
        if self.available():
            return None
        if _SEARCH_METHOD is None:
            return (
                f"{self.label}: the RePEc API has no search function "
                f"(per-identifier lookups only; see {_DOCS}). Economics working "
                "papers with DOIs are still reachable through openalex and crossref."
            )
        return super().unavailable_reason()

    def search(
        self,
        conn: sqlite3.Connection | None,
        query: str,
        limit: int,
        *,
        fresh: bool = False,
    ) -> list[Paper]:
        """Always [] — there is no upstream search to call.

        Kept total rather than raising: the registry already filters this
        provider out via `available()`, and a caller that reaches it anyway
        gets the reason from `unavailable_reason()`, not an exception.
        """
        return []
