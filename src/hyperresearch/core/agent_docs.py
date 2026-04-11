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
## Research Base (hyperresearch)

**CLI path: `{hpr}`** — use this exact path for all hyperresearch commands below. It may not be on your system PATH.

This project uses hyperresearch as an agent-driven research knowledge base. The `research/` directory contains markdown notes collected from web sources and original research. Append `--json` to any command for structured output.

### MANDATORY: How to do research

When the user asks you to research a topic, **you MUST follow this workflow**. Do NOT use WebFetch for source pages — use `{hpr} fetch` instead. It runs a real headless browser, handles JavaScript, bypasses bot detection, saves full content with screenshots and images, and indexes everything for future sessions.

**This is a deep research tool.** Your job is to go down rabbit holes, cast a wide net, and collect as much raw source material as possible. **Over-collect, then prune.** It is always better to have too many sources than too few — you can deprecate notes later, but you can't un-skip a source you never fetched.

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

**Spawn multiple fetcher agents in parallel** — one per URL or small batch. They run on Haiku, so this is fast and cheap. Err on the side of fetching too many pages.

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

**The goal is exhaustive collection.** You are building a knowledge base that future agents will rely on. Missing a source is worse than having one extra note. Prune later during curation.

**Step 5: Synthesize** — Once you have the raw sources indexed, search and read them to build your synthesis:
```bash
{hpr} search "topic" --include-body -j
```

**Step 6: Prune** — After synthesis, deprecate notes that turned out to be irrelevant:
```bash
{hpr} note update <id> --status deprecated -j
```
This keeps the KB clean without losing anything permanently.

### Why {hpr} fetch, not WebFetch

`{hpr} fetch` runs a real headless Chromium browser — it bypasses bot detection, saves full content with formatting, persists across sessions, and tracks URLs to prevent re-fetching. **Use WebFetch only for quick one-off lookups you don't need to save.**

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

**Step 1: Tag and summarize every new note**
Fetched notes arrive as drafts with no summary. Fix each one:
```bash
{hpr} note list --status draft -j                         # Find unprocessed notes
{hpr} note update <id> --summary "One-line summary" -j    # Add summary
{hpr} note update <id> --add-tag <topic> -j               # Add tags
```
- REUSE existing tags: `{hpr} tags -j` — do not invent new ones unless truly novel
- Every note MUST have: at least one tag, a summary (under 120 chars), a source URL
- Summaries should be specific and searchable, not generic ("Overview of X" is useless; "X achieves Y by doing Z" is useful)

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
    """Find the absolute path to the hyperresearch executable."""
    import shutil
    import sys

    # Check if it's on PATH already
    which = shutil.which("hyperresearch")
    if which:
        return which

    # Find it relative to the current Python interpreter (works for venv installs)
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
    blurb = HYPERRESEARCH_BLURB.format(
        marker=HYPERRESEARCH_SECTION_MARKER,
        end_marker=HYPERRESEARCH_SECTION_END,
        hpr=hpr_path,
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
