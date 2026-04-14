---
name: research
description: >
  Deep research on any topic. Classifies requests by cognitive activity
  (collect / synthesize / compare / forecast), not subject matter. Produces
  a sourced, adversarially-audited report with full data-flow provenance.
  Trigger: /research
---

# Research Dispatcher

The research protocol has ONE process spine (this file) and FOUR modality files that encode substance differences. Read this file end-to-end. Then read the modality file the classifier routes you to. Both are required.

**There are no numeric targets in this protocol.** No word counts, no H2 counts, no words-per-section floors. A draft is as long as the substance demands and as short as the structure allows. The user's own scope cues (if any) are the only length guidance that applies.

**The user's verbatim prompt is the only gospel in this session.** It gets copied into the scaffold at Step 7 and every subsequent step re-reads it. Whenever you are unsure what to do, re-read the prompt. Whenever the draft feels like it's drifting, re-read the prompt. The auditor at Step 11 grades the draft against the verbatim prompt — not against any abstract notion of quality.

---

## The 4 activities

Research requests are classified by what the output needs to DO, not what the subject IS.

| Activity | Question it answers | Primary virtue | Modality file |
|---|---|---|---|
| **collect** | "What exists / what happened / who did what" | Exhaustive enumerative coverage with per-entity fields | `.claude/skills/hyperresearch/SKILL-collect.md` |
| **synthesize** | "What does it mean / how does it work / why" | Interpretive density — a defended thesis grounded in evidence | `.claude/skills/hyperresearch/SKILL-synthesize.md` |
| **compare** | "Which is better for what / how do they differ" | Proportionate per-entity depth + a committed recommendation | `.claude/skills/hyperresearch/SKILL-compare.md` |
| **forecast** | "What will happen / what should we do" | Committed prediction from past + current state with explicit time horizon | `.claude/skills/hyperresearch/SKILL-forecast.md` |

**Subject matter does not decide the classification.** A query about a fictional franchise can be collect (per-character enumeration), synthesize (a thesis about what the franchise means), compare (this franchise vs another), or forecast (will this franchise's new arc succeed). A query about distributed databases can be any of the four. The classifier reads what the output should *do*, not what the subject *is*.

**A single prompt can blend activities** — that is normal. Pick ONE primary and optionally ONE secondary flavor. The primary determines the process and the structural backbone; the secondary informs the substance rules at Step 9. Example: "Analyze Saint Seiya's armor classes: for each significant character, cover techniques, story arcs, fate — and develop a thematic argument about what the armor means" is **collect** (primary — the per-character enumeration is the backbone) + **synthesize** (secondary — thematic beats layered into each entity section).

---

## Step 0: Clarify if vague

If the request is vague or ambiguous, ask 1–3 focused questions before proceeding. Don't guess.

---

## Step 0.5: Check existing vault coverage first

```bash
$HPR search "<topic>" -j
```

If the vault already has >10 relevant notes: tell the user, summarize what's there, and ask whether they want deeper research, a specific angle, or synthesis from existing notes. Don't re-fetch what's already curated.

---

## Step 1: Classify + commit the verbatim prompt

State your classification in writing BEFORE doing anything else. Copy the user's prompt verbatim into your working memory. This is the format you MUST output:

```markdown
## User Prompt (VERBATIM — gospel)
> [paste the entire user message here, character-for-character. Do not
> paraphrase. Do not summarize. Do not reformat. This text is the only
> authoritative source for what the output should contain and look like.]

## Primary activity
<collect | synthesize | compare | forecast>

## Secondary flavor (optional)
<collect | synthesize | compare | forecast | none>

## One-sentence justification
<why this primary activity matches what the output needs to DO>

## What the user explicitly asked for (extracted from the verbatim prompt)
- **Explicit deliverables:** <list every specific ask — "answer A, B, C", "include a recommendation", "for each X give Y" — or "none">
- **Explicit entities or items:** <every item named in the prompt, or "none">
- **Explicit per-item fields:** <every field the prompt demands per entity — "power level / technique / fate" — or "none">
- **Explicit structure:** <"one section per", "ranked list", "executive summary", etc., or "silent">
- **Explicit format:** <prose / bullets / table / code / FAQ, or "silent">
- **Explicit scope cues:** <"brief", "detailed", "deep dive", specific lengths, or "silent">
- **Explicit ordering:** <chronological / by importance / custom, or "silent">

## Core tension
<what makes this question non-trivial — a paradox, a disagreement, a tradeoff,
a constraint interaction, an open problem. One-to-three sentences. This is
what the draft must earn its way through.>
```

Then **read the corresponding modality file with the Read tool.** The modality file tells you HOW to do the activity-specific parts (source strategy, substance rules, conformance checks). This dispatcher tells you WHAT steps to run and in what order.

---

## Tiebreaker questions

When two activities seem equally applicable:

**collect vs compare** — Does the user want coverage ("tell me everything") or evaluation ("which is best")? Recommendation expected or entities set against each other → **compare**. Coverage is the point and no recommendation is requested → **collect**.

**collect vs synthesize** — Does the output need a defended thesis or just complete coverage? If the user explicitly asks for interpretation, meaning, or analysis alongside enumeration, the primary is usually **collect** (the enumeration is the dominant ask) and the secondary flavor is **synthesize**. Pure enumeration without thesis → **collect**. Pure thesis without per-entity coverage → **synthesize**.

**synthesize vs forecast** — Is the claim about what IS (how it works, what it means) or what WILL BE (prediction, recommendation)? Past/present → **synthesize**. Future → **forecast**.

**compare vs forecast** — Is the user asking which option is best NOW or which will be best LATER? Now → **compare**. Later → **forecast** (often with compare flavor).

**Any activity when the prompt contains "for each X, provide Y / Z / W"** — The explicit per-entity field list is a collection contract. Route to **collect** as the primary regardless of subject, with any interpretive / comparative / predictive framing as secondary flavor. The per-entity contract takes precedence because it is the most specific kind of user mandate.

---

## Prompt fidelity — the gospel rule

**Re-read the user's verbatim prompt at every checkpoint.** The prompt is inside the scaffold (Step 7). Every checkpoint re-opens the scaffold. Every time you re-open the scaffold, re-read the prompt first. Every structural decision must trace back to the prompt or a modality default that the prompt is silent on.

- If the prompt specifies structure / format / entities / fields / ordering / scope: **the user's request is authoritative**. Modality defaults yield.
- If the prompt is silent on any of those: **the modality default applies** to what the prompt left open.
- The modality file is authoritative for SUBSTANCE (interpretation density, proportionate depth, probability language, mechanism clarity). Substance rules hold regardless of shape.

**Never negotiate the user's contract.** If the user asked for 108 entities and 4 fields each, you owe 108 × 4 data points. You do NOT get to substitute "representative examples + thematic commentary". You do NOT get to silently downgrade "each" to "the most important". If the user's contract seems impossible to satisfy within a reasonable draft, surface that tension to the user and ask — do not paper over it by producing less than what was asked.

---

## Process discipline (applies to every activity)

This protocol is **process-driven**. Each required step produces an **artifact** that a later step reads. Skipping a step does not save work — it breaks the dependency chain silently, and the later step operates on missing-but-pretended input. The draft then gets written without the tension analysis; the audit never fires; the report ships un-stress-tested.

**Definition of task failure:** if a required artifact does not exist on disk or in the vault at the checkpoint where the next step expects it, the task has FAILED at that checkpoint. Failure is not fatal — it means: STOP the current step, return to the step that produces the missing artifact, complete it, and re-run the checkpoint. You may NOT compensate for a missing artifact by doing extra work inside the step that follows it.

Read this section before doing anything else, then follow it literally. You will self-review four times in a single research session. If any review fails, you go back.

### Required TODO list (build this immediately after Step 1 classification)

Before executing Step 2, create this exact TODO list with the TodoWrite tool. Do NOT fetch anything, search anything, or write anything until the list exists:

1. Check existing vault coverage (Step 0.5)
2. Discover sources (Step 2)
3. Fetch source batch or open the guided reading loop (Step 3)
4. **Checkpoint 1: post-fetch review**
5. Rabbit-hole pass with `--suggested-by` provenance (Step 4)
6. Curate every source: tier + content_type + summary + analyst extract (Steps 5–6)
7. Run link / lint / graph hubs (Steps 5–6)
8. **Checkpoint 2: post-curate review**
9. Write scaffold note WITH verbatim user prompt as first section (Step 7)
10. Write comparisons note (Step 8)
11. **Checkpoint 3: pre-draft gate — CRITICAL**
12. Write `research/notes/final_report.md` (Step 9)
13. Gap analysis + adversarial search (Step 10)
14. Adversarial audit via `hyperresearch-auditor` — both modes in parallel (Step 11)
15. **Checkpoint 4: post-audit review**
16. Write Opinionated Synthesis section (Step 12)
17. Save synthesis note + health checks (Steps 13–14)

Mark each item `completed` only after its artifact exists AND you have verified it exists with a command. You may NOT mark item 12 (the draft) `in_progress` until items 1–11 are all `completed`. The TODO list is the process ledger.

---

## Zettelkasten conventions (apply in every activity)

All notes follow atomic Zettelkasten conventions. The CLI manages the index.

**Note `type:` field:** `source` | `synthesis` | `moc` | `scaffold` | `comparison`

**Status lifecycle:** `draft` → `review` → `evergreen` → `stale` → `deprecated` → `archive`

**Every source note must have:** `title`, `source` (URL), at least one `tag`, `summary` (≤120 chars), `status`, `tier`, `content_type`.

**Epistemic metadata (required on every source note before Checkpoint 2):**

- **`tier`** — what epistemic role this source plays:
  - `ground_truth` — the artifact itself: official filings, product specs, datasets, primary texts, peer-reviewed papers with original data, regulatory text
  - `institutional` — authoritative synthesizers: analyst reports, think-tanks, review/survey papers, textbooks, canonical criticism
  - `practitioner` — how domain participants actually experience it: user reviews, community threads, practitioner blogs, postmortems, migration guides
  - `commentary` — discussion without new signal: news summaries, opinion pieces, derivative explainers
  - `unknown` — unclassified (default at fetch time; must be replaced during curation)
- **`content_type`** — what kind of artifact this is: `paper` | `docs` | `article` | `blog` | `forum` | `dataset` | `policy` | `code` | `book` | `transcript` | `review` | `unknown`

Tier and content_type are orthogonal: a `paper` can be `ground_truth` (original data) or `institutional` (a review). A `blog` can be `practitioner` (named engineer's postmortem) or `commentary` (derivative explainer).

**Tagging:** Check existing tags first (`$HPR tags -j`). Reuse existing tags. Apply multiple relevant tags per note. Do not invent synonyms.

**Wiki-links:** Connect related notes with `[[note-id]]`. Every note should link to at least one sibling.

---

## Step 2: Source discovery

The modality file tells you the source strategy (what APIs to hit, what source types to prioritize, whether to run the academic sweep). Run it.

Then, regardless of modality, run an **adversarial search round** — searches that specifically look for the failure case, the dissenting view, the critique, the contrarian, the known limitations. Every activity needs this:

```
WebSearch("<topic> criticism limitations problems")
WebSearch("<topic> against the grain dissenting view")
WebSearch("why <dominant view> is wrong")
```

A corpus without dissent is advocacy, not research. If the adversarial round returns nothing substantive, note that explicitly — it is itself a finding.

---

## Step 3: Fetch — guided reading loop (preferred) or batch

**Default: the guided reading loop** (described below). Seed with 3–5 high-signal URLs, then let each iteration's analyst subagents propose next targets based on what the prior sources cite.

**Batch fetch** only when the target set is already known and complete — e.g., the user handed you 10 URLs, or the modality file says to batch (compare activity with explicitly-named entities is the usual case).

### Guided reading loop protocol

The loop is a bounce between fetching and reading:

```
fetch 3-5 seeds  →  hyperresearch-analyst reads each with goal in hand  →
  analyst returns extract + "next_targets" (URLs, queries, names, claims to verify)  →
  main agent fetches next_targets with --suggested-by flag  →
  hyperresearch-analyst reads those  →  ...
```

Each iteration is a research director: the analyst reads one source, proposes what to read next, and hands the decision back to the main agent. This discovers source trees you couldn't find by keyword search alone — the essay names three critics, those critics cite a 1998 monograph, the monograph references a specific passage in the primary work.

**Phase 1 — Seed fetch.** Pick the 3–5 highest-signal URLs:
- 1–2 canonical reference entries (Wikipedia, field survey, official docs)
- 1–2 analytical/critical sources visible in search results
- 0–1 adversarial/dissenting source

Spawn `hyperresearch-fetcher` on ONLY those 3–5. Do NOT batch-fetch 20 URLs upfront — half get wasted on sources the loop would tell you to skip.

**Phase 2 — Guided reading iterations.** For each fresh note, spawn the **`hyperresearch-analyst`** agent (Sonnet, registered at `.claude/agents/hyperresearch-analyst.md`) with `mode=guided`:

```
research_goal: <the user's original verbatim prompt>
sub_goal: <what this specific source should contribute>
source_note_id: <the id of the note to read>
mode: guided
already_covered: <sub-topics prior iterations answered, or "none">
already_fetched_urls: <output of `$HPR sources list -j`>
```

Spawn multiple analysts in parallel — one per source in the current batch. Each returns: extract content + covered sub-topics + 2–5 next_targets + coverage status.

**Phase 3 — Main agent orchestration.** After each iteration returns:

1. **Track the iteration in TodoWrite.** Add `Iteration N: fetch [targets] from [sources]`. After it completes, mark with the coverage delta ("added 4 sources, 2 sub-topics newly covered"). This makes stalls visible.
2. Collect every extract into a running knowledge accumulator.
3. Merge and dedupe next_targets across all analysts. If three subagents propose the same URL, fetch it once — pass all three suggesting source IDs via repeated `--suggested-by` flags.
4. Prioritize next_targets by: (a) which would most likely *change* the argument if they disagreed with current sources, (b) which sub-topics the corpus doesn't yet cover, (c) which tiers are missing.
5. **Fetch the top 3–5 next_targets WITH `--suggested-by` flag. This is mandatory:**

   ```bash
   $HPR fetch "<url>" \
     --tag <topic> \
     --suggested-by <source-note-id-1> \
     --suggested-by <source-note-id-2> \
     --suggested-by-reason "<the analyst's justification>" \
     -j
   ```

   Without this flag the data-flow chain breaks — the fetched note has no link back to the source that found it, and you cannot trace how the research graph assembled itself.

   **Graceful duplicate handling:** if the URL is already in the vault, fetch will NOT error. It appends the breadcrumb to the existing note and returns `{ok: true, duplicate: true, backlinks_added: N}`. Fetch every next_target; let fetch handle dedup.

6. Refresh `already_fetched_urls` (`$HPR sources list -j`). Pass it to the next iteration.
7. Spawn `hyperresearch-analyst` on the new notes. Loop.

**Phase 4 — Termination.** Exit when ANY of these fires:
- **Coverage complete** — all analyst returns report `coverage: complete` for the sub-topics you need.
- **Cycle detected** — next_targets repeat or every proposed target's fetch returns `duplicate: true` with `backlinks_added: 0`.
- **Diminishing returns** — a full iteration adds zero new sub-topics. The TodoWrite delta tracker catches this.
- **Iteration cap: 5 full loops** — more than this and the loop is drifting, not converging. Stop and move on.

Then proceed to curation (Steps 5–6).

---

## Step 4: Rabbit holes — follow what sources point at

Beyond the guided loop's automated next_targets, actively scan fresh notes for:

- **Cited datasets / primary data** → fetch the original, not the summary
- **Named scholars / practitioners / companies** → find their own writing
- **Referenced historical cases / precedents** → fetch the case itself
- **Interviews or quotes** → find the full transcript

Every manual rabbit-hole fetch MUST also pass `--suggested-by` naming the source that sent you there:

```bash
$HPR fetch "<url>" \
  --tag <topic> \
  --suggested-by <source-note-id> \
  --suggested-by-reason "<one-line reason>" \
  -j
```

Claims carry more weight when the graph shows you traced them to primary sources.

---

## Step 4.5: Note triage (MANDATORY throughout)

Never blindly `note show` every note. Triage first.

| Level | Command | When |
|---|---|---|
| 1 — List | `$HPR note list -j` | Always start here. Summaries only, no bodies. |
| 2 — Meta | `$HPR note show <id> --meta -j` | When the summary hints at deeper value. |
| 3 — Inline | `$HPR note show <id> -j` | word_count < 2000. Batch small notes: `note show <id1> <id2> <id3> -j` |
| 4 — Search | `$HPR search "<q>" --include-body --max-tokens 6000 -j` | When you want content across multiple notes. |
| 5 — Subagent | Spawn `hyperresearch-analyst` (mode=extract) | word_count > 3000, OR whenever you need one specific answer from a big source. Never dump large notes inline. |

---

## Steps 5–6: Curate every source

Raw fetched notes arrive with `status=draft`, `tier=unknown`, auto-detected `content_type`, and no summary. Curation has two parallel jobs:

1. **Set metadata** — tier, content_type, summary, tags, status (you do this with `$HPR note update`)
2. **Extract relevant content** — spawn `hyperresearch-analyst` on the source so you have an extract note grounded in the research goal

**Both must happen for every fetched source.** The analyst extract is what gives you the substance to write deep prose about the source later; the metadata is what lets you query and filter the corpus during drafting.

### Step A: Spawn the analyst on every source

For research, the analyst is the default reading mechanism — not a fallback for big sources. Even small sources (1500 words) deserve analyst treatment because the analyst's URL-scan surfaces follow-up targets for the loop.

```
For each draft source note:
  Spawn hyperresearch-analyst with:
    research_goal: <the user's original verbatim prompt>
    sub_goal: "establish what this source contributes and what URLs / authors / claims warrant follow-up"
    source_note_id: <draft note id>
    mode: guided
    already_covered: <running list from prior analysts>
    already_fetched_urls: <output of `$HPR sources list -j`>
```

Spawn 3–5 in parallel (Sonnet, cheap). Each analyst reads the source, persists an extract note (`--add-tag extract --parent <source-id>`), and returns an extract + next_targets + coverage status.

Collect every analyst's next_targets into TodoWrite. After each batch, fetch the top next_targets WITH `--suggested-by` so the loop iterates. **The fetch:extract ratio after curation should be at least 1:1** — every fetched source has a paired extract note. The `analyst-coverage` lint rule catches misses at Checkpoint 2.

### Step B: Set metadata from the analyst's findings

The analyst's return tells you the tier and content_type. After it returns:

```bash
$HPR note update <source-id> \
  --tier <ground_truth|institutional|practitioner|commentary> \
  --content-type <paper|docs|article|blog|forum|dataset|policy|code|book|transcript|review> \
  --summary "<one-line description, can borrow from the analyst's extract>" \
  --add-tag <topic> --add-tag <subtopic> \
  --status review \
  -j
```

**Tier and content_type are PER-NOTE decisions.** Never apply one value to the whole batch. A fandom wiki is `docs`; a news article is `article`; a named-engineer blog post is `blog`; a reddit thread is `forum`; a GitHub README is `code`. An arxiv paper on theory is `institutional`; the same paper reporting experimental data is `ground_truth`; a conference keynote transcript is `commentary`. Read each analyst return and make the call per source.

### Completion check

```bash
$HPR lint --rule uncurated -j         # zero uncurated
$HPR lint --rule provenance -j        # zero provenance issues (--suggested-by chain exists)
$HPR lint --rule analyst-coverage -j  # zero analyst-coverage issues
$HPR link --auto -j
$HPR graph hubs -j
```

If any lint returns issues, curation is NOT done. Go back, run more analyst calls, fetch proposed next_targets with `--suggested-by`, and re-run the lints before Checkpoint 2.

---

## Step 7: Build the scaffold — with the verbatim user prompt as the first section

**Required artifact:** a note tagged `scaffold` whose FIRST section is the user's verbatim prompt.
**Verification:** `$HPR note list --tag scaffold -j` must return ≥1 entry after this step AND the body of that note must contain the verbatim user prompt.
**On failure:** the draft has no anchor. Return to Step 7 and write the scaffold.

Using the **Write tool**, create `research/scaffold.md` with this exact structure:

```markdown
## User Prompt (VERBATIM — gospel)
> [the user's entire message, copied character-for-character from the prompt.
> This is the authoritative source. Every subsequent step re-reads this
> section. Do not paraphrase. Do not truncate. Do not reformat.]

## What the user explicitly asked for
- **Explicit deliverables:** <list — or "none">
- **Explicit entities or items:** <list — or "none">
- **Explicit per-item fields:** <list — or "none">
- **Explicit structure:** <or "silent">
- **Explicit format:** <or "silent">
- **Explicit scope cues:** <or "silent">
- **Explicit ordering:** <or "silent">

## Primary activity and secondary flavor
- **Primary:** <collect | synthesize | compare | forecast>
- **Secondary (optional):** <or "none">
- **Why:** <one sentence>

## Core tension
<what makes this question non-trivial — the paradox, disagreement, tradeoff,
or open problem the draft has to earn its way through>

## The structural plan
<Ordered list of sections the draft will produce. Honor every explicit
structural mandate from "What the user explicitly asked for". Where the
prompt is silent, apply the primary modality's default structural guidance.
For each section, name it AND describe what it will contain in one line.>

## Where each source will land
<One line per curated source-id: which heading(s) it serves and in what role
(ground-truth evidence, institutional synthesis, dissenting voice, etc.).>

## Coverage checklist (the auditor will verify this)
<One line per explicit contract from "What the user explicitly asked for".
The auditor at Step 11 reads this checklist and verifies each item is
ticked off in the draft. If the user said "for each of 108 Specters provide
techniques and fate", there must be a coverage-checklist line that will be
checked against the draft. Do not write vague checks.>
```

Then run:

```bash
$HPR note new "Scaffold: <topic>" --tag scaffold --status draft \
  --body-file research/scaffold.md --summary "Scaffold for <topic>" -j
```

**The verbatim user prompt goes FIRST.** This is non-negotiable. Every checkpoint re-opens the scaffold, and re-opening the scaffold means re-reading the prompt. The prompt lives inside the document so it cannot drift out of context.

---

## Step 8: Cross-source comparisons

**Required artifact:** a note tagged `comparison` containing 3–5 explicit source-vs-source disagreements with your position on each.
**Verification:** `$HPR note list --tag comparison -j` must return ≥1 entry after this step.
**On failure:** the thesis / recommendation / forecast has no stress test. "I did it in my head" is not acceptable.

Find 3–5 places where sources disagree. Read both at Level 3+ before comparing.

Using the **Write tool**, create `research/comparisons.md`:

```markdown
## Disagreement 1: <what axis are they disagreeing about>
- Source A ([URL]): <claim/reading> because <reasoning/evidence>
- Source B ([URL]): <different claim> because <different reasoning>
- Why they differ: <theoretical framework? different data? different time window? different scope?>
- My position: <which is more credible and why — take a side, with the evidence that tips the balance>
```

Then run:

```bash
$HPR note new "Comparisons: <topic>" --tag comparison --status draft \
  --body-file research/comparisons.md --summary "Source comparison for <topic>" -j
```

---

## Step 9: Write the draft

**Before writing anything:** re-open `research/scaffold.md`. Re-read the verbatim user prompt. Re-read the "What the user explicitly asked for" extraction. Re-read the coverage checklist. This is mandatory — every draft session must begin with re-encountering the prompt.

Then read your modality file's substance rules. The modality file tells you HOW to write: interpretation density (synthesize), enumerative completeness (collect), proportionate depth + recommendation (compare), probability language + time horizon (forecast).

**Write `research/notes/final_report.md`** as a normal markdown file (no frontmatter needed for the draft — final save happens at Step 13).

### Shared writing constraints (apply to every activity)

- **The opening must establish the core tension.** What makes this question non-trivial? What paradox, disagreement, tradeoff, or open problem is the draft earning its way through? If the user requested a specific opening shape (definitions, executive summary, narrative hook), honor that shape — then make it do tension-framing work.
- **Every body section must earn its analytical beat.** A section that just describes facts without making an interpretive / comparative / forward move is a catalog entry, not a research contribution. Each section ends with a so-what, a comparison, a tension, or a forward beat.
- **Sources in tension at least twice in the body.** Find two places where your sources disagree and walk the reader through the disagreement, naming both positions and explaining which is more defensible. Synthesis alone does not make up for this — the body itself must engage dissent.
- **Every claim has a citation.** Inline parenthetical URL, or `[[note-id]]` if you want the reader to trace it in the vault.
- **Tier weighting.** Anchor substantive claims in `ground_truth` sources. Use `institutional` for positioning. Use `practitioner` for reality checks. Use `commentary` only to characterize reception, never to establish a load-bearing claim.
- **No padding to hit a length.** There is no length target. If your substance fits in 3,000 words, write 3,000 words. If it needs 12,000, write 12,000. A draft should be as long as the content demands.

### Activity-specific substance rules

Open your modality file and read its Step 9 section. Its substance rules layer on top of the shared constraints above — they do not replace them.

### Secondary flavor layering (MANDATORY when your scaffold declared a secondary)

If your Step 1 classification declared a secondary flavor, your draft must satisfy BOTH modalities' substance rules — not just the primary's. Read the **secondary modality's Step 9 substance rules AND its conformance checks** before you start writing.

Conflict resolution:
- **Primary wins on structure.** Section shape, entity-vs-thematic sequencing, comparison-matrix presence, scaffold skeleton — all determined by the primary modality.
- **Secondary wins on substance within sections.** Per-paragraph density rules, tension requirements, interpretation/enumeration discipline — these layer on top of the primary's structure.

Example (Q91-style: `primary=collect`, `secondary=synthesize`):
- Collect (primary) forces per-character coverage across every entity category in the prompt. The structure is entity-based.
- Synthesize (secondary) forces every paragraph to fuse fact with interpretive claim AND at least two body sections to put sources in tension.
- The draft has entity-named sections (primary structure) where every paragraph inside makes an interpretive claim about what that entity means (secondary substance).

The auditor applies BOTH check lists at Step 11. Secondary-flavor violations are **not waivable** — they are CRITICAL findings that block synthesis save via the `audit-gate` lint rule. If a prompt is genuinely 50/50 across two activities, plan to satisfy both; do not silently drop the secondary.

---

## Step 10: Gap analysis + adversarial search

After the first draft, run adversarial searches specific to your activity — the modality file names the queries. Ask yourself:

- Did you engage with the strongest counter-position?
- Is every item in the scaffold's coverage checklist actually ticked off in the draft?
- Are there tiers you're missing (all commentary, no ground_truth)?
- Is there a named voice you should be citing that isn't in the vault yet?

Fetch what's missing. Update the draft.

---

## Step 11: Adversarial audit — spawn `hyperresearch-auditor` twice

**Required artifact:** text output from both `hyperresearch-auditor` runs in your context, plus every identified violation applied to the draft.
**Verification:** in writing, list each violation the auditors raised and whether it has been fixed or explicitly rejected.
**On failure:** an unapplied audit is equivalent to no audit. Task has FAILED at Checkpoint 4.

**Spawn `hyperresearch-auditor` twice — once per mode. Run them SEQUENTIALLY, comprehensiveness first then conformance.** The auditor is a registered Claude Code agent (`.claude/agents/hyperresearch-auditor.md`) running on Opus. Both runs MUST receive the user's original research query **verbatim** — the same prompt you pasted into the scaffold.

Run comprehensiveness first so its findings land in `research/audit_findings.json` without a write race, then run conformance which reads the file and appends its own entry.

```
First spawn (wait for completion before the second):
  research_query: <paste the user's verbatim prompt from scaffold §1>
  modality: <collect | synthesize | compare | forecast>
  mode: comprehensiveness
  final_report_path: research/notes/final_report.md
  scaffold_note_id: <scaffold note id>
  comparison_note_id: <comparison note id>

Second spawn (only AFTER the first has returned and written its entry):
  research_query: <paste the user's verbatim prompt from scaffold §1>
  modality: <collect | synthesize | compare | forecast>
  mode: conformance
  final_report_path: research/notes/final_report.md
  scaffold_note_id: <scaffold note id>
  comparison_note_id: <comparison note id>
```

After both have returned, verify `research/audit_findings.json` has TWO new entries (one per mode) before proceeding. If only one mode's entry is present, re-spawn the missing mode — the `audit-gate` lint rule will fail at Step 13 if either is missing.

The auditor reads your modality file's "Conformance checks" section, applies each check, persists its findings to `research/audit_findings.json`, and returns a text summary with `pass` / `needs_fixes` / `failed` status. Apply every CRITICAL finding before saving the synthesis, and mark each fixed finding's `fixed_at` field in the JSON file as you go. The auditor also reads the scaffold — so it re-encounters the verbatim prompt — and verifies the draft honors the scaffold's coverage checklist.

---

## Step 12: Opinionated synthesis

Append this to the end of the draft:

```markdown
## Opinionated Synthesis

### <Activity-specific header — see modality file>
<the cross-cutting picture the modality demands: thematic threads for
synthesize, comparison matrix for compare, position-with-horizon for
forecast, coverage summary for collect>

### Thematic Threads
<patterns across the body sections that the per-section analysis couldn't
surface — what the whole corpus is saying that no single source said>

### My Reasoned Position
<your defensible stance, explicitly labeled. Synthesize demands a thesis;
compare demands a recommendation; forecast demands a prediction with
probability language and a time horizon; collect demands a "what this whole
set amounts to" claim.>

### Open Questions
<what the sources didn't settle, what data is unavailable, what would
change your position>

### Concluding Thoughts
<one tight paragraph: the single most important thing a reader should
take away — and why>
```

---

## Steps 13–14: Save and present

**Before saving the synthesis**, run the audit-gate lint to confirm the audit loop is closed. This is a hard gate — the synthesis cannot be saved until it returns zero error-severity issues:

```bash
$HPR lint --rule audit-gate -j
```

The `audit-gate` rule checks three conditions against `research/audit_findings.json`:

1. **Both audit modes must have appended a run.** If the file has a comprehensiveness run but no conformance run (or vice versa), the gate fails with a missing-mode error — spawn the missing auditor mode and retry.
2. **No unresolved CRITICAL findings in the most recent conformance run.** Every CRITICAL must have a non-null `fixed_at` timestamp. Walk the unresolved list, apply the fix to `research/notes/final_report.md`, and mark `fixed_at: <current ISO timestamp>` on the finding in the JSON file. If a finding cannot be fixed (e.g. the auditor misread the draft), resolve it by marking `fixed_at` with a `notes` field explaining why the rejection is safe — but that is a last resort, not a bypass.
3. **IMPORTANT findings surface as `info` severity** (advisory, does not block save). They appear in the lint output so you see them before committing. You are strongly encouraged to patch them if they name real gaps — they often do. Mark each as `fixed_at` in the JSON once patched.

After applying fixes:
- If you patched the draft, re-spawn the conformance auditor (which will append a fresh run to the findings file) and re-run the lint.
- If `audit-gate` returns zero error-severity issues — proceed to save.
- If it still fails, diagnose which specific finding is blocking and address it. **Do NOT bypass the gate by editing `audit_findings.json` to clear findings without patching the draft first.**

This is how the audit loop actually closes: findings are persisted → fixes are applied → `fixed_at` is set → the lint passes → the synthesis saves. Each step leaves an artifact on disk.

Using the **Write tool**, create `research/synthesis.md`:

```markdown
# <Topic> — Synthesis
## Position
<your thesis / recommendation / forecast / coverage summary>
## Sources
<[[note-id-1]], [[note-id-2]], ...>
## Open Questions
<unresolved>
```

Then run:

```bash
$HPR note new "Synthesis: <topic>" --tag <topic> --tag synthesis --type moc \
  --status review --body-file research/synthesis.md \
  --summary "<one-line position>" -j
```

Present to the user: your position in 2–3 sentences, the key structural beats, sources collected, and what would change your position.

---

## Process review checkpoints

Each checkpoint is a STOP point. Run the commands, state results in writing, decide whether the task has failed.

### Checkpoint 1 — after Step 3 (post-fetch)

**Purpose:** verify the corpus has enough voice diversity before reading it.

```bash
$HPR note list --status draft -j | python -c "import sys,json; d=json.load(sys.stdin)['data']; print(f'draft notes: {len(d)}')"
$HPR sources list -j | python -c "
import sys, json
from collections import Counter
from urllib.parse import urlparse
d = json.load(sys.stdin)['data']
sources = d if isinstance(d, list) else d.get('sources', [])
total = len(sources)
domains = Counter(urlparse(s['url']).netloc.replace('www.','') for s in sources if s.get('url'))
print(f'total sources: {total}, unique domains: {len(domains)}')
for dom, count in domains.most_common(10):
    pct = count / max(total, 1) * 100
    flag = ' <-- OVER 30% (concentrated)' if pct > 30 else ''
    print(f'  {count:>3}  ({pct:>5.1f}%)  {dom}{flag}')
"
```

**Pass conditions:**
- [ ] At least one note fetched from each mandatory adversarial search
- [ ] No single domain represents >30% of fetched sources (voice diversity)
- [ ] At least 5 unique non-reference voices (critical essays, named-author blog posts, peer-reviewed papers — NOT listicles or reference wikis)

**On failure:** run additional searches with diversified queries, vary the source types, seek named voices. Return to Step 2.

### Checkpoint 2 — after Steps 5–6 (post-curate)

**Purpose:** verify every source has been analyzed AND classified.

```bash
$HPR lint --rule uncurated -j
$HPR lint --rule provenance -j
$HPR lint --rule analyst-coverage -j
$HPR note list --all -j | python -c "import sys,json; from collections import Counter; notes=json.load(sys.stdin)['data']; t=Counter(n.get('tier') for n in notes if n.get('status')!='draft'); ct=Counter(n.get('content_type') for n in notes if n.get('status')!='draft'); print(f'tiers: {dict(t)}'); print(f'content_types: {dict(ct)}')"
```

**Pass conditions:**
- [ ] Zero `uncurated` issues
- [ ] Zero `provenance` **errors** — the rule itself computes the non-seed ratio and errors when under 30% on a corpus >10, so if this lint returns zero errors the guided loop fired adequately. Read its output carefully; its message tells you `non_seeds / total` directly.
- [ ] Zero `analyst-coverage` issues (at least 33% of fetched sources have a paired extract note)
- [ ] Tier and content_type distributions are nuanced (not one dominant value)
- [ ] At least two tiers represented
- [ ] At least three content_types represented

**On failure:** re-classify per-note based on each analyst's return; spawn analysts on skipped sources; **run the guided reading loop**: spawn `hyperresearch-analyst` on existing sources, collect their `next_targets`, and fetch the top 3-5 WITH `--suggested-by <source-note-id>`. You cannot proceed to Step 7 (scaffold) until the guided loop has fired at least once — the provenance chain is a load-bearing invariant.

**Specifically when `provenance` errors:** the rule message will say something like *"Only 3/19 source notes (16%) have breadcrumbs — the guided reading loop did not fire"*. Read that number literally. If it's below 30%, you MUST return to Step 4 and run the guided loop: spawn an analyst on each existing source, collect `next_targets`, fetch each target with `--suggested-by <source-note-id> --suggested-by-reason "<why>"`, then re-run Checkpoint 2. Skipping this means the draft rests on seed fetches alone and the bouncing-loop-discovered critical voices never made it into the corpus.

### Checkpoint 3 — BEFORE Step 9 (pre-draft gate — CRITICAL)

**Purpose:** this is the gate that protects the draft from being written on a broken foundation.

```bash
$HPR note list --tag scaffold -j | python -c "import sys,json; d=json.load(sys.stdin)['data']; print(f'scaffold notes: {len(d)}')"
$HPR note list --tag comparison -j | python -c "import sys,json; d=json.load(sys.stdin)['data']; print(f'comparison notes: {len(d)}')"
$HPR note list --tag extract -j | python -c "import sys,json; d=json.load(sys.stdin)['data']; print(f'extract notes: {len(d)}')"
$HPR lint --rule scaffold-prompt -j
$HPR lint --rule uncurated -j
$HPR lint --rule provenance -j
$HPR lint --rule analyst-coverage -j
$HPR lint --rule workflow -j
```

**Pass conditions:**
- [ ] Scaffold note count ≥ 1
- [ ] Zero `scaffold-prompt` issues — the scaffold body MUST contain the verbatim user prompt as its first section. This is machine-checked; the gospel rule is non-negotiable.
- [ ] Comparison note count ≥ 1
- [ ] Extract note count ≥ 30% of fetched source count
- [ ] Zero `uncurated`, `provenance`, `analyst-coverage`, `workflow` issues

**On failure:** you CANNOT write the draft. Return to the step that produces the missing artifact. If `scaffold-prompt` failed, return to Step 7 and re-write the scaffold with the user's verbatim prompt as its first section — do not fudge it.

### Checkpoint 4 — after Step 11 (post-audit)

**Purpose:** verify the audit fired and its findings were applied.

**Pass conditions:**
- [ ] `hyperresearch-auditor` was spawned twice (comprehensiveness + conformance) and both returned
- [ ] Every violation flagged has been fixed in `research/notes/final_report.md` OR explicitly rejected in writing with a reason
- [ ] If the conformance auditor flagged missing scaffold / comparison / extract notes, you returned to the relevant checkpoint and fixed it

**On failure:** spawn the auditor (or re-spawn) and apply the findings. Do not save the synthesis note until this checkpoint passes.

---

## CLI path

Find the `hyperresearch` executable from CLAUDE.md ("CLI path:" line) and store it:

```bash
HPR="<path from CLAUDE.md>"
```
