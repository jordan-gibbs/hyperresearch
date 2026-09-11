"""CORE as the third open-access resolver — offline, HTTP and DNS stubbed.

Two network seams are stubbed: `core.scholar._http_get_json` for Unpaywall
and Europe PMC (as in `test_oa_recovery.py`) and `scholar.base._http_get` for
CORE, which needs a bearer header that the older layer cannot send.
"""

from __future__ import annotations

import json
from typing import ClassVar

import pytest

from hyperresearch.core import oa, scholar
from hyperresearch.core.config import ScholarSettings
from hyperresearch.scholar import base
from hyperresearch.web.base import WebResult

ABSTRACT = "This paper studies widgets. " * 40  # ~1080 chars
FULL_TEXT = ("Section text about widgets and their measurement. " * 900).strip()  # ~45k chars
PDF_TEXT = ("Extracted from the PDF instead. " * 900).strip()

DOI = "10.1371/journal.pone.0000217"
WORK_URL = "https://api.core.ac.uk/v3/works/84982915"
DOWNLOAD_URL = "https://core.ac.uk/download/567595624.pdf"
SOURCE_PDF = "http://europepmc.org/articles/PMC1790863?pdf=render"
SOURCE_PAGE = "https://repo.example.org/handle/1234"

EPMC_HIT = {
    "resultList": {
        "result": [{"pmcid": "PMC12345", "isOpenAccess": "Y", "inEPMC": "Y", "license": "cc-by"}]
    }
}
UNPAYWALL_PDF = {
    "is_oa": True,
    "best_oa_location": {
        "url_for_pdf": "https://repo.example.org/record/1.pdf",
        "version": "publishedVersion",
        "license": "cc-by",
        "host_type": "repository",
    },
}


def _record(**overrides):
    rec = {
        "id": 84982915,
        "title": "Quantifying organismal complexity using a population genetic approach.",
        "doi": DOI,
        "yearPublished": 2007,
        "documentType": None,
        "fieldOfStudy": "article",
        "downloadUrl": DOWNLOAD_URL,
        "sourceFulltextUrls": [SOURCE_PDF, SOURCE_PAGE],
        "links": [{"type": "display", "url": "https://core.ac.uk/works/84982915"}],
    }
    rec.update(overrides)
    return rec


def _search_hit(rec=None):
    return {"totalHits": 1, "limit": 1, "offset": 0, "results": [rec or _record()]}


def _work(text=FULL_TEXT, **overrides):
    return _record(fullText=text, **overrides)


def _result(content: str, url: str = "https://publisher.example.com/doi/10.1/x", **kw) -> WebResult:
    return WebResult(url=url, title=kw.pop("title", "A Paper"), content=content, **kw)


@pytest.fixture
def public_dns(monkeypatch):
    monkeypatch.setattr(
        oa.socket, "getaddrinfo", lambda host, port: [(2, 1, 6, "", ("93.184.216.34", 0))]
    )


@pytest.fixture
def keyed(monkeypatch):
    monkeypatch.setenv("CORE_API_KEY", "test-key")


@pytest.fixture
def no_key(monkeypatch):
    monkeypatch.delenv("CORE_API_KEY", raising=False)


@pytest.fixture
def vault(tmp_vault):
    """A stock install: no contact email, so Unpaywall is off."""
    tmp_vault.config.scholar = ScholarSettings()
    return tmp_vault


def _stub_legacy(monkeypatch, responses: dict[str, dict | None]):
    """Unpaywall / Europe PMC seam, keyed by URL substring."""
    calls: list[str] = []

    def fake_get(url: str):
        calls.append(url)
        for key, value in responses.items():
            if key in url:
                return value
        return None

    monkeypatch.setattr(scholar, "_http_get_json", fake_get)
    return calls


def _stub_core(monkeypatch, responses: dict[str, object]):
    """CORE seam, keyed by URL substring. A value may be a dict (JSON body),
    a raw string, None (dead upstream), or an Exception to raise."""
    calls: list[tuple[str, dict[str, str] | None]] = []

    def fake_get(url: str, headers: dict[str, str] | None = None) -> str | None:
        calls.append((url, headers))
        for key, value in responses.items():
            if key in url:
                if isinstance(value, Exception):
                    raise value
                if value is None or isinstance(value, str):
                    return value
                return json.dumps(value)
        return None

    monkeypatch.setattr(base, "_http_get", fake_get)
    monkeypatch.setattr(base, "_throttle", lambda url: None)
    return calls


def _stub_pdf(monkeypatch, returned):
    from hyperresearch.web import crawl4ai_provider

    tried: list[str] = []

    def fake(url, settings):
        tried.append(url)
        return returned(url) if callable(returned) else returned

    monkeypatch.setattr(crawl4ai_provider, "_fetch_pdf", fake)
    return tried


class TestChainOrder:
    """CORE is the broad net BEHIND the two resolvers that know which version
    they are serving. It must only be consulted once both have missed."""

    def test_unpaywall_hit_never_reaches_core(self, tmp_vault, monkeypatch, keyed):
        _stub_legacy(monkeypatch, {"unpaywall": UNPAYWALL_PDF})
        core_calls = _stub_core(monkeypatch, {"search/works": _search_hit()})
        loc = oa.resolve_oa(tmp_vault.db, DOI, 30, email="a@b.co")
        assert loc.resolver == "unpaywall"
        assert core_calls == []

    def test_epmc_hit_never_reaches_core(self, tmp_vault, monkeypatch, keyed):
        _stub_legacy(monkeypatch, {"europepmc": EPMC_HIT})
        core_calls = _stub_core(monkeypatch, {"search/works": _search_hit()})
        loc = oa.resolve_oa(tmp_vault.db, DOI, 30, email=None)
        assert loc.resolver == "europepmc"
        assert core_calls == []

    def test_core_after_both_miss(self, tmp_vault, monkeypatch, keyed):
        legacy = _stub_legacy(monkeypatch, {"unpaywall": {"is_oa": False}})
        core_calls = _stub_core(monkeypatch, {"search/works": _search_hit()})
        loc = oa.resolve_oa(tmp_vault.db, DOI, 30, email="a@b.co")
        assert loc.resolver == "core"
        assert any("unpaywall" in c for c in legacy)
        assert any("europepmc" in c for c in legacy)
        assert len(core_calls) == 1

    def test_core_candidates_come_after_every_unpaywall_and_epmc_candidate(
        self, tmp_vault, monkeypatch, keyed
    ):
        payload = {
            "is_oa": True,
            "oa_locations": [
                {"url_for_pdf": "https://a.example.org/a.pdf", "version": "publishedVersion"},
                {"url": "https://a.example.org/landing", "version": "publishedVersion"},
            ],
        }
        _stub_legacy(monkeypatch, {"unpaywall": payload, "europepmc": EPMC_HIT})
        _stub_core(monkeypatch, {"search/works": _search_hit()})
        chain = [
            loc.resolver
            for loc in oa.iter_oa_candidates(tmp_vault.db, DOI, 30, email="a@b.co")
        ]
        assert chain == ["unpaywall", "unpaywall", "europepmc", "core", "core", "core", "core"]

    def test_arxiv_ids_still_declined(self, tmp_vault, monkeypatch, keyed):
        _stub_legacy(monkeypatch, {})
        core_calls = _stub_core(monkeypatch, {"search/works": _search_hit()})
        assert oa.resolve_oa(tmp_vault.db, "arXiv:2501.00001", 30) is None
        assert core_calls == []


class TestKeyGating:
    def test_no_key_skips_core_silently(self, tmp_vault, monkeypatch, no_key):
        """Exactly like Unpaywall without an email: no call, no error, no noise."""
        _stub_legacy(monkeypatch, {})
        core_calls = _stub_core(monkeypatch, {"search/works": _search_hit()})
        assert oa.resolve_oa(tmp_vault.db, DOI, 30) is None
        assert core_calls == []

    def test_no_key_leaves_recovery_untouched(self, vault, monkeypatch, no_key, public_dns):
        _stub_legacy(monkeypatch, {})
        core_calls = _stub_core(monkeypatch, {"search/works": _search_hit(), "/works/": _work()})
        original = _result(ABSTRACT)
        out, loc = oa.recover_full_text(vault, None, "https://p/x", DOI, original)
        assert out is original and loc is None
        assert core_calls == []

    def test_blank_key_counts_as_absent(self, tmp_vault, monkeypatch):
        monkeypatch.setenv("CORE_API_KEY", "   ")
        _stub_legacy(monkeypatch, {})
        core_calls = _stub_core(monkeypatch, {"search/works": _search_hit()})
        assert oa.resolve_oa(tmp_vault.db, DOI, 30) is None
        assert core_calls == []

    def test_key_travels_as_bearer_header_not_in_url(self, tmp_vault, monkeypatch, keyed):
        _stub_legacy(monkeypatch, {})
        core_calls = _stub_core(monkeypatch, {"search/works": _search_hit()})
        oa.resolve_oa(tmp_vault.db, DOI, 30)
        url, headers = core_calls[0]
        assert headers == {"Authorization": "Bearer test-key"}
        assert "test-key" not in url


class TestCandidates:
    def test_order_is_text_then_core_pdf_then_source_copies(self, tmp_vault, monkeypatch, keyed):
        _stub_legacy(monkeypatch, {})
        _stub_core(monkeypatch, {"search/works": _search_hit()})
        locs = list(oa.iter_oa_candidates(tmp_vault.db, DOI, 30))
        assert [(c.kind, c.url) for c in locs] == [
            ("coretext", WORK_URL),
            ("pdf", DOWNLOAD_URL),
            ("pdf", SOURCE_PDF),
            ("page", SOURCE_PAGE),
        ]
        assert all(c.resolver == "core" for c in locs)
        assert all(c.host_type == "repository" for c in locs)

    def test_empty_download_url_and_duplicates_are_skipped(self, tmp_vault, monkeypatch, keyed):
        """Live CORE returns `downloadUrl: ""` and repeats it in
        `sourceFulltextUrls`; neither may produce a candidate twice."""
        rec = _record(downloadUrl="", sourceFulltextUrls=[DOWNLOAD_URL, DOWNLOAD_URL, ""])
        _stub_legacy(monkeypatch, {})
        _stub_core(monkeypatch, {"search/works": _search_hit(rec)})
        locs = list(oa.iter_oa_candidates(tmp_vault.db, DOI, 30))
        assert [(c.kind, c.url) for c in locs] == [("coretext", WORK_URL), ("pdf", DOWNLOAD_URL)]

    def test_record_without_id_has_no_text_candidate(self, tmp_vault, monkeypatch, keyed):
        rec = _record(id=None, sourceFulltextUrls=[])
        _stub_legacy(monkeypatch, {})
        _stub_core(monkeypatch, {"search/works": _search_hit(rec)})
        locs = list(oa.iter_oa_candidates(tmp_vault.db, DOI, 30))
        assert [c.kind for c in locs] == ["pdf"]

    def test_version_is_unknown_unless_core_says_preprint(self, tmp_vault, monkeypatch, keyed):
        _stub_legacy(monkeypatch, {})
        _stub_core(monkeypatch, {"search/works": _search_hit()})
        loc = oa.resolve_oa(tmp_vault.db, DOI, 30)
        assert loc.version is None  # never assumed to be the version of record
        assert loc.license is None  # CORE's schema has no licence field

    def test_preprint_is_recorded_as_submitted_version(self, tmp_vault, monkeypatch, keyed):
        _stub_legacy(monkeypatch, {})
        _stub_core(monkeypatch, {"search/works": _search_hit(_record(documentType="preprint"))})
        loc = oa.resolve_oa(tmp_vault.db, DOI, 30)
        assert loc.version == "submittedVersion"

    def test_licence_read_only_when_present(self, tmp_vault, monkeypatch, keyed):
        _stub_legacy(monkeypatch, {})
        _stub_core(monkeypatch, {"search/works": _search_hit(_record(license=" cc-by "))})
        assert oa.resolve_oa(tmp_vault.db, DOI, 30).license == "cc-by"


class TestRecovery:
    def test_happy_path_uses_core_plain_text(self, vault, monkeypatch, keyed, public_dns):
        _stub_legacy(monkeypatch, {})
        core_calls = _stub_core(monkeypatch, {"search/works": _search_hit(), "/works/": _work()})
        tried_pdfs = _stub_pdf(monkeypatch, _result(PDF_TEXT))

        out, loc = oa.recover_full_text(vault, None, "https://p.example.com/x", DOI, _result(ABSTRACT))

        assert loc is not None and loc.resolver == "core" and loc.kind == "coretext"
        assert loc.url == WORK_URL
        assert out.content == FULL_TEXT
        assert out.url == WORK_URL
        assert out.title.startswith("Quantifying organismal complexity")  # CORE's title, not the stub's
        assert tried_pdfs == []  # the text came first; the PDF was never needed
        # Both CORE calls carried the key as a bearer header.
        assert [h for _, h in core_calls] == [{"Authorization": "Bearer test-key"}] * 2

    def test_title_falls_back_to_the_original(self, vault, monkeypatch, keyed, public_dns):
        _stub_legacy(monkeypatch, {})
        _stub_core(monkeypatch, {"search/works": _search_hit(), "/works/": _work(title="")})
        out, loc = oa.recover_full_text(vault, None, "https://p/x", DOI, _result(ABSTRACT, title="Kept"))
        assert loc is not None and out.title == "Kept"

    def test_public_tier_sentinel_falls_through_to_the_pdf(self, vault, monkeypatch, keyed, public_dns):
        """An unauthorised-tier key still gets a 200 with a placeholder in
        `fullText`. It must not become a note; the CORE PDF is next."""
        _stub_legacy(monkeypatch, {})
        _stub_core(
            monkeypatch,
            {"search/works": _search_hit(), "/works/": _work("Not available for public API users.")},
        )
        tried = _stub_pdf(monkeypatch, _result(PDF_TEXT))
        out, loc = oa.recover_full_text(vault, None, "https://p/x", DOI, _result(ABSTRACT))
        assert loc.kind == "pdf" and loc.url == DOWNLOAD_URL
        assert out.content == PDF_TEXT
        assert tried == [DOWNLOAD_URL]

    def test_never_shrinks_the_note(self, vault, monkeypatch, keyed, public_dns):
        """Quality can only go up: a body shorter than the abstract loses."""
        _stub_legacy(monkeypatch, {})
        _stub_core(monkeypatch, {"search/works": _search_hit(), "/works/": _work("short")})
        _stub_pdf(monkeypatch, None)
        original = _result(ABSTRACT)
        out, loc = oa.recover_full_text(vault, None, "https://p/x", DOI, original)
        assert out is original and loc is None

    def test_longer_but_still_not_full_text_is_rejected(self, vault, monkeypatch, keyed, public_dns):
        """Longer than the abstract is not enough; it must clear the floor too."""
        _stub_legacy(monkeypatch, {})
        _stub_core(
            monkeypatch,
            {"search/works": _search_hit(), "/works/": _work("Record page prose. " * 100)},  # ~1.9k
        )
        _stub_pdf(monkeypatch, None)
        original = _result(ABSTRACT)
        out, loc = oa.recover_full_text(vault, None, "https://p/x", DOI, original)
        assert out is original and loc is None

    def test_floor_is_the_configured_one(self, vault, monkeypatch, keyed, public_dns):
        vault.config.scholar = ScholarSettings(oa_min_full_text_chars=1500)
        _stub_legacy(monkeypatch, {})
        _stub_core(
            monkeypatch,
            {"search/works": _search_hit(), "/works/": _work("Record page prose. " * 100)},
        )
        _, loc = oa.recover_full_text(vault, None, "https://p/x", DOI, _result(ABSTRACT))
        assert loc is not None and loc.kind == "coretext"

    def test_attempt_cap_is_honoured_across_core_candidates(self, vault, monkeypatch, keyed, public_dns):
        vault.config.scholar = ScholarSettings(oa_max_attempts=1)
        _stub_legacy(monkeypatch, {})
        _stub_core(monkeypatch, {"search/works": _search_hit(), "/works/": _work("short")})
        tried = _stub_pdf(monkeypatch, _result(PDF_TEXT))
        original = _result(ABSTRACT)
        out, loc = oa.recover_full_text(vault, None, "https://p/x", DOI, original)
        assert out is original and loc is None
        assert tried == []  # the one attempt went to the text; the PDF was never reached

    def test_walks_source_copies_when_core_hosted_ones_fail(self, vault, monkeypatch, keyed, public_dns):
        _stub_legacy(monkeypatch, {})
        _stub_core(monkeypatch, {"search/works": _search_hit(), "/works/": None})
        tried = _stub_pdf(monkeypatch, lambda url: _result(PDF_TEXT, url=url) if url == SOURCE_PDF else None)
        out, loc = oa.recover_full_text(vault, None, "https://p/x", DOI, _result(ABSTRACT))
        assert tried == [DOWNLOAD_URL, SOURCE_PDF]
        assert loc.url == SOURCE_PDF and out.content == PDF_TEXT

    def test_landing_page_copy_goes_through_the_provider(self, vault, monkeypatch, keyed, public_dns):
        vault.config.scholar = ScholarSettings(oa_max_attempts=5)
        _stub_legacy(monkeypatch, {})
        _stub_core(monkeypatch, {"search/works": _search_hit(), "/works/": None})
        _stub_pdf(monkeypatch, None)

        class FakeProvider:
            name = "fake"
            seen: ClassVar[list[str]] = []

            def fetch(self, url):
                self.seen.append(url)
                return _result(FULL_TEXT, url=url)

        out, loc = oa.recover_full_text(vault, FakeProvider(), "https://p/x", DOI, _result(ABSTRACT))
        assert FakeProvider.seen == [SOURCE_PAGE]
        assert loc.kind == "page" and out.content == FULL_TEXT

    def test_work_fetch_is_not_cached_but_the_lookup_is(self, vault, monkeypatch, keyed, public_dns):
        """The metadata lookup lands in api_cache; the full text does not —
        the note is the cache for a paper, as with every other resolver."""
        _stub_legacy(monkeypatch, {})
        core_calls = _stub_core(monkeypatch, {"search/works": _search_hit(), "/works/": _work()})
        for _ in range(2):
            _, loc = oa.recover_full_text(vault, None, "https://p/x", DOI, _result(ABSTRACT))
            assert loc is not None
        searches = [u for u, _ in core_calls if "search/works" in u]
        works = [u for u, _ in core_calls if "/v3/works/" in u]
        assert len(searches) == 1
        assert len(works) == 2


class TestSoftFailure:
    """Every CORE failure leaves the caller exactly where it was."""

    @pytest.mark.parametrize(
        "search_response",
        [
            None,
            "<html>502</html>",
            "[]",
            {},
            {"results": None},
            {"results": "x"},
            {"results": []},
            {"results": [None]},
            {"results": [{"id": None, "downloadUrl": None, "sourceFulltextUrls": None}]},
            {"results": [{"title": "No id, no copies"}]},
            RuntimeError("connection reset"),
        ],
    )
    def test_bad_lookup_is_soft(self, vault, monkeypatch, keyed, public_dns, search_response):
        _stub_legacy(monkeypatch, {})
        _stub_core(monkeypatch, {"search/works": search_response, "/works/": _work()})
        _stub_pdf(monkeypatch, None)
        original = _result(ABSTRACT)
        out, loc = oa.recover_full_text(vault, None, "https://p/x", DOI, original)
        assert out is original and loc is None

    @pytest.mark.parametrize(
        "work_response",
        [None, "not json", "[]", {}, {"fullText": None}, {"fullText": 42}, RuntimeError("boom")],
    )
    def test_bad_work_fetch_is_soft(self, vault, monkeypatch, keyed, public_dns, work_response):
        _stub_legacy(monkeypatch, {})
        _stub_core(monkeypatch, {"search/works": _search_hit(), "/works/": work_response})
        _stub_pdf(monkeypatch, None)
        original = _result(ABSTRACT)
        out, loc = oa.recover_full_text(vault, None, "https://p/x", DOI, original)
        assert out is original and loc is None

    def test_junk_text_is_rejected(self, vault, monkeypatch, keyed, public_dns):
        _stub_legacy(monkeypatch, {})
        _stub_core(
            monkeypatch,
            {"search/works": _search_hit(), "/works/": _work("Just a moment... " + "x " * 5000)},
        )
        _stub_pdf(monkeypatch, None)
        original = _result(ABSTRACT)
        out, loc = oa.recover_full_text(vault, None, "https://p/x", DOI, original)
        assert out is original and loc is None

    def test_no_doi_never_calls_core(self, vault, monkeypatch, keyed):
        _stub_legacy(monkeypatch, {})
        core_calls = _stub_core(monkeypatch, {"search/works": _search_hit()})
        original = _result(ABSTRACT)
        out, loc = oa.recover_full_text(vault, None, "https://p/x", None, original)
        assert out is original and loc is None and core_calls == []

    def test_disabled_recovery_never_calls_core(self, tmp_vault, monkeypatch, keyed):
        tmp_vault.config.scholar = ScholarSettings(oa_recovery=False)
        _stub_legacy(monkeypatch, {})
        core_calls = _stub_core(monkeypatch, {"search/works": _search_hit()})
        original = _result(ABSTRACT)
        out, loc = oa.recover_full_text(tmp_vault, None, "https://p/x", DOI, original)
        assert out is original and loc is None and core_calls == []


class TestUrlGate:
    """CORE's URLs arrive in a third-party API response and are therefore
    hostile input; every one of them goes through `check_oa_url`."""

    def test_internal_download_url_is_refused(self, vault, monkeypatch, keyed):
        rec = _record(id=None, downloadUrl="http://169.254.169.254/latest/meta-data", sourceFulltextUrls=[])
        _stub_legacy(monkeypatch, {})
        _stub_core(monkeypatch, {"search/works": _search_hit(rec)})
        monkeypatch.setattr(
            oa.socket, "getaddrinfo", lambda h, p: [(2, 1, 6, "", ("169.254.169.254", 0))]
        )
        tried = _stub_pdf(monkeypatch, _result(FULL_TEXT))
        original = _result(ABSTRACT)
        out, loc = oa.recover_full_text(vault, None, "https://p/x", DOI, original)
        assert out is original and loc is None
        assert tried == []  # refused before any fetch

    def test_text_endpoint_is_gated_too(self, vault, monkeypatch, keyed):
        """Even the URL we build ourselves from CORE's `id` is checked — the
        id is theirs, and the gate is cheap."""
        _stub_legacy(monkeypatch, {})
        core_calls = _stub_core(monkeypatch, {"search/works": _search_hit(), "/works/": _work()})
        monkeypatch.setattr(oa.socket, "getaddrinfo", lambda h, p: [(2, 1, 6, "", ("10.0.0.5", 0))])
        _stub_pdf(monkeypatch, None)
        original = _result(ABSTRACT)
        out, loc = oa.recover_full_text(vault, None, "https://p/x", DOI, original)
        assert out is original and loc is None
        assert not any("/v3/works/" in u for u, _ in core_calls)

    def test_refused_url_does_not_consume_an_attempt(self, vault, monkeypatch, keyed):
        vault.config.scholar = ScholarSettings(oa_max_attempts=1)
        rec = _record(id=None, downloadUrl="http://169.254.169.254/x.pdf", sourceFulltextUrls=[SOURCE_PDF])
        _stub_legacy(monkeypatch, {})
        _stub_core(monkeypatch, {"search/works": _search_hit(rec)})

        def dns(host, port):
            addr = "169.254.169.254" if host.startswith("169.") else "93.184.216.34"
            return [(2, 1, 6, "", (addr, 0))]

        monkeypatch.setattr(oa.socket, "getaddrinfo", dns)
        tried = _stub_pdf(monkeypatch, lambda url: _result(PDF_TEXT, url=url))
        _, loc = oa.recover_full_text(vault, None, "https://p/x", DOI, _result(ABSTRACT))
        assert tried == [SOURCE_PDF]
        assert loc.url == SOURCE_PDF


class TestDisclosure:
    """A note whose body came from CORE must say so everywhere the contract
    requires: banner, `oa_*` frontmatter, and (via those) `note show -j` and
    the fetch output, which read the same fields."""

    @pytest.fixture
    def recovered(self, vault, monkeypatch, keyed, public_dns):
        _stub_legacy(monkeypatch, {})
        _stub_core(monkeypatch, {"search/works": _search_hit(), "/works/": _work()})
        out, loc = oa.recover_full_text(vault, None, "https://publisher.example.com/x", DOI, _result(ABSTRACT))
        return out, loc

    def test_banner_names_core_and_admits_unknown_version(self, recovered):
        _, loc = recovered
        text = oa.recovery_notice(loc, "https://publisher.example.com/x", len(ABSTRACT))
        assert "Open-access full text substituted" in text
        assert f"<{WORK_URL}> via core" in text
        assert "https://publisher.example.com/x" in text
        assert "unrecorded version" in text  # never dressed up as the version of record
        assert "Quote this source with care" in text
        assert "Licence reported" not in text  # CORE reported none, so none is claimed
        assert all(line.startswith(">") for line in text.strip().splitlines())

    def test_frontmatter_records_core_without_inventing_fields(self, recovered):
        _, loc = recovered
        assert oa.oa_frontmatter(loc) == {
            "oa_url": WORK_URL,
            "oa_source": "core",
            "oa_recovery_kind": "substituted",
        }

    def test_preprint_version_reaches_banner_and_frontmatter(self, vault, monkeypatch, keyed, public_dns):
        _stub_legacy(monkeypatch, {})
        rec = _record(documentType="preprint")
        _stub_core(monkeypatch, {"search/works": _search_hit(rec), "/works/": _work(**{"documentType": "preprint"})})
        _, loc = oa.recover_full_text(vault, None, "https://p/x", DOI, _result(ABSTRACT))
        assert loc.version == "submittedVersion"
        assert oa.oa_frontmatter(loc)["oa_version"] == "submittedVersion"
        assert "NOT peer reviewed" in oa.recovery_notice(loc, "https://p/x", 900)

    def test_rescue_banner_and_frontmatter(self, vault, monkeypatch, keyed, public_dns):
        _stub_legacy(monkeypatch, {})
        _stub_core(monkeypatch, {"search/works": _search_hit(), "/works/": _work()})
        out, loc = oa.rescue_full_text(vault, None, "https://publisher.example.com/x", DOI)
        assert loc is not None and loc.resolver == "core"
        assert out.content == FULL_TEXT
        text = oa.recovery_notice(loc, "https://publisher.example.com/x", 0, blocked_reason="403")
        assert "never read" in text and "via core" in text
        assert "NOTHING in this note came from the source URL" in text
        assert oa.oa_frontmatter(loc, kind="rescued")["oa_recovery_kind"] == "rescued"


class TestRescue:
    def test_rescue_respects_the_switch(self, tmp_vault, monkeypatch, keyed):
        tmp_vault.config.scholar = ScholarSettings(oa_rescue_blocked=False)
        _stub_legacy(monkeypatch, {})
        core_calls = _stub_core(monkeypatch, {"search/works": _search_hit(), "/works/": _work()})
        assert oa.rescue_full_text(tmp_vault, None, "https://p/x", DOI) == (None, None)
        assert core_calls == []

    def test_rescue_still_requires_real_full_text(self, vault, monkeypatch, keyed, public_dns):
        _stub_legacy(monkeypatch, {})
        _stub_core(monkeypatch, {"search/works": _search_hit(), "/works/": _work("A record page. " * 60)})
        _stub_pdf(monkeypatch, None)
        assert oa.rescue_full_text(vault, None, "https://p/x", DOI) == (None, None)

    def test_rescue_without_key_is_a_no_op(self, vault, monkeypatch, no_key):
        _stub_legacy(monkeypatch, {})
        core_calls = _stub_core(monkeypatch, {"search/works": _search_hit(), "/works/": _work()})
        assert oa.rescue_full_text(vault, None, "https://p/x", DOI) == (None, None)
        assert core_calls == []
