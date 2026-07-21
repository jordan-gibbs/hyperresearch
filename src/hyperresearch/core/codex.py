"""Codex installer for hyperresearch skills, custom agents, and AGENTS.md."""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from datetime import date
from pathlib import Path

import yaml

HYPERRESEARCH_SECTION_MARKER = "<!-- hyperresearch:start -->"
HYPERRESEARCH_SECTION_END = "<!-- hyperresearch:end -->"

CODEX_COMPATIBILITY_NOTE = """\
### Codex compatibility note

Claude Code tool allowlists do not map directly to Codex custom-agent TOML.
Hyperresearch therefore converts those restrictions into binding developer
instructions. Keep the same narrow role boundaries and do not broaden a
patch-only role into full-file regeneration.
"""

_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("hyperresearch install --steps-only .", "hyperresearch install --agent codex --steps-only ."),
    ("hyperresearch init . --json", "hyperresearch init . --agent codex --json"),
    (".claude/skills/", ".agents/skills/"),
    (".claude/agents/", ".codex/agents/"),
    ("Claude Code's `Skill` tool", "Codex's explicit `$skill-name` invocation"),
    ("Claude Code’s `Skill` tool", "Codex's explicit `$skill-name` invocation"),
    ("via the `Skill` tool", "by explicitly invoking the named Codex skill"),
    ("the `Skill` tool", "an explicit `$skill-name` invocation"),
    ("Skill tool", "explicit `$skill-name` invocation"),
    ("the Task tool", "the `spawn_agent` tool"),
    ("Task tool", "`spawn_agent` tool"),
    ("Task calls", "`spawn_agent` calls"),
    ("Task call", "`spawn_agent` call"),
    ("CLAUDE.md", "AGENTS.md"),
    ("Claude-in-Chrome", "a compatible browser MCP"),
    ("TodoWrite", "update_plan"),
    ("WebFetch", "raw page fetching"),
    ("Bash heredocs", "shell heredocs"),
    ("[Read, Write]", "read and file-writing only"),
    ("Read+Write", "read + file-writing"),
    ("`Bash`", "`shell`"),
    ("`Edit`", "`apply_patch`"),
    ("`Write`", "file-writing tools"),
    ("`Read`", "file-reading tools"),
    ("Write tool", "file-writing tools"),
    ("Read tool", "file-reading tools"),
    ("Edit tool", "`apply_patch`"),
    ("Edit call", "`apply_patch` edit"),
    ("[Read, Edit]", "read and targeted-edit only"),
    ("Read+Edit", "read + targeted-edit"),
    ("tool-locked", "instruction-locked"),
    ("Claude Code allowlist", "Codex agent instructions"),
    ("physically cannot Write", "must not write a replacement file"),
    ("physically cannot", "must not"),
    ("Claude Code", "Codex"),
)


def adapt_for_codex(content: str) -> str:
    """Translate Claude-specific paths and orchestration terms for Codex."""
    adapted = content
    for old, new in _REPLACEMENTS:
        adapted = adapted.replace(old, new)

    adapted = re.sub(
        r'Skill\(skill:\s*["\']([^"\']+)["\']\)',
        lambda match: f"${match.group(1)}",
        adapted,
    )

    # Rewrite only slash-command tokens, never path segments such as
    # .agents/skills/hyperresearch.
    adapted = re.sub(
        r"(?<![A-Za-z0-9_.-])/hyperresearch\b",
        "$hyperresearch",
        adapted,
    )

    adapted = adapted.replace(
        "In non-interactive (`-p`) mode, a text-only response (no tool call) "
        "triggers `end_turn` — the process exits and the pipeline dies.",
        "While subagents are running, keep the orchestration turn active until "
        "all delegated work returns.",
    )
    adapted = adapted.replace(
        "Every response while subagent tasks are in flight MUST include a tool call.",
        "While subagent tasks are in flight, continue using orchestration tools "
        "until every delegated task returns.",
    )
    return adapted


def _parse_frontmatter(markdown: str) -> tuple[dict[str, str], str]:
    normalized = markdown.lstrip("\ufeff")
    if not normalized.startswith("---\n"):
        raise ValueError("Claude agent markdown must start with YAML frontmatter")

    try:
        raw_frontmatter, body = normalized[4:].split("\n---\n", 1)
    except ValueError as exc:
        raise ValueError("Claude agent markdown has no closing frontmatter delimiter") from exc

    loaded = yaml.safe_load(raw_frontmatter)
    if not isinstance(loaded, dict):
        raise ValueError("Claude agent frontmatter must be a mapping")
    fields = {str(key): str(value) for key, value in loaded.items() if value is not None}
    return fields, body.lstrip("\n")


def _adapt_browser_fetcher(instructions: str) -> str:
    """Replace Claude-in-Chrome setup details with MCP-agnostic Codex guidance."""
    setup = """## Setup (once per session)

Use the available browser MCP tools that provide tab context, new-tab creation,
navigation, page-text extraction, find, screenshots, and computer interaction.
Tool names vary by MCP server, so resolve them from the active tool list instead
of assuming a specific provider prefix. Always open a new tab for this work and
never reuse the user's existing tabs. If a compatible browser MCP is unavailable
or repeatedly errors, return the current item to the human escalation queue and
report the limitation.

"""
    return re.sub(
        r"## Setup \(once per session\).*?(?=## The drain loop)",
        setup,
        instructions,
        flags=re.DOTALL,
    )


def claude_agent_to_toml(markdown: str, *, filename: str | None = None) -> str:
    """Convert a rendered Claude agent markdown file into Codex custom-agent TOML."""
    fields, body = _parse_frontmatter(markdown)
    name = fields.get("name", "").strip()
    description = fields.get("description", "").strip()
    if not name:
        raise ValueError("Claude agent frontmatter must define a non-empty name")
    if not description:
        raise ValueError(f"Claude agent {name!r} must define a non-empty description")

    instructions = adapt_for_codex(body).strip()
    if filename == "hyperresearch-browser-fetcher.md":
        instructions = _adapt_browser_fetcher(instructions)

    # Omit model/sandbox settings so the agent inherits the active Codex session.
    return (
        f"name = {json.dumps(name, ensure_ascii=False)}\n"
        f"description = {json.dumps(description, ensure_ascii=False)}\n"
        f"developer_instructions = {json.dumps(instructions, ensure_ascii=False)}\n"
    )


def _write_if_changed(path: Path, content: str) -> bool:
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def _install_from_staging(
    staging_root: Path,
    target_root: Path,
    *,
    include_entry: bool,
    include_steps: bool,
    include_agents: bool,
) -> list[str]:
    """Install Codex files from an already-rendered Claude staging tree."""
    actions: list[str] = []
    source_skills = staging_root / ".claude" / "skills"
    target_skills = target_root / ".agents" / "skills"

    expected_skills: set[str] = set()
    if source_skills.is_dir() and (include_entry or include_steps):
        for source_dir in sorted(source_skils.iterdir()):
            if not source_dir.is_dir():
                continue
            is_entry = source_dir.name == "hyperresearch"
            is_step = source_dir.name.startswith("hyperresearch-")
            if not ((include_entry and is_entry) or (include_steps and is_step)):
                continue
            source_file = source_dir / "SKILL.md"
            if not source_file.exists():
                continue
            expected_skills.add(source_dir.name)
            destination = target_skills / source_dir.name / "SKILL.md"
            content = adapt_for_codex(source_file.read_text(encoding="utf-8"))
            if _write_if_changed(destination, content):
                actions.append(f"Codex: .agents/skills/{source_dir.name}/SKILL.md")

    if target_skills.is_dir() and include_steps:
        for child in sorted(target_skills.iterdir()):
            if not child.is_dir() or not child.name.startswith("hyperresearch-"):
                continue
            if child.name in expected_skills:
                continue
            shutil.rmtree(child)
            actions.append(f"Codex: pruned stale skill {child.name}")

    if include_agents:
        source_agents = staging_root / ".claude" / "agents"
        target_agents = target_root / ".codex" / "agents"
        expected_agents: set[str] = set()
        if source_agents.is_dir():
            for source_file in sorted(source_agents.glob("hyperresearch-*.md")):
                destination_name = f"{source_file.stem}.toml"
                expected_agents.add(destination_name)
                destination = target_agents / destination_name
                content = claude_agent_to_toml(
                    source_file.read_text(encoding="utf-8"), filename=source_file.name
                )
                if _write_if_changed(destination, content):
                    actions.append(f"Codex: .codex/agents/{destination_name}")

        if target_agents.is_dir():
            for child in sorted(target_agents.glob("hyperresearch-*.toml")):
                if child.name in expected_agents:
                    continue
                child.unlink()
                actions.append(f"Codex: pruned stale agent {child.name}")

    return actions


def inject_codex_docs(vault_root: Path, hpr_path: str | None = None) -> list[str]:
    """Create or update the managed hyperresearch section in AGENTS.md."""
    if hpr_path is None:
        from hyperresearch.core.agent_docs import _resolve_executable

        hpr_path = _resolve_executable()
    from hyperresearch.core.agent_docs import HYPERRESEARCH_BLURB

    hpr_path = hpr_path.replace("\\", "/")
    canonical = HYPERRESEARCH_BLURB.format(
        marker=HYPERRESEARCH_SECTION_MARKER,
        end_marker=HYPERRESEARCH_SECTION_END,
        hpr=hpr_path,
        today=date.today().isoformat(),
    )
    blurb = adapt_for_codex(canonical).strip()
    blurb = blurb.replace(
        HYPERRESEARCH_SECTION_END,
        CODEX_COMPATIBILITY_NOTE.strip() + "\n" + HYPERRESEARCH_SECTION_END,
    )

    path = vault_root / "AGENTS.md"
    if path.exists():
        existing = path.read_text(encoding="utf-8-sig")
        if HYPERRESEARCH_SECTION_MARKER in existing:
            pattern = re.compile(
                re.escape(HYPERRESEARCH_SECTION_MARKER)
                + r".*?"

                + re.escape(HYPERRESEARCH_SECTION_END),
                re.DOTALL,
            )
            updated = pattern.sub(lambda _: blurb, existing)
            if updated == existing:
                return []
            path.write_text(updated, encoding="utf-8")
            return ["AGENTS.md (updated)"]

        separator = "\n\n" if not existing.endswith("\n") else "\n"
        path.write_text(existing + separator + blurb + "\n", encoding="utf-8")
        return ["AGENTS.md (appended)"]

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# AGENTS\n\n" + blurb + "\n", encoding="utf-8")
    return ["AGENTS.md (created)"]


def install_codex(
    target_root: Path,
    *,
    hpr_path: str = "hyperresearch",
    profile: str = "full",
    global_install: bool = False,
    steps_only: bool = False,
) -> list[str]:
    """Render existing Claude assets, then install Codex-native equivalents."""
    if global_install and steps_only:
        raise ValueError("global_install and steps_only cannot both be true")

    from hyperresearch.core.hooks import (
        _install_hyperresearch_step_skills,
        _set_render_state,
        install_global_hooks,
        install_hooks,
    )

    with tempfile.TemporaryDirectory(prefix="hyperresearch-codex-") as temp_dir:
        staging = Path(temp_dir)
        target_config = target_root / ".hyperresearch" / "config.toml"
        if target_config.exists() and not global_install:
            staging_config = staging / ".hyperresearch" / "config.toml"
            staging_config.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target_config, staging_config)

        if steps_only:
            config_path = target_root / ".hyperresearch" / "config.toml"
            _set_render_state(profile, config_path if config_path.exists() else None)
            _install_hyperresearch_step_skills(staging)
        elif global_install:
            install_global_hooks(staging, hpr_path=hpr_path, profile=profile)
        else:
            install_hooks(staging, hpr_path=hpr_path, profile=profile)

        return _install_from_staging(
            staging,
            target_root,
            include_entry=not steps_only,
            include_steps=not global_install,
            include_agents=not steps_only,
        )
