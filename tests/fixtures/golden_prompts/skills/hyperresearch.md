---
name: hyperresearch
description: >
  Deep research via the HYPERRESEARCH V8 architecture — a tier-adaptive 16-step
  pipeline (light / full / dissertation) that scales from a ~30-minute light-tier
  answer to an adversarially-audited report at the installed scale gear
  (~1.5–2.5 hours). This entry skill is a ROUTER.
  It does not contain step procedures — it tells you which Skill to invoke
  for each step, in order. Each step's instructions live in its own skill
  file (`hyperresearch-1-decompose` through `hyperresearch-16-readability-audit`)
  and are loaded fresh into context when you invoke them.
---

# Hyperresearch V8 — multi-skill chain orchestrator

You are the orchestrator. Your entire job in this conversation is:
1. Read this file once at the start.
2. Bootstrap canonical inputs (research_query, vault_tag, scaffold).
3. Invoke each step skill in sequence via the `Skill` tool.
4. Between steps, do nothing except mark todos and (optionally) think to `research/runs/<vault_tag>/temp/orchestrator-notes.md`.

You do NOT do the work of any step yourself. The step skills do. You just sequence them.

---

## How the chain works (READ THIS CAREFULLY)

Each pipeline step is its own skill file. To run a step:

```
Skill(skill: "hyperresearch-N-stepname")
```

When you invoke a Skill, that skill's full procedure is loaded into your context **fresh**. You then execute that step's procedure, hit its exit criterion, and return to the entry skill (this file) to invoke the next step.

**Why this design?** Context compaction. V7 was one 1200-line skill that got compacted away by the time Layer 4 needed its triple-draft procedure. The orchestrator forgot the procedure, wrote a single draft, and produced a flat-scoring report. V8 fixes this at the source: each step's procedure is loaded into context **only at the moment it's needed**, fresh, with no eviction risk.

**The 16 step skills** (all prefixed `hyperresearch-`):

| # | Skill name | What it does | Tiers |
|---|---|---|---|
| 1 | `hyperresearch-1-decompose` | Canonical query → scaffold + decomposition + coverage matrix + tier classification | all |
| 1.5 | `hyperresearch-1-5-chapter-partition` | Partition atomic items into 4–10 chapters; steps 2–10 then loop per chapter | dissertation |
| 2 | `hyperresearch-2-width-sweep` | Multi-perspective search plan + parallel fetcher waves | all |
| 3 | `hyperresearch-3-contradiction-graph` | Pair contradictions across the corpus into ranked fight clusters | full |
| 4 | `hyperresearch-4-loci-analysis` | 2 loci-analysts → scored loci.json with source budgets | full |
| 5 | `hyperresearch-5-depth-investigation` | K depth-investigators in parallel → interim notes with committed positions | full |
| 6 | `hyperresearch-6-cross-locus-reconcile` | Reconcile committed positions → comparisons.md | full |
| 7 | `hyperresearch-7-source-tensions` | Extract expert disagreements → source-tensions.json | full |
| 8 | `hyperresearch-8-corpus-critic` | "What source would overturn this?" + targeted gap-fill fetch | full |
| 9 | `hyperresearch-9-evidence-digest` | Top claims + verbatim quotes → evidence-digest.md | full |
| 10 | `hyperresearch-10-triple-draft` | Per-angle source curation + 3 parallel draft-orchestrators (3 angle-specific drafts) | all |
| 11 | `hyperresearch-11-synthesize` | Synthesis plan + outline + spawn synthesizer subagent (two-pass write) → final_report.md | full |
| 12 | `hyperresearch-12-critics` | 4 adversarial critics in parallel → findings JSONs | full |
| 13 | `hyperresearch-13-gap-fetch` | Fetch sources for critic-identified vault gaps | full |
| 14 | `hyperresearch-14-patcher` | Surgical Edit hunks applied to draft | full |
| 14.5 | `hyperresearch-14-5-cite-check` | Verify citation-sentence bindings; second small patcher pass | full |
| 15 | `hyperresearch-15-polish` | Hygiene + filler pass (Edit-based subagent) | all |
| 16 | `hyperresearch-16-readability-audit` | Readability recommender writes JSON suggestions; orchestrator selectively applies via Edit | all |

---

## Tier routing

Step 1 classifies the query into a `pipeline_tier` (`light` / `full`). The tier is written to `research/runs/<vault_tag>/prompt-decomposition.json`. After step 1, **read that file** to learn the tier, then sequence steps according to:

| Tier | Steps that run | Typical time |
|------|---|---|
| `light` | 1 → 2 → 10 (single draft) → 15 → 16 | ~30–40 min |
| `full` | 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11 → 12 → 13 → 14 → 14.5 → 15 → 16 | ~1.5–2.5 hours |
| `dissertation` | 1 → 1.5 (chapter partition) → [2 → … → 10 per chapter] → 6g/11 (global) → 12 → 13 → 14 → 14.5 → 15 → 16 | ~4–8 hours |

`dissertation` is opt-in only — the user must explicitly request it (or the run was initialized with `--profile dissertation`). Step 1 never auto-classifies into it. On dissertation runs, steps 2–10 loop per chapter (see `hyperresearch-1-5-chapter-partition`), with up to 2 chapters in flight; each chapter stays within the proven 40–80-source envelope while the run totals 300–450 sources.

**RESPECT THE TIER GATE.** When step 1 classifies a query as `light`, do NOT run the skipped steps "just to be thorough." The tier classification is a product decision: simple queries should produce fast, right-sized answers. Trust the classification. If you're uncertain, tier up — but never silently upgrade every query to `full`.

**Scale gear (tier ≠ gear).** The numbers rendered into the step skills — source targets, loci caps, depth budgets, word targets — come from the installed scale profile, the **gear** (currently `full`). The `full` tier row above already reflects it. Two gears ship: `full` (55–80 sources, ~1.5–2.5 hours) and `premier` (100–130 sources, double depth budget, ~3–5 hours). The user switches gears with `hyperresearch profile use <full|premier>` — that re-renders the installed skills, so it takes effect on the NEXT run, never mid-run. `light` and `dissertation` are tiers, not gears: light is auto-classified per query; dissertation is opt-in per run and loops each chapter inside the gear's envelope.

---

## Bootstrap (run BEFORE invoking step 1)

Before you invoke any step skill, do this:

0. **Auto-init if missing.** Two checks for the first-run-after-global-install case:
   - **Vault check.** If `.hyperresearch/` doesn't exist in the working directory, run `hyperresearch init . --json`. Creates the SQLite vault and `research/` directory.
   - **Step-skills check.** If `.claude/skills/hyperresearch-1-decompose/SKILL.md` doesn't exist relative to the working directory, run `hyperresearch install --steps-only . --json`. Installs the 16 step skill files needed by `Skill(skill: "hyperresearch-N-...")` calls in later steps.

   If either command fails because the binary isn't on PATH, tell the user to run `pip install hyperresearch` first. If both files already exist, both commands no-op cheaply — safe to run unconditionally.

0.5. **Archive any pre-3.0 flat artifacts.** Run `hyperresearch archive-run --json`. On vaults that ran pre-3.0 pipelines, flat artifacts (research/scaffold.md, loci.json, etc.) may still sit at the research root; this moves them into `research/runs/archive-<prev-tag>-<UTC-timestamp>/`. On 3.0+ vaults every run already owns `research/runs/<vault_tag>/`, so concurrent and sequential runs never collide and this command cheaply no-ops.

1. **Resolve the canonical research query.** Order of precedence:
   - If `research/prompt.txt` exists (legacy harness / wrapped run), read it. Its contents are the canonical research query. GOSPEL.
   - Otherwise, use the user's verbatim prompt as the canonical research query.
   - Extract wrapper requirements separately: required save path, citation format, terminal-section shape, wrapper contract. These are binding but NOT part of the query.
   - If `research/wrapper_contract.json` exists, read it.

2. **Mint a unique vault tag.** First produce a short topical slug from the canonical query — 3–5 lowercase hyphen-separated words, e.g. `efield-dft-sac`. Then call `hyperresearch vault-tag <slug> --json` and parse the `vault_tag` field from the response. The CLI appends a random 6-hex-char suffix that's verified unique against every prior run's workspaces, query files, and final reports in this vault. The result — e.g. `efield-dft-sac-a3f9b7` — is the canonical vault_tag for the rest of the pipeline.

2.5. **Initialize the run workspace.** Run:
   ```bash
   hyperresearch run init <vault_tag> --profile <full|light|premier|dissertation> --json
   ```
   For a standard run, pass the installed gear (`full`) unless the user asked for something else.
   Pass `--budget <usd>` when the user set a spend ceiling. This scaffolds `research/runs/<vault_tag>/` (with `temp/`) and writes `run.json` — the run manifest. **The manifest is your durable memory**: record every step transition with `hyperresearch run step <vault_tag> <N> --status running|done -j` as you go. The profile here defaults to matching the tier you expect; if step 1 classifies differently, the manifest's profile field is informational — the decomposition's tier rules.

3. **Persist the query file.** Write the verbatim canonical query to `research/runs/<vault_tag>/query.md`:
   ```markdown
   ---
   vault_tag: <slug>
   created: <ISO-8601 timestamp>
   source: prompt.txt | user-prompt
   ---

   <verbatim query text, character-for-character>
   ```
   This file is the **canonical query reference for the entire pipeline**. Every step skill and every subagent reads it by path.

4. **Classify modality** (collect / synthesize / compare / forecast) — record in the scaffold. This is a label that calibrates step 10's drafting style:
   - **collect**: enumerative coverage, per-entity sections with named fields
   - **synthesize**: defended thesis with evidence chains
   - **compare**: proportionate per-entity depth + a committed recommendation
   - **forecast**: predictive claims grounded in past + present, explicit time horizon

5. **Write the scaffold.** Write `research/runs/<vault_tag>/scaffold.md` (your private planning document — it MUST NOT appear anywhere in the final report). Include in scaffold:
   - User Prompt (VERBATIM — gospel)
   - Run config (vault_tag, query_file_path, modality, wrapper requirements)
   - Modality classification rationale
   - Tier rationale (filled in after step 1)
   - Wrapper requirements (save path, citation format, terminal sections)

6. **Seed the TodoWrite list.** Create todos for all 16 step skill invocations using the integer step numbers, e.g.:
   - `Step 1 — Skill: hyperresearch-1-decompose`
   - `Step 2 — Skill: hyperresearch-2-width-sweep`
   - ... (through Step 16)

   The todo list survives context compaction; it's your durable memory of where you are in the chain.

7. **Invoke step 1:** `Skill(skill: "hyperresearch-1-decompose")`.

After step 1 returns, read `research/runs/<vault_tag>/prompt-decomposition.json` to learn the tier, then continue invoking step skills per the tier routing table above. After each step's exit criterion is met, mark its todo complete and move to the next.

---

## Four canonical rules (ALWAYS in force)

1. **NEVER EMIT BARE TEXT WHILE TASKS ARE RUNNING.** In non-interactive (`-p`) mode, a text-only response (no tool call) triggers `end_turn` — the process exits and the pipeline dies. Every response while subagent tasks are in flight MUST include a tool call. The best one is appending analytical thoughts to `research/runs/<vault_tag>/temp/orchestrator-notes.md`. Vault count checks at most once per minute.

2. **PATCH, NEVER REGENERATE.** After step 11 produces the synthesized final report (or step 10 for light tier), the only modifications are surgical Edit hunks from step 14 (patcher) and step 15 (polish-auditor). Both subagents are tool-locked to `[Read, Edit]`. If a critic's finding would require rewriting a whole section, it escalates to you as a structural issue — not a rewrite. Keep hunks surgical.

3. **ARGUE, DON'T JUST REPORT** (full force for `argumentative` response_format; relaxed for `structured` and `short`). The pipeline is engineered to push the final report toward argumentative density. Loci must include at least one dialectical locus. Depth investigators must commit to a position. Step 6 forces cross-locus reconciliation. Step 11's synthesizer requires every body section that touches a tension to engage it explicitly.

4. **RESPECT THE TIER GATE.** See tier routing table. Don't add steps "for thoroughness." Don't drop steps "for budget." The tier is a binding contract.

---

## Browser-lane escalations (all tiers)

Blocked fetches (login walls, bot walls, captchas) are queued, not lost: `$HPR escalation list --status queued --tag <vault_tag> -j`. Step 2.8 drains the queue via ONE `hyperresearch-browser-fetcher` subagent driving the user's real Chrome browser. Two standing rules:

1. **CAPTCHAs / logins / 2FA are ALWAYS the human's.** The browser-fetcher marks them `needs_human`; you consolidate ALL of them into ONE message to the user at a natural pause point (never one interruption per URL). In non-interactive runs, `$HPR run block <vault_tag> --on human-challenges` and continue with everything else.
2. **One browser-fetcher at a time.** It's the user's actual browser — parallel instances are chaos. Check the queue again after step 13 (gap-fetch) if new fetches got blocked.

## Subagent spawn contract (applies to every Task call)

When a step skill instructs you to spawn a subagent, the prompt you pass MUST include three pieces near the top:

1. **`research_query` — verbatim, block-quoted** from `research/runs/<vault_tag>/query.md`. Do not paraphrase, do not summarize.

2. **Pipeline position statement.** One sentence naming what step the subagent runs in, what came before, what comes after. Example: *"You are step 5 (depth investigator) of the hyperresearch V8 pipeline. Step 4's loci analysts produced `research/runs/<vault_tag>/loci.json`; after you return, step 6 will reconcile your committed position against the other investigators'."*

3. **The subagent's specific inputs** (vault_tag, output_path, locus, etc.). Each step skill's spawn template documents the required fields.

Skipping any of these in a Task prompt is a process violation.

---

## Recovery: if you wake up uncertain where you are

Context compaction may eat parts of this conversation. If you're unsure what step you're on:

0. **Read the run manifest FIRST.** `hyperresearch run resume <vault_tag> --json` (or with no tag for the newest run) returns the exact next step and the Skill invocation to continue with. This is the primary recovery path — the manifest records every step transition you logged via `hyperresearch run step`. The artifact scan below is the fallback for manifests that are missing or were not kept up to date.
1. **Check the TodoWrite list.** It carries integer step numbers and survives compaction.
2. **Check disk artifacts (fallback).** Each step writes a canonical artifact:
   - Step 1: `research/runs/<vault_tag>/scaffold.md`, `research/runs/<vault_tag>/prompt-decomposition.json`, `research/runs/<vault_tag>/temp/coverage-matrix.md`
   - Step 2: vault notes tagged with vault_tag (`$HPR note list --tag <vault_tag> --all -j`)
   - Step 3: `research/runs/<vault_tag>/temp/contradiction-graph.json`, `research/runs/<vault_tag>/temp/consensus-claims.json`
   - Step 4: `research/runs/<vault_tag>/loci.json`
   - Step 5: vault notes with `type: interim` (`$HPR note list --tag <vault_tag> --type interim --all -j`)
   - Step 6: `research/runs/<vault_tag>/comparisons.md`
   - Step 7: `research/runs/<vault_tag>/temp/source-tensions.json`
   - Step 8: `research/runs/<vault_tag>/corpus-critic-gaps.json`, `research/runs/<vault_tag>/temp/corpus-critic-results.md`
   - Step 9: `research/runs/<vault_tag>/temp/evidence-digest.md`
   - Step 10: `research/runs/<vault_tag>/temp/draft-{a,b,c}.md` (or `research/notes/final_report_<vault_tag>.md` for light tier single-pass)
   - Step 11: `research/runs/<vault_tag>/temp/synthesis-plan.md`, `research/runs/<vault_tag>/temp/synthesis-outline.md`, `research/runs/<vault_tag>/temp/synthesis-pass1.md`, `research/notes/final_report_<vault_tag>.md`
   - Step 12: `research/runs/<vault_tag>/critic-findings-{dialectic,depth,width,instruction}.json`
   - Step 13: `research/runs/<vault_tag>/temp/post-critic-fetch-log.md`
   - Step 14: `research/runs/<vault_tag>/patch-log.json` (and edited final_report.md)
   - Step 15: `research/runs/<vault_tag>/polish-log.json` (and edited final_report.md)
   - Step 16: `research/runs/<vault_tag>/readability-recommendations.json`, `research/runs/<vault_tag>/readability-decisions.json` (and edited final_report.md)
3. **Find the highest-numbered step whose artifact exists.** Resume from the next step.
4. **Re-invoke this entry skill** if you've lost track entirely: `Skill(skill: "hyperresearch")`. It loads fresh.

If you're ever uncertain what to do next, the answer is: re-read this file and find the next step in the tier sequence.

---

## Final integrity gate (after step 16)

Once step 16 returns, run the integrity check:

```bash
for f in research/runs/<vault_tag>/critic-findings-dialectic.json \
         research/runs/<vault_tag>/critic-findings-depth.json \
         research/runs/<vault_tag>/critic-findings-width.json \
         research/runs/<vault_tag>/critic-findings-instruction.json \
         research/runs/<vault_tag>/patch-log.json \
         research/runs/<vault_tag>/polish-log.json; do
  test -f "$f" || echo "MISSING: $f"
done
```

(Light tier skips critics + patcher entirely — the critic-findings and patch-log files won't exist. That's expected; only `polish-log.json` is required for light.)

Then run the verification battery + lint:
```bash
$HPR run verify <vault_tag> --json          # structural: headings, length, citation density, artifacts, cite-check resolution
$HPR sources retractions --tag <vault_tag> --json   # ship-time retraction re-check (bypasses cache)
$HPR lint --rule wrapper-report --json
$HPR lint --rule locus-coverage --json
$HPR lint --rule scaffold-prompt --json
$HPR lint --rule patch-surgery --json
$HPR lint --rule quote-integrity --json     # every quoted span must exist verbatim in a vault note
$HPR lint --rule retracted-citations --json # retracted sources cited unmarked block the ship
$HPR lint --rule numeric-consistency --json # warnings: numbers untraceable to evidence — verify or remove
```

If `run verify` fails or any rule returns `error` severity issues, address them before declaring complete. Then ship: the final report lives at `research/notes/final_report_<vault_tag>.md`.

---

## Invariants you cannot break

1. **PATCHING not REGENERATION after step 11.** Once step 11 produces the final report (or step 10 for light tier), modifications are surgical Edit hunks only.
2. **One final report.** Step 11's synthesizer writes the final report ONCE. No re-synthesizing. (Light tier: step 10 writes it once.)
3. **At least one dialectical locus.** Step 4 must surface ≥1 dialectical locus unless skip is justified.
4. **Every interim note commits to a position.** Step 5 investigators end with `## Committed position`.
5. **`research/runs/<vault_tag>/comparisons.md` exists when loci count ≥ 1.** Step 6 is mandatory whenever step 4 produced any loci.
6. **Steps are sequential at the outermost level, parallel within.** You cannot start step N+1 before step N completes. Within a step, parallelism is mandatory when there are multiple subagents.
7. **Canonical research query is gospel everywhere.** Every subagent gets the verbatim query.
8. **Hygiene rules apply to the final report only.** Workspace artifacts (scaffold, loci JSONs, interim notes, comparisons.md, patch log) can look however they need to look.
9. **NEVER skip a step that the tier gate says to run.** For `full` tier, ALL 16 steps run. For `light`, the prescribed 5 steps run.
10. **Step 10 triple-draft ensemble is MANDATORY for `full` tier.** You MUST spawn 3 `hyperresearch-draft-orchestrator` subagents. Writing `research/notes/final_report_<vault_tag>.md` directly in step 10 (instead of going through the synthesizer in step 11) is a PIPELINE VIOLATION for these tiers.
11. **Step 11 synthesis is MANDATORY for `full` tier.** The synthesizer subagent (Read+Write tool-locked) writes the final report from the 3 drafts. The orchestrator does NOT write the final report itself for these tiers.
12. **Subagents read full source text.** Draft sub-orchestrators MUST batch-read every note in their `must_read_note_ids` list before writing. Fetchers MUST chase 3-8 primary sources via citation chains.
13. **NEVER emit a bare text response while subagent tasks are in flight.**

---

## Why V8

V7 was one 1200-line skill loaded once. By Layer 4 (line ~2200 in a 3000-line conversation), context compaction had evicted the procedure. The orchestrator silently dropped Layer 3.7 (corpus critic), rewrote its todo to replace the triple-draft ensemble with a single draft, and produced a flat-scoring report. This happened in 100% of runs where the orchestrator didn't re-read the skill file.

V8 makes re-reading structural. Each step skill is loaded fresh via the `Skill` tool at the moment it's needed. The procedure is in context exactly when it matters. Compaction can evict an old step's procedure — that's fine, the orchestrator never needs it again because each step is self-contained and reads its inputs from disk.

The trade: 16 skill files instead of 1, plus 16 invocations of the `Skill` tool over the run. The cost is negligible; the reliability gain is the difference between Q57 (55.9, full pipeline) and Q9 (52.6, single-draft fallback).

---

## Now begin

If you've read this far and the bootstrap (above) is done, invoke step 1:

```
Skill(skill: "hyperresearch-1-decompose")
```

If the bootstrap is NOT done, do the bootstrap first, then invoke step 1.
