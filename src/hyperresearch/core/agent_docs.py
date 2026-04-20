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

HYPERRESEARCH_BLURB = """
{marker}
## Research Base (hyperresearch) — Today is {today}

**CLI path: `{hpr}`** — use this exact path for every hyperresearch command. It may not be on your system PATH.

**Paths in this document are relative to your current working directory**, not to the CLI binary's location. Use `research/notes/final_report.md` (not a prefix with the binary path) when you save files.

This project uses hyperresearch as an agent-driven research knowledge base. The `research/` directory contains markdown notes collected from web sources and original research. Append `--json` to any command for structured output.

### How to do research

**Default: `/research-layercake <query>`** — the 7-phase pipeline. The protocol, subagent roster, pipeline contracts, and invariants all live in the skill file at `.claude/skills/research-layercake/SKILL.md`. Read that file before you start a research session; it is the single source of truth for how layercake runs.

For a quick single-pass run (no loci, no critics, no patcher), use `/research <query>` — protocol in `.claude/skills/hyperresearch/SKILL.md` and the 4 modality files alongside it.

**Do NOT use WebFetch for source pages** — use `{hpr} fetch` instead. The skill files explain when to fetch vs. search.

### What the skill files own

The skill files own everything about how to research. That includes:
- The pipeline phases and what each phase does
- Which subagents exist and what each one is for (fetcher, loci-analyst, depth-investigator, 4 critics, patcher, polish-auditor)
- The tool-lock invariant (patcher and polish-auditor can only Read + Edit, never Write)
- The subagent spawn contract (every Task call passes the verbatim research_query + pipeline position + inputs)
- Artifact locations (`research/scaffold.md`, `research/prompt-decomposition.json`, `research/loci.json`, `research/comparisons.md`, interim notes, patch / polish logs)
- The curation pass after every research session

If you need to know how layercake works, read the skill file. This document does NOT duplicate that content — when the skill file and this file disagree, the skill file wins.

### Canonical research query

In a normal run, the canonical research query is the user's verbatim prompt. In wrapped runs, if `research/prompt.txt` exists, that file is gospel and overrides any wrapping instructions. Wrapper requirements (save path, citation format, terminal sections) are a separate contract, captured in the scaffold — not pasted into the `## User Prompt (VERBATIM — gospel)` section.

### Academic APIs before web search

For any topic with a research literature, hit academic APIs BEFORE running web searches. They return citation-ranked canonical papers; web search returns derivative commentary.

- **Semantic Scholar:** `https://api.semanticscholar.org/graph/v1/paper/search?query=<q>&fields=title,year,citationCount,externalIds&limit=10` — then citation-chain the top papers forward + backward.
- **arXiv:** `https://export.arxiv.org/api/query?search_query=cat:cs.LG+AND+all:<q>&sortBy=relevance&max_results=25`
- **OpenAlex:** `https://api.openalex.org/works?search=<q>&sort=cited_by_count:desc&per-page=15&mailto=research@example.com`
- **PubMed:** `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term=<q>&retmode=json&retmax=20`

After the academic sweep, run web searches for context, news, non-academic angles, and at least one adversarial search ("criticism of X", "limitations of X").

### PDFs fetch directly

`{hpr} fetch` auto-detects PDF URLs (arXiv, NBER, SSRN, direct `.pdf` links) and extracts full text via pymupdf. Fetch them aggressively. Raw PDFs land in `research/raw/<note-id>.pdf` and the note's frontmatter links back via `raw_file:`.

### Searching the vault

```bash
{hpr} search "query" --json                # Full-text search
{hpr} search "query" --tag ml --json       # Filter by tag / status / date / parent
{hpr} search "query" --include-body --json # Full-body search, not just titles
{hpr} note show <id> --json                # Read one note
{hpr} note show <id1> <id2> <id3> --json   # Batch-read notes in one call
{hpr} note list --json                     # List all notes with summaries
{hpr} tags --json                          # Existing tag vocabulary
```

### Images, screenshots, and assets

```bash
{hpr} fetch "<url>" --tag <topic> --save-assets -j   # Saves screenshot + top images
{hpr} assets list --note <note-id> --json            # Assets for a specific note
{hpr} assets path <note-id> --type screenshot -j     # Get screenshot path (viewable with Read)
```

### Authenticated crawling

Login-gated content (LinkedIn, Twitter, paywalled news) needs a browser profile. Set up once via `{hpr} setup` or `crwl profiles`. Config in `.hyperresearch/config.toml` under `[web]`: `profile = "research"`, `magic = true`. LinkedIn / Twitter / Facebook / Instagram / TikTok auto-use a visible browser to avoid session kills.

If a fetch returns a login wall, tell the user to run `{hpr} setup` and create a login profile.

### Curate after every session

Every research session must end with a curation pass:

```bash
{hpr} note list --status draft -j                                        # Find unprocessed notes
{hpr} note show <id> -j                                                  # Read the content
{hpr} note update <id> --summary "<specific summary>" --add-tag <t> -j   # Add summary + tags
{hpr} lint -j                                                            # Find missing tags / summaries / broken links
{hpr} repair -j                                                          # Auto-fix broken links, rebuild indexes
{hpr} status -j                                                          # Overall vault health
```

Lifecycle: `draft` → `review` → `evergreen` (or `stale` → `deprecated` → `archive` for outdated material).

Summaries must be specific — "Mamba achieves linear-time sequence modeling via selective state spaces" beats "Paper about Mamba". Reuse the existing tag vocabulary (`{hpr} tags -j`) rather than inventing new tags.

### Key conventions

- Notes live in `research/notes/` as markdown with YAML frontmatter
- Link notes with `[[note-id]]` syntax
- After editing `.md` files directly, run `{hpr} sync` to update the index
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
