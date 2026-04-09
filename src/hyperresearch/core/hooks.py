"""Agent hook installer — injects PreToolUse hooks for Claude Code, Codex, Cursor, Gemini CLI.

These hooks remind agents to check the research base before doing raw web searches.
"""

from __future__ import annotations

import json
from pathlib import Path

# The hook script that gets installed
HOOK_SCRIPT = """\
#!/usr/bin/env node
/**
 * hyperresearch PreToolUse hook — reminds agent to check research base first.
 * Installed by: hyperresearch install
 */
const fs = require('fs');
const path = require('path');

// Check if a .hyperresearch directory exists (vault is initialized)
function findVault() {
    let dir = process.env.CLAUDE_PROJECT_DIR || process.cwd();
    while (true) {
        if (fs.existsSync(path.join(dir, '.hyperresearch'))) return dir;
        const parent = path.dirname(dir);
        if (parent === dir) return null;
        dir = parent;
    }
}

const vault = findVault();
if (vault) {
    const msg = [
        'HYPERRESEARCH: A research knowledge base exists in this project.',
        'Before searching the web, check existing research:',
        '  hyperresearch search "<your query>" -j',
        'Save useful findings back:',
        '  hyperresearch note new "Title" --tag t --body-file /tmp/content.md --source "url" -j',
    ].join('\\n');
    process.stderr.write(msg + '\\n');
}
"""

# Cursor rule file content
CURSOR_RULE = """\
---
description: Hyperresearch research base integration
alwaysApply: true
---

# Research Base (hyperresearch)

This project has a hyperresearch research base. Before searching the web or browsing URLs:

1. **Check existing research first**: `hyperresearch search "<query>" -j`
2. **Save useful findings**: `hyperresearch note new "Title" --tag t --body-file /tmp/content.md --source "url" -j`
3. **Browse the knowledge graph**: `hyperresearch graph hubs -j` for key topics

The research base persists across sessions. Don't duplicate work — check before fetching.
"""


def install_hooks(vault_root: Path, platforms: list[str] | None = None) -> list[str]:
    """Install agent hooks for specified platforms. Returns list of actions taken."""
    if platforms is None:
        platforms = ["claude"]

    actions = []

    if "claude" in platforms or "all" in platforms:
        result = _install_claude_hook(vault_root)
        if result:
            actions.append(result)

    if "codex" in platforms or "all" in platforms:
        result = _install_codex_hook(vault_root)
        if result:
            actions.append(result)

    if "cursor" in platforms or "all" in platforms:
        result = _install_cursor_rule(vault_root)
        if result:
            actions.append(result)

    if "gemini" in platforms or "all" in platforms:
        result = _install_gemini_hook(vault_root)
        if result:
            actions.append(result)

    return actions


def _write_hook_script(vault_root: Path) -> Path:
    """Write the hook JS script to .hyperresearch/hook.js."""
    hook_dir = vault_root / ".hyperresearch"
    hook_dir.mkdir(parents=True, exist_ok=True)
    hook_path = hook_dir / "hook.js"
    hook_path.write_text(HOOK_SCRIPT, encoding="utf-8")
    return hook_path


def _install_claude_hook(vault_root: Path) -> str | None:
    """Install PreToolUse hook into .claude/settings.json."""
    hook_path = _write_hook_script(vault_root)

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


def _install_codex_hook(vault_root: Path) -> str | None:
    """Install hook into .codex/hooks.json."""
    hook_path = _write_hook_script(vault_root)

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


def _install_gemini_hook(vault_root: Path) -> str | None:
    """Install BeforeTool hook into .gemini/settings.json."""
    hook_path = _write_hook_script(vault_root)

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
