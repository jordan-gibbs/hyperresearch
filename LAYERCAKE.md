# Layercake Architecture — Implementation Plan

Branched from `feat/benchmark-real-gates`. Replaces the current parallel three-run ensemble (breadth/depth/dialectical → section-grafting merger) with a **sequential-with-parallelism pipeline** where width is discovered first, depth is discovered from the width sweep, the draft is written once, and critique is applied as **targeted patches** — never regeneration.

---

## Layercake pipeline (7 phases)

```
Layer 1 — WIDTH SWEEP (parallel)
  orchestrator → N × fetchers  (cover topic corners broadly)
                ↓
Layer 2 — LOCI ANALYSIS (concurrent with late L1)
  orchestrator → 1–3 × loci-analyst
                ↓ returns 1–8 "depth loci" prompts + rationale
Layer 3 — DEPTH INVESTIGATION (parallel, 1 per locus)
  orchestrator → K × depth-investigator  (each can spawn fetchers,
                  read vault, write interim artifacts, then collate)
                ↓
Layer 4 — DRAFT (orchestrator, single pass)
  orchestrator writes draft from width corpus + depth packets
                ↓
Layer 5 — ADVERSARIAL CRITIQUE (parallel, 3 framings)
  orchestrator → dialectic-critic + depth-critic + width-critic
                ↓ each returns findings list (not a rewrite)
Layer 6 — PATCH PASS (orchestrator, Edit-tool-only subagent)
  orchestrator → patcher  (applies critiques as Edit hunks; CANNOT regenerate)
                ↓
Layer 7 — POLISH AUDIT (orchestrator, Edit-tool-only subagent)
  orchestrator → polish-auditor  (readability, adherence, cut fat, dedupe)
                ↓
final_report.md
```

### Key departures from the current ensemble

| | Ensemble (current) | Layercake |
|---|---|---|
| Investigation shape | 3 parallel full sub-runs, each does its own discovery + draft | One pipeline; width first, depth is discovered from width |
| Who writes the draft | 3 sub-runs each write a draft; Opus merger fuses | Orchestrator writes once from collated depth packets |
| Sources of divergence | Prior framings (breadth/depth/dialectical) assigned upfront | Loci-analyst discovers rabbitholes from actual source set |
| Review | Per-sub-run auditor + post-merge auditor | 3-framing adversarial critics on the single draft |
| Critique handling | Rewriter pass recovers dropped evidence | Patcher applies critiques as Edit hunks — no rewrite |
| Cost profile | 3× full discovery + merger | 1× width + K× depth packets + 1 draft + 3 critiques + 2 patch passes |

---

## Architecture decisions

### 1. Layercake replaces ensemble on this branch. Single-pass `/research` stays.

Two skills supported: `/research` (single-pass) and `/research-layercake` (new default). The ensemble mode and its subagents (`hyperresearch-subrun`, `hyperresearch-merger`, `hyperresearch-rewriter`) are retired on this branch. The old skill file `SKILL-ensemble.md` becomes `SKILL-layercake.md` in spirit but is rewritten end-to-end.

Reasoning: the user said "slightly different architecture" and opened a new branch. The ensemble's three-parallel-drafts-then-fuse model is a *different* design from the width→depth→patch model — enough difference that maintaining both would be noise. If we want the old ensemble back later, it's on `feat/benchmark-real-gates` already.

### 2. Patching is enforced at the tool level, not prompt level.

The patcher subagent has **only Read and Edit** in its tool allowlist. It physically cannot Write. It cannot Bash-write. It cannot emit a full document because its output path to the draft is Edit's `old_string`/`new_string` pairs, which must match exactly and must be surgical. Same enforcement for the polish auditor.

Reasoning: "patch, not rewrite" has to be an invariant the agent cannot violate even if it would be "easier" to regenerate. Prompt-level enforcement fails under pressure — we've seen agents rewrite when instructed not to. Tool-level enforcement is the only reliable path.

### 3. Orchestrator is the only agent that spawns subagents.

Depth investigators can call fetcher subagents (they need that for their own source gathering), but they cannot spawn analysts, critics, patchers, or other depth investigators. This keeps the graph shallow and debuggable, and prevents runaway recursion.

### 4. Number of analysts and depth investigators is dynamic but bounded.

- **Loci analysts:** exactly 2 by default (range 1–3). Two analysts reduce single-point-of-failure in rabbithole identification without tripling cost. Runtime env var or skill argument can override.
- **Depth investigators:** spawned equal to count of loci identified, clamped to [1, 8]. Analysts return their loci list; orchestrator dedupes and clamps.

### 5. Adversarial critics are exactly 3, with fixed framings.

- **dialectic-critic** — find the counter-evidence the draft missed or glossed
- **depth-critic** — find places the draft skates over technical substance that deserves expansion
- **width-critic** — find topical corners the draft doesn't cover despite the width corpus supporting them

Fixed 3 (not variable) so the orchestrator always spawns the same roster. Easier to debug, bench, and reason about.

### 6. Shared vault. Interim artifacts persisted as tagged notes.

Depth investigators write their interim reports to the vault as notes with `type: interim` and `tag: locus-N`. The orchestrator reads them back during draft time. After the final report is shipped, interim notes stay in the vault — they're useful artifacts for future sessions. No ephemeral scratch dir.

### 7. Loci-analyst and depth-investigator are new agents. Reuse fetcher.

- **hyperresearch-fetcher** — reused as-is for width sweep and depth investigators' source gathering
- **hyperresearch-analyst** — retired; its extract-taking role is absorbed into the depth investigator
- **hyperresearch-subrun / hyperresearch-merger / hyperresearch-rewriter** — retired
- **hyperresearch-auditor** — retired as structured today; spirit lives on in the 3 critics and polish-auditor

### 8. Benchmark harness: replace `--ensemble` with `--layercake`.

`bench/harness.py` currently has `--ensemble/--no-ensemble` (default True). On this branch: `--layercake/--no-layercake` (default True). When layercake is off, runs single-pass `/research`. Runs directory: `bench/runs_layercake/`. Model suffix `-layercake`. Mirror in `bench/evaluate.py`.

### 9. CLAUDE.md leads with layercake.

`src/hyperresearch/core/agent_docs.py` updates the generated CLAUDE.md to describe layercake as the default mode, name the 7 phases, and keep single-pass `/research` as the fallback.

---

## Subagent roster (after the change)

| Agent | Model | Tools | Role | Status |
|---|---|---|---|---|
| hyperresearch-fetcher | Haiku | Bash, Read | URL → vault note | **Keep as-is** |
| hyperresearch-loci-analyst | Sonnet | Bash, Read, Write | Read width corpus → 1–8 depth loci | **New** |
| hyperresearch-depth-investigator | Sonnet | Bash, Read, Write, Task (fetcher only) | Investigate one locus: fetch new sources, read vault, write interim note, collate | **New** |
| hyperresearch-dialectic-critic | Opus | Bash, Read | Read draft → findings list of counter-evidence gaps | **New** |
| hyperresearch-depth-critic | Opus | Bash, Read | Read draft → findings list of shallow spots | **New** |
| hyperresearch-width-critic | Opus | Bash, Read | Read draft → findings list of topical coverage gaps vs vault | **New** |
| hyperresearch-patcher | Sonnet | Read, Edit | Apply critique findings as surgical Edit hunks; cannot Write | **New** |
| hyperresearch-polish-auditor | Sonnet | Read, Edit | Readability + adherence + redundancy cuts as Edit hunks | **New** |
| hyperresearch-analyst | — | — | — | **Retire** |
| hyperresearch-subrun | — | — | — | **Retire** |
| hyperresearch-merger | — | — | — | **Retire** |
| hyperresearch-rewriter | — | — | — | **Retire** |
| hyperresearch-auditor | — | — | — | **Retire** (spirit split across 3 critics + polish-auditor) |

---

## Skill file layout

```
src/hyperresearch/skills/
  research.md                        # single-pass entrypoint — unchanged
  hyperresearch/
    SKILL.md                         # dispatcher for single-pass (existing, untouched)
    SKILL-collect.md                 # modality files (existing, untouched)
    SKILL-synthesize.md
    SKILL-compare.md
    SKILL-forecast.md
    SKILL-layercake.md               # NEW — replaces SKILL-ensemble.md
  research-ensemble.md               # REPLACE — renames to research-layercake.md? Keep name?
```

**Decision on entry-point name:** keep the slash command `/research-ensemble` for now (less disruption to muscle memory and CLAUDE.md prose), but the skill file under the hood is `SKILL-layercake.md`. Future rename to `/research-layercake` is a one-line CLI change. OPEN — ask before merging.

---

## Per-phase prompt content sketches

### Layer 1 — Width sweep
Orchestrator runs academic API sweep + web search to build a URL queue (≥30 candidates), then spawns fetchers in parallel batches. Target: 30–80 sources covering topic corners. Same discovery doctrine as current single-pass SKILL.md Step 2 — academic APIs BEFORE web.

### Layer 2 — Loci analysis
Analyst reads the width corpus (titles, summaries, one-line observations) and returns:
```json
{
  "loci": [
    {
      "name": "short-slug",
      "one_line": "The question this locus answers",
      "rationale": "Why the width corpus hints at depth here",
      "target_sources": ["url-or-note-id", "..."],
      "suggested_searches": ["query-1", "query-2"]
    }
  ],
  "skip_loci": ["reasons some obvious-seeming loci were rejected"]
}
```
Two analysts run in parallel. Orchestrator dedupes their loci lists (same `name` or high overlap in `rationale`) and clamps to 8.

### Layer 3 — Depth investigation
Each depth investigator receives one locus prompt:
```
You are investigating locus: {name}
The question: {one_line}
Why it matters: {rationale}
Starting sources: {target_sources}
Suggested searches: {suggested_searches}

Use fetchers to gather more sources. Read the vault for what's already there.
Write ONE interim report note as `interim-{locus-name}.md` with type: interim.
That note must contain:
- 3–10 most relevant quoted passages (with citations)
- Your synthesis of what the evidence says on this locus
- Open questions the evidence doesn't resolve
Return ONLY the note id when done.
```

### Layer 4 — Draft
Orchestrator assembles draft from: width corpus (via vault search), interim notes for each locus (deep reading), and the modality rules (collect/synthesize/compare/forecast — inherited from SKILL.md).

### Layer 5 — Adversarial critique
Three critics, each reads the draft + vault index (for critiques-in-context) and returns:
```json
{
  "findings": [
    {
      "severity": "critical|major|minor",
      "anchor": "first 60-char of paragraph this attaches to",
      "issue": "One-sentence description of the problem",
      "evidence": "citation or vault note id that supports the critique",
      "suggested_patch": "Specific text edit the patcher should make — NOT a rewrite"
    }
  ]
}
```

### Layer 6 — Patch pass
Patcher subagent reads all three critics' findings, merges them, deduplicates, and applies each as an Edit hunk on `research/notes/final_report.md`. It cannot Write. Its only path to change the draft is Edit(old_string, new_string).

Enforcement: if the patcher tries to make a hunk whose `new_string` is >500 chars longer than `old_string`, halt with an error. That's the mechanical tripwire for "regeneration pretending to be a patch."

### Layer 7 — Polish audit
Polish auditor reads final draft and emits Edit hunks for:
- Sentences that repeat information from earlier sentences
- Transitional filler ("It is worth noting," "Notably," "Importantly")
- Paragraphs that fail the modality's adherence rule
- Any hygiene issue from current auditor's conformance mode (frontmatter leak, scaffold leak, etc.)

Same Edit-only tool lock. Same 500-char hunk tripwire.

---

## Critical files to modify / add

| File | Action | What changes |
|---|---|---|
| `src/hyperresearch/core/hooks.py` | **Major rewrite** | Delete `ANALYST_AGENT`, `AUDITOR_AGENT`, `SUBRUN_AGENT`, `MERGER_AGENT`, `REWRITER_AGENT` constants. Add 6 new agent prompt constants: `LOCI_ANALYST_AGENT`, `DEPTH_INVESTIGATOR_AGENT`, `DIALECTIC_CRITIC_AGENT`, `DEPTH_CRITIC_AGENT`, `WIDTH_CRITIC_AGENT`, `PATCHER_AGENT`, `POLISH_AUDITOR_AGENT`. Keep `FETCHER_AGENT` unchanged. Update `install_hooks()` to register the new roster. Keep `SCAFFOLD_ONLY_SECTION_HEADERS` and hygiene utilities — they still apply. |
| `src/hyperresearch/skills/research-ensemble.md` | **Rewrite** | Becomes the layercake orchestrator prompt. 7 phases documented. |
| `src/hyperresearch/skills/research.md` | Minor edit | Update the "Canonical research query" section if wrapper behavior changes. Otherwise untouched — single-pass protocol still applies when a depth investigator needs to write an interim report. |
| `src/hyperresearch/core/agent_docs.py` | Update CLAUDE.md template | Lead with layercake, name the 7 phases, retire ensemble prose. |
| `src/hyperresearch/cli/lint.py` | Update | Extract analyst-coverage linting is obsolete (no analyst agent). Replace with `locus-coverage` lint: every locus identified by an analyst must have an `interim-{name}.md` note. Keep scaffold-prompt, workflow, provenance, benchmark-report rules. |
| `src/hyperresearch/core/hooks.py` module constant `SCAFFOLD_ONLY_SECTION_HEADERS` | Keep | Still relevant for hygiene — scaffold-only sections must not leak. |
| `bench/harness.py` | Update | `--layercake/--no-layercake` replacing `--ensemble/--no-ensemble`. Runs dir `runs_layercake/`. Model suffix `-layercake`. |
| `bench/evaluate.py` | Update | Same: `--layercake` flag. |
| `README.md` | Rewrite the ensemble section | Describe layercake 7 phases. Retire ensemble language. |
| `tests/test_cli/test_lint.py` | Update | Drop analyst-coverage tests. Add locus-coverage tests. Update workflow tests for new artifact set (interim notes instead of extract notes). |
| `tests/test_core/test_hooks.py` | Update | New subagent file assertions (`.claude/agents/hyperresearch-loci-analyst.md`, etc.). |
| `CHANGELOG.md` | Add entry | v0.7.0 — layercake architecture. |

New files (none expected — all additions are new agent constants in `hooks.py` and a rewritten skill file; no new source files needed).

---

## Execution batches

**Batch 1 — Subagent roster (hooks.py)**
Delete old 5 agent constants. Add 7 new ones. Update `install_hooks()` to generate the right files. Write new agent prompts with emphatic patching invariant on patcher + polish-auditor.

**Batch 2 — Skill rewrite (SKILL-layercake.md)**
Write the 7-phase orchestrator protocol. Include the loci-analyst output schema, depth-investigator task template, critic output schema, patcher Edit-hunk contract. Include the 500-char hunk tripwire rule.

**Batch 3 — CLAUDE.md update (agent_docs.py)**
Update the generated CLAUDE.md to lead with layercake, describe the 7 phases in 1 paragraph each, keep the academic-API-sweep + vault-curation sections unchanged (those are cross-cutting).

**Batch 4 — Lint rule swap (cli/lint.py)**
Replace analyst-coverage with locus-coverage. Update benchmark-report gate if it referenced ensemble-specific artifacts.

**Batch 5 — Bench harness (harness.py, evaluate.py)**
Rename flag, runs dir, model suffix. Update summary output to reference "layercake" instead of "ensemble."

**Batch 6 — Tests (test_lint.py, test_hooks.py)**
Update test fixtures for new subagent files and new lint rules.

**Batch 7 — Docs (README.md, CHANGELOG.md)**
Rewrite the ensemble section. Add v0.7.0 changelog entry naming the architectural shift and the retired agents.

**Batch 8 — End-to-end bench run**
Pick 3 queries (one collect, one synthesize, one compare). Run `bench/harness.py --layercake --ids 56,63,90 --no-auto-eval` (small to contain cost). Inspect the generated `runs_layercake/query_*/research/notes/` for:
- width corpus present
- interim-{locus}.md notes present
- final_report.md present
- no regenerated hunks in patch pass (audit the git blame-equivalent by diffing draft vs patched)

---

## Verification at each batch

```bash
.venv/Scripts/python.exe -m ruff check src/ tests/
.venv/Scripts/python.exe -m pytest tests/ -q
.venv/Scripts/hyperresearch.exe install           # fresh install, confirm 8 agents + 2 skills
ls .claude/agents/                                  # should list fetcher, loci-analyst, depth-investigator, 3 critics, patcher, polish-auditor
ls .claude/skills/                                  # hyperresearch/ (single-pass) + research-layercake/ (new)
```

End-to-end dry run: invoke `/research-ensemble` (or renamed `/research-layercake`) on a small query, watch the phase transitions in the session log, confirm:
- fetchers fire in parallel in L1
- 2 loci-analysts fire in parallel in L2
- K depth-investigators fire in parallel in L3 (one per locus)
- 3 critics fire in parallel in L5
- patcher + polish-auditor each fire once, sequentially, in L6 + L7
- final `research/notes/final_report.md` exists and is coherent
- no ERROR-severity lint rules fire on the final vault

---

## Patching invariant — how it actually holds

The user was emphatic: **patching, not regeneration**. Five layers of enforcement:

1. **Tool allowlist (mechanical):** patcher and polish-auditor have `[Read, Edit]` only. No Write, no Bash, no NotebookEdit.
2. **Hunk-size tripwire (mechanical):** any Edit where `len(new_string) - len(old_string) > 500` is flagged in the run log and treated as a soft violation. Three violations in a row → halt the pipeline.
3. **Prompt invariant (behavioral):** the patcher prompt opens with "You cannot rewrite the document. You can only emit Edit hunks. Each hunk should change as little as possible while addressing the critique."
4. **Critic output schema (upstream):** critics return `suggested_patch` as a targeted text change, not a section rewrite. The patcher is incentivized to follow the critic's suggestion verbatim.
5. **Post-hoc lint rule:** a `patch-surgery` lint rule measures churn between the L4 draft and the final report. If >40% of the text changed, fail and ask for manual review.

If any single layer fails, the others catch it. This is the "defense in depth" logic — no single rule is load-bearing.

---

## Open questions (flag before merging)

1. **Slash command name.** Keep `/research-ensemble` for continuity? Or rename to `/research-layercake` to match the skill file? Recommend rename; it's one CLI line, and the architectural shift is large enough to warrant the new name.

2. **Retire analyst/auditor/merger/rewriter/subrun OR keep them as deprecated modules?** Recommend retire fully — this is a new branch, the old code is preserved on `feat/benchmark-real-gates`. No half-commitments.

3. **Interim-note lifecycle.** Interim notes live in the vault forever? Or do we tag them `status: interim` and archive them after 30 days? Recommend keep forever; they're cheap to store and often the most useful artifact of a session.

4. **Depth-investigator Task access.** The depth investigator needs to spawn fetchers, which requires the Task tool. But Task can spawn ANY subagent. Constrain via prompt ("you may only spawn hyperresearch-fetcher") or via a new tool variant? Recommend prompt-level for now — simpler, and if we see fetcher-only violations in practice we can tighten later.

5. **Loci count default.** 2 analysts × up to 8 loci each, deduped to ≤8 → up to 8 depth investigators. This can be expensive on complex queries. Recommend a hard cap of 6 at first, tunable via env var.

6. **Cross-locus conflict.** If two depth investigators independently fetch the same source, does the vault dedupe? Yes — the current `hyperresearch fetch` already handles this via URL tracking. No new work here.

7. **What if critics disagree?** dialectic says "add more counter-evidence," depth says "go deeper on X," width says "you missed topic Y." The patcher applies each as an independent hunk; hunks rarely intersect because they target different parts of the doc. If they do intersect, the Edit tool will fail on the second hunk (old_string no longer matches) — that's the signal to stop patching and flag for human review.

8. **Migration path.** No. No shim, no deprecation path. This is a new branch, the old behavior is preserved on the prior branch, and if we ship layercake to main it supersedes ensemble entirely. Anyone pinned to ensemble can pin a git SHA.

---

## Risks

1. **The patcher cheats anyway.** Most likely failure mode: patcher emits a single giant Edit that replaces the whole draft. The 500-char tripwire + churn lint rule + prompt invariant should prevent this, but it's the thing to watch in the end-to-end dry run. If we see it happening, the right fix is to split the patcher into a "planner" (produces a hunk list) + "applier" (runs Edit calls one at a time) — more mechanical separation.

2. **Loci analysis is low-signal.** If the width corpus is too shallow, analysts can't identify meaningful rabbitholes. We might see analysts returning "expand on the main topic" as a locus, which is useless. Mitigation: require `rationale` field to name specific evidence from the width corpus. Analysts that can't fill this get zero loci approved.

3. **Depth investigators over-fetch.** Each investigator can spawn fetchers, which can spawn more fetchers via transitive chains. The current vault has 91+ sources per query on the benchmark — if each investigator adds 15+ more, we hit token budget. Cap investigator fetches at 10 new sources per locus.

4. **Benchmark regression.** Layercake might score lower than ensemble on the first pass because the critics are new and may be miscalibrated. Expect 2–3 rounds of prompt tuning before layercake matches or beats ensemble. Plan for the 13-query bench run to land 1–3 points below ensemble on the first try; budget for iteration.

5. **Subagent proliferation.** 8 agents is a lot. If the user wants to add another layer later (synthesizer? fact-checker?), we're at 9+. Might consider collapsing the 3 critics into a single multi-framing critic that runs 3 times internally. Table for v2.

6. **Cost profile unclear.** Ensemble is ~3× the cost of single-pass. Layercake's cost is harder to predict because depth-investigator count is variable. First bench run will tell us — could be cheaper than ensemble (no 3× redundant discovery) or more expensive (more distinct subagent invocations). Budget for surprise.

---

## Out of scope

- **New benchmarks.** Layercake runs against the existing DeepResearch-Bench set. No new scoring logic, no new reference answers.
- **FACT evaluator changes.** Citation accuracy metric is orthogonal to architecture. Leave it alone.
- **Ensemble regression tests.** The old ensemble is on `feat/benchmark-real-gates`. If we need to A/B compare, run that branch separately; don't maintain both architectures on this branch.
- **Multi-turn conversations.** Layercake is still single-shot. Adding follow-up/refinement loops is a v2 topic.
- **Research-base curation prompts.** The curation step (tags, summaries, status promotion) is independent of architecture and stays the same.

---

## Total estimated work

~800–1200 LOC touched across 10 files. Two focused days to ship Batches 1–7. Day 3 is the bench dry run + one round of prompt tuning based on what we see.

Execution order is the batch order above. After each batch: ruff + pytest + `hyperresearch install` sanity, same rhythm as the prior rebrand plan.
