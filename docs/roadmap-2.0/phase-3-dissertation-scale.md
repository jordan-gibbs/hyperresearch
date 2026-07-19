# Phase 3 — Dissertation scale: chaptered execution, run isolation, hundreds of sources

## Goal

One run produces a PhD-dissertation-scale report: 25K–80K words, 250–450 sources, chaptered structure, literature-review matrix — in a single multi-hour session that is resumable, budget-governed, and safe to run alongside other runs. The architectural move is **hierarchy**: the proven 40–80-source pipeline becomes the per-chapter unit, with global reconcile/synthesis/critic layers above it. No single agent ever holds the whole corpus.

## Non-goals

No changes to the per-chapter research mechanics (steps 2–10 run as-is within a chapter). No multi-machine distribution. Browser-lane sourcing is Phase 4; verification depth is Phase 5.

## Current state (audit anchors, v0.8.7)

- Run artifacts write to **flat paths**: `research/scaffold.md`, `research/loci.json`, `research/comparisons.md`, `research/temp/*`, `research/critic-findings-*.json`, `research/patch-log.json`. The 0.8.6 changelog explicitly flags that two overlapping runs race on these and defers per-run dirs as "a deeper refactor."
- Recovery is implicit: "find the highest-numbered step whose artifact exists" (router skill, Recovery section). No manifest, no spend tracking, no explicit resume command. `hpr archive-run` moves *prior* run artifacts aside; `hpr vault-tag` mints collision-safe tags.
- Scale ceilings (all profile parameters after Phase 1): source target 55–80 with a "beyond ~80 diminishing returns" rationale (width-sweep ~line 227); loci ≤ 6; depth budget 40; 3 drafts × ≤50 must-reads (a 300-source corpus would be mostly unread by any drafter); word ceiling 10K (`argumentative`); evidence digest ≤120 claims.
- Lint rules glob flat paths: `wrapper-report`, `patch-surgery`, `instruction-coverage` look for `research/…/final_report*.md` and flat artifact names (`cli/lint.py:516,1006,1103`).
- Pacing constants tuned for ~1-hour runs: ≤1 vault check/min, 30–60s note appends, 80% wave-done threshold.

## Workstreams

### WS1 — Per-run workspaces: `research/runs/<vault_tag>/` (M)

**Design.** All run-scoped artifacts move under a per-run directory; vault notes stay global (the vault is the shared, compounding asset — runs are ephemeral workspaces over it).

```
research/runs/<vault_tag>/
  run.json                    # manifest (WS2)
  query.md                    # replaces research/query-<tag>.md
  scaffold.md
  prompt-decomposition.json
  loci.json                   # per-chapter under chapters/ when chaptered
  comparisons.md
  corpus-critic-gaps.json
  critic-findings-*.json
  patch-log.json  polish-log.json  readability-*.json
  temp/                       # everything currently in research/temp/
  chapters/ch1/ … chapters/chN/   # WS3: per-chapter artifact sets
  escalation-queue.json       # Phase 4
```

**Changes.**
- `Vault` gains `runs_dir` / `run_dir(tag)` properties (`core/vault.py` alongside the existing dir properties); `hpr run init <tag>` scaffolds it.
- Skills/agents templates: every artifact path becomes `{{ run_dir }}/…` (Phase 1's template system makes this a variable substitution, not a 30-file hand edit).
- `compute_sync_plan` (`core/sync.py`) already skips `research/` root staging files; extend the skip to `research/runs/**` except any note-shaped files intentionally placed there (keep the existing frontmatter-probe logic — reuse `_has_frontmatter`).
- Final reports **stay** at `research/notes/final_report_<vault_tag>.md` — they are vault notes, the product.
- Lint rules that glob flat paths get run-aware resolution: `--run <tag>` flag, defaulting to the newest dir under `research/runs/`; keep legacy flat-path fallback for pre-2.0 vaults (the 0.8.5 precedent: rules already glob `final_report*.md` with back-compat).
- `hpr archive-run` becomes trivial (move one directory) but stays for pre-2.0 layouts.

**Resolves** the 0.8.6-flagged parallel-run race: two concurrent runs own disjoint trees. Vault-level contention (SQLite writes) is already serialized by WAL + `BEGIN IMMEDIATE`.

### WS2 — Run manifest + explicit resume (M)

**Design.** `run.json`, written by the orchestrator at each step boundary (schema versioned):

```json
{
  "vault_tag": "china-rail-x9f2a1", "profile": "dissertation",
  "started_at": "...", "updated_at": "...",
  "status": "running | paused | blocked | done | failed",
  "steps": { "1": {"status": "done", "finished_at": "..."},
              "2": {"status": "running", "chapter": 3} },
  "chapters": { "ch1": {"title": "...", "status": "done", "sources": 62},
                 "ch3": {"status": "width-sweep"} },
  "spend": { "estimated_usd": 41.2, "sources_fetched": 187, "notes_written": 214 },
  "blocked_on": null
}
```

**Surface.** `hpr run status [<tag>] [-j]` (human + agent readable), `hpr run resume <tag>` (prints the resume position + the exact Skill invocation to continue with — the orchestrator consumes this instead of the artifact-existence heuristic, which remains the fallback), `hpr run abort <tag>`. The router skill's Recovery section rewrites to: read `run.json` first; artifact scan only if the manifest is missing/corrupt.

**Spend tracking.** The orchestrator can't see true token costs; track proxies it *can* observe (sources fetched, subagents spawned by type × profile-configured cost estimates). Good enough for the budget governor; exact accounting is out of scope.

### WS3 — Chaptered execution (L — the core of this phase)

**Design.** New **step 1.5 (chapter partition)**, full/dissertation profiles only, triggered when decomposition's atomic-item count or the profile demands it (`chapters = "auto"` → 1 chapter below ~12 atomic items, else 4–10 grouped by topical cohesion; `chapters = N` to force).

Execution shape:

```
1 decompose → 1.5 partition
for each chapter (2–3 chapters concurrently, profile-capped):
    2 width sweep → 3 contradictions → 4 loci → 5 depth → 6 reconcile
    → 7 tensions → 8 corpus critic → 9 digest → 10 chapter draft (single draft per chapter)
global:
    6g cross-CHAPTER reconcile   (chapter positions → global tensions doc)
    11g global synthesis          (chapter drafts → integrated dissertation, chapter H1s preserved)
    12 critics (per-chapter instruction/width; global dialectic/depth)
    13 gap-fetch → 14 patcher → 15 polish → 16 readability   (whole document)
```

**Key decisions.**
- **Chapter tagging:** `<vault_tag>-ch<N>` alongside `<vault_tag>` on every note, so per-chapter queries (`--tag <tag>-ch3`) and whole-run queries both work. Cross-chapter source *reuse* is free — a source fetched for ch2 is findable by ch5's coverage check via the ranked vault search (Phase 2), so chapters don't re-fetch each other's sources (dedup is by URL in `sources` anyway).
- **Per-chapter drafting replaces the triple-draft ensemble at chapter level.** The triple-draft's purpose (angle diversity) is served globally: chapters *are* the decomposition, and global synthesis integrates across them. Profile flag `chapter_draft_count = 1` (dissertation) vs `draft_count = 3` (full, unchaptered) keeps the 1.x behavior intact for unchaptered runs.
- **Critics at two altitudes:** instruction-critic checks the global document against `required_section_headings` + chapter contract; dialectic/depth critics run per-chapter (bounded context) with findings merged; width-critic runs globally against the full corpus tag. Critic finding caps scale by chapter count (profile).
- **Synthesizer context limits:** the global synthesizer reads chapter drafts (each ≤ ~8K words) + global reconcile doc — bounded regardless of corpus size. For 80K-word outputs, synthesis proceeds chapter-by-chapter against the global outline (two-pass per chapter, one voice doc as the running style contract) — same Read+Write tool-lock, writing one file incrementally.
- **Concurrency:** chapters are independent through step 9; run 2–3 concurrently (profile `chapter_concurrency`), bounded by subagent-slot pressure. WS1's per-chapter dirs make this race-free; the orchestrator interleaves via its existing task-notification loop.

**New/changed skills:** `hyperresearch-1.5-chapter-partition` (new), chapter-loop control in the router, `6g`/`11g` global variants (new skills or profile-gated sections of 6/11). All numeric knobs (chapter count bounds, per-chapter source targets, concurrency) live in `[profile.dissertation]`.

### WS4 — Budget governor (S)

**Design.** `--budget <usd>` at invocation → `run.json.budget`. The orchestrator checks `hpr run status -j` at step boundaries; the router skill gains a "budget check" rule: remaining budget scales the *next* step's parameters (fewer wave-2 fetchers, lower depth budgets, fewer chapters) using profile-defined floors — never silently skipping tier-mandated steps, instead shrinking their fan-out and recording the decision in the manifest. Hard stop at 100%: pause with `status: blocked`, `blocked_on: "budget"`, surface to user.

### WS5 — Dissertation artifacts + profile (M)

- **`[profile.dissertation]`:** steps incl. 1.5; `source_min = 250`, `source_target = [300, 450]` (allocated per chapter: each chapter runs the proven 40–80 envelope); `loci_max = 20` total (≤4/chapter); `depth_budget_total = 160`; `claims_cap = [400, 600]` global (per-chapter digests + global index); `word_targets.dissertation = [25000, 80000]`; `chapter_concurrency = 2`; scaled critic caps; pacing constants (WS6).
- **New `response_format: dissertation`** in step-1 decompose: chaptered H1s, per-chapter exec summaries, global abstract + conclusion + full bibliography.
- **Literature-review matrix:** `hpr claims matrix --tag <vault_tag> [-o file.md]` — per-source rows (source, year, tier, method/evidence_type, key findings from claims, limitations from adversarial claims, quality_score) generated from the Phase-2 claims table; embedded as a dissertation appendix and used by chapter drafters. Pure Python + one small LLM-free aggregation; drafters add prose interpretation.
- **Numeric meta-analysis pass:** new step-9 sub-step (dissertation profile): group claims sharing a `stance_target`/quantity across ≥5 sources → comparison table with ranges/outliers flagged → shipped into evidence digest. Extraction is from claims' `numbers` fields (already captured); no new agent, orchestrator-level aggregation via `hpr claims list -j`.

### WS6 — Pacing for multi-hour runs (S)

Profile-parameterize the cadence constants (vault-check interval, note-append cadence, wave-done ratio, subagent failure-retry counts) — dissertation runs check less frequently and tolerate longer waves. Add heartbeat writes to `run.json.updated_at` so `hpr run status` can flag a stalled run (no update > N minutes → `possibly-stalled` warning).

## Dependencies

- **Phase 1 (hard):** every scale number here is a profile parameter; path rewiring rides templates.
- **Phase 2 (strong):** ranked curation + claims table power chapter curation, the lit-review matrix, and meta-analysis. A Phase-3-without-Phase-2 fallback (orchestrator-judgment curation per chapter) works but is explicitly degraded.
- Phase 0 transitively.

## Acceptance criteria

- [ ] Two concurrent runs with different tags share a vault with zero artifact collisions (integration test: parallel `run init` + artifact writes + lint).
- [ ] Kill a run mid-step-5; `hpr run resume` reports the correct position; the orchestrator continues without re-fetching completed chapters (manifest test + manual run).
- [ ] Lint suite passes with run-dir layout and still passes on a legacy flat-layout vault.
- [ ] A dissertation-profile run on a broad query produces: ≥250 sources across ≥4 chapters, chaptered ≥25K-word report, lit-review matrix appendix, all integrity gates green.
- [ ] Budget governor: a run with `--budget` under-shoots the cap and records scaling decisions in the manifest; hard-stop pauses cleanly.
- [ ] `full` (unchaptered) profile behavior is byte-compatible with 1.x pipeline semantics (golden bench query).

## Risks & mitigations

- **Coherence across chapters** — chaptered writing can read as an anthology. Mitigation: global reconcile (6g) + running voice doc in 11g + global critics; the synthesizer's existing "one prose voice, not section-grafted" contract applies per the whole document.
- **Cost blowout** — 300+ sources ≈ $200–500/run. Mitigation: budget governor is in this phase for that reason; dissertation profile is opt-in.
- **Orchestrator context over multi-hour runs** — even with fresh-loaded step skills, the conversation grows. Mitigation: the manifest makes recovery cheap and explicit; chapter loops re-invoke the router; consider a per-chapter sub-orchestrator agent if single-session limits bite (flagged, not committed).
- **Migration** — pre-2.0 vaults with flat artifacts. Mitigation: lint/back-compat fallbacks (WS1); `archive-run` still handles old layouts; no forced migration.

## Effort

| WS | Size |
|---|---|
| WS1 run workspaces | M |
| WS2 manifest + resume | M |
| WS3 chaptered execution | L |
| WS4 budget governor | S |
| WS5 dissertation artifacts | M |
| WS6 pacing | S |
