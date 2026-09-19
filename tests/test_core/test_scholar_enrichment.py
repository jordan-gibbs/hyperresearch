"""Tests for `hpr sources score` enrichment — fully offline, HTTP stubbed."""

from __future__ import annotations

import json

import pytest

from hyperresearch.core import scholar


@pytest.fixture
def doi_vault(tmp_vault):
    """Vault with two DOI-bearing notes and one plain note."""
    from hyperresearch.core.note import write_note
    from hyperresearch.core.sync import compute_sync_plan, execute_sync

    write_note(
        tmp_vault.notes_dir, "Cited Paper", body="Highly cited work.",
        tier="institutional",
        extra_frontmatter={"doi": "10.1/cited", "source": "https://doi.org/10.1/cited"},
    )
    write_note(
        tmp_vault.notes_dir, "Retracted Paper", body="Withdrawn work.",
        tier="institutional",
        extra_frontmatter={"doi": "10.1/retracted", "source": "https://doi.org/10.1/retracted"},
    )
    write_note(tmp_vault.notes_dir, "Plain Blog", body="No DOI here.")
    plan = compute_sync_plan(tmp_vault, force=True)
    execute_sync(tmp_vault, plan)
    return tmp_vault


def _stub_openalex(monkeypatch, responses: dict[str, dict | None]):
    """Stub the raw HTTP layer with canned per-URL-substring responses."""
    calls: list[str] = []

    def fake_get(url: str):
        calls.append(url)
        for key, value in responses.items():
            if key in url:
                return value
        return None

    monkeypatch.setattr(scholar, "_http_get_json", fake_get)
    return calls


OPENALEX_CITED = {
    "cited_by_count": 512,
    "primary_location": {"source": {"display_name": "Nature"}},
    "is_retracted": False,
}
OPENALEX_RETRACTED = {
    "cited_by_count": 30,
    "primary_location": {"source": {"display_name": "BadJournal"}},
    "is_retracted": True,
}


class TestScoreSources:
    def test_enrichment_populates_db_and_frontmatter(self, doi_vault, monkeypatch):
        _stub_openalex(monkeypatch, {
            "10.1%2Fcited": OPENALEX_CITED,
            "10.1%2Fretracted": OPENALEX_RETRACTED,
        })
        result = scholar.score_sources(doi_vault)
        assert result["scored"] == 2
        assert result["retracted"] == ["retracted-paper"]

        row = doi_vault.db.execute(
            "SELECT citation_count, venue, is_retracted, authority_score, quality_score "
            "FROM notes WHERE id = 'cited-paper'"
        ).fetchone()
        assert row["citation_count"] == 512
        assert row["venue"] == "Nature"
        assert row["is_retracted"] == 0
        assert row["authority_score"] is not None
        assert row["quality_score"] is not None

        # Frontmatter mirror written
        text = next(doi_vault.notes_dir.glob("cited-paper.md")).read_text(encoding="utf-8")
        assert "citation_count: 512" in text
        assert "venue: Nature" in text

    def test_retracted_gets_quality_floor(self, doi_vault, monkeypatch):
        _stub_openalex(monkeypatch, {
            "10.1%2Fcited": OPENALEX_CITED,
            "10.1%2Fretracted": OPENALEX_RETRACTED,
        })
        scholar.score_sources(doi_vault)
        floor = doi_vault.config.ranking.retraction_floor
        row = doi_vault.db.execute(
            "SELECT quality_score FROM notes WHERE id = 'retracted-paper'"
        ).fetchone()
        assert row["quality_score"] == floor

    def test_cache_prevents_second_http_call(self, doi_vault, monkeypatch):
        calls = _stub_openalex(monkeypatch, {
            "10.1%2Fcited": OPENALEX_CITED,
            "10.1%2Fretracted": OPENALEX_RETRACTED,
        })
        scholar.score_sources(doi_vault)
        first_count = len(calls)
        assert first_count == 2
        # Re-score fresh=True → cache bypassed but api_cache row present;
        # fresh=False re-run skips already-enriched notes entirely.
        scholar.score_sources(doi_vault)
        assert len(calls) == first_count  # no new HTTP calls

    def test_api_failure_is_soft(self, doi_vault, monkeypatch):
        _stub_openalex(monkeypatch, {})  # everything misses -> None
        result = scholar.score_sources(doi_vault)
        assert result["scored"] == 0
        assert len(result["missing"]) == 2  # both DOI notes unresolved, no crash

    def test_arxiv_ids_route_to_semantic_scholar(self, tmp_vault, monkeypatch):
        from hyperresearch.core.note import write_note
        from hyperresearch.core.sync import compute_sync_plan, execute_sync

        write_note(
            tmp_vault.notes_dir, "Arxiv Preprint", body="x",
            extra_frontmatter={"doi": "arXiv:2501.01234"},
        )
        plan = compute_sync_plan(tmp_vault, force=True)
        execute_sync(tmp_vault, plan)

        calls = _stub_openalex(monkeypatch, {
            "semanticscholar": {"citationCount": 7, "venue": "arXiv"},
        })
        result = scholar.score_sources(tmp_vault)
        assert result["scored"] == 1
        assert any("semanticscholar.org" in c for c in calls)
        assert not any("openalex.org" in c for c in calls)

    @pytest.mark.parametrize("doi", ["arXiv:2501.01234", "10.1/fallback"])
    def test_semantic_scholar_retraction_stays_unchecked(
        self, tmp_vault, monkeypatch, no_sleep, doi,
    ):
        from hyperresearch.core.frontmatter import parse_frontmatter
        from hyperresearch.core.note import write_note
        from hyperresearch.core.sync import compute_sync_plan, execute_sync
        from hyperresearch.search.filters import SearchFilters
        from hyperresearch.search.fts import search_fts

        write_note(
            tmp_vault.notes_dir, "Unchecked Paper", body="Research evidence.",
            extra_frontmatter={"doi": doi, "is_retracted": False, "citation_count": 1},
        )
        execute_sync(tmp_vault, compute_sync_plan(tmp_vault))
        _stub_openalex(monkeypatch, {
            "semanticscholar": {"citationCount": 7, "venue": "arXiv"},
        })

        result = scholar.score_sources(tmp_vault, fresh=True)
        assert result["scored"] == 1
        assert result["retracted"] == []
        row = tmp_vault.db.execute(
            "SELECT citation_count, venue, is_retracted FROM notes WHERE id = 'unchecked-paper'"
        ).fetchone()
        assert row["citation_count"] == 7
        assert row["venue"] == "arXiv"
        assert row["is_retracted"] is None

        text = (tmp_vault.notes_dir / "unchecked-paper.md").read_text(encoding="utf-8")
        meta, _ = parse_frontmatter(text)
        assert meta.is_retracted is None
        assert meta.citation_count == 7

        for resync in (False, True):
            if resync:
                execute_sync(tmp_vault, compute_sync_plan(tmp_vault, force=True))
            unchecked = search_fts(
                tmp_vault.db, "", filters=SearchFilters(retraction="unchecked"),
            )
            assert [r["id"] for r in unchecked] == ["unchecked-paper"]
            assert unchecked[0]["is_retracted"] is None
            assert search_fts(
                tmp_vault.db, "", filters=SearchFilters(retraction="not-retracted"),
            ) == []

    def test_authority_is_vault_relative_percentile(self, doi_vault, monkeypatch):
        _stub_openalex(monkeypatch, {
            "10.1%2Fcited": OPENALEX_CITED,        # 512 citations
            "10.1%2Fretracted": OPENALEX_RETRACTED,  # 30 citations
        })
        scholar.score_sources(doi_vault)
        rows = {
            r["id"]: r["authority_score"]
            for r in doi_vault.db.execute(
                "SELECT id, authority_score FROM notes WHERE authority_score IS NOT NULL"
            )
        }
        assert rows["cited-paper"] == 1.0
        assert rows["retracted-paper"] == 0.5


class TestBackfillDois:
    def test_backfill_from_source_url(self, tmp_vault):
        from hyperresearch.core.note import write_note
        from hyperresearch.core.sync import compute_sync_plan, execute_sync

        write_note(
            tmp_vault.notes_dir, "Old Fetch", body="fetched before doi capture existed",
            source="https://arxiv.org/abs/2401.00001",
        )
        plan = compute_sync_plan(tmp_vault, force=True)
        execute_sync(tmp_vault, plan)

        gained = scholar.backfill_dois(tmp_vault)
        assert gained == 1
        row = tmp_vault.db.execute("SELECT doi FROM notes WHERE id = 'old-fetch'").fetchone()
        assert row["doi"] == "arXiv:2401.00001"
        text = next(tmp_vault.notes_dir.glob("old-fetch.md")).read_text(encoding="utf-8")
        assert "arXiv:2401.00001" in text


class TestApiCache:
    def test_cache_roundtrip(self, tmp_vault, monkeypatch):
        calls = []

        def fake_get(url):
            calls.append(url)
            return {"hello": "world"}

        monkeypatch.setattr(scholar, "_http_get_json", fake_get)
        conn = tmp_vault.db
        r1 = scholar._fetch_json(conn, "https://api.openalex.org/works/x", ttl_days=30)
        r2 = scholar._fetch_json(conn, "https://api.openalex.org/works/x", ttl_days=30)
        assert r1 == r2 == {"hello": "world"}
        assert len(calls) == 1  # second hit served from cache

    def test_fresh_bypasses_cache(self, tmp_vault, monkeypatch):
        calls = []

        def fake_get(url):
            calls.append(url)
            return {"n": len(calls)}

        monkeypatch.setattr(scholar, "_http_get_json", fake_get)
        conn = tmp_vault.db
        scholar._fetch_json(conn, "https://api.openalex.org/works/y", ttl_days=30)
        r2 = scholar._fetch_json(conn, "https://api.openalex.org/works/y", ttl_days=30, fresh=True)
        assert len(calls) == 2
        assert r2 == {"n": 2}

    def test_cache_body_is_json(self, tmp_vault, monkeypatch):
        monkeypatch.setattr(scholar, "_http_get_json", lambda url: {"a": 1})
        conn = tmp_vault.db
        scholar._fetch_json(conn, "https://api.openalex.org/works/z", ttl_days=30)
        row = conn.execute(
            "SELECT body FROM api_cache WHERE url = 'https://api.openalex.org/works/z'"
        ).fetchone()
        assert json.loads(row["body"]) == {"a": 1}


@pytest.mark.parametrize("doi", ["arXiv:2501.01234", "10.1/fallback"])
def test_semantic_scholar_metadata_has_unknown_retraction(tmp_vault, monkeypatch, no_sleep, doi):
    _stub_openalex(monkeypatch, {
        "semanticscholar": {"citationCount": 7, "venue": "arXiv"},
    })
    metadata = scholar.lookup_metadata(tmp_vault.db, doi, ttl_days=30)
    assert metadata == {"citation_count": 7, "venue": "arXiv", "is_retracted": None}


# ---------------------------------------------------------------------------
# 429 handling (#70) — patches httpx.get underneath _http_get_json, and
# time.sleep so the backoff ladder never actually waits.
# ---------------------------------------------------------------------------


class _Resp:
    def __init__(self, status: int, body: dict | None = None, headers: dict | None = None):
        self.status_code = status
        self._body = body or {}
        self.headers = headers or {}

    def json(self):
        return self._body


def _stub_httpx(monkeypatch, sequence: list[_Resp]):
    """Serve canned responses in order; record every (url, headers) call."""
    import httpx

    calls: list[tuple[str, dict]] = []
    queue = list(sequence)

    def fake_get(url, **kwargs):
        calls.append((url, dict(kwargs.get("headers") or {})))
        return queue.pop(0) if queue else _Resp(200, {"ok": True})

    monkeypatch.setattr(httpx, "get", fake_get)
    return calls


@pytest.fixture
def no_sleep(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr(scholar.time, "sleep", lambda s: slept.append(s))
    return slept


S2_URL = "https://api.semanticscholar.org/graph/v1/paper/arXiv:2501.01234?fields=citationCount"


def _arxiv_plus_doi_vault(tmp_vault):
    from hyperresearch.core.note import write_note
    from hyperresearch.core.sync import compute_sync_plan, execute_sync

    write_note(
        tmp_vault.notes_dir, "Arxiv Preprint", body="x",
        extra_frontmatter={"doi": "arXiv:2501.01234"},
    )
    write_note(
        tmp_vault.notes_dir, "Cited Paper", body="y", tier="institutional",
        extra_frontmatter={"doi": "10.1/cited"},
    )
    plan = compute_sync_plan(tmp_vault, force=True)
    execute_sync(tmp_vault, plan)
    return tmp_vault


def _s2_throttled(url: str):
    if "semanticscholar" in url:
        raise scholar.RateLimitedError("api.semanticscholar.org", 3)
    return OPENALEX_CITED


class TestRateLimitRetry:
    def test_429_then_success_retries_with_backoff(self, monkeypatch, no_sleep):
        calls = _stub_httpx(monkeypatch, [_Resp(429), _Resp(429), _Resp(200, {"citationCount": 3})])
        assert scholar._http_get_json(S2_URL) == {"citationCount": 3}
        assert len(calls) == 3
        assert no_sleep == [2.0, 4.0]

    def test_429_exhausted_raises_rate_limited(self, monkeypatch, no_sleep):
        calls = _stub_httpx(monkeypatch, [_Resp(429), _Resp(429), _Resp(429)])
        with pytest.raises(scholar.RateLimitedError) as exc:
            scholar._http_get_json(S2_URL)
        assert len(calls) == 3
        assert exc.value.host == "api.semanticscholar.org"
        assert exc.value.attempts == 3
        assert no_sleep == [2.0, 4.0]

    def test_retry_after_header_is_honoured(self, monkeypatch, no_sleep):
        _stub_httpx(monkeypatch, [_Resp(429, headers={"Retry-After": "7"}), _Resp(200, {"a": 1})])
        assert scholar._http_get_json(S2_URL) == {"a": 1}
        assert no_sleep == [7.0]

    def test_insane_retry_after_falls_back_to_ladder(self, monkeypatch, no_sleep):
        _stub_httpx(monkeypatch, [
            _Resp(429, headers={"Retry-After": "86400"}),
            _Resp(429, headers={"Retry-After": "Fri, 31 Dec 1999 23:59:59 GMT"}),
            _Resp(200, {"a": 1}),
        ])
        scholar._http_get_json(S2_URL)
        assert no_sleep == [2.0, 4.0]

    def test_other_non_200_stays_soft_none_without_retry(self, monkeypatch, no_sleep):
        for status in (404, 500, 503):
            calls = _stub_httpx(monkeypatch, [_Resp(status)])
            assert scholar._http_get_json(S2_URL) is None
            assert len(calls) == 1
        assert no_sleep == []

    def test_rate_limit_is_not_cached(self, tmp_vault, monkeypatch, no_sleep):
        _stub_httpx(monkeypatch, [_Resp(429)] * 3)
        with pytest.raises(scholar.RateLimitedError):
            scholar._fetch_json(tmp_vault.db, S2_URL, ttl_days=30)
        row = tmp_vault.db.execute("SELECT 1 FROM api_cache WHERE url = ?", (S2_URL,)).fetchone()
        assert row is None


class TestRateLimitInScoreSources:
    def test_exhausted_429_lands_in_rate_limited_not_missing(self, tmp_vault, monkeypatch):
        vault = _arxiv_plus_doi_vault(tmp_vault)
        monkeypatch.setattr(scholar, "_http_get_json", _s2_throttled)
        result = scholar.score_sources(vault)
        assert result["scored"] == 1
        assert result["rate_limited"] == ["arxiv-preprint"]
        assert result["missing"] == []
        # Not marked enriched -> a later run retries it
        row = vault.db.execute(
            "SELECT citation_count FROM notes WHERE id = 'arxiv-preprint'"
        ).fetchone()
        assert row["citation_count"] is None

    def test_doi_fallback_to_s2_that_is_throttled_is_rate_limited(self, doi_vault, monkeypatch):
        # OpenAlex has nothing, the S2 fallback is throttled -> rate_limited, not missing
        def fake_get(url):
            if "semanticscholar" in url:
                raise scholar.RateLimitedError("api.semanticscholar.org", 3)
            return None

        monkeypatch.setattr(scholar, "_http_get_json", fake_get)
        result = scholar.score_sources(doi_vault)
        assert sorted(result["rate_limited"]) == ["cited-paper", "retracted-paper"]
        assert result["missing"] == []

    def test_summary_key_present_when_nothing_throttled(self, doi_vault, monkeypatch):
        _stub_openalex(monkeypatch, {})
        result = scholar.score_sources(doi_vault)
        assert result["rate_limited"] == []
        assert len(result["missing"]) == 2

    def test_cli_reports_rate_limit_distinctly(self, tmp_vault, monkeypatch):
        from typer.testing import CliRunner

        from hyperresearch.cli import app

        vault = _arxiv_plus_doi_vault(tmp_vault)
        monkeypatch.setattr(scholar, "_http_get_json", _s2_throttled)
        monkeypatch.chdir(vault.root)
        result = CliRunner().invoke(app, ["sources", "score"])
        assert result.exit_code == 0, result.output
        assert "Rate-limited" in result.output
        assert "No metadata found" not in result.output

        result = CliRunner().invoke(app, ["sources", "score", "--fresh", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["data"]["rate_limited"] == ["arxiv-preprint"]

        result = CliRunner().invoke(app, ["sources", "retractions", "--json"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["data"]["rate_limited"] == 1


class TestSemanticScholarApiKey:
    def test_key_attached_only_to_semanticscholar_host(self, monkeypatch, no_sleep):
        monkeypatch.setenv("S2_API_KEY", "sekrit")
        calls = _stub_httpx(monkeypatch, [])
        others = [
            "https://api.openalex.org/works/doi:10.1%2Fx",
            "https://api.unpaywall.org/v2/10.1%2Fx?email=a@b.c",
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=x",
            "https://evil.example.com/semanticscholar.org/steal",
            "https://semanticscholar.org.evil.example.com/steal",
        ]
        scholar._http_get_json(S2_URL)
        for url in others:
            scholar._http_get_json(url)
        by_url = dict(calls)
        assert by_url[S2_URL]["x-api-key"] == "sekrit"
        assert by_url[S2_URL]["User-Agent"].startswith("hyperresearch")
        for url in others:
            assert "x-api-key" not in by_url[url], url

    def test_alternate_env_name_and_no_key(self, monkeypatch, no_sleep):
        monkeypatch.delenv("S2_API_KEY", raising=False)
        monkeypatch.setenv("SEMANTIC_SCHOLAR_API_KEY", "alt")
        calls = _stub_httpx(monkeypatch, [])
        scholar._http_get_json(S2_URL)
        assert calls[0][1]["x-api-key"] == "alt"

        monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY")
        calls = _stub_httpx(monkeypatch, [])
        scholar._http_get_json(S2_URL)
        assert "x-api-key" not in calls[0][1]


class TestOaResolversStaySoft:
    def test_rate_limit_means_no_oa_copy(self, tmp_vault, monkeypatch):
        from hyperresearch.core import oa

        def fake_get(url):
            raise scholar.RateLimitedError("api.unpaywall.org", 3)

        monkeypatch.setattr(scholar, "_http_get_json", fake_get)
        assert oa._resolve_europepmc(tmp_vault.db, "10.1/x", 30, False) is None
        assert list(oa._unpaywall_candidates(tmp_vault.db, "10.1/x", 30, "a@b.c", True, False)) == []


class TestSemanticScholarKeyScopeHardening:
    """Security review of #70: the key must ride only on a real
    semanticscholar.org host, per hop, and never follow a redirect away."""

    LOOKALIKES = (
        "https://evilsemanticscholar.org/steal",
        "https://notsemanticscholar.org/steal",
        "https://semanticscholar.org.evil.example/steal",
        "https://api.semanticscholar.org@evil.example/steal",  # userinfo trick
        "https://evil.example/?next=api.semanticscholar.org",
        "https://evil.example/api.semanticscholar.org/graph",
        "https://evil.example#semanticscholar.org",
    )
    GENUINE = (
        "https://api.semanticscholar.org/graph/v1/paper/x",
        "https://semanticscholar.org/x",
        "https://API.SemanticScholar.ORG:443/x",  # case + explicit port
        "https://user@api.semanticscholar.org/x",  # userinfo on the real host
        "https://partner.api.semanticscholar.org./x",  # trailing-dot FQDN
    )

    def test_lookalike_hosts_never_get_the_key(self, monkeypatch, no_sleep):
        monkeypatch.setenv("S2_API_KEY", "sekrit")
        calls = _stub_httpx(monkeypatch, [])
        for url in self.LOOKALIKES:
            scholar._http_get_json(url)
        assert len(calls) == len(self.LOOKALIKES)
        for url, headers in calls:
            assert "x-api-key" not in headers, url
            assert "sekrit" not in url

    def test_genuine_hosts_get_the_key(self, monkeypatch, no_sleep):
        monkeypatch.setenv("S2_API_KEY", "sekrit")
        calls = _stub_httpx(monkeypatch, [])
        for url in self.GENUINE:
            scholar._http_get_json(url)
        for url, headers in calls:
            assert headers.get("x-api-key") == "sekrit", url

    def test_is_s2_host_survives_unparseable_urls(self):
        assert scholar._is_s2_host("https://[::1/x") is False
        assert scholar._is_s2_host("not a url") is False
        assert scholar._is_s2_host("") is False

    def test_key_is_dropped_on_cross_host_redirect(self, monkeypatch, no_sleep):
        # httpx strips only `Authorization` on cross-origin redirects; a
        # redirect off semanticscholar.org must not carry x-api-key along.
        monkeypatch.setenv("S2_API_KEY", "sekrit")
        calls = _stub_httpx(monkeypatch, [
            _Resp(302, headers={"Location": "https://evil.example/collect"}),
            _Resp(200, {"ok": 1}),
        ])
        assert scholar._http_get_json(S2_URL) == {"ok": 1}
        assert [u for u, _ in calls] == [S2_URL, "https://evil.example/collect"]
        assert calls[0][1]["x-api-key"] == "sekrit"
        assert "x-api-key" not in calls[1][1]

    def test_key_reattached_when_redirect_lands_back_on_s2(self, monkeypatch, no_sleep):
        monkeypatch.setenv("S2_API_KEY", "sekrit")
        calls = _stub_httpx(monkeypatch, [
            _Resp(301, headers={"Location": "https://evil.example/hop"}),
            _Resp(302, headers={"Location": "/graph/v1/paper/y"}),  # relative
            _Resp(200, {"ok": 2}),
        ])
        assert scholar._http_get_json(S2_URL) == {"ok": 2}
        assert [u for u, _ in calls] == [
            S2_URL, "https://evil.example/hop", "https://evil.example/graph/v1/paper/y",
        ]
        assert "x-api-key" not in calls[1][1]
        assert "x-api-key" not in calls[2][1]

        calls = _stub_httpx(monkeypatch, [
            _Resp(302, headers={"Location": "https://api.semanticscholar.org/v2"}),
            _Resp(200, {"ok": 3}),
        ])
        assert scholar._http_get_json(S2_URL) == {"ok": 3}
        assert calls[1][1]["x-api-key"] == "sekrit"

    def test_redirect_chain_is_bounded(self, monkeypatch, no_sleep):
        calls = _stub_httpx(monkeypatch, [
            _Resp(302, headers={"Location": f"https://api.semanticscholar.org/loop/{i}"})
            for i in range(50)
        ])
        assert scholar._http_get_json(S2_URL) is None
        assert len(calls) == scholar._MAX_REDIRECTS + 1

    def test_redirect_to_non_http_scheme_is_not_followed(self, monkeypatch, no_sleep):
        calls = _stub_httpx(monkeypatch, [
            _Resp(302, headers={"Location": "file:///etc/passwd"}),
        ])
        assert scholar._http_get_json(S2_URL) is None
        assert len(calls) == 1

    def test_redirect_without_location_is_soft_none(self, monkeypatch, no_sleep):
        calls = _stub_httpx(monkeypatch, [_Resp(304)])
        assert scholar._http_get_json(S2_URL) is None
        assert len(calls) == 1

    @pytest.mark.parametrize("raw", ["-5", "nan", "inf", "1e12", "9" * 40, "", "  "])
    def test_hostile_retry_after_never_sleeps_beyond_the_ladder(self, monkeypatch, no_sleep, raw):
        _stub_httpx(monkeypatch, [
            _Resp(429, headers={"Retry-After": raw}),
            _Resp(429, headers={"Retry-After": raw}),
            _Resp(200, {"a": 1}),
        ])
        scholar._http_get_json(S2_URL)
        assert no_sleep == [2.0, 4.0]
        assert sum(no_sleep) <= 2 * scholar._RETRY_AFTER_MAX

    def test_rate_limited_error_never_carries_the_key(self, monkeypatch, no_sleep):
        monkeypatch.setenv("S2_API_KEY", "sekrit")
        _stub_httpx(monkeypatch, [_Resp(429)] * 3)
        with pytest.raises(scholar.RateLimitedError) as exc:
            scholar._http_get_json(S2_URL)
        assert "sekrit" not in str(exc.value)
        assert "sekrit" not in repr(exc.value)
