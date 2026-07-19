"""Phase-3 tests: dissertation profile + literature matrix + target grouping."""

from __future__ import annotations

import json

from hyperresearch.core.claims import (
    group_by_target,
    ingest_claims_dir,
    literature_matrix,
    render_matrix_markdown,
)
from hyperresearch.core.profiles import resolve_profile


class TestDissertationProfile:
    def test_builtin_resolves(self):
        p = resolve_profile("dissertation")
        assert p.chapters == (4, 10)
        assert p.chapter_concurrency == 2
        assert p.chapter_source_target == (40, 80)
        assert p.source_min == 250
        assert p.source_target == (300, 450)
        assert p.loci_max == 20
        assert p.depth_budget_total == 160
        assert p.draft_count == 1
        assert p.word_targets["dissertation"] == (25000, 80000)
        assert p.must_read["dissertation"] == (35, 50)
        assert p.critic_finding_caps["instruction"] == 30

    def test_flat_profiles_are_unchaptered(self):
        assert resolve_profile("full").chapters == (0, 0)
        assert resolve_profile("light").chapters == (0, 0)

    def test_extends_dissertation(self, tmp_path):
        cfg = tmp_path / "config.toml"
        cfg.write_text(
            '[profile.thesis]\nextends = "dissertation"\nsource_min = 150\n',
            encoding="utf-8",
        )
        p = resolve_profile("thesis", cfg)
        assert p.source_min == 150
        assert p.chapters == (4, 10)  # inherited

    def test_chapter_range_validated(self, tmp_path):
        import pytest

        from hyperresearch.core.profiles import ProfileError

        cfg = tmp_path / "config.toml"
        cfg.write_text("[profile.dissertation]\nchapters = [10, 4]\n", encoding="utf-8")
        with pytest.raises(ProfileError, match="invalid profile"):
            resolve_profile("dissertation", cfg)


class TestLiteratureMatrix:
    def _seed_claims(self, vault):
        temp = vault.root / "research" / "temp"
        temp.mkdir(parents=True, exist_ok=True)
        (temp / "claims-python-async-patterns.json").write_text(
            json.dumps([
                {"claim": "Async gives 10x throughput", "numbers": ["10x"],
                 "evidence_type": "empirical", "confidence": "high",
                 "stance_target": "async-throughput", "stance": "supports"},
                {"claim": "Async is hard to debug", "evidence_type": "opinion",
                 "stance_target": "async-throughput", "stance": "disputes"},
            ]),
            encoding="utf-8",
        )
        (temp / "claims-rust-ownership.json").write_text(
            json.dumps([
                {"claim": "Ownership eliminates data races", "evidence_type": "empirical",
                 "stance_target": "async-throughput", "stance": "supports",
                 "numbers": ["100%"]},
            ]),
            encoding="utf-8",
        )
        ingest_claims_dir(vault, vault_tag="mx-run")

    def test_matrix_rows(self, seeded_vault):
        self._seed_claims(seeded_vault)
        conn = seeded_vault.db
        conn.execute("UPDATE notes SET quality_score = 0.9, tier = 'institutional' WHERE id = 'python-async-patterns'")
        conn.execute("UPDATE notes SET quality_score = 0.3 WHERE id = 'rust-ownership'")
        conn.commit()

        rows = literature_matrix(conn, vault_tag="mx-run")
        assert len(rows) == 2
        assert rows[0]["id"] == "python-async-patterns"  # sorted by quality desc
        assert rows[0]["n_claims"] == 2
        assert rows[0]["n_empirical"] == 1
        assert rows[0]["key_claim"] == "Async gives 10x throughput"  # empirical+quantified wins

    def test_matrix_markdown_render(self, seeded_vault):
        self._seed_claims(seeded_vault)
        rows = literature_matrix(seeded_vault.db)
        md = render_matrix_markdown(rows)
        assert md.startswith("| Source |")
        assert "[[python-async-patterns]]" in md

    def test_matrix_cli_writes_file(self, seeded_vault, monkeypatch):
        from typer.testing import CliRunner

        from hyperresearch.cli import app

        self._seed_claims(seeded_vault)
        monkeypatch.chdir(seeded_vault.root)
        runner = CliRunner()
        out = seeded_vault.root / "research" / "temp" / "lit-matrix.md"
        r = runner.invoke(app, ["claims", "matrix", "--tag", "mx-run", "--out", str(out), "--json"])
        assert r.exit_code == 0
        assert out.exists()
        assert "| Source |" in out.read_text(encoding="utf-8")


class TestTargetGrouping:
    def test_groups_across_sources(self, seeded_vault):
        TestLiteratureMatrix()._seed_claims(seeded_vault)
        groups = group_by_target(seeded_vault.db, vault_tag="mx-run", min_sources=2)
        assert len(groups) == 1
        g = groups[0]
        assert g["stance_target"] == "async-throughput"
        assert g["n_sources"] == 2
        assert g["stances"] == {"supports": 2, "disputes": 1}
        assert {v["note_id"] for v in g["quantified"]} == {"python-async-patterns", "rust-ownership"}

    def test_min_sources_filters_singletons(self, seeded_vault):
        TestLiteratureMatrix()._seed_claims(seeded_vault)
        groups = group_by_target(seeded_vault.db, min_sources=3)
        assert groups == []
