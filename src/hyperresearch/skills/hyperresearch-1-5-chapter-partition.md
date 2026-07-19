---
name: hyperresearch-1-5-chapter-partition
description: >
  Step 1.5 of the hyperresearch V8 pipeline — CHAPTERED PROFILES ONLY
  (dissertation). Partitions the decomposed query into 4-10 topically
  cohesive chapters, writes the chapter plan, and registers chapters in the
  run manifest. Steps 2-10 then loop per chapter, each staying within the
  proven per-chapter source envelope; global reconciliation and synthesis
  integrate across chapters. Skipped entirely when the profile's `chapters`
  is (0, 0). Invoked via Skill tool from the entry skill.
---

# Step 1.5 — Chapter partition (chaptered profiles only)

**Profile gate:** Runs ONLY when the resolved profile's `chapters` range is non-zero (e.g. `dissertation` = << dissertation.chapters|dash >> chapters). For `light` and `full`, this step does not exist — skip directly to step 2.

**Why chapters:** no single agent can hold a << dissertation.source_target|dash >>-source corpus. Chapters make the proven << dissertation.chapter_source_target|dash >>-source pipeline the *unit of execution*: each chapter runs its own width sweep through drafting, and global layers integrate on top. The ~80-source quality ceiling is per-chapter, not per-run.

---

## Recover state

Read these inputs:
- `research/runs/<vault_tag>/scaffold.md` — run config
- `research/runs/<vault_tag>/prompt-decomposition.json` — atomic items, required_section_headings
- `research/runs/<vault_tag>/query.md` — canonical query

---

## Procedure

1. **Decide chapter count.** Group the decomposition's atomic items into << dissertation.chapters|dash >> topically cohesive chapters. Rules:
   - Every atomic item lands in exactly ONE chapter (cross-cutting items go to the chapter that will treat them most deeply; other chapters reference, not re-research).
   - A chapter is a *research unit*: it must be answerable with << dissertation.chapter_source_target|dash >> sources. If a candidate chapter obviously needs more, split it.
   - When `required_section_headings` already implies a chapter structure (the prompt asked for named parts), FOLLOW IT — chapters must map 1:1 onto required top-level headings when they exist.
   - Fewer than ~12 atomic items → the query doesn't need chaptering; record 1 chapter and note the pipeline degenerates to the flat `full` shape.

2. **Write the chapter plan** to `research/runs/<vault_tag>/chapter-plan.json`:
   ```json
   {
     "chapters": [
       {
         "id": "ch1",
         "title": "<chapter title — becomes the H1 in the final document>",
         "atomic_items": ["<verbatim items from the decomposition>"],
         "rationale": "<1-2 sentences: why these items cohere>",
         "depends_on": []
       }
     ]
   }
   ```
   `depends_on` lists chapters whose findings this chapter builds on (usually empty; used to order execution).

3. **Scaffold chapter workspaces.** For each chapter, create `research/runs/<vault_tag>/chapters/<id>/` with an empty `temp/` subdirectory. Chapter-scoped step artifacts (loci.json, comparisons.md, claims, drafts) live there; the flat run-root copies are NOT used on chaptered runs.

4. **Register chapters in the manifest:**
   ```bash
   $HPR run step <vault_tag> 1.5 --status done -j
   ```
   and for each chapter:
   ```bash
   $HPR run event <vault_tag> --type chapter-plan --data '{"chapter": "<id>", "title": "<title>"}' -j
   ```

5. **Chapter tagging convention.** Every note fetched or written for a chapter carries BOTH tags: `<vault_tag>` and `<vault_tag>-<id>` (e.g. `china-rail-x9f2a1-ch3`). Whole-run queries use the first; per-chapter queries use the second. Cross-chapter source reuse is free — dedup is by URL, and a chapter's coverage check searches the whole `<vault_tag>` corpus before fetching.

---

## Chapter execution loop (what the orchestrator does next)

For each chapter (respecting `depends_on`, up to << dissertation.chapter_concurrency >> chapters in flight):

1. Invoke steps 2 → 10 with the chapter as scope:
   - The "research query" for chapter-scoped subagent spawns is the verbatim canonical query PLUS a chapter assignment block naming the chapter's title and atomic items.
   - Artifact paths swap `research/runs/<vault_tag>/` for `research/runs/<vault_tag>/chapters/<id>/` (each chapter has its own loci.json, comparisons.md, temp/).
   - Source targets come from `chapter_source_target`, not the global `source_target`.
   - Step 10 writes ONE draft per chapter to `research/runs/<vault_tag>/chapters/<id>/draft.md` (draft_count is 1 for chaptered profiles — angle diversity comes from the chapters themselves).
2. Record progress: `$HPR run step <vault_tag> <N> --status done --chapter <id> -j` after each chapter-step completes.
3. After ALL chapters finish step 10, proceed to the global layers: step 6 re-runs GLOBALLY (cross-CHAPTER tensions from the chapters' comparisons.md files → `research/runs/<vault_tag>/comparisons.md`), then step 11 synthesizes the chapter drafts into the final document (chapter titles become H1s), then steps 12-16 run once against the whole document.

**Budget check at every chapter boundary:** `$HPR run status <vault_tag> -j`. If `status` is `blocked` with `blocked_on: "budget"`, STOP spawning and surface to the user. Never silently skip profile-mandated steps — shrink the NEXT chapter's fan-out (fewer wave-2 fetchers, lower depth budgets) when `budget_remaining_usd` is under ~30% instead.

---

## Exit criterion

- `research/runs/<vault_tag>/chapter-plan.json` exists with every atomic item assigned to exactly one chapter
- Chapter workspaces exist under `research/runs/<vault_tag>/chapters/`
- Manifest step 1.5 marked done, chapters registered

## Next step

Return to the entry skill and begin the chapter execution loop at step 2 for the first chapter(s): `Skill(skill: "hyperresearch-2-width-sweep")`.
