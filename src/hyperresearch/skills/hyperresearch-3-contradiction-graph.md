---
name: hyperresearch-3-contradiction-graph
description: >
  Step 3 of the hyperresearch V8 pipeline. Builds an explicit graph of opposing
  claims across the corpus. Ranked fight clusters feed step 4's loci
  analysis so that loci emerge from where evidence actually forks, not
  from agent intuition. Also identifies consensus claims (3+ independent
  agreements) for confident assertion in the draft. Invoked via Skill
  tool from the entry skill after step 2 completes.
---

# Step 3 — Contradiction graph

**Tier gate:** SKIP for `light`. Run for `standard` and `full`.

**Goal:** before loci analysis, build an explicit graph of opposing claims. Loci should emerge from where the evidence actually forks, not from agent intuition about what seems interesting.

---

## Recover state

Read these inputs:
- `research/scaffold.md` — vault_tag
- `research/prompt-decomposition.json` — atomic items, pipeline_tier
- All `research/temp/claims-*.json` files (one per fetched note)

If no claims files exist (e.g., fetchers didn't produce them), skip this step entirely — the next step (loci analysis) falls back to corpus prose-scanning.

---

## Procedure

1. **Load all claims** from `research/temp/claims-*.json` files.

2. **Pair contradictions.** For each claim, find claims from OTHER sources that contradict it. Match on:
   - Same `stance_target` with opposing `stance` (supports vs. refutes)
   - Same `entities` with opposite conclusions
   - Same scope but different `numbers` (e.g., "market grew 15%" vs. "market shrank 3%")
   - Overlapping `scope_conditions` but different `evidence_type` pointing different directions

3. **Cluster contradiction pairs into fights.** Group related pairs into clusters — each cluster is one contested question:
   ```json
   {
     "cluster_id": "short-slug",
     "fight": "one-sentence description of what's contested",
     "side_a": {"position": "...", "claims": ["claim-text-1"], "sources": ["note-id-1"]},
     "side_b": {"position": "...", "claims": ["claim-text-1"], "sources": ["note-id-1"]},
     "evidence_quality_delta": "which side has stronger evidence types (empirical > theoretical > anecdotal)",
     "scope_overlap": "genuine disagreement, or scoped differently and both right?",
     "decision_relevance": "high|medium|low — does resolving this matter for the research_query"
   }
   ```

4. **Rank clusters** by decision_relevance (high first), then by evidence_quality_delta (tighter fights rank higher).

5. **Write `research/temp/contradiction-graph.json`** — array of ranked fight clusters.

6. **Identify consensus claims.** Claims where 3+ INDEPENDENT sources (after redundancy audit if step 2.6 ran) agree. Write these to `research/temp/consensus-claims.json`. These are the "settled ground" the draft can assert confidently without hedging.

---

## Exit criterion

- `research/temp/contradiction-graph.json` exists (may be empty array if corpus is univocal)
- `research/temp/consensus-claims.json` exists (may be empty array)

---

## Next step

Return to the entry skill (`hyperresearch`). Tier-based routing:

- **standard tier:** Skip steps 4–8. Invoke `Skill(skill: "hyperresearch-9-evidence-digest")`
- **full tier:** Invoke `Skill(skill: "hyperresearch-4-loci-analysis")`
