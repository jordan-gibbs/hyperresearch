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

**Over-collect.** It is always better to have too many sources than too few. You can deprecate notes later.

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

If there's more to get, go get it. If you've genuinely exhausted the topic, move on. But be honest — on complex topics, expect 50-80+ sources before you've truly covered it.

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

## Step 7: Synthesize draft report

Search the full research base with bodies:

```bash
$HPR search "<topic>" --include-body -j
```

Read the top notes and write a comprehensive draft report with inline URL citations.

## Step 8: Gap analysis (MANDATORY)

After writing your draft, stop and compare it against the original query. Re-read the user's request word by word:
- What specific questions did they ask that I haven't fully answered?
- What subtopics or angles did I miss entirely?
- Where did I make claims without strong enough evidence?
- What would an expert in this field say is missing?

Launch a new round of research to fill every gap — web search, fetch, follow links, spawn fetcher subagents in parallel. Add the new material to your draft.

## Step 9: Adversarial audit (MANDATORY — do this twice)

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
Read this report as a domain expert. Does the argument flow logically? Are conclusions
supported by the evidence presented? Are there logical leaps, unsupported claims, or
contradictions? Is the structure optimal for the topic? Be specific — list every weakness.
```

Pass your full draft report text to both agents.

**After each audit round:**
1. Read both agents' feedback
2. If they found missing topics or weak arguments — do another round of web search + fetching
3. Rewrite the report with new sources and structural fixes
4. Run the audit again (second loop) on the revised report

**Do at least one audit loop. Do two if the first found significant gaps.** Only finalize after auditors have no major complaints.

**While audit agents are running, don't idle.** Use the wait time to:
- Improve weak or missing summaries on notes (`$HPR note update <id> --summary "..." -j`)
- Add more specific tags to under-tagged notes (`$HPR note update <id> --add-tag <tag> -j`)
- Add `[[wiki-links]]` between related notes
- Run `$HPR lint -j` and fix issues
- Read notes you haven't reviewed yet for links worth following

## Step 10: Save the final report

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

## Step 11: Present to user

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
