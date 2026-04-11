"""Agent hook installer — injects PreToolUse hooks for Claude Code, Codex, Cursor, Gemini CLI.

These hooks remind agents to check the research base before doing raw web searches.
Also installs a research subagent that uses a cheap model for URL fetching.
"""

from __future__ import annotations

import json
from pathlib import Path

# Subagent definition for Claude Code — uses haiku for cheap URL fetching
RESEARCHER_AGENT = """\
---
name: hyperresearch-fetcher
description: >
  Use this agent to fetch web URLs into the research base. Delegate to this agent
  whenever you need to fetch one or more URLs with hyperresearch. It runs on a cheap,
  fast model — spawn multiple in parallel for bulk research. Do NOT do URL fetching
  yourself when this agent is available.
model: haiku
tools: Bash, Read
color: blue
---

You are a research fetcher. Your job is to fetch URLs and save them to the
hyperresearch knowledge base using the CLI.

## Error handling

If you get AUTH_REQUIRED or "Redirected to login page":
- The browser profile session has expired.
- Tell the parent agent: "Auth expired for this site. User needs to run
  'hyperresearch setup' and re-create their login profile."
- Do NOT retry — the session is dead.

Note: LinkedIn, Twitter, Facebook, Instagram, and TikTok automatically use a
visible browser window to avoid session kills. No --visible flag needed.

If you get a browser crash or "failed to launch" error:
- Tell the parent agent the exact error message.
- Do NOT retry — it will fail the same way.

## Commands

On Windows, ALWAYS prefix commands with `PYTHONIOENCODING=utf-8`:

```bash
PYTHONIOENCODING=utf-8 {hpr_path} fetch "<url>" --tag <topic> -j
```

For each URL you are given:

1. Check if it's already fetched:
   PYTHONIOENCODING=utf-8 {hpr_path} sources check "<url>" -j

2. If not already fetched, fetch it:
   PYTHONIOENCODING=utf-8 {hpr_path} fetch "<url>" --tag <topic> -j

3. After fetching, read the note and look for links worth following:
   PYTHONIOENCODING=utf-8 {hpr_path} note show <note-id> -j

4. Report back: the note ID, title, word count, AND a list of links found
   in the content that look like they lead to primary sources, references,
   related material, or deeper content. Be aggressive — list anything that
   might be worth fetching. The parent agent will decide what to pursue.

If the first fetch fails with a browser error, stop and report the error.
Do not attempt remaining URLs.

If given multiple URLs and fetching works, process them sequentially. Report results for each.

Keep your responses short — just the facts. The parent agent will synthesize.
"""

# The hook script that gets installed
HOOK_SCRIPT_TEMPLATE = """\
#!/usr/bin/env node
/**
 * hyperresearch PreToolUse hook — reminds agent to check research base first.
 * Installed by: hyperresearch install
 */
const fs = require('fs');
const path = require('path');

const HPR = '{hpr_path}';

// Check if a .hyperresearch directory exists (vault is initialized)
function findVault() {{
    let dir = process.env.CLAUDE_PROJECT_DIR || process.cwd();
    while (true) {{
        if (fs.existsSync(path.join(dir, '.hyperresearch'))) return dir;
        const parent = path.dirname(dir);
        if (parent === dir) return null;
        dir = parent;
    }}
}}

const vault = findVault();
if (vault) {{
    const msg = [
        'HYPERRESEARCH: A research knowledge base exists in this project.',
        '',
        'BEFORE searching the web, check existing research:',
        '  ' + HPR + ' search "<your query>" -j',
        '',
        'DO NOT use WebFetch for source pages. Use hyperresearch fetch instead:',
        '  ' + HPR + ' fetch "<url>" --tag <topic> -j',
        'It runs a real headless browser, saves full content + screenshot, and indexes for future sessions.',
        '',
        'After fetching, READ the content and FOLLOW LINKS to primary sources. Keep fetching until you have the real sources, not just summaries.',
        '',
        'For multiple URLs, use subagents to fetch in parallel.',
    ].join('\\n');
    process.stderr.write(msg + '\\n');
}}
"""

# Cursor rule file content
CURSOR_RULE = """\
---
description: Hyperresearch research base integration
alwaysApply: true
---

# Research Base (hyperresearch)

This project has a hyperresearch research base.

**When researching, ALWAYS follow this workflow:**

1. **Check existing research**: `hyperresearch search "<query>" -j`
2. **Fetch source pages** using a cheap subagent or lower-tier model — do NOT use your main context for fetching. Use `hyperresearch fetch "<url>" --tag <topic> -j`
3. **Read fetched content and follow links** to primary sources — fetch the paper, not the blog post about it
4. **Keep going** until you have the real sources, not summaries
5. **Delegate fetching to cheaper/faster models** when your platform supports subagents

The research base persists across sessions. Raw source material with formatting > rewritten summaries.
"""


def install_hooks(vault_root: Path, platforms: list[str] | None = None, hpr_path: str = "hyperresearch") -> list[str]:
    """Install agent hooks for specified platforms. Returns list of actions taken."""
    if platforms is None:
        platforms = ["claude"]

    actions = []

    if "claude" in platforms or "all" in platforms:
        result = _install_claude_hook(vault_root, hpr_path)
        if result:
            actions.append(result)
        result = _install_research_skill(vault_root)
        if result:
            actions.append(result)
        result = _install_researcher_agent(vault_root, hpr_path)
        if result:
            actions.append(result)

    if "codex" in platforms or "all" in platforms:
        result = _install_codex_hook(vault_root, hpr_path)
        if result:
            actions.append(result)

    if "cursor" in platforms or "all" in platforms:
        result = _install_cursor_rule(vault_root)
        if result:
            actions.append(result)

    if "gemini" in platforms or "all" in platforms:
        result = _install_gemini_hook(vault_root, hpr_path)
        if result:
            actions.append(result)

    return actions


def _write_hook_script(vault_root: Path, hpr_path: str) -> Path:
    """Write the hook JS script to .hyperresearch/hook.js."""
    hook_dir = vault_root / ".hyperresearch"
    hook_dir.mkdir(parents=True, exist_ok=True)
    hook_path = hook_dir / "hook.js"
    # Escape backslashes for JS string literal
    js_path = hpr_path.replace("\\", "\\\\")
    hook_path.write_text(HOOK_SCRIPT_TEMPLATE.format(hpr_path=js_path), encoding="utf-8")
    return hook_path


def _install_claude_hook(vault_root: Path, hpr_path: str) -> str | None:
    """Install PreToolUse hook into .claude/settings.json."""
    hook_path = _write_hook_script(vault_root, hpr_path)

    settings_dir = vault_root / ".claude"
    settings_dir.mkdir(exist_ok=True)
    settings_path = settings_dir / "settings.json"

    settings = {}
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    hooks = settings.setdefault("hooks", {})
    pre_tool = hooks.setdefault("PreToolUse", [])

    # Check if already installed
    for entry in pre_tool:
        if isinstance(entry, dict):
            for h in entry.get("hooks", []):
                if "hyperresearch" in h.get("command", ""):
                    return None  # Already installed

    # Add hook that fires before web-related tools
    pre_tool.append({
        "matcher": "Glob|Grep|WebSearch|WebFetch",
        "hooks": [{
            "type": "command",
            "command": f"node {hook_path.as_posix()}",
        }],
    })

    settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    return "Claude Code: .claude/settings.json (PreToolUse hook)"


def _install_codex_hook(vault_root: Path, hpr_path: str) -> str | None:
    """Install hook into .codex/hooks.json."""
    hook_path = _write_hook_script(vault_root, hpr_path)

    codex_dir = vault_root / ".codex"
    codex_dir.mkdir(exist_ok=True)
    hooks_path = codex_dir / "hooks.json"

    hooks = {}
    if hooks_path.exists():
        try:
            hooks = json.loads(hooks_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    pre_tool = hooks.setdefault("PreToolUse", [])
    for entry in pre_tool:
        if isinstance(entry, dict):
            for h in entry.get("hooks", []):
                if "hyperresearch" in h.get("command", ""):
                    return None

    pre_tool.append({
        "matcher": "Bash",
        "hooks": [{
            "type": "command",
            "command": f"node {hook_path.as_posix()}",
        }],
    })

    hooks_path.write_text(json.dumps(hooks, indent=2) + "\n", encoding="utf-8")
    return "Codex: .codex/hooks.json (PreToolUse hook)"


def _install_cursor_rule(vault_root: Path) -> str | None:
    """Install always-apply rule into .cursor/rules/hyperresearch.mdc."""
    rules_dir = vault_root / ".cursor" / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    rule_path = rules_dir / "hyperresearch.mdc"

    if rule_path.exists():
        return None  # Already exists

    rule_path.write_text(CURSOR_RULE, encoding="utf-8")
    return "Cursor: .cursor/rules/hyperresearch.mdc (alwaysApply rule)"


def _install_gemini_hook(vault_root: Path, hpr_path: str) -> str | None:
    """Install BeforeTool hook into .gemini/settings.json."""
    hook_path = _write_hook_script(vault_root, hpr_path)

    gemini_dir = vault_root / ".gemini"
    gemini_dir.mkdir(exist_ok=True)
    settings_path = gemini_dir / "settings.json"

    settings = {}
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    hooks = settings.setdefault("hooks", {})
    before_tool = hooks.setdefault("BeforeTool", [])

    for entry in before_tool:
        if isinstance(entry, dict):
            for h in entry.get("hooks", []):
                if "hyperresearch" in h.get("command", ""):
                    return None

    before_tool.append({
        "hooks": [{
            "type": "command",
            "command": f"node {hook_path.as_posix()}",
        }],
    })

    settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    return "Gemini CLI: .gemini/settings.json (BeforeTool hook)"


def _install_researcher_agent(vault_root: Path, hpr_path: str) -> str | None:
    """Install the hyperresearch-fetcher subagent for Claude Code."""
    agents_dir = vault_root / ".claude" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    agent_path = agents_dir / "hyperresearch-fetcher.md"

    # Use forward slashes for bash compatibility on Windows
    hpr_posix = hpr_path.replace("\\", "/")
    content = RESEARCHER_AGENT.format(hpr_path=hpr_posix)

    # Always overwrite to keep in sync with latest version
    if agent_path.exists():
        existing = agent_path.read_text(encoding="utf-8")
        if existing == content:
            return None

    agent_path.write_text(content, encoding="utf-8")
    return "Claude Code: .claude/agents/hyperresearch-fetcher.md (haiku research agent)"


def _install_research_skill(vault_root: Path) -> str | None:
    """Install the /research skill for Claude Code."""
    import importlib.resources

    # Read the skill file from the package
    try:
        skill_content = (
            importlib.resources.files("hyperresearch.skills")
            .joinpath("research.md")
            .read_text(encoding="utf-8")
        )
    except Exception:
        # Fallback: read from source tree relative to this file
        skill_src = Path(__file__).parent.parent / "skills" / "research.md"
        if not skill_src.exists():
            return None
        skill_content = skill_src.read_text(encoding="utf-8")

    # Install to project .claude/skills/
    skill_dir = vault_root / ".claude" / "skills" / "hyperresearch"
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_path = skill_dir / "SKILL.md"

    if skill_path.exists():
        existing = skill_path.read_text(encoding="utf-8")
        if existing == skill_content:
            return None

    skill_path.write_text(skill_content, encoding="utf-8")
    return "Claude Code: .claude/skills/hyperresearch/SKILL.md (/research skill)"
