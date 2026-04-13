"""Agent documentation integration — inject hyperresearch docs into agent config files.

Supports: CLAUDE.md, AGENTS.md, GEMINI.md, .github/copilot-instructions.md
By default on init, only creates CLAUDE.md. Others created via --agents flags
or if the file already exists in the repo.
"""

from __future__ import annotations

import re
from pathlib import Path

HYPERRESEARCH_SECTION_MARKER = "<!-- hyperresearch:start -->"
HYPERRESEARCH_SECTION_END = "<!-- hyperresearch:end -->"

HYPERRESEARCH_BLURB = """\

{marker}
## Research Base (hyperresearch) — Today is {today}

**CLI path: `{hpr}`** — use this exact path for all hyperresearch commands below. It may not be on your system PATH.

**IMPORTANT — paths:** The CLI path above is the location of the `hyperresearch` binary, **nothing else**. It is NOT your working directory. All file and directory paths in this document (`research/notes/`, `research/raw/`, `.hyperresearch/config.toml`, etc.) are **relative to your current working directory**. When you save files with the Write tool, use relative paths like `research/notes/final_report.md` — do NOT prefix them with the directory containing the hyperresearch binary. The `research/` folder lives wherever you are running from.

This project uses hyperresearch as an agent-driven research knowledge base. The `research/` directory contains markdown notes collected from web sources and original research. Append `--json` to any command for structured output.

### MANDATORY: How to do research

When the user asks you to research a topic, **you MUST follow this workflow**. Do NOT use WebFetch for source pages — use `{hpr} fetch` instead. It runs a real headless browser, handles JavaScript, bypasses bot detection, saves full content with screenshots and images, and indexes everything for future sessions.

**This is a deep research tool.** Your job is to go down rabbit holes, cast a wide net, and collect enough raw source material to say something meaningful across it. **Over-collect, then prune.** It is better to have too many sources than too few — you can deprecate notes later, but you can't un-skip a source you never fetched.

**But collection is not the goal.** Collection is a means to an argument. A report built from 30 sources that disagree, contextualize each other, and force you to take positions is worth more than a report built from 80 sources that each contribute one paragraph of description. Optimise for **depth of engagement** (each source read carefully, compared with 2–3 others, cited multiple times across the report) rather than **count of citations**. If you find yourself translating one source into one paragraph or one section, you are building a catalog — stop and restructure.

**There is no time limit.** Deep research can run for hours if the topic demands it. Do multiple rounds of research — as new subtopics, angles, and questions reveal themselves, launch new rounds of fetcher subagents in parallel to chase them down. The first round uncovers the landscape; the second round digs into what you found; the third round fills gaps. Keep going.

**CHECKPOINT: Before you start writing ANY draft, stop and take stock.** Run:
```bash
{hpr} note list -j
```
Don't collect sources just to hit a number. Instead, review what you have and ask:
- What angles, subtopics, or perspectives are NOT yet covered?
- Which existing notes reference papers, data, or sources I haven't fetched yet?
- Are there counterarguments, alternative viewpoints, or competing theories I'm missing?
- Do I have primary sources, or just secondhand summaries?

If the answer to any of these is "yes, there's more to get" — go back and get it. Spawn more fetcher agents, search new angles, follow links from existing notes. Keep going until you genuinely can't find anything new worth adding.

**Step 0: Classify the request and pick a protocol (MANDATORY)** — Different research requests need fundamentally different strategies. Source counts, primary/secondary mix, section structure, target length, analytical mode — all change based on request shape. A single universal protocol is wrong. **Before Step 1, classify the request and state your classification in writing** (in working memory or `/tmp/scaffold.md` — NOT a hyperresearch note).

The 7 request types:

| Type | Name | Use when |
|---|---|---|
| 1 | **Canonical Knowledge Retrieval** | Mature field with textbook chapters or canonical surveys; an expert would start by citing a classic source. |
| 2 | **Market / Landscape Mapping** | Enumerable competitive analysis — list of companies, products, vendors with attributes. |
| 3 | **Engineering / Technical How-To** | User is trying to DO something. Ideal answer is a procedure or method selection. |
| 4 | **Interpretive / Humanities Analysis** | Subject is a text, work, tradition, or cultural phenomenon. Good answer takes a position and defends it. |
| 5 | **Comparative Evaluation** | Prompt names multiple alternatives by name and expects a matrix + pick. |
| 6 | **Emerging / Cutting-Edge Research** | Most useful material is <2 years old; best sources are arXiv/bioRxiv/conference papers. |
| 7 | **Forecast / Strategy / Recommendation** | Asks what will happen or should be done; ideal answer commits to a prediction or prescription. |
| 0 | **General Research (fallback)** | Doesn't cleanly fit one type, or genuinely spans multiple. |

Overlap is expected. Classify a **primary** type and, if applicable, a **secondary** type. Apply the primary's parameter block; borrow special rules from the secondary.

**State your classification** before Step 1:
1. Primary type: #N — one-sentence justification tied to the prompt.
2. Secondary type: #N or "none".
3. Applied parameters (5 lines): source strategy, target length, opening-section shape, target H2 count, analytical mode.

**Request-type parameter blocks** — apply the block for your primary type. These overrides take precedence over the generic defaults referenced in Step 3 and Step 7.

**Type 1 — Canonical Knowledge Retrieval.** Sources: 5–15 primary (seminal papers, textbooks, canonical surveys) + 5–15 secondary. Primary-heavy. Target 6,000–10,000 words. Opening: historical/conceptual progression — how the field arrived at consensus. H2 count: 10–15, sequenced by dependency (concept → result → consequence). Analytical mode: explain WHY canonical results hold; compare competing formulations; signal which textbook to start with. Special rule: sequence by dependency, not by source.

**Type 2 — Market / Landscape Mapping.** Sources: 20–50 secondary (reports, press, official docs) + 5–10 primary (filings, specs, API docs). Secondary-heavy. Target 5,000–9,000 words. Opening: market definition + segmentation + the framework used to score vendors. H2 count: 8–14, one per vendor *cluster* or category — NEVER one per individual vendor. Analytical mode: take a position on who is winning and why. Special rule: at least one comparison matrix in the body is MANDATORY. Never list vendors in isolation. If the user asked for rankings, deliver with confidence.

**Type 3 — Engineering / Technical How-To.** Sources: 5–15 primary (papers, docs, GitHub, RFCs, standards) + 5–15 secondary (blog posts, tutorials, SO). Balanced. Target 4,000–8,000 words. Opening: problem statement + constraint landscape — what makes this hard. H2 count: 8–14. Analytical mode: pick a recommended approach; explain when to use alternatives. Special rule: if a method has a reference implementation, link and characterize it. Include a decision tree or selection matrix.

**Type 4 — Interpretive / Humanities Analysis.** Sources: 3–10 primary (the work itself, key scholarly monographs, canonical commentary) + 10–25 secondary (critical essays, interviews, reviews). Primary-heavy for depth. Target 7,000–11,000 words. Opening: thesis + the interpretive tradition this work sits in. H2 count: **6–10** (fewer, LONGER sections — 800–1500 words each). Sections are THEMATIC, not entity-cataloged. Analytical mode: take and defend an interpretation; engage dissenting readings. Special rule: NEVER one section per character / chapter / author. Special rule: at least 2 body sections must put sources in tension with each other. Special rule: this is the type where catalog-style reports fail hardest — double-check that no section is <400 words or entity-named.

**Type 5 — Comparative Evaluation.** Sources: 3–5 primary per comparand + 2–5 secondary per comparand (so N×5 to N×10 total). Depth scales with N. Target 5,000–10,000 words. Opening: the comparison framework — dimensions being scored and why they matter. H2 count: typically 1 per comparand + 2–4 synthesis sections (~8–12 total). Analytical mode: explicit scoring on each dimension + recommended pick with tradeoffs. Special rule: a comparison matrix in the body is MANDATORY. Special rule: equal depth across comparands — rebalance if uneven.

**Type 6 — Emerging / Cutting-Edge Research.** Sources: 5–15 primary (preprints, conference papers, authoritative reviews if any) + 3–8 secondary (news, blog posts from authors). Primary-dominant. Target 5,000–9,000 words. Opening: the open problem + why prior approaches fell short. H2 count: 8–12. Analytical mode: honest about disagreement; forecast 2–5 years out with caveats. Special rule: if a claim is from a 2024–2026 preprint, say so — don't assume consensus. Include an explicit "What we don't know yet" section. Do NOT pad with mature-field material to hit a source count.

**Type 7 — Forecast / Strategy / Recommendation.** Sources: 15–30 secondary (analyst reports, think-tanks, news) + 5–10 primary (official announcements, filings, datasets). Secondary-heavy. Target 6,000–10,000 words. Opening: the decision/question being answered + the forces shaping it. H2 count: 8–12. Analytical mode: confident prescription with explicit reasoning chain; probability language over hedging. Special rule: at least one body section must commit to a direction — not everything can be deferred to the Opinionated Synthesis. Acknowledge the time horizon explicitly.

**Type 0 — General Research (fallback).** Use universal defaults: 15–25 / 30–50 / 50–80 source floors (see below), framework opening, 12–20 H2 headings, 400–600 words per H2 (see Step 7).

**Source-count floors for Type 0 (fallback only):**
- Simple factual question: 15–25 sources
- Complex or technical topic: 30–50 sources
- PhD-level research question: 50–80 sources

**Source count is a function of request type, not topic complexity.** If you classified in Step 0, use that type's parameter block as primary guidance — fall back to the floors above only for Type 0.

**Primary-heavy vs. secondary-heavy is the axis that matters most — getting this wrong is a worse failure than getting the count wrong.** Types 1, 4, 5, 6 are primary-heavy — cite originals and engage with them deeply. Types 2, 7 are secondary-heavy — triangulate across many descriptions. Type 3 is balanced. Most sources should be cited multiple times across multiple sections. If a source earns only one citation, it's probably not pulling its weight — either deepen engagement or cut it.

Stop fetching when you can't find anything new worth adding, not when you hit a number. And be honest about the opposite: if you're still fetching past the type's range without a clear gap in mind, you're procrastinating on the writing.

**Step 1: Check what's already known**
```bash
{hpr} search "topic" --include-body -j
{hpr} sources list -j
```

**Step 2: Search broadly** — Use WebSearch with multiple queries. Don't stop at one search. Try different phrasings, related terms, and specific sub-topics. Cast a wide net.

**Step 3: Fetch EVERYTHING relevant** — A `hyperresearch-fetcher` subagent is installed in `.claude/agents/`. It uses a **cheap, fast model (Haiku)** to do the actual URL fetching. **Delegate all fetching to it** — do NOT fetch URLs yourself or use WebFetch.

For each URL or batch of URLs, spawn the fetcher agent:
```
Use the hyperresearch-fetcher agent to fetch these URLs with tag "<topic>":
- https://example.com/article1
- https://example.com/article2
```

**Spawn 10-20 fetcher agents in parallel per round** — give each agent 2-3 URLs max. They run on Haiku and cost fractions of a cent each. After each web search, immediately spawn fetchers for ALL promising URLs from the results — don't cherry-pick, fetch everything. Then do another round of searches and another round of fetchers. Repeat until you hit the source checkpoint.

If the `hyperresearch-fetcher` agent is not available (other platforms), fall back to running the command directly:
```bash
{hpr} fetch "<url>" --tag <topic> -j
```

**Step 4: Go down rabbit holes** — After fetching, read the notes:
```bash
{hpr} note show <note-id> -j
```
Look for links in the content that point to **primary sources, references, related papers, deeper material, or tangentially related topics**. Fetch those too. Then read THOSE notes and follow THEIR links.

**Keep going aggressively:**
- A blog post about a paper? Fetch the paper.
- A news article about a tool? Fetch the docs AND the GitHub repo.
- A paper cites 3 key references? Fetch all 3.
- A profile mentions a company? Fetch the company page.
- Found a related topic that might be relevant? Fetch it. You can always deprecate it later.
- A page links to raw data, CSV files, or datasets? Fetch those and analyze them.
- A source references specific statistics without citing them? Search for and fetch the primary data.

**Follow links deeply.** Don't stop at the first page. When a fetched page links to more detailed sources, primary research, raw data, or technical documentation — follow those links and fetch them too. The best insights come from primary sources, not secondhand summaries.

**Run analysis when needed.** If you find raw data (tables, CSVs, statistics), don't just quote numbers — write and run code to compute real figures, verify claims, calculate trends, and produce original analysis. Concrete numbers from actual data are worth more than vague summaries.

**The goal is exhaustive collection.** You are building a knowledge base that future agents will rely on. Missing a source is worse than having one extra note. Prune later during curation.

**Do NOT stop collecting until you are certain you have enough breadth.** After each round of fetching, ask yourself: "Are there major angles, subtopics, or perspectives I haven't covered yet?" If yes, search and fetch more. If a topic has 5 facets, you need sources on all 5 — not just the first 2 you found. Keep going until you can confidently say the collection covers the full scope of the topic. A half-covered topic is worse than no coverage at all.

**Step 4.5: Read notes efficiently — triage by frontmatter (MANDATORY)** — When inspecting notes, NEVER blindly `{hpr} note show` every note. Bodies can be 15,000+ words; frontmatter summaries are usually under 40. **Triage first, body-read only when earned.** This protocol applies throughout Steps 4, 6, and 7.

**Level 1 — Frontmatter sweep (cheap, always).** Start with:
```bash
{hpr} note list -j
```
Returns per note: `id`, `title`, `tags`, `summary`, `word_count`, `status` — **no bodies**. Scan this to build a relevance shortlist. For many claims the summary alone is enough — cite the source URL directly without re-reading the body.

**Level 2 — Frontmatter-only show.** For a single note whose summary hints at deeper value, pull full frontmatter without body:
```bash
{hpr} note show <id> --meta -j
```
Adds `source`, `parent`, `created`, `updated`, `raw_file` (if the note has a PDF). Still cheap.

**Level 3 — Inline body read (small notes only).** For `word_count < 2000` (~2700 tokens), read directly:
```bash
{hpr} note show <id> -j
```
Batch siblings: `{hpr} note show <id1> <id2> <id3> -j`.

**Level 4 — Targeted search with body, token-capped.** When pulling content from multiple notes at once:
```bash
{hpr} search "<precise question>" --include-body --max-tokens 6000 -j
```
`--max-tokens` truncates intelligently and flags `"truncated": true` on the last fitting result. Use this instead of N separate `note show` calls.

**Level 5 — Delegate heavy notes to a Sonnet subagent (MANDATORY for large notes).** For any note with `word_count > 6000` (~8000 tokens, often PDFs), do NOT dump it into your own context. Spawn a Sonnet subagent with a pointed extraction prompt:

> Fresh Sonnet subagent prompt:
> "Read `research/notes/<id>.md` (and its raw file at `research/raw/<id>.pdf` if the frontmatter has `raw_file` set). Extract ONLY what answers this specific question: '<your precise question>'. Return under 500 words, with direct quotes for any non-trivial claim and the source URL. If the note doesn't actually answer the question, say so and stop."

The subagent reads the full 20K+ tokens internally but returns only ~500 tokens to you — roughly a 40× context savings per large note, which compounds across a session.

**Level 6 — Raw PDF re-extraction (rare).** If a note has `raw_file: raw/<id>.pdf` AND the extracted markdown looks garbled or is missing content you need (specific figure, table, equation), read the raw PDF directly with the Read tool. Most of the time the extracted markdown is sufficient — only fall back here when it's clearly broken.

**Triage thresholds (guidance, not hard rules):**
- `word_count < 2000` → **Trivial**: read inline (Level 3), batch with siblings
- `word_count 2000–6000` → **Medium**: Level 2 frontmatter first; body only if summary suggests high value
- `word_count > 6000` → **Heavy**: Level 5 Sonnet delegation. Don't read inline.

Override with reason (e.g. a single 8000-word paper is your most important primary source — read it once, directly). But defaulting to "just `note show` everything" is how sessions run out of context and reports turn shallow.

**Step 5: Build the conceptual scaffold (MANDATORY — do this BEFORE writing)** — This is the single biggest lever for report quality. Strong reports are built from a scaffold, not assembled by translating notes into sections. Before you write a single paragraph of prose, answer these four questions.

**Where to put the scaffold:** keep it in your working memory, or dump it to a temp file like `/tmp/scaffold.md`. **DO NOT save it as a hyperresearch note.** The research base is for durable source material, not ephemeral pre-writing analysis. Notes are forever; scaffolds are for the next hour of writing.

1. **What is the hard question?** One sentence — not the surface query, the underlying difficulty. ("Why is eukaryotic HGT rare despite being evolutionarily important?" not "What is HGT?")
2. **What is the naive answer?** What a reader would guess before reading the sources. This is your foil — the thing the report has to explain away.
3. **What is the structural tension?** What makes this topic worth 10,000 words instead of 500? The constraint, the paradox, the thing sources disagree on, the reason the field hasn't converged.
4. **What is the progression?** Sketch 6–12 H2 section headings in **dependency order**. Each section must BUILD on the one before, not sit parallel to it. A reader should only be able to understand section 3 because they read sections 1 and 2. If your headings could be read in any order, that's a catalog, not a report.

The opening section of the final report MUST be a framework section — not "What is X." It should establish the hard question, the naive answer, and why the naive answer is insufficient. This is what separates analytical reports from catalog-style ones.

**Step 6: Compare sources across a common axis (MANDATORY)** — Before writing the body, find 3–5 places where your sources actually disagree, emphasize different things, or frame the same problem differently. Use search to locate them:
```bash
{hpr} search "topic" --include-body -j
```

For each disagreement, capture a short comparison block (in your working memory or in the same scratch file as the scaffold from Step 5 — **NOT as a hyperresearch note**; these are ephemeral analysis artifacts, not durable sources):
- what each source says, with URLs
- why they differ (different data? methodology? assumptions? era? scope?)
- your position on which is more credible, with reasoning

These comparisons become the backbone of body sections — they will end up as prose *inside* the final report, not as separate KB entries. Sources earn their citations by being **compared**, not by being listed. If every source is corroborating every other source, you didn't need many sources — go back and search for contrarian views, criticism, or alternative frameworks. Reference-quality reports always surface disagreement; catalog-style reports never do.

**Step 7: Write the draft** — First, pull up your Step 0 classification. The parameter block for your primary type sets target length, H2 count, opening shape, and analytical mode. The hard constraints below are Type 0 defaults — they apply EXCEPT where your type's block overrides them. Notable overrides:
- **Type 4 Humanities** targets 6–10 longer H2s (800–1500 words each), not 12–20.
- **Type 2 Market** wants one section per vendor *cluster*, not per individual vendor.
- **Type 5 Comparative** requires a mandatory comparison matrix in the body.
- **Type 6 Emerging** requires a "What we don't know yet" section.

Now, and only now, write the report. Follow these rules as hard constraints (under Type 0; type-specific overrides apply where listed above):

- **Target 400–600 words per H2 section.** If a section is under 200 words, merge it into a sibling. If over 800, split it — but only if the split sections stay above 300. (Type 4 Humanities: 800–1500 per section.)
- **Aim for 12–20 H2 headings on a 10K-word report; 8–15 on a 5K-word report.** If you're above 25, you are fragmenting. Merge. (Type 4 Humanities: 6–10.)
- **Never write one section per source or one section per named entity.** Sources serve sections, not the other way around. A single H2 section should weave 3–8 sources together. A character, vendor, or paper does not earn its own section unless it has >400 words of analysis attached.
- **Every body section ends with an analytical beat** — a 1–2 sentence "so what does this tell us" that integrates across the sources just cited. Not a summary; a step forward in the argument. The Opinionated Synthesis at the end is NOT supposed to carry the synthesis load alone.
- **Open with the framework, not a definition.** Section 1 = the hard question, the naive answer, the structural tension. Not "X is a Y that does Z." Definitions can go into a sub-section or a sidebar.
- **Cite inline with parenthetical URLs.** Every non-trivial claim needs one. Prefer primary sources over secondary summaries.
- **Use comparison tables, not fact tables.** A good table contrasts cases on a common axis (e.g., Recipient → Donor → Gene → Function). A bad table dumps attributes of a single entity (Name | Star | Technique | Fate). If your table is dumping facts about one thing, it probably belongs in prose.
- **Word count targets by topic difficulty.** Simple factual: 3,000–5,000. Complex or technical: 6,000–9,000. PhD-level: 9,000–12,000. Hitting these is easier when sections are 400–600 words each, not 80–150. Missing these is usually a signal that the scaffold from Step 5 is off — revisit it.

**Step 8: Gap analysis (MANDATORY)** — After writing your draft, stop and compare it against the original query. Re-read the user's request word by word. Ask yourself:
- What specific questions did they ask that I haven't fully answered?
- What subtopics or angles did I miss entirely?
- Where did I make claims without strong enough evidence?
- What would an expert in this field say is missing?

Then launch a new round of research to fill every gap — web search, fetch, follow links, the full workflow. Spawn fetcher subagents in parallel for the new URLs. Add the new material to your draft.

**Step 9: Adversarial audit (MANDATORY — do this twice)** — After the gap-filling round, launch two subagents in parallel to audit the revised draft. This runs up to 2 loops.

Spawn two agents in parallel:
- **Agent 1 — Comprehensiveness auditor:** "Read this report and search the research base (`{hpr} search` and `{hpr} note show`) to find gaps. What subtopics, angles, data points, or counterarguments are missing? What claims lack citations? What sections are shallow? Compare against the original query and be ruthless — list every gap."
- **Agent 2 — Logic and structure auditor:** "Read this report as a domain expert. The report should declare its Step 0 request-type classification and follow that type's parameter block. Check specifically: (1) Does section 1 establish a framework (hard question, naive answer, structural tension) or just define terms? (2) Are sections in dependency order — does each build on the previous, or could they be shuffled? (3) Short sections: are there any under 200 words that should be merged into siblings? (Type 4 Humanities floor is 400, not 200.) (4) Count H2 headings. Fragmentation threshold varies by type: Type 0 General >25 on a <12K-word report; Type 4 Humanities >12; Type 2 Market >15. (5) Does each section end with an analytical beat, or does it just stop? (6) Are sources compared against each other anywhere, or only listed in parallel? (7) Does the argument flow logically — leaps, unsupported claims, contradictions? (8) Does the report match its declared request type? If Type 4 Humanities, are sections thematic rather than entity-catalog? If Type 5 Comparative, is there a mandatory comparison matrix? If Type 6 Emerging, is there a 'What we don't know yet' section? If Type 2 Market, is there a position on who is winning? Flag every type violation. List every weakness with specific section names and quotes."

Pass your full draft report text to both agents. They search the research base independently and report back.

**After each audit round:**
1. Read both agents' feedback
2. If they identified missing topics or weak arguments — do another round of web search and fetching to fill the gaps
3. If the structure auditor flagged fragmentation, over-short sections, or a missing framework — **consolidate headings and rewrite, don't just patch.** Merging five 100-word sections into one 500-word section is a rewrite, not an edit. Do not skip this; it's where catalog-style drafts become argument-style drafts.
4. Rewrite the report incorporating new sources and fixing structural issues
5. Run the audit again (second loop) on the revised report

**You MUST do at least one audit loop. Do two if the first audit found significant gaps.** Only after the auditors have no major complaints should you finalize the report.

**While audit agents are running, don't idle.** Use the wait time productively:
- Improve summaries on notes that have weak or missing summaries
- Add more specific tags to notes that only have one generic tag
- Add `[[wiki-links]]` between related notes to build the knowledge graph
- Run `{hpr} lint -j` and fix any issues it finds
- Read notes you haven't read yet and look for links worth following in future rounds

**Step 10: Opinionated Synthesis (MANDATORY — end of report)** — A catalog of facts is not a report. You **MUST** append a section titled `## Opinionated Synthesis` at the very end of the report. This is where you stop reciting what sources said and start reasoning across them. **This section complements — it does not replace — the per-section analytical beats from Step 7.** If the body sections are purely descriptive and all the analysis is dumped in this section, the report is still a catalog with a synthesis bolted onto the end.

The synthesis section must include:

1. **Comparative analysis across categories** — don't just describe each concept/group/topic in isolation. Compare them. Use tables where useful.
2. **Thematic threads and progression** — what patterns cut across the topic? What's the narrative arc?
3. **Your reasoned position** — take a defensible stance, clearly labeled as your own analysis grounded in the sources.
4. **Open questions and limitations** — what did the sources NOT answer?
5. **Concluding thoughts** — one tight paragraph answering the original question.

Use these exact subheadings at the end of your report:

```markdown
## Opinionated Synthesis

### Comparative Analysis
<cross-cutting comparisons — tables where useful>

### Thematic Threads
<patterns, progressions, throughlines>

### My Reasoned Position
<your defensible stance, clearly labeled as analysis>

### Open Questions
<gaps in the research, what the sources didn't answer>

### Concluding Thoughts
<one tight paragraph, answers the original question>
```

**Do NOT skip this section.** Even a 9,000-word body of cataloged facts is incomplete without it. The synthesis is what separates a research report from a Wikipedia dump.

**Step 11: Prune** — After the final report is done, deprecate notes that turned out to be irrelevant:
```bash
{hpr} note update <id> --status deprecated -j
```
This keeps the KB clean without losing anything permanently.

### Why {hpr} fetch, not WebFetch

`{hpr} fetch` runs a real headless Chromium browser — it bypasses bot detection, saves full content with formatting, persists across sessions, and tracks URLs to prevent re-fetching. **Use WebFetch only for quick one-off lookups you don't need to save.**

### PDFs are fully supported — fetch them directly

`{hpr} fetch` automatically detects PDF URLs and extracts full text using pymupdf — no browser needed. **Fetch PDFs aggressively:**
- arXiv papers (both `/abs/` and `/pdf/` links work — auto-converted)
- NBER working papers, SSRN papers, direct `.pdf` links
- Conference proceedings, technical reports, whitepapers

PDF extraction is fast and produces clean text from all pages. **Do not skip a source just because it's a PDF.** If a paper is behind a paywall, look for preprint versions on arXiv, SSRN, ResearchGate, or the author's personal page.

Raw files are automatically saved to `research/raw/<note-id>.pdf` and linked from the note's frontmatter (`raw_file: raw/<note-id>.pdf`). You can read the raw PDF directly if you need to verify content or extract figures.

### Use scholarly APIs when available

For academic research, use APIs to find and access papers programmatically:
- **arXiv API** — `https://export.arxiv.org/api/query?search_query=...` returns XML with abstracts, authors, PDF links
- **Semantic Scholar API** — `https://api.semanticscholar.org/graph/v1/paper/search?query=...` returns structured paper data with citations
- **CrossRef API** — `https://api.crossref.org/works?query=...` for DOI lookups and metadata
- **PubMed/NCBI API** — for biomedical research

Write code to call these APIs when the topic is academic. The structured data (citation counts, related papers, abstracts) is often more useful than scraping a webpage. Fetch the actual papers via their PDF links after finding them through the API.

### Raw content is king

**Save raw source material with original formatting** — not rewritten summaries. Future agents need the full context to draw their own conclusions. Preserve headings, tables, code blocks, and technical details. Follow links to primary sources (the paper, not the blog post about the paper). Connect related notes with `[[note-id]]` wiki-links.

For manually written notes:
```bash
{hpr} note new "Title" --tag t1 --body-file /tmp/content.md --source "https://..." --summary "One-liner" --json
```

### Searching the research base

```bash
{hpr} search "query" --json                # Full-text search
{hpr} search "query" --tag ml --json       # Filter by tag, status, date, parent
{hpr} search "query" --include-body --json # Include full note bodies in results
{hpr} note show <id> --json                # Read a note
{hpr} note show <id1> <id2> <id3> --json   # Read multiple notes at once
{hpr} note list --json                     # List all notes with summaries
```

### Images, screenshots, and assets

Use `--save-assets` / `-a` when you need to capture visual content from a page:

```bash
{hpr} fetch "<url>" --tag <topic> --save-assets -j   # Saves screenshot + top images
```

This saves a screenshot of the rendered page and downloads the top content images (skipping icons, logos, ads). Only use this flag when visual content matters — diagrams, charts, figures, architecture images. For text-only pages, skip it.

```bash
{hpr} assets list --json                           # List all downloaded assets
{hpr} assets list --note <note-id> --json          # Assets for a specific note
{hpr} assets path <note-id> --type screenshot -j   # Get screenshot path (viewable with Read)
{hpr} assets path <note-id> --type image -j        # Get image paths
```

**To view an image or screenshot**, use the path from `{hpr} assets path` with your Read tool — it supports PNG, JPG, and other image formats directly.

### Authenticated crawling (social media, paywalled sites, etc.)

To access login-gated content (LinkedIn, Twitter, paywalled news), the user must create a login profile.
This is done once via `crwl profiles` or during `hyperresearch setup`.

```toml
# .hyperresearch/config.toml
[web]
provider = "crawl4ai"
profile = "research"      # Name of the login profile
magic = true
```

**If no profile is configured**, crawl4ai still works for public pages. If a fetch returns a login wall or "sign in to view" content, tell the user they need to set up a login profile:

```
To access login-gated sites, run: hyperresearch setup
Choose option 1 to create a login profile — a browser opens, you log into your sites, done.
```

**If fetches fail with browser crash / "failed to launch":**
The profile may be corrupted or the browser binary missing. Tell the user to run `crwl profiles`
to recreate the profile, or `playwright install chromium` to reinstall the browser.

### MANDATORY: Curate after every research session

The research base is a **long-lived knowledge investment**, not a scratchpad. Every future agent session benefits from well-organized notes. **After fetching sources, you MUST do a curation pass.**

**Step 1: Read and summarize every new note**
Fetched notes arrive as drafts with no summary. **You must read each note and write a real summary** — not a generic label but a specific description of what the source contains:
```bash
{hpr} note list --status draft -j                         # Find unprocessed notes
{hpr} note show <id> -j                                   # Read the note content
{hpr} note update <id> --summary "One-line summary" -j    # Add YOUR summary after reading it
{hpr} note update <id> --add-tag <topic> -j               # Add meaningful tags
```
- **Read the content first**, then write a summary that captures what's actually in it. "Maskin & Riley prove existence and uniqueness of equilibrium in asymmetric first-price auctions via ODE system" — not "Paper about auctions"
- REUSE existing tags: `{hpr} tags -j` — do not invent new ones unless truly novel, but add multiple relevant tags per note
- Every note MUST have: at least one tag, a summary (under 120 chars), a source URL
- For PDF notes, check the `raw_file` field in the frontmatter — it points to the actual PDF in `research/raw/`. You can read it directly if the extracted text is incomplete

**Step 2: Connect related notes with wiki-links**
Read through new notes and add `[[other-note-id]]` links to connect related material:
```bash
{hpr} search "related topic" -j                           # Find related notes
{hpr} note show <id> -j                                   # Read a note
```
Then edit the markdown file directly to add links like `See also: [[other-note-id]]` at the bottom. This builds the knowledge graph.

**Step 3: Promote quality notes**
Move notes through the lifecycle based on their value:
```bash
{hpr} note update <id> --status review -j     # Needs review but has good content
{hpr} note update <id> --status evergreen -j  # High-quality, lasting reference
```
- `draft` — just fetched, unprocessed
- `review` — has tags/summary, content looks good, needs human review
- `evergreen` — verified, high-quality, lasting value
- `stale` → `deprecated` → `archive` — for outdated material

**Step 4: Run health checks**
```bash
{hpr} lint -j      # Find notes missing tags, summaries, or with broken links
{hpr} repair -j    # Auto-fix broken links, rebuild indexes, promote eligible notes
{hpr} status -j    # Overall vault health
```

**Step 5: Check the knowledge graph**
```bash
{hpr} graph hubs -j              # Most linked-to notes (key topics)
{hpr} graph backlinks <id> -j    # What links TO this note
{hpr} graph broken -j            # Broken [[links]] to fix
```

### This is an investment, not a dump

The research base compounds across sessions. A well-curated note that three future agents can find and use is worth 10x a raw dump nobody can navigate. When doing research:

- **Tag consistently** — use the existing tag vocabulary, not ad-hoc variations
- **Write real summaries** — "Mamba achieves linear-time sequence modeling via selective state spaces" not "Paper about Mamba"
- **Link aggressively** — every note should link to related notes via `[[note-id]]`
- **Promote good notes** — move quality content from `draft` to `review` to `evergreen`
- **Deprecate stale content** — if a note is outdated, mark it `deprecated` rather than leaving it to mislead future agents
- **Build MOC (map of content) notes** — for major topics, create a synthesis note that links to all related sources with `type: moc`

### Key conventions

- Notes live in `research/notes/` as markdown with YAML frontmatter
- Link between notes with `[[note-id]]` syntax
- After editing .md files directly, run `{hpr} sync` to update the index
- Statuses: draft -> review -> evergreen -> stale -> deprecated -> archive
- Run `{hpr} --help` for the full command list
{end_marker}
"""

# Which files each agent flag creates
AGENT_FILES = {
    "claude": "CLAUDE.md",
    "agents": "AGENTS.md",
    "gemini": "GEMINI.md",
    "copilot": ".github/copilot-instructions.md",
}


def _resolve_executable() -> str:
    """Find the absolute path to the hyperresearch executable.

    Priority: venv sibling of current python > PATH > bare name.
    """
    import shutil
    import sys

    # First: find it relative to the current Python interpreter (venv installs).
    # This takes priority over PATH to avoid picking up a system-wide install.
    python_dir = Path(sys.executable).parent
    for name in ("hyperresearch", "hyperresearch.exe"):
        candidate = python_dir / name
        if candidate.exists():
            return str(candidate)
    # Also check Scripts/ subdirectory (Windows venv layout)
    for name in ("hyperresearch", "hyperresearch.exe"):
        candidate = python_dir / "Scripts" / name
        if candidate.exists():
            return str(candidate)

    # Second: check PATH
    which = shutil.which("hyperresearch")
    if which:
        return which

    # Fallback — bare name, hope it's on PATH
    return "hyperresearch"


def inject_agent_docs(
    vault_root: Path,
    agents: list[str] | None = None,
) -> list[str]:
    """Inject hyperresearch docs into agent config files.

    Args:
        vault_root: The repo root.
        agents: Which agent files to create. Default: ["claude"].
                Options: "claude", "agents", "gemini", "copilot".
                If a file already exists, it's always updated regardless of this list.
    """
    if agents is None:
        agents = ["claude"]

    hpr_path = _resolve_executable()
    # Use forward slashes — bash on Windows eats backslashes
    hpr_path = hpr_path.replace("\\", "/")
    from datetime import date
    blurb = HYPERRESEARCH_BLURB.format(
        marker=HYPERRESEARCH_SECTION_MARKER,
        end_marker=HYPERRESEARCH_SECTION_END,
        hpr=hpr_path,
        today=date.today().isoformat(),
    )
    modified = []

    # Determine which files to handle
    files_to_inject: list[tuple[Path, str]] = []

    # CLAUDE.md
    if "claude" in agents or (vault_root / "CLAUDE.md").exists():
        files_to_inject.append((vault_root / "CLAUDE.md", "CLAUDE.md"))

    # AGENTS.md — prefer uppercase, respect existing lowercase
    if "agents" in agents or (vault_root / "AGENTS.md").exists() or (vault_root / "agents.md").exists():
        if (vault_root / "agents.md").exists() and not (vault_root / "AGENTS.md").exists():
            files_to_inject.append((vault_root / "agents.md", "agents.md"))
        else:
            files_to_inject.append((vault_root / "AGENTS.md", "AGENTS.md"))

    # GEMINI.md
    if "gemini" in agents or (vault_root / "GEMINI.md").exists():
        files_to_inject.append((vault_root / "GEMINI.md", "GEMINI.md"))

    # .github/copilot-instructions.md
    copilot_path = vault_root / ".github" / "copilot-instructions.md"
    if "copilot" in agents or copilot_path.exists():
        files_to_inject.append((copilot_path, ".github/copilot-instructions.md"))

    for filepath, filename in files_to_inject:
        result = _inject_into_file(filepath, blurb, filename)
        if result:
            modified.append(result)

    return modified


def _inject_into_file(filepath: Path, blurb: str, filename: str) -> str | None:
    """Inject the hyperresearch blurb into a single file. Returns action taken or None."""
    if filepath.exists():
        content = filepath.read_text(encoding="utf-8-sig")

        if HYPERRESEARCH_SECTION_MARKER in content:
            pattern = re.compile(
                re.escape(HYPERRESEARCH_SECTION_MARKER) + r".*?" + re.escape(HYPERRESEARCH_SECTION_END),
                re.DOTALL,
            )
            new_content = pattern.sub(lambda _: blurb.strip(), content)
            if new_content != content:
                filepath.write_text(new_content, encoding="utf-8")
                return f"{filename} (updated)"
            return None
        else:
            separator = "\n\n" if not content.endswith("\n") else "\n"
            filepath.write_text(content + separator + blurb.strip() + "\n", encoding="utf-8")
            return f"{filename} (appended)"
    else:
        filepath.parent.mkdir(parents=True, exist_ok=True)
        header = f"# {filepath.stem}\n"
        filepath.write_text(header + blurb.strip() + "\n", encoding="utf-8")
        return f"{filename} (created)"
