"""OpenAlexProvider — fully offline; the only network seam is stubbed.

Every test monkeypatches `hyperresearch.scholar.base._http_get` and passes
`conn=None` so the api_cache is bypassed entirely. `_throttle` is stubbed too:
it is a real `time.sleep` against the per-host courtesy delay and would
otherwise add a fifth of a second to every test in this file for no coverage.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from hyperresearch.scholar import base
from hyperresearch.scholar.base import ProviderError
from hyperresearch.scholar.providers.openalex import OpenAlexProvider, _invert_abstract

# A realistic single-result response, trimmed to the fields we read plus a few
# we deliberately ignore, with OpenAlex's actual nesting preserved.
LIVE_SHAPE: dict[str, Any] = {
    "meta": {"count": 1, "per_page": 25},
    "results": [
        {
            "id": "https://openalex.org/W2741809807",
            "doi": "https://doi.org/10.7717/peerj.4375",
            "display_name": "The state of OA: a large-scale analysis",
            "title": "The state of OA: a large-scale analysis",
            "publication_year": 2018,
            "type": "article",
            "cited_by_count": 1043,
            "abstract_inverted_index": {
                "Despite": [0],
                "growing": [1],
                "interest": [2],
                "in": [3, 7],
                "Open": [4],
                "Access": [5],
                "(OA)": [6],
                "scholarly": [8],
                "literature": [9],
            },
            "authorships": [
                {"author": {"id": "https://openalex.org/A1", "display_name": "Heather Piwowar"}},
                {"author": {"id": "https://openalex.org/A2", "display_name": "Jason Priem"}},
            ],
            "primary_location": {
                "source": {"display_name": "PeerJ", "type": "journal"},
                "landing_page_url": "https://peerj.com/articles/4375",
                "pdf_url": None,
            },
            "best_oa_location": {
                "source": {"display_name": "PeerJ"},
                "landing_page_url": "https://peerj.com/articles/4375",
                "pdf_url": "https://peerj.com/articles/4375.pdf",
            },
            "open_access": {"is_oa": True, "oa_status": "gold"},
        }
    ],
}


def _stub(monkeypatch: pytest.MonkeyPatch, payload: Any, calls: list[str] | None = None) -> None:
    """Stub the raw HTTP seam.

    `payload` is a dict (serialized to JSON), a raw string (for malformed-body
    tests), or None (for an upstream failure).
    """
    body = payload if payload is None or isinstance(payload, str) else json.dumps(payload)

    def fake_get(url: str, headers: dict[str, str] | None = None) -> str | None:
        if calls is not None:
            calls.append(url)
        return body

    monkeypatch.setattr(base, "_http_get", fake_get)
    monkeypatch.setattr(base, "_throttle", lambda url: None)


@pytest.fixture(autouse=True)
def _no_contact_email(monkeypatch: pytest.MonkeyPatch) -> None:
    """URL assertions must not depend on the developer's own environment."""
    monkeypatch.delenv("HYPERRESEARCH_CONTACT_EMAIL", raising=False)


class TestAbstractInversion:
    """The regression most likely to break silently — see module docstring."""

    def test_reconstructs_words_in_position_order(self) -> None:
        # Keys deliberately out of order: a naive "join the keys" gives
        # "brown quick fox the" and would pass a laxer assertion.
        index = {"quick": [1], "the": [0], "fox": [3], "brown": [2]}
        assert _invert_abstract(index) == "the quick brown fox"

    def test_repeated_word_appears_at_every_position(self) -> None:
        index = {"in": [3, 7], "a": [0], "b": [1], "c": [2], "d": [4], "e": [5], "f": [6]}
        assert _invert_abstract(index) == "a b c in d e f in"

    def test_real_fixture_reads_as_prose(self) -> None:
        provider = OpenAlexProvider()
        paper = provider._to_paper(LIVE_SHAPE["results"][0])
        assert paper is not None
        assert paper.abstract == (
            "Despite growing interest in Open Access (OA) in scholarly literature"
        )

    def test_null_index_is_a_missing_abstract_not_an_error(self) -> None:
        assert _invert_abstract(None) is None

    def test_empty_index_is_none(self) -> None:
        assert _invert_abstract({}) is None

    def test_non_dict_index_is_none(self) -> None:
        assert _invert_abstract(["not", "an", "index"]) is None

    def test_garbage_positions_are_dropped_not_fatal(self) -> None:
        index = {"kept": [0], "dropped": ["x", None], "also": [1]}
        assert _invert_abstract(index) == "kept also"


class TestParsing:
    def test_maps_every_contract_field(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _stub(monkeypatch, LIVE_SHAPE)
        papers = OpenAlexProvider().search(None, "open access", 25)
        assert len(papers) == 1
        paper = papers[0]
        assert paper.title == "The state of OA: a large-scale analysis"
        assert paper.source == "openalex"
        assert paper.doi == "10.7717/peerj.4375"
        assert paper.year == 2018
        assert paper.authors == ("Heather Piwowar", "Jason Priem")
        assert paper.venue == "PeerJ"
        assert paper.citation_count == 1043
        assert paper.work_type == "article"
        assert paper.identifier == "W2741809807"
        assert paper.url == "https://peerj.com/articles/4375"
        assert paper.pdf_url == "https://peerj.com/articles/4375.pdf"
        assert paper.extra["oa_status"] == "gold"

    def test_pdf_prefers_best_oa_over_primary_location(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        work = {
            "display_name": "Two PDFs",
            "primary_location": {"pdf_url": "https://paywall.example/x.pdf"},
            "best_oa_location": {"pdf_url": "https://repo.example/x.pdf"},
        }
        _stub(monkeypatch, {"results": [work]})
        (paper,) = OpenAlexProvider().search(None, "q", 5)
        assert paper.pdf_url == "https://repo.example/x.pdf"

    def test_bare_record_survives_with_only_a_title(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub(monkeypatch, {"results": [{"display_name": "Minimal Work"}]})
        (paper,) = OpenAlexProvider().search(None, "q", 5)
        assert paper.title == "Minimal Work"
        assert paper.doi is None
        assert paper.year is None
        assert paper.authors == ()
        assert paper.venue is None
        assert paper.abstract is None
        assert paper.citation_count is None
        assert paper.work_type == "other"
        assert paper.extra == {}

    def test_untitled_records_are_skipped_not_fatal(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub(
            monkeypatch,
            {"results": [{"id": "https://openalex.org/W1"}, {"display_name": "Kept"}, None]},
        )
        papers = OpenAlexProvider().search(None, "q", 5)
        assert [p.title for p in papers] == ["Kept"]

    def test_url_falls_back_to_doi_then_openalex_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub(monkeypatch, {"results": [{"display_name": "T", "doi": "https://doi.org/10.1/x"}]})
        (paper,) = OpenAlexProvider().search(None, "q", 5)
        assert paper.url == "https://doi.org/10.1/x"

        _stub(monkeypatch, {"results": [{"display_name": "T", "id": "https://openalex.org/W9"}]})
        (paper,) = OpenAlexProvider().search(None, "q", 5)
        assert paper.url == "https://openalex.org/W9"

    def test_authorships_missing_author_names_are_skipped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        work = {
            "display_name": "T",
            "authorships": [{"author": {}}, {"raw_author_name": "x"}, {"author": {"display_name": "Real Name"}}],
        }
        _stub(monkeypatch, {"results": [work]})
        (paper,) = OpenAlexProvider().search(None, "q", 5)
        assert paper.authors == ("Real Name",)

    def test_boolean_citation_count_is_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # bool subclasses int; without the guard `True` would become 1 citation.
        _stub(monkeypatch, {"results": [{"display_name": "T", "cited_by_count": True}]})
        (paper,) = OpenAlexProvider().search(None, "q", 5)
        assert paper.citation_count is None

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("article", "article"),
            ("journal-article", "article"),
            ("book", "book"),
            ("book-chapter", "book-chapter"),
            ("preprint", "preprint"),
            ("posted-content", "preprint"),
            ("dissertation", "thesis"),
            ("report", "report"),
            ("dataset", "dataset"),
            ("peer-review", "other"),
            ("paratext", "other"),
            ("", "other"),
        ],
    )
    def test_type_mapping(
        self, monkeypatch: pytest.MonkeyPatch, raw: str, expected: str
    ) -> None:
        _stub(monkeypatch, {"results": [{"display_name": "T", "type": raw}]})
        (paper,) = OpenAlexProvider().search(None, "q", 5)
        assert paper.work_type == expected


class TestFailurePaths:
    def test_upstream_none_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _stub(monkeypatch, None)
        assert OpenAlexProvider().search(None, "q", 5) == []

    def test_malformed_json_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _stub(monkeypatch, "{not json at all")
        assert OpenAlexProvider().search(None, "q", 5) == []

    def test_top_level_list_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _stub(monkeypatch, [{"display_name": "wrong shape"}])
        assert OpenAlexProvider().search(None, "q", 5) == []

    def test_missing_results_key_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _stub(monkeypatch, {"meta": {"count": 0}, "error": "Invalid query parameters"})
        assert OpenAlexProvider().search(None, "q", 5) == []

    def test_results_not_a_list_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _stub(monkeypatch, {"results": {"0": {"display_name": "T"}}})
        assert OpenAlexProvider().search(None, "q", 5) == []

    def test_blank_query_raises_provider_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _stub(monkeypatch, LIVE_SHAPE)
        with pytest.raises(ProviderError):
            OpenAlexProvider().search(None, "   ", 5)


class TestRequestShape:
    def test_query_and_limit_in_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []
        _stub(monkeypatch, LIVE_SHAPE, calls)
        OpenAlexProvider().search(None, "climate adaptation", 12)
        assert "search=climate%20adaptation" in calls[0]
        assert "per-page=12" in calls[0]

    def test_limit_is_clamped_to_openalex_page_ceiling(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[str] = []
        _stub(monkeypatch, LIVE_SHAPE, calls)
        OpenAlexProvider().search(None, "q", 5000)
        assert "per-page=200" in calls[0]

    def test_relevance_sort_sends_no_sort_param(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []
        _stub(monkeypatch, LIVE_SHAPE, calls)
        OpenAlexProvider().search(None, "q", 5)
        assert "sort=" not in calls[0]

    def test_citation_sort(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []
        _stub(monkeypatch, LIVE_SHAPE, calls)
        OpenAlexProvider().search(None, "q", 5, sort="citations")
        assert "sort=cited_by_count:desc" in calls[0]

    def test_unknown_sort_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _stub(monkeypatch, LIVE_SHAPE)
        with pytest.raises(ProviderError):
            OpenAlexProvider().search(None, "q", 5, sort="newest")

    def test_work_type_filter_from_constructor(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []
        _stub(monkeypatch, LIVE_SHAPE, calls)
        OpenAlexProvider("book").search(None, "the frankfurt school", 5)
        assert "filter=type:book|monograph|reference-book" in calls[0]

    def test_search_work_type_overrides_constructor(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[str] = []
        _stub(monkeypatch, LIVE_SHAPE, calls)
        OpenAlexProvider("book").search(None, "q", 5, work_type="thesis")
        assert "filter=type:dissertation" in calls[0]

    def test_unfilterable_work_type_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _stub(monkeypatch, LIVE_SHAPE)
        with pytest.raises(ProviderError):
            OpenAlexProvider().search(None, "q", 5, work_type="filing")

    def test_mailto_appended_only_when_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[str] = []
        _stub(monkeypatch, LIVE_SHAPE, calls)
        OpenAlexProvider().search(None, "q", 5)
        assert "mailto=" not in calls[0]

        monkeypatch.setenv("HYPERRESEARCH_CONTACT_EMAIL", "someone@example.org")
        OpenAlexProvider().search(None, "q", 5)
        assert "mailto=someone%40example.org" in calls[1]


class TestContract:
    def test_slug_and_availability(self) -> None:
        provider = OpenAlexProvider()
        assert provider.slug == "openalex"
        assert provider.needs_key is False
        assert provider.available() is True
        assert provider.unavailable_reason() is None
