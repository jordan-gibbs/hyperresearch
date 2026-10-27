"""FirecrawlResearchProvider — fully offline; the only network seam is stubbed.

Hit shapes below are trimmed from live `GET /v2/search/research/papers`
responses (2026-10): ids grouped by namespace, a namespaced `primaryId`, and
no authors, year or venue.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from hyperresearch.scholar import base
from hyperresearch.scholar.base import Paper, ProviderError
from hyperresearch.scholar.dedup import merge_papers
from hyperresearch.scholar.providers.firecrawl_research import FirecrawlResearchProvider

ARXIV_HIT = {
    "paperId": "8319239866974784291",
    "primaryId": "arxiv:1706.03762",
    "ids": {"arxiv": ["1706.03762"]},
    "title": "Attention Is All You Need",
    "abstract": "The dominant sequence transduction models are based on recurrent networks.",
    "score": 0.98245,
}
# Published article that started as a medRxiv preprint: two DOIs, preprint first.
PUBLISHED_FROM_PREPRINT_HIT = {
    "paperId": "1",
    "primaryId": "pmcid:PMC10863028",
    "ids": {
        "doi": ["10.1101/2024.01.31.24301674", "10.1371/journal.pone.0303303"],
        "pmcid": ["PMC10863028"],
        "pmid": ["38352327"],
    },
    "title": "Relative contribution of COVID-19 vaccination and SARS-CoV-2 infection",
    "abstract": "Seroprevalence of anti-spike antibodies…",
    "score": 0.95,
}
PREPRINT_ONLY_HIT = {
    "paperId": "2",
    "primaryId": "doi:10.1101/2020.11.17.20228155",
    "ids": {"doi": ["10.1101/2020.11.17.20228155"]},
    "title": "Community prevalence of antibodies to SARS-CoV-2",
    "abstract": "We report seroprevalence.",
    "score": 0.94,
}
OLD_ARXIV_HIT = {
    "paperId": "3",
    "primaryId": "arxiv:hep-th/9711200",
    "ids": {"arxiv": ["hep-th/9711200"]},
    "title": "The Large N Limit of Superconformal Field Theories and Supergravity",
    "abstract": "We show that the large N limit of certain conformal field theories...",
    "score": 0.97,
}


def _stub(
    monkeypatch: pytest.MonkeyPatch,
    payload: Any,
    calls: list[tuple[str, dict[str, str] | None]] | None = None,
) -> None:
    body = payload if payload is None or isinstance(payload, str) else json.dumps(payload)

    def fake_get(url: str, headers: dict[str, str] | None = None) -> str | None:
        if calls is not None:
            calls.append((url, headers))
        return body

    monkeypatch.setattr(base, "_http_get", fake_get)
    monkeypatch.setattr(base, "_throttle", lambda url: None)


def _search(monkeypatch: pytest.MonkeyPatch, *hits: dict[str, Any]) -> list[Paper]:
    _stub(monkeypatch, {"success": True, "partial": False, "results": list(hits)})
    return FirecrawlResearchProvider().search(None, "q", 10)


def test_arxiv_hit_is_a_dated_preprint_with_a_readable_copy(monkeypatch):
    (paper,) = _search(monkeypatch, ARXIV_HIT)

    assert paper.title == "Attention Is All You Need"
    assert paper.source == "firecrawl"
    assert paper.work_type == "preprint"
    assert paper.year == 2017
    assert paper.doi is None
    assert paper.url == "https://arxiv.org/abs/1706.03762"
    assert paper.pdf_url == "https://arxiv.org/pdf/1706.03762"
    assert paper.identifier == "arxiv:1706.03762"


def test_old_style_arxiv_id_still_yields_the_year(monkeypatch):
    (paper,) = _search(monkeypatch, OLD_ARXIV_HIT)
    assert paper.year == 1997


def test_published_doi_beats_the_preprint_doi(monkeypatch):
    (paper,) = _search(monkeypatch, PUBLISHED_FROM_PREPRINT_HIT)

    assert paper.doi == "10.1371/journal.pone.0303303"
    assert paper.extra["preprint_doi"] == "10.1101/2024.01.31.24301674"
    assert paper.work_type == "article"
    # Its year would be the preprint's, not the article's: left to the merge.
    assert paper.year is None
    assert paper.url == "https://pmc.ncbi.nlm.nih.gov/articles/PMC10863028/"


def test_preprint_only_doi_gives_year_and_preprint_type(monkeypatch):
    (paper,) = _search(monkeypatch, PREPRINT_ONLY_HIT)

    assert paper.doi == "10.1101/2020.11.17.20228155"
    assert paper.year == 2020
    assert paper.work_type == "preprint"
    assert paper.url == "https://doi.org/10.1101/2020.11.17.20228155"


def test_thin_hit_merges_into_the_openalex_record_by_doi(monkeypatch):
    (thin,) = _search(monkeypatch, PUBLISHED_FROM_PREPRINT_HIT)
    rich = Paper(
        title="Relative contribution of COVID-19 vaccination and SARS-CoV-2 infection",
        source="openalex",
        doi="10.1371/journal.pone.0303303",
        year=2024,
        authors=("A. Author", "B. Author"),
        venue="PLOS ONE",
    )

    (merged,) = merge_papers([thin, rich], ["openalex", "firecrawl"])

    assert merged.year == 2024
    assert merged.venue == "PLOS ONE"
    assert merged.authors == ("A. Author", "B. Author")
    assert merged.extra["also_in"] == "openalex,firecrawl"
    assert merged.extra["pmcid"] == "PMC10863028"


def test_key_is_sent_as_bearer_only_when_set(monkeypatch):
    calls: list[tuple[str, dict[str, str] | None]] = []
    _stub(monkeypatch, {"success": True, "results": []}, calls)

    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
    FirecrawlResearchProvider().search(None, "base editing", 5)
    monkeypatch.setenv("FIRECRAWL_API_KEY", "fc-test")
    FirecrawlResearchProvider().search(None, "base editing", 5)

    assert calls[0][1] is None
    assert calls[1][1] == {"Authorization": "Bearer fc-test"}
    assert "query=base%20editing" in calls[0][0] and "k=5" in calls[0][0]


@pytest.mark.parametrize(
    "payload",
    [None, "not json", {"success": False, "error": "rate limited"}, {"success": True}],
)
def test_upstream_failure_is_an_empty_result(monkeypatch, payload):
    _stub(monkeypatch, payload)
    assert FirecrawlResearchProvider().search(None, "q", 5) == []


def test_untitled_hits_are_dropped(monkeypatch):
    assert _search(monkeypatch, {"primaryId": "pmid:1", "ids": {"pmid": ["1"]}}) == []


def test_blank_query_is_refused(monkeypatch):
    _stub(monkeypatch, {"success": True, "results": []})
    with pytest.raises(ProviderError):
        FirecrawlResearchProvider().search(None, "   ", 5)
