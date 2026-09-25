---
name: hyperresearch-16-readability-audit
description: >
  Step 16 (final) of the hyperresearch V8 pipeline. Spawns the
  hyperresearch-readability-recommender subagent (<% if platform == "codex" %>reads the report,
  writes JSON only<% else %>Read+Write
  tool-locked<% endif %>) to audit the polished final report and write JSON
  recommendations for paragraph merges, breaks, list/table conversions,
  bold injection, sentence splits, and HR removal. The orchestrator
  reads the recommendations and SELECTIVELY applies them via direct
  <% if platform == "codex" %>apply_patch hunks<% else %>Edit calls<% endif %> (the recommender does NOT modify the report itself).
  Logs orchestrator decisions to a separate file. Runs for ALL tiers.
  Invoked via <% if platform == "codex" %>step-file read<% else %>Skill tool<% endif %> from the entry skill.
---

# Step 16 — Readability audit & selective apply (FINAL STEP)

**Tier gate:** Runs for ALL tiers. Every report gets a readability audit, regardless of tier — readability is the dimension where small structural changes (paragraph rhythm, list/table conversions, bold injection) yield outsized scoring gains.

**Goal:** improve the report's visual structure, paragraph rhythm, and scannability without changing substantive content. The recommender writes a JSON list of suggested changes; YOU (the orchestrator) decide which to apply.

**Why split recommender + orchestrator-applied:** an <% if platform == "codex" %>patch<% else %>Edit<% endif %>-based reformatter (V7-style) sometimes makes changes that hurt the argument — converting a flowing paragraph to a bullet list when the prose was load-bearing, or merging paragraphs that addressed distinct sub-topics. By having the recommender produce JSON suggestions and the orchestrator decide what to apply, we get the recommender's pattern-matching speed plus your judgment about which changes serve the research_query.

---

## Recover state

Read these inputs:
- `research/runs/<vault_tag>/scaffold.md` — vault_tag
- `research/notes/final_report_<vault_tag>.md` — the polished final report from step 15

---

## Step 16.1 — Spawn the readability recommender

Spawn ONE `hyperresearch-readability-recommender` subagent<% if platform == "codex" %> (custom agent `.codex/agents/hyperresearch-readability-recommender.toml`) and wait for it to finish<% else %><% endif %>. Single spawn, runs once.

**Spawn template:**
```
<% if platform == "codex" %>custom_agent: hyperresearch-readability-recommender   # spawn the custom agent defined in .codex/agents/hyperresearch-readability-recommender.toml<% else %>subagent_type: hyperresearch-readability-recommender<% endif %>
prompt: |
  RESEARCH QUERY (verbatim, gospel):
  > {{paste research/runs/<vault_tag>/query.md body}}

  QUERY FILE: research/runs/<vault_tag>/query.md

  PIPELINE POSITION: You are step 16 of the hyperresearch V8 pipeline —
  the final analytical pass. The final report at
  research/notes/final_report_<vault_tag>.md has been drafted (step 10),
  synthesized (step 11), critiqued (step 12), gap-filled (step 13),
  patched (step 14), and polish-audited (step 15). Your job: write
  JSON recommendations for paragraph rhythm, list/table conversions,
<% if platform == "codex" %>  and other structural readability improvements. You only read the
  report and write your recommendations file — you never modify the
  report. The orchestrator
<% else %>  and other structural readability improvements. You are tool-locked
  to [Read, Write] — you cannot Edit the report. The orchestrator
<% endif %>  reads your recommendations and decides which to apply.

  YOUR INPUTS:
  - draft_path: research/notes/final_report_<vault_tag>.md
  - recommendations_path: research/runs/<vault_tag>/readability-recommendations.json

  RUN DIRECTIVES: append the FULL contents of research/runs/<vault_tag>/shims/polish.md here, verbatim.

  Write recommendations as a JSON array per the schema in your agent
  prompt. Cap at << p.readability_rec_cap >> recommendations, prioritized by impact.
```

---

## Step 16.2 — Read the recommendations

When the recommender returns:

1. **Read `research/runs/<vault_tag>/readability-recommendations.json`.**

2. **Read the recommender's report-back.** It tells you:
   - Total count of recommendations
   - Breakdown by category (merge-paragraphs, break-paragraph, make-list, make-table, bold-keyterms, split-sentence, remove-hr, add-whitespace)
   - Highest-severity issue
   - Expected net char delta if all applied

---

## Step 16.3 — Decide which to apply

You are not obligated to apply every recommendation. Use these heuristics:

**Apply confidently:**
- All `merge-paragraphs` recommendations where adjacent paragraphs are clearly the same sub-topic (rationale field confirms this)
- All `break-paragraph` recommendations on paragraphs > 800 CJK / 1500 EN chars
- All `remove-hr` recommendations (horizontal rules don't belong in research reports)
- All `add-whitespace` recommendations (zero risk)
- `make-table` recommendations when the prose-comparison passage cited 3+ entities × 2+ dimensions and the recommender's suggested table preserves all comparison points

**Apply with judgment:**
- `make-list` recommendations: confirm the prose was actually enumerative (3+ items in sequence) and not load-bearing argumentative prose. If the rationale says "items appear sequentially in flowing prose," that's NOT a list candidate — skip it.
- `bold-keyterms` recommendations: confirm the term is genuinely a key term, not just any noun. Bold load-bearing concepts and statistics; don't over-bold.

**Apply skeptically (often skip):**
- `split-sentence` recommendations on argumentative prose where sentence length serves emphasis or rhythm
- Recommendations that touch the opening thesis paragraph (load-bearing — keep as written)
- Recommendations that change tables that already exist

**Always skip:**
- Any recommendation whose `current` field doesn't match the actual draft (the recommender mis-anchored — log and ignore)
- Recommendations that would change H2 heading text
- Recommendations that delete substantive content (the recommender shouldn't, but verify)

---

<% if platform == "codex" %>## Step 16.4 — Apply chosen recommendations via apply_patch

For each recommendation you decide to apply:

1. Use `apply_patch` on `research/notes/final_report_<vault_tag>.md`
2. Text to replace = the recommendation's `current` field (exactly as the recommender wrote it)
3. Replacement text = the recommendation's `recommended` field

**For non-ASCII text (CJK / Arabic / Cyrillic):** the recommender copied `current` verbatim from the report file.<% else %>## Step 16.4 — Apply chosen recommendations via Edit

For each recommendation you decide to apply:

1. Use the Edit tool on `research/notes/final_report_<vault_tag>.md`
2. `old_string` = the recommendation's `current` field (exactly as the recommender wrote it)
3. `new_string` = the recommendation's `recommended` field

**For non-ASCII text (CJK / Arabic / Cyrillic):** the recommender copied `current` verbatim from Read output.<% endif %> Trust that. Don't retype.

**Order of application:**
1. `remove-hr` first (smallest changes, cleanest baseline)
2. `merge-paragraphs` and `break-paragraph` (paragraph-level changes)
3. `make-list` and `make-table` (structural conversions)
4. `bold-keyterms` (within paragraphs that survived the merges/breaks)
5. `split-sentence` (within finalized paragraphs)
6. `add-whitespace` (final cleanup)

If <% if platform == "codex" %>a patch fails because the `current` text<% else %>an Edit fails because `old_string`<% endif %> doesn't match (recommender mis-anchored), skip that recommendation and continue with the rest.

---

## Step 16.5 — Log decisions

Write `research/runs/<vault_tag>/readability-decisions.json` with the orchestrator's decisions:

```json
{
  "total_recommendations": <int>,
  "applied": [<list of recommendation IDs you applied>],
  "skipped": [
    {"id": "rec-N", "reason": "<one sentence>"}
  ],
  "edit_failures": [
    {"id": "rec-N", "reason": "old_string did not match the draft"}
  ],
  "net_char_delta_actual": <int — measure the actual delta>
}
```

This is the audit trail. If a future review finds a readability problem we should have fixed, this log shows whether we considered it and skipped, or never saw the recommendation.

---

## Exit criterion

- `research/runs/<vault_tag>/readability-recommendations.json` exists
- `research/runs/<vault_tag>/readability-decisions.json` exists with at least one entry in `applied` or all `skipped`
- `research/notes/final_report_<vault_tag>.md` reflects the applied recommendations
- The final report's structure (H2 list, executive summary, conclusion) is unchanged from step 15's output (this step does not restructure)

---

## Pipeline complete

<% if platform == "codex" %>Return to the entry skill (`hyperresearch`) and run its **Final integrity gate** (`run finish`). Mark all plan items complete. Only after `run finish` reports `"passed": true` (or the run is honestly `blocked` after 3 fix rounds), tell the user the final report path and list any still-queued escalations.

The run is not done until the gate has spoken.<% else %>Return to the entry skill (`hyperresearch`). Mark all todos complete. Tell the user the final report path.

You're done.<% endif %>
