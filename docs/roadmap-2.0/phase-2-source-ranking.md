# Phase 2 — The source-ranking engine

## Goal

Make source quality a **persistent, queryable property** instead of ephemeral prompt prose. After Phase 2, every source note carries a composite quality score built from fetch-time utility, citation-graph authority, vault centrality, and independence; retrieval is tier- and score-weighted; extracted claims live in the database keyed to their sources; and semantic search works over the vault. This is the prerequisite for both dissertation-scale curation (Phase 3) and mechanical verification (Phase 5).

## Non-goals

No changes to how many sources are fetched (Phase 3), no citation-*checking* (Phase 5). The LLM still makes final curation judgments — Phase 2 gives it a ranked shortlist instead of a flat pile.

## Current state (audit anchors, v0.8.7)

- **No numeric source ranking exists in the Python layer.** The `sources` table (`core/db.py:101-110`) has columns `url, note_id, domain, fetched_at, provider, content_hash, status` — a dedup ledger only.
- The step-2 utility score (6 dims × 0–3) is written to `research/temp/scored-urls.md`, used once for fetch selection, then **discarded** — it never travels with the note.
- `tier` / `content_type` exist on notes (`models/note.py:30-39`, CHECK-constrained in `db.py:27-30`) but are set by agent frontmatter whim and **never enter search scoring**: `search/fts.py:143-144` selects them and ignores them; ranking is BM25 + status multipliers only (`fts.py:154-164`).
- The `embeddings` table (`core/db.py:88-94`) is schema-defined and completely dormant — no writer, no reader.
- Claims are extracted per-fetch into `research/temp/claims-<note-id>.json` (fetcher agent contract) and consumed by steps 3/9 as files; they are never persisted queryably.
- Citation numbering in reports is order-of-first-appearance (draft-orchestrator/synthesizer prompts) — quality-blind.
- Provenance graph (links + `--suggested-by` breadcrumbs) exists in the `links` table but nothing computes centrality on it.

## Workstreams

### WS1 — Source-score schema + utility persistence (M)

**Design.** New migration (SCHEMA_VERSION 9). Scores live on **notes** (the citable unit), with fetch metadata staying on `sources`.

```sql
ALTER TABLE notes ADD COLUMN doi TEXT;
ALTER TABLE notes ADD COLUMN utility_score REAL;        -- step-2 composite (0-18), persisted at fetch
ALTER TABLE notes ADD COLUMN authority_score REAL;      -- citation-graph derived (WS2), normalized 0-1
ALTER TABLE notes ADD COLUMN centrality_score REAL;     -- vault PageRank (WS3), normalized 0-1
ALTER TABLE notes ADD COLUMN independence REAL;         -- 1.0 default; discounted for derivative-of (WS see phase 5)
ALTER TABLE notes ADD COLUMN citation_count INTEGER;    -- external, from OpenAlex/S2
ALTER TABLE notes ADD COLUMN venue TEXT;
ALTER TABLE notes ADD COLUMN is_retracted INTEGER DEFAULT 0;
ALTER TABLE notes ADD COLUMN quality_score REAL;        -- computed composite, see WS4
```

Frontmatter mirrors (`NoteMeta` gains optional `doi`, `utility_score`, etc.) so markdown stays truth and `sync` round-trips them; DB-only derived values (`centrality_score`, `quality_score`) are cache-resident and recomputed, not stored in frontmatter.

**Utility persistence.** Step-2 skill change: when the orchestrator scores URLs, fetcher spawn prompts include the URL's utility score, and the fetcher writes it into the new note's frontmatter (`utility_score:`). `scored-urls.md` remains the working artifact; the score now survives it.

**DOI capture.** Fetcher extracts DOI/arXiv id when present (meta tags, arXiv URL patterns — `crawl4ai_provider.py:44-50` already recognizes arXiv URLs); `hpr sources backfill-doi` regexes existing notes' source URLs/bodies for the 804-note back-catalog.

### WS2 — External citation metadata: `hpr sources score` (M)

**Design.** Batch CLI command that enriches DOI/arXiv-bearing notes from free scholarly APIs (httpx already a dependency; the CLAUDE.md academic-API endpoints are the same services, now called from Python instead of prose):

- **OpenAlex** (`api.openalex.org/works/doi:<doi>`, batch via filter, `mailto` param): `cited_by_count`, venue, retraction flag, referenced_works for chaining.
- **Semantic Scholar Graph** (`/graph/v1/paper/DOI:<doi>?fields=citationCount,venue,externalIds`): fallback + arXiv coverage.
- **Crossref** (`api.crossref.org/works/<doi>`): `update-to` relations surface retractions/corrections (Retraction Watch data flows through Crossref since 2023).

**Mechanics.** Rate limits: OpenAlex ~10 rps polite pool, S2 ~1 rps unauthenticated — batch endpoints where available, sequential with backoff otherwise. Cache responses in a new `api_cache` table (url, fetched_at, body) with a 30-day TTL so re-scoring is cheap. `authority_score` = log-scaled `citation_count` normalized within the vault (rank percentile), so a 50-citation niche paper isn't crushed by a 10k-citation classic in another field. Non-academic sources (no DOI) keep `authority_score = NULL` — the composite (WS4) falls back to tier weighting for them.

**Pipeline hook.** Step 2 gains a post-wave sub-step: `hpr sources score --tag <vault_tag>` after each fetch wave (cheap; only new DOI-bearing notes hit APIs). Retraction hits (`is_retracted=1`) are surfaced immediately in the step-2 coverage check so a retracted source never anchors a locus.

### WS3 — Vault centrality: `hpr graph rank` (S)

**Design.** PageRank over the directed graph of `links` rows (wiki-links + suggested-by breadcrumbs, which already land in `links` because breadcrumbs are body wiki-links). Pure-Python power iteration — the vault is thousands of nodes, not millions; no new dependency. Damping 0.85, 50 iterations or 1e-6 convergence. Store to `notes.centrality_score` (normalized 0–1 by max). Expose as `hpr graph rank [-j]` and recompute automatically at the end of `sync` when links changed (cheap) or behind `--no-rank` for huge vaults.

**Interpretation note for the docs/prompts:** centrality in *this* graph means "many independent research chains converged on this source" — a strong load-bearing signal precisely because fetcher chasing is citation-driven.

### WS4 — Composite quality score + tier-weighted retrieval (M)

**Design.** `quality_score` computed at sync/score time:

```
quality = w_tier * tier_weight[tier]            # ground_truth 1.0 … commentary 0.4, unknown 0.6
        + w_util * (utility_score / 18)
        + w_auth * (authority_score or tier_fallback)
        + w_cent * centrality_score
        - retraction_penalty (hard: is_retracted → quality = 0.05)
```

Weights in config `[ranking]` (defaults: tier 0.35, utility 0.2, authority 0.25, centrality 0.2). All inputs nullable — missing components renormalize rather than zeroing.

**Retrieval integration.** `search/fts.py`: after BM25 + status multipliers (`fts.py:154-164`), multiply by `(0.5 + quality_score)` when `--ranked` is passed (new flag; default off to preserve existing behavior/tests, flipped on in pipeline prompts). New `hpr search --ranked --tag <vault_tag> --for-item "<atomic item>"` becomes the curation primitive.

**Pipeline integration (the payoff).** Step 10 curation changes from "orchestrator surveys the vault and hand-picks" to: `hpr note list --tag <vault_tag> --ranked -j` → top-K per atomic item by quality × relevance → orchestrator *refines* (angle differentiation, tension proponents) instead of *inventing*. Citation preference in drafts: when multiple sources support a claim, cite the highest-quality one — the ranked list makes this instruction executable rather than aspirational.

### WS5 — Claims table (M)

**Design.** Persist what fetchers already produce. New tables (same migration):

```sql
CREATE TABLE claims (
  id INTEGER PRIMARY KEY,
  note_id TEXT NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
  claim TEXT NOT NULL,
  quoted_support TEXT,
  numbers TEXT,               -- JSON array
  confidence TEXT,            -- high/medium/low
  evidence_type TEXT,         -- empirical/statistical/anecdotal/opinion
  stance_target TEXT,
  stance TEXT,
  vault_tag TEXT
);
CREATE VIRTUAL TABLE claims_fts USING fts5(claim, quoted_support, content='claims', content_rowid='id');
```

`hpr claims ingest research/temp/claims-*.json` (idempotent by note_id+claim hash) runs at the end of step 2 / step 13; `hpr claims list --note <id>`, `--search "<text>"`, `--tag <vault_tag>` query it. Steps 3 (contradiction graph) and 9 (evidence digest) can consume the DB instead of re-parsing JSON files — optional simplification, keep file compatibility for now.

**Why:** this is the substrate for Phase 5's cite-check (claim ↔ sentence verification) and numeric-consistency lint, and it makes "which source best supports X" a query.

### WS6 — Embeddings revival: semantic search (L)

**Design.** Populate the dormant `embeddings` table (`core/db.py:88-94`). Pluggable provider via config `[embeddings]`: `provider = "none" | "voyage" | "openai" | "local"` (voyage-3-lite-class API models are cheap and good; `local` via sentence-transformers stays an optional extra to avoid a heavy default dependency). Embed title + summary + first ~1500 body chars per note; store float32 BLOBs; brute-force cosine at query time (fine to ~50k notes; no vector-DB dependency).

**Surface.** `hpr embed sync` (embed new/changed notes), `hpr search --semantic "<q>"`, and hybrid `--ranked --semantic` (reciprocal-rank-fusion of FTS and cosine lists). Pipeline use: step-10 curation and step-13 gap-check ("does the vault already cover X?") — semantic match catches conceptually-relevant sources FTS keyword match misses, which matters at 300+ sources.

**Fallback.** Everything degrades gracefully with `provider = "none"` (the default): no API key required for core functionality.

## Dependencies

- Phase 0 (single fetch engine to hook utility/DOI persistence into; prompts as editable markdown).
- Phase 1 (skill/agent prompt changes ride the template system; `[ranking]`/`[embeddings]` config sections).

## Acceptance criteria

- [ ] Migration v9 applies cleanly to the live 804-note vault; `sync` round-trips new frontmatter fields.
- [ ] After a pipeline run: every fetched note has `utility_score`; DOI-bearing notes have `citation_count`/`authority_score`; `hpr graph rank` populates centrality; `quality_score` computed for all.
- [ ] `hpr sources score` respects rate limits, caches, and survives API outages (partial enrichment, no crash).
- [ ] A retracted DOI (test fixture) drives `quality_score` to floor and surfaces in step-2 coverage output.
- [ ] `hpr search --ranked` reorders results by quality (test: same BM25 score, different tiers → ground_truth first); default search unchanged.
- [ ] `hpr claims ingest/list/search` work; claims survive re-ingest idempotently.
- [ ] `hpr embed sync` + `--semantic` return sane neighbors on the live vault with an API provider configured; `provider="none"` leaves all other features working.
- [ ] Step-10 skill template consumes ranked curation; bench spot-run shows no RACE regression.

## Risks & mitigations

- **API coverage gaps** — much of a web corpus has no DOI. Mitigation: composite renormalizes over available components; tier weighting carries non-academic sources.
- **Score gaming the drafts** — over-weighting authority buries good practitioner sources. Mitigation: weights are config; the orchestrator refines rather than blindly takes top-K; bench comparison before/after.
- **Embedding cost/privacy** — vault bodies leave the machine with API providers. Mitigation: opt-in (`none` default), embed only title+summary+excerpt, document it.
- **Migration risk on live vaults** — additive ALTERs only; no table rebuilds; back up `.hyperresearch/hyperresearch.db` in the migration (the file is disposable cache anyway — worst case `sync` rebuilds).

## Effort

| WS | Size |
|---|---|
| WS1 schema + utility persistence | M |
| WS2 citation metadata CLI | M |
| WS3 vault PageRank | S |
| WS4 composite + retrieval | M |
| WS5 claims table | M |
| WS6 embeddings | L |
