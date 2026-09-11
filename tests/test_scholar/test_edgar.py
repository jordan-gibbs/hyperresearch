"""SEC EDGAR full-text search provider.

Fixtures are trimmed from a real `efts.sec.gov/LATEST/search-index` response
(Elasticsearch envelope, one hit per DOCUMENT). The two behaviors that matter
most here are the contact-address gate — the SEC 403s any request without one,
so the provider must not make the request — and deduplication of the several
exhibit hits a single filing produces.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from hyperresearch.scholar import base
from hyperresearch.scholar.providers.edgar import EdgarProvider

CONTACT = "research@example.org"


def _hit(
    doc_id: str,
    score: float,
    *,
    adsh: str | None = "0001161697-21-000289",
    form: str = "10-K",
    file_date: str = "2021-06-01",
    cik: str = "0001498148",
    file_type: str = "10-K",
    description: str | None = "FORM 10-K ANNUAL REPORT FOR 02-28-2021",
) -> dict[str, Any]:
    source: dict[str, Any] = {
        "ciks": [cik],
        "period_ending": "2021-02-28",
        "file_num": ["000-55079"],
        # Real payloads carry doubled spaces around the parentheticals.
        "display_names": [
            "Artificial Intelligence Technology Solutions Inc.  (AITX)  (CIK 0001498148)"
        ],
        "xsl": None,
        "sequence": 1,
        "root_forms": [form.split("/")[0]],
        "file_date": file_date,
        "biz_states": ["NV"],
        "sics": ["3714"],
        "form": form,
        "film_num": ["21982165"],
        "biz_locations": ["Reno, NV"],
        "file_type": file_type,
        "inc_states": ["NV"],
        "items": [],
    }
    if adsh is not None:
        source["adsh"] = adsh
    if description is not None:
        source["file_description"] = description
    return {"_index": "edgar_file", "_id": doc_id, "_score": score, "_source": source}


def _envelope(*hits: Any) -> str:
    return json.dumps(
        {
            "took": 12,
            "timed_out": False,
            "hits": {"total": {"value": len(hits), "relation": "eq"}, "hits": list(hits)},
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
def with_contact(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HYPERRESEARCH_CONTACT_EMAIL", CONTACT)


@pytest.fixture
def without_contact(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HYPERRESEARCH_CONTACT_EMAIL", raising=False)


# --- the contact-address gate ------------------------------------------------


def test_unavailable_without_contact_email(without_contact: None) -> None:
    provider = EdgarProvider()
    assert provider.available() is False
    reason = provider.unavailable_reason()
    assert reason is not None
    assert "HYPERRESEARCH_CONTACT_EMAIL" in reason
    assert "403" in reason


def test_no_request_is_made_without_contact_email(
    monkeypatch: pytest.MonkeyPatch, without_contact: None
) -> None:
    urls = _serve(monkeypatch, _envelope(_hit("0001161697-21-000289:form_10-k.htm", 18.4)))
    assert EdgarProvider().search(None, "artificial intelligence", 5) == []
    assert urls == []


def test_blank_contact_email_counts_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HYPERRESEARCH_CONTACT_EMAIL", "   ")
    assert EdgarProvider().available() is False


def test_available_with_contact_email(with_contact: None) -> None:
    provider = EdgarProvider()
    assert provider.slug == "edgar"
    assert provider.needs_key is False
    assert provider.available() is True
    assert provider.unavailable_reason() is None


# --- parsing -----------------------------------------------------------------


def test_parses_a_filing(monkeypatch: pytest.MonkeyPatch, with_contact: None) -> None:
    urls = _serve(monkeypatch, _envelope(_hit("0001161697-21-000289:form_10-k.htm", 18.4)))
    papers = EdgarProvider().search(None, '"artificial intelligence"', 5)

    assert len(papers) == 1
    paper = papers[0]
    assert paper.work_type == "filing"
    assert paper.source == "edgar"
    assert paper.identifier == "0001161697-21-000289"
    assert paper.year == 2021
    assert paper.abstract is None
    assert paper.venue == "U.S. Securities and Exchange Commission (EDGAR)"
    # CIK loses its leading zeros, the accession folder loses its dashes.
    assert paper.url == (
        "https://www.sec.gov/Archives/edgar/data/1498148/000116169721000289/form_10-k.htm"
    )
    # Doubled spaces from display_names are collapsed in the composed title.
    assert paper.title == (
        "Artificial Intelligence Technology Solutions Inc. (AITX) (CIK 0001498148)"
        " — 10-K (filed 2021-06-01)"
    )
    assert paper.extra["form"] == "10-K"
    assert paper.extra["cik"] == "0001498148"
    assert paper.extra["filed"] == "2021-06-01"
    assert paper.extra["accession"] == "0001161697-21-000289"
    assert paper.extra["file_description"] == "FORM 10-K ANNUAL REPORT FOR 02-28-2021"
    assert paper.extra["period_ending"] == "2021-02-28"
    assert paper.extra["company"].startswith("Artificial Intelligence Technology")
    assert urls[0].startswith("https://efts.sec.gov/LATEST/search-index?q=")
    assert "%22artificial%20intelligence%22" in urls[0]


def test_exhibits_of_one_filing_collapse_to_the_best_hit(
    monkeypatch: pytest.MonkeyPatch, with_contact: None
) -> None:
    # EFTS returns hits by descending score, so the first document seen for an
    # accession is the one whose text matched best; later exhibits are noise.
    _serve(
        monkeypatch,
        _envelope(
            _hit("0001161697-21-000289:ex_99-1.htm", 19.2, file_type="EX-99"),
            _hit("0001161697-21-000289:form_10-k.htm", 18.4),
            _hit(
                "0001161697-22-000273:form_10-ka.htm",
                18.6,
                adsh="0001161697-22-000273",
                form="10-K/A",
                file_date="2022-05-31",
            ),
            _hit("0001161697-21-000289:ex_31-1.htm", 12.0, file_type="EX-31"),
        ),
    )
    papers = EdgarProvider().search(None, "insider trading", 10)

    assert [p.identifier for p in papers] == ["0001161697-21-000289", "0001161697-22-000273"]
    assert papers[0].url is not None and papers[0].url.endswith("/ex_99-1.htm")
    assert papers[1].extra["form"] == "10-K/A"
    assert papers[1].year == 2022


def test_limit_applies_after_dedup(monkeypatch: pytest.MonkeyPatch, with_contact: None) -> None:
    _serve(
        monkeypatch,
        _envelope(
            _hit("0001161697-21-000289:a.htm", 3.0),
            _hit("0001161697-21-000289:b.htm", 2.0),
            _hit("0001161697-22-000273:c.htm", 1.0, adsh="0001161697-22-000273"),
        ),
    )
    papers = EdgarProvider().search(None, "x", 1)
    assert [p.identifier for p in papers] == ["0001161697-21-000289"]


def test_accession_falls_back_to_id_prefix(
    monkeypatch: pytest.MonkeyPatch, with_contact: None
) -> None:
    _serve(monkeypatch, _envelope(_hit("0009999999-24-000001:doc.htm", 1.0, adsh=None)))
    papers = EdgarProvider().search(None, "x", 5)
    assert [p.identifier for p in papers] == ["0009999999-24-000001"]


def test_missing_document_name_links_to_the_filing_index(
    monkeypatch: pytest.MonkeyPatch, with_contact: None
) -> None:
    _serve(monkeypatch, _envelope(_hit("0001161697-21-000289", 1.0)))
    papers = EdgarProvider().search(None, "x", 5)
    assert papers[0].url == (
        "https://www.sec.gov/Archives/edgar/data/1498148/000116169721000289/"
        "0001161697-21-000289-index.htm"
    )


def test_missing_cik_yields_no_url_but_keeps_the_record(
    monkeypatch: pytest.MonkeyPatch, with_contact: None
) -> None:
    hit = _hit("0001161697-21-000289:form_10-k.htm", 1.0)
    hit["_source"]["ciks"] = []
    _serve(monkeypatch, _envelope(hit))
    papers = EdgarProvider().search(None, "x", 5)
    assert len(papers) == 1
    assert papers[0].url is None
    assert "cik" not in papers[0].extra


def test_title_without_company_falls_back_to_accession(
    monkeypatch: pytest.MonkeyPatch, with_contact: None
) -> None:
    hit = _hit("0001161697-21-000289:form_10-k.htm", 1.0, description=None)
    hit["_source"]["display_names"] = []
    hit["_source"]["form"] = None
    hit["_source"]["root_forms"] = []
    _serve(monkeypatch, _envelope(hit))
    papers = EdgarProvider().search(None, "x", 5)
    assert papers[0].title == "SEC filing 0001161697-21-000289 (filed 2021-06-01)"
    assert "file_description" not in papers[0].extra


# --- failure paths -----------------------------------------------------------


def test_upstream_unreachable_returns_empty(
    monkeypatch: pytest.MonkeyPatch, with_contact: None
) -> None:
    _serve(monkeypatch, None)
    assert EdgarProvider().search(None, "x", 5) == []


def test_malformed_json_returns_empty(monkeypatch: pytest.MonkeyPatch, with_contact: None) -> None:
    _serve(monkeypatch, "<html><title>Request Rejected</title></html>")
    assert EdgarProvider().search(None, "x", 5) == []


@pytest.mark.parametrize(
    "body",
    [
        pytest.param("[]", id="top-level-list"),
        pytest.param('{"hits": null}', id="null-hits"),
        pytest.param('{"hits": {"hits": null}}', id="null-inner-hits"),
        pytest.param('{"hits": {"hits": [1, "two", null]}}', id="junk-rows"),
        pytest.param('{"hits": {"hits": [{"_id": "x:y"}]}}', id="row-without-source"),
        pytest.param('{"hits": {"hits": [{"_source": {"form": "8-K"}}]}}', id="no-accession"),
    ],
)
def test_unexpected_shapes_return_empty(
    monkeypatch: pytest.MonkeyPatch, with_contact: None, body: str
) -> None:
    _serve(monkeypatch, body)
    assert EdgarProvider().search(None, "x", 5) == []


def test_blank_query_makes_no_request(monkeypatch: pytest.MonkeyPatch, with_contact: None) -> None:
    urls = _serve(monkeypatch, _envelope())
    assert EdgarProvider().search(None, "  ", 5) == []
    assert urls == []
