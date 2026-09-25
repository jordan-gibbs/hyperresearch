---
name: hyperresearch-8-corpus-critic
description: >
  Step 8 of the hyperresearch V8 pipeline. Spawns one corpus-critic subagent
  to identify "what source, if found, would overturn the current
  direction?" gaps, then runs a targeted fetch wave to fill them.
  Highest-leverage intervention point: corrections applied before drafting
  cost nothing; corrections applied after drafting require patches.
  Invoked via <% if platform == "codex" %>step-file read<% else %>Skill tool<% endif %> from the entry skill (full tier only).
---

# Step 8 — Pre-draft corpus critic (targeted gap-fill)

**Tier gate:** `full` tier ONLY. Skip for `light`.

**Goal:** before drafting, ask "what source, if found, would overturn the current direction?" and run a targeted fetch wave to fill the most dangerous gaps. This is the highest-leverage intervention point in the pipeline — corrections applied before drafting cost nothing; corrections applied after drafting require patches and risk structural drift.

---

## Recover state

Read these inputs:
- `research/runs/<vault_tag>/scaffold.md` — vault_tag
- `research/runs/<vault_tag>/comparisons.md` — cross-locus tensions
- `research/runs/<vault_tag>/loci.json` — scored loci
- `research/runs/<vault_tag>/temp/source-tensions.json` — expert disagreements
- `research/runs/<vault_tag>/prompt-decomposition.json` — specifically the `time_periods` array

---

## Pre-flight: period-pinned primary-source coverage check

**Run this BEFORE spawning the corpus-critic subagent.** If `prompt-decomposition.json -> time_periods` is non-empty, walk every entry and verify the vault contains a primary source filed *for that exact period* — not "most recent", not narrative commentary, not earnings-call transcripts standing in for tabular filings.

For each `time_period` entry:

1. Search the vault for a primary source matching the `primary_source` description and the `issuer`:
   ```bash
   PYTHONIOENCODING=utf-8 {hpr_path} search "<period> <issuer>" --tag <vault_tag> --include-body -j
   ```
2. Open the candidate notes (`note show <id> -j`) and verify the document's actual reporting period — the filing must cover the SPECIFIC period named in the prompt, not an adjacent one. A Q1 2025 10-Q does NOT satisfy "Q3 2024" — different period, different tabular data.
3. **If the period-pinned filing is missing, add it to `research/runs/<vault_tag>/temp/period-pinned-gaps.json` (`{"gaps": [...]}`) as a `priority: critical` gap of type `period-pinned-primary` BEFORE spawning the corpus-critic subagent.** This is the orchestrator's OWN file — the subagent writes elsewhere (below) and the two are merged in Procedure step 2, so nothing here gets overwritten. Number the ids `pp-1`, `pp-2`, ... Schema:
   ```json
   {{
     "id": "pp-1",
     "type": "period-pinned-primary",
     "target_position": "<period> exact figures for <issuer>",
     "search_queries": [
       "site:sec.gov 10-Q \"period ended September 30, 2024\" <issuer>",
       "<issuer> Q3 2024 10-Q filing PDF"
     ],
     "source_type": "primary-filing",
     "priority": "critical",
     "rationale": "Prompt names <period>; vault has no filing covering that exact period. Tabular line items only exist in the period-pinned filing. Without it, the draft will paraphrase rounded numbers from earnings calls and miss the rubric's exact figures."
   }}
   ```

The targeted fetch wave in the next step will pull these filings BEFORE the corpus-critic finishes its broader gap analysis. This ordering matters: numerical-precision misses are the largest single category of avoidable factual-accuracy failures.

---

## Procedure

1. **Spawn ONE `hyperresearch-corpus-critic` subagent**<% if platform == "codex" %> (custom agent `.codex/agents/hyperresearch-corpus-critic.toml`) and wait for it to finish<% else %><% endif %>.

   **Spawn template:**
   ```
   <% if platform == "codex" %>custom_agent: hyperresearch-corpus-critic   # spawn the custom agent defined in .codex/agents/hyperresearch-corpus-critic.toml<% else %>subagent_type: hyperresearch-corpus-critic<% endif %>
   prompt: |
     RESEARCH QUERY (verbatim, gospel):
     > {{paste research/runs/<vault_tag>/query.md body}}

     QUERY FILE: research/runs/<vault_tag>/query.md

     PIPELINE POSITION: You are step 8 of the hyperresearch V8 pipeline.
     Step 6 produced research/runs/<vault_tag>/comparisons.md. After you return, the
     orchestrator runs a targeted fetch wave, then step 10 drafts.

     YOUR INPUTS:
     - corpus_tag: <vault_tag>
     - comparisons_path: research/runs/<vault_tag>/comparisons.md
     - loci_path: research/runs/<vault_tag>/loci.json
     - output_path: research/runs/<vault_tag>/temp/corpus-critic-gaps-raw.json

     RUN DIRECTIVES: append the FULL contents of research/runs/<vault_tag>/shims/research.md here, verbatim.
   ```

2. **Merge into the step artifact.** Read the subagent's output (`research/runs/<vault_tag>/temp/corpus-critic-gaps-raw.json`; each gap carries an `id` like `cc-1`, a `priority` of critical / high, and a `type` of overturning / strengthening / independent-verification). Write `research/runs/<vault_tag>/corpus-critic-gaps.json` as `{"gaps": [...]}` containing the pre-flight `period-pinned-gaps.json` entries FIRST (they are the critical, period-pinned ones), then the subagent's gaps. Every gap keeps its `id` — the `pp-` / `cc-` prefixes keep the two sets from colliding, and the fetch wave below references gaps by id. If there was no pre-flight file, the merged file is just the subagent's gaps.

3. **Targeted fetch wave.** Spawn **<< p.corpus_critic_fetchers|dash >> fetcher subagents** to search for and fetch the sources identified in the gaps<% if platform == "codex" %> (custom agent `.codex/agents/hyperresearch-fetcher.toml` — spawn them in parallel and wait for all of them)<% else %><% endif %>.

   **Spawn template:**
   ```
   <% if platform == "codex" %>custom_agent: hyperresearch-fetcher   # spawn the custom agent defined in .codex/agents/hyperresearch-fetcher.toml<% else %>subagent_type: hyperresearch-fetcher<% endif %>
   prompt: |
     RESEARCH QUERY (verbatim, gospel):
     > {{paste research/runs/<vault_tag>/query.md body}}

     QUERY FILE: research/runs/<vault_tag>/query.md

     PIPELINE POSITION: You are a step 8 fetcher (corpus-critic gap-fill)
     of the hyperresearch V8 pipeline. The corpus critic identified specific
     gaps; you fetch sources targeting those gaps. After you return, the
     orchestrator updates comparisons.md based on what you found.

     YOUR INPUTS:
     - vault_tag: <vault_tag>
     - search_queries: [<gap.search_queries>]
     - source_type: <gap.source_type>
     - gap_id: <gap.id>

     RUN DIRECTIVES: append the FULL contents of research/runs/<vault_tag>/shims/research.md here, verbatim.
   ```

4. **Assess results.**
   - **Overturning source found:** re-read the relevant committed position from the interim note. If the new source genuinely undercuts it, update `research/runs/<vault_tag>/comparisons.md` to note the weakened position — the draft will handle it with appropriate calibration. Do NOT re-run the full depth investigation; adjust the position's confidence level.
   - **Overturning source NOT found:** the committed position gains confidence. Note this in `comparisons.md` — "adversarial search for counter-evidence to [position] returned no substantive challenges."
   - **Strengthening/verification source found:** note the additional support in `comparisons.md`. The draft can assert more confidently.

5. **Log results** to `research/runs/<vault_tag>/temp/corpus-critic-results.md`:
   - Each gap: what was searched, what was found (or not), how it affects the committed positions
   - Updated confidence levels for any positions that changed

---

## Exit criterion

- `research/runs/<vault_tag>/corpus-critic-gaps.json` exists (the merged file — pre-flight period-pinned gaps plus the subagent's, every gap with an `id`)
- All critical gaps attempted (fetched or documented as unfindable)
- `research/runs/<vault_tag>/temp/corpus-critic-results.md` exists
- `research/runs/<vault_tag>/comparisons.md` updated with confidence/strengthening/overturning notes

---

## Next step

Return to the entry skill (`hyperresearch`). Invoke step 9:

```
<% if platform == "codex" %>cat .hyperresearch/codex/steps/hyperresearch-9-evidence-digest.md<% else %>Skill(skill: "hyperresearch-9-evidence-digest")<% endif %>
```
