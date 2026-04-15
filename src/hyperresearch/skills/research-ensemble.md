---
name: research-ensemble
description: >
  Ensemble research mode. Trades ~5x cost for one unified report that
  integrates three parallel sub-runs on the SAME shared vault, each with
  a subtly different framing that drives natural divergence in what they
  fetch and emphasize. Opus orchestrates, spawns three Sonnet sub-runs
  (breadth / depth / dialectical), and then spawns an Opus merger that
  compiles the final report on comprehensiveness, readability, argument
  strength, and citation quality. Use when depth-of-corpus and
  argument-stability matter more than wall-clock time.
---

# Research Ensemble Protocol

> You are the ensemble orchestrator. Your job is to run the `/research`
> protocol THREE TIMES in parallel against the SAME shared vault, each
> with a subtly different framing, then spawn a merger subagent that
> unifies the three drafts into one final report. The user's verbatim
> prompt is GOSPEL — identical across all three sub-runs, never altered.
> The three "framings" are private lenses the sub-runs use to bias
> discovery and analysis; they never enter the scaffolds or the drafts.

**This is the ensemble skill. It's SEPARATE from `/research`.** The user
typed `/research-ensemble` specifically because they want the 3-way
compound reading. Do not convert to single-run; do not abort to
`/research` without orchestrator-level failure.

**Cost disclosure to the user — required, early.** Before you do real
work, tell the user: "Ensemble mode costs ~5x a normal `/research` run
(3 parallel sub-runs + merger + post-merger audit). Each sub-run
targets 25+ fetches; combined corpus aims for 50+ sources. Takes
longer and costs more, but produces a noticeably deeper report."

---

## Step 0: The same clarify-if-vague rule as `/research`

If the prompt is ambiguous enough that three sub-runs might diverge
on WHAT the user is asking (not just HOW), ask ONE clarifying
question before proceeding. Ambiguity in scope destroys the ensemble
— three sub-runs on three different interpretations of the prompt
cannot be merged. Ambiguity in approach is fine; the ensemble
exploits that.

If the prompt is already clear, skip this step and proceed.

---

## Step 1: Classify the prompt ONCE (not per-sub-run)

Read `.claude/skills/hyperresearch/SKILL.md` Step 1 — run the same
classification logic to pick a primary modality (`collect`,
`synthesize`, `compare`, `forecast`) and optional secondary flavor.

**Classification is done ONCE.** All three sub-runs use the SAME
modality and secondary flavor. If sub-runs reclassify individually,
they produce structurally-incomparable drafts and the merger has
nothing to splice.

Record the classification — you will pass it to every sub-run spawn.

---

## Step 2: Capture the verbatim prompt as gospel

Store the user's verbatim prompt (character-for-character, no edits)
in a TodoWrite entry or a scratch note. This is what you pass into
every sub-run's `research_query` parameter. The merger verifies all
three sub-run scaffolds contain this text IDENTICALLY; any drift
halts the merge.

Do not paraphrase. Do not "clean up" whitespace. Do not strip
punctuation. Copy exactly.

---

## Step 3: Auto-archive prior ensemble artifacts

Before spawning any sub-run, check whether the vault has leftover
per-run files from a previous ensemble attempt:

```bash
ls research/notes/final_report-run-*.md 2>/dev/null
ls research/notes/scaffold-run-*.md 2>/dev/null
ls research/notes/comparisons-run-*.md 2>/dev/null
ls research/audit_findings-run-*.json 2>/dev/null
ls research/notes/final_report.md 2>/dev/null
```

If ANY of these exist, auto-archive them to
`research/archive/ensemble-<ISO-timestamp>/` and log the path. Do NOT
halt and ask the user — ensemble retries after an interrupted run are
common enough that friction on this path is a real nuisance. The
archive preserves the prior artifacts if the user wants them; the
ensemble proceeds cleanly.

Implementation:

```bash
TIMESTAMP=$(date -u +%Y-%m-%dT%H%M%SZ)
ARCHIVE=research/archive/ensemble-$TIMESTAMP
mkdir -p $ARCHIVE
# Move every prior per-run artifact, plus the prior merged report.
mv research/notes/final_report-run-*.md $ARCHIVE/ 2>/dev/null
mv research/notes/scaffold-run-*.md $ARCHIVE/ 2>/dev/null
mv research/notes/comparisons-run-*.md $ARCHIVE/ 2>/dev/null
mv research/audit_findings-run-*.json $ARCHIVE/ 2>/dev/null
mv research/notes/final_report.md $ARCHIVE/ 2>/dev/null
# Sync to de-index the moved notes.
$HPR sync -j
```

Tell the user once: "Auto-archived prior ensemble artifacts to
`research/archive/ensemble-<timestamp>/`." Then proceed. Source notes
and extracts stay in `research/notes/` — they're part of the shared
vault's compounding corpus and continue to be useful for this run.

---

## Step 4: Build the orchestration TODO list

Use TodoWrite to lay out the full ensemble. Do NOT spawn anything
until this list exists:

1. Clarify prompt if vague (Step 0)
2. Classify prompt once (Step 1)
3. Capture verbatim prompt (Step 2)
4. Check / archive prior artifacts (Step 3)
5. Spawn `hyperresearch-subrun` x3 in parallel (Step 5 — one per framing)
6. Wait for all 3 returns; collect artifacts + audit statuses
7. **Pre-merger gate:** read each per-run audit_findings; halt on unresolved CRITICALs (Step 6)
8. Spawn `hyperresearch-merger` (Step 7)
9. Spawn `hyperresearch-auditor` on merged draft — comprehensiveness + conformance (Step 8)
10. Apply audit fixes, re-audit if needed (Step 9)
11. Save synthesis note (Step 10)
12. Report to user (Step 11)

Mark each item `completed` only after its artifact exists AND you've
verified it with a command. Mid-orchestration crashes are recoverable
if the TODO list accurately reflects where you stopped.

---

## Step 5: Spawn three `hyperresearch-subrun` agents IN PARALLEL

Each sub-run receives:
- The same verbatim `research_query` (gospel)
- A unique `run_id` — `run-a`, `run-b`, or `run-c`
- A unique `framing_nudge` — a 2-3 sentence private lens
- `minimum_fetch_target` = 25 (hard floor on this sub-run's fetches)
- The ONE classified `modality` and optional `secondary_modality`

**The three framings — copy these verbatim into spawn prompts:**

### run-a — evidentiary breadth

```
framing_nudge: Approach this with a bias toward evidentiary breadth.
Prioritize casting a wide net over going deep. Emphasize primary-
source hunting, ground-truth tier (official statistics, filings,
policy text, institutional datasets), non-English sources where
regionally relevant, and named dissenting voices. When spawning
analysts, phrase their goals to maximize BREADTH of what they look
for in each source. Target as many distinct sub-topics as the prompt
touches, not depth within any single one.
```

### run-b — citation-chain depth

```
framing_nudge: Approach this with a bias toward citation-chain depth.
When reading sources, prioritize tracing their references — follow
footnote chains, fetch the originating paper not the blog post about
it, pursue the cited dataset not the summary. When spawning analysts,
phrase their goals to extract NEXT-TARGET URLS above all — a source
that cites 10 other sources is more valuable to you than a source
that concludes. Prefer fewer high-density seeds with aggressive
rabbit-hole depth over a wide flat set of shallow reads.
```

### run-c — dialectical tension

```
framing_nudge: Approach this with a bias toward dialectical tension.
Prioritize finding where domain experts disagree, where the dominant
framing is challenged, where the strongest counter-argument lives.
When running adversarial searches, use named-skeptic queries over
generic criticism. When analysts extract, tell them to flag
commentary's strongest dissent. Your scaffold and draft will still
commit to a position like any `/research` run, but your source mix
will weight the contrarian side more heavily than a default reading
would.
```

### The spawn itself

Launch all three in a single message — three parallel `Task` calls
(this is where parallelism pays off; sequential spawns waste the
whole point):

```
Spawn hyperresearch-subrun with:
  research_query: <verbatim user prompt from Step 2>
  run_id: run-a
  framing_nudge: <the run-a text above, copied exactly>
  minimum_fetch_target: 25
  modality: <from Step 1>
  secondary_modality: <from Step 1, or "none">

Spawn hyperresearch-subrun with:
  research_query: <verbatim user prompt from Step 2>
  run_id: run-b
  framing_nudge: <the run-b text above>
  minimum_fetch_target: 25
  modality: <same>
  secondary_modality: <same>

Spawn hyperresearch-subrun with:
  research_query: <verbatim user prompt from Step 2>
  run_id: run-c
  framing_nudge: <the run-c text above>
  minimum_fetch_target: 25
  modality: <same>
  secondary_modality: <same>
```

Each sub-run is a full `/research` protocol pass — it will take real
time (typically 10-30 minutes each, depending on the prompt's depth).
Wait for all three to complete before proceeding. The sub-runs share
the vault; their fetches deduplicate naturally via
`INSERT OR IGNORE INTO sources`; their per-run filenames and tags
keep their scaffolds, drafts, and audit files distinct.

---

## Step 6: Pre-merger gate — verify all three sub-runs passed audit

Each sub-run returns a summary with `audit_status`. But trust-and-
verify: read each per-run audit file directly.

For each run_id in `[run-a, run-b, run-c]`:

```bash
PYTHONIOENCODING=utf-8 $HPR lint --rule audit-gate \
  --audit-file research/audit_findings-<run_id>.json -j
```

The `audit-gate` lint rule returns `pass` only when both
comprehensiveness AND conformance entries exist AND every CRITICAL
is resolved.

**If any sub-run's audit-gate fails:**

Do NOT spawn the merger. Surface to the user:

> "Sub-run `<run_id>` did not pass audit — its findings at
> `research/audit_findings-<run_id>.json` have unresolved CRITICAL
> issues. All three sub-run drafts exist at
> `research/notes/final_report-run-{a,b,c}.md` as independently
> readable artifacts. You can:
> 1. Review the unresolved findings, apply fixes to the sub-run's
>    draft manually (re-spawn `hyperresearch-auditor` with the
>    per-run audit path after fixes), and re-run this orchestrator.
> 2. Accept one of the passing sub-run drafts as the final report
>    by copying it to `research/notes/final_report.md`.
> 3. Start the ensemble over with a refined prompt."

Halt the ensemble. The merger does NOT get spawned with known-bad
sub-run inputs.

**If all three sub-runs pass:** proceed to Step 7.

---

## Step 7: Spawn `hyperresearch-merger` (ONCE)

```
Spawn hyperresearch-merger with:
  research_query: <verbatim user prompt from Step 2>
  run_ids: ["run-a", "run-b", "run-c"]
  sub_run_artifacts: {
    "run-a": {
      "scaffold_path": "research/notes/scaffold-run-a.md",
      "comparisons_path": "research/notes/comparisons-run-a.md",
      "final_report_path": "research/notes/final_report-run-a.md",
      "audit_findings_path": "research/audit_findings-run-a.json"
    },
    "run-b": { ... run-b paths ... },
    "run-c": { ... run-c paths ... }
  }
  parent_final_report_path: research/notes/final_report.md
  parent_audit_path: research/audit_findings.json
  modality: <from Step 1>
```

The merger reads all three drafts + audits + scaffolds, scores each
on four axes, picks a base, splices in unique material from the
other two, unions the Sources sections, proofreads, and writes the
unified draft. It ALSO appends a `mode: merger` run to the parent's
`audit_findings.json` with detailed scoring per sub-run.

Wait for the merger to return. The merger's return shape:

- `status`: pass / needs_fixes / failed
- `merged_report_path`: `research/notes/final_report.md`
- `base_run`: which sub-run anchored the merge
- `splice_mode`: full / short_circuited
- `splices_applied`: integer
- `sources_unified`: integer
- `combined_source_target_met`: bool
- Any critical issues the orchestrator should surface

### Merger failure fallback

If `status` is `failed`, the merger writes a `mode: merger-failed`
entry to the parent's audit_findings.json and does NOT produce
`research/notes/final_report.md`. Surface this to the user:

> "The merger could not produce a unified draft. The three sub-run
> drafts at `research/notes/final_report-run-{a,b,c}.md` are
> independently valid artifacts — each passed its own audit. The
> merger reported: `<reason>`. You can pick the strongest sub-run
> draft, promote it to `research/notes/final_report.md`, and save
> it manually as the final report. Or re-run the ensemble."

Halt. Do not proceed to Step 8 without a merged draft.

---

## Step 8: Run Step 11 audit on the merged draft (parent vault)

The merged draft is a NEW synthesis — it gets a full adversarial
audit in the parent vault's `research/audit_findings.json`, same as
a normal `/research` run would.

Spawn `hyperresearch-auditor` twice — sequentially, comprehensiveness
first then conformance:

```
First spawn (wait for completion before the second):
  research_query: <verbatim user prompt from Step 2>
  modality: <from Step 1>
  mode: comprehensiveness
  final_report_path: research/notes/final_report.md
  audit_findings_path: research/audit_findings.json
  scaffold_note_id: <id of run-a's scaffold note, or the base_run's>

Second spawn (after the first returns):
  research_query: <verbatim user prompt from Step 2>
  modality: <from Step 1>
  mode: conformance
  final_report_path: research/notes/final_report.md
  audit_findings_path: research/audit_findings.json
  scaffold_note_id: <same as above>
```

The auditor writes to the parent's audit_findings.json, which now
contains:
1. The merger's `mode: merger` entry
2. The comprehensiveness auditor's entry
3. The conformance auditor's entry

---

## Step 9: Apply audit fixes, re-audit if needed

Standard fix-apply loop:
1. Read both auditor returns. For each CRITICAL, apply the fix to
   `research/notes/final_report.md`. The merged draft can tolerate
   small edits here — the merger's structural spine stays, but you
   can add a missing citation, tighten a hedge, or expand an under-
   developed prompt-named section by pulling from the per-run
   extract notes (tagged with `run-a`/`run-b`/`run-c`).
2. For each fix, set the finding's `fixed_at` timestamp in the
   parent's audit_findings.json.
3. If any CRITICAL cannot be resolved by editing (e.g., the merged
   draft lacks evidence for a prompt-named item AND no sub-run
   surfaced it), the correct fix may be to fetch new sources and
   re-audit — but at this point you are doing single-run work on the
   merged draft, not ensemble work.
4. Re-run `hyperresearch-auditor` (both modes) to verify the fixes
   landed. The `audit-gate` lint rule checks that every CRITICAL in
   the newest conformance run has `fixed_at` populated.

```bash
PYTHONIOENCODING=utf-8 $HPR lint --rule audit-gate -j
```

Must return no issues. The default `audit-gate` path is the parent's
`research/audit_findings.json` — no `--audit-file` override needed
at this step because you ARE checking the parent.

---

## Step 10: Save the synthesis — standard Step 13 of `/research`

Promote the merged draft to a first-class synthesis note in the
vault. Use the same command `/research` uses:

```bash
PYTHONIOENCODING=utf-8 $HPR note new "<concise title derived from prompt>" \
  --tag synthesis --tag ensemble \
  --tier institutional \
  --content-type synthesis \
  --summary "<one-line summary of the merged conclusion>" \
  --status review \
  --body-file research/notes/final_report.md \
  -j
```

The `audit-gate` lint rule blocks save if any CRITICAL in the latest
conformance run is unresolved — standard protection.

---

## Step 11: Report to the user

Report a tight summary. What the user needs to see:

```
Ensemble research complete.

Merged final report: research/notes/final_report.md (<N> words)

Sub-run drafts (preserved for reference):
- research/notes/final_report-run-a.md (breadth, <N> words, <K> citations)
- research/notes/final_report-run-b.md (depth,   <N> words, <K> citations)
- research/notes/final_report-run-c.md (dialectical, <N> words, <K> citations)

Merger picked run-<X> as base; <S> splices applied from siblings.
Combined unique sources: <N> (target was 50+).
Merged draft passed comprehensiveness + conformance audit.

Per-run audit files: research/audit_findings-run-{a,b,c}.json
Parent audit findings: research/audit_findings.json (includes merger
entry + post-merger audits)
```

If the combined source count fell short of 50, note that explicitly
— ensemble underperformed its volume target, which likely means all
three sub-runs ran out of high-signal sources in the domain (benign)
or skimped on fetching (non-benign; surface it so the user can
decide).

---

## Hard rules — orchestrator scope

- **The user's prompt is gospel.** Pass it verbatim to all three
  sub-runs; the merger verifies character-for-character identity
  across the three scaffolds' prompt sections.
- **Classify exactly once.** All three sub-runs use the same
  modality. No per-sub-run reclassification.
- **Spawn the three sub-runs in parallel, not sequentially.** Three
  `Task` calls in a single message. Sequential spawning defeats
  half the point.
- **Do NOT spawn the merger before verifying all three sub-run
  audit-gates pass.** Bad sub-run inputs produce bad merges.
- **Do NOT write to `research/notes/final_report.md` before the
  merger runs.** That path is reserved for the merged output.
- **Do NOT skip the post-merger audit.** The merged draft is a new
  synthesis — it gets the same Step 11 treatment as a normal
  `/research` run.
- **Do NOT silently delete per-run artifacts after merging.** The
  sub-run drafts stay on disk as independently readable artifacts
  — users may want to see how the three framings diverged.
- **Do NOT convert the ensemble to a single-run on sub-run failure.**
  If a sub-run fails audit, halt and surface options. The user
  invoked `/research-ensemble` specifically; silently degrading to
  single-run is worse than explicit failure.
- **Cost disclosure is mandatory, early.** The user must know ~5x
  cost before the three sub-runs start.

---

## Why this design (for future maintainers)

The ensemble attacks two single-run ceilings:

1. **Variance ceiling** — three Sonnet sub-runs with subtly different
   framings produce three parallel readings; compounding LLM
   randomness drives natural divergence in source discovery and
   emphasis. The merger picks the best-of-3 structural spine and
   splices in unique evidence from the other two.

2. **Depth-of-corpus ceiling** — because all three sub-runs share ONE
   unified vault, their combined fetch decisions stack into a richer
   source corpus than any single run could produce. Each sub-run
   pushes for 25+ of its own fetches; the shared corpus grows toward
   60+, and every sub-run sees what the others found (natural, not
   forced, deduplication via `INSERT OR IGNORE`).

The unified vault is the critical architectural choice. Per-sub-run
vaults would isolate the corpora, losing the compounding-knowledge
benefit. With a shared vault, the knowledge base persists across the
ensemble and across future sessions — a long-lived asset, not a
per-run workspace.

The three framings are deliberately SUBTLE — not radical "styles".
Radical styles produce tonally incompatible drafts the merger can't
harmonize. Subtle nudges plus LLM nondeterminism produce divergent
source discovery without clashing voices; the merger's job stays
tractable.

Cost: ~5x a normal `/research` run (3 sub-runs + merger + post-
merger audit + orchestrator overhead). Not 2x, not 3x. Be honest
with users.
