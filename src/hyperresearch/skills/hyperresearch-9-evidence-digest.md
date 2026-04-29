---
name: hyperresearch-9-evidence-digest
description: >
  Step 9 of the hyperresearch V8 pipeline. Assembles the top load-bearing
  claims and verbatim quotes from the claims JSONs into
  research/temp/evidence-digest.md — a single high-fidelity evidence
  index the draft sub-orchestrators read as primary evidence (higher
  fidelity than fetcher summaries). Invoked via Skill tool from the
  entry skill (standard / full tiers).
---

# Step 9 — Evidence digest

**Tier gate:** Run for `standard` and `full`. Skip for `light`.

**Goal:** assemble the top load-bearing claims and verbatim quotes from the claims JSONs into a single digest file the drafter reads as primary evidence — higher-fidelity than fetcher summaries.

---

## Recover state

Read these inputs:
- `research/scaffold.md` — vault_tag
- `research/prompt-decomposition.json` — atomic items, response_format, pipeline_tier
- All `research/temp/claims-*.json` files
- `research/temp/consensus-claims.json` (if step 3 ran)
- `research/temp/contradiction-graph.json` (if step 3 ran)

---

## Procedure

1. **Read all claims files** from `research/temp/claims-*.json` for every non-deprecated note tagged with the vault tag. If no claim files exist (e.g., fetchers didn't produce them), skip this step.

2. **Filter and rank.** Keep claims where `confidence` is `"high"` OR `evidence_type` is `"empirical"` or `"statistical"`. From the remainder, prefer claims with non-empty `numbers` arrays and non-empty `quoted_support`. Cap at:
   - **80–120 claims total** for `full` tier
   - **40–60 claims** for `standard` tier

3. **Group by atomic item.** Match each surviving claim to the atomic item it is most relevant to based on **topic overlap** — do not rely on exact field matching. A claim about "United Health Group regulatory exposure" serves the atomic item "UNH risk factors" even though no field matches exactly. Use the claim's `entities`, `stance_target`, `scope_conditions`, and `claim` text holistically to judge relevance. When uncertain, include the claim under the most relevant item rather than dropping it to Ungrouped. Claims that genuinely don't map to any atomic item go into an "Ungrouped" section at the end.

4. **Include consensus and contested claims.**
   - If `research/temp/consensus-claims.json` exists, include its claims marked as `[consensus]`.
   - If `research/temp/contradiction-graph.json` exists, include the top 3–5 contested claim pairs with both sides' `quoted_support` passages.

5. **Write `research/temp/evidence-digest.md`.** Format: one H3 per atomic item, bullet list of claims. Each bullet includes:
   - The `claim` text
   - The `quoted_support` verbatim passage (block-quoted)
   - The `source_note_id`

   Keep it scannable — this is an evidence index, not a narrative.

   Example:
   ```markdown
   ### Atomic item: Market growth in Southeast Asia

   - Annual growth rate of 12.4% in 2024 (empirical)
     > "Southeast Asian e-commerce GMV grew from $89B to $100B between 2023 and 2024, a 12.4% YoY expansion."
     [source-note-12]

   - Vietnam led by penetration rate (statistical)
     > "Vietnam reached 64% e-commerce penetration in 2024, the highest in SEA, surpassing Singapore (61%)."
     [source-note-19]
   ```

---

## Exit criterion

- `research/temp/evidence-digest.md` exists
- Contains at least:
  - 30 claims for `full` tier
  - 15 claims for `standard` tier
- Grouped by atomic item with verbatim quoted_support and source_note_id

If fewer claims exist in total, include all of them.

---

## Next step

Return to the entry skill (`hyperresearch`). Invoke step 10:

```
Skill(skill: "hyperresearch-10-triple-draft")
```

Step 10 is the most important step in the pipeline. Re-read the entry skill before invoking if needed — the triple-draft ensemble must spawn 3 draft-orchestrators for `standard` and `full` tiers.
