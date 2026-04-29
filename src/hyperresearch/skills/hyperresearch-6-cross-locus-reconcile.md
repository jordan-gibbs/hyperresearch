---
name: hyperresearch-6-cross-locus-reconcile
description: >
  Step 6 of the hyperresearch V8 pipeline. Reconciles the committed positions
  from all depth investigators into research/comparisons.md — 3-5 named
  cross-locus tensions with engagement guidance for the draft. This is
  the structural step that gives the single draft argumentative density.
  Invoked via Skill tool from the entry skill (full tier only).
---

# Step 6 — Cross-locus reconciliation

**Tier gate:** SKIP entirely for `light` and `standard` tiers (no loci = no comparisons). Only `full` tier runs this step.

**Goal:** before drafting, reconcile the committed positions from all depth investigators. Produce `research/comparisons.md` — a short document naming 3–5 places where the loci conflict or complicate each other.

**Why this step exists:** the depth investigators each committed to a position on their own locus. Some of those positions disagree, some reinforce each other, some partially complicate each other. The draft must engage those cross-locus dynamics explicitly — not summarize each locus in isolation. Writing `comparisons.md` forces you to see the loci in cross-section before opening the draft.

**This step is always-on for full tier.** Even single-locus runs produce `comparisons.md` — with that locus's committed position as the lone argumentative anchor the draft must engage. The discipline of writing it down BEFORE drafting is the same.

---

## Recover state

Read these inputs:
- `research/scaffold.md` — vault_tag
- `research/loci.json` — scored loci
- All interim notes: `$HPR search "" --tag <vault_tag> --type interim --json` then `$HPR note show <id1> <id2> ... -j`

You need the `## Committed position` section from every interim note in your context.

---

## Procedure

1. **Lay out all committed positions.** For each interim note, read its `## Committed position` section. Write them down side-by-side in a scratch list (you can use `research/temp/orchestrator-notes.md` as scratch).

2. **Hunt for tensions.** Ask of every pair of positions:
   - Do they agree on the facts but disagree on what the facts mean?
   - Do they cite different evidence and reach opposite conclusions?
   - Does one locus's position assume something another locus's evidence complicates?
   - Is one locus's position a special case of another's general claim?
   - Do they converge on a conclusion but via different mechanisms (worth noting — convergence from independent paths is itself a finding)?

3. **Pick the 3–5 strongest cross-locus dynamics.** Reject weak ones (loci that are simply orthogonal, or that restate each other). You want cross-locus relationships that a good final draft should actually wrestle with.

4. **Write `research/comparisons.md`:**

   ```markdown
   # Cross-locus comparisons

   ## Tension 1: <short name for the dynamic>

   - **Locus A** ([[interim-A]]) commits: <one-line committed position>
   - **Locus B** ([[interim-B]]) commits: <one-line committed position>
   - **The cross-locus dynamic:** <2–3 sentences naming exactly how they relate — conflict? convergence? complication? special case? Name the load-bearing disagreement or agreement.>
   - **How the draft should engage this:** <one sentence. Example: "Section on X must acknowledge that Y from Locus B undercuts the simple reading of Locus A" or "The recommendation should privilege Locus B's position because its evidence base is stronger.">

   ## Tension 2: ...
   ```

5. **Calibration synthesis.** For each tension, note the investigators' confidence levels and "what would change this position" conditions from their calibrated committed positions. When two investigators disagree but one is "high confidence" and the other is "low confidence," the draft should weight accordingly. When both name the same "what would change my mind" condition, that's a genuine open question to flag explicitly.

6. **This document is the argumentative spine of the draft.** Every tension you name here must become a visible argumentative beat in the final report — a paragraph or section that engages the disagreement explicitly, not a one-line gesture. If you write `comparisons.md` with 4 tensions and the draft only visibly engages 1, the insight score suffers.

---

## Exit criterion

- `research/comparisons.md` exists
- Contains 3–5 named tensions (or 1 distilled position for single-locus runs)
- Each tension includes: locus references, dynamic description, engagement guidance, calibration note

---

## Next step

Return to the entry skill (`hyperresearch`). Invoke step 7:

```
Skill(skill: "hyperresearch-7-source-tensions")
```
