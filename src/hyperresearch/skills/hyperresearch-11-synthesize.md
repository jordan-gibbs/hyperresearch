---
name: hyperresearch-11-synthesize
description: >
  Step 11 of the hyperresearch V8 pipeline. Reads the 3 angle-specific drafts
  from step 10, spot-checks factual conflicts, writes a synthesis plan +
  outline, then spawns ONE hyperresearch-synthesizer subagent (Read+Write
  tool-locked) that writes the final report in TWO passes — pass 1 rough
  integrated draft, pass 2 voice/redundancy/length cleanup. Skipped for
  light tier (which writes a single draft directly in step 10). Invoked
  via Skill tool from the entry skill (full tier).
---

# Step 11 — Synthesize the final report

**Tier gate:** SKIP entirely for `light` tier — light tier wrote `research/notes/final_report_<vault_tag>.md` directly in step 10 and proceeds straight to step 15 (polish). For `full`: run as documented below.

**Goal:** turn the 3 angle-specific drafts from step 10 into ONE integrated final report at `research/notes/final_report_<vault_tag>.md`. The orchestrator preps the strategic brief; the synthesizer subagent writes the report in two passes (rough integrated draft, then voice/redundancy/length cleanup).

**Why split orchestrator + synthesizer:** the orchestrator has been running for 30+ minutes and 200K+ tokens of context. Writing a coherent 5000-10000 word report at this point is the highest cognitive load step in the pipeline, and orchestrator context is full of stale subagent dispatch logic. The synthesizer is a fresh session with `[Read, Write]` tool-lock, focused exclusively on producing the final report. This is the same architectural move that made the patcher and polish-auditor reliable.

---

## Recover state

Read these inputs:
- `research/runs/<vault_tag>/scaffold.md` — vault_tag
- `research/runs/<vault_tag>/prompt-decomposition.json` — atomic items, required_section_headings, response_format, citation_style
- `research/runs/<vault_tag>/temp/draft-a.md`, `research/runs/<vault_tag>/temp/draft-b.md`, `research/runs/<vault_tag>/temp/draft-c.md` — the 3 angle-specific drafts from step 10
- `research/runs/<vault_tag>/comparisons.md` (full tier) — cross-locus tensions
- `research/runs/<vault_tag>/temp/source-tensions.json` (full tier) — expert disagreements
- `research/runs/<vault_tag>/temp/evidence-digest.md` — load-bearing claims with verbatim quotes
- `research/runs/<vault_tag>/query.md` — canonical research query (GOSPEL)

---

## Step 11.1 — Read all 3 drafts in full

1. **Read each draft in full** from `research/runs/<vault_tag>/temp/draft-{a,b,c}.md`. Don't skim — actually read. Hold them in context.

2. **Re-read each sub-orchestrator's report-back** (from your own task results in step 10). Note each draft's:
   - Core thesis
   - How many notes from `must_read_note_ids` it actually read
   - Strongest argumentative beat
   - Word/character count

---

## Step 11.2 — Spot-check factual conflicts (orchestrator only)

The synthesizer is tool-locked to `[Read, Write]` — it cannot run Bash to query the vault. So YOU resolve factual conflicts here, before spawning it.

For each substantive contradiction between drafts:
1. Identify the cited source IDs on both sides
2. `$HPR note show <id1> <id2> -j` to read the actual source bodies
3. Decide which side is correct. Write the verdict to `research/runs/<vault_tag>/temp/synthesis-conflicts.md`:
   ```markdown
   ## Conflict 1: <one-line description>
   - Draft A says: <claim with citation>
   - Draft B says: <opposing claim with citation>
   - Source check: <what the source actually says, verbatim where possible>
   - **Verdict:** <which side, with reason>
   ```

If there are no substantive conflicts, write a one-line file: "No factual conflicts found across drafts."

---

## Step 11.3 — Write the synthesis plan

Write `research/runs/<vault_tag>/temp/synthesis-plan.md`. This is your strategic brief for the synthesizer:

```markdown
# Synthesis plan

## Core thesis (1-2 sentences)
<the final report's central argument>

## The 3-7 strongest argumentative beats
1. **<short name>** — sourced from Draft <A/B/C>. <one sentence on the beat and why it's load-bearing>
2. ...

## Section structure
<list required_section_headings if present, OR the inferred H2 structure>

## Per-section commitments
### Section 1: <heading>
- Evidence to pull from: Draft A's <topic>, Draft C's <topic>
- Argumentative beat: <which committed position to argue here>
- Cross-locus tension to engage (if any): <name from comparisons.md>

### Section 2: ...

## Where drafts disagreed
- **<Disagreement 1>:** Draft A says X; Draft B says Y. **Commit to <side>** because <reason>. The other side gets explicit engagement, not equal hedging.
- ...

## Length target
- response_format: <short|structured|argumentative>
- Pass 1 target: <middle of pass-1 range>
- Pass 2 final target: <middle of pass-2 range>
```

---

## Step 11.4 — Write the synthesis outline

Write `research/runs/<vault_tag>/temp/synthesis-outline.md`. This is the per-section contract — 1-2 sentences per H2 naming what evidence and argument lives there:

```markdown
# Synthesis outline

## Executive summary
<1-2 sentences: the direct answer to the research_query, with top-line numbers if applicable>

## I. <First H2 from required_section_headings or plan>
<1-2 sentences: what this section establishes, which evidence anchors it, what argumentative beat lives here>

## II. <Second H2>
<1-2 sentences>

...

## Conclusion / Opinionated synthesis
<1-2 sentences: the committed reading, the strongest forward-looking implication>

## Sources
<only emitted when citation_style == "inline" — N numbered entries, deduplicated. For "wikilink" style (default), the wiki-link markers in the body are self-resolving and no separate Sources section is needed.>
```

The outline is short (50-200 words total). It's the structural anchor that prevents pass-1 sections from rambling.

---

## Step 11.5 — VERIFICATION GATE

Before spawning the synthesizer, verify these files exist with non-trivial content:
- `research/runs/<vault_tag>/temp/synthesis-plan.md` — must include the core thesis and at least one per-section commitment
- `research/runs/<vault_tag>/temp/synthesis-outline.md` — must include one outline entry per H2 in the planned structure
- `research/runs/<vault_tag>/temp/synthesis-conflicts.md` — exists (may say "no conflicts found")
- `research/runs/<vault_tag>/temp/draft-{a,b,c}.md` — all three exist

If any are missing or trivial, fix them before proceeding. The synthesizer cannot do strategic planning — it can only execute the plan. Skipping plan/outline produces a thin synthesizer output that doesn't beat the original drafts.

---

## Step 11.6 — Spawn the synthesizer

Spawn ONE `hyperresearch-synthesizer` subagent. Single spawn, runs once.

**Spawn template:**
```
subagent_type: hyperresearch-synthesizer
prompt: |
  RESEARCH QUERY (verbatim, gospel):
  > {{paste research/runs/<vault_tag>/query.md body}}

  QUERY FILE: research/runs/<vault_tag>/query.md

  PIPELINE POSITION: You are step 11 of the hyperresearch V8 pipeline.
  Step 10 produced 3 angle-specific drafts. The orchestrator wrote a
  synthesis plan and outline. You read everything and write the final
  report in TWO passes (pass 1 = rough integrated draft, pass 2 = voice/
  redundancy/length cleanup). You are tool-locked to [Read, Write] — you
  cannot Bash, cannot spawn subagents. After you return, step 12 (4
  critics) reads your final report.

  YOUR INPUTS:
  - query_file_path: research/runs/<vault_tag>/query.md
  - draft_paths: [research/runs/<vault_tag>/temp/draft-a.md, research/runs/<vault_tag>/temp/draft-b.md, research/runs/<vault_tag>/temp/draft-c.md]
  - synthesis_plan_path: research/runs/<vault_tag>/temp/synthesis-plan.md
  - synthesis_outline_path: research/runs/<vault_tag>/temp/synthesis-outline.md
  - synthesis_conflicts_path: research/runs/<vault_tag>/temp/synthesis-conflicts.md
  - decomposition_path: research/runs/<vault_tag>/prompt-decomposition.json
  - comparisons_path: research/runs/<vault_tag>/comparisons.md
  - source_tensions_path: research/runs/<vault_tag>/temp/source-tensions.json
  - evidence_digest_path: research/runs/<vault_tag>/temp/evidence-digest.md
  - pass1_output_path: research/runs/<vault_tag>/temp/synthesis-pass1.md
  - final_output_path: research/notes/final_report_<vault_tag>.md
  - response_format: "<short|structured|argumentative>"
  - citation_style: "<wikilink|inline|none>"

  RUN DIRECTIVES: append the FULL contents of research/runs/<vault_tag>/shims/drafting.md here, verbatim.

  Read everything. Write pass 1 to pass1_output_path. Then audit pass 1
  for redundancy, voice consistency, weak sections, and length, and
  write the cleaned pass 2 to final_output_path. Do not paste paragraphs
  from the input drafts — synthesize them in your own voice.

  **Citation rendering:**
  - If citation_style == "wikilink" (default): every citation is a
    `[[note-id]]` marker pointing at the source note in the vault. No
    separate `## Sources` section. The wiki-link IS the citation —
    readers click through to the source note's frontmatter for title +
    URL. Do NOT add numbered references.
  - If citation_style == "inline": every citation is a `[N]` marker
    (multiple sources at one point grouped in a single bracket:
    `[7, 12]`, never stacked `[7][12]`), AND the report ends with a
    `## Sources` section listing each cited source as `[N] Title. URL`
    (read each cited note's YAML frontmatter for title + URL).
  - If citation_style == "none": no citation markers anywhere, no
    Sources section.
```

**CRITICAL: never emit bare text while the synthesizer is running.** It will take 5-15 minutes (two passes). Use the wait time to think — append notes to `research/runs/<vault_tag>/temp/orchestrator-notes.md` about what you'll watch for in step 12 (the critics) based on the synthesis plan you just wrote.

---

## Step 11.7 — Validate the synthesizer output

When the synthesizer returns:

1. **Confirm both files exist:**
   - `research/runs/<vault_tag>/temp/synthesis-pass1.md` (pass 1, rough integrated)
   - `research/notes/final_report_<vault_tag>.md` (pass 2, final)

2. **Read the synthesizer's report-back.** It tells you:
   - Word/character count
   - Pass 1 vs pass 2 length delta (should be NEGATIVE — pass 2 cuts)
   - Top redundancies cut
   - Top voice fixes
   - Sections flagged as still weak

3. **Sanity checks on the final report:**
   - **LENGTH GATE (mechanical, not a judgment call):** count the words (`wc -w` or python). The profile ceiling for the response_format is a HARD limit — the ship gate (`run finish`) fails any report more than 20% over target, so an over-long report here is guaranteed rework later. Check it now, when fixing is cheapest.
   - Has all H2s from `required_section_headings`
   - Citations match `citation_style`: `[[note-id]]` markers for `"wikilink"` (no Sources section); `[N]` markers + a `## Sources` section for `"inline"`; no markers for `"none"`
   - No adjacent citation stacks (`grep -c ']['` should be 0 — grouped brackets like `[7, 12]` are the style)
   - Major body sections open with a plain-language primer before the analysis (spot-check 3 sections)
   - No YAML frontmatter, no scaffold leaks, no pipeline vocabulary

If pass 2 is longer than pass 1 (positive delta), something went wrong — pass 2 is supposed to cut. Investigate before proceeding.

**If the length gate fails (word count above the target high):** re-spawn the synthesizer ONCE for a compression pass — input is its own final report, directive is "cut to <middle of target range> words: collapse redundant sections, cut the weakest evidence per point, keep every load-bearing claim and citation." This is the ONE permitted regeneration, because the write-once invariant starts only after this step's exit criteria pass; length violations discovered later can only be fixed by exactly this move at higher cost.

If any other sanity check fails, hand-craft an Edit on `research/notes/final_report_<vault_tag>.md` yourself to fix it. Do NOT re-spawn the synthesizer for non-length issues — that's regeneration, which violates the patch-not-regenerate invariant once we have a final draft.

---

## Write-once after synthesis

After this step, the final report is only modified by Edit hunks from the patcher (step 14) and polish auditor (step 15). Do NOT re-write or re-synthesize.

---

## Exit criterion

- `research/notes/final_report_<vault_tag>.md` exists, **word count verified ≤ target high** (counted mechanically, not estimated)
- `research/runs/<vault_tag>/temp/synthesis-pass1.md` exists (debugging artifact)
- All H2s from `required_section_headings` present
- Citations match `citation_style` (wikilink → `[[note-id]]` no Sources section; inline → `[N]` + Sources section; none → no markers), with no adjacent citation stacks
- No YAML frontmatter, no pipeline vocabulary, no scaffold leaks

---

## Next step

Return to the entry skill (`hyperresearch`). Invoke step 12:

```
Skill(skill: "hyperresearch-12-critics")
```
