# Phase 5 — Verification: the layer that makes it better than a human

## Goal

Verification density no human researcher sustains: every citation checked against its source, every quote mechanically verified verbatim, every number traced to extracted evidence, every cited DOI swept for retractions, consensus counted only across *independent* sources — plus telemetry that makes pipeline tuning data-driven and a bench gate that stops prompt regressions from shipping. This is where machine research stops being merely faster and becomes more trustworthy.

## Non-goals

Not a fact-checking oracle: verification confirms the report faithfully represents its sources, not that the sources are true (source *quality* is Phase 2's job; truth remains the reader's). No new sourcing (Phases 2–4).

## Current state (audit anchors, v0.8.7)

- **No post-hoc citation verification exists.** The critics audit coverage/argument/instructions; none checks whether citation `[14]` actually supports the sentence it's attached to. The FACT half of DeepResearch-Bench measures exactly this, externally — the pipeline never self-measures it.
- Quotes in reports are unverifiable mechanically today; `quoted_support` exists in claims JSONs (and, after Phase 2 WS5, in the `claims` table) but nothing cross-checks report text against it.
- Retraction status: not checked anywhere (Phase 2 WS2 adds `is_retracted` at fetch/score time; nothing re-checks at ship time or for older vault sources being reused).
- Independence: the step-2.6 redundancy audit tags `derivative-of` for >60% shared `quoted_support` — but consensus counting ("3+ independent sources agree", step 3) trusts the corpus is independent; syndicated/churnalism chains can inflate agreement.
- Telemetry: none. No per-step cost/time record survives a run; profile tuning is vibes. `bench/` exists (DeepResearch-Bench harness, RACE/FACT via Gemini) but is manual and cluttered with ~20 `_*.py` scratch scripts (`bench/_analyze_drafts.py`, `_grade_q9_parallel.py`, etc.).
- Lint architecture is ready for new rules: `RULES` dict registry (`cli/lint.py:16`), severity model, `--rule` selection, JSON output — new verifications slot in as rules.

## Workstreams

### WS1 — Cite-check: new step 14.5 (L)

**Design.** After patching (step 14), before polish (15): verify that each citation supports its sentence. Runs for full + dissertation profiles.

**Mechanics.**
1. **Extract pairs (Python):** `hpr citecheck extract <report> -j` parses the report into (sentence, citation-target) pairs for both citation styles — `[N]`→Sources-list entry→note id, and `[[note-id]]` wikilinks. Pure parsing, reuses `core/patterns.py` wiki-link regexes.
2. **Triage (Python):** for each pair, look up the cited note's claims (Phase 2 claims table). Auto-pass tier: the sentence's numbers/entities appear in a claim's `quoted_support` or `numbers` (string/number match) → verified-mechanical. Remainder goes to the LLM tier.
3. **LLM tier:** a new `hyperresearch-cite-checker` subagent (sonnet; Read + Bash for `note show`) receives batches of (sentence, note-id, note-body-excerpt) and returns per-pair verdicts: `supported | partially-supported | unsupported | wrong-source` (with the note id that *does* support it when findable via claims search). Sampling for scale: 100% of number-bearing and strong-claim sentences; profile-configurable sample rate (default 60%) for the rest; dissertation profile checks 100% of chapter-topic sentences.
4. **Findings:** `research/runs/<tag>/cite-check-findings.json` in critic-findings format → the **patcher runs a second, small pass** (reuse step-14 machinery verbatim: same agent, same tool lock, appended patch-log section) fixing `unsupported`/`wrong-source` items — swap citation, soften claim to what the source supports, or escalate.

**Why 14.5, not part of step 12:** critics read the pre-patch draft; cite-check must audit what will actually ship, after patch hunks moved text and citations.

### WS2 — Mechanical lints: quote-integrity + numeric-consistency (M)

New rules in the `RULES` registry, both pure Python, both run in the step-15 gate:

- **`quote-integrity`:** every quoted span in the final report (≥ N words, default 5, config) must appear verbatim (whitespace-normalized) in some vault note body — checked via SQL `LIKE`/FTS phrase query against `note_content.body_plain`, scoped to the run's tag first, whole vault second. Unmatched → `error` with the quote and nearest fuzzy match (difflib) so the fix is fast. Kills hallucinated quotes dead.
- **`numeric-consistency`:** every number in the report (excluding structural numbers — dates in headings, section numbers, table indices; maintain an exclusion regex) must appear in (a) a claims-table `numbers`/`quoted_support` entry, (b) a cited note's body, or (c) a computed-value allowlist the meta-analysis pass (Phase 3 WS5) emits for derived figures. Unmatched → `warning` (not error — legitimate arithmetic exists), listed with locations. Severity configurable; dissertation profile promotes to error.

Both rules respect run-dir resolution (Phase 3) and legacy layout.

### WS3 — Retraction sweep at ship time (S)

**Design.** `hpr sources retractions --tag <vault_tag> [-j]`: for every note *cited in the final report*, re-check `is_retracted` (Phase 2's cached Crossref/OpenAlex path; TTL-bypassing `--fresh` flag for the ship-time run). New lint rule **`retracted-citations`** (`error`): a cited retracted source blocks the integrity gate; the report must either drop it or cite it *as* retracted (an explicit `(retracted)` marker in the citation satisfies the rule — sometimes the retraction is the story). Step 15 skill adds the sweep before the gate. Also valuable for **vault reuse**: old sources fetched in prior runs get re-checked when newly cited.

### WS4 — Independence audit (M)

**Design.** Generalize `derivative-of` into a first-class independence model feeding consensus math:

- **Detection upgrades (Python assist + existing audit):** beyond >60% shared quotes — shared canonical URL after redirect resolution, near-duplicate bodies (reuse MinHash from `core/similarity.py` — it exists for dedup already), same wire-service/PR boilerplate signatures (dateline + "PRNewswire/Business Wire/AP" markers), and same-domain clustering. `hpr sources independence --tag <tag>` computes clusters and writes `independence` scores (Phase 2 column): 1.0 for cluster roots, discounted members share credit.
- **Consensus integration:** step 3's consensus rule ("3+ independent sources agree") and step 9's digest change from counting *sources* to counting *independence-weighted clusters* — the skill templates read cluster data via `hpr sources independence -j`. Five syndicated copies of one press release = one vote.
- **Report surface:** the synthesizer's confidence language keys off weighted counts; the polish auditor's job is unchanged.

### WS5 — Run telemetry + `hpr run report` (M)

**Design.** Extend the Phase-3 manifest into a queryable record:

- Per-step: wall-time, subagents spawned (type × count), sources fetched/escalated/abandoned, claims ingested, findings raised/applied/skipped, estimated cost (profile cost-model × spawn counts).
- `hpr run report <tag>` renders a post-run summary (markdown + `-j`); `hpr run report --all -j` aggregates across runs for tuning questions ("what does wave 2 actually yield?", "how often does gap-fetch fire?", "cite-check unsupported rate by profile").
- Storage: `run.json` for live state + an append-only `research/runs/<tag>/events.jsonl` for per-event granularity (step start/end, spawn, fetch outcome). Orchestrator writes events through `hpr run event` so the format stays uniform.
- This is the feedback loop for every profile number Phase 1 made tunable — replace inherited constants with observed yield curves.

### WS6 — Bench as CI regression gate (M)

**Design.**
- **Cleanup:** move `bench/_*.py` scratch scripts (~20 files: `_analyze_drafts.py`, `_audit_references*.py`, `_grade_q9_parallel.py`, `_predict_full100.py`, etc.) into `bench/archive/` or delete; keep `harness.py`, `setup.sh`, `evaluate.sh`, README as the supported surface.
- **Smoke tier:** `bench/harness.py --smoke` — 3 fixed queries (1 light, 1 full-EN, 1 full-ZH), assertions on *structural* outcomes that don't need Gemini: report exists, length in profile range, required headings present, citation density ≥ floor, integrity gate green, cite-check unsupported rate < threshold (WS1 gives us an internal quality metric — this is the point: CI can gate on self-measured citation faithfulness without external judges).
- **Trigger:** manual/nightly workflow (`workflow_dispatch` + schedule) — not per-PR (each run costs real money); PRs touching `src/hyperresearch/skills/` or `agents/` get a bot comment reminding that bench-smoke hasn't validated the change until the nightly passes. Full 100-query RACE/FACT runs stay manual for release candidates.
- **Regression memory:** smoke results append to `bench/results/history.jsonl`; the workflow diffs against the trailing median and fails on >X% structural-metric regression.

## Dependencies

- **Phase 2 (hard for WS1/WS3):** claims table powers triage; DOI metadata powers retractions.
- **Phase 3 (soft):** run dirs/manifest for findings paths and telemetry home; WS2 lints work without it via legacy layout.
- Phase 0/1 transitively (templates, config).

## Acceptance criteria

- [ ] Cite-check on a seeded report with 3 planted defects (unsupported claim, wrong-source citation, fabricated quote) flags all 3; patcher pass fixes or escalates them; a clean report passes with < 5% LLM-tier flags.
- [ ] `quote-integrity` catches a planted fabricated quote; passes on a legitimate report; runs in seconds on the live vault.
- [ ] `numeric-consistency` traces report numbers to claims/bodies; exclusion regex keeps false positives < ~10% on example-reports/.
- [ ] A cited retracted DOI (fixture) blocks the gate; `(retracted)`-marked citation passes.
- [ ] Independence: a fixture cluster of 4 syndicated copies + 1 original counts as ~1 consensus vote, not 5.
- [ ] `hpr run report` produces per-step cost/time/yield for a completed run; `--all` aggregates.
- [ ] Nightly bench-smoke workflow runs green on main and fails on a deliberately broken skill (test the gate itself once).
- [ ] `bench/` root contains only supported files.

## Risks & mitigations

- **Cite-check cost** — LLM-tier at dissertation scale is thousands of pairs. Mitigation: mechanical triage first (claims matching auto-passes the bulk), sampling tiers, sonnet not opus, batched pairs per spawn.
- **False-positive lints eroding trust** — a noisy numeric-consistency rule gets ignored. Mitigation: warning severity by default, exclusion regex tuned on `example-reports/`, promote to error only for dissertation profile after observed precision.
- **Second patcher pass destabilizing a polished draft** — 14.5 runs *before* 15 precisely so polish sees the final text; patch-surgery lint already guards unapplied criticals.
- **Bench flakiness in CI** — live-web runs are nondeterministic. Mitigation: structural assertions (not score thresholds), trailing-median comparison, nightly not per-PR.

## Effort

| WS | Size |
|---|---|
| WS1 cite-check | L |
| WS2 mechanical lints | M |
| WS3 retraction sweep | S |
| WS4 independence | M |
| WS5 telemetry | M |
| WS6 bench CI | M |
