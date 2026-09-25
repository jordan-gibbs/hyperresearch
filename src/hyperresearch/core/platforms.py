"""Agent runtimes hyperresearch installs into — Claude Code and OpenAI Codex.

The pipeline prompts are shared; each platform differs in where its files
live and how the orchestrator loads a step or spawns a subagent:

    Claude Code  — step procedures are skills (`.claude/skills/<name>/SKILL.md`)
                   invoked with the Skill tool; subagents are markdown files in
                   `.claude/agents/` spawned with the Task tool.
    Codex        — only the entry skill is a skill (`.agents/skills/hyperresearch/`);
                   step procedures are plain files the orchestrator reads, because
                   Codex caps the skill listing and has no documented
                   skill-to-skill invocation. Subagents are TOML files in
                   `.codex/agents/`.

Templates branch on the `platform` render variable (see core/render.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

CLAUDE = "claude"
CODEX = "codex"
PLATFORMS: tuple[str, ...] = (CLAUDE, CODEX)


class PlatformError(ValueError):
    pass


def check_platform(name: str) -> str:
    """Return `name` if it is a known platform, else raise PlatformError."""
    if name not in PLATFORMS:
        raise PlatformError(f"Unknown platform '{name}'. Available: {', '.join(PLATFORMS)}")
    return name


def resolve_targets(target: str) -> list[str]:
    """`--target` value -> platforms to install: claude | codex | all."""
    if target == "all":
        return list(PLATFORMS)
    return [check_platform(target)]


@dataclass(frozen=True)
class PlatformPaths:
    """Install locations, relative to a project root (or the home dir for --global)."""

    skills_dir: PurePosixPath  # entry skill lives at <skills_dir>/hyperresearch/SKILL.md
    steps_dir: PurePosixPath  # step procedures: <steps_dir>/<name>/SKILL.md or <name>.md
    agents_dir: PurePosixPath
    agent_suffix: str
    docs_file: str
    label: str


PATHS: dict[str, PlatformPaths] = {
    CLAUDE: PlatformPaths(
        skills_dir=PurePosixPath(".claude/skills"),
        steps_dir=PurePosixPath(".claude/skills"),
        agents_dir=PurePosixPath(".claude/agents"),
        agent_suffix=".md",
        docs_file="CLAUDE.md",
        label="Claude Code",
    ),
    CODEX: PlatformPaths(
        skills_dir=PurePosixPath(".agents/skills"),
        steps_dir=PurePosixPath(".hyperresearch/codex/steps"),
        agents_dir=PurePosixPath(".codex/agents"),
        agent_suffix=".toml",
        docs_file="AGENTS.md",
        label="Codex",
    ),
}


def paths_for(platform: str) -> PlatformPaths:
    return PATHS[check_platform(platform)]
