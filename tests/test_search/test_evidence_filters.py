"""Evidence selection through the CLI, MCP and semantic search, fully offline."""

import json

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.core import embed
from hyperresearch.core.note import write_note
from hyperresearch.core.sync import compute_sync_plan, execute_sync
from hyperresearch.search.filters import SearchFilters
from hyperresearch.search.fts import SearchQueryError, search_fts


@pytest.fixture
def evidence_vault(tmp_vault):
    for name, metadata in [
        ("published", dict(doi="10.1234/ABC", venue="Nature", citation_count=50,
                           is_retracted=False, oa_version="publishedVersion")),
        ("accepted", dict(venue="Nature", citation_count=10, is_retracted=False,
                          oa_version="acceptedVersion")),
        ("retracted", dict(venue="Nature", citation_count=100, is_retracted=True,
                           oa_version="publishedVersion")),
        ("preprint", dict(citation_count=0, oa_version="submittedVersion")),
        ("unchecked", {}),
    ]:
        write_note(tmp_vault.notes_dir, name, body="Evidence for retrieval.",
                   tags=["retrieval"], summary=f"Summary of {name}",
                   extra_frontmatter=metadata)
    execute_sync(tmp_vault, compute_sync_plan(tmp_vault))
    return tmp_vault


@pytest.mark.parametrize(("filters", "expected"), [
    (dict(doi="10.1234/abc"), {"published"}),
    (dict(venue="nature"), {"published", "accepted", "retracted"}),
    (dict(min_citations=50), {"published", "retracted"}),
    (dict(min_citations=0), {"published", "accepted", "retracted", "preprint"}),
    (dict(retraction="not-retracted"), {"published", "accepted"}),
    (dict(retraction="retracted"), {"retracted"}),
    (dict(retraction="unchecked"), {"preprint", "unchecked"}),
    (dict(oa_version="submittedVersion"), {"preprint"}),
    (dict(oa_version="acceptedVersion"), {"accepted"}),
    (dict(venue="Nature", min_citations=20, retraction="not-retracted",
          oa_version="publishedVersion", tags=["retrieval"]), {"published"}),
    (dict(venue="Nature' OR 1=1 --"), set()),
])
@pytest.mark.parametrize("query", ["", "retrieval"])
def test_evidence_selection(evidence_vault, filters, expected, query):
    results = search_fts(evidence_vault.db, query, filters=SearchFilters(**filters))
    assert {r["id"] for r in results} == expected


def test_filter_only_pagination_and_metadata(evidence_vault):
    filters = SearchFilters(venue="Nature")
    all_results = search_fts(evidence_vault.db, "", filters=filters)
    page = search_fts(evidence_vault.db, "", filters=filters, limit=1, offset=1)
    assert page == all_results[1:2]
    by_id = {r["id"]: r for r in all_results}
    assert by_id["published"]["is_retracted"] is False
    assert by_id["retracted"]["is_retracted"] is True
    assert by_id["published"]["doi"] == "10.1234/ABC"
    assert by_id["published"]["citation_count"] == 50
    assert by_id["published"]["oa_version"] == "publishedVersion"
    unknown = search_fts(evidence_vault.db, "", filters=SearchFilters(retraction="unchecked"))
    assert all(r["is_retracted"] is None for r in unknown)
    assert all(r["snippet"] == f"Summary of {r['id']}" for r in all_results)


def test_invalid_text_does_not_turn_into_metadata_browse(evidence_vault):
    with pytest.raises(SearchQueryError):
        search_fts(evidence_vault.db, "***", filters=SearchFilters(venue="Nature"))


@pytest.mark.parametrize("args", [
    ["--min-citations", "-1"], ["--retraction", "false"],
    ["--oa-version", "peer-reviewed"], ["--semantic", "--venue", "Nature"],
])
def test_cli_rejects_invalid_filters_before_vault_discovery(tmp_path, monkeypatch, args):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, ["search", *args, "-j"])
    assert result.exit_code == 1
    assert "INVALID_FILTER" in result.stdout


def test_cli_and_mcp_filter_without_text(evidence_vault, monkeypatch):
    monkeypatch.chdir(evidence_vault.root)
    result = CliRunner().invoke(app, [
        "search", "--doi", "10.1234/abc", "--venue", "nature", "--min-citations", "50",
        "--retraction", "not-retracted", "--oa-version", "publishedVersion", "-j",
    ])
    assert result.exit_code == 0, result.output
    rows = json.loads(result.stdout)["data"]["results"]
    assert [r["id"] for r in rows] == ["published"]
    assert rows[0]["is_retracted"] is False

    mcp = pytest.importorskip("hyperresearch.mcp.server")
    monkeypatch.setattr(mcp, "_vault", evidence_vault)
    mcp_rows = json.loads(mcp.search_notes(
        doi="10.1234/abc", venue="nature", min_citations=50,
        retraction="not-retracted", oa_version="publishedVersion",
    ))
    assert [r["id"] for r in mcp_rows] == ["published"]
    assert mcp_rows[0]["is_retracted"] is False
    assert "Evidence for retrieval" in mcp_rows[0]["body"]
    assert mcp.search_notes(retraction="false").startswith("Invalid search filter:")


def test_hybrid_filters_before_semantic_limit(evidence_vault, monkeypatch):
    config = evidence_vault.config_path
    config.write_text(config.read_text().replace('provider = "none"', 'provider = "openai"'))
    vault = type(evidence_vault).discover(evidence_vault.root)
    monkeypatch.setattr(embed, "_http_embed", lambda *args: [[1.0, 0.0]])
    # The strongest matches must be excluded BEFORE top-k selection.
    for note_id, vector in [("retracted", [1.0, 0.0]), ("unchecked", [1.0, 0.0]),
                            ("accepted", [1.0, 0.0]), ("published", [0.5, 0.5])]:
        vault.db.execute("INSERT INTO embeddings VALUES (?, 'test', 2, ?, '2026-01-01')",
                         (note_id, embed._pack(vector)))
    vault.db.commit()
    filters = SearchFilters(retraction="not-retracted", min_citations=50)
    assert [r["id"] for r in embed.semantic_search(vault, "unmatched", limit=1, filters=filters)] == ["published"]
    monkeypatch.chdir(vault.root)
    result = CliRunner().invoke(app, [
        "search", "unmatched", "--semantic", "--retraction", "not-retracted",
        "--min-citations", "50", "--limit", "1", "-j",
    ])
    assert result.exit_code == 0, result.output
    rows = json.loads(result.stdout)["data"]["results"]
    assert [r["id"] for r in rows] == ["published"]
    assert rows[0]["is_retracted"] is False
    assert rows[0]["citation_count"] == 50
