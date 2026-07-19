# Hyperresearch 2.0 Roadmap

This directory holds the engineering specs for the 2.0 program: six phases that take hyperresearch from a ~80-source, ~10K-word single-report harness to a dissertation-scale research system with persistent source ranking, mechanical verification, and a browser lane for hard-to-reach sources.

## The 2.0 thesis

1.x won on **process discipline**: the 16-step V8 chain, adversarial critics, tool-locked patching, and lint-enforced contracts. Two audits (2026-07-19) found that the remaining gap between 1.x and "better than a human researcher" is not orchestration — it's that:

1. **Quality judgment is ephemeral.** The 6-dimension utility score is used once to pick fetch targets, then discarded. Citations are numbered by first appearance. Nothing in the Python layer can answer "which sources are most load-bearing?" — the `sources` table is a dedup ledger with no score, tier, or rank column.
2. **Scale is prose-hardcoded.** Source gates (min 45 / target 55–80), loci cap (6), depth budget (40), draft count (3), must-read bounds (20–50), word ceiling (10K) all live as literals inside skill and agent prompt text. Scaling up currently means rewriting 17 skills and 14 agent prompts.

2.0 fixes both: quality judgment becomes **persistent and programmatic** (ranking, claims, verification), and scale becomes a **profile** instead of a rewrite.

## Phases

| Phase | Doc | One-liner |
|---|---|---|
| 0 | [phase-0-cleanup.md](phase-0-cleanup.md) | Clear the debt: prompts out of `hooks.py`, V7→V8 vocabulary, one fetch engine, dead code out |
| 1 | [phase-1-config-profiles.md](phase-1-config-profiles.md) | Every magic number becomes config; pipeline profiles + templated prompts |
| 2 | [phase-2-source-ranking.md](phase-2-source-ranking.md) | Persistent source scores, citation-graph metadata, tier-weighted retrieval, claims table |
| 3 | [phase-3-dissertation-scale.md](phase-3-dissertation-scale.md) | Per-run workspaces, run manifest/resume, chaptered execution, hundreds of sources |
| 4 | [phase-4-chrome-lane.md](phase-4-chrome-lane.md) | Claude-in-Chrome fetch lane: escalation queue, human-in-the-loop checkpoint, session handoff |
| 5 | [phase-5-verification.md](phase-5-verification.md) | Cite-check, quote-integrity, retraction sweep, independence audit, telemetry, bench CI |

## Dependency graph

```
Phase 0 (cleanup)
   │
Phase 1 (config + profiles)
   │
   ├──────────────┬──────────────┐
Phase 2        Phase 4        Phase 3*
(ranking)      (chrome lane)  (scale)
   │                             │
   └──────────────┬──────────────┘
              Phase 5
           (verification)
```

\* Phase 3 depends on Phase 1 (profiles) and benefits strongly from Phase 2 (programmatic curation at scale); it can start after Phase 1 with Phase-2 integration deferred. Phase 4 is independent after Phase 1 and can run in parallel with 2/3. Phase 5's cite-check and retraction workstreams require Phase 2's claims table and DOI metadata; its mechanical lints (quote-integrity, numeric-consistency) only require Phase 0.

## Status

- [ ] Phase 0 — cleanup (partially pulled forward: width-sweep consistency fix landed with Phase 1; prompt extraction from hooks.py, V7 vocabulary unification, fetch consolidation, and dead-code removal remain open)
- [x] Phase 1 — config + profiles (2026-07-19)
- [x] Phase 2 — source ranking (2026-07-19)
- [x] Phase 3 — dissertation scale (2026-07-19)
- [x] Phase 4 — chrome lane (2026-07-19; session handoff deliberately dropped — see phase doc/CHANGELOG)
- [x] Phase 5 — verification (2026-07-19; bench CI workflow replaced by shipped `hpr run verify` — bench/ is gitignored)

## What 1.x already has (do not rebuild)

Contributors should not re-implement any of the following — they exist and work:

- **Multi-lens sourcing**: 4 search lenses (breadth / academic citation-chain / adversarial ≥5 searches / period-pinned primary filings), academic-APIs-before-web, Wikipedia-as-source-hub-never-cited, mandatory fetcher citation-chasing (3–8 primaries per batch) with `--suggested-by` provenance chains.
- **Fetch-time quality gates**: pre-fetch 6-dim utility scoring, login-wall/junk/binary detection (`web/base.py`), redundancy audit tagging `derivative-of` sources.
- **Adversarial architecture**: pre-draft corpus critic, 4 parallel post-draft critics, tool-locked patcher/polish-auditor (`[Read, Edit]`), patch-never-regenerate invariant.
- **Process lint suite**: `scaffold-prompt`, `locus-coverage`, `patch-surgery`, `wrapper-report`, `audit-gate`, `instruction-coverage`, `citation-style-preservation`, `provenance` (`cli/lint.py`).
- **Provenance & archival**: rooted suggestion tree, `raw_file` PDF archival via pymupdf, `sources` URL ledger.
- **Compounding vault**: markdown-is-truth / SQLite-is-cache, FTS5 search with status-aware ranking, run-to-run safety (`archive-run`, collision-safe `vault-tag`).
- **Authenticated crawling v1**: crawl4ai browser profiles, patchright stealth, visible-browser fallback for session-killing domains.

## Conventions for these docs

Every phase doc follows the same structure: Goal & non-goals → Current state (with `file:line` audit anchors, verified 2026-07-19 against v0.8.7 / commit `1dcf415`) → Workstreams (design, file-level changes, schemas, migration notes) → Dependencies → Acceptance criteria → Risks & mitigations → Effort estimates (S = hours, M = a day or two, L = several days).

Line numbers drift; when executing a phase, re-verify anchors with grep before editing. The anchor's job is to make the target findable, not to be eternally exact.
