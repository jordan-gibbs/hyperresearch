"""DoabProvider — fully offline; the only network seam is stubbed.

Every test monkeypatches `hyperresearch.scholar.base._http_get` and passes
`conn=None` so the api_cache is bypassed. `_throttle` is stubbed too: it is a
real `time.sleep` against the per-host courtesy delay.

The fixtures reproduce the live `/rest/search?expand=metadata` shape captured
on 2026-09-11: a bare JSON array of DSpace items whose bibliographic fields
all live in a `metadata: [{key, value, language, schema, element, qualifier}]`
list with repeated keys.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from hyperresearch.scholar import base
from hyperresearch.scholar.base import ProviderError
from hyperresearch.scholar.providers.doab import DoabProvider, _sanitize


def _md(key: str, value: Any) -> dict[str, Any]:
    schema, _, rest = key.partition(".")
    element, _, qualifier = rest.partition(".")
    return {
        "key": key,
        "value": value,
        "language": None,
        "schema": schema,
        "element": element,
        "qualifier": qualifier or None,
    }


def _item(
    handle: str | None, name: str | None, *metadata: dict[str, Any], **overrides: Any
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "uuid": "924da6a6-e9f9-4489-9e46-3e3ad212ffe0",
        "name": name,
        "handle": handle,
        "type": "item",
        "expand": ["parentCollection", "parentCollectionList", "parentCommunityList", "all"],
        "lastModified": "2026-08-22 17:36:15.68",
        "parentCollection": None,
        "parentCollectionList": None,
        "parentCommunityList": None,
        "bitstreams": None,
        "withdrawn": "false",
        "archived": "true",
        "link": "/rest/items/924da6a6-e9f9-4489-9e46-3e3ad212ffe0",
        "metadata": list(metadata),
    }
    item.update(overrides)
    return item


# A monograph with a DOI, a publisher, a series, an OAPEN cross-reference and
# the usual grab-bag `dc.identifier` values.
BOOK = _item(
    "20.500.12854/87866",
    "Prisms of Work",
    _md("dc.contributor.author", "Rösser, Michael"),
    _md("dc.date.accessioned", "2024-02-23T10:12:01Z"),
    _md("dc.date.issued", "2024"),
    _md("dc.identifier", "ONIX_20240223_9783111218090_64"),
    _md("dc.identifier", "OCN: 1415898335"),
    _md("dc.identifier", "https://library.oapen.org/handle/20.500.12657/87866"),
    _md("dc.identifier.uri", "https://directory.doabooks.org/handle/20.500.12854/87866"),
    _md(
        "dc.description.abstract",
        "Labour  relations on the German East African\nrailway, 1890-1918.",
    ),
    _md("dc.language", "English"),
    _md("dc.relation.ispartofseries", "Work in Global and Historical Perspective"),
    _md("dc.subject.classification", "thema EDItEUR::N History and Archaeology"),
    _md("dc.subject.other", "colonialism"),
    _md("dc.title", "Prisms of Work"),
    _md("dc.type", "book"),
    _md("oapen.identifier.doi", "10.1515/9783111218090"),
    _md("oapen.relation.isPublishedBy", "https://directory.doabooks.org/handle/20.500.12854/25750"),
    _md("publisher.name", "De Gruyter"),
    _md("publisher.country", "Germany"),
)

# A chapter-granularity deposit from an Italian university press.
CHAPTER = _item(
    "20.500.12854/96379",
    "Chapter Georg Simmel e la filosofia del lavoro",
    _md("dc.contributor.author", "Cristante, Stefano"),
    _md("dc.date.issued", "2022"),
    _md("dc.identifier.uri", "https://directory.doabooks.org/handle/20.500.12854/96379"),
    _md("dc.title", "Chapter Georg Simmel e la filosofia del lavoro"),
    _md("dc.type", "chapter"),
    _md("dc.language", "Italian"),
    _md("oapen.identifier.doi", "10.36253/978-88-5518-596-2.05"),
    _md("publisher.name", "Firenze University Press"),
)


def _stub(monkeypatch: pytest.MonkeyPatch, payload: Any, calls: list[str] | None = None) -> None:
    """Stub the raw HTTP seam.

    `payload` is JSON-serialisable (serialised), a raw string (malformed-body
    tests), None (upstream failure), or a callable taking the URL and
    returning one of those, for paging tests.
    """

    def fake_get(url: str, headers: dict[str, str] | None = None) -> str | None:
        if calls is not None:
            calls.append(url)
        body = payload(url) if callable(payload) else payload
        if body is None or isinstance(body, str):
            return body
        return json.dumps(body)

    monkeypatch.setattr(base, "_http_get", fake_get)
    monkeypatch.setattr(base, "_throttle", lambda url: None)


class TestParsing:
    def test_maps_every_contract_field(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _stub(monkeypatch, [BOOK])
        (paper,) = DoabProvider().search(None, "labour history", 10)
        assert paper.title == "Prisms of Work"
        assert paper.source == "doab"
        assert paper.work_type == "book"
        assert paper.doi == "10.1515/9783111218090"
        assert paper.identifier == "20.500.12854/87866"
        assert paper.url == "https://directory.doabooks.org/handle/20.500.12854/87866"
        assert paper.year == 2024
        assert paper.authors == ("Rösser, Michael",)
        assert paper.venue == "De Gruyter"
        # Internal whitespace and the newline are collapsed.
        assert paper.abstract == "Labour relations on the German East African railway, 1890-1918."
        assert paper.pdf_url is None
        assert paper.citation_count is None
        assert paper.extra["language"] == "English"
        assert paper.extra["series"] == "Work in Global and Historical Perspective"
        assert paper.extra["oapen_url"] == "https://library.oapen.org/handle/20.500.12657/87866"
        assert paper.extra["doab_type"] == "book"
        assert "editors" not in paper.extra

    def test_chapter_maps_to_book_chapter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _stub(monkeypatch, [CHAPTER])
        (paper,) = DoabProvider().search(None, "simmel", 10)
        assert paper.work_type == "book-chapter"
        assert paper.doi == "10.36253/978-88-5518-596-2.05"
        assert paper.venue == "Firenze University Press"

    def test_unknown_type_defaults_to_book(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _stub(monkeypatch, [_item("h/1", "T", _md("dc.title", "T"), _md("dc.type", "monograph"))])
        (paper,) = DoabProvider().search(None, "q", 5)
        assert paper.work_type == "book"

    def test_edited_volume_falls_back_to_editors(self, monkeypatch: pytest.MonkeyPatch) -> None:
        item = _item(
            "h/2",
            "Gender Roles vs. Gender Equality",
            _md("dc.title", "Gender Roles vs. Gender Equality"),
            _md("dc.contributor.editor", "Yang, Mimi"),
            _md("dc.type", "book"),
        )
        _stub(monkeypatch, [item])
        (paper,) = DoabProvider().search(None, "gender", 5)
        assert paper.authors == ("Yang, Mimi",)
        assert paper.extra["editors"] == "Yang, Mimi"
        assert paper.extra["authors_are_editors"] == "true"

    def test_authors_win_over_editors_when_both_present(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        item = _item(
            "h/3",
            "T",
            _md("dc.title", "T"),
            _md("dc.contributor.author", "A. Author"),
            _md("dc.contributor.author", "B. Author"),
            _md("dc.contributor.editor", "E. Editor"),
        )
        _stub(monkeypatch, [item])
        (paper,) = DoabProvider().search(None, "q", 5)
        assert paper.authors == ("A. Author", "B. Author")
        assert paper.extra["editors"] == "E. Editor"
        assert "authors_are_editors" not in paper.extra

    def test_doi_falls_back_to_identifier_grab_bag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        item = _item(
            "h/4",
            "T",
            _md("dc.title", "T"),
            _md("dc.identifier", "341390"),
            _md("dc.identifier", "OCN: 670411651"),
            _md("dc.identifier", "https://doi.org/10.7765/9781526137807"),
        )
        _stub(monkeypatch, [item])
        (paper,) = DoabProvider().search(None, "q", 5)
        assert paper.doi == "10.7765/9781526137807"
        # Bare numeric identifiers must never be mistaken for DOIs.
        assert paper.identifier == "h/4"

    def test_identifier_falls_back_to_doi_without_handle(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        item = _item(None, "T", _md("dc.title", "T"), _md("oapen.identifier.doi", "10.1/x"))
        _stub(monkeypatch, [item])
        (paper,) = DoabProvider().search(None, "q", 5)
        assert paper.identifier == "10.1/x"
        assert paper.url is None

    def test_url_is_built_from_handle_when_uri_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _stub(monkeypatch, [_item("20.500.12854/9936", "T", _md("dc.title", "T"))])
        (paper,) = DoabProvider().search(None, "q", 5)
        assert paper.url == "https://directory.doabooks.org/handle/20.500.12854/9936"

    def test_download_url_is_pdf_url_only_when_it_is_a_pdf(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pdf = _item(
            "h/5",
            "T",
            _md("dc.title", "T"),
            _md(
                "oapen.identifier.downloadUrl",
                "https://library.oapen.org/bitstream/20.500.12657/35004/1/341390.PDF?sequence=1",
            ),
        )
        landing = _item(
            "h/6",
            "U",
            _md("dc.title", "U"),
            _md("oapen.identifier.downloadUrl", "https://doi.org/10.5771/9783957104090"),
        )
        _stub(monkeypatch, [pdf, landing])
        first, second = DoabProvider().search(None, "q", 5)
        assert first.pdf_url == (
            "https://library.oapen.org/bitstream/20.500.12657/35004/1/341390.PDF?sequence=1"
        )
        assert "fulltext_url" not in first.extra
        assert second.pdf_url is None
        assert second.extra["fulltext_url"] == "https://doi.org/10.5771/9783957104090"

    def test_title_falls_back_to_name(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _stub(monkeypatch, [_item("h/7", "From name field", _md("dc.type", "book"))])
        (paper,) = DoabProvider().search(None, "q", 5)
        assert paper.title == "From name field"

    def test_untitled_and_withdrawn_and_non_items_are_dropped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        untitled = _item("h/8", None, _md("dc.type", "book"))
        withdrawn = _item("h/9", "Gone", _md("dc.title", "Gone"), withdrawn="true")
        collection = _item(
            "h/10", "A collection", _md("dc.title", "A collection"), type="collection"
        )
        keep = _item("h/11", "Keep", _md("dc.title", "Keep"))
        _stub(monkeypatch, [untitled, withdrawn, collection, keep, "not a dict", 42])
        papers = DoabProvider().search(None, "q", 10)
        assert [p.title for p in papers] == ["Keep"]

    def test_null_and_malformed_metadata_entries_are_skipped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        item = _item(
            "h/12",
            "T",
            _md("dc.title", "T"),
            _md("dc.contributor.author", None),
            _md("dc.contributor.author", "   "),
            {"value": "no key"},
            "not even a dict",
            _md("dc.date.issued", "not a year"),
        )
        _stub(monkeypatch, [item])
        (paper,) = DoabProvider().search(None, "q", 5)
        assert paper.authors == ()
        assert paper.year is None

    def test_metadata_absent_entirely(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # The un-expanded shape: name null, metadata absent. Unusable but must
        # not crash — it is what a caller who drops `expand=metadata` gets.
        _stub(monkeypatch, [{"uuid": "x", "name": None, "handle": "h/13", "type": "item"}])
        assert DoabProvider().search(None, "q", 5) == []


class TestRequest:
    def test_url_shape_and_accept_header(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: dict[str, Any] = {}

        def fake_get(url: str, headers: dict[str, str] | None = None) -> str | None:
            seen["url"] = url
            seen["headers"] = headers
            return "[]"

        monkeypatch.setattr(base, "_http_get", fake_get)
        monkeypatch.setattr(base, "_throttle", lambda url: None)
        DoabProvider().search(None, "labour history", 5)
        assert seen["url"] == (
            "https://directory.doabooks.org/rest/search"
            "?query=labour%20history&expand=metadata&limit=5&offset=0"
        )
        assert seen["headers"] == {"Accept": "application/json"}

    def test_empty_query_is_a_provider_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []
        _stub(monkeypatch, [], calls)
        with pytest.raises(ProviderError):
            DoabProvider().search(None, "   ", 5)
        # A query that is nothing but Solr syntax is empty once sanitised.
        with pytest.raises(ProviderError):
            DoabProvider().search(None, "(*)", 5)
        assert calls == []

    @pytest.mark.parametrize(
        ("raw", "clean"),
        [
            ("labour history", "labour history"),
            ("war AND peace", "war and peace"),
            ("post-colonial theory", "post-colonial theory"),
            ("dc.type:book", "dc.type book"),
            ("(unbalanced", "unbalanced"),
            ('"civil war"', '"civil war"'),
            ('"odd quote', "odd quote"),
            ("wild*card ~fuzz ^boost", "wild card fuzz boost"),
            ("  padded   query  ", "padded query"),
        ],
    )
    def test_sanitize(self, raw: str, clean: str) -> None:
        assert _sanitize(raw) == clean

    def test_pages_in_chunks_and_stops_on_short_page(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []

        def by_offset(url: str) -> list[dict[str, Any]]:
            if "offset=0" in url:
                return [_item(f"h/{i}", f"T{i}", _md("dc.title", f"T{i}")) for i in range(20)]
            if "offset=20" in url:
                return [_item("h/20", "T20", _md("dc.title", "T20"))]
            raise AssertionError(f"unexpected page request {url}")

        _stub(monkeypatch, by_offset, calls)
        papers = DoabProvider().search(None, "q", 60)
        assert len(papers) == 21
        assert len(calls) == 2
        assert "limit=20&offset=0" in calls[0]
        assert "limit=20&offset=20" in calls[1]

    def test_last_page_asks_only_for_the_remainder(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []
        full = [_item(f"h/{i}", f"T{i}", _md("dc.title", f"T{i}")) for i in range(20)]
        _stub(monkeypatch, lambda url: full if "offset=0" in url else full[:5], calls)
        papers = DoabProvider().search(None, "q", 25)
        assert len(papers) == 25
        assert "limit=5&offset=20" in calls[1]

    def test_limit_is_clamped_to_ceiling(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []
        full = [_item(f"h/{i}", f"T{i}", _md("dc.title", f"T{i}")) for i in range(20)]
        _stub(monkeypatch, full, calls)
        papers = DoabProvider().search(None, "q", 10_000)
        assert len(papers) == 100
        assert len(calls) == 5

    def test_offset_advances_by_raw_count_not_kept_count(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Withdrawn records still occupy upstream positions; skipping them
        # must not cause the next page to re-read the same slice.
        calls: list[str] = []
        page = [
            _item(f"h/{i}", f"T{i}", _md("dc.title", f"T{i}"), withdrawn="true") for i in range(20)
        ]
        _stub(monkeypatch, lambda url: page if "offset=0" in url else [], calls)
        assert DoabProvider().search(None, "q", 40) == []
        assert "offset=20" in calls[1]


class TestFailurePaths:
    def test_upstream_failure_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _stub(monkeypatch, None)
        assert DoabProvider().search(None, "q", 5) == []

    def test_malformed_body_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _stub(monkeypatch, "<html><title>Just a moment...</title></html>")
        assert DoabProvider().search(None, "q", 5) == []

    def test_json_object_instead_of_array_returns_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # DSpace error envelopes are objects; a Cloudflare challenge is HTML.
        _stub(monkeypatch, {"error": "Internal Server Error", "status": 500})
        assert DoabProvider().search(None, "q", 5) == []

    def test_no_results_is_empty_not_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _stub(monkeypatch, [])
        assert DoabProvider().search(None, "zzzqqx", 5) == []

    def test_failure_mid_walk_keeps_first_page(self, monkeypatch: pytest.MonkeyPatch) -> None:
        full = [_item(f"h/{i}", f"T{i}", _md("dc.title", f"T{i}")) for i in range(20)]
        _stub(monkeypatch, lambda url: full if "offset=0" in url else None)
        assert len(DoabProvider().search(None, "q", 40)) == 20


def test_registry_metadata() -> None:
    provider = DoabProvider()
    assert provider.slug == "doab"
    assert provider.needs_key is False
    assert provider.key_env == ()
    assert provider.available() is True
    assert provider.unavailable_reason() is None
