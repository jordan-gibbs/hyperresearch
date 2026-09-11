"""`hpr scholar` CLI surface.

No network and no real provider: the registry is monkeypatched to hand back
fakes defined here. That is deliberate — these tests must keep passing while
provider modules are added, renamed, or removed, and they must not depend on
whoever runs them holding an API key.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.scholar.base import Paper, ProviderError, SearchProvider

runner = CliRunner()


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


def make_provider(
    slug: str,
    *,
    papers: tuple[Paper, ...] = (),
    raises: Exception | None = None,
    needs_key: bool = False,
    key_env: tuple[str, ...] = (),
    covers: str = "Fake coverage",
) -> SearchProvider:
    """A concrete SearchProvider built at test time, with a call log."""
    calls: list[dict[str, Any]] = []

    def search(
        self: SearchProvider,
        conn: Any,
        query: str,
        limit: int,
        *,
        fresh: bool = False,
    ) -> list[Paper]:
        calls.append({"query": query, "limit": limit, "fresh": fresh, "conn": conn})
        if raises is not None:
            raise raises
        return list(papers)

    cls = type(
        f"Fake_{slug}",
        (SearchProvider,),
        {
            "slug": slug,
            "label": f"{slug.capitalize()} Index",
            "covers": covers,
            "needs_key": needs_key,
            "key_env": key_env,
            "search": search,
            "calls": calls,
        },
    )
    return cls()  # type: ignore[no-any-return]


def install(monkeypatch: pytest.MonkeyPatch, *providers: SearchProvider) -> None:
    """Point the registry at `providers` and keep the search cache out of it."""
    from hyperresearch.cli import scholar_cmd
    from hyperresearch.scholar import registry

    def fake_get_providers(
        slugs: list[str] | None = None,
        *,
        scope: str = "all",
        include_unavailable: bool = False,
    ) -> list[SearchProvider]:
        found = list(providers)
        if scope == "papers":
            found = [p for p in found if p.slug in registry.PAPER_SLUGS]
        if slugs:
            wanted = {s.strip().lower() for s in slugs if s.strip()}
            found = [p for p in found if p.slug in wanted]
        if not include_unavailable:
            found = [p for p in found if p.available()]
        return found

    monkeypatch.setattr(registry, "get_providers", fake_get_providers)
    # No vault in these tests; the command must not need one.
    monkeypatch.setattr(scholar_cmd, "_open_cache", lambda: (None, None))


def payload(result: Any) -> dict[str, Any]:
    assert result.exit_code == 0, result.output
    parsed: dict[str, Any] = json.loads(result.output)
    assert parsed["ok"] is True
    return parsed


ALPHA_PAPER = Paper(
    title="Attention Is All You Need",
    source="alpha",
    doi="10.1/attn",
    year=2017,
    authors=("Vaswani, A.",),
    citation_count=100,
    url="https://alpha/attn",
)
BETA_SAME = Paper(
    title="attention is all you need",
    source="beta",
    doi="https://doi.org/10.1/ATTN",
    year=2018,
    authors=("Vaswani, A.", "Shazeer, N."),
    citation_count=9000,
    abstract="The dominant sequence transduction models...",
)
BETA_OTHER = Paper(
    title="Deep Residual Learning",
    source="beta",
    doi="10.1/resnet",
    year=2016,
)


# ---------------------------------------------------------------------------
# scholar sources
# ---------------------------------------------------------------------------


def test_sources_runs_with_zero_providers_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The registry tolerates missing provider modules; so must the CLI."""
    install(monkeypatch)
    result = runner.invoke(app, ["scholar", "sources"])
    assert result.exit_code == 0
    assert "No discovery providers" in result.output


def test_sources_json_lists_slug_label_covers_and_availability(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FAKE_GAMMA_KEY", raising=False)
    install(
        monkeypatch,
        make_provider("alpha", covers="Everything with a DOI"),
        make_provider("gamma", needs_key=True, key_env=("FAKE_GAMMA_KEY",)),
    )
    rows = payload(runner.invoke(app, ["scholar", "sources", "--json"]))["data"]
    assert [r["slug"] for r in rows] == ["alpha", "gamma"]
    assert rows[0]["covers"] == "Everything with a DOI"
    assert rows[0]["available"] is True
    assert rows[0]["reason"] is None
    # An unavailable provider is listed WITH its reason rather than hidden.
    assert rows[1]["available"] is False
    assert "FAKE_GAMMA_KEY" in rows[1]["reason"]


def test_sources_human_output_shows_the_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FAKE_GAMMA_KEY", raising=False)
    install(monkeypatch, make_provider("gamma", needs_key=True, key_env=("FAKE_GAMMA_KEY",)))
    result = runner.invoke(app, ["scholar", "sources"])
    assert result.exit_code == 0
    assert "gamma" in result.output
    assert "FAKE_GAMMA_KEY" in result.output


def test_sources_rejects_an_unknown_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch, make_provider("alpha"))
    result = runner.invoke(app, ["scholar", "sources", "--scope", "banana", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["error_code"] == "BAD_SCOPE"


# ---------------------------------------------------------------------------
# scholar search
# ---------------------------------------------------------------------------


def test_search_json_shape_and_cross_provider_merge(monkeypatch: pytest.MonkeyPatch) -> None:
    install(
        monkeypatch,
        make_provider("alpha", papers=(ALPHA_PAPER,)),
        make_provider("beta", papers=(BETA_SAME, BETA_OTHER)),
    )
    data = payload(runner.invoke(app, ["scholar", "search", "transformers", "--json"]))["data"]

    assert data["query"] == "transformers"
    assert data["providers"] == ["alpha", "beta"]
    assert data["per_source"] == {"alpha": 1, "beta": 2}
    assert data["raw_records"] == 3
    assert data["merged_records"] == 2
    assert data["failed"] == []

    first = data["results"][0]
    assert first["title"] == "Attention Is All You Need"
    assert first["source"] == "alpha"
    # Merge rules reach the wire format: max citations, longest author list,
    # the abstract only the second provider had, and the corroboration trail.
    assert first["citation_count"] == 9000
    assert first["authors"] == ["Vaswani, A.", "Shazeer, N."]
    assert first["abstract"].startswith("The dominant")
    assert first["extra"]["also_in"] == "alpha,beta"
    assert data["results"][1]["title"] == "Deep Residual Learning"


def test_search_source_filter_queries_only_that_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    alpha = make_provider("alpha", papers=(ALPHA_PAPER,))
    beta = make_provider("beta", papers=(BETA_OTHER,))
    install(monkeypatch, alpha, beta)

    data = payload(
        runner.invoke(app, ["scholar", "search", "q", "-s", "beta", "--json"])
    )["data"]

    assert data["providers"] == ["beta"]
    assert [r["title"] for r in data["results"]] == ["Deep Residual Learning"]
    assert alpha.calls == []  # type: ignore[attr-defined]
    assert len(beta.calls) == 1  # type: ignore[attr-defined]


def test_search_passes_limit_and_fresh_through_to_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    alpha = make_provider("alpha", papers=(ALPHA_PAPER,))
    install(monkeypatch, alpha)

    payload(runner.invoke(app, ["scholar", "search", "q", "-n", "7", "--fresh", "--json"]))

    call = alpha.calls[0]  # type: ignore[attr-defined]
    assert call["limit"] == 7
    assert call["fresh"] is True


def test_search_survives_a_provider_that_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    install(
        monkeypatch,
        make_provider("alpha", raises=ProviderError("alpha is down")),
        make_provider("beta", papers=(BETA_OTHER,)),
    )
    data = payload(runner.invoke(app, ["scholar", "search", "q", "--json"]))["data"]

    assert data["failed"] == [{"source": "alpha", "error": "alpha is down"}]
    assert [r["title"] for r in data["results"]] == ["Deep Residual Learning"]
    assert "alpha" not in data["per_source"]


def test_search_survives_an_unexpected_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    install(
        monkeypatch,
        make_provider("alpha", raises=ValueError("boom")),
        make_provider("beta", papers=(BETA_OTHER,)),
    )
    data = payload(runner.invoke(app, ["scholar", "search", "q", "--json"]))["data"]
    assert data["failed"][0]["source"] == "alpha"
    assert "ValueError: boom" in data["failed"][0]["error"]
    assert len(data["results"]) == 1


def test_search_empty_results(monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch, make_provider("alpha"))
    parsed = payload(runner.invoke(app, ["scholar", "search", "nothing here", "--json"]))
    assert parsed["count"] == 0
    assert parsed["data"]["results"] == []
    assert parsed["data"]["merged_records"] == 0


def test_search_empty_results_human_output(monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch, make_provider("alpha"))
    result = runner.invoke(app, ["scholar", "search", "nothing here"])
    assert result.exit_code == 0
    assert "No results" in result.output


def test_search_reports_why_a_source_was_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    """A silently smaller corpus is worse than a loud one."""
    monkeypatch.delenv("FAKE_GAMMA_KEY", raising=False)
    install(
        monkeypatch,
        make_provider("alpha", papers=(ALPHA_PAPER,)),
        make_provider("gamma", needs_key=True, key_env=("FAKE_GAMMA_KEY",)),
    )
    data = payload(runner.invoke(app, ["scholar", "search", "q", "--json"]))["data"]
    assert data["providers"] == ["alpha"]
    assert any("FAKE_GAMMA_KEY" in note for note in data["unavailable"])


def test_search_year_from_drops_older_records(monkeypatch: pytest.MonkeyPatch) -> None:
    undated = Paper(title="Undated Work", source="alpha")
    install(monkeypatch, make_provider("alpha", papers=(ALPHA_PAPER, BETA_OTHER, undated)))
    data = payload(
        runner.invoke(app, ["scholar", "search", "q", "--year-from", "2017", "--json"])
    )["data"]
    titles = [r["title"] for r in data["results"]]
    assert "Deep Residual Learning" not in titles
    assert "Attention Is All You Need" in titles
    # Undated records are kept: we drop what we can show is too old, not what
    # we simply cannot date.
    assert "Undated Work" in titles


def test_search_limit_is_per_provider_not_a_merged_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    """A post-merge cap would hide every provider but the first.

    Merge order is provider precedence, so capping the merged list at `-n`
    means a two-source search at `-n 2` returns only the first source's two
    records and the second source appears empty. The limit is passed to each
    provider; the merged list is whatever survives dedup.
    """
    alpha = tuple(Paper(title=f"A {i}", source="alpha", doi=f"10.1/a{i}") for i in range(2))
    beta = tuple(Paper(title=f"B {i}", source="beta", doi=f"10.1/b{i}") for i in range(2))
    install(
        monkeypatch,
        make_provider("alpha", papers=alpha),
        make_provider("beta", papers=beta),
    )
    data = payload(runner.invoke(app, ["scholar", "search", "q", "-n", "2", "--json"]))["data"]
    assert data["merged_records"] == 4
    assert data["returned"] == 4
    assert {r["source"] for r in data["results"]} == {"alpha", "beta"}


def test_search_scope_papers_narrows_the_provider_set(monkeypatch: pytest.MonkeyPatch) -> None:
    from hyperresearch.scholar import registry

    monkeypatch.setattr(registry, "PAPER_SLUGS", frozenset({"alpha"}))
    install(
        monkeypatch,
        make_provider("alpha", papers=(ALPHA_PAPER,)),
        make_provider("beta", papers=(BETA_OTHER,)),
    )
    data = payload(
        runner.invoke(app, ["scholar", "search", "q", "--scope", "papers", "--json"])
    )["data"]
    assert data["providers"] == ["alpha"]


def test_search_errors_when_no_provider_matches_the_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch, make_provider("alpha"))
    result = runner.invoke(app, ["scholar", "search", "q", "-s", "nope", "--json"])
    assert result.exit_code == 1
    parsed = json.loads(result.output)
    assert parsed["ok"] is False
    assert parsed["error_code"] == "NO_PROVIDERS"


def test_search_errors_with_zero_providers_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch)
    result = runner.invoke(app, ["scholar", "search", "q", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["error_code"] == "NO_PROVIDERS"


def test_search_rejects_an_unknown_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch, make_provider("alpha"))
    result = runner.invoke(app, ["scholar", "search", "q", "--scope", "banana", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["error_code"] == "BAD_SCOPE"


def test_search_human_output_shows_the_merge_trail(monkeypatch: pytest.MonkeyPatch) -> None:
    install(
        monkeypatch,
        make_provider("alpha", papers=(ALPHA_PAPER,)),
        make_provider("beta", papers=(BETA_SAME,)),
    )
    result = runner.invoke(app, ["scholar", "search", "transformers"])
    assert result.exit_code == 0
    assert "Attention Is All You Need" in result.output
    assert "also in" in result.output
