---
name: hyperresearch-5-depth-investigation
description: >
  Step 5 of the hyperresearch V8 pipeline. Spawns K depth-investigator
  subagents in parallel (one per scored locus), each producing one
  interim note with a Committed Position section. Investigators read
  full source bodies for their locus and may fetch additional sources
  within their source_budget. Invoked via Skill tool from the entry
  skill (full tier only).
---

# Step 5 — Depth investigation (parallel, K = len(loci))

**Tier gate:** SKIP entirely for `light` tier. Only `full` tier runs depth investigation.

**Goal:** produce ONE `interim-{locus}.md` note per locus with dense synthesis that the draft sub-orchestrators (step 10) will draft from.

---

## Recover state

Read these inputs:
- `research/scaffold.md` — vault_tag
- `research/loci.json` — scored loci with source_budget per locus
- `research/temp/contradiction-graph.json` (if step 3 ran)
- `research/query-<vault_tag>.md` — canonical research query

---

## Procedure

1. **Spawn K `hyperresearch-depth-investigator` subagents in parallel** (ONE message, all Task calls). One per locus with `source_budget > 0`, capped at 6.

   **Spawn template:**
   ```
   subagent_type: hyperresearch-depth-investigator
   prompt: |
     RESEARCH QUERY (verbatim, gospel):
     > {{paste research/query-<vault_tag>.md body}}

     QUERY FILE: research/query-<vault_tag>.md

     PIPELINE POSITION: You are step 5 (depth-investigator) of the
     hyperresearch V8 pipeline. Step 4's loci analysts produced research/loci.json;
     after you return, step 6 will reconcile your committed position against
     the other investigators' positions in research/comparisons.md.

     YOUR LOCUS (from research/loci.json):
     - name: "<locus name>"
     - one_line: "<one-line locus description>"
     - flavor: "dialectical" / "synthesis" / "technical"
     - source_budget: <integer from loci.json>
     - rationale: "<why this locus matters>"

     YOUR INPUTS:
     - corpus_tag: <vault_tag>
     - locus_name: <locus name>
     - source_budget: <hard cap on additional sources you can fetch>

     CRITICAL: Read the full source text of relevant vault notes (via
     `hyperresearch note show <id1> <id2> ... -j`) BEFORE writing your
     interim note. Drafting from summaries alone produces paraphrase;
     drafting from full text produces synthesis. Use your source_budget
     to fetch additional sources beyond the width corpus if needed.

     OUTPUT: Write a single interim note via the hyperresearch CLI with
     type=interim, tags = <vault_tag> + locus-<locus-name>. The note MUST
     end with a "## Committed position" section that takes a SIDE on the
     dialectical question (or a synthesis verdict for non-dialectical
     loci). Include calibration: confidence level, what evidence would
     change your mind.
   ```

   Each investigator's hard cap is `locus.source_budget`, not a flat number.

2. **Each investigator writes ONE interim note** into the vault with `type: interim` and tags `<vault_tag>` + `locus-<locus-name>`. Return value is the note id.

3. **Wait for all K to complete.** Investigators can fail independently. Proceed with whichever succeeded. If >50% failed, stop and reassess loci quality with the user.

4. **Read the interim notes.** After all return, list them:
   ```bash
   $HPR search "" --tag <vault_tag> --type interim --json
   ```
   Then batch-read them:
   ```bash
   $HPR note show <id1> <id2> ... -j
   ```
   Hold the Committed Position sections in your context — they are the load-bearing input to step 6 (cross-locus reconciliation).

**INVARIANT:** Every interim note ends with a `## Committed position` section. An interim note ending with descriptive summary only is defective — flag it and re-spawn that investigator with the committed-position requirement emphasized.

---

## Exit criterion

- One interim note per locus with `source_budget > 0`, each tagged `<vault_tag>` + `locus-<locus-name>`
- Every interim note ends with `## Committed position`

If >50% of investigators failed: stop and escalate.

---

## Next step

Return to the entry skill (`hyperresearch`). Invoke step 6:

```
Skill(skill: "hyperresearch-6-cross-locus-reconcile")
```
