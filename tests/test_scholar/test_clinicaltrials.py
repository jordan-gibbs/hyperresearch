"""ClinicalTrials.gov provider.

Fixtures are trimmed from real `/api/v2/studies` responses, keeping the exact
nesting: `studies[].protocolSection.<module>.<field>`. The deep nesting is the
whole risk in this provider, so the failure cases below are mostly about
records that arrive with modules missing.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from hyperresearch.scholar import base
from hyperresearch.scholar.providers.clinicaltrials import ClinicalTrialsProvider

FULL_STUDY: dict[str, Any] = {
    "protocolSection": {
        "identificationModule": {
            "nctId": "NCT04041310",
            "orgStudyIdInfo": {"id": "NOUS-209-01"},
            "organization": {"fullName": "Nouscom SRL", "class": "INDUSTRY"},
            "briefTitle": "Nous-209 Genetic Vaccine for Microsatellite Unstable Solid Tumors",
            "officialTitle": (
                "A Phase I/II, Multicenter, Open-Label Study of Nous-209 Genetic "
                "Vaccine for the Treatment of Microsatellite Unstable Solid Tumors"
            ),
        },
        "statusModule": {
            "statusVerifiedDate": "2026-02",
            "overallStatus": "ACTIVE_NOT_RECRUITING",
            "startDateStruct": {"date": "2019-10-21", "type": "ACTUAL"},
            "completionDateStruct": {"date": "2026-10-30", "type": "ESTIMATED"},
        },
        "sponsorCollaboratorsModule": {
            "responsibleParty": {"type": "SPONSOR"},
            "leadSponsor": {"name": "Nouscom SRL", "class": "INDUSTRY"},
            "collaborators": [{"name": "Merck Sharp & Dohme LLC", "class": "INDUSTRY"}],
        },
        "descriptionModule": {
            "briefSummary": "NOUS-209-01 is a multicenter, open-label clinical study.",
            "detailedDescription": "Longer protocol prose that we do not surface.",
        },
        "conditionsModule": {
            "conditions": ["Solid Tumor, Adult", "Colorectal Cancer"],
            "keywords": ["MSI-H CRC"],
        },
        "designModule": {
            "studyType": "INTERVENTIONAL",
            "phases": ["PHASE1", "PHASE2"],
            "enrollmentInfo": {"count": 130, "type": "ESTIMATED"},
        },
    },
    "derivedSection": {},
    "hasResults": False,
}

# A real minimal registration: an id and a title and essentially nothing else.
SPARSE_STUDY: dict[str, Any] = {
    "protocolSection": {
        "identificationModule": {
            "nctId": "NCT00000102",
            "briefTitle": "Congenital Adrenal Hyperplasia: Calcium Channels",
        }
    }
}


def _payload(*studies: Any) -> dict[str, Any]:
    return {"totalCount": len(studies), "studies": list(studies)}


@pytest.fixture
def capture(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record requested URLs while returning nothing, for no-request assertions."""
    seen: list[str] = []

    def fake_get(url: str, headers: dict[str, str] | None = None) -> str | None:
        seen.append(url)
        return None

    monkeypatch.setattr(base, "_http_get", fake_get)
    return seen


def _serve(monkeypatch: pytest.MonkeyPatch, body: str | None) -> list[str]:
    seen: list[str] = []

    def fake_get(url: str, headers: dict[str, str] | None = None) -> str | None:
        seen.append(url)
        return body

    monkeypatch.setattr(base, "_http_get", fake_get)
    return seen


def test_parses_a_full_study(monkeypatch: pytest.MonkeyPatch) -> None:
    urls = _serve(monkeypatch, json.dumps(_payload(FULL_STUDY)))
    papers = ClinicalTrialsProvider().search(None, "pembrolizumab", 5)

    assert len(papers) == 1
    paper = papers[0]
    assert paper.identifier == "NCT04041310"
    assert paper.work_type == "trial"
    assert paper.source == "clinicaltrials"
    assert paper.url == "https://clinicaltrials.gov/study/NCT04041310"
    assert paper.title.startswith("Nous-209 Genetic Vaccine")
    assert paper.year == 2019
    assert paper.venue == "Nouscom SRL"
    assert paper.abstract == "NOUS-209-01 is a multicenter, open-label clinical study."
    assert paper.extra["status"] == "ACTIVE_NOT_RECRUITING"
    assert paper.extra["phase"] == "PHASE1/PHASE2"
    assert paper.extra["study_type"] == "INTERVENTIONAL"
    assert paper.extra["enrollment"] == "130"
    assert paper.extra["conditions"] == "Solid Tumor, Adult; Colorectal Cancer"
    assert paper.extra["lead_sponsor"] == "Nouscom SRL"
    assert "query.term=pembrolizumab" in urls[0]
    assert "pageSize=5" in urls[0]


def test_sparse_study_keeps_what_exists_and_nulls_the_rest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _serve(monkeypatch, json.dumps(_payload(SPARSE_STUDY)))
    papers = ClinicalTrialsProvider().search(None, "adrenal", 5)

    assert len(papers) == 1
    paper = papers[0]
    assert paper.identifier == "NCT00000102"
    assert paper.year is None
    assert paper.venue is None
    assert paper.abstract is None
    assert paper.extra == {"nct_id": "NCT00000102"}


def test_falls_back_to_official_title(monkeypatch: pytest.MonkeyPatch) -> None:
    study = {
        "protocolSection": {
            "identificationModule": {
                "nctId": "NCT99999999",
                "officialTitle": "A Randomized Trial Of Something",
            }
        }
    }
    _serve(monkeypatch, json.dumps(_payload(study)))
    papers = ClinicalTrialsProvider().search(None, "something", 5)

    assert [p.title for p in papers] == ["A Randomized Trial Of Something"]


@pytest.mark.parametrize(
    "study",
    [
        pytest.param({"derivedSection": {}}, id="no-protocolSection"),
        pytest.param({"protocolSection": None}, id="null-protocolSection"),
        pytest.param({"protocolSection": []}, id="protocolSection-wrong-type"),
        pytest.param({"protocolSection": {"identificationModule": {}}}, id="empty-module"),
        pytest.param(
            {"protocolSection": {"identificationModule": {"briefTitle": "No id here"}}},
            id="title-without-id",
        ),
        pytest.param(
            {"protocolSection": {"identificationModule": {"nctId": "NCT1"}}},
            id="id-without-title",
        ),
        pytest.param("not a study at all", id="not-a-dict"),
    ],
)
def test_unusable_records_are_dropped_not_raised(
    monkeypatch: pytest.MonkeyPatch, study: Any
) -> None:
    _serve(monkeypatch, json.dumps(_payload(study)))
    assert ClinicalTrialsProvider().search(None, "anything", 5) == []


def test_bad_record_does_not_lose_the_good_ones(monkeypatch: pytest.MonkeyPatch) -> None:
    _serve(monkeypatch, json.dumps(_payload({"derivedSection": {}}, FULL_STUDY)))
    papers = ClinicalTrialsProvider().search(None, "pembrolizumab", 5)

    assert [p.identifier for p in papers] == ["NCT04041310"]


def test_limit_is_honored(monkeypatch: pytest.MonkeyPatch) -> None:
    _serve(monkeypatch, json.dumps(_payload(FULL_STUDY, SPARSE_STUDY)))
    papers = ClinicalTrialsProvider().search(None, "trial", 1)

    assert len(papers) == 1


def test_upstream_unreachable_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    _serve(monkeypatch, None)
    assert ClinicalTrialsProvider().search(None, "pembrolizumab", 5) == []


def test_malformed_json_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    _serve(monkeypatch, "<html>503 Service Unavailable</html>")
    assert ClinicalTrialsProvider().search(None, "pembrolizumab", 5) == []


@pytest.mark.parametrize(
    "body",
    [
        pytest.param("[]", id="top-level-list"),
        pytest.param('{"studies": null}', id="null-studies"),
        pytest.param('{"studies": {}}', id="studies-wrong-type"),
        pytest.param('{"totalCount": 0, "studies": []}', id="no-results"),
    ],
)
def test_unexpected_envelopes_return_empty(monkeypatch: pytest.MonkeyPatch, body: str) -> None:
    _serve(monkeypatch, body)
    assert ClinicalTrialsProvider().search(None, "pembrolizumab", 5) == []


def test_blank_query_makes_no_request(capture: list[str]) -> None:
    assert ClinicalTrialsProvider().search(None, "   ", 5) == []
    assert capture == []


def test_provider_is_always_available() -> None:
    provider = ClinicalTrialsProvider()
    assert provider.slug == "clinicaltrials"
    assert provider.needs_key is False
    assert provider.available() is True
    assert provider.unavailable_reason() is None
