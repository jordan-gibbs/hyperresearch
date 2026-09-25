---
name: hyperresearch-7-source-tensions
description: >
  Step 7 of the hyperresearch V8 pipeline. Extracts explicit expert
  disagreements from the corpus into research/runs/<vault_tag>/temp/source-tensions.json,
  including orphan tensions that didn't surface as loci. Reads full source
  bodies of top << p.tension_full_reads|hyphen >> sources (not summaries) to find tensions that hide
  in nuance. The Source Tensions section in step 10's draft is the single
  highest-leverage move for insight scores. Invoked via <% if platform == "codex" %>step-file read<% else %>Skill tool<% endif %> from
  the entry skill (full tier only).
---

# Step 7 — Source tension extraction

**Tier gate:** SKIP for `light` tier. Only `full` tier runs this step.

**Goal:** extract explicit expert disagreements from the corpus and comparisons into a structured artifact that step 10 MUST include as a dedicated section. This is the single highest-leverage move for the insight dimension.

**Why this step exists:** step 6's `comparisons.md` captures cross-locus tensions — places where depth investigators disagree. But the richest disagreements often live in the width corpus itself: Source A says X, Source B says Y, and neither the loci analysts nor the depth investigators elevated this as a locus because it cut across multiple topics. These "orphan tensions" are invisible to locus-driven analysis but are exactly what distinguishes an expert synthesis from a competent survey.

---

## Recover state

Read these inputs:
- `research/runs/<vault_tag>/scaffold.md` — vault_tag
- `research/runs/<vault_tag>/comparisons.md` — cross-locus tensions
- `research/runs/<vault_tag>/temp/contradiction-graph.json` (if step 3 ran)
- Survey vault: `{hpr_path} note list --tag <vault_tag> --all -j` for the << p.tension_survey|dash >> highest-quality non-deprecated sources

---

## Procedure

1. **Re-read `comparisons.md`.** Each tension there is already a candidate source tension. Extract: the two positions, the strongest evidence for each, your preliminary reading of which side has the better case.

2. **Scan the width corpus for orphan tensions.** For the << p.tension_survey|dash >> highest-quality non-deprecated sources, then **read the full body** of the top << p.tension_full_reads|dash >> sources most likely to contain disagreements — use `{hpr_path} note show <id1> <id2> ... -j` in batches. **Tensions hide in nuance that summaries flatten:** a source's "however" clause, a footnote caveat, a methodological critique buried in a discussion section. You cannot extract tensions you haven't read. Look for:
   - Sources that explicitly disagree with each other (different conclusions from similar evidence)
   - Sources that use competing theoretical frameworks to explain the same phenomenon
   - Sources where one side cites data the other side ignores
   - Government/institutional positions that conflict with academic findings
   - Industry claims that contradict independent research
   - Historical consensus that recent evidence challenges

3. **If `research/runs/<vault_tag>/temp/contradiction-graph.json` exists**, read it. Any high-relevance fight cluster that was NOT promoted to a locus is a prime orphan-tension candidate. It was important enough for the contradiction graph but wasn't investigated in depth — these deserve standalone treatment in the draft.

4. **Select << p.source_tensions|dash >> source tensions.** Combine comparisons.md tensions with orphan tensions. Rank by:
   - **Decision relevance:** does resolving this tension change the report's recommendation?
   - **Evidence quality:** are both sides grounded in real evidence (not just opinion)?
   - **Reader value:** would an expert reader find this tension illuminating?

   Drop tensions that are: trivially resolved (one side is clearly wrong), definitional (the disagreement is about word meaning, not substance), or orthogonal to the research query.

5. **For each tension, pre-commit to a resolution.** Do NOT leave tensions open. For each:
   - Name it in 5–10 words (e.g., "NHTSA's 'no defect' vs. NTSB's 'design failure'")
   - State Side A's strongest case with evidence (quote or cite specific sources)
   - State Side B's strongest case with evidence
   - Commit to a reading: which side has the better evidence, or is there a synthesis? Name the load-bearing reason.

6. **Write `research/runs/<vault_tag>/temp/source-tensions.json`:**
   ```json
   {
     "tensions": [
       {
         "name": "short descriptive name",
         "side_a": {
           "position": "one-sentence claim",
           "evidence": "strongest evidence with source note ids",
           "proponents": ["source-note-id-1", "source-note-id-2"]
         },
         "side_b": {
           "position": "one-sentence claim",
           "evidence": "strongest evidence with source note ids",
           "proponents": ["source-note-id-3"]
         },
         "resolution": "one-paragraph committed reading with load-bearing reason",
         "origin": "comparisons|contradiction-graph|orphan-scan",
         "decision_relevance": "high|medium"
       }
     ]
   }
   ```

This artifact feeds directly into step 10's mandatory Source Tensions section. Every tension named here becomes a subsection in the final report.

---

## Exit criterion

- `research/runs/<vault_tag>/temp/source-tensions.json` exists with << p.source_tensions|dash >> tensions
- Each tension has both sides with proponents, a committed resolution, and decision_relevance

---

## Next step

Return to the entry skill (`hyperresearch`). Invoke step 8:

```
<% if platform == "codex" %>cat .hyperresearch/codex/steps/hyperresearch-8-corpus-critic.md<% else %>Skill(skill: "hyperresearch-8-corpus-critic")<% endif %>
```
