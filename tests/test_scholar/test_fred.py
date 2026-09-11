"""FRED series-search provider.

Fixtures follow the St. Louis Fed's documented `fred/series/search` response
(top-level `seriess`, doubled s, per upstream). Beyond parsing, the property
under test is key hygiene: FRED puts the key in the query string, and the
shared cache is keyed by URL, so the provider must never let that URL reach
the cache.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

import pytest

from hyperresearch.scholar import base
from hyperresearch.scholar.providers.fred import FredProvider

KEY = "abcdef0123456789abcdef0123456789"

GDPC1: dict[str, Any] = {
    "id": "GDPC1",
    "realtime_start": "2026-09-11",
    "realtime_end": "2026-09-11",
    "title": "Real Gross Domestic Product",
    "observation_start": "1947-01-01",
    "observation_end": "2026-04-01",
    "frequency": "Quarterly",
    "frequency_short": "Q",
    "units": "Billions of Chained 2017 Dollars",
    "units_short": "Bil. of Chn. 2017 $",
    "seasonal_adjustment": "Seasonally Adjusted Annual Rate",
    "seasonal_adjustment_short": "SAAR",
    "last_updated": "2026-08-28 07:46:02-05",
    "popularity": 92,
    "group_popularity": 93,
    "notes": "BEA Account Code: A191RX. Real gross domestic product is the inflation adjusted value.",
}

UNRATE: dict[str, Any] = {
    "id": "UNRATE",
    "realtime_start": "2026-09-11",
    "realtime_end": "2026-09-11",
    "title": "Unemployment Rate",
    "observation_start": "1948-01-01",
    "observation_end": "2026-08-01",
    "frequency": "Monthly",
    "frequency_short": "M",
    "units": "Percent",
    "units_short": "%",
    "seasonal_adjustment": "Seasonally Adjusted",
    "seasonal_adjustment_short": "SA",
    "last_updated": "2026-09-05 07:44:01-05",
    "popularity": 95,
    "group_popularity": 95,
}


def _envelope(*rows: Any) -> str:
    return json.dumps(
        {
            "realtime_start": "2026-09-11",
            "realtime_end": "2026-09-11",
            "order_by": "search_rank",
            "sort_order": "desc",
            "count": len(rows),
            "offset": 0,
            "limit": 1000,
            "seriess": list(rows),
        }
    )


def _serve(monkeypatch: pytest.MonkeyPatch, body: str | None) -> list[str]:
    seen: list[str] = []

    def fake_get(url: str, headers: dict[str, str] | None = None) -> str | None:
        seen.append(url)
        return body

    monkeypatch.setattr(base, "_http_get", fake_get)
    return seen


@pytest.fixture
def with_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FRED_API_KEY", KEY)


@pytest.fixture
def without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FRED_API_KEY", raising=False)


# --- key gate ----------------------------------------------------------------


def test_unavailable_without_key(without_key: None) -> None:
    provider = FredProvider()
    assert provider.slug == "fred"
    assert provider.needs_key is True
    assert provider.key_env == ("FRED_API_KEY",)
    assert provider.available() is False
    reason = provider.unavailable_reason()
    assert reason is not None
    assert "FRED_API_KEY" in reason


def test_no_request_without_key(monkeypatch: pytest.MonkeyPatch, without_key: None) -> None:
    urls = _serve(monkeypatch, _envelope(GDPC1))
    assert FredProvider().search(None, "gdp", 5) == []
    assert urls == []


def test_available_with_key(with_key: None) -> None:
    provider = FredProvider()
    assert provider.available() is True
    assert provider.unavailable_reason() is None


# --- parsing -----------------------------------------------------------------


def test_parses_a_series(monkeypatch: pytest.MonkeyPatch, with_key: None) -> None:
    urls = _serve(monkeypatch, _envelope(GDPC1))
    papers = FredProvider().search(None, "real gdp", 5)

    assert len(papers) == 1
    paper = papers[0]
    assert paper.work_type == "series"
    assert paper.source == "fred"
    assert paper.identifier == "GDPC1"
    assert paper.title == "Real Gross Domestic Product (1947-01-01 to 2026-04-01)"
    assert paper.url == "https://fred.stlouisfed.org/series/GDPC1"
    assert paper.venue == "Federal Reserve Economic Data"
    assert paper.year == 1947
    assert paper.abstract is not None and paper.abstract.startswith("BEA Account Code")
    assert paper.extra["series_id"] == "GDPC1"
    assert paper.extra["frequency"] == "Quarterly"
    assert paper.extra["units"] == "Billions of Chained 2017 Dollars"
    assert paper.extra["seasonal_adjustment"] == "Seasonally Adjusted Annual Rate"
    assert paper.extra["observation_start"] == "1947-01-01"
    assert paper.extra["observation_end"] == "2026-04-01"
    assert paper.extra["last_updated"] == "2026-08-28 07:46:02-05"
    assert paper.extra["popularity"] == "92"

    assert len(urls) == 1
    assert urls[0].startswith("https://api.stlouisfed.org/fred/series/search?")
    assert "search_text=real%20gdp" in urls[0]
    assert "file_type=json" in urls[0]
    assert "limit=5" in urls[0]
    assert f"api_key={KEY}" in urls[0]


def test_series_without_notes_has_no_abstract(
    monkeypatch: pytest.MonkeyPatch, with_key: None
) -> None:
    _serve(monkeypatch, _envelope(UNRATE))
    papers = FredProvider().search(None, "unemployment", 5)
    assert papers[0].abstract is None
    assert papers[0].extra["frequency"] == "Monthly"


def test_title_without_window_when_dates_missing(
    monkeypatch: pytest.MonkeyPatch, with_key: None
) -> None:
    row = {"id": "X1", "title": "Some Series", "observation_start": "2001-01-01"}
    _serve(monkeypatch, _envelope(row))
    papers = FredProvider().search(None, "some", 5)
    assert papers[0].title == "Some Series"
    assert papers[0].year == 2001


def test_limit_is_honored(monkeypatch: pytest.MonkeyPatch, with_key: None) -> None:
    _serve(monkeypatch, _envelope(GDPC1, UNRATE))
    assert len(FredProvider().search(None, "rate", 1)) == 1


@pytest.mark.parametrize(
    "row",
    [
        pytest.param({"title": "No id"}, id="missing-id"),
        pytest.param({"id": "NOTITLE"}, id="missing-title"),
        pytest.param({"id": "", "title": "Blank id"}, id="blank-id"),
        pytest.param("GDPC1", id="not-a-dict"),
        pytest.param(None, id="null-row"),
    ],
)
def test_unusable_rows_are_dropped(
    monkeypatch: pytest.MonkeyPatch, with_key: None, row: Any
) -> None:
    _serve(monkeypatch, _envelope(row, UNRATE))
    assert [p.identifier for p in FredProvider().search(None, "x", 5)] == ["UNRATE"]


# --- key hygiene -------------------------------------------------------------


def test_key_never_reaches_the_url_cache(monkeypatch: pytest.MonkeyPatch, with_key: None) -> None:
    """A vault connection is offered and must be ignored.

    `base.fetch_text` writes every successful uncached fetch into `api_cache`
    keyed by URL. For FRED that URL carries the key, so a provider that forwards
    `conn` leaks the key into the vault database.
    """
    _serve(monkeypatch, _envelope(GDPC1))
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE api_cache (url TEXT PRIMARY KEY, body TEXT, fetched_at TEXT)")

    papers = FredProvider().search(conn, "real gdp", 5)
    assert len(papers) == 1

    rows = conn.execute("SELECT url FROM api_cache").fetchall()
    assert rows == []


def test_key_never_appears_in_result_fields(
    monkeypatch: pytest.MonkeyPatch, with_key: None
) -> None:
    _serve(monkeypatch, _envelope(GDPC1))
    paper = FredProvider().search(None, "real gdp", 5)[0]
    assert KEY not in json.dumps(paper.to_dict())


# --- failure paths -----------------------------------------------------------


def test_upstream_unreachable_returns_empty(
    monkeypatch: pytest.MonkeyPatch, with_key: None
) -> None:
    _serve(monkeypatch, None)
    assert FredProvider().search(None, "gdp", 5) == []


def test_malformed_json_returns_empty(monkeypatch: pytest.MonkeyPatch, with_key: None) -> None:
    _serve(monkeypatch, "Bad Request.  The value for variable api_key is not a 32 character")
    assert FredProvider().search(None, "gdp", 5) == []


@pytest.mark.parametrize(
    "body",
    [
        pytest.param("[]", id="top-level-list"),
        pytest.param('{"seriess": null}', id="null-seriess"),
        pytest.param('{"seriess": {}}', id="seriess-wrong-type"),
        pytest.param('{"series": [{"id": "GDPC1", "title": "x"}]}', id="single-s-key"),
        pytest.param('{"error_code": 400, "error_message": "Bad Request."}', id="api-error"),
    ],
)
def test_unexpected_shapes_return_empty(
    monkeypatch: pytest.MonkeyPatch, with_key: None, body: str
) -> None:
    _serve(monkeypatch, body)
    assert FredProvider().search(None, "gdp", 5) == []


def test_blank_query_makes_no_request(monkeypatch: pytest.MonkeyPatch, with_key: None) -> None:
    urls = _serve(monkeypatch, _envelope(GDPC1))
    assert FredProvider().search(None, "   ", 5) == []
    assert urls == []
