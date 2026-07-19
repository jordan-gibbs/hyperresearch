---
name: hyperresearch-14-5-cite-check
description: >
  Step 14.5 of the hyperresearch V8 pipeline (full + dissertation tiers).
  Verifies that each citation in the patched report actually supports its
  sentence: mechanical triage auto-passes pairs confirmed by the claims
  table, the cite-checker agent judges the sampled remainder, and a second
  small patcher pass applies the findings. Runs AFTER step 14 (the patcher
  moved text and citations; audit what will actually ship) and BEFORE step
  15 (polish sees the corrected text). Invoked via Skill tool.
---

# Step 14.5 — Cite-check (citation-sentence binding verification)

**Tier gate:** Runs for `full` and `dissertation`. SKIP for `light` — a light report's citation volume doesn't justify the pass; the `quote-integrity` and `numeric-consistency` lint rules still cover it mechanically at the step-15 gate.

**Goal:** every citation that ships either supports its sentence or gets fixed. This is the difference between "has citations" and "citations are true bindings" — the single thing external fact-checkers actually measure.

---

## Recover state

Read these inputs:
- `research/runs/<vault_tag>/scaffold.md` — vault_tag
- `research/notes/final_report_<vault_tag>.md` — the PATCHED report from step 14

---

## Step 14.5.1 — Extract + mechanical triage

```bash
$HPR citecheck extract <vault_tag> -j
```

This parses every (sentence, citation) pair from the report — both `[N]` and `[[note-id]]` styles — and auto-passes pairs whose numbers or wording the cited note's extracted claims already confirm. Output: `research/runs/<vault_tag>/cite-check-pairs.json` with:
- `summary` — total / auto-passed / dangling / needs-llm counts
- `sampled_for_llm` — the pairs the agent must judge (100% of number-bearing sentences; sampled for the rest)
- `dangling` — citations that resolve to NO vault note

**Dangling citations are findings immediately** — no agent needed. Each one becomes a `critical` finding (fabricated or mangled citation).

**If `sampled_for_llm` is empty and there are no dangling citations:** write an empty findings file `[]` to `research/runs/<vault_tag>/cite-check-findings.json`, record `$HPR run step <vault_tag> 14.5 --status done -j`, and proceed to step 15. Done.

---

## Step 14.5.2 — Spawn the cite-checker

Spawn ONE `hyperresearch-cite-checker` subagent (two in parallel with split index ranges when `sampled_for_llm` exceeds ~40 pairs):

```
subagent_type: hyperresearch-cite-checker
prompt: |
  RESEARCH QUERY (verbatim, gospel):
  > {{paste research/runs/<vault_tag>/query.md body}}

  QUERY FILE: research/runs/<vault_tag>/query.md

  PIPELINE POSITION: You are step 14.5 (cite-checker) of the hyperresearch
  V8 pipeline. Step 14's patcher already applied critic findings; you
  verify citation-sentence bindings on the text that will ship. Your
  findings feed a second, small patcher pass. You do not edit the report.

  YOUR INPUTS:
  - pairs_file: research/runs/<vault_tag>/cite-check-pairs.json
  - your_range: sampled_for_llm[<start>..<end>]
  - findings_path: research/runs/<vault_tag>/cite-check-findings.json
  - vault_tag: <vault_tag>
```

When splitting across two checkers, give each its own findings path (`cite-check-findings-a.json` / `-b.json`) and merge the arrays into `cite-check-findings.json` yourself afterward.

---

## Step 14.5.3 — Second patcher pass

Append the dangling-citation findings (from 14.5.1) to the findings file, then reuse the step 14 machinery exactly: spawn ONE `hyperresearch-patcher` (tool-locked Read + Edit) with `research/runs/<vault_tag>/cite-check-findings.json` as its findings input and `research/runs/<vault_tag>/cite-check-patch-log.json` pre-stubbed:

```json
{"total_findings": 0, "applied": [], "skipped": [], "conflicts": [], "orchestrator_escalated": []}
```

Fix repertoire (in the findings' `suggested_fix`): swap to `correct_note_id`, soften the claim to what the source supports, or delete the sentence when nothing supports it. Same rules as step 14: surgical hunks, zero regeneration, `critical` findings must not be silently skipped.

**Skip the pass entirely** when the merged findings file is `[]`.

---

## Exit criterion

- `research/runs/<vault_tag>/cite-check-pairs.json` exists
- `research/runs/<vault_tag>/cite-check-findings.json` exists (possibly `[]`)
- If findings were non-empty: `cite-check-patch-log.json` shows every `critical` finding applied or escalated
- Manifest: `$HPR run step <vault_tag> 14.5 --status done -j`

## Next step

Return to the entry skill and invoke `Skill(skill: "hyperresearch-15-polish")`.
