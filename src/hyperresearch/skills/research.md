---
name: research
description: >
  Deep research on any topic. Searches the web, fetches sources with a headless browser,
  follows links to primary sources, builds a searchable knowledge base, and synthesizes
  findings. Use when the user asks to research, investigate, or learn about a topic.
  Trigger: /research
---

# Deep Research Skill

## Step 0: Clarify the request

Before doing ANY research, evaluate the user's request. If it is vague, ambiguous, or could go in multiple directions, **ask clarifying questions first**. Do not guess — ask. Examples:

- "Research AI models" → Ask: "Which aspect? Training techniques, specific architectures, benchmarks, a particular company's models, deployment strategies?"
- "Find out about this company" → Ask: "What specifically? Financials, leadership, products, tech stack, culture, recent news?"
- "Look into transformers" → Ask: "The neural network architecture, or a specific variant? Are you interested in the theory, practical implementation, or recent alternatives like Mamba?"

Ask 1-3 focused questions. Once you understand the scope, proceed. If the request is already specific and clear, skip this step and start researching immediately.

## Step 0.5: Classify the request and pick a protocol (MANDATORY)

Different research requests need fundamentally different strategies. Source counts, primary/secondary mix, section structure, target length, analytical mode — all change based on the request shape. A single universal protocol is wrong. **Before Step 1, classify the request into one of the 7 types below and state your classification in writing** (in working memory or `/tmp/scaffold.md` — NOT a hyperresearch note).

### The 7 request types

| Type | Name | Use when |
|---|---|---|
| 1 | **Canonical Knowledge Retrieval** | Mature field with textbook chapters or canonical survey papers; a domain expert would start by citing a classic source. |
| 2 | **Market / Landscape Mapping** | Enumerable competitive analysis — list of companies, products, vendors with attributes. |
| 3 | **Engineering / Technical How-To** | User is trying to DO something. Ideal answer is a procedure or method selection. |
| 4 | **Interpretive / Humanities Analysis** | Subject is a text, work, tradition, or cultural phenomenon. Good answer takes a position and defends it. |
| 5 | **Comparative Evaluation** | Prompt names multiple alternatives by name and expects a matrix + pick. |
| 6 | **Emerging / Cutting-Edge Research** | Most useful material is <2 years old; best sources are arXiv/bioRxiv/conference papers. |
| 7 | **Forecast / Strategy / Recommendation** | Asks what will happen or what should be done; ideal answer commits to a prediction or prescription. |
| 0 | **General Research (fallback)** | Doesn't cleanly fit one type, or genuinely spans multiple. |

Overlap is expected. Classify a **primary** type and, if applicable, a **secondary** type. Apply the parameter block for the primary; borrow special rules from the secondary.

### State your classification

Before Step 1, write this down:

1. **Primary type**: #N — one-sentence justification tied to the prompt.
2. **Secondary type**: #N or "none".
3. **Applied parameters** (5 lines): source strategy, target length, opening-section shape, target H2 count, analytical mode.

Refer back to this throughout the workflow. It's how you avoid drifting into one-size-fits-all defaults.

---

## Request-type parameter blocks

Pick the block for your primary type and apply it. These **override** the generic defaults in Step 3 (source count) and Step 9 (writing constraints).

### Type 1 — Canonical Knowledge Retrieval

- **Source strategy:** 5–15 primary (seminal papers, textbooks, canonical surveys) + 5–15 secondary (recent reviews, textbook chapters). Primary-heavy. Read primary DEEP.
- **Target length:** 6,000–10,000 words
- **Opening:** historical / conceptual progression — how the field arrived at current consensus
- **H2 count:** 10–15, sequenced by dependency (concept → result → consequence)
- **Analytical mode:** explain WHY canonical results hold; compare competing formulations; signal which textbook to start with
- **Special rule:** sequence content by dependency, not by source. A reader should need sections 1 and 2 to understand section 3.

### Type 2 — Market / Landscape Mapping

- **Source strategy:** 20–50 secondary (analyst reports, press, official docs) + 5–10 primary (filings, product specs, API docs). Secondary-heavy — triangulation across many descriptions is correct here.
- **Target length:** 5,000–9,000 words
- **Opening:** market definition + segmentation + the framework used to score vendors
- **H2 count:** 8–14, one per vendor *cluster* or category — NEVER one per individual vendor
- **Analytical mode:** take a position on who is winning and why
- **Special rule:** at least one comparison matrix in the body, with common axes, is MANDATORY. Never list vendors in isolation.
- **Special rule:** if the user asked for rankings, deliver them with confidence. Rankings without commitment are worthless.

### Type 3 — Engineering / Technical How-To

- **Source strategy:** 5–15 primary (papers, docs, GitHub repos, RFCs, standards) + 5–15 secondary (blog posts, tutorials, StackOverflow). Roughly balanced.
- **Target length:** 4,000–8,000 words
- **Opening:** the problem statement + the constraint landscape — what makes this hard, why naive approaches fail
- **H2 count:** 8–14
- **Analytical mode:** pick a recommended approach; explain when to use alternatives
- **Special rule:** if a method has a reference implementation, link it and characterize it
- **Special rule:** include a decision tree or selection matrix ("use X when..., use Y when...")

### Type 4 — Interpretive / Humanities Analysis

- **Source strategy:** 3–10 primary (the work itself, key scholarly monographs, canonical commentary) + 10–25 secondary (critical essays, interviews, reviews). Primary-heavy for depth.
- **Target length:** 7,000–11,000 words
- **Opening:** thesis + the interpretive tradition this work sits in
- **H2 count:** **6–10** (fewer, LONGER sections — 800–1500 words each). Sections are THEMATIC, not entity-cataloged.
- **Analytical mode:** take and defend an interpretation; engage dissenting readings
- **Special rule:** NEVER one section per character / chapter / author. Sections must be thematic (e.g. "Sacrifice as cosmology" — not "Pegasus Seiya").
- **Special rule:** at least 2 body sections must put sources in tension with each other — find where scholars disagree and walk through it.
- **Special rule:** this is the type where catalog-style reports fail hardest. Before submitting, double-check that no section is <400 words or entity-named.

### Type 5 — Comparative Evaluation

- **Source strategy:** 3–5 primary per comparand + 2–5 secondary per comparand (so N×5 to N×10 total). Depth scales with N.
- **Target length:** 5,000–10,000 words
- **Opening:** the comparison framework itself — the dimensions being scored and why they matter
- **H2 count:** typically 1 per comparand + 2–4 synthesis sections (~8–12 total)
- **Analytical mode:** explicit scoring on each dimension + a recommended pick with tradeoffs
- **Special rule:** one comparison matrix in the body is MANDATORY (not optional)
- **Special rule:** equal depth across comparands — if one section is 400 words and another is 1200, rebalance

### Type 6 — Emerging / Cutting-Edge Research

- **Source strategy:** 5–15 primary (preprints, conference papers, authoritative reviews if any) + 3–8 secondary (news, blog posts from authors). Primary-dominant.
- **Target length:** 5,000–9,000 words
- **Opening:** the open problem + why prior approaches fell short
- **H2 count:** 8–12
- **Analytical mode:** honest about disagreement; forecast 2–5 years out with caveats
- **Special rule:** if a claim is from a 2024–2026 preprint, say so. Don't assume consensus in fast-moving fields.
- **Special rule:** include an explicit "What we don't know yet" section
- **Special rule:** do NOT pad with mature-field material to hit a source count. Fewer primary sources deeply engaged beats more sources shallowly skimmed.

### Type 7 — Forecast / Strategy / Recommendation

- **Source strategy:** 15–30 secondary (analyst reports, think-tanks, news) + 5–10 primary (official announcements, filings, datasets). Secondary-heavy.
- **Target length:** 6,000–10,000 words
- **Opening:** the decision / question being answered + the forces shaping it
- **H2 count:** 8–12
- **Analytical mode:** confident prescription with an explicit reasoning chain. Probability language over hedging.
- **Special rule:** at least one body section must commit to a direction — not everything can be deferred to the Opinionated Synthesis at the end.
- **Special rule:** acknowledge the time horizon explicitly — what's true in 6 months vs. 5 years.

### Type 0 — General Research (fallback)

Use the generic defaults: 15–25 / 30–50 / 50–80 source floors (see Step 3), framework opening, 12–20 H2 headings, 400–600 words per H2 (see Step 9).

---

When invoked, follow these steps **in order**. Do not skip steps. The CLI path will be provided by the CLAUDE.md — look for the "CLI path:" line in the Research Base section.

If you can't find the CLI path, check for the hyperresearch executable:
```bash
which hyperresearch 2>/dev/null || where hyperresearch 2>/dev/null || find . -path "*/.venv/*/hyperresearch*" -type f 2>/dev/null | head -1
```
Store it in a variable: `HPR="<path>"` for the rest of this workflow.

## Step 1: Check existing knowledge

Before searching the web, check what's already in the research base:

```bash
$HPR search "<topic>" --include-body -j
$HPR sources list -j
```

If there's already substantial coverage, tell the user what's known and ask if they want deeper research or a specific angle.

## Step 2: Search broadly

Run **multiple web searches** with different phrasings. Don't stop at one query:

```
WebSearch("<topic>")
WebSearch("<topic> research paper 2025 2026")
WebSearch("<topic> deep dive technical")
WebSearch("<related angle or subtopic>")
```

Collect ALL promising URLs — aim for 10-20 sources minimum. More is better. You'll prune later.

## Step 3: Fetch everything

Spawn `hyperresearch-fetcher` subagents to fetch URLs in parallel. They run on Haiku (cheap).

```
Spawn hyperresearch-fetcher agents for each URL batch:
- Batch 1: [url1, url2, url3, url4, url5]
- Batch 2: [url6, url7, url8, url9, url10]
```

Each fetcher will report back with note IDs and interesting links found in the content.

**Over-collect, then engage deeply.** It's better to have too many sources than too few — but collection is a means to an argument, not the goal. A report built from 30 sources that disagree and force you to take positions beats a report built from 80 sources that each contribute one bullet of description. Read each source carefully. If you find yourself translating one source into one paragraph or one section, stop — you are building a catalog.

**There is no time limit.** Do multiple rounds of fetching — as new subtopics and questions reveal themselves, launch new rounds of fetcher subagents in parallel to chase them down. The first round uncovers the landscape, the second digs into what you found, the third fills gaps. Keep going until you've exhausted the topic. Do not rush.

**CHECKPOINT: Before writing any draft, stop and take stock:**
```bash
$HPR note list -j
```
Review what you have. Don't chase a number — chase completeness:
- What angles or subtopics are NOT yet covered?
- Which notes reference sources you haven't fetched?
- Are there counterarguments or alternative viewpoints missing?
- Do you have primary sources or just secondhand summaries?

If there's more to get, go get it. **Source count is a function of request type, not topic complexity** — use the parameter block from Step 0.5 (your classified primary type) as your primary guidance. Fall back to the universal floors below ONLY if you classified as Type 0 General Research:
- Simple factual question: ~15–25 sources
- Complex or technical topic: ~30–50 sources
- PhD-level research question: ~50–80 sources

**Primary-heavy vs. secondary-heavy is the axis that matters most — getting this wrong is a worse failure than getting the count wrong.** "Primary" means the claim comes from first-hand: an original paper, an official document, a dataset, a product spec. "Secondary" means any description or discussion of a primary source. Types 1, 4, 5, 6 are primary-heavy — cite originals, engage with them deeply, prune irrelevant secondary coverage. Types 2, 7 are secondary-heavy — triangulate across many descriptions because no single secondary source is authoritative. Type 3 is balanced.

Stop fetching when you can't find anything new worth adding, not when you hit a number. And be honest about the opposite failure: if you're still fetching past the type's range without a clear gap in mind, you're procrastinating on the writing.

## Step 4: Go down rabbit holes

Read the fetched notes and follow links to deeper material:

```bash
$HPR note show <note-id> -j
```

For each note, look for:
- **Papers cited** → fetch them (PDFs are fully supported — fetch directly)
- **Documentation linked** → fetch it
- **GitHub repos mentioned** → fetch the README
- **Related topics referenced** → search and fetch
- **People/companies mentioned** → fetch their pages
- **Raw data, CSVs, datasets linked** → fetch and analyze them
- **Statistics without primary sources** → search for and fetch the original data

**PDFs work natively.** arXiv papers, NBER working papers, conference proceedings — fetch them directly. The tool auto-detects PDFs and extracts full text. Don't skip sources because they're PDFs.

**Use scholarly APIs for academic topics.** When the research is academic, use APIs to find papers:
- arXiv API: `https://export.arxiv.org/api/query?search_query=...`
- Semantic Scholar API: `https://api.semanticscholar.org/graph/v1/paper/search?query=...`
- CrossRef API: `https://api.crossref.org/works?query=...`

Write code to call these, get structured paper data (citations, related work, abstracts), then fetch the actual PDFs.

Follow links deeply — don't stop at the first page. When a source links to more detailed material, primary research, or raw data, follow those links and fetch them too.

**Run analysis when needed.** If you find raw data (tables, CSVs, statistics), write and run code to compute real figures, verify claims, calculate trends, and produce original analysis. Concrete numbers from actual data beat vague summaries.

Spawn more fetcher agents for these secondary sources.

**Do NOT stop collecting until you are certain you have enough breadth.** After each round of fetching, ask yourself: "Are there major angles, subtopics, or perspectives I haven't covered yet?" If yes, search and fetch more. If a topic has 5 facets, you need sources on all 5 — not just the first 2 you found. Keep going until you can confidently say the collection covers the full scope of the topic.

## Step 4.5: Read notes efficiently — triage by frontmatter (MANDATORY)

When inspecting notes in the research base, NEVER blindly `note show` every note. Bodies can be 15,000+ words; frontmatter summaries are usually under 40. **Triage first, body-read only when earned.** This protocol applies throughout the rest of the workflow — use it in Step 4 (rabbit holes), Step 8 (cross-source comparison), and Step 9 (draft writing).

### Level 1 — Frontmatter sweep (cheap, always start here)

```bash
$HPR note list -j
```

Returns one object per note with `id`, `title`, `tags`, `summary`, `word_count`, `status` — **no bodies**. Scan this to build a relevance shortlist. For many claims the summary field is enough — a well-curated note's summary already tells you what the source claims, and you cite the source URL directly without re-reading the body.

### Level 2 — Frontmatter-only show (targeted)

For a single note whose summary hints at deeper value, pull its full frontmatter without the body:

```bash
$HPR note show <id> --meta -j
```

Adds `source`, `parent`, `created`, `updated`, `raw_file` (if the note has a PDF). Still cheap. Decide from here whether the body is worth pulling.

### Level 3 — Inline body read (only for small notes)

```bash
$HPR note show <id> -j
```

Threshold: `word_count < 2000` (~2700 tokens). Small enough to read directly. Batch several at once: `note show <id1> <id2> <id3> -j`.

### Level 4 — Targeted search with body, token-capped

When you need content from multiple notes at once:

```bash
$HPR search "<precise question>" --include-body --max-tokens 6000 -j
```

`--max-tokens` truncates intelligently and flags `"truncated": true` on the last fitting result. Prefer this over N separate `note show` calls.

### Level 5 — Delegate heavy notes to a Sonnet subagent (MANDATORY for large notes)

For any note with `word_count > 6000` (~8000 tokens, often PDFs), do NOT dump it into your own context. Spawn a Sonnet subagent with a pointed extraction prompt:

> Use a fresh Sonnet subagent:
> "Read `research/notes/<id>.md` (and its raw file at `research/raw/<id>.pdf` if the frontmatter has `raw_file` set). Extract ONLY what answers this specific question: '<your precise question>'. Return under 500 words, with direct quotes for any non-trivial claim and the source URL. If the note doesn't actually answer the question, say so and stop."

The subagent reads the full 20K+ tokens internally but returns only ~500 tokens to you — roughly a 40× context savings per large note, which compounds across a session.

### Level 6 — Raw PDF re-extraction (rare)

If a note has `raw_file: raw/<id>.pdf` in its frontmatter AND the extracted markdown looks garbled or is missing content you need (specific figure, table, equation), read the raw PDF directly with the Read tool. Most of the time the extracted markdown is sufficient — only fall back here when it's clearly broken.

### Triage thresholds (guidance, not hard rules)

| word_count | Tier | Action |
|---|---|---|
| `< 2000` | Trivial | Read inline via Level 3. Batch with siblings. |
| `2000 – 6000` | Medium | Level 2 frontmatter first. Body only if the summary suggests high value. |
| `> 6000` | Heavy | Level 5 Sonnet delegation. Don't read inline. |

Override with reason (e.g. a single 8000-word paper is your most important primary source — read it directly, once). But defaulting to "just `note show` everything" is how sessions run out of context and reports turn shallow.

## Step 5: Auto-link and curate

Run the auto-linker to connect related notes:

```bash
$HPR link --auto -j
```

Check what tags exist and ensure consistency:

```bash
$HPR tags -j
```

Update any notes missing summaries (auto-curation handles most, but fix any gaps):

```bash
$HPR lint -j
$HPR repair -j
```

## Step 6: Discover the knowledge graph

Find the hub notes and key connections:

```bash
$HPR graph hubs -j
$HPR graph backlinks <most-linked-note-id> -j
```

## Step 7: Build the conceptual scaffold (MANDATORY — before writing)

This is the single biggest lever for report quality. Reports that look like references are built from a scaffold; reports that look like Wikipedia dumps are assembled by translating notes into sections. Before a single paragraph of prose, answer these four questions.

**Where to put the scaffold:** keep it in your working memory, or dump it to a temp file like `/tmp/scaffold.md`. **DO NOT save it as a hyperresearch note.** The research base is for durable source material, not ephemeral pre-writing analysis. Notes are forever; scaffolds are for the next hour of writing.

1. **What is the hard question?** One sentence — the underlying difficulty, not the surface query.
2. **What is the naive answer?** What a reader would guess before reading any sources. This is your foil — the thing the report has to explain away.
3. **What is the structural tension?** What makes this topic worth 10,000 words? The paradox, the constraint, the thing sources disagree on, the unsettled question.
4. **What is the progression?** Sketch 6–12 H2 section headings in **dependency order**. Each section must build on the previous one. If the headings could be shuffled, you have a catalog, not a report.

The final report's **opening section MUST be a framework section**, not a definition section. Section 1 establishes the hard question and the structural tension. Not "X is a Y that does Z."

## Step 8: Cross-source comparison (MANDATORY)

Sources earn their citations by being compared against each other, not by being listed in parallel. Find 3–5 places where your sources actually disagree, emphasize different things, or frame the same problem differently.

```bash
$HPR search "<topic>" --include-body -j
```

For each disagreement, capture a short comparison block in the same scratch file as the scaffold from Step 7 — **NOT as a hyperresearch note**. These are ephemeral analysis artifacts that will end up as prose inside the final report, not durable KB entries:
- what each source says, with URLs
- why they differ (data, methodology, assumptions, era, scope)
- your position on which is more credible, with reasoning

These comparisons become the backbone of body sections. If every source is corroborating every other source, you didn't need many sources — search again for contrarian views, criticism, or competing frameworks.

## Step 9: Write the draft

**First, pull up your classification from Step 0.5.** The parameter block for your primary type sets target length, H2 count, opening shape, and analytical mode. The hard constraints below are Type 0 defaults — they apply EXCEPT where your type's block overrides them. Notable overrides:
- **Type 4 Humanities** targets 6–10 longer H2s (800–1500 words each), not 12–20.
- **Type 2 Market** wants one section per vendor *cluster*, not per individual vendor.
- **Type 5 Comparative** requires a mandatory comparison matrix in the body.
- **Type 6 Emerging** requires a "What we don't know yet" section.

Now write the report. These are hard constraints (under Type 0; type-specific overrides apply where listed above):

- **Target 400–600 words per H2 section.** Sections under 200 words get merged. Sections over 800 get split — only if both halves stay above 300. (Type 4 Humanities: 800–1500.)
- **Aim for 12–20 H2 headings on a 10K-word report; 8–15 on a 5K-word report.** Above 25 is fragmentation — merge. (Type 4 Humanities: 6–10.)
- **Never write one section per source or one section per named entity.** A single H2 section weaves 3–8 sources together. A character, vendor, or paper does not earn its own section unless it has >400 words of real analysis attached.
- **Every body section ends with an analytical beat** — a 1–2 sentence "so what does this tell us" that integrates across the sources just cited. The Opinionated Synthesis at the end is NOT supposed to carry the synthesis load alone.
- **Open with the framework from Step 7, not a definition.** Section 1 = hard question + naive answer + structural tension.
- **Cite inline with parenthetical URLs.** Every non-trivial claim needs one. Prefer primary sources.
- **Comparison tables over fact tables.** A good table contrasts cases on a common axis. A bad table dumps attributes of one entity.
- **Word count targets.** Simple factual: 3,000–5,000. Complex/technical: 6,000–9,000. PhD-level: 9,000–12,000. Missing these is usually a signal that the scaffold from Step 7 is wrong — go back and fix the scaffold before writing more prose.

## Step 10: Gap analysis (MANDATORY)

After writing your draft, stop and compare it against the original query. Re-read the user's request word by word:
- What specific questions did they ask that I haven't fully answered?
- What subtopics or angles did I miss entirely?
- Where did I make claims without strong enough evidence?
- What would an expert in this field say is missing?

Launch a new round of research to fill every gap — web search, fetch, follow links, spawn fetcher subagents in parallel. Add the new material to your draft.

## Step 11: Adversarial audit (MANDATORY — do this twice)

After the gap-filling round, launch two subagents in parallel to audit the revised draft:

**Agent 1 — Comprehensiveness auditor:**
```
Read this report and search the research base ($HPR search, $HPR note show) to find gaps.
What subtopics, angles, data points, or counterarguments are missing? What claims lack
citations? What sections are shallow? Compare against the original query and be ruthless —
list every gap you find.
```

**Agent 2 — Logic and structure auditor:**
```
Read this report as a domain expert. The report should declare its request type
(Step 0.5 classification) and follow the matching parameter block. Check specifically:
  (1) Does section 1 establish a framework — hard question, naive answer, structural
      tension — or does it just define terms?
  (2) Are sections in dependency order? Does each section build on the previous one, or
      could they be shuffled without loss?
  (3) Are there sections under 200 words that should be merged into siblings?
      (Type 4 Humanities: <400 is the floor, not 200.)
  (4) Count H2 headings. Fragmentation thresholds vary by type: Type 0 General is >25 on
      a <12K-word report; Type 4 Humanities is >12; Type 2 Market is >15.
  (5) Does each body section end with an analytical beat, or does it just stop?
  (6) Are sources compared against each other anywhere, or only listed in parallel?
  (7) Does the argument flow logically — leaps, unsupported claims, contradictions?
  (8) Does the report match its declared request type? If Type 4 Humanities, are sections
      thematic rather than entity-catalog? If Type 5 Comparative, is there a mandatory
      comparison matrix? If Type 6 Emerging, is there a "What we don't know yet" section?
      If Type 2 Market, is there a position on who is winning? Flag every type violation.
List every weakness with specific section names and direct quotes.
```

Pass your full draft report text to both agents.

**After each audit round:**
1. Read both agents' feedback
2. If they found missing topics or weak arguments — do another round of web search + fetching
3. If the structure auditor flagged fragmentation, short sections, or a missing framework — **consolidate and rewrite, don't just patch.** Merging five 100-word sections into one 500-word section is a rewrite, not an edit. This is where catalog-style drafts become argument-style drafts.
4. Rewrite the report with new sources and structural fixes
5. Run the audit again (second loop) on the revised report

**Do at least one audit loop. Do two if the first found significant gaps.** Only finalize after auditors have no major complaints.

**While audit agents are running, don't idle.** Use the wait time to:
- Improve weak or missing summaries on notes (`$HPR note update <id> --summary "..." -j`)
- Add more specific tags to under-tagged notes (`$HPR note update <id> --add-tag <tag> -j`)
- Add `[[wiki-links]]` between related notes
- Run `$HPR lint -j` and fix issues
- Read notes you haven't reviewed yet for links worth following

## Step 12: Opinionated synthesis (MANDATORY — end of report)

A comprehensive catalog of facts is not a report. Before finalizing, you **MUST** append a section titled **`## Opinionated Synthesis`** at the very end of the report. This is where you stop reciting what sources said and start **reasoning across them**.

This section **complements — it does not replace** — the per-section analytical beats from Step 9. If all the analysis is dumped in this appendix and the body sections are purely descriptive, the report is still a catalog with a synthesis bolted onto the end. Both are required.

**Your Opinionated Synthesis section MUST include:**

1. **Comparative analysis across categories.** Don't just describe each group or concept in isolation — compare them. What do the groups have in common? Where do they differ? What patterns emerge when you look at them side by side? Build at least one comparison table if the topic supports it.

2. **Thematic threads and progression.** What themes cut across the whole topic? What's the narrative arc? How do things evolve over time, across versions, across authors, across schools of thought? Identify the throughlines.

3. **Your reasoned position.** Take a defensible stance. What's the most important finding? What's over-hyped? What's underrated? What do you expect to change in the next 2–5 years? Label it clearly as your own analysis, grounded in the sources you fetched.

4. **Open questions and limitations.** What did the sources NOT answer? What would an expert say is still unclear? Where is the research thin? Name the gaps explicitly.

5. **Concluding thoughts.** One tight paragraph that ties everything back to the user's original question. What's the takeaway they should remember?

**Structure of the synthesis section (use these subheadings exactly):**

```markdown
## Opinionated Synthesis

### Comparative Analysis
<cross-cutting comparisons — tables where useful>

### Thematic Threads
<patterns, progressions, throughlines across the topic>

### My Reasoned Position
<your defensible stance, clearly labeled as analysis>

### Open Questions
<gaps in the research, what the sources didn't answer>

### Concluding Thoughts
<one tight paragraph, answers the original question>
```

**Do NOT skip this section.** A report without an Opinionated Synthesis is incomplete. Even 9,000 words of carefully cataloged facts is just reference material without it. The synthesis is what separates a research report from a Wikipedia dump.

## Step 13: Save the final report

Save the final reviewed report as a synthesis note:

```bash
cat > /tmp/synthesis.md << 'SYNTHESIS'
# <Topic> — Research Synthesis

## Key Findings
<your synthesis here>

## Sources
<wiki-links to all source notes: [[note-id-1]], [[note-id-2]], etc.>

## Open Questions
<what wasn't answered, what needs more research>
SYNTHESIS

$HPR note new "Synthesis: <topic>" --tag <topic> --tag synthesis --type moc --status review --body-file /tmp/synthesis.md --summary "<one-line summary of findings>" -j
```

## Step 14: Present to user

Present your findings with:

1. **Executive summary** — 2-3 sentence answer to their question
2. **Key findings table** — the most important discoveries
3. **Sources collected** — how many notes, from which domains
4. **Hub notes** — the most-referenced/important notes in the graph
5. **Open questions** — what you didn't find or what needs more research
6. **How to explore** — tell them they can ask follow-up questions and you'll search the KB

Example closing:
```
Research complete. 15 sources collected on "<topic>":
- 3 primary papers, 5 technical blogs, 4 documentation pages, 3 news articles
- Hub notes: [[key-note-1]], [[key-note-2]]
- All sources are saved and searchable across sessions.

Ask me anything about this topic — I'll search the research base first.
```

## Important rules

- **NEVER use WebFetch for source pages.** Always use `$HPR fetch` or the fetcher subagent.
- **Over-collect, then prune.** Fetch aggressively. Deprecate irrelevant notes after synthesis.
- **Save raw content.** Don't rewrite or summarize sources before saving. The full text is the value.
- **Follow links.** A blog post about a paper is not the paper. Fetch the paper.
- **Save your synthesis.** Every research session should produce a synthesis note that future agents can find.
