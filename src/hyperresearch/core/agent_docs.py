"""Agent documentation integration — inject the hyperresearch blurb into CLAUDE.md.

hyperresearch is a Claude Code harness. This module writes/updates CLAUDE.md
at the vault root so Claude Code auto-loads the research workflow on every
session. Pre-existing AGENTS.md / GEMINI.md / .github/copilot-instructions.md
files (from older hyperresearch vaults or other tools) are left alone — we
don't delete user content, but we no longer generate them either.
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

When the user asks you to research a topic, **default to `/research-layercake`** — the 7-phase pipeline that discovers width first, derives depth loci from the width corpus, runs parallel depth investigations, drafts once, and patches the draft via adversarial critics (no regeneration). The protocol lives in `.claude/skills/research-layercake/SKILL.md`.

Use the single-pass `/research` skill only when the user explicitly asks for a faster run or when the query is trivial enough that the layercake overhead is wasteful. The single-pass protocol lives in `.claude/skills/hyperresearch/SKILL.md`.

**Do NOT use WebFetch for source pages** — use `{hpr} fetch` instead.

SKILL.md classifies your request by cognitive activity (what the output needs to DO, not what the subject IS) and routes to one of 4 modality files: SKILL-collect.md (enumerative coverage with per-entity fields), SKILL-synthesize.md (defended thesis or mechanism explanation), SKILL-compare.md (per-entity evaluation with committed recommendation), or SKILL-forecast.md (forward-looking prediction with explicit time horizon). The dispatcher owns the shared protocol (discovery, fetch, guided reading loop, curation, scaffold, comparisons, draft, audit, synthesis). Each modality file encodes only the substance rules and conformance checks specific to that activity. Read SKILL.md first — it owns the process and will tell you which modality file to open next for substance guidance.

**The canonical research query is gospel.** In normal runs that is the user's verbatim prompt. In wrapped runs, if `research/prompt.txt` exists, that file is the canonical research query for the scaffold and every downstream subagent call. Keep wrapper instructions separate: required save path, citation format, or wrapper-specific closing sections are binding packaging requirements, but they do NOT belong inside the `## User Prompt (VERBATIM — gospel)` section.

### Layercake pipeline — 7 phases

Width first, depth second, one draft, patched not regenerated.

1. **Width sweep** — 30-80 sources fetched in parallel via `hyperresearch-fetcher` batches. Academic APIs before web search.
2. **Loci analysis** — 2 `hyperresearch-loci-analyst` subagents read the width corpus in parallel and each returns 1-8 specific "depth loci" (questions where deeper investigation pays off). The orchestrator dedupes and clamps to 6.
3. **Depth investigation** — 1 `hyperresearch-depth-investigator` per locus, in parallel. Each can spawn its own fetchers (up to 10 new sources per locus) and writes ONE `interim-{{locus}}.md` note to the vault.
4. **Draft** — the orchestrator writes `research/notes/final_report.md` ONCE, weaving the width corpus with the interim notes and following the modality file's substance rules.
5. **Adversarial critique** — 3 critics in parallel: `hyperresearch-dialectic-critic` (counter-evidence the draft missed), `hyperresearch-depth-critic` (shallow spots the interim notes could fill), `hyperresearch-width-critic` (topical corners the draft ignores). Each returns a findings JSON with `suggested_patch` entries.
6. **Patch pass** — `hyperresearch-patcher` (tool-locked to `[Read, Edit]`) reads all three findings files and applies them as surgical Edit hunks. It cannot Write. It cannot regenerate. Per-hunk ≤500-char expansion cap.
7. **Polish audit** — `hyperresearch-polish-auditor` (also `[Read, Edit]` only) strips hygiene leaks, cuts filler, breaks long sentences, flags structural mismatches to the orchestrator.

The patching invariant is load-bearing: after Layer 4 the draft is only ever modified by small Edit hunks. If a critic's finding cannot fit into a ≤500-char hunk, it escalates to the orchestrator as a structural issue. This prevents the "just rewrite it" failure mode that plagues post-hoc review in long-running agent pipelines.

Layercake takes longer than a single `/research` pass — that is the trade you are making on purpose by invoking the default mode.

### Why {hpr} fetch, not WebFetch

`{hpr} fetch` runs a real headless Chromium browser — it bypasses bot detection, saves full content with formatting, persists across sessions, and tracks URLs to prevent re-fetching. **Use WebFetch only for quick one-off lookups you don't need to save.**

### PDFs are fully supported — fetch them directly

`{hpr} fetch` automatically detects PDF URLs and extracts full text using pymupdf — no browser needed. **Fetch PDFs aggressively:**
- arXiv papers (both `/abs/` and `/pdf/` links work — auto-converted)
- NBER working papers, SSRN papers, direct `.pdf` links
- Conference proceedings, technical reports, whitepapers

PDF extraction is fast and produces clean text from all pages. **Do not skip a source just because it's a PDF.** If a paper is behind a paywall, look for preprint versions on arXiv, SSRN, ResearchGate, or the author's personal page.

Raw files are automatically saved to `research/raw/<note-id>.pdf` and linked from the note's frontmatter (`raw_file: raw/<note-id>.pdf`). You can read the raw PDF directly if you need to verify content or extract figures.

### MANDATORY: Academic API sweep before web search

For any topic with a research literature, **query academic APIs BEFORE running web searches.** Academic APIs return citation-ranked canonical papers. Web search returns derivative commentary. This order matters — getting it backwards biases your entire source set toward secondhand summaries.

**Semantic Scholar** — citation-count search + forward/backward citation chaining:
```python
import urllib.request, json, time, urllib.parse
q = urllib.parse.quote("your topic")
url = "https://api.semanticscholar.org/graph/v1/paper/search?query=" + q + "&fields=title,year,citationCount,externalIds&limit=10"
with urllib.request.urlopen(url) as r:
    papers = json.loads(r.read())["data"]
papers.sort(key=lambda p: p.get("citationCount", 0), reverse=True)
# Then citation chain: for top 3 papers, fetch references + citations
for paper in papers[:3]:
    pid = paper["paperId"]
    refs = "https://api.semanticscholar.org/graph/v1/paper/" + pid + "/references?fields=title,year,citationCount&limit=30"
    cits = "https://api.semanticscholar.org/graph/v1/paper/" + pid + "/citations?fields=title,year,citationCount,isInfluential&limit=50"
    # fetch both, sort results by citationCount, add top papers to fetch queue
    time.sleep(0.4)
```
Backward chaining finds the foundational canon; forward chaining finds everything built on it in the last 3 years.

**arXiv API** — for cs.*, stat.*, q-bio.*, econ.*, math.*, physics.*:
```
https://export.arxiv.org/api/query?search_query=cat:cs.LG+AND+all:<topic>&sortBy=relevance&max_results=25
```
Returns Atom XML with titles, abstracts, and direct PDF links. Feed the PDF links to `{hpr} fetch`.

**OpenAlex** — for humanities, social science, medicine, or non-arXiv disciplines:
```
https://api.openalex.org/works?search=<topic>&sort=cited_by_count:desc&per-page=15&mailto=research@example.com
```
Covers 250M+ works across all disciplines. `related_works` on a known paper finds its citation neighborhood.

**PubMed eutils** — for biomedical/clinical topics:
```
https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term=<topic>&retmode=json&retmax=20
```

After the academic sweep, run web searches for context, news, and non-academic angles — including at least one adversarial search ("criticism of X", "limitations of X", "X does not work").

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


def inject_agent_docs(vault_root: Path) -> list[str]:
    """Inject hyperresearch docs into CLAUDE.md at the vault root.

    Always writes/updates CLAUDE.md. Does NOT touch AGENTS.md, GEMINI.md,
    or .github/copilot-instructions.md — hyperresearch is a Claude Code
    harness now, not a multi-platform tool. Pre-existing non-Claude doc
    files are left untouched (we don't delete user content), but no new
    ones are created.
    """
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

    modified: list[str] = []
    result = _inject_into_file(vault_root / "CLAUDE.md", blurb, "CLAUDE.md")
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
