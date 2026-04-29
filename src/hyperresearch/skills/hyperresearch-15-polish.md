---
name: hyperresearch-15-polish
description: >
  Step 15 (final) of the hyperresearch V8 pipeline. Spawns the
  hyperresearch-polish-auditor subagent (TOOL-LOCKED to Read + Edit) for
  the final hygiene + readability pass. Strips pipeline-reference leaks,
  YAML frontmatter, scaffold sections, filler phrases, run-on sentences.
  Escalates structural mismatches rather than fabricating content.
  Invoked via Skill tool from the entry skill. Followed by step 16
  (readability audit) which is the actual final step before ship.
---

# Step 15 — Polish audit

**Tier gate:** Runs for ALL tiers. Every report gets a polish pass regardless of tier.

**Goal:** final hygiene + readability pass. Tool-locked to `[Read, Edit]`.

---

## Recover state

Read these inputs:
- `research/notes/final_report.md` — the patched draft from step 14 (or single-pass draft for light tier)
- `research/query-<vault_tag>.md` — canonical research query

---

## Step 15.1 — Pre-create the polish log stub

The polish auditor has `[Read, Edit]` only and cannot create a new file (same tool-lock rule as the step 14 patcher). Stub it first:

```bash
echo '{"applied": [], "escalations": []}' > research/polish-log.json
```

---

## Step 15.2 — Spawn the polish auditor

Spawn ONCE.

**Spawn template:**
```
subagent_type: hyperresearch-polish-auditor
prompt: |
  RESEARCH QUERY (verbatim, gospel):
  > {{paste research/query-<vault_tag>.md body}}

  QUERY FILE: research/query-<vault_tag>.md

  PIPELINE POSITION: You are step 15 (polish auditor) of the
  hyperresearch V8 pipeline — the final step. Step 14 (patcher) applied
  critic findings as Edit hunks. After you return, the orchestrator
  runs the final integrity gate and ships. You are TOOL-LOCKED to
  [Read, Edit].

  YOUR INPUTS:
  - draft_path: research/notes/final_report.md
  - polish_log_path: research/polish-log.json   (already stubbed)
```

The polish auditor strips:
- Pipeline reference leaks (`[[interim-*]]` wikilinks, `[I\d+]` references) — converted to proper citations or deleted depending on `citation_style`
- Hygiene leaks (YAML frontmatter, scaffold sections, prompt echoes)
- Filler phrases ("It is worth noting", "Importantly", etc.)
- Redundant sentences / paragraphs that restate prior content
- Run-on sentences and over-long paragraphs (breaks into smaller units via Edit)

---

## Step 15.3 — Handle escalations

The polish auditor ESCALATES structural mismatches (wrong format for the prompt, missing required sections, etc.) rather than fabricating content to fix them. Read the escalations in the polish log.

If the escalation names a structural issue (e.g., "user asked for a ranked list; draft is unranked prose"), you have one shot to fix it — craft the restructure yourself with hand-written Edits, then ship.

**Sanity-check net length.** Polish should have NEGATIVE net char delta. If the polish log shows positive net chars added, something went wrong — polish is for cutting, not expanding.

**Do not apply polish edits yourself in step 15.2.** The polish auditor's tool lock is the mechanism. Calling Edit directly bypasses the hygiene-check and filler-detection logic baked into the auditor's prompt. If the auditor returned empty, re-spawn it; don't do the work yourself unless step 15.3 escalations require it.

---

## Step 15.4 — Final integrity gate

Before declaring the run complete, verify every expected pipeline artifact exists. **The required set depends on the tier:**

- **light tier:** only `research/polish-log.json` is required (steps 12–14 are skipped, so no critic findings or patch log).
- **full tier:** require all four critic findings + patch-log + polish-log:

```bash
for f in research/critic-findings-dialectic.json \
         research/critic-findings-depth.json \
         research/critic-findings-width.json \
         research/critic-findings-instruction.json \
         research/patch-log.json \
         research/polish-log.json; do
  test -f "$f" || echo "MISSING: $f"
done
```

If any artifact is missing, the responsible step failed silently. Re-spawn the responsible agent ONCE with the missing output path as its explicit required output. If it fails a second time, write a minimal stub (`{"findings":[]}` for critic files, canonical empty-log schema for patch-log.json / polish-log.json) and log the failure in the run log before proceeding.

---

## Step 15.5 — Record the run + lint gate

1. **Record the run.** Append to `research/audit_findings.json`:
   ```json
   {
     "mode": "hyperresearch-v8",
     "run_id": "<iso timestamp>",
     "loci_count": <K>,
     "critical_findings_applied": <int>,
     "critical_findings_skipped": <int>,
     "polish_escalations": <int>,
     "final_word_count": <int>
   }
   ```

2. **Run the lint gate:**
   ```bash
   $HPR lint --rule wrapper-report --json
   $HPR lint --rule locus-coverage --json
   $HPR lint --rule scaffold-prompt --json
   $HPR lint --rule patch-surgery --json
   ```

   If any rule returns `error` severity issues, address them before declaring complete:
   - `wrapper-report`: scaffold leaked into the body — re-spawn the polish auditor with the specific leak flagged
   - `locus-coverage`: a locus identified in step 4 has no interim note — a depth investigator failed silently; do not re-run, just note in the run log
   - `scaffold-prompt`: scaffold's User Prompt section doesn't match the query file exactly — fix the scaffold
   - `patch-surgery`: draft churn from step 11 → final exceeds the safety threshold — read the patch log and investigate

---

## Step 15.6 — Ship

The final report lives at `research/notes/final_report.md`. The wrapper's required save path (if any) is a separate copy — handle per the wrapper contract.

---

## Exit criterion

- `research/polish-log.json` populated
- Final integrity gate passed (or stub-filled with documented failure)
- Lint gate passed
- `research/notes/final_report.md` is the final, shippable artifact

---

---

## Next step

Return to the entry skill (`hyperresearch`). Invoke step 16:

```
Skill(skill: "hyperresearch-16-readability-audit")
```

Step 16 is the final step — readability audit + selective apply. Runs for ALL tiers.
