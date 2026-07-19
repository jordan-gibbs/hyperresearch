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
