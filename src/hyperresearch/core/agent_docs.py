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

This project uses hyperresearch as an agent-driven research knowledge base. The `research/` directory contains markdown notes collected from web sources and original research. Append `--json` to any command for structured output.

### MANDATORY: How to do research

When the user asks you to research a topic, **you MUST follow this workflow**. Do NOT use WebFetch for source pages — use `{hpr} fetch` instead. It runs a real headless browser, handles JavaScript, bypasses bot detection, saves full content with screenshots and images, and indexes everything for future sessions.

**This is a deep research tool.** Your job is to go down rabbit holes, cast a wide net, and collect as much raw source material as possible. **Over-collect, then prune.** It is always better to have too many sources than too few — you can deprecate notes later, but you can't un-skip a source you never fetched.

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

Quality over quantity — but on complex topics, true comprehensiveness requires quantity. If you've only collected 15-25 sources on a PhD-level question, you've barely scratched the surface. Expect to need:
- Simple factual question: 20-30 sources
- Complex or technical topic: 50-80 sources
- PhD-level research question: 80-100+ sources

If you've exhausted every angle and there's genuinely nothing left to find, that's fine — move on. But be honest with yourself about whether you've actually exhausted it or just stopped early.

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

**Step 5: Synthesize** — Once you have the raw sources indexed, search and read them to build your synthesis:
```bash
{hpr} search "topic" --include-body -j
```

Write a draft report with inline URL citations.

**Step 6: Gap analysis (MANDATORY)** — After writing your draft, stop and compare it against the original query. Re-read the user's request word by word. Ask yourself:
- What specific questions did they ask that I haven't fully answered?
- What subtopics or angles did I miss entirely?
- Where did I make claims without strong enough evidence?
- What would an expert in this field say is missing?

Then launch a new round of research to fill every gap — web search, fetch, follow links, the full workflow. Spawn fetcher subagents in parallel for the new URLs. Add the new material to your draft.

**Step 7: Adversarial audit (MANDATORY — do this twice)** — After the gap-filling round, launch two subagents in parallel to audit the revised draft. This runs up to 2 loops.

Spawn two agents in parallel:
- **Agent 1 — Comprehensiveness auditor:** "Read this report and search the research base (`{hpr} search` and `{hpr} note show`) to find gaps. What subtopics, angles, data points, or counterarguments are missing? What claims lack citations? What sections are shallow? Compare against the original query and be ruthless — list every gap."
- **Agent 2 — Logic and structure auditor:** "Read this report as a domain expert. Does the argument flow logically? Are conclusions supported by the evidence presented? Are there logical leaps, unsupported claims, or contradictions? Is the structure optimal for the topic? Be specific — list every weakness."

Pass your full draft report text to both agents. They search the research base independently and report back.

**After each audit round:**
1. Read both agents' feedback
2. If they identified missing topics or weak arguments — do another round of web search and fetching to fill the gaps
3. Rewrite the report incorporating new sources and fixing structural issues
4. Run the audit again (second loop) on the revised report

**You MUST do at least one audit loop. Do two if the first audit found significant gaps.** Only after the auditors have no major complaints should you finalize the report.

**While audit agents are running, don't idle.** Use the wait time productively:
- Improve summaries on notes that have weak or missing summaries
- Add more specific tags to notes that only have one generic tag
- Add `[[wiki-links]]` between related notes to build the knowledge graph
- Run `{hpr} lint -j` and fix any issues it finds
- Read notes you haven't read yet and look for links worth following in future rounds

**Step 8: Prune** — After the final report is done, deprecate notes that turned out to be irrelevant:
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
