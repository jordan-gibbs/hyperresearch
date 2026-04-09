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

This project uses hyperresearch as an agent-driven research knowledge base. The `research/` directory contains markdown notes collected from web sources and original research. Append `--json` to any command for structured output.

### Search and read

```bash
hyperresearch search "query" --json                # Full-text search
hyperresearch search "query" --tag ml --json       # Filter by tag, status, date, parent
hyperresearch search "query" --include-body --json # Include full note bodies in results
hyperresearch note show <id> --json                     # Read a note
hyperresearch note show <id1> <id2> <id3> --json        # Read multiple notes at once
hyperresearch note list --json                          # List all notes with summaries
```

### Collect research

When you find useful information via web search or browsing, save it as a note:

```bash
hyperresearch note new "Title" --tag t1 --body-file /tmp/content.md --source "https://..." --summary "One-liner" --json
hyperresearch note update <id> --status evergreen --add-tag ml --summary "Updated" --json
```

**Always check the research base BEFORE searching the web** — the answer may already be here.

### Knowledge graph and maintenance

```bash
hyperresearch graph backlinks <id> --json    # What links TO this note
hyperresearch graph hubs --json              # Most linked-to notes
hyperresearch graph broken --json            # Broken [[links]]
hyperresearch lint --json                    # Health check
hyperresearch repair --json                  # Full rebuild + fix broken links + promote notes
hyperresearch status --json                  # Vault overview
```

### Note quality requirements

Every note MUST have:
- At least one tag (`--tag`). REUSE existing tags from `hyperresearch tags -j` -- do not invent new ones unless necessary.
- A summary (`--summary`). One sentence, under 120 characters.
- A body with meaningful content (50+ words).
- A source URL (`--source`) when the content comes from the web.
- Use `--body-file` instead of `--body` to avoid shell escaping issues.

Run `hyperresearch lint -j` to check quality, `hyperresearch repair -j` to auto-fix.

### Key conventions

- Notes live in `research/notes/` as markdown with YAML frontmatter
- Link between notes with `[[note-id]]` syntax
- After editing .md files directly, run `hyperresearch sync` to update the index
- Statuses: draft -> review -> evergreen -> stale -> deprecated -> archive
- Run `hyperresearch --help` for the full command list
{end_marker}
"""

# Which files each agent flag creates
AGENT_FILES = {
    "claude": "CLAUDE.md",
    "agents": "AGENTS.md",
    "gemini": "GEMINI.md",
    "copilot": ".github/copilot-instructions.md",
}


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

    blurb = HYPERRESEARCH_BLURB.format(marker=HYPERRESEARCH_SECTION_MARKER, end_marker=HYPERRESEARCH_SECTION_END)
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
            new_content = pattern.sub(blurb.strip(), content)
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
