---
name: hyperresearch-13-gap-fetch
description: >
  Step 13 of the hyperresearch V8 pipeline. Conditional fetcher wave to fill
  vault gaps that critics identified. If a critic says "the draft ignored
  topic X" and the vault has zero sources on X, the patcher has nothing
  to cite. This step fetches the missing sources BEFORE patching so the
  patcher has ammunition. Capped at 5 gaps. Invoked via Skill tool from
  the entry skill (standard / full tiers).
---

# Step 13 — Post-critic gap fetch (conditional)

**Tier gate:** Run for `standard` and `full`. Skip for `light` (no critics = no findings).

**Goal:** critics identify gaps the draft missed, but the patcher can only work with evidence already in the vault. If a critic says "the draft ignored topic X" and the vault has zero sources on X, the patcher has nothing to cite. This step fills those gaps BEFORE patching.

---

## Recover state

Read these inputs:
- `research/scaffold.md` — vault_tag
- All `research/critic-findings-*.json` files (which exist depends on tier)

---

## Procedure

1. **Read whichever critic findings files exist.** Scan for findings where:
   - `failure_mode` is `"missing"`, `"under-covered"`, or `"missing-forward-analysis"`
   - `failure_mode` is any width-critic finding (these are coverage gaps by definition)
   - `severity` is `major` or `critical`

2. **For each qualifying finding, check whether the vault has evidence.** Run a targeted vault search for the topic the finding names:
   ```bash
   $HPR search "<finding topic keywords>" --tag <vault_tag> --json
   ```
   If 2+ relevant notes exist, the patcher can handle it — move on. If 0-1 relevant notes exist, this is a **fetch-worthy gap**.

3. **Collect fetch-worthy gaps.** Cap at **5 gaps maximum** — this is a surgical fill, not a second width sweep. Prioritize by severity (critical first) then by how many critic findings the gap would resolve.

   If 0 fetch-worthy gaps: log "no gaps to fill" and proceed directly to step 14.

4. **Run targeted fetch wave.** For each gap, generate 2-3 search queries and collect URLs. Spawn **2-4 fetchers** with the gap-filling URLs.

   **Spawn template:**
   ```
   subagent_type: hyperresearch-fetcher
   prompt: |
     RESEARCH QUERY (verbatim, gospel):
     > {{paste research/query-<vault_tag>.md body}}

     QUERY FILE: research/query-<vault_tag>.md

     PIPELINE POSITION: You are a step 13 (post-critic gap-fill) fetcher
     of the hyperresearch V8 pipeline. Critics identified gaps in vault
     coverage; you fetch sources targeting those gaps. After you return,
     the patcher (step 14) cites your sources to address findings.

     YOUR INPUTS:
     - vault_tag: <vault_tag>
     - urls: [<gap-targeted URLs>]
     - extra_tags: ["post-critic-fill"]
   ```

   Each fetcher: fetches, quality-checks, summarizes, extracts claims (same procedure as step 2). Tags notes with `vault_tag` + `post-critic-fill`. Writes claims to `research/temp/claims-<note-id>.json`.

5. **Update evidence digest.** If new claims were extracted, append them to `research/temp/evidence-digest.md` under a new `### Post-critic gap fill` section. The patcher reads the evidence digest when looking for citation sources to insert.

6. **Log results** to `research/temp/post-critic-fetch-log.md`:
   - Each gap: what was searched, how many new sources found, note IDs
   - If a gap remained unfilled after fetching: flag it so the patcher knows to acknowledge the limitation rather than fabricate

---

## Exit criterion

- `research/temp/post-critic-fetch-log.md` exists (even if it says "no gaps found")
- All fetch-worthy gaps attempted (proceed to step 14 whether or not all gaps were filled — unfilled gaps are noted in the log)

**Cost:** +$1-3 per run (2-4 Sonnet fetchers). Most runs with good step 2 coverage will find 0-2 gaps, making this a near-no-op.

---

## Next step

Return to the entry skill (`hyperresearch`). Invoke step 14:

```
Skill(skill: "hyperresearch-14-patcher")
```
