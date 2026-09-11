"""CrossrefProvider — fully offline; the only network seam is stubbed.

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
from hyperresearch.scholar.providers.crossref import CrossrefProvider, _strip_jats

# Realistic response: Crossref's `message` envelope, list-valued `title` and
# `container-title`, a JATS abstract with the usual redundant title label, and
# a similarity-checking PDF link.
LIVE_SHAPE: dict[str, Any] = {
    "status": "ok",
    "message-type": "work-list",
    "message": {
        "total-results": 1,
        "items": [
            {
                "DOI": "10.1038/s41586-021-03819-2",
                "URL": "http://dx.doi.org/10.1038/s41586-021-03819-2",
                "type": "journal-article",
                "title": ["Highly accurate protein structure prediction with AlphaFold"],
                "container-title": ["Nature"],
                "publisher": "Springer Science and Business Media LLC",
                "is-referenced-by-count": 21473,
                "abstract": (
                    "<jats:title>Abstract</jats:title><jats:p>Proteins are essential to "
                    "life, and understanding their structure can facilitate a mechanistic "
                    "understanding of their function.</jats:p>"
                ),
                "author": [
                    {"given": "John", "family": "Jumper", "sequence": "first"},
                    {"given": "Richard", "family": "Evans"},
                    {"name": "AlphaFold Team"},
                ],
                "issued": {"date-parts": [[2021, 7, 15]]},
                "created": {"date-time": "2021-07-15T15:03:15Z"},
                "link": [
                    {
                        "URL": "https://www.nature.com/articles/s41586-021-03819-2.pdf",
                        "content-type": "application/pdf",
                        "intended-application": "similarity-checking",
                    }
                ],
            }
        ],
    },
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


def _wrap(*items: Any) -> dict[str, Any]:
    return {"status": "ok", "message": {"items": list(items)}}


@pytest.fixture(autouse=True)
def _no_contact_email(monkeypatch: pytest.MonkeyPatch) -> None:
    """URL assertions must not depend on the developer's own environment."""
    monkeypatch.delenv("HYPERRESEARCH_CONTACT_EMAIL", raising=False)


class TestParsing:
    def test_maps_every_contract_field(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _stub(monkeypatch, LIVE_SHAPE)
        papers = CrossrefProvider().search(None, "alphafold", 20)
        assert len(papers) == 1
        paper = papers[0]
        assert paper.title == "Highly accurate protein structure prediction with AlphaFold"
        assert paper.source == "crossref"
        assert paper.doi == "10.1038/s41586-021-03819-2"
        assert paper.identifier == "10.1038/s41586-021-03819-2"
        assert paper.year == 2021
        assert paper.authors == ("John Jumper", "Richard Evans", "AlphaFold Team")
        assert paper.venue == "Nature"
        assert paper.citation_count == 21473
        assert paper.work_type == "article"
        assert paper.url == "http://dx.doi.org/10.1038/s41586-021-03819-2"
        assert paper.pdf_url == "https://www.nature.com/articles/s41586-021-03819-2.pdf"
        assert paper.extra["publisher"] == "Springer Science and Business Media LLC"

    def test_subtitle_is_appended(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _stub(monkeypatch, _wrap({"title": ["Main"], "subtitle": ["A Study"]}))
        (paper,) = CrossrefProvider().search(None, "q", 5)
        assert paper.title == "Main: A Study"

    def test_subtitle_already_in_title_is_not_duplicated(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub(monkeypatch, _wrap({"title": ["Main: A Study"], "subtitle": ["A Study"]}))
        (paper,) = CrossrefProvider().search(None, "q", 5)
        assert paper.title == "Main: A Study"

    def test_organizational_author_uses_name_field(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        item = {
            "title": ["T"],
            "author": [{"name": "The WHO Collaborating Group"}, {"family": "Solo"}, {}],
        }
        _stub(monkeypatch, _wrap(item))
        (paper,) = CrossrefProvider().search(None, "q", 5)
        assert paper.authors == ("The WHO Collaborating Group", "Solo")

    def test_boolean_citation_count_is_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # bool subclasses int; without the guard `True` would become 1 citation.
        _stub(monkeypatch, _wrap({"title": ["T"], "is-referenced-by-count": True}))
        (paper,) = CrossrefProvider().search(None, "q", 5)
        assert paper.citation_count is None

    def test_non_pdf_links_are_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        item = {
            "title": ["T"],
            "link": [
                {"URL": "https://x.example/full.xml", "content-type": "application/xml"},
                {"URL": "https://x.example/unspecified", "content-type": "unspecified"},
            ],
        }
        _stub(monkeypatch, _wrap(item))
        (paper,) = CrossrefProvider().search(None, "q", 5)
        assert paper.pdf_url is None

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("journal-article", "article"),
            ("proceedings-article", "article"),
            ("book-chapter", "book-chapter"),
            ("book", "book"),
            ("monograph", "book"),
            ("posted-content", "preprint"),
            ("dissertation", "thesis"),
            ("report", "report"),
            ("dataset", "dataset"),
            ("component", "other"),
            ("", "other"),
        ],
    )
    def test_type_mapping(
        self, monkeypatch: pytest.MonkeyPatch, raw: str, expected: str
    ) -> None:
        _stub(monkeypatch, _wrap({"title": ["T"], "type": raw}))
        (paper,) = CrossrefProvider().search(None, "q", 5)
        assert paper.work_type == expected


class TestAbstracts:
    """Crossref abstracts are optional deposits — absence is the normal case."""

    def test_jats_is_flattened_and_the_abstract_label_dropped(self) -> None:
        raw = "<jats:title>Abstract</jats:title><jats:p>Body <jats:italic>text</jats:italic>.</jats:p>"
        assert _strip_jats(raw) == "Body text."

    def test_entities_are_unescaped(self) -> None:
        assert _strip_jats("<jats:p>Tea &amp; toast &lt; brunch</jats:p>") == "Tea & toast < brunch"

    def test_missing_abstract_is_none_not_empty_string(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Roughly a quarter of sampled Crossref records carry no abstract, and
        # whole publishers deposit none, so this path is the common one.
        _stub(monkeypatch, _wrap({"title": ["T"]}))
        (paper,) = CrossrefProvider().search(None, "q", 5)
        assert paper.abstract is None

    def test_tag_only_abstract_collapses_to_none(self) -> None:
        assert _strip_jats("<jats:p></jats:p>") is None

    def test_non_string_abstract_is_none(self) -> None:
        assert _strip_jats({"jats:p": "nope"}) is None


class TestDates:
    @pytest.mark.parametrize(
        ("date_parts", "expected"),
        [
            ([[2019, 3, 14]], 2019),
            ([[2019, 3]], 2019),
            ([[2019]], 2019),
            ([[None]], None),
            ([[]], None),
            ([], None),
        ],
    )
    def test_variable_date_part_depth(
        self, monkeypatch: pytest.MonkeyPatch, date_parts: Any, expected: int | None
    ) -> None:
        _stub(monkeypatch, _wrap({"title": ["T"], "issued": {"date-parts": date_parts}}))
        (paper,) = CrossrefProvider().search(None, "q", 5)
        assert paper.year == expected

    def test_falls_back_to_published_online(self, monkeypatch: pytest.MonkeyPatch) -> None:
        item = {
            "title": ["T"],
            "issued": {"date-parts": [[None]]},
            "published-online": {"date-parts": [[2022, 1]]},
        }
        _stub(monkeypatch, _wrap(item))
        (paper,) = CrossrefProvider().search(None, "q", 5)
        assert paper.year == 2022

    def test_last_resort_is_the_deposit_timestamp(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        item = {"title": ["T"], "created": {"date-time": "2015-11-02T09:00:00Z"}}
        _stub(monkeypatch, _wrap(item))
        (paper,) = CrossrefProvider().search(None, "q", 5)
        assert paper.year == 2015


class TestFailurePaths:
    def test_empty_title_list_skips_the_record(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _stub(monkeypatch, _wrap({"DOI": "10.1/x", "title": []}, {"title": ["Kept"]}))
        papers = CrossrefProvider().search(None, "q", 5)
        assert [p.title for p in papers] == ["Kept"]

    def test_missing_title_key_skips_the_record(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _stub(monkeypatch, _wrap({"DOI": "10.1/x"}, None, {"title": ["Kept"]}))
        papers = CrossrefProvider().search(None, "q", 5)
        assert [p.title for p in papers] == ["Kept"]

    def test_title_as_bare_string_still_parses(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Crossref is inconsistent about which fields are list-valued.
        _stub(monkeypatch, _wrap({"title": "Scalar Title"}))
        (paper,) = CrossrefProvider().search(None, "q", 5)
        assert paper.title == "Scalar Title"

    def test_upstream_none_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _stub(monkeypatch, None)
        assert CrossrefProvider().search(None, "q", 5) == []

    def test_malformed_json_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _stub(monkeypatch, "<html>502 Bad Gateway</html>")
        assert CrossrefProvider().search(None, "q", 5) == []

    def test_error_envelope_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _stub(monkeypatch, {"status": "error", "message": [{"type": "invalid-parameter"}]})
        assert CrossrefProvider().search(None, "q", 5) == []

    def test_missing_message_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _stub(monkeypatch, {"status": "ok"})
        assert CrossrefProvider().search(None, "q", 5) == []

    def test_items_not_a_list_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _stub(monkeypatch, {"message": {"items": "nope"}})
        assert CrossrefProvider().search(None, "q", 5) == []

    def test_blank_query_raises_provider_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _stub(monkeypatch, LIVE_SHAPE)
        with pytest.raises(ProviderError):
            CrossrefProvider().search(None, "\t\n", 5)


class TestRequestShape:
    def test_query_and_rows_in_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []
        _stub(monkeypatch, LIVE_SHAPE, calls)
        CrossrefProvider().search(None, "protein folding", 30)
        assert "query=protein%20folding" in calls[0]
        assert "rows=30" in calls[0]

    def test_rows_clamped_to_crossref_page_ceiling(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[str] = []
        _stub(monkeypatch, LIVE_SHAPE, calls)
        CrossrefProvider().search(None, "q", 9999)
        assert "rows=100" in calls[0]

    def test_relevance_sort_sends_no_sort_param(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []
        _stub(monkeypatch, LIVE_SHAPE, calls)
        CrossrefProvider().search(None, "q", 5)
        assert "sort=" not in calls[0]

    def test_citation_sort(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []
        _stub(monkeypatch, LIVE_SHAPE, calls)
        CrossrefProvider().search(None, "q", 5, sort="citations")
        assert "sort=is-referenced-by-count&order=desc" in calls[0]

    def test_unknown_sort_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _stub(monkeypatch, LIVE_SHAPE)
        with pytest.raises(ProviderError):
            CrossrefProvider().search(None, "q", 5, sort="oldest")

    def test_work_type_filter_uses_crossref_vocabulary(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[str] = []
        _stub(monkeypatch, LIVE_SHAPE, calls)
        CrossrefProvider("book-chapter").search(None, "q", 5)
        assert "filter=type:book-chapter" in calls[0]

    def test_unfilterable_work_type_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _stub(monkeypatch, LIVE_SHAPE)
        with pytest.raises(ProviderError):
            CrossrefProvider().search(None, "q", 5, work_type="trial")

    def test_mailto_appended_only_when_configured(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[str] = []
        _stub(monkeypatch, LIVE_SHAPE, calls)
        CrossrefProvider().search(None, "q", 5)
        assert "mailto=" not in calls[0]

        monkeypatch.setenv("HYPERRESEARCH_CONTACT_EMAIL", "someone@example.org")
        CrossrefProvider().search(None, "q", 5)
        assert "mailto=someone%40example.org" in calls[1]


class TestContract:
    def test_slug_and_availability(self) -> None:
        provider = CrossrefProvider()
        assert provider.slug == "crossref"
        assert provider.needs_key is False
        assert provider.available() is True
        assert provider.unavailable_reason() is None
