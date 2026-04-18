---
name: research-layercake
description: >
  Deep research via the LAYERCAKE architecture — a 7-phase pipeline:
  prompt decomposition → width sweep → loci analysis → depth
  investigation → draft → four adversarial critics in parallel
  (dialectic / depth / width / instruction) → surgical patch pass →
  polish audit.
  The patcher and polish auditor are TOOL-LOCKED to Read + Edit: they
  cannot regenerate the draft, only apply surgical hunks. Invoke with
  /research-layercake.
---

# Layercake — the default multi-agent research protocol

This is the orchestrator. You are running it as Opus. The pipeline spawns specialized subagents in every layer; you do not do their work yourself. You coordinate, assemble evidence, write ONE draft, and ship.

**Two canonical rules:**

1. **PATCH, NEVER REGENERATE.** After the first draft is written (Layer 4), the draft is only ever modified by Edit hunks produced by the patcher (Layer 6) and the polish auditor (Layer 7). Both subagents are tool-locked to `[Read, Edit]`. Neither can Write a new draft. If a critic's finding would require rewriting a whole section, it escalates to you as a structural issue — not a rewrite. Keep hunks surgical: change as little as possible while addressing the issue.

2. **ARGUE, DON'T JUST REPORT.** The layercake pipeline is engineered to push the final report toward argumentative density. Loci analysts must flag at least one dialectical locus (where sources disagree). Depth investigators must commit to a position at the end of every interim note — not just summarize. Layer 3.5 forces you to reconcile those positions in `comparisons.md` before drafting. Layer 4 requires every body section that touches a cross-locus tension to engage it explicitly. A descriptive "survey" draft is a pipeline failure, not a neutral output.

---

## Subagent spawn contract (applies to every Task call you make)

Every subagent in the pipeline needs context about **what they're for, where they sit in the pipeline, and what the user actually asked**. When you spawn ANY subagent via the Task tool, the prompt you pass must include the following three pieces — in this order, near the top:

1. **`research_query` — verbatim, block-quoted.** The canonical user question. If `research/prompt.txt` exists, that file's content IS the research_query. Do not paraphrase, do not summarize, do not "clean up" — paste it character-for-character. This is every subagent's north star; an agent without the research_query in its prompt is guaranteed to drift off the user's ask.

2. **Pipeline position statement.** One sentence naming what layer the subagent is running in, what came before, what comes after. Example: *"You are Layer 3 (depth investigator) of the layercake pipeline. Layer 2's loci analysts produced `research/loci.json`; after you return, Layer 3.5 will reconcile your committed position against the other investigators'."* This prevents subagents from doing adjacent layers' work (e.g., patchers trying to regenerate, critics trying to fix).

3. **The subagent's specific inputs.** What the subagent prompt documents as its required fields (vault_tag, output_path, locus, etc.). These vary per subagent — see each agent's description for its schema.

Skipping any of these three in a Task prompt is a process violation. A fetcher that doesn't see the research_query fetches URLs without context for why; a critic that doesn't see the pipeline position may patch the draft directly (it shouldn't); a patcher that doesn't see the research_query applies findings without the north-star check.

Concrete Task-call template:

```
subagent_type: hyperresearch-<agent-name>
prompt: |
  RESEARCH QUERY (verbatim, gospel):
  > {{paste contents of research/prompt.txt OR user's literal prompt here, character-for-character}}

  PIPELINE POSITION: You are Layer N of the 7-phase layercake pipeline.
  Prior layers: {{list what's already run and what artifacts they produced}}.
  After you: {{list what comes next and what it expects from your output}}.

  YOUR INPUTS:
  - <input_1>: <value>
  - <input_2>: <value>
  - ...

  {{Any agent-specific guidance beyond what's already in the agent's
  own prompt file.}}
```

This contract applies to ALL subagent Task calls — fetchers included. A fetcher that knows the research_query can make smarter quality calls ("is this URL relevant to *this* question?") than one fetching blind.

---

## Inputs and setup

**Canonical research query.** Resolve the same way the single-pass `/research` skill does:

- If `research/prompt.txt` exists, read it. Its contents are the canonical research query. GOSPEL.
- Otherwise, use the user's verbatim prompt as the canonical research query.
- Extract wrapper requirements separately: required save path, citation format, terminal-section shape, wrapper contract. These are binding but NOT part of the query.
- If `research/wrapper_contract.json` exists, read it — it encodes forbidden body sections and required terminal sections for the ambient wrapper.

**Vault tag.** Generate a short slug from the canonical query. Every note created during this run gets this tag so you can scope searches later.

**Modality.** Classify the query by cognitive activity the same way `/research` does: collect / synthesize / compare / forecast. The modality file lives at `.claude/skills/hyperresearch/SKILL-<modality>.md`. You will read it before writing the Layer 4 draft.

Write all of this to `research/scaffold.md` before Layer 1 starts. Use the same scaffold template the single-pass skill uses (see `.claude/skills/hyperresearch/SKILL.md` Step 7). The scaffold is your private planning document — it MUST NOT appear anywhere in the final report.

---

## Layer 0.5 — Prompt decomposition

**Goal:** before any research happens, decompose the user's prompt into its atomic items. This artifact is read by the instruction-critic in Layer 5 and by the final draft in Layer 4 to make sure the pipeline doesn't drift from what was actually asked.

**Why this layer exists:** the single dimension where the pipeline has the widest variance is whether the draft structurally mirrors the prompt. When the prompt asks for "for each significant character, describe techniques / arcs / fate" and the draft produces per-character sections with those three fields in order — that's a structural match, high instruction-following. When the prompt asks the same thing and the draft organizes around thematic analysis with characters mentioned as illustrations — that's a structural mismatch, even if every fact is in there. The decomposition makes the structural requirement explicit, in writing, BEFORE drafting.

### Procedure

1. Re-read the canonical research_query end to end.
2. Walk through it and extract every atomic item — anything that's a discrete thing the prompt named. These fall into categories:
   - **Sub-questions** — explicit or implicit questions the draft must answer ("What cues influence this?" → atomic: "cues influencing X")
   - **Named entities / categories** — every character, product, company, concept, time period, etc. the prompt names by name
   - **Required formats** — "mind map", "ranked list", "FAQ", "tabular", "scenario matrix", etc.
   - **Required sections** — "include X section", "end with Y", "begin with Z"
   - **Time horizons** — "through 2027", "next 12 months", "historical through 2010-present"
   - **Scope conditions** — "for non-academic contexts", "under SIL-4 constraints"
3. Write `research/prompt-decomposition.json`:

```json
{
  "sub_questions": [
    "What is the specific question this addresses?",
    "..."
  ],
  "entities": [
    {"name": "Bronze Saints", "type": "category", "required_fields": ["techniques", "arcs", "fate"]},
    ...
  ],
  "required_formats": [
    "mind map of causal structure",
    "5-tier support/resistance table"
  ],
  "required_sections": [
    "## Opinionated Synthesis (if wrapper_contract demands it)"
  ],
  "time_horizons": ["2010-present", "12-month forward"],
  "scope_conditions": ["urban rail specifically, not mainline"]
}
```

4. Every atomic item you put here becomes a draft requirement in Layer 4 and a critic-verifiable check in Layer 5. If you leave an atomic item out of the decomposition, the instruction-critic won't catch it. Be thorough — inflation (including items the prompt didn't actually name) is worse than omission, because the critic will then demand content the user didn't ask for.

5. **Do NOT include wrapper-contract requirements here** — those live in `research/wrapper_contract.json` separately. The decomposition is ONLY about what the user's actual prompt named.

**Exit criterion:** `research/prompt-decomposition.json` exists, is valid JSON, and every atomic item in it can be pointed at a specific passage of the research_query.

---

## Layer 1 — Width sweep

**Goal:** cover the topical corners of the query with 30–80 curated sources before any depth investigation starts.

1. **Academic APIs first.** For topics with a research literature, hit Semantic Scholar / arXiv / OpenAlex / PubMed BEFORE web search. Academic APIs return citation-ranked canonical papers; web search returns derivative commentary.

2. **Plan the URL queue.** Aim for at least 30 URLs spanning:
   - Top-cited canonical sources on the core topic
   - Recent (last 2 years) developments
   - At least one adversarial angle ("criticism of X", "limitations of Y")
   - Obviously off-center corners (related subfields the query brushes against)

3. **Parallel fetcher batches.** Spawn `hyperresearch-fetcher` subagents via the Task tool with URL lists. Batch sizes of 4–8 URLs per fetcher. Spawn multiple fetchers in a single message when they're independent — that's parallel execution.

4. **Fetcher must tag every new note** with your `<vault_tag>`. Seed fetches (URLs you found directly from search, not from another note) omit `--suggested-by` entirely. Do NOT invent breadcrumb tokens like `layercake-seed` — placeholder breadcrumbs are a process violation.

5. **Curation happens inline.** The fetcher already deprecates junk and writes summaries. You monitor: if >30% of fetches come back as junk, the URL queue was bad — reassess before continuing.

**Exit criterion for Layer 1:** at least 20 substantive (non-deprecated) notes in the vault tagged with `<vault_tag>`. If you fall short after two fetcher rounds, tell the user the topic is under-resourced and proceed anyway; the loci analysts will flag the shortfall.

---

## Layer 2 — Loci analysis (parallel, 2 analysts)

**Goal:** identify 1–6 specific questions where depth investigation will pay off.

1. **Spawn 2 `hyperresearch-loci-analyst` subagents in parallel.** Both read the same width corpus but return independently. Pass each:
   - `research_query` — canonical, verbatim
   - `corpus_tag` — `<vault_tag>`
   - `analyst_id` — `a` for one, `b` for the other
   - `output_path` — `research/loci-a.json` and `research/loci-b.json`

2. **Wait for both.** If one fails, proceed with the single successful output. If both fail (empty loci lists), tell the user the width sweep was too thin and stop — do not force depth on a weak corpus.

3. **Deduplicate and clamp to 6.**
   - Read both JSON outputs.
   - Dedupe on `name` (exact match) or near-match (same core question, different phrasing). When in doubt, prefer the entry with stronger `corpus_evidence`.
   - If the deduped list exceeds 6, drop the weakest entries — rank by how load-bearing the rationale is for the canonical research query.
   - The deduped, clamped list is authoritative. Write it to `research/loci.json`.
   - **Persist both analysts' `skip_loci` arrays** in the same file — union them under a top-level `skip_loci` key. These justifications matter downstream: the `locus-coverage` lint rule can cross-reference them when an interim note is "missing" to distinguish real investigator failure from legitimate skip. Schema: `{"loci": [...deduped-clamped...], "skip_loci": [...union from both analysts...]}`.

4. **Decide investigator count.** You spawn ONE depth-investigator per locus, capped at 6. If only 1 locus passes dedupe, spawn 1. The cap is a cost control — depth investigators can each fetch up to 10 new sources, and 6 × 10 = 60 new sources on top of the width corpus is already a lot.

**Placeholder-breadcrumb ban reminder:** depth investigators will fetch sources; make sure your instructions to them match what the fetcher will accept. Do not hand them breadcrumb placeholders like `layercake-locus-seed` — use real source note ids from the vault or omit `--suggested-by` entirely.

---

## Layer 3 — Depth investigation (parallel, K = len(loci))

**Goal:** produce ONE `interim-{locus}.md` note per locus with dense synthesis that the orchestrator will draft from in Layer 4.

1. **Spawn K `hyperresearch-depth-investigator` subagents in parallel.** Pass each:
   - `locus` — the full locus object from `research/loci.json`
   - `research_query` — canonical, verbatim
   - `corpus_tag` — `<vault_tag>`

2. **Each investigator writes ONE interim note** into the vault with `type: interim` and tags `<vault_tag>` + `locus-<locus-name>`. Return value is the note id.

3. **Wait for all K to complete.** Investigators can fail independently. Proceed with whichever succeeded. If >50% failed, reassess — the loci analyst may have produced un-investigatable questions.

4. **Read the interim notes.** Before writing the draft, use `$HPR search "" --tag <vault_tag> --type interim --json` to list them, then `$HPR note show <id1> <id2> ... -j` to read them in one call. Hold the Committed Position sections in your context — they are the load-bearing input to Layer 3.5 and Layer 4.

---

## Layer 3.5 — Cross-locus comparisons (orchestrator, bridge step)

**Goal:** before drafting, reconcile the committed positions from all depth investigators. Produce `research/comparisons.md` — a short document naming 3–5 places where the loci conflict or complicate each other. This is the structural step that gives the single draft the argumentative density the old ensemble got from compiling three independent drafts.

**Why this step exists:** the depth investigators each committed to a position on their own locus. Some of those positions will disagree with each other, some will reinforce each other, some will partially complicate each other. The draft must engage those cross-locus dynamics explicitly — not summarize each locus in isolation. Writing `comparisons.md` forces you (the orchestrator) to see the loci in cross-section before you open the draft.

**This step is always-on.** Even single-locus runs produce `comparisons.md` — with that locus's committed position as the lone argumentative anchor the draft must engage. The document is different (one position distilled vs. 3–5 tensions reconciled) but the discipline of writing it down BEFORE drafting is the same, and the lint rules expect the file to exist whenever Layer 2 wrote `research/loci.json`.

### Procedure

1. **Lay out all committed positions.** For each interim note, read its `## Committed position` section. Write them down side-by-side in a scratch list.

2. **Hunt for tensions.** Ask of every pair of positions:
   - Do they agree on the facts but disagree on what the facts mean?
   - Do they cite different evidence and reach opposite conclusions?
   - Does one locus's position assume something another locus's evidence complicates?
   - Is one locus's position a special case of another's general claim?
   - Do they converge on a conclusion but via different mechanisms (worth noting — convergence from independent paths is itself a finding)?

3. **Pick the 3–5 strongest cross-locus dynamics.** Reject weak ones (loci that are simply orthogonal, or that restate each other). You want cross-locus relationships that a good final draft should actually wrestle with — not every possible pair.

4. **Write `research/comparisons.md`:**

```markdown
# Cross-locus comparisons

## Tension 1: <short name for the dynamic>

- **Locus A** ([[interim-A]]) commits: <one-line committed position>
- **Locus B** ([[interim-B]]) commits: <one-line committed position>
- **The cross-locus dynamic:** <2–3 sentences naming exactly how they relate — conflict? convergence? complication? special case? Name the load-bearing disagreement or the load-bearing agreement.>
- **How the draft should engage this:** <one sentence. Example: "Section on X must acknowledge that Y from Locus B undercuts the simple reading of Locus A" or "The recommendation should privilege Locus B's position because its evidence base is stronger on the point where they disagree.">

## Tension 2: ...
```

5. **This document is the argumentative spine of your draft.** Every tension you name here must become a visible argumentative beat in the final report — a paragraph or section that engages the disagreement explicitly, not a one-line gesture. If you write `comparisons.md` with 4 tensions and the draft only visibly engages 1 of them, the insight score suffers.

---

## Layer 4 — Draft (orchestrator, single pass)

**Goal:** write ONE draft that weaves the width corpus with the depth interim notes AND engages the cross-locus tensions from `research/comparisons.md` AND mirrors the atomic items from `research/prompt-decomposition.json`, following the modality file's substance rules.

1. **Re-read `research/prompt-decomposition.json`.** Every atomic item named there is a draft requirement. For each sub-question, the draft must answer it. For each named entity, the draft must address it (in a dedicated section, subsection, or paragraph, as the decomposition's structure implies). For each required format, the draft must honor it. You are mirroring the user's structure, not reorganizing the topic around your own analytical axes.

2. **Re-read `research/comparisons.md`.** The tensions there are your argumentative spine. Keep the document open in your working context while drafting.

3. **Read your modality file now.** Open `.claude/skills/hyperresearch/SKILL-<modality>.md` and apply its substance rules. Pay particular attention to the modality's insight-generation rules — these are the rules that push you from reporting evidence to interpreting it.

4. **Read SKILL.md's Step 9 (draft conventions).** The dispatcher's drafting rules (citation placement, length discipline, visual-device encouragement, filler bans) apply to the layercake draft the same way they apply to a single-pass draft.

5. **Structure the draft around the decomposition.** When the prompt named 5 entities in a list, the draft should typically have 5 sections or subsections in that order. When the prompt asked for a mind map, include a mind map. When the prompt named sub-questions A/B/C, answer them in that order. Your own analytical framing belongs in the synthesis section at the end — NOT as the body's structural spine. This single rule is the highest-leverage insight-following move available.

6. **Write the draft to `research/notes/final_report.md`.** Structure:
   - Opening paragraphs that state the thesis / framing. Your thesis must commit to a position — not "this report surveys X" but "X is true (or X is false, or X is the right frame) because..." — grounded in the cross-locus comparisons you identified.
   - Body sections mirroring the decomposition's structural cues. **Each body section that touches a tension named in `comparisons.md` must engage that tension explicitly** — by name, with a paragraph that commits to a reading of the disagreement, not just reports both sides.
   - Closing section per the modality rule. Where the modality demands a reasoned position (synthesize, compare, forecast), that position must visibly incorporate the strongest cross-locus tensions — not average them out into hedged prose.
   - Sources list — numbered `[N]` entries matching the inline `[N]` citations

7. **Insight-generation rules (applied to every body section):**
   - **Commit, don't hedge.** Sentences like "some argue X while others argue Y" are allowed as setup but MUST be followed by "the evidence weighs toward X because Z" or an equivalent committed reading. Pure "on the one hand / on the other hand" prose is low-insight reporting.
   - **Interpret, don't just cite.** For every 2–3 citations, there should be at least one interpretive beat — a sentence or clause that draws a conclusion the sources themselves didn't draw. Interpretive density drives the insight dimension; descriptive citation stacks suppress it.
   - **Privilege committed investigator positions.** Each `## Committed position` section from a depth investigator is a claim the draft can cite directly ("our reading of the FRMCS evidence is that..." — then [N]). These are your strongest argumentative levers — use them, don't soften them into "the literature suggests...".
   - **Every body section argues, not just the synthesis.** A common failure mode is drafts that save commitment for the synthesis section and leave body sections in descriptive / reporting mode. That doesn't work — the body is where evidence is introduced, and the body is where arguments should LAND. Each H2 should end with (or contain) at least one sentence that commits to a reading of that section's evidence. "Here is how this evidence is best understood" belongs in every section, not just the final one.
   - **Weave named tensions INLINE with immediate resolution.** When a cross-locus tension from `comparisons.md` is relevant to a body section, engage it inline in that section — name the tension, quote the strongest version of each side, and commit to a reading — then move on. Do NOT gather tensions into a dedicated "Source Tensions" H2 at the end; that gives the reader an unresolved buffet. Reference-quality reports name tensions where they arise in the doctrinal or analytical flow and resolve them immediately.
   - **Prescriptive specificity when evidence supports it.** When an investigator's `## Committed position` contains a specific threshold, number, rule, or named mechanism, preserve that specificity in the draft. Do not soften "manufacturer liability attaches when handover warnings fall below 10 seconds at highway speeds" into "manufacturer liability attaches when warnings are too brief." The precision is the authority; softening it to LLM-directional language drops the report's prescriptive weight. If a recommendation in the draft reads abstract, ask yourself what specific threshold or rule the evidence supports, and say it.

8. **Include inline citations.** Every load-bearing claim gets `[N]`. The `[N]` numbering is deterministic: first cited source is `[1]`, next new source is `[2]`, and so on. The Sources list at the end matches this numbering.

9. **Honor wrapper contracts.** If `research/wrapper_contract.json` specifies a required terminal section (e.g., `## Opinionated Synthesis`), include it. If it specifies forbidden body sections, do not use them.

10. **Hygiene.** The final report MUST NOT contain:
    - YAML frontmatter
    - Any scaffold-only section (the polish auditor strips these if they leak, but prevention is cheaper)
    - The user prompt verbatim
    - Literal "User asked:" or similar prompt-echo preambles
    - `research/comparisons.md` content verbatim — comparisons.md is planning, not body content
    - `research/prompt-decomposition.json` content verbatim — decomposition is planning, not body content

11. **Write-once.** You write this draft once. After this point, the draft is only modified by Edit hunks from the patcher and polish auditor. Do NOT re-draft.

---

## Layer 5 — Adversarial critique (parallel, 4 critics)

**Goal:** four independent findings lists against the single draft, each from a different adversarial angle. Each critic has its own role — they complement, not duplicate.

1. **Spawn 4 critics in parallel.** In ONE message, invoke:
   - `hyperresearch-dialectic-critic` → `research/critic-findings-dialectic.json` (counter-evidence the draft missed or straw-manned)
   - `hyperresearch-depth-critic` → `research/critic-findings-depth.json` (shallow spots where interim notes could fill substance)
   - `hyperresearch-width-critic` → `research/critic-findings-width.json` (corpus clusters the draft ignores despite evidence)
   - `hyperresearch-instruction-critic` → `research/critic-findings-instruction.json` (atomic items from `research/prompt-decomposition.json` that the draft missed, under-covered, reordered, or reformatted)

2. **Pass each critic:**
   - `research_query` — canonical, verbatim (GOSPEL — same text every critic sees)
   - `draft_path` — `research/notes/final_report.md`
   - `output_path` — one of the four paths above
   - `vault_tag` — `<vault_tag>`
   - For `instruction-critic` additionally: `decomposition_path` = `research/prompt-decomposition.json`

3. **Wait for all four.** If one fails, you can proceed with three findings files, but log the absence to the run log — the patch pass is less robust with missing critic coverage. Do NOT skip the instruction-critic specifically — it's the only critic measuring prompt adherence, which is the dimension with the widest variance.

4. **Do not read the findings yourself and apply them.** The patcher reads the findings. Your job is to hand them to the patcher.

---

## Layer 6 — Patch pass (`hyperresearch-patcher`)

**Goal:** apply critic findings to the draft as surgical Edit hunks. Zero regeneration.

1. **Pre-create the patch log stub.** The patcher is tool-locked to `[Read, Edit]` — it cannot Write. Edit can only modify files that already exist. So you (the orchestrator) MUST write an empty stub first, which the patcher will then Edit to populate:

```bash
echo '{"applied": [], "skipped": [], "conflicts": []}' > research/patch-log.json
```

   If you skip this step the patcher will silently have nowhere to write its log, will inline the log in its response instead, and you may mis-capture or drop the data entirely. This has historically been the single most common Layer 6 failure mode — do not skip it.

2. **Spawn the patcher ONCE.** Pass:
   - `research_query` — canonical, verbatim (same as every other subagent). The patcher checks every finding against this before applying; findings that don't serve the research_query are rejected.
   - `draft_path` — `research/notes/final_report.md`
   - `findings_paths` — list of the four critic JSONs (dialectic / depth / width / instruction)
   - `patch_log_path` — `research/patch-log.json` (already stubbed above)

3. **The patcher is tool-locked to `[Read, Edit]`.** It physically cannot Write. It can only call Edit with old_string/new_string pairs, and its prompt requires each hunk to stay surgical. Its job is to: (a) apply each finding's patch as an Edit on the draft file, and (b) populate the pre-stubbed patch log via Edit on `research/patch-log.json`.

4. **Read the patch log when it returns.** Check:
   - Did the patcher apply all `critical` findings? If any critical was SKIPPED, that's a pipeline blocker — resolve it yourself before Layer 7. Options: (a) reject the finding as invalid after re-reading the draft, (b) escalate to the user, (c) hand-craft an Edit to address it.
   - Did any findings CONFLICT? Look at the conflict log — if two critics disagreed and the patcher picked one, consider whether the discarded one was actually more important.
   - Did the patcher log a "patch too large" skip? That means a critic proposed regeneration in patch clothing. If the finding was critical, re-spawn the critic with a tighter suggestion, or address it yourself with multiple small hunks.
   - **Is the patch log still the empty stub `{"applied":[],"skipped":[],"conflicts":[]}`?** If yes, the patcher failed to log — its Task result will contain the real log inline. Read the Task result, parse out the JSON, and write it to `research/patch-log.json` yourself via Bash so downstream lint rules see it.

5. **Do not apply the patches yourself.** You MUST spawn the patcher subagent. Do NOT call Edit directly on `research/notes/final_report.md` in Layer 6 — the patcher has the tool-lock invariants (surgical-hunk discipline, old-text exact match, conflict resolution, integrate-don't-caveat rule) baked into its prompt. Bypassing it defeats the entire adversarial-patch architecture. If the patcher returns an empty result or appears to have failed, re-spawn it — don't fall back to doing it yourself.

6. **Do not re-spawn the patcher on the same findings** unless you've modified the findings. The patcher's second run on identical input is a waste.

---

## Layer 7 — Polish audit (`hyperresearch-polish-auditor`)

**Goal:** final hygiene + readability pass. Also tool-locked to `[Read, Edit]`.

1. **Pre-create the polish log stub.** Same rule as Layer 6 — the polish auditor has `[Read, Edit]` only and cannot create a new file. Stub it first:

```bash
echo '{"applied": [], "escalations": []}' > research/polish-log.json
```

2. **Spawn the polish auditor ONCE.** Pass:
   - `research_query` — canonical, verbatim
   - `draft_path` — `research/notes/final_report.md`
   - `polish_log_path` — `research/polish-log.json` (already stubbed above)

3. **The polish auditor strips:**
   - Hygiene leaks (YAML frontmatter, scaffold sections, prompt echoes)
   - Filler phrases ("It is worth noting", "Importantly", etc.)
   - Redundant sentences / paragraphs that restate prior content
   - Run-on sentences and over-long paragraphs (breaks into smaller units via Edit)

4. **The polish auditor ESCALATES** structural mismatches (wrong format for the prompt, missing required sections, etc.) rather than fabricating content to fix them. Read the escalations in the polish log. If the escalation names a structural issue (e.g., "user asked for a ranked list; draft is unranked prose"), you have one shot to fix it — craft the restructure yourself with hand-written Edits, then ship.

5. **Sanity-check net length.** Polish should have NEGATIVE net char delta. If the polish log shows positive net chars added, something went wrong — polish is for cutting, not expanding.

6. **Do not apply polish edits yourself.** Same rule as Layer 6 — the polish auditor's tool lock is the mechanism. Calling Edit directly in Layer 7 bypasses the hygiene-check and filler-detection logic baked into the auditor's prompt. If the auditor returned empty, re-spawn it; don't do the work yourself.

---

## After Layer 7: audit findings + lint gate

1. **Record the run.** Append to `research/audit_findings.json`:
```json
{
  "mode": "layercake",
  "run_id": "<iso timestamp>",
  "loci_count": <K>,
  "critical_findings_applied": <int>,
  "critical_findings_skipped": <int>,
  "polish_escalations": <int>,
  "final_word_count": <int>
}
```

2. **Run the lint gate.**
```bash
$HPR lint --rule wrapper-report --json
$HPR lint --rule locus-coverage --json
$HPR lint --rule scaffold-prompt --json
$HPR lint --rule patch-surgery --json
```

If any rule returns `error` severity issues, address them before declaring the run complete:
- `wrapper-report`: scaffold leaked into the body — spawn the polish auditor once more with the specific leak flagged
- `locus-coverage`: a locus identified in Layer 2 has no interim note in the vault — a depth investigator failed silently; do not re-run, just note it in the run log
- `scaffold-prompt`: the scaffold's `## User Prompt (VERBATIM — gospel)` does not match `research/prompt.txt` exactly — fix the scaffold
- `patch-surgery`: the draft's churn from Layer 4 → final exceeds the safety threshold — this is a red flag that regeneration snuck in somewhere; read the patch log and investigate

3. **Ship.** The final report lives at `research/notes/final_report.md`. The wrapper's required save path (if any) is a separate copy — handle per the wrapper contract.

---

## Invariants you cannot break

1. **PATCHING not REGENERATION after Layer 4.** The draft is written once in Layer 4. Every modification after that is an Edit hunk from the patcher or polish auditor. If you catch yourself thinking "let me just rewrite this section," stop — that's a Layer 4 or Layer 6 issue to handle through the subagent, not a shortcut.

2. **One draft.** You write the final report ONCE. Do not re-draft between Layer 4 and Layer 7. If the critics flag a structural issue that a patch cannot fix, resolve it by spawning a targeted helper with Edit tool (hand-craft Edit calls yourself) — never by re-writing from scratch.

3. **At least one dialectical locus.** Unless a loci-analyst justifies its absence in `skip_loci` with specific evidence of a univocal corpus, Layer 2 must surface at least one `flavor: "dialectical"` locus. No dialectical locus + no justification = re-spawn the loci-analyst with a tighter prompt.

4. **Every interim note commits to a position.** Depth investigators return a `## Committed position` section that takes a side. An interim note ending with descriptive summary only is defective — flag it and re-spawn that investigator with the committed-position requirement emphasized.

5. **`research/comparisons.md` exists whenever loci count ≥ 2.** Layer 3.5 is mandatory when there are at least 2 loci to compare. Skipping Layer 3.5 causes the draft to report locus-by-locus instead of engaging cross-locus dynamics — that's the failure mode that tanks the insight score.

6. **Depth investigators' outputs are interim notes, not prose sections.** You consume their synthesis and positions in Layer 4. You do not paste their text into the draft; you weave it and reconcile it against other investigators.

7. **Layers are sequential at the outermost level, parallel within.** You cannot start Layer 2 before Layer 1 completes, Layer 3 before Layer 2 completes, Layer 3.5 before Layer 3 completes, Layer 4 before Layer 3.5 completes. Within a layer, parallelism is mandatory when there are multiple subagents (spawn them in one message).

8. **Canonical research query is gospel everywhere.** Every subagent you spawn gets the canonical research query as an explicit input. Do not let wrapper instructions leak into their task prompts.

9. **Hygiene rules apply to the final report only.** The scaffold, the loci JSONs, the interim notes, `comparisons.md`, the patch log — these are workspace artifacts and can look however they need to look. The `final_report.md` is the single artifact subject to frontmatter-strip, scaffold-strip, filler-strip rules.

---

## Escalation hotlines

- **Width sweep too thin** → tell the user, run Layer 2 anyway, expect weaker loci
- **No dialectical locus returned** → re-spawn the loci-analyst once with an emphatic reminder that dialectical loci are mandatory unless the corpus is univocal. If the analyst still returns none, trust its skip_loci justification.
- **Both loci analysts fail** → stop the pipeline, tell the user the corpus was insufficient
- **>50% depth investigators fail** → stop, reassess loci quality with the user
- **Interim note missing `## Committed position`** → re-spawn that investigator. Uncommitted interim notes are the root cause of descriptive drafts.
- **Only 1 locus** → Layer 3.5 still runs; `comparisons.md` distills that locus's committed position as the lone argumentative anchor for the draft. Don't skip the file.
- **Critic disagreement unresolvable by patcher** → you pick a side (higher severity wins); log to the run log
- **Critical finding cannot be patched** → do not ship; address it (hand-craft Edit, or re-spawn targeted critic with tighter suggestion, or reject the finding with reason)
- **Polish escalation on structural mismatch** → hand-craft the Edits yourself; do not expand polish auditor's scope

---

## Why layercake

The single-pass `/research` skill runs one investigator against the whole topic. Layercake sequences width first (to lay a map), then depth (to fill the rabbitholes the map revealed), then cross-locus reconciliation (Layer 3.5, to turn parallel depth packets into a coherent argument before drafting). The depth loci are *discovered from the width corpus* — they are not pre-assigned framings. That means the depth investigations track the evidence the query actually turned up, not framings we guessed before reading anything.

Layer 3.5 is the insight-generation step. The old ensemble architecture generated argumentative density by compiling three independent drafts and letting the merger graft the strongest argumentative beats across them. Layercake substitutes a cheaper move: force each investigator to commit to a position, force the orchestrator to reconcile those positions before drafting, then draft once with the reconciliation as the argumentative spine. The insight gain of ensemble's 3×-draft strategy is available without actually running 3 full drafts — IF the Layer 3.5 reconciliation is done honestly.

The adversarial critics + patcher + polish auditor are a checked commit on the draft: three independent readings flag issues, a tool-locked patcher applies them surgically, and a tool-locked polish auditor cuts the fat. The tool lock is the load-bearing invariant — it prevents the "just rewrite it" failure mode that plagues post-hoc review in long-running agent pipelines.

If any layer's subagent fails, you can fall back to manual handling (hand-craft Edits via your own Edit tool, rerun a single critic, etc.). You cannot fall back to "re-draft from scratch" — that violates the core invariant.
