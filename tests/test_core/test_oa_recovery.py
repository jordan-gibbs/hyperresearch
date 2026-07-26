"""Tests for open-access full-text recovery — fully offline, HTTP and DNS stubbed."""

from __future__ import annotations

import pytest

from hyperresearch.core import oa, scholar
from hyperresearch.core.config import ScholarSettings
from hyperresearch.web.base import WebResult

ABSTRACT = "This paper studies widgets. " * 40  # ~1080 chars — abstract sized
FULL_TEXT = "Section text about widgets and their measurement. " * 900  # ~45k chars


def _result(content: str, url: str = "https://publisher.example.com/doi/10.1/x", **kw) -> WebResult:
    return WebResult(url=url, title=kw.pop("title", "A Paper"), content=content, **kw)


@pytest.fixture
def public_dns(monkeypatch):
    """Resolve every hostname to a public address, with no network access."""
    monkeypatch.setattr(
        oa.socket, "getaddrinfo", lambda host, port: [(2, 1, 6, "", ("93.184.216.34", 0))]
    )


def _stub_http(monkeypatch, responses: dict[str, dict | None]):
    """Stub the shared scholar HTTP layer with canned per-URL-substring responses."""
    calls: list[str] = []

    def fake_get(url: str):
        calls.append(url)
        for key, value in responses.items():
            if key in url:
                return value
        return None

    monkeypatch.setattr(scholar, "_http_get_json", fake_get)
    return calls


UNPAYWALL_PDF = {
    "is_oa": True,
    "best_oa_location": {
        "url": "https://repo.example.org/record/1",
        "url_for_pdf": "https://repo.example.org/record/1.pdf",
        "version": "publishedVersion",
        "license": "cc-by",
        "host_type": "repository",
    },
    "oa_locations": [],
}

EPMC_HIT = {
    "resultList": {
        "result": [
            {"pmcid": "PMC12345", "isOpenAccess": "Y", "inEPMC": "Y", "license": "cc-by"}
        ]
    }
}


class TestCheckOaUrl:
    """The resolved URL arrives inside a third-party API response, so it is
    attacker-influenceable and must not be fetchable at internal hosts."""

    def test_accepts_public_https(self, public_dns):
        ok, _ = oa.check_oa_url("https://repo.example.org/paper.pdf")
        assert ok is True

    def test_rejects_non_http_scheme(self):
        ok, reason = oa.check_oa_url("file:///etc/passwd")
        assert ok is False and "scheme" in reason

    def test_rejects_embedded_credentials(self):
        ok, reason = oa.check_oa_url("https://user:pw@repo.example.org/p.pdf")
        assert ok is False and "credentials" in reason

    def test_rejects_bare_hostname(self):
        ok, reason = oa.check_oa_url("http://localhost/p.pdf")
        assert ok is False and "non-public hostname" in reason

    def test_rejects_private_address(self, monkeypatch):
        monkeypatch.setattr(
            oa.socket, "getaddrinfo", lambda h, p: [(2, 1, 6, "", ("169.254.169.254", 0))]
        )
        ok, reason = oa.check_oa_url("https://metadata.example.org/p.pdf")
        assert ok is False and "non-public address" in reason

    def test_rejects_loopback_ip_literal(self, monkeypatch):
        monkeypatch.setattr(oa.socket, "getaddrinfo", lambda h, p: [(2, 1, 6, "", ("127.0.0.1", 0))])
        ok, reason = oa.check_oa_url("https://127.0.0.1/p.pdf")
        assert ok is False and "non-public address" in reason

    def test_rejects_unresolvable_host(self, monkeypatch):
        def boom(host, port):
            raise OSError("nope")

        monkeypatch.setattr(oa.socket, "getaddrinfo", boom)
        ok, reason = oa.check_oa_url("https://nowhere.example.org/p.pdf")
        assert ok is False and "DNS resolution failed" in reason


class TestNeedsRecovery:
    def test_thin_body_triggers(self):
        assert oa.needs_oa_recovery(_result(ABSTRACT), ScholarSettings()) is True

    def test_full_text_does_not_trigger(self):
        assert oa.needs_oa_recovery(_result(FULL_TEXT), ScholarSettings()) is False

    def test_pdf_does_not_trigger(self):
        r = _result(ABSTRACT, raw_content_type="application/pdf")
        assert oa.needs_oa_recovery(r, ScholarSettings()) is False

    def test_disabled_never_triggers(self):
        settings = ScholarSettings(oa_recovery=False)
        assert oa.needs_oa_recovery(_result(ABSTRACT), settings) is False

    def test_paywall_phrase_triggers_on_long_page(self):
        # Long page, plenty of nav chrome, no article text.
        body = FULL_TEXT[:8000] + " Purchase PDF to continue."
        assert oa.needs_oa_recovery(_result(body), ScholarSettings()) is True

    def test_threshold_is_configurable(self):
        settings = ScholarSettings(oa_min_full_text_chars=100)
        assert oa.needs_oa_recovery(_result(ABSTRACT), settings) is False


class TestResolve:
    def test_arxiv_ids_are_declined(self, tmp_vault, monkeypatch):
        calls = _stub_http(monkeypatch, {})
        assert oa.resolve_oa(tmp_vault.db, "arXiv:2501.00001", 30, email="a@b.co") is None
        assert calls == []

    def test_no_email_skips_unpaywall(self, tmp_vault, monkeypatch):
        calls = _stub_http(monkeypatch, {"europepmc": EPMC_HIT})
        loc = oa.resolve_oa(tmp_vault.db, "10.1/x", 30, email=None)
        assert loc is not None and loc.resolver == "europepmc"
        assert not any("unpaywall" in c for c in calls)

    def test_unpaywall_pdf_preferred(self, tmp_vault, monkeypatch):
        _stub_http(monkeypatch, {"unpaywall": UNPAYWALL_PDF})
        loc = oa.resolve_oa(tmp_vault.db, "10.1/x", 30, email="a@b.co")
        assert loc.url == "https://repo.example.org/record/1.pdf"
        assert loc.resolver == "unpaywall"
        assert loc.kind == "pdf"
        assert loc.version == "publishedVersion"
        assert loc.license == "cc-by"

    def test_published_version_beats_preprint(self, tmp_vault, monkeypatch):
        payload = {
            "is_oa": True,
            "best_oa_location": None,
            "oa_locations": [
                {"url_for_pdf": "https://a.example.org/pre.pdf", "version": "submittedVersion"},
                {"url_for_pdf": "https://a.example.org/acc.pdf", "version": "acceptedVersion"},
                {"url_for_pdf": "https://a.example.org/pub.pdf", "version": "publishedVersion"},
            ],
        }
        _stub_http(monkeypatch, {"unpaywall": payload})
        loc = oa.resolve_oa(tmp_vault.db, "10.1/x", 30, email="a@b.co")
        assert loc.url == "https://a.example.org/pub.pdf"

    def test_pdf_beats_a_better_version_without_one(self, tmp_vault, monkeypatch):
        payload = {
            "is_oa": True,
            "oa_locations": [
                {"url": "https://a.example.org/landing", "version": "publishedVersion"},
                {"url_for_pdf": "https://a.example.org/acc.pdf", "version": "acceptedVersion"},
            ],
        }
        _stub_http(monkeypatch, {"unpaywall": payload})
        loc = oa.resolve_oa(tmp_vault.db, "10.1/x", 30, email="a@b.co")
        assert loc.url == "https://a.example.org/acc.pdf"
        assert loc.kind == "pdf"

    def test_landing_page_used_when_no_pdf_anywhere(self, tmp_vault, monkeypatch):
        payload = {"is_oa": True, "best_oa_location": {"url": "https://a.example.org/landing"}}
        _stub_http(monkeypatch, {"unpaywall": payload})
        loc = oa.resolve_oa(tmp_vault.db, "10.1/x", 30, email="a@b.co")
        assert loc.url == "https://a.example.org/landing"
        assert loc.kind == "page"

    def test_closed_access_falls_through_to_epmc(self, tmp_vault, monkeypatch):
        _stub_http(monkeypatch, {"unpaywall": {"is_oa": False}, "europepmc": EPMC_HIT})
        loc = oa.resolve_oa(tmp_vault.db, "10.1/x", 30, email="a@b.co")
        assert loc.resolver == "europepmc"
        assert loc.url.endswith("/PMC12345/fullTextXML")

    def test_epmc_requires_open_access_flag(self, tmp_vault, monkeypatch):
        closed = {"resultList": {"result": [{"pmcid": "PMC1", "isOpenAccess": "N"}]}}
        _stub_http(monkeypatch, {"europepmc": closed})
        assert oa.resolve_oa(tmp_vault.db, "10.1/x", 30) is None

    def test_epmc_requires_a_pmcid(self, tmp_vault, monkeypatch):
        no_pmcid = {"resultList": {"result": [{"isOpenAccess": "Y"}]}}
        _stub_http(monkeypatch, {"europepmc": no_pmcid})
        assert oa.resolve_oa(tmp_vault.db, "10.1/x", 30) is None

    def test_both_resolvers_dry(self, tmp_vault, monkeypatch):
        _stub_http(monkeypatch, {})
        assert oa.resolve_oa(tmp_vault.db, "10.1/x", 30, email="a@b.co") is None


class TestDisclosure:
    def test_notice_names_source_resolver_and_size(self):
        loc = oa.OALocation(
            url="https://repo.example.org/p.pdf",
            resolver="unpaywall",
            kind="pdf",
            version="publishedVersion",
            license="cc-by",
        )
        text = oa.recovery_notice(loc, "https://publisher.example.com/doi/10.1/x", 1080)
        assert "https://repo.example.org/p.pdf" in text
        assert "unpaywall" in text
        assert "https://publisher.example.com/doi/10.1/x" in text
        assert "1,080" in text
        assert "cc-by" in text

    def test_preprint_notice_warns_about_quoting(self):
        loc = oa.OALocation(
            url="https://a.example.org/pre.pdf",
            resolver="unpaywall",
            kind="pdf",
            version="submittedVersion",
        )
        text = oa.recovery_notice(loc, "https://p.example.com/x", 900)
        assert "NOT peer reviewed" in text
        assert "version of record" in text

    def test_version_of_record_gets_no_warning(self):
        loc = oa.OALocation(
            url="https://a.example.org/p.pdf", resolver="europepmc", kind="pdf",
            version="publishedVersion",
        )
        assert "Quote this source with care" not in oa.recovery_notice(loc, "https://p/x", 900)

    def test_frontmatter_omits_unknown_fields(self):
        loc = oa.OALocation(url="https://a/p.pdf", resolver="europepmc", kind="pdf")
        assert oa.oa_frontmatter(loc) == {"oa_url": "https://a/p.pdf", "oa_source": "europepmc"}


class TestRecoverFullText:
    """The orchestration layer. Every failure path must return the original
    result untouched — an abstract beats no note at all."""

    @pytest.fixture
    def vault(self, tmp_vault):
        tmp_vault.config.scholar = ScholarSettings(contact_email="a@b.co")
        return tmp_vault

    def _stub_pdf(self, monkeypatch, returned):
        from hyperresearch.web import crawl4ai_provider

        monkeypatch.setattr(crawl4ai_provider, "_fetch_pdf", lambda url, settings: returned)

    def test_happy_path_swaps_the_body(self, vault, monkeypatch, public_dns):
        _stub_http(monkeypatch, {"unpaywall": UNPAYWALL_PDF})
        self._stub_pdf(monkeypatch, _result(FULL_TEXT, url="https://repo.example.org/record/1.pdf"))
        out, loc = oa.recover_full_text(vault, None, "https://p.example.com/x", "10.1/x",
                                        _result(ABSTRACT))
        assert loc is not None and loc.resolver == "unpaywall"
        assert out.content == FULL_TEXT

    def test_no_doi_is_a_no_op(self, vault, monkeypatch):
        calls = _stub_http(monkeypatch, {"unpaywall": UNPAYWALL_PDF})
        original = _result(ABSTRACT)
        out, loc = oa.recover_full_text(vault, None, "https://p/x", None, original)
        assert out is original and loc is None and calls == []

    def test_full_text_page_is_a_no_op(self, vault, monkeypatch):
        calls = _stub_http(monkeypatch, {"unpaywall": UNPAYWALL_PDF})
        original = _result(FULL_TEXT)
        out, loc = oa.recover_full_text(vault, None, "https://p/x", "10.1/x", original)
        assert out is original and loc is None and calls == []

    def test_unsafe_url_is_refused(self, vault, monkeypatch):
        payload = {
            "is_oa": True,
            "best_oa_location": {"url_for_pdf": "http://169.254.169.254/latest/meta-data"},
        }
        _stub_http(monkeypatch, {"unpaywall": payload})
        monkeypatch.setattr(
            oa.socket, "getaddrinfo", lambda h, p: [(2, 1, 6, "", ("169.254.169.254", 0))]
        )
        self._stub_pdf(monkeypatch, _result(FULL_TEXT))
        original = _result(ABSTRACT)
        out, loc = oa.recover_full_text(vault, None, "https://p/x", "10.1/x", original)
        assert out is original and loc is None

    def test_record_page_is_rejected_as_not_full_text(self, vault, monkeypatch, public_dns):
        """A repository record page is longer than an abstract but is still
        metadata, not a paper. It must not pass for full text."""
        _stub_http(monkeypatch, {"unpaywall": UNPAYWALL_PDF})
        self._stub_pdf(monkeypatch, _result("Title, authors, and a summary. " * 60))  # ~1.8k
        original = _result(ABSTRACT)
        out, loc = oa.recover_full_text(vault, None, "https://p/x", "10.1/x", original)
        assert out is original and loc is None

    def test_falls_through_to_the_next_candidate(self, vault, monkeypatch, public_dns):
        """Publishers 403 their own OA PDFs; the next copy must still be tried."""
        payload = {
            "is_oa": True,
            "oa_locations": [
                {"url_for_pdf": "https://blocked.example.org/a.pdf", "version": "publishedVersion"},
                {"url_for_pdf": "https://mirror.example.org/b.pdf", "version": "publishedVersion"},
            ],
        }
        _stub_http(monkeypatch, {"unpaywall": payload})

        from hyperresearch.web import crawl4ai_provider

        tried: list[str] = []

        def flaky(url, settings):
            tried.append(url)
            return None if "blocked" in url else _result(FULL_TEXT, url=url)

        monkeypatch.setattr(crawl4ai_provider, "_fetch_pdf", flaky)
        out, loc = oa.recover_full_text(vault, None, "https://p/x", "10.1/x", _result(ABSTRACT))
        assert tried == ["https://blocked.example.org/a.pdf", "https://mirror.example.org/b.pdf"]
        assert loc.url == "https://mirror.example.org/b.pdf"
        assert out.content == FULL_TEXT

    def test_attempt_cap_is_honoured(self, vault, monkeypatch, public_dns):
        vault.config.scholar = ScholarSettings(contact_email="a@b.co", oa_max_attempts=2)
        payload = {
            "is_oa": True,
            "oa_locations": [
                {"url_for_pdf": f"https://m{i}.example.org/x.pdf", "version": "publishedVersion"}
                for i in range(5)
            ],
        }
        _stub_http(monkeypatch, {"unpaywall": payload})

        from hyperresearch.web import crawl4ai_provider

        tried: list[str] = []
        monkeypatch.setattr(
            crawl4ai_provider, "_fetch_pdf", lambda url, s: tried.append(url) or None
        )
        original = _result(ABSTRACT)
        out, loc = oa.recover_full_text(vault, None, "https://p/x", "10.1/x", original)
        assert len(tried) == 2
        assert out is original and loc is None

    def test_shorter_recovery_is_rejected(self, vault, monkeypatch, public_dns):
        _stub_http(monkeypatch, {"unpaywall": UNPAYWALL_PDF})
        self._stub_pdf(monkeypatch, _result("garbled"))  # bad PDF extraction
        original = _result(ABSTRACT)
        out, loc = oa.recover_full_text(vault, None, "https://p/x", "10.1/x", original)
        assert out is original and loc is None

    def test_junk_recovery_is_rejected(self, vault, monkeypatch, public_dns):
        _stub_http(monkeypatch, {"unpaywall": UNPAYWALL_PDF})
        self._stub_pdf(monkeypatch, _result("Just a moment... " + "x " * 5000, title="Cloudflare"))
        original = _result(ABSTRACT)
        out, loc = oa.recover_full_text(vault, None, "https://p/x", "10.1/x", original)
        assert out is original and loc is None

    def test_failed_pdf_download_is_soft(self, vault, monkeypatch, public_dns):
        _stub_http(monkeypatch, {"unpaywall": UNPAYWALL_PDF})
        self._stub_pdf(monkeypatch, None)
        original = _result(ABSTRACT)
        out, loc = oa.recover_full_text(vault, None, "https://p/x", "10.1/x", original)
        assert out is original and loc is None

    def test_raising_fetcher_is_soft(self, vault, monkeypatch, public_dns):
        from hyperresearch.web import crawl4ai_provider

        def boom(url, settings):
            raise RuntimeError("connection reset")

        _stub_http(monkeypatch, {"unpaywall": UNPAYWALL_PDF})
        monkeypatch.setattr(crawl4ai_provider, "_fetch_pdf", boom)
        original = _result(ABSTRACT)
        out, loc = oa.recover_full_text(vault, None, "https://p/x", "10.1/x", original)
        assert out is original and loc is None

    def test_disabled_by_config(self, tmp_vault, monkeypatch):
        tmp_vault.config.scholar = ScholarSettings(oa_recovery=False, contact_email="a@b.co")
        calls = _stub_http(monkeypatch, {"unpaywall": UNPAYWALL_PDF})
        original = _result(ABSTRACT)
        out, loc = oa.recover_full_text(tmp_vault, None, "https://p/x", "10.1/x", original)
        assert out is original and loc is None and calls == []

    def test_non_pdf_location_uses_the_provider(self, vault, monkeypatch, public_dns):
        payload = {"is_oa": True, "best_oa_location": {"url": "https://repo.example.org/html"}}
        _stub_http(monkeypatch, {"unpaywall": payload})

        class FakeProvider:
            name = "fake"

            def fetch(self, url):
                return _result(FULL_TEXT, url=url)

        out, loc = oa.recover_full_text(vault, FakeProvider(), "https://p/x", "10.1/x",
                                        _result(ABSTRACT))
        assert loc is not None and loc.kind == "page"
        assert out.content == FULL_TEXT


JATS = """<article>
  <front><article-meta>
    <title-group><article-title>Widgets and <italic>Gadgets</italic></article-title></title-group>
    <abstract><p>We measured widgets.</p></abstract>
  </article-meta></front>
  <body>
    <sec><title>Introduction</title>
      <p>Widgets matter <xref ref-type="bibr" rid="b1">[1]</xref> a great deal.</p>
      <sec><title>Prior work</title><p>Others tried.</p></sec>
    </sec>
    <sec><title>Methods</title>
      <p>We used calipers.</p>
      <fig><caption><p>Figure 1. A widget.</p></caption></fig>
      <list><list-item><p>first</p></list-item><list-item><p>second</p></list-item></list>
    </sec>
  </body>
  <back><ref-list><ref id="b1"><mixed-citation>Someone 1999</mixed-citation></ref></ref-list></back>
</article>"""


class TestJats:
    def test_structure_and_inline_flattening(self):
        md = oa.jats_to_markdown(JATS)
        assert md.startswith("# Widgets and Gadgets")
        assert "## Abstract" in md
        assert "We measured widgets." in md
        assert "## Introduction" in md
        assert "### Prior work" in md  # nested section gets a deeper heading
        assert "*Figure 1. A widget.*" in md
        assert "- first" in md and "- second" in md

    def test_xref_markers_are_dropped_without_eating_the_sentence(self):
        md = oa.jats_to_markdown(JATS)
        assert "Widgets matter a great deal." in md
        assert "[1]" not in md

    def test_back_matter_is_excluded(self):
        assert "Someone 1999" not in oa.jats_to_markdown(JATS)

    def test_unparseable_xml_returns_none(self):
        assert oa.jats_to_markdown("<article><body>") is None

    def test_empty_document_returns_none(self):
        assert oa.jats_to_markdown("<article></article>") is None


class TestEpmcRecovery:
    def test_jats_becomes_the_note_body(self, tmp_vault, monkeypatch, public_dns):
        _stub_http(monkeypatch, {"europepmc": EPMC_HIT})
        long_jats = JATS.replace(
            "<p>We used calipers.</p>", "<p>" + ("We used calipers. " * 600) + "</p>"
        )
        monkeypatch.setattr(oa, "_http_get_text", lambda url: long_jats)

        out, loc = oa.recover_full_text(
            tmp_vault, None, "https://p.example.com/x", "10.1/x", _result(ABSTRACT)
        )
        assert loc is not None and loc.kind == "jats"
        assert loc.url.endswith("/fullTextXML")
        assert out.title == "Widgets and Gadgets"
        assert "## Introduction" in out.content

    def test_unfetchable_xml_is_soft(self, tmp_vault, monkeypatch, public_dns):
        _stub_http(monkeypatch, {"europepmc": EPMC_HIT})
        monkeypatch.setattr(oa, "_http_get_text", lambda url: None)
        original = _result(ABSTRACT)
        out, loc = oa.recover_full_text(
            tmp_vault, None, "https://p.example.com/x", "10.1/x", original
        )
        assert out is original and loc is None


class TestMigration:
    def test_adds_columns_and_is_idempotent(self):
        import sqlite3

        from hyperresearch.core.migrations import _migrate_v11_oa_recovery

        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE notes (id TEXT PRIMARY KEY, title TEXT)")
        conn.execute("INSERT INTO notes VALUES ('old-note', 'Pre-existing')")

        _migrate_v11_oa_recovery(conn)
        _migrate_v11_oa_recovery(conn)  # re-running must not raise

        cols = {row[1] for row in conn.execute("PRAGMA table_info(notes)")}
        assert {"oa_url", "oa_source", "oa_version", "oa_license"} <= cols
        # Existing rows are left alone — we cannot know after the fact whether
        # an old note's body came from its source URL.
        assert conn.execute("SELECT oa_url FROM notes WHERE id='old-note'").fetchone()[0] is None


class TestConfigSection:
    def test_defaults(self, tmp_path):
        from hyperresearch.core.config import VaultConfig

        cfg = VaultConfig.load(tmp_path / "nope.toml")
        assert cfg.scholar == ScholarSettings()
        assert cfg.scholar.oa_recovery is True
        assert cfg.scholar.contact_email == ""
        assert cfg.scholar.oa_min_full_text_chars == 6000

    def test_override_and_roundtrip(self, tmp_path):
        from hyperresearch.core.config import VaultConfig

        p = tmp_path / "config.toml"
        p.write_text(
            '[scholar]\ncontact_email = "me@example.org"\noa_min_full_text_chars = 2000\n',
            encoding="utf-8",
        )
        cfg = VaultConfig.load(p)
        assert cfg.scholar.contact_email == "me@example.org"
        assert cfg.scholar.oa_min_full_text_chars == 2000
        cfg.save(p)
        assert VaultConfig.load(p).scholar == cfg.scholar

    def test_written_config_explains_the_substitution(self, tmp_vault):
        text = (tmp_vault.root / ".hyperresearch" / "config.toml").read_text(encoding="utf-8")
        assert "[scholar]" in text
        assert "REQUIRED by Unpaywall" in text
        assert "legal open-access copy" in text
        assert "oa_url" in text
