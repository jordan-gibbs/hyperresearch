"""CORE discovery provider — offline, the HTTP seam stubbed.

The fixture record is a lightly trimmed copy of what `GET /v3/search/works/`
returned live, quirks included: `downloadUrl` as an empty string, a `journals`
entry whose title is null, a null `documentType` with the real classification
in `fieldOfStudy`, duplicated author orderings, and a `sourceFulltextUrls`
entry pointing at a PDF that does not end in `.pdf`.
"""

from __future__ import annotations

import json

import pytest

from hyperresearch.scholar import base
from hyperresearch.scholar.providers import core_oa
from hyperresearch.scholar.providers.core_oa import CoreProvider

PLOS_RECORD = {
    "id": 84982915,
    "title": "Quantifying organismal complexity using a population genetic approach.",
    "doi": "10.1371/journal.pone.0000217",
    "yearPublished": 2007,
    "publishedDate": "2007-02-14T00:00:00+00:00",
    "publisher": "Public Library of Science (PLoS)",
    "abstract": "Organismal complexity is hard to measure. We propose a population genetic approach.",
    "authors": [
        {"name": "Olivier Tenaillon"},
        {"name": "Silander, Olin K."},
        {"name": "Olin K Silander"},
        {"name": "Olivier Tenaillon"},
    ],
    "citationCount": 0,
    "documentType": None,
    "fieldOfStudy": "article",
    "downloadUrl": "",
    "sourceFulltextUrls": ["http://europepmc.org/articles/PMC1790863?pdf=render"],
    "journals": [{"title": None, "identifiers": []}],
    "links": [{"type": "display", "url": "https://core.ac.uk/works/84982915"}],
    "dataProviders": [{"id": 1, "name": "DOAJ", "url": "https://api.core.ac.uk/v3/data-providers/1"}],
    "identifiers": [{"identifier": "10.1371/journal.pone.0000217", "type": "doi"}],
}

IEEE_RECORD = {
    "id": 143427938,
    "title": "3D CATBraTS: Channel Attention Transformer for Brain Tumour Semantic Segmentation",
    "doi": "https://doi.org/10.1109/CBMS58004.2023.00267",
    "yearPublished": 2023,
    "publisher": "IEEE",
    "abstract": "Brain tumour diagnosis is a challenging task.",
    "authors": [{"name": "Bonmati Coll, E."}, {"name": "Psarrou, A."}],
    "citationCount": 4,
    "documentType": None,
    "fieldOfStudy": "conference-paper",
    "downloadUrl": "https://core.ac.uk/download/567595624.pdf",
    "sourceFulltextUrls": ["https://core.ac.uk/download/567595624.pdf"],
    "journals": [{"title": "Proc. IEEE CBMS", "identifiers": []}],
    "links": [
        {"type": "download", "url": "https://core.ac.uk/download/567595624.pdf"},
        {"type": "reader", "url": "https://core.ac.uk/reader/567595624"},
    ],
    "dataProviders": [{"id": 138, "name": "WestminsterResearch"}],
}

ENVELOPE = {"totalHits": 2, "limit": 10, "offset": 0, "results": [PLOS_RECORD, IEEE_RECORD]}


@pytest.fixture
def keyed(monkeypatch):
    monkeypatch.setenv("CORE_API_KEY", "test-key")


@pytest.fixture
def no_key(monkeypatch):
    monkeypatch.delenv("CORE_API_KEY", raising=False)


def _stub(monkeypatch, body):
    """Stub the package's single network seam; record what was requested."""
    calls: list[tuple[str, dict[str, str] | None]] = []

    def fake_get(url: str, headers: dict[str, str] | None = None) -> str | None:
        calls.append((url, headers))
        return body

    monkeypatch.setattr(base, "_http_get", fake_get)
    monkeypatch.setattr(base, "_throttle", lambda url: None)
    return calls


class TestAvailability:
    def test_class_attributes(self):
        p = CoreProvider()
        assert p.slug == "core"
        assert p.needs_key is True
        assert p.key_env == ("CORE_API_KEY",)

    def test_unavailable_without_key(self, no_key):
        p = CoreProvider()
        assert p.available() is False
        assert "CORE_API_KEY" in (p.unavailable_reason() or "")

    def test_available_with_key(self, keyed):
        assert CoreProvider().available() is True

    def test_search_without_key_raises_provider_error(self, no_key, monkeypatch):
        """Per the SearchProvider contract: could-not-attempt is ProviderError,
        not an empty list that reads as "CORE has nothing"."""
        calls = _stub(monkeypatch, json.dumps(ENVELOPE))
        with pytest.raises(base.ProviderError):
            CoreProvider().search(None, "widgets", 5)
        assert calls == []


class TestRequest:
    def test_url_and_bearer_header(self, keyed, monkeypatch):
        calls = _stub(monkeypatch, json.dumps(ENVELOPE))
        CoreProvider().search(None, "brain tumour segmentation", 5)
        assert len(calls) == 1
        url, headers = calls[0]
        assert url.startswith("https://api.core.ac.uk/v3/search/works/?q=")
        assert "brain%20tumour%20segmentation" in url
        assert "limit=5" in url
        assert "exclude=fullText" in url  # metadata search must not haul bodies
        assert headers == {"Authorization": "Bearer test-key"}
        assert "test-key" not in url  # the key never lands in the cache key

    def test_limit_is_clamped_to_core_page_cap(self, keyed, monkeypatch):
        calls = _stub(monkeypatch, json.dumps(ENVELOPE))
        CoreProvider().search(None, "x", 5000)
        assert "limit=100" in calls[0][0]

    def test_doi_search_url_uses_fielded_query(self):
        url = core_oa.doi_search_url("10.1371/journal.pone.0000217")
        assert "q=doi%3A%2210.1371%2Fjournal.pone.0000217%22" in url
        assert "limit=1" in url

    def test_work_url(self):
        assert core_oa.work_url("84982915") == "https://api.core.ac.uk/v3/works/84982915"


class TestMapping:
    @pytest.fixture
    def papers(self, keyed, monkeypatch):
        _stub(monkeypatch, json.dumps(ENVELOPE))
        return CoreProvider().search(None, "anything", 10)

    def test_two_records_two_papers(self, papers):
        assert [p.source for p in papers] == ["core", "core"]

    def test_plos_record(self, papers):
        p = papers[0]
        assert p.title.startswith("Quantifying organismal complexity")
        assert p.doi == "10.1371/journal.pone.0000217"
        assert p.year == 2007
        assert p.identifier == "84982915"
        assert p.url == "https://core.ac.uk/works/84982915"  # the display link wins
        # Exact duplicates collapse; different orderings of a name do not.
        assert p.authors == ("Olivier Tenaillon", "Silander, Olin K.", "Olin K Silander")
        # journals[0].title is null, so the publisher is the venue.
        assert p.venue == "Public Library of Science (PLoS)"
        assert p.abstract.startswith("Organismal complexity")
        # downloadUrl is "", so the query-string PDF from the source list is used.
        assert p.pdf_url == "http://europepmc.org/articles/PMC1790863?pdf=render"
        assert p.citation_count == 0  # reported as CORE reports it
        assert p.work_type == "article"
        assert p.extra["core_id"] == "84982915"
        assert p.extra["field_of_study"] == "article"
        assert p.extra["data_provider"] == "DOAJ"
        assert "document_type" not in p.extra  # it was null

    def test_ieee_record(self, papers):
        p = papers[1]
        assert p.doi == "10.1109/cbms58004.2023.00267"  # doi.org prefix stripped, lowercased
        assert p.venue == "Proc. IEEE CBMS"
        assert p.pdf_url == "https://core.ac.uk/download/567595624.pdf"
        assert p.citation_count == 4
        # No display link: fall back to the CORE-hosted download.
        assert p.url == "https://core.ac.uk/download/567595624.pdf"
        assert p.work_type == "article"  # conference-paper maps to article

    def test_work_type_vocabulary(self):
        assert core_oa.paper_from_record({"title": "T", "documentType": "thesis"}).work_type == "thesis"
        assert core_oa.paper_from_record({"title": "T", "fieldOfStudy": "preprint"}).work_type == "preprint"
        assert core_oa.paper_from_record({"title": "T", "documentType": "slides"}).work_type == "other"
        assert core_oa.paper_from_record({"title": "T", "documentType": "zzz"}).work_type == "article"

    def test_record_without_title_is_dropped(self):
        assert core_oa.paper_from_record({"id": 1, "doi": "10.1/x"}) is None
        assert core_oa.paper_from_record({"id": 1, "title": "   "}) is None

    def test_minimal_record_falls_back_to_core_page_then_doi(self):
        assert core_oa.paper_from_record({"title": "T", "id": 7}).url == "https://core.ac.uk/works/7"
        assert core_oa.paper_from_record({"title": "T", "doi": "10.1/x"}).url == "https://doi.org/10.1/x"
        assert core_oa.paper_from_record({"title": "T"}).url is None

    def test_year_falls_back_to_published_date(self):
        p = core_oa.paper_from_record({"title": "T", "publishedDate": "2019-05-01T00:00:00+00:00"})
        assert p.year == 2019

    def test_citation_count_rejects_non_ints(self):
        assert core_oa.paper_from_record({"title": "T", "citationCount": "12"}).citation_count is None
        assert core_oa.paper_from_record({"title": "T", "citationCount": True}).citation_count is None
        assert core_oa.paper_from_record({"title": "T", "citationCount": -1}).citation_count is None

    def test_authors_tolerate_bare_strings_and_junk(self):
        p = core_oa.paper_from_record({"title": "T", "authors": ["A. Smith", {"name": ""}, 3, None]})
        assert p.authors == ("A. Smith",)


class TestFullText:
    def test_real_text_passes_through(self):
        assert core_oa.full_text_from_work({"fullText": "  The body.  "}) == "The body."

    def test_public_tier_sentinel_is_not_text(self):
        """Unauthenticated callers get a real string in `fullText`. It must
        never be mistaken for a paper."""
        assert core_oa.full_text_from_work({"fullText": "Not available for public API users."}) is None
        assert core_oa.full_text_from_work({"fullText": "NOT AVAILABLE FOR PUBLIC API USERS"}) is None

    def test_missing_or_empty_is_none(self):
        assert core_oa.full_text_from_work({"fullText": ""}) is None
        assert core_oa.full_text_from_work({"fullText": None}) is None
        assert core_oa.full_text_from_work({}) is None
        assert core_oa.full_text_from_work("nope") is None

    def test_looks_like_pdf(self):
        assert core_oa.looks_like_pdf("https://core.ac.uk/download/1.pdf")
        assert core_oa.looks_like_pdf("https://core.ac.uk/download/1.PDF?x=1")
        assert core_oa.looks_like_pdf("http://europepmc.org/articles/PMC1?pdf=render")
        assert not core_oa.looks_like_pdf("https://repo.example.org/handle/123")


class TestFailurePaths:
    """`search()` is total: every upstream failure is an empty list."""

    def test_upstream_none(self, keyed, monkeypatch):
        _stub(monkeypatch, None)
        assert CoreProvider().search(None, "x", 5) == []

    def test_not_json(self, keyed, monkeypatch):
        _stub(monkeypatch, "<html>rate limited</html>")
        assert CoreProvider().search(None, "x", 5) == []

    @pytest.mark.parametrize(
        "body",
        [
            "[]",
            '"a string"',
            "{}",
            '{"results": null}',
            '{"results": "not a list"}',
            '{"results": [null, 3, "x", []]}',
            '{"results": [{"id": 1}]}',  # a record with no title
        ],
    )
    def test_malformed_envelopes(self, keyed, monkeypatch, body):
        _stub(monkeypatch, body)
        assert CoreProvider().search(None, "x", 5) == []

    def test_partial_garbage_keeps_the_good_records(self, keyed, monkeypatch):
        _stub(monkeypatch, json.dumps({"results": [None, PLOS_RECORD, {"title": None}]}))
        out = CoreProvider().search(None, "x", 5)
        assert len(out) == 1 and out[0].identifier == "84982915"

    def test_uses_the_shared_cache(self, keyed, tmp_vault, monkeypatch):
        calls = _stub(monkeypatch, json.dumps(ENVELOPE))
        CoreProvider().search(tmp_vault.db, "x", 5)
        CoreProvider().search(tmp_vault.db, "x", 5)
        assert len(calls) == 1
        CoreProvider().search(tmp_vault.db, "x", 5, fresh=True)
        assert len(calls) == 2
