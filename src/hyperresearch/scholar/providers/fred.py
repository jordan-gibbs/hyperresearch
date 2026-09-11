"""FRED — Federal Reserve Economic Data series search (St. Louis Fed).

An argument about inflation, employment or credit conditions that cites only
commentary is citing people describing a number. FRED is where the number
itself lives: roughly 800k time series from the BLS, BEA, Census, Treasury and
the Fed itself, each with a stable id, a stated frequency, stated units and a
stated seasonal adjustment. Those four attributes are how you tell whether two
people quoting "unemployment" are quoting the same thing. These records are
`work_type="series"`.

A key is required — self-service from the St. Louis Fed — and read from FRED_API_KEY.

KEY HYGIENE
-----------
FRED authenticates by query parameter; there is no header form. That collides
with the shared cache in `base`, which is keyed BY URL, so caching a FRED
request would write the user's key into the vault's `api_cache` table in
plaintext where it would survive every later read of that database. This
provider therefore always calls `fetch_json` with `conn=None`: no cached URL
ever contains the key. The cost is one uncached request per search, which the
per-host courtesy delay already paces. Nothing here ever puts the request URL
into a message, an exception or a log for the same reason.

Endpoint, parameters and response shape are per the St. Louis Fed's own
documentation for `fred/series/search` (top-level `seriess` array — the
doubled "s" is upstream's, not a typo). Not exercised against the live API
during development: no key was present on the machine.
"""

from __future__ import annotations

import sqlite3
from typing import Any, ClassVar
from urllib.parse import quote

from hyperresearch.scholar.base import (
    Paper,
    SearchProvider,
    clamp_limit,
    coerce_year,
    fetch_json,
)

_BASE = "https://api.stlouisfed.org/fred/series/search"

# Upstream's documented ceiling for `limit`.
_MAX_LIMIT = 1000

_VENUE = "Federal Reserve Economic Data"

# Fields copied verbatim into `extra` when present. These are the attributes
# that decide whether a series answers the question asked of it — a monthly
# seasonally-adjusted index and an annual raw level are not interchangeable
# even when their titles match.
_EXTRA_FIELDS: tuple[tuple[str, str], ...] = (
    ("frequency", "frequency"),
    ("units", "units"),
    ("seasonal_adjustment", "seasonal_adjustment"),
    ("observation_start", "observation_start"),
    ("observation_end", "observation_end"),
    ("last_updated", "last_updated"),
)


def _text(mapping: dict[str, Any], key: str) -> str | None:
    value = mapping.get(key)
    if not isinstance(value, str):
        return None
    return value.strip() or None


class FredProvider(SearchProvider):
    """Economic time series by full-text search over series titles and notes."""

    slug: ClassVar[str] = "fred"
    label: ClassVar[str] = "FRED"
    covers: ClassVar[str] = (
        "U.S. and international economic time series — frequency, units, "
        "seasonal adjustment, coverage window. Requires FRED_API_KEY."
    )
    needs_key: ClassVar[bool] = True
    key_env: ClassVar[tuple[str, ...]] = ("FRED_API_KEY",)

    def search(
        self,
        conn: sqlite3.Connection | None,
        query: str,
        limit: int,
        *,
        fresh: bool = False,
    ) -> list[Paper]:
        term = query.strip()
        key = self.api_key()
        if not term or not key:
            return []
        ceiling = clamp_limit(limit, _MAX_LIMIT)
        url = (
            f"{_BASE}?search_text={quote(term)}&api_key={quote(key)}&file_type=json&limit={ceiling}"
        )
        # conn is deliberately dropped, not forwarded: see KEY HYGIENE above.
        # `fresh` is accepted for interface parity and is a no-op without a
        # cache to bypass.
        payload = fetch_json(None, url)
        if not isinstance(payload, dict):
            return []
        rows = payload.get("seriess")
        if not isinstance(rows, list):
            return []

        papers: list[Paper] = []
        for row in rows:
            paper = self._to_paper(row)
            if paper is not None:
                papers.append(paper)
            if len(papers) >= ceiling:
                break
        return papers

    def _to_paper(self, row: Any) -> Paper | None:
        if not isinstance(row, dict):
            return None
        series_id = _text(row, "id")
        title = _text(row, "title")
        if not series_id or not title:
            return None

        extra: dict[str, str] = {"series_id": series_id}
        for field_name, extra_key in _EXTRA_FIELDS:
            value = _text(row, field_name)
            if value:
                extra[extra_key] = value
        popularity = row.get("popularity")
        if isinstance(popularity, int):
            extra["popularity"] = str(popularity)

        # The coverage window is what distinguishes two same-named series, so
        # it belongs where a scannable result list will show it.
        start = extra.get("observation_start")
        end = extra.get("observation_end")
        display_title = f"{title} ({start} to {end})" if start and end else title

        return Paper(
            title=display_title,
            source=self.slug,
            url=f"https://fred.stlouisfed.org/series/{series_id}",
            # A series has no publication year; the first observation is the
            # only date that describes the record rather than today's refresh.
            year=coerce_year(start),
            venue=_VENUE,
            abstract=_text(row, "notes"),
            work_type="series",
            identifier=series_id,
            extra=extra,
        )
