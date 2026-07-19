"""Semantic search — embeddings over vault notes (revives the dormant table).

Provider-pluggable via `[embeddings] provider`:

    none    (default) semantic search disabled; zero API keys required
    voyage  Voyage AI  (VOYAGE_API_KEY, default model voyage-3-lite)
    openai  OpenAI     (OPENAI_API_KEY, default model text-embedding-3-small)

Each note is embedded from title + summary + the first `body_chars` of body.
Vectors are float32 BLOBs in the `embeddings` table; query time is brute-force
cosine (fine to ~50k notes — no vector-DB dependency).

All HTTP goes through `_http_embed`, monkeypatched in tests — the suite never
calls a paid API.
"""

from __future__ import annotations

import struct
from datetime import UTC, datetime

DEFAULT_MODELS = {
    "voyage": "voyage-3-lite",
    "openai": "text-embedding-3-small",
}


class EmbeddingError(Exception):
    pass


def _pack(vector: list[float]) -> bytes:
    return struct.pack(f"<{len(vector)}f", *vector)


def _unpack(blob: bytes) -> list[float]:
    n = len(blob) // 4
    return list(struct.unpack(f"<{n}f", blob))


def cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _http_embed(provider: str, model: str, texts: list[str]) -> list[list[float]]:
    """Call the provider's embedding API for a batch of texts.

    Isolated for test monkeypatching. Raises EmbeddingError on failure.
    """
    import os

    import httpx

    try:
        if provider == "voyage":
            key = os.environ.get("VOYAGE_API_KEY")
            if not key:
                raise EmbeddingError("VOYAGE_API_KEY not set")
            resp = httpx.post(
                "https://api.voyageai.com/v1/embeddings",
                json={"input": texts, "model": model},
                headers={"Authorization": f"Bearer {key}"},
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()["data"]
            return [d["embedding"] for d in data]
        if provider == "openai":
            key = os.environ.get("OPENAI_API_KEY")
            if not key:
                raise EmbeddingError("OPENAI_API_KEY not set")
            resp = httpx.post(
                "https://api.openai.com/v1/embeddings",
                json={"input": texts, "model": model},
                headers={"Authorization": f"Bearer {key}"},
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()["data"]
            return [d["embedding"] for d in data]
    except EmbeddingError:
        raise
    except Exception as e:
        raise EmbeddingError(f"embedding request failed: {e}") from e
    raise EmbeddingError(f"unknown embeddings provider '{provider}'")


def _note_text(row, body_chars: int) -> str:
    parts = [row["title"] or ""]
    if row["summary"]:
        parts.append(row["summary"])
    body = row["body_plain"] or ""
    if body:
        parts.append(body[:body_chars])
    return "\n".join(parts)


def embed_sync(vault, batch_size: int = 32) -> dict:
    """Embed new/changed notes. Returns {embedded, skipped, provider, model}.

    A note needs (re)embedding when it has no vector or its content_hash
    changed since the vector was written (tracked via embeddings.created_at
    vs notes.synced_at is unreliable — we store the content_hash in the
    `model` field suffix instead: "<model>@<hash>").
    """
    cfg = vault.config.embeddings
    if cfg.provider == "none":
        raise EmbeddingError(
            "embeddings disabled: set [embeddings] provider = \"voyage\" or "
            "\"openai\" in .hyperresearch/config.toml"
        )
    model = cfg.model or DEFAULT_MODELS.get(cfg.provider, "")
    conn = vault.db

    rows = conn.execute(
        """SELECT n.id, n.title, n.summary, n.content_hash, nc.body_plain,
                  e.model AS embedded_model
           FROM notes n
           JOIN note_content nc ON nc.note_id = n.id
           LEFT JOIN embeddings e ON e.note_id = n.id
           WHERE n.type NOT IN ('index')"""
    ).fetchall()

    todo = []
    for row in rows:
        stamp = f"{model}@{row['content_hash']}"
        if row["embedded_model"] != stamp:
            todo.append((row, stamp))

    embedded = 0
    now = datetime.now(UTC).isoformat()
    for i in range(0, len(todo), batch_size):
        batch = todo[i : i + batch_size]
        texts = [_note_text(row, cfg.body_chars) for row, _ in batch]
        vectors = _http_embed(cfg.provider, model, texts)
        if len(vectors) != len(batch):
            raise EmbeddingError("provider returned wrong number of vectors")
        for (row, stamp), vec in zip(batch, vectors, strict=True):
            conn.execute(
                """INSERT OR REPLACE INTO embeddings
                   (note_id, model, dimensions, vector, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (row["id"], stamp, len(vec), _pack(vec), now),
            )
            embedded += 1
        conn.commit()

    return {
        "embedded": embedded,
        "skipped": len(rows) - len(todo),
        "provider": cfg.provider,
        "model": model,
    }


def semantic_search(vault, query: str, limit: int = 20) -> list[dict]:
    """Brute-force cosine search. Returns [{id, score}] best-first."""
    cfg = vault.config.embeddings
    if cfg.provider == "none":
        raise EmbeddingError(
            "embeddings disabled: set [embeddings] provider in config.toml"
        )
    model = cfg.model or DEFAULT_MODELS.get(cfg.provider, "")
    [query_vec] = _http_embed(cfg.provider, model, [query])

    conn = vault.db
    results = []
    for row in conn.execute("SELECT note_id, vector FROM embeddings").fetchall():
        score = cosine(query_vec, _unpack(row["vector"]))
        results.append({"id": row["note_id"], "score": score})
    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:limit]


def reciprocal_rank_fusion(
    ranked_lists: list[list[str]],
    k: int = 60,
) -> list[tuple[str, float]]:
    """RRF-combine multiple ranked id lists (hybrid FTS + semantic search)."""
    scores: dict[str, float] = {}
    for lst in ranked_lists:
        for rank, note_id in enumerate(lst):
            scores[note_id] = scores.get(note_id, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
