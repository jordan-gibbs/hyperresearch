"""Tests for claims persistence (WS5) and embeddings (WS6) — fully offline."""

from __future__ import annotations

import json

import pytest

from hyperresearch.core import embed
from hyperresearch.core.claims import (
    ingest_claims_dir,
    ingest_claims_file,
    list_claims,
    search_claims,
)
from hyperresearch.core.embed import (
    EmbeddingError,
    cosine,
    reciprocal_rank_fusion,
)


@pytest.fixture
def claims_vault(seeded_vault):
    """Seeded vault plus a claims JSON file for one of its notes."""
    temp = seeded_vault.root / "research" / "temp"
    temp.mkdir(parents=True, exist_ok=True)
    claims = [
        {
            "claim": "Async IO improves throughput for network-bound workloads",
            "quoted_support": "async/await syntax enables concurrent I/O",
            "numbers": ["10x"],
            "confidence": "high",
            "evidence_type": "empirical",
            "stance_target": "async-performance",
            "stance": "supports",
        },
        {
            "claim": "GIL limits CPU-bound parallelism",
            "confidence": "medium",
            "evidence_type": "opinion",
        },
    ]
    (temp / "claims-python-async-patterns.json").write_text(
        json.dumps(claims), encoding="utf-8"
    )
    return seeded_vault


class TestClaimsIngest:
    def test_ingest_and_list(self, claims_vault):
        summary = ingest_claims_dir(claims_vault, vault_tag="test-run")
        assert summary["ingested"] == 2
        assert summary["errors"] == []
        rows = list_claims(claims_vault.db, note_id="python-async-patterns")
        assert len(rows) == 2
        assert rows[0]["vault_tag"] == "test-run"
        assert json.loads(rows[0]["numbers"]) == ["10x"]

    def test_reingest_is_idempotent(self, claims_vault):
        ingest_claims_dir(claims_vault)
        second = ingest_claims_dir(claims_vault)
        assert second["ingested"] == 0
        assert second["skipped"] == 2
        assert len(list_claims(claims_vault.db)) == 2

    def test_fts_search(self, claims_vault):
        ingest_claims_dir(claims_vault)
        hits = search_claims(claims_vault.db, "throughput")
        assert len(hits) == 1
        assert hits[0]["note_id"] == "python-async-patterns"

    def test_unknown_note_errors_softly(self, claims_vault):
        temp = claims_vault.root / "research" / "temp"
        (temp / "claims-nonexistent-note.json").write_text("[]", encoding="utf-8")
        summary = ingest_claims_dir(claims_vault)
        assert any("not in vault" in e for e in summary["errors"])

    def test_wrapper_format_accepted(self, claims_vault, tmp_path):
        p = claims_vault.root / "research" / "temp" / "claims-rust-ownership.json"
        p.write_text(json.dumps({"claims": [{"claim": "Ownership prevents data races"}]}), encoding="utf-8")
        r = ingest_claims_file(claims_vault.db, p)
        claims_vault.db.commit()
        assert r["ingested"] == 1

    def test_claims_cli(self, claims_vault, monkeypatch):
        from typer.testing import CliRunner

        from hyperresearch.cli import app

        monkeypatch.chdir(claims_vault.root)
        runner = CliRunner()
        result = runner.invoke(app, ["claims", "ingest", "--tag", "cli-run", "--json"])
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["data"]["ingested"] == 2

        result = runner.invoke(app, ["claims", "search", "throughput", "--json"])
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["count"] == 1


def _write_claims(directory, note_id: str, *claims: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"claims-{note_id}.json").write_text(
        json.dumps([{"claim": c} for c in claims]), encoding="utf-8"
    )


@pytest.fixture
def run_scoped_vault(seeded_vault):
    """Seeded vault whose claims live where the fetcher contract writes
    them: research/runs/<vault_tag>/temp/ — two runs, nothing in the
    legacy flat research/temp/."""
    runs = seeded_vault.root / "research" / "runs"
    _write_claims(runs / "run-a" / "temp", "python-async-patterns", "A1 async claim", "A2 async claim")
    _write_claims(runs / "run-b" / "temp", "rust-ownership", "B1 ownership claim")
    return seeded_vault


class TestClaimsIngestRunWorkspace:
    """#69 — the default scan must see the run workspace, not just research/temp/."""

    def test_default_scan_finds_run_workspace_claims(self, run_scoped_vault):
        assert not list((run_scoped_vault.root / "research" / "temp").glob("claims-*.json"))
        summary = ingest_claims_dir(run_scoped_vault)
        assert summary["files"] == 2
        assert summary["ingested"] == 3
        assert summary["errors"] == []
        assert "hint" not in summary
        assert len(list_claims(run_scoped_vault.db)) == 3

    def test_default_scan_unions_legacy_flat_and_runs(self, run_scoped_vault):
        _write_claims(run_scoped_vault.root / "research" / "temp", "concurrency", "Legacy flat claim")
        summary = ingest_claims_dir(run_scoped_vault)
        assert summary["files"] == 3
        assert summary["ingested"] == 4
        notes = {r["note_id"] for r in list_claims(run_scoped_vault.db)}
        assert notes == {"python-async-patterns", "rust-ownership", "concurrency"}

    def test_tag_narrows_to_that_run(self, run_scoped_vault):
        summary = ingest_claims_dir(run_scoped_vault, vault_tag="run-a")
        assert summary["files"] == 1
        assert summary["ingested"] == 2
        assert summary["scanned"] == [str(run_scoped_vault.root / "research" / "runs" / "run-a" / "temp")]
        rows = list_claims(run_scoped_vault.db)
        assert {r["note_id"] for r in rows} == {"python-async-patterns"}
        assert {r["vault_tag"] for r in rows} == {"run-a"}

    def test_tag_without_run_dir_falls_back_to_union(self, run_scoped_vault):
        summary = ingest_claims_dir(run_scoped_vault, vault_tag="no-such-run")
        assert summary["files"] == 2
        assert summary["ingested"] == 3
        assert {r["vault_tag"] for r in list_claims(run_scoped_vault.db)} == {"no-such-run"}

    def test_explicit_dir_scans_only_itself(self, run_scoped_vault):
        explicit = run_scoped_vault.root / "research" / "runs" / "run-b" / "temp"
        summary = ingest_claims_dir(run_scoped_vault, temp_dir=explicit, vault_tag="run-a")
        assert summary["files"] == 1
        assert summary["ingested"] == 1
        assert summary["scanned"] == [str(explicit)]
        assert {r["note_id"] for r in list_claims(run_scoped_vault.db)} == {"rust-ownership"}

    def test_zero_files_carries_hint(self, seeded_vault):
        summary = ingest_claims_dir(seeded_vault)
        assert summary["files"] == 0
        assert "research/runs/<vault_tag>/temp/claims-<note-id>.json" in summary["hint"]

    def test_cli_tag_form_used_by_width_sweep_skill(self, run_scoped_vault, monkeypatch):
        from typer.testing import CliRunner

        from hyperresearch.cli import app

        monkeypatch.chdir(run_scoped_vault.root)
        runner = CliRunner()
        # Exact invocation from skills/hyperresearch-2-width-sweep.md
        result = runner.invoke(app, ["claims", "ingest", "--tag", "run-a", "-j"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["data"]["files"] == 1
        assert payload["data"]["ingested"] == 2

        result = runner.invoke(app, ["claims", "list", "--tag", "run-a", "--json"])
        assert json.loads(result.stdout)["count"] == 2

        # Human-readable zero-file case (run exists, no claims yet) surfaces the hint
        (run_scoped_vault.root / "research" / "runs" / "run-empty" / "temp").mkdir(parents=True)
        result = runner.invoke(app, ["claims", "ingest", "--tag", "run-empty"])
        assert result.exit_code == 0, result.output
        assert "from 0 file(s)" in result.output
        assert "no claims-*.json found" in result.output


class TestEmbeddings:
    def _fake_embedder(self, monkeypatch):
        """Deterministic fake: vector derived from text hash. Counts calls."""
        calls = {"batches": 0, "texts": 0}

        def fake(provider, model, texts):
            calls["batches"] += 1
            calls["texts"] += len(texts)
            out = []
            for t in texts:
                h = sum(ord(c) for c in t) % 97
                out.append([float(h), 1.0, float(len(t) % 13)])
            return out

        monkeypatch.setattr(embed, "_http_embed", fake)
        return calls

    def test_provider_none_raises_cleanly(self, seeded_vault):
        with pytest.raises(EmbeddingError, match="disabled"):
            embed.embed_sync(seeded_vault)

    def test_embed_sync_and_incremental(self, seeded_vault, monkeypatch):
        calls = self._fake_embedder(monkeypatch)
        cfg_path = seeded_vault.config_path
        cfg_path.write_text(
            cfg_path.read_text(encoding="utf-8").replace(
                'provider = "none"', 'provider = "openai"'
            ),
            encoding="utf-8",
        )
        # Fresh Vault object so the edited config is re-read
        vault = type(seeded_vault).discover(seeded_vault.root)

        r1 = embed.embed_sync(vault)
        assert r1["embedded"] >= 4
        assert r1["provider"] == "openai"
        assert calls["texts"] == r1["embedded"]

        r2 = embed.embed_sync(vault)
        assert r2["embedded"] == 0  # unchanged content -> no re-embedding
        assert r2["skipped"] >= 4

        hits = embed.semantic_search(vault, "concurrency patterns", limit=3)
        assert len(hits) == 3
        assert all("id" in h and "score" in h for h in hits)

    def test_cosine(self):
        assert cosine([1, 0], [1, 0]) == pytest.approx(1.0)
        assert cosine([1, 0], [0, 1]) == pytest.approx(0.0)
        assert cosine([], []) == 0.0

    def test_rrf_fusion(self):
        fused = reciprocal_rank_fusion([["a", "b", "c"], ["b", "a", "d"]])
        ids = [x[0] for x in fused]
        # a and b appear in both lists -> outrank c and d
        assert set(ids[:2]) == {"a", "b"}

    def test_vector_pack_roundtrip(self):
        vec = [0.5, -1.25, 3.0]
        assert embed._unpack(embed._pack(vec)) == vec

    def _openai_vault(self, seeded_vault, monkeypatch):
        self._fake_embedder(monkeypatch)
        cfg_path = seeded_vault.config_path
        cfg_path.write_text(
            cfg_path.read_text(encoding="utf-8").replace(
                'provider = "none"', 'provider = "openai"'
            ),
            encoding="utf-8",
        )
        vault = type(seeded_vault).discover(seeded_vault.root)
        embed.embed_sync(vault)
        return vault

    def test_semantic_search_matches_naive_cosine(self, seeded_vault, monkeypatch):
        """#59 — the numpy matmul in `semantic_search` must rank and score
        exactly like a plain per-row `cosine()` loop, computed independently
        here rather than by re-running `semantic_search` itself."""
        vault = self._openai_vault(seeded_vault, monkeypatch)
        query = "concurrency patterns"
        cfg = vault.config.embeddings
        model = cfg.model or embed.DEFAULT_MODELS[cfg.provider]
        [query_vec] = embed._http_embed(cfg.provider, model, [query])

        naive = [
            {"id": row["note_id"], "score": cosine(query_vec, embed._unpack(row["vector"]))}
            for row in vault.db.execute("SELECT note_id, vector FROM embeddings").fetchall()
        ]
        naive.sort(key=lambda r: r["score"], reverse=True)

        hits = embed.semantic_search(vault, query, limit=len(naive))
        assert [h["id"] for h in hits] == [n["id"] for n in naive]
        for h, n in zip(hits, naive, strict=True):
            assert h["score"] == pytest.approx(n["score"], abs=1e-5)

    def test_semantic_search_scores_dimension_mismatch_as_zero(self, seeded_vault, monkeypatch):
        """A note still holding a vector from a since-changed embeddings
        model/dimension (mid-migration, before the next `embed sync`) can't
        join the matmul's matrix — it must score 0 instead of crashing or
        reshape()-ing garbage, same as `cosine()` did on a length mismatch."""
        vault = self._openai_vault(seeded_vault, monkeypatch)
        note_id = vault.db.execute("SELECT note_id FROM embeddings LIMIT 1").fetchone()["note_id"]
        vault.db.execute(
            "UPDATE embeddings SET vector = ? WHERE note_id = ?",
            (embed._pack([1.0, 2.0]), note_id),
        )
        vault.db.commit()

        hits = embed.semantic_search(vault, "concurrency patterns", limit=10)
        assert len(hits) == 4
        mismatched = next(h for h in hits if h["id"] == note_id)
        assert mismatched["score"] == 0.0


class TestClaimsIngestHostileInput:
    """Security review of #69: `--tag` is a CLI argument an agent may have
    been talked into, and claims JSON is agent-written from fetched page
    content. Neither may steer the scan outside the vault or crash it."""

    def _texts(self, vault) -> set[str]:
        return {c["claim"] for c in list_claims(vault.db)}

    def test_relative_tag_cannot_escape_runs_dir(self, run_scoped_vault, tmp_path):
        import os

        from hyperresearch.core.claims import default_claims_dirs

        vault = run_scoped_vault
        outside = tmp_path / "outside-vault"
        _write_claims(outside / "temp", "python-async-patterns", "OUTSIDE claim")
        runs = vault.root / "research" / "runs"
        escaping_tag = os.path.relpath(outside, runs)  # ../../..\\outside-vault
        assert ".." in escaping_tag

        dirs = [d.resolve() for d in default_claims_dirs(vault, escaping_tag)]
        assert (outside / "temp").resolve() not in dirs
        summary = ingest_claims_dir(vault, vault_tag=escaping_tag)
        assert "OUTSIDE claim" not in self._texts(vault)
        # Fell through to the default union of run workspaces.
        assert summary["ingested"] == 3

    def test_absolute_tag_cannot_escape_runs_dir(self, run_scoped_vault, tmp_path):
        from hyperresearch.core.claims import default_claims_dirs

        vault = run_scoped_vault
        outside = tmp_path / "abs-outside"
        _write_claims(outside / "temp", "python-async-patterns", "ABS OUTSIDE claim")
        dirs = [d.resolve() for d in default_claims_dirs(vault, str(outside))]
        assert (outside / "temp").resolve() not in dirs
        ingest_claims_dir(vault, vault_tag=str(outside))
        assert "ABS OUTSIDE claim" not in self._texts(vault)

    def test_symlinked_claims_file_outside_vault_is_skipped(self, run_scoped_vault, tmp_path):
        import os

        from hyperresearch.core.claims import discover_claims_files

        vault = run_scoped_vault
        target = tmp_path / "elsewhere" / "claims-python-async-patterns.json"
        target.parent.mkdir()
        target.write_text(json.dumps([{"claim": "LINKED claim"}]), encoding="utf-8")
        link = vault.root / "research" / "runs" / "run-b" / "temp" / "claims-python-async-patterns.json"
        try:
            os.symlink(target, link)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks unavailable on this host")
        assert link.resolve() not in {f.resolve() for f in discover_claims_files(vault)}
        ingest_claims_dir(vault)
        assert "LINKED claim" not in self._texts(vault)

    def test_oversized_claims_file_is_skipped_not_read(self, run_scoped_vault, monkeypatch):
        from hyperresearch.core import claims as claims_mod

        vault = run_scoped_vault
        monkeypatch.setattr(claims_mod, "MAX_CLAIMS_FILE_BYTES", 64)
        big = vault.root / "research" / "runs" / "run-a" / "temp" / "claims-python-async-patterns.json"
        big.write_text(json.dumps([{"claim": "x" * 500}]), encoding="utf-8")
        summary = ingest_claims_dir(vault)
        assert any("limit 64" in e for e in summary["errors"])
        assert "x" * 500 not in self._texts(vault)
        assert summary["ingested"] == 1  # run-b still ingested

    def test_malformed_claim_fields_do_not_abort_ingest(self, run_scoped_vault):
        vault = run_scoped_vault
        path = vault.root / "research" / "runs" / "run-a" / "temp" / "claims-python-async-patterns.json"
        path.write_text(json.dumps([
            {"claim": {"nested": "object"}},  # dict where prose belongs
            {"claim": 12345},  # number where prose belongs
            {"claim": ["a", "list"]},
            {"claim": True},
            {
                "claim": "survives",
                "confidence": [1, 2],  # unbindable
                "quoted_support": {"x": 1},  # unbindable
                "stance": 5,
                "evidence_type": None,
                "numbers": {"deep": [[[1]]]},
            },
            {"claim": "also survives", "confidence": 0.9, "quoted_support": "q"},
            "not even a dict",
            None,
        ]), encoding="utf-8")
        summary = ingest_claims_dir(vault)
        assert summary["ingested"] == 3  # two here + run-b's one
        assert {"survives", "also survives"} <= self._texts(vault)
        assert summary["skipped"] >= 4

    def test_overlong_claim_text_is_bounded(self, run_scoped_vault):
        from hyperresearch.core.claims import MAX_CLAIM_FIELD_CHARS

        vault = run_scoped_vault
        path = vault.root / "research" / "runs" / "run-a" / "temp" / "claims-python-async-patterns.json"
        path.write_text(json.dumps([{"claim": "y" * (MAX_CLAIM_FIELD_CHARS + 5000)}]), encoding="utf-8")
        ingest_claims_dir(vault)
        assert max(len(t) for t in self._texts(vault)) == MAX_CLAIM_FIELD_CHARS

    def test_deeply_nested_json_is_an_error_not_a_crash(self, run_scoped_vault):
        vault = run_scoped_vault
        path = vault.root / "research" / "runs" / "run-a" / "temp" / "claims-python-async-patterns.json"
        path.write_text("[" * 200_000 + "]" * 200_000, encoding="utf-8")
        summary = ingest_claims_dir(vault)
        assert any("unreadable JSON" in e for e in summary["errors"])
        assert summary["ingested"] == 1
