"""Phase-2 source-ranking tests: schema v9, DOI capture, PageRank, quality."""

from __future__ import annotations

from hyperresearch.core.config import RankingSettings
from hyperresearch.core.graphrank import compute_centrality, pagerank
from hyperresearch.core.quality import compute_quality_for_row, compute_quality_scores
from hyperresearch.core.scholar import extract_doi


class TestSchemaV9:
    def test_new_columns_exist(self, tmp_vault):
        cols = {row[1] for row in tmp_vault.db.execute("PRAGMA table_info(notes)")}
        expected = {
            "doi", "utility_score", "authority_score", "centrality_score",
            "independence", "citation_count", "venue", "is_retracted", "quality_score",
        }
        assert expected <= cols

    def test_new_tables_exist(self, tmp_vault):
        tables = {
            row[0]
            for row in tmp_vault.db.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
            )
        }
        assert "claims" in tables
        assert "api_cache" in tables
        # claims_fts is a virtual table
        assert tmp_vault.db.execute("SELECT count(*) FROM claims_fts").fetchone() is not None

    def test_migration_from_v8_is_idempotent(self, tmp_vault):
        from hyperresearch.core.migrations import _migrate_v9_source_ranking

        _migrate_v9_source_ranking(tmp_vault.db)  # re-run on already-migrated DB
        cols = {row[1] for row in tmp_vault.db.execute("PRAGMA table_info(notes)")}
        assert "quality_score" in cols

    def test_frontmatter_roundtrip(self, tmp_vault):
        from hyperresearch.core.note import write_note
        from hyperresearch.core.sync import compute_sync_plan, execute_sync

        write_note(
            tmp_vault.notes_dir,
            "Ranked Paper",
            body="A paper with ranking metadata.",
            extra_frontmatter={
                "doi": "10.1234/example",
                "utility_score": 14.0,
                "citation_count": 42,
                "venue": "NeurIPS",
                "is_retracted": False,
            },
        )
        plan = compute_sync_plan(tmp_vault, force=True)
        execute_sync(tmp_vault, plan)
        row = tmp_vault.db.execute(
            "SELECT doi, utility_score, citation_count, venue, is_retracted "
            "FROM notes WHERE id = 'ranked-paper'"
        ).fetchone()
        assert row["doi"] == "10.1234/example"
        assert row["utility_score"] == 14.0
        assert row["citation_count"] == 42
        assert row["venue"] == "NeurIPS"
        assert row["is_retracted"] == 0

    def test_derived_scores_survive_resync(self, seeded_vault):
        conn = seeded_vault.db
        conn.execute(
            "UPDATE notes SET quality_score = 0.9, centrality_score = 0.5 "
            "WHERE id = 'concurrency'"
        )
        conn.commit()
        from hyperresearch.core.sync import compute_sync_plan, execute_sync

        plan = compute_sync_plan(seeded_vault, force=True)
        execute_sync(seeded_vault, plan)
        row = conn.execute(
            "SELECT quality_score, centrality_score FROM notes WHERE id = 'concurrency'"
        ).fetchone()
        assert row["quality_score"] == 0.9
        assert row["centrality_score"] == 0.5


class TestDoiExtraction:
    def test_doi_org_url(self):
        assert extract_doi("https://doi.org/10.1038/s41586-024-0001-2") == "10.1038/s41586-024-0001-2"

    def test_arxiv_abs_and_pdf(self):
        assert extract_doi("https://arxiv.org/abs/2501.01234") == "arXiv:2501.01234"
        assert extract_doi("https://arxiv.org/pdf/2501.01234v2") == "arXiv:2501.01234v2"

    def test_citation_meta_tag(self):
        html = '<head><meta name="citation_doi" content="10.1145/3576915.3616613"></head>'
        assert extract_doi("https://example.com/paper", raw_html=html) == "10.1145/3576915.3616613"

    def test_body_doi_marker(self):
        body = "Published in Nature. DOI: 10.1038/nphys1170 (2024)."
        assert extract_doi("https://example.com/x", content=body) == "10.1038/nphys1170"

    def test_no_doi(self):
        assert extract_doi("https://example.com/blog-post", content="just a blog") is None

    def test_trailing_punctuation_stripped(self):
        assert extract_doi("https://x.com", content="see DOI: 10.1000/xyz123.") == "10.1000/xyz123"

    def test_body_doi_inside_code_span(self):
        # Extracted page text renders <code> as a backtick span; the backtick
        # must not end up in the DOI, and must not hide it either.
        assert extract_doi("https://x.com", content="cite `DOI: 10.1000/xyz123` here") == "10.1000/xyz123"
        assert extract_doi("https://x.com", content="DOI: `10.1000/xyz123`") == "10.1000/xyz123"


class TestPageRank:
    def test_hub_ranks_highest(self):
        nodes = ["hub", "a", "b", "c"]
        edges = [("a", "hub"), ("b", "hub"), ("c", "hub"), ("hub", "a")]
        scores = pagerank(nodes, edges)
        assert scores["hub"] == max(scores.values())

    def test_empty_graph(self):
        assert pagerank([], []) == {}

    def test_dangling_nodes_handled(self):
        scores = pagerank(["a", "b"], [("a", "b")])
        assert abs(sum(scores.values()) - 1.0) < 0.01

    def test_compute_centrality_on_seeded_vault(self, seeded_vault):
        n = compute_centrality(seeded_vault.db)
        assert n > 0
        rows = seeded_vault.db.execute(
            "SELECT id, centrality_score FROM notes ORDER BY centrality_score DESC"
        ).fetchall()
        assert rows[0]["centrality_score"] == 1.0  # normalized by max
        # The MOC/hub notes are linked from multiple notes → should outrank the orphan
        by_id = {r["id"]: r["centrality_score"] for r in rows}
        assert by_id["concurrency"] > by_id["orphan-note"]


class TestQualityComposite:
    R = RankingSettings()

    def test_retraction_floors_everything(self):
        q = compute_quality_for_row(self.R, "ground_truth", 18.0, 1.0, 1.0, True)
        assert q == self.R.retraction_floor

    def test_tier_only_renormalizes(self):
        q = compute_quality_for_row(self.R, "ground_truth", None, None, None, False)
        assert q == 1.0  # single component, full weight on tier weight 1.0

    def test_no_components_gives_none(self):
        assert compute_quality_for_row(self.R, None, None, None, None, False) is None

    def test_full_composite_weighting(self):
        q = compute_quality_for_row(self.R, "commentary", 9.0, 0.5, 0.5, False)
        # (0.35*0.4 + 0.2*0.5 + 0.25*0.5 + 0.2*0.5) / 1.0
        assert abs(q - (0.35 * 0.4 + 0.2 * 0.5 + 0.25 * 0.5 + 0.2 * 0.5)) < 1e-9

    def test_ground_truth_beats_commentary(self):
        gt = compute_quality_for_row(self.R, "ground_truth", None, None, None, False)
        com = compute_quality_for_row(self.R, "commentary", None, None, None, False)
        assert gt > com

    def test_compute_all(self, seeded_vault):
        conn = seeded_vault.db
        conn.execute("UPDATE notes SET tier = 'ground_truth' WHERE id = 'concurrency'")
        conn.execute("UPDATE notes SET tier = 'commentary' WHERE id = 'orphan-note'")
        conn.commit()
        updated = compute_quality_scores(conn, self.R)
        assert updated >= 4
        rows = {
            r["id"]: r["quality_score"]
            for r in conn.execute("SELECT id, quality_score FROM notes")
        }
        assert rows["concurrency"] > rows["orphan-note"]


class TestRankedSearch:
    def test_quality_reorders_equal_relevance(self, seeded_vault):
        from hyperresearch.search.fts import search_fts

        conn = seeded_vault.db
        # Two notes both matching "concurrency"; give one a high and one a low quality
        conn.execute("UPDATE notes SET quality_score = 0.95 WHERE id = 'rust-ownership'")
        conn.execute("UPDATE notes SET quality_score = 0.05 WHERE id = 'python-async-patterns'")
        conn.commit()

        plain = search_fts(conn, "concurrency", ranking={})
        ranked = search_fts(conn, "concurrency", ranking={}, quality_ranked=True)
        ids_ranked = [r["id"] for r in ranked]
        assert ids_ranked.index("rust-ownership") < ids_ranked.index("python-async-patterns")
        # Default search unchanged: quality did not affect the plain ordering
        assert [r["id"] for r in plain] != ids_ranked or plain != ranked

    def test_search_cli_ranked_flag(self, seeded_vault, monkeypatch):
        import json

        from typer.testing import CliRunner

        from hyperresearch.cli import app

        monkeypatch.chdir(seeded_vault.root)
        runner = CliRunner()
        result = runner.invoke(app, ["search", "concurrency", "--ranked", "--json"])
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["ok"] is True


class TestStubExclusion:
    """Resolver-minted stubs (`repair --stub` / `graph stub`) must not pollute
    either ranker: a stub exists only because something linked to it, so its
    inbound-link count is tautological (issue #93).
    """

    @staticmethod
    def _mint_stub(vault, target: str) -> None:
        from hyperresearch.core.note import stub_summary, write_note
        from hyperresearch.core.sync import compute_sync_plan, execute_sync

        # Mirror cli/repair.py + cli/graph.py exactly.
        write_note(
            vault.temp_dir,
            target.replace("-", " ").title(),
            body=f"# {target}\n\n*Stub — created to resolve a broken link. Expand this note.*\n",
            note_id=target,
            status="draft",
            summary=stub_summary(target),
        )
        execute_sync(vault, compute_sync_plan(vault))

    def test_stub_absent_from_most_linked_index(self, seeded_vault):
        from hyperresearch.indexgen.generator import IndexGenerator

        # seeded_vault's "concurrency" MOC links to [[nonexistent-topic]].
        self._mint_stub(seeded_vault, "nonexistent-topic")
        resolved = seeded_vault.db.execute(
            "SELECT target_id FROM links WHERE target_ref = 'nonexistent-topic'"
        ).fetchone()
        assert resolved["target_id"] == "nonexistent-topic"  # the link DID resolve

        gen = IndexGenerator(seeded_vault)
        gen._build_most_linked()
        text = (seeded_vault.index_dir / "_most-linked.md").read_text(encoding="utf-8")
        assert "[[nonexistent-topic]]" not in text
        assert "[[concurrency]]" in text  # real hubs still listed

    def test_stub_receives_no_pagerank_weight(self, seeded_vault):
        self._mint_stub(seeded_vault, "nonexistent-topic")
        # Simulate a vault ranked BEFORE the exclusion: stale weight on the stub.
        seeded_vault.db.execute(
            "UPDATE notes SET centrality_score = 0.9 WHERE id = 'nonexistent-topic'"
        )
        seeded_vault.db.commit()

        n = compute_centrality(seeded_vault.db)
        by_id = {
            r["id"]: r["centrality_score"]
            for r in seeded_vault.db.execute("SELECT id, centrality_score FROM notes").fetchall()
        }
        assert "nonexistent-topic" in by_id
        assert by_id["nonexistent-topic"] == 0.0
        # Stub was excluded from the ranked node set entirely.
        assert n == len(by_id) - 1
        # Real notes still ranked and normalized.
        assert max(by_id.values()) == 1.0
        assert by_id["concurrency"] > by_id["orphan-note"]
