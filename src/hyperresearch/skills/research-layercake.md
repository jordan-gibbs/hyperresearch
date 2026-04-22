---
name: research-layercake
description: >
  Deep research via the LAYERCAKE architecture — a tier-adaptive pipeline
  (light / standard / full) that scales from a 3-minute $5 answer to a
  45-minute $40 adversarially-audited report. Full pipeline: prompt
  decomposition → width sweep → loci analysis → depth investigation →
  draft → four adversarial critics (dialectic / depth / width /
  instruction) → surgical patch pass → polish audit → readability
  reformat. Light/standard tiers skip depth investigation and reduce
  critic count. The patcher, polish auditor, and readability reformatter
  are TOOL-LOCKED to Read + Edit. Invoke with /research-layercake.
---

# Layercake — the default multi-agent research protocol

This is the orchestrator. You are running it as Opus. The pipeline spawns specialized subagents in every layer; you do not do their work yourself. You coordinate, assemble evidence, write ONE draft, and ship.

**Pipeline tiers** — not every query needs all 8 layers. Layer 0.5 classifies the query into a `pipeline_tier` (`light` / `standard` / `full`) that determines which layers run. Each layer section below has a **Tier gate** line at the top. Read it. The routing summary:

| Tier | Layers that run | Typical cost | Typical time |
|------|----------------|-------------|-------------|
| `light` | 0.5 → 1 (reduced) → 4 → 7 → 8 | ~$3–8 | ~3–8 min |
| `standard` | 0.5 → 1 → 4 → 5 (2 critics) → 6 → 7 → 8 | ~$10–20 | ~10–20 min |
| `full` | 0.5 → 1 → 2 → 3 → 3.5 → 4 → 5 (4 critics) → 6 → 7 → 8 | ~$30–50 | ~25–45 min |

**Three canonical rules:**

1. **PATCH, NEVER REGENERATE.** After the first draft is written (Layer 4), the draft is only ever modified by Edit hunks produced by the patcher (Layer 6) and the polish auditor (Layer 7). Both subagents are tool-locked to `[Read, Edit]`. Neither can Write a new draft. If a critic's finding would require rewriting a whole section, it escalates to you as a structural issue — not a rewrite. Keep hunks surgical: change as little as possible while addressing the issue.

2. **ARGUE, DON'T JUST REPORT** (applies at full force to `argumentative` response_format; relaxed for `structured` and `short` — see Layer 4 step 0). The layercake pipeline is engineered to push the final report toward argumentative density. Loci analysts must flag at least one dialectical locus (where sources disagree). Depth investigators must commit to a position at the end of every interim note — not just summarize. Layer 3.5 forces you to reconcile those positions in `comparisons.md` before drafting. Layer 4 requires every body section that touches a cross-locus tension to engage it explicitly. A descriptive "survey" draft is a pipeline failure for `argumentative` format — but is acceptable for `structured` format when the query asks for breadth.

3. **RESPECT THE TIER GATE.** When Layer 0.5 classifies a query as `light` or `standard`, do NOT run the skipped layers "just to be thorough." The tier classification is a product decision: simple queries should produce fast, cheap, right-sized answers. Running a full 7-layer pipeline on "What is CRISPR?" wastes $30 and produces an overwrought 8000-word report the user didn't ask for. Trust the classification. If you're uncertain, tier up — but never silently upgrade every query to `full`.

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
3. **Produce `required_section_headings`.** This is the single highest-leverage field. It is an ordered array of literal H2 heading strings the draft MUST emit in order. Population rule:
   - If the prompt contains enumerated asks (regex `\b\d[.\)]` such as "1)", "1." or leading phrase "List X, Y, Z" / "cover the following:"), produce one entry per enumerated item, in prompt order, with the prompt's verbatim noun-phrase as the heading slug.
   - If the prompt names N entities in a list and asks to "discuss", "analyze", "describe", or "evaluate" each, produce one heading per entity.
   - Otherwise, leave the array **empty**. Narrative prompts ("Write a paper about X", "How did Y happen?") do not force structure — the drafter picks its own spine.

   Example (prompt: "Your report should: 1) List major manufacturers... 2) Include images... 3) Analyze primary use cases... 4) Investigate market penetration across North America, Japan/Korea, Southeast Asia, South America"):
   ```json
   "required_section_headings": [
     "## 1. Major Manufacturers, Device Models, and Configurations",
     "## 2. Images of Representative Devices",
     "## 3. Primary Use Cases and Deployment Scenarios",
     "## 4. Regional Market Analysis"
   ]
   ```

4. Write `research/prompt-decomposition.json`:

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
  "required_section_headings": [
    "## 1. Major Manufacturers, Device Models, and Configurations",
    "## 2. Images of Representative Devices",
    "## 3. Primary Use Cases and Deployment Scenarios",
    "## 4. Regional Market Analysis"
  ],
  "time_horizons": ["2010-present", "12-month forward"],
  "scope_conditions": ["urban rail specifically, not mainline"],
  "pipeline_tier": "full",
  "response_format": "argumentative",
  "citation_style": "inline"
}
```

5. Every atomic item you put here becomes a draft requirement in Layer 4 and a critic-verifiable check in Layer 5. If you leave an atomic item out of the decomposition, the instruction-critic won't catch it. **Omit nothing the prompt names explicitly. List every numbered ask, every named entity, every format cue as a separate atomic item, even if they feel redundant.** The critic catches false-positive atomic items cheaply; it cannot catch false-negatives.

6. **Do NOT include wrapper-contract requirements here** — those live in `research/wrapper_contract.json` separately. The decomposition is ONLY about what the user's actual prompt named.

7. **Classify `pipeline_tier` and `response_format`.** These two fields control how much pipeline machinery runs and how the output is shaped. Classify them from the query itself — not from the topic's complexity, but from what the user is actually asking for.

   **`pipeline_tier`** — how much pipeline to run:

   | Tier | When to use | Signal words / patterns | What runs |
   |------|-------------|------------------------|-----------|
   | `"light"` | Query has a clear, bounded answer. Factual lookup, definition, simple explanation, short how-to, list/catalog, quick comparison. A few good sources suffice; no adversarial evidence needed; no thesis to defend. | "What is...", "How do I...", "List the...", "Define...", "What are the main...", short prompts (<50 words), single clear question | Layers 0.5 → 1 (reduced) → 4 → 7 |
   | `"standard"` | Moderate coverage across a topic. Survey, landscape overview, current-state report, multi-entity comparison, decision support. Needs breadth more than depth. | "Overview of...", "Compare X and Y", "What's the current state of...", "Which should I use for...", moderate-length prompts, 2-5 sub-questions | Layers 0.5 → 1 → 4 → 5 (2 critics) → 6 → 7 |
   | `"full"` | Deep analysis, synthesis of conflicting evidence, defended thesis, literature review, forecast with evidence chains. The adversarial architecture adds real value. | "Analyze the impact of...", "Evaluate whether...", multi-paragraph prompts, explicit request for depth/rigor, research-grade questions, contested topics where sources disagree | All layers (0.5 → 1 → 2 → 3 → 3.5 → 4 → 5 → 6 → 7) |

   **Default is `"full"`.** When uncertain, tier up. The cost of running extra layers on a simple query is wasted money (~$30); the cost of running too few layers on a complex query is a bad report.

   **`response_format`** — how the output is shaped:

   | Format | When to use | Characteristics |
   |--------|-------------|----------------|
   | `"short"` | Query expects a direct answer, not a report. | 500–2000 words. 1–5 paragraphs. Tables/lists as needed. No Opinionated Synthesis section. Thesis up front, evidence follows. |
   | `"structured"` | Query asks for coverage across entities/topics. Scannability matters more than argumentative density. | 2000–5000 words. Scannable subsections, visual hierarchy. Breadth-first: more topics, shorter treatments. Tables, bullets, visual devices liberally. Survey-style coverage is acceptable. |
   | `"argumentative"` | Query demands a defended thesis, deep analysis, or evidence-chain reasoning. | 5000–10000 words. Dense thesis-driven prose. "ARGUE, DON'T JUST REPORT" fully active. Required Opinionated Synthesis with all subsections. |

   **The two dimensions are independent.** A `light` query can be `short` (definition) or `structured` (catalog). A `full` query can be `structured` (comprehensive survey where depth investigation still matters) or `argumentative` (deep analysis). The most common pairings:

   - `light` + `short` — factual lookup, definition, simple how-to
   - `light` + `structured` — list/catalog, quick multi-entity comparison
   - `standard` + `structured` — survey, landscape overview, decision matrix
   - `full` + `argumentative` — deep analysis, literature review, forecast (the current default)
   - `full` + `structured` — comprehensive survey where adversarial depth still matters

   **`citation_style`** — how the final report handles source attribution:

   | Style | When to use | Output |
   |-------|-------------|--------|
   | `"inline"` | **Default.** User wants a verifiable research report with evidence chains. Most research queries. | `[N]` inline citations + numbered Sources list at the end |
   | `"none"` | User wants a polished expert-analysis piece with no visible citation apparatus. Magazine/editorial style. Also used for benchmark runs where references have no citations. | No `[N]` markers, no Sources section. Facts asserted authoritatively. |

   Default is `"inline"`. Only use `"none"` when the user explicitly requests an uncited report, when `research/prompt.txt` or wrapper contract specifies no citations, or when the benchmark harness sets `citation_style: "none"` in the scaffold.

**Exit criterion:** `research/prompt-decomposition.json` exists, is valid JSON, every atomic item traces to the research_query, and `pipeline_tier` + `response_format` + `citation_style` are set.

---

## Layer 1 — Width sweep

**Tier gate:** Runs for ALL tiers. For `light` tier: skip academic APIs, target 12–20 sources, limit to 2–3 fetcher batches, and move directly to Layer 4 after fetching. For `standard` and `full`: run as documented below.

**Goal:** achieve comprehensive topical coverage — every atomic item from the decomposition must have at least 3 supporting sources by the end of this layer. Target 40–100 curated sources for `standard`/`full` tiers.

### Step 1 — Coverage-aware search planning

Before spawning any fetchers, produce a **search plan** that maps the decomposition to concrete searches. This is the single highest-leverage step for comprehensiveness — an ad-hoc search finds 40 sources on the same 3 sub-topics; a planned search distributes sources across all atomic items.

1. **Read `research/prompt-decomposition.json`.** Extract every `sub_question` and every `entity` with its `required_fields`.

2. **For each atomic item, plan 2–4 distinct searches.** Each search should target a different angle:
   - One search for the core factual content of that item
   - One search for recent developments / state-of-the-art (last 2 years)
   - One search for contrarian / adversarial takes ("criticism of X", "limitations of Y", "problems with Z")
   - One search for a lateral angle (adjacent field, analogous case, upstream/downstream in a causal chain)

3. **Write the search plan to `research/temp/search-plan.md`** — a simple table:
   ```markdown
   | Atomic item | Search query | Type | Target |
   |---|---|---|---|
   | Sub-Q1: "What are the growth trends?" | "China financial industry growth trends 2025 2026" | web | factual |
   | Sub-Q1 | "China finance development forecast report" | web | recent |
   | Sub-Q1 | "China financial sector risks challenges 2025" | web | adversarial |
   | Entity: PE | "China private equity fundraising 2025 statistics" | web | factual |
   | Entity: PE | "China PE exit problems structural decline" | web | adversarial |
   | ... | ... | ... | ... |
   ```

   The plan typically has 20–60 planned searches for a `full` query. This is more searches than you'll execute — prioritize, but err toward breadth.

4. **Add academic API searches.** For each atomic item with research literature, add Semantic Scholar / arXiv / OpenAlex queries. These go in the same plan table with `type: academic`.

5. **Add at least 3 adversarial searches total** ("criticism of...", "failure of...", "why X doesn't work", "limitations of..."). The dialectic critic will punish one-sided coverage.

### Step 2 — Execute searches and build URL queue

1. **Academic APIs first.** For topics with a research literature, hit Semantic Scholar / arXiv / OpenAlex / PubMed BEFORE web search. Academic APIs return citation-ranked canonical papers; web search returns derivative commentary.

2. **Web searches from the plan.** Execute ALL planned searches from Step 1. Collect every URL that looks relevant — aim for **80–150 candidate URLs** before deduplication for `full` tier, 50–80 for `standard`. Cast a wide net. Under-searching is the #1 cause of comprehensiveness failures; over-searching costs pennies.

3. **Build and deduplicate the master URL queue.** Remove exact-URL duplicates. Remove obvious junk domains (social media share pages, login walls, 404 farms). The deduplicated queue should have **60–120 URLs** for `full` tier, 40–70 for `standard`.

   **Wikipedia SOURCE HUB rule:** Include Wikipedia URLs in the queue — they're valuable for discovery — but treat them as SOURCE HUBS, not as citable sources. When a fetcher processes a Wikipedia article, it extracts the references/citations Wikipedia links to. Those primary sources go into Wave 2 (or the same wave if capacity permits). Wikipedia itself is NEVER cited in the final report. The fetcher tags Wikipedia notes with `source-hub` automatically. If your URL queue contains Wikipedia articles, make sure to budget capacity for the follow-up primary sources they'll surface.

4. **Partition the queue into non-overlapping batches.** Split the master queue into **10–12 batches** of **8–12 URLs each**. Each batch goes to exactly ONE fetcher. **Zero overlap** — no URL appears in more than one batch. Partition strategy:
   - Group by atomic item where possible (all PE sources in one batch, all IB sources in another)
   - Mix in 1–2 cross-cutting sources per batch to avoid tunnel vision
   - Put academic papers in their own batches (they're slower to fetch — PDF extraction)

### Step 3 — Parallel fetcher waves (phased)

**Wave 1 (main wave):** Spawn **10–12 fetcher subagents in ONE message** — that's true parallel execution. Each fetcher gets its own non-overlapping batch from Step 2. This single wave should fetch 80–120 URLs in the time it previously took to fetch 30.

**CRITICAL: no token waste.** Each fetcher gets ONLY its batch. No fetcher searches for new URLs or duplicates another fetcher's work. The orchestrator did the searching in Step 2; fetchers just fetch, check quality, and summarize. If a fetcher finishes early, it's done — it does NOT go find more URLs.

**Wave 2 (gap-filling, after coverage check):** Smaller, targeted. Only spawned if Step 5 identifies uncovered items. Typically 3–5 fetchers with 5–8 URLs each, all targeting specific gaps.

### Step 4 — Tag and quality control

**Fetcher must tag every new note** with your `<vault_tag>`. Seed fetches (URLs you found directly from search, not from another note) omit `--suggested-by` entirely. Do NOT invent breadcrumb tokens like `layercake-seed` — placeholder breadcrumbs are a process violation.

**Curation happens inline.** The fetcher already deprecates junk and writes summaries. You monitor: if >30% of fetches come back as junk, the URL queue was bad — reassess before continuing.

### Step 5 — Coverage check (MANDATORY)

After Wave 1 returns, run the coverage check before proceeding:

1. **List fetched sources:** `$HPR search "" --tag <vault_tag> --json` — count substantive (non-deprecated) notes.

2. **Map sources → atomic items.** For each atomic item in the decomposition, identify which fetched sources serve it (by title/summary). Mark each item as:
   - **Well-covered** (4+ relevant sources)
   - **Adequate** (2–3 sources)
   - **Thin** (1 source)
   - **Uncovered** (0 sources)

3. **Wave 2 fetch for gaps.** For every `thin` or `uncovered` item:
   - Run 2–3 targeted searches specifically for that item
   - Spawn 3–5 fetchers with gap-filling URLs (non-overlapping batches, same rules as Wave 1)
   - This wave is smaller (typically 20–40 URLs) but surgically targeted at weak spots

4. **Write coverage report.** After Wave 2, write `research/temp/coverage-gaps.md`:
   - List every atomic item with its coverage status and source count
   - Any item still at 0 sources after Wave 2 is a genuine gap — flag it prominently so the drafter acknowledges the limitation explicitly

**Do NOT skip the coverage check.** The comprehensiveness score is directly proportional to how many atomic items have multi-source coverage. One targeted second-pass fetch (+2 minutes, +$2) can prevent a 5-point comprehensiveness drop.

### Source count targets

| Tier | Minimum sources | Target sources | Fetchers per wave | Waves |
|------|----------------|---------------|-------------------|-------|
| `light` | 10 | 15–25 | 3–5 | 1–2 |
| `standard` | 30 | 40–60 | 8–10 | 2 |
| `full` | 50 | 60–120 | 10–12 | 2–3 |

These are substantive (non-deprecated) note counts. Junk doesn't count toward the minimum.

**Exit criterion for Layer 1:** minimum source count met AND coverage check shows no `uncovered` atomic items (thin is acceptable, uncovered is not). If you fall short after two waves, proceed anyway but write `research/temp/coverage-gaps.md` listing what's missing so the drafter handles it.

---

## Layer 2 — Loci analysis (parallel, 2 analysts)

**Tier gate:** SKIP entirely for `light` and `standard` tiers — proceed directly to Layer 4. Only `full` tier runs loci analysis.

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

**Tier gate:** SKIP entirely for `light` and `standard` tiers. Only `full` tier runs depth investigation.

**Goal:** produce ONE `interim-{locus}.md` note per locus with dense synthesis that the orchestrator will draft from in Layer 4.

1. **Spawn K `hyperresearch-depth-investigator` subagents in parallel.** Pass each:
   - `locus` — the full locus object from `research/loci.json`
   - `research_query` — canonical, verbatim
   - `corpus_tag` — `<vault_tag>`

2. **Each investigator writes ONE interim note** into the vault with `type: interim` and tags `<vault_tag>` + `locus-<locus-name>`. Return value is the note id.

3. **Wait for all K to complete.** Investigators can fail independently. Proceed with whichever succeeded. If >50% failed, reassess — the loci analyst may have produced un-investigatable questions.

4. **Read the interim notes.** Before writing the draft, use `$HPR search "" --tag <vault_tag> --type interim --json` to list them, then `$HPR note show <id1> <id2> ... -j` to read them in one call. Hold the Committed Position sections in your context — they are the load-bearing input to Layer 3.5 and Layer 4.

---

## Long-source delegation (on-demand, any time after Layer 1)

**Goal:** when a single long source (>5000 words) is load-bearing to the research_query or to a depth locus, delegate end-to-end analysis to the `hyperresearch-source-analyst` subagent instead of reading it inline. The analyst runs on Sonnet with a 1M-token context window, reads the full source, and writes a structured analytical digest as a new `type: source-analysis` note backlinked to the original. Downstream layers consume the digest as a dense proxy for the source — avoiding context-cost duplication and preserving far more substance than a fetcher summary alone.

**Why this delegation exists:** the fetcher (Haiku) writes a 1-2 paragraph summary at fetch time. That's often enough for tangential or thin sources. But for a 70-page mechanism-design paper, a 500-page regulatory filing, or a long academic survey, a fetcher summary is structurally insufficient — details that matter for the research_query get compressed away. Depth investigators can read such sources for their specific locus, but they're scoped to that locus and may miss cross-locus substance. The source-analyst is the single-source deep-reading role that fills that gap.

### Trigger rule

Delegate to `hyperresearch-source-analyst` when ALL three conditions hold:

1. **Length threshold:** the source's `word_count` (visible on `$HPR note show <id> -j`) exceeds ~5000 words.
2. **Relevance:** the source is relevant to the research_query — not tangential, not off-topic. Judge from the fetcher summary + title + tags; if uncertain, err toward delegating (the analyst can produce a "not-relevant" verdict cheaply).
3. **No existing analysis:** no `type: source-analysis` note already exists for this source. Check via `$HPR search "" --tag <vault_tag> --type source-analysis --json` and look for an incoming link from `[[<source_note_id>]]`.

**Cap: at most 6 source-analysts per query.** Same ceiling as depth investigators; same cost reasoning. Beyond that, depth investigators read long sources inline for their specific locus — the source-analyst is for the most load-bearing sources only.

### Who can trigger a spawn

- **You (the orchestrator)** in Layer 1 (if a newly-fetched long source is clearly load-bearing) or between layers (when you realize a particular source deserves deeper treatment than a fetcher summary provides).
- **A depth investigator** in Layer 3 — if the investigator encounters a long source central to its locus AND no analysis exists, the investigator can spawn the source-analyst via its own `Task` tool. The analysis feeds the investigator's interim note.

### How to spawn

Standard 3-piece Task contract (same as every other subagent) plus the source-specific inputs:

```
subagent_type: hyperresearch-source-analyst
prompt: |
  RESEARCH QUERY (verbatim, gospel):
  > {{paste contents of research/prompt.txt character-for-character}}

  PIPELINE POSITION: You are a leaf subagent available to Layers 1–4 for deep
  end-to-end analysis of ONE long source. Prior layers have fetched the
  source into the vault; your digest feeds the depth investigator's interim
  note, the Layer 3.5 comparisons, or the Layer 4 draft directly. You do
  NOT spawn other subagents.

  YOUR INPUTS:
  - source_note_id: <the vault note id of the long source>
  - output_path: /tmp/source-analysis-<source_note_id>.md
  - vault_tag: <vault_tag>

  Read the source end-to-end, produce the structured analysis digest,
  and report back with the new note id + your relevance verdict.
```

### How the output is consumed

- **Depth investigators** cite the analysis by note id from their interim note's Committed position section.
- **Layer 3.5 comparisons** can reference the analysis when a cross-locus tension turns on a specific long source.
- **Layer 4 draft** can cite the analysis note OR the original source for the same substantive claim — both are valid. Prefer the analysis note when you want to signal "the full digest backs this sentence"; prefer the original source when you're citing a specific quote or number extracted from it.
- **Layer 5 critics** may consume the analysis as pre-digested evidence. The dialectic critic, in particular, can compare the analyst's Key findings list against the draft's claims to spot missed substance.

### When NOT to delegate

- Short sources (<5000 words): the fetcher summary is enough.
- Sources that are already fully summarized in their abstract and first page (some blog posts, some press releases).
- When the cap has been reached — fall back to depth-investigator partial reads.
- When the source is in a language the analyst can't read reliably (test with a non-ASCII spot-check if unsure).

---

## Layer 3.5 — Cross-locus comparisons (orchestrator, bridge step)

**Tier gate:** SKIP entirely for `light` and `standard` tiers (no loci = no comparisons). Only `full` tier runs this step.

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

**Tier gate:** Runs for ALL tiers. For `light` tier: you have only the width corpus (no interim notes, no comparisons.md). For `standard`: same — width corpus only, no depth artifacts. For `full`: full access to all prior-layer artifacts.

**Goal:** write ONE draft that weaves the width corpus with the depth interim notes AND engages the cross-locus tensions from `research/comparisons.md` AND mirrors the atomic items from `research/prompt-decomposition.json`, following the modality file's substance rules.

0. **Read `response_format` from `research/prompt-decomposition.json` and adapt.** This field controls the draft's shape:

   **`"short"` format:**
   - Target **500–2000 words** (English) or **1500–6000 characters** (Chinese/CJK). Direct answer, 1–5 paragraphs. Tables/lists when appropriate.
   - Thesis up front in the first sentence or paragraph. Evidence follows compactly.
   - **No Opinionated Synthesis section** — the entire response IS the synthesis.
   - Still honor the modality's substance rules. Just compress.
   - This is NOT a lesser draft — it's a *calibrated* draft. A 3-paragraph answer with a clear committed position beats a 10-page report the user didn't ask for.

   **`"structured"` format:**
   - Target **2000–5000 words** (English) or **6000–15000 characters** (Chinese/CJK). Scannable subsections with clear visual hierarchy.
   - **Breadth-first:** cover more ground with shorter treatments per topic. Each subsection should be 150–400 words (or 500–1200 characters for CJK), not 800.
   - Use tables, bullet lists, comparison matrices, and visual devices *liberally*. A well-structured table can replace 3 paragraphs of prose.
   - The "ARGUE, DON'T JUST REPORT" rule is **relaxed for body sections** — survey-style descriptive coverage is acceptable when the query asks for breadth. The Opinionated Synthesis at the end is where you argue.
   - **Include the Opinionated Synthesis** with all required subsections unless the wrapper says otherwise.

   **`"argumentative"` format (default):**
   - Target **5000–10000 words** (English) or **20000–25000 characters** (Chinese/CJK). Dense thesis-driven prose. "ARGUE, DON'T JUST REPORT" fully active in every section.
   - **CJK length calibration:** Chinese references average ~22-26K characters. A report under 18K chars will lose on comprehensiveness; a report over 30K chars dilutes good content with padding. For Chinese queries, aim for the CHARACTER count targets, not English word counts. 1 Chinese char ≈ 1.5-2 English words of information.
   - This is the current default behavior — all existing Layer 4 rules below apply at full force.
   
   **Length discipline across all formats:** Target the MIDDLE of your character-count range. Under-length loses on comprehensiveness; over-length loses on readability and dilutes good content with padding. A 22K-char Chinese report that is dense, structured, and evaluative will outscore a 50K-char report that is verbose and repetitive. A focused 7000-word English report beats a meandering 15000-word one.

1. **Re-read `research/prompt-decomposition.json`.** Every atomic item named there is a draft requirement. For each sub-question, the draft must answer it. For each named entity, the draft must address it (in a dedicated section, subsection, or paragraph, as the decomposition's structure implies). For each required format, the draft must honor it. You are mirroring the user's structure, not reorganizing the topic around your own analytical axes.

1a. **Check `research/temp/coverage-gaps.md`** (if it exists). Any atomic item listed here had insufficient source coverage from Layer 1. For these items: still address them in the draft (they're prompt requirements), but acknowledge the limitation explicitly — "available evidence on X is limited" or similar — rather than silently omitting them or fabricating claims without source support. A well-flagged gap is better than a false confidence or a missing section.

2. **Re-read `research/comparisons.md`.** The tensions there are your argumentative spine. Keep the document open in your working context while drafting.

3. **Read your modality file now.** Open `.claude/skills/hyperresearch/SKILL-<modality>.md` and apply its substance rules. Pay particular attention to the modality's insight-generation rules — these are the rules that push you from reporting evidence to interpreting it.

4. **Read SKILL.md's Step 9 (draft conventions).** The dispatcher's drafting rules (length discipline, visual-device encouragement, filler bans) apply to the layercake draft the same way they apply to a single-pass draft. **Note:** layercake's citation behavior is controlled by `citation_style` in step 8, which may differ from SKILL.md's default citation guidance. Step 8 takes precedence.

5. **Structure the draft around the decomposition.** When the prompt named 5 entities in a list, the draft should typically have 5 sections or subsections in that order. When the prompt asked for a mind map, include a mind map. When the prompt named sub-questions A/B/C, answer them in that order. Your own analytical framing belongs in the synthesis section at the end — NOT as the body's structural spine. This single rule is the highest-leverage insight-following move available.

   **Consider numbering sections** for formal structure. Numbered headings (e.g., `## I. 执行摘要`, `## II. 宏观背景`) with lettered subsections (`### A. 子主题`) signal structure and make hierarchy explicit. This is appropriate for analytical and advisory reports. For technical how-tos or informal overviews, unnumbered headings may read better. Use your judgment based on the query's tone and the `response_format`.

   **HARD GATE on `required_section_headings`.** If `research/prompt-decomposition.json` has a non-empty `required_section_headings` array, the draft's ordered top-level H2 list MUST equal that array element-wise before the body proceeds to the Opinionated Synthesis (or any terminal section). Every heading string from `required_section_headings` appears in order as a literal H2. Your own analytical framing (cross-tension narratives, methodological caveats, etc.) goes INSIDE those sections or inside the terminal Synthesis — NEVER as an additional top-level H2 that sits between or before the required headings. If `required_section_headings` is empty, this gate does not apply and you pick the spine.

6. **Write the draft to `research/notes/final_report.md`.** Structure:
   - **Executive summary (2-4 paragraphs)** at the top, immediately after the H1 title. State the core thesis, key findings, and top-line numbers. This is not optional — reference-quality reports always open with a summary that lets the reader grasp the conclusion before reading the evidence. For Chinese reports, this should be 400-800 characters.
   - Opening paragraphs that state the thesis / framing. Your thesis must commit to a position — not "this report surveys X" but "X is true (or X is false, or X is the right frame) because..." — grounded in the cross-locus comparisons you identified.
   - Body sections mirroring the decomposition's structural cues. **Each body section that touches a tension named in `comparisons.md` must engage that tension explicitly** — by name, with a paragraph that commits to a reading of the disagreement, not just reports both sides.
   - **Each body H2 section should be 1500-3000 characters (Chinese) or 800-1500 words (English).** Sections shorter than this threshold are under-developed — go deeper. Add sub-arguments, specific data points, named examples, counter-arguments and responses, and forward-looking implications. A section that just states "X is true [3]" and moves on is wasting evidence the width corpus and depth investigators surfaced.
   - **Comparative analysis section** — a dedicated H2 (e.g., "比较分析" or "Comparative Analysis") that synthesizes across body sections. This is where cross-cutting themes, ranking tables, and trade-off matrices go. Reference articles almost always include this; our reports often skip it and jump to conclusions.
   - Closing section per the modality rule. Where the modality demands a reasoned position (synthesize, compare, forecast), that position must visibly incorporate the strongest cross-locus tensions — not average them out into hedged prose. **Include explicit strategic recommendations** — bulleted, actionable items. Not just "X is the best sector" but "practitioners should:" followed by a bold-labeled bullet list.
   
   **Structural completeness check before writing:** Before you start writing, verify your outline has: (a) executive summary, (b) context/background section, (c) one H2 per major topic from the decomposition, (d) comparative analysis section, (e) conclusion with recommendations, (f) Sources list if `citation_style` is `"inline"`. If any of these is missing from your mental outline, add it. Reports that skip the exec summary or comparative analysis section score systematically lower on instruction-following and comprehensiveness.

7. **Insight-generation rules (applied to every body section):**
   - **Commit, don't hedge.** Sentences like "some argue X while others argue Y" are allowed as setup but MUST be followed by "the evidence weighs toward X because Z" or an equivalent committed reading. Pure "on the one hand / on the other hand" prose is low-insight reporting.
   - **Interpret, don't just assert.** For every 2–3 factual claims, there should be at least one interpretive beat — a sentence or clause that draws a conclusion the sources themselves didn't draw. Interpretive density drives the insight dimension; descriptive claim stacks suppress it.
   - **Privilege committed investigator positions.** Each `## Committed position` section from a depth investigator is a claim the draft can assert directly ("the FRMCS evidence demonstrates that..."). These are your strongest argumentative levers — use them, don't soften them into "the literature suggests...".
   - **Every body section argues, not just the synthesis.** A common failure mode is drafts that save commitment for the synthesis section and leave body sections in descriptive / reporting mode. That doesn't work — the body is where evidence is introduced, and the body is where arguments should LAND. Each H2 should end with (or contain) at least one sentence that commits to a reading of that section's evidence. "Here is how this evidence is best understood" belongs in every section, not just the final one.
   - **Weave named tensions INLINE with immediate resolution.** When a cross-locus tension from `comparisons.md` is relevant to a body section, engage it inline in that section — name the tension, quote the strongest version of each side, and commit to a reading — then move on. Do NOT gather tensions into a dedicated "Source Tensions" H2 at the end; that gives the reader an unresolved buffet. Reference-quality reports name tensions where they arise in the doctrinal or analytical flow and resolve them immediately.
   - **Prescriptive specificity when evidence supports it.** When an investigator's `## Committed position` contains a specific threshold, number, rule, or named mechanism, preserve that specificity in the draft. Do not soften "manufacturer liability attaches when handover warnings fall below 10 seconds at highway speeds" into "manufacturer liability attaches when warnings are too brief." The precision is the authority; softening it to LLM-directional language drops the report's prescriptive weight. If a recommendation in the draft reads abstract, ask yourself what specific threshold or rule the evidence supports, and say it.

8. **Source attribution (controlled by `citation_style`).** Read `citation_style` from `research/prompt-decomposition.json`.

   **If `citation_style` is `"inline"` (default):** Include inline `[N]` citations on load-bearing claims. The `[N]` numbering is deterministic: first cited source is `[1]`, next new source is `[2]`, and so on. End the report with a numbered Sources list matching the inline citations. Aim for moderate citation density — enough to ground key claims (30-60 total citations for an argumentative report) without cluttering every sentence. Wikipedia NEVER appears in the Sources list.

   **If `citation_style` is `"none"`:** Do NOT include inline `[N]` citations anywhere. Do NOT include a Sources/References section. Assert facts directly and authoritatively: "中国直接融资比重仅为29%" — not "中国直接融资比重仅为29% [3]." You know which sources support which claims from the width corpus and interim notes — use that knowledge to write with confidence, but do not expose the citation apparatus. The report reads as authoritative expert analysis, not annotated literature review.

8a. **Use bullet lists liberally.** Bullet lists make reports scannable and structured. Use them for:
   - Sub-point enumeration within analysis sections (优势/劣势/机遇/挑战 for each topic)
   - Policy measures and regulatory requirements
   - Recommendations (always bulleted, never buried in prose)
   - Comparative points within or across topics
   - Any passage that enumerates 3+ items in a sentence — convert to a list

   **Pattern — bold category labels within bullet lists:**
   ```
   **优势：**
   - Point one with specific number
   - Point two with mechanism named

   **挑战：**
   - Point one
   - Point two
   ```

   Every H2 body section should contain at least one bulleted enumeration where the content is enumerative. Do NOT force bullets where the content is flowing argumentative prose — bullets serve enumeration, not narration.

8b. **Short paragraphs.** No paragraph should exceed **400 characters** (Chinese/CJK) or **800 characters** (English). Target average paragraph length of **150-300 characters** (Chinese) or **300-600 characters** (English). One idea per paragraph. If a paragraph covers both "what happened" and "what it means," split into two.

8c. **Short sentences.** Target average sentence length of **50-80 characters** (Chinese) or **80-150 characters** (English). Split compound sentences with multiple semicolons, parenthetical asides, or relative clauses. Each sentence expresses one idea. Avoid: "由于X因素的影响，加之Y政策的推动，再叠加Z趋势的催化，该领域呈现出..."  Instead: "X因素推动了增长。Y政策加速了这一趋势。Z进一步放大了效果。"

8d. **Use bold for emphasis and visual hierarchy.** Bold key terms on first mention, key statistics and thresholds, verdict/judgment labels, and category labels within bullet lists. Examples: **买方投顾模式**, **29%直接融资比重**, **核心判断：**, **SWOT分析**. The goal is scannability — a reader skimming should be able to pick out key terms and numbers from bold text alone.

8e. **Write evaluatively, not descriptively.** The report is expert analysis, not a neutral survey. Where the evidence supports a clear reading, state it directly:
   - Instead of "可能存在风险" → **"面临结构性挑战"**
   - Instead of "some evidence suggests" → **"evidence strongly indicates"**
   - Instead of "various factors contribute" → **"three key drivers dominate"**

   Include explicit verdict statements in every H2 section. Every body section should end with a committed reading of that section's evidence.

   **Guardrail: do NOT overstate genuinely uncertain claims.** When evidence is contested, preliminary, or speculative, hedging is honesty, not weakness. "This outcome is likely IF current trends continue" is better than "This outcome WILL happen." The evaluative rule applies to claims the evidence supports — not to forecasts on open questions or actively-debated topics where the sources themselves disagree.

9. **Honor wrapper contracts.** If `research/wrapper_contract.json` specifies a required terminal section (e.g., `## Opinionated Synthesis`), include it. If it specifies forbidden body sections, do not use them.

10. **Hygiene.** The final report MUST NOT contain:
    - YAML frontmatter
    - Any scaffold-only section (the polish auditor strips these if they leak, but prevention is cheaper)
    - The user prompt verbatim
    - Literal "User asked:" or similar prompt-echo preambles
    - `research/comparisons.md` content verbatim — comparisons.md is planning, not body content
    - `research/prompt-decomposition.json` content verbatim — decomposition is planning, not body content

10a. **Vocabulary prohibitions.** The following pipeline-internal terms are SCAFFOLDING. Never write them into reader-facing prose. Audits of past runs found them leaking into the body text of 13 of 15 final reports, and graders mark those reports down on readability and instruction-following. The polish auditor strips these as a backstop, but preventing the leak at draft time is cheaper than rewriting afterward.

    **Forbidden in body prose:** `Locus <N>`, `Tension <N>`, `comparisons.md` / `research/comparisons.md`, `committed reading`, `committed position` (as self-reference), `cross-locus`, `width corpus`, `depth investigation`, `layercake` / "layercake final report", `per the scaffold` / `from the scaffold`, bare `loci` when referring to pipeline taxonomy, `[[interim-report-*]]` wikilinks, `[I\\d+]` citation format.

    **When you need to reference a cross-locus tension captured in `comparisons.md`:** name the substantive dynamic the tension describes. Not "Tension 2" but "the isolation-versus-competition question." Not "Locus 3's verdict" but "the 500K-threshold evidence commits:". The reader does not know about loci, tensions, or comparisons.md — do not teach them the pipeline's internal vocabulary just to cite it.

    **When you reference an interim note's findings:** If `citation_style` is `"inline"`, use the `[N]` numeric citation that corresponds to the interim note in the Sources list. If `"none"`, assert the finding directly in authoritative prose. Either way, the internal note id (`interim-report-*`) is never reader-facing.

    **"Loci" as a domain word** — if your topic is one where "locus" is a legitimate domain term (molecular biology, law, neuroscience), the ban applies only to pipeline-taxonomy usage. A sentence like "the coding locus lies within exon 3" is fine; "three loci converged on the same finding" is a leak.

11. **Write-once.** You write this draft once. After this point, the draft is only modified by Edit hunks from the patcher and polish auditor. Do NOT re-draft.

---

## Layer 5 — Adversarial critique (parallel, 4 critics)

**Tier gate:** SKIP entirely for `light` tier — proceed directly to Layer 7 (polish). For `standard` tier: spawn only **2 critics** — `width-critic` (catches missed coverage) and `instruction-critic` (catches prompt-adherence gaps). Skip dialectic and depth critics. For `full` tier: spawn all 4 as documented.

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

**Tier gate:** SKIP entirely for `light` tier (no critics = no findings to patch). For `standard` and `full`: run as documented.

**Goal:** apply critic findings to the draft as surgical Edit hunks. Zero regeneration.

0. **Skip gate (optional — for advanced users).** Before spawning the patcher, check whether `research/skip-patcher.txt` exists. If it does, the invoker has requested that Layer 6 be bypassed for this run. In that case, skip steps 1–6 entirely and record a minimal log:

```bash
# Count findings across all four critic JSON files
total=$(jq -s '[.[] | .findings | length] | add' \
  research/critic-findings-dialectic.json \
  research/critic-findings-depth.json \
  research/critic-findings-width.json \
  research/critic-findings-instruction.json 2>/dev/null)
cat > research/patch-log.json <<EOF
{"total_findings": ${total:-0}, "applied": [], "skipped": [{"reason": "patcher-skipped-by-invoker"}], "conflicts": [], "orchestrator_escalated": []}
EOF
```

Then proceed directly to Layer 7 (polish auditor). Do NOT spawn the patcher and do NOT attempt to apply findings yourself — the skip flag is respected as-is. Most runs should not use this gate; it exists for users who want to compare draft quality with and without surgical patching.

1. **Pre-create the patch log stub.** The patcher is tool-locked to `[Read, Edit]` — it cannot Write. Edit can only modify files that already exist. So you (the orchestrator) MUST write the canonical stub first, which the patcher will then Edit to populate:

```bash
echo '{"total_findings": 0, "applied": [], "skipped": [], "conflicts": [], "orchestrator_escalated": []}' > research/patch-log.json
```

   The schema above is canonical. The patcher's only job on this file is to Edit the existing keys — `total_findings` becomes an integer, the four arrays get populated. **The patcher MUST NOT invent alternate schemas** like `{orchestrator_structural_fixes, patcher_hunks}` or counts-only variants. Downstream tooling assumes the canonical shape.

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
   - **Is the patch log still the empty stub `{"total_findings":0,"applied":[],"skipped":[],"conflicts":[],"orchestrator_escalated":[]}`?** If yes, the patcher failed to log — its Task result will contain the real log inline. Read the Task result, parse out the JSON, and write it to `research/patch-log.json` yourself via Bash so downstream lint rules see it.

4a. **Handle `orchestrator_escalated` findings (structural restructures).** The patcher populates this array with findings where `requires_orchestrator_restructure: true` — most commonly, structural-mirror-check findings from the instruction critic (wrong H2 order / missing required heading / extra H2). The patcher's tool-lock cannot safely move / rename H2 sections, so YOU (the orchestrator) handle them here, before Layer 7:
   - For each entry, read the `issue` field to understand which H2 in the draft needs to move, be added, or be renamed.
   - Apply the restructure via hand-written Edit calls on `research/notes/final_report.md`. You have Write and Edit access — the tool lock only applies to the patcher and polish auditor subagents, not to you.
   - Preserve the body content within each H2 section — you are moving / renaming / inserting headings, not regenerating prose. If a new heading is added and its body needs fresh content, write a short evidence-grounded paragraph for it, citing notes from the width corpus or relevant interim notes.
   - Log what you changed in a new `research/orchestrator-restructure-log.md` file (plain markdown, one bullet per change) so downstream lint rules can see this step happened.
   - Never regenerate a whole section or the whole draft. The "patch not regenerate" invariant still binds you — you have broader tools but not broader license.

5. **Do not apply the revisions yourself.** You MUST spawn the patcher (revisor) subagent. Do NOT call Edit directly on `research/notes/final_report.md` in Layer 6 — the revisor has the tool-lock invariants (surgical-edit discipline, conflict resolution, integrate-don't-caveat rule) baked into its prompt. Bypassing it defeats the entire adversarial-review architecture. If the revisor returns an empty result or appears to have failed, re-spawn it — don't fall back to doing it yourself.

6. **Do not re-spawn the revisor on the same findings** unless you've modified the findings. The revisor's second run on identical input is a waste.

---

## Layer 7 — Polish audit (`hyperresearch-polish-auditor`)

**Tier gate:** Runs for ALL tiers. Every report gets a polish pass regardless of tier.

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
   - Citation cleanup per `citation_style`: if `"none"`, strips all `[N]` and the Sources section; if `"inline"`, strips only Wikipedia-sourced citations
   - Hygiene leaks (YAML frontmatter, scaffold sections, prompt echoes)
   - Filler phrases ("It is worth noting", "Importantly", etc.)
   - Redundant sentences / paragraphs that restate prior content
   - Run-on sentences and over-long paragraphs (breaks into smaller units via Edit)

4. **The polish auditor ESCALATES** structural mismatches (wrong format for the prompt, missing required sections, etc.) rather than fabricating content to fix them. Read the escalations in the polish log. If the escalation names a structural issue (e.g., "user asked for a ranked list; draft is unranked prose"), you have one shot to fix it — craft the restructure yourself with hand-written Edits, then ship.

5. **Sanity-check net length.** Polish should have NEGATIVE net char delta. If the polish log shows positive net chars added, something went wrong — polish is for cutting, not expanding.

6. **Do not apply polish edits yourself.** Same rule as Layer 6 — the polish auditor's tool lock is the mechanism. Calling Edit directly in Layer 7 bypasses the hygiene-check and filler-detection logic baked into the auditor's prompt. If the auditor returned empty, re-spawn it; don't do the work yourself.

---

## Layer 8 — Readability reformat (`hyperresearch-readability-reformatter`)

**Tier gate:** Runs for ALL tiers. Every report gets a readability pass.

**Goal:** final structural pass for readability — break paragraphs to cap (400 chars CJK / 800 chars EN), convert enumerations to bullet lists, inject bold labels, split long sentences. If `citation_style` is `"none"`, also strip any residual `[N]` citations and Sources section. Does NOT change any substantive content.

1. **Pre-create the reformat log stub.** The reformatter is tool-locked to `[Read, Edit]` — same pattern as Layer 6 and 7.

```bash
echo '{"paragraphs_split": 0, "subheadings_added": 0, "lists_created": 0, "tables_created": 0, "sentences_split": 0, "citations_stripped": 0, "sources_section_removed": false, "net_char_delta": 0}' > research/reformat-log.json
```

2. **Spawn the readability reformatter ONCE.** Pass:
   - `research_query` — canonical, verbatim
   - `draft_path` — `research/notes/final_report.md`
   - `reformat_log_path` — `research/reformat-log.json` (already stubbed above)

3. **The reformatter applies:**
   - Citation cleanup: if `citation_style` is `"none"`, strip residual `[N]` and Sources section; if `"inline"`, leave intact
   - Paragraph splits: any paragraph exceeding 400 chars (CJK) or 800 chars (EN)
   - List conversions: enumerative passages → bullet lists with bold labels
   - Bold injection: key terms, statistics, category labels
   - Sentence splits: sentences exceeding 80 chars (CJK) or 150 chars (EN)
   - Whitespace cleanup

4. **The reformatter DOES NOT:**
   - Add, remove, or change any substantive claims
   - Add H3 subheadings (the drafter owns section structure)
   - Rename H2 headings
   - Move content between sections
   - Change the report's language
   - Add horizontal rules (`---`)

5. **Check the reformat log.** Net char delta should be NEGATIVE if citations were stripped (they consume significant characters). If no citations were present, delta may be slightly positive from list formatting.

6. **Do not apply reformat edits yourself.** Same tool-lock discipline as Layer 6 and 7.

---

## After Layer 8: audit findings + lint gate

0. **Required-artifacts integrity check.** Before declaring the run complete, verify every expected pipeline artifact exists. Run:

```bash
for f in research/critic-findings-dialectic.json \
         research/critic-findings-depth.json \
         research/critic-findings-width.json \
         research/critic-findings-instruction.json \
         research/patch-log.json \
         research/polish-log.json \
         research/reformat-log.json; do
  test -f "$f" || echo "MISSING: $f"
done
```

   If any artifact is missing, the responsible layer failed silently. Re-spawn the responsible agent ONCE with the missing output path as its explicit required output. If it fails a second time, write a minimal stub (`{"findings":[]}` for critic files, canonical empty-log schema for patch-log.json / polish-log.json) and log the failure in the run log before proceeding — never let a pipeline step leave a missing artifact.

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

10. **Orchestrator scratch files live under `research/tmp/`.** Any test JSON you build while debugging a critic output, any Python assembly script, any `.pkl` / `.txt` / `build_*.py` helper — these go in `research/tmp/` or `<run_dir>/tmp/`. Never emit scratch files directly under `research/`. The top-level `research/` namespace is reserved for the canonical pipeline artifacts listed in the integrity check above.

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
