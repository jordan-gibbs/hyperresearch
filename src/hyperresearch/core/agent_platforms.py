"""Shared agent-platform selection and installed-layout detection."""

from __future__ import annotations

from pathlib import Path

_AGENT_CHOICES: dict[str, tuple[str, ...]] = {
    "claude": ("claude",),
    "codex": ("codex",),
    "both": ("claude", "codex"),
}


def selected_agents(value: str) -> tuple[str, ...]:
    """Normalize a CLI platform selection."""
    selected = value.strip().lower()
    try:
        return _AGENT_CHOICES[selected]
    except KeyError as exc:
        raise ValueError("--agent must be claude, codex, or both") from exc


def _has_managed_entries(directory: Path, pattern: str) -> bool:
    return directory.is_dir() and any(directory.glob(pattern))


def _has_managed_doc(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        return "<!-- hyperresearch:start -->" in path.read_text(encoding="utf-8-sig")
    except OSError:
        return False


def detect_installed_agents(root: Path) -> tuple[str, ...]:
    """Detect project integrations, including global-entry/steps-only projects."""
    installed: list[str] = []
    claude_skills = root / ".claude" / "skills"
    claude_agents = root / ".claude" / "agents"
    codex_skills = root / ".agents" / "skills"
    codex_agents = root / ".codex" / "agents"

    if (
        _has_managed_doc(root / "CLAUDE.md")
        or (claude_skills / "hyperresearch").is_dir()
        or _has_managed_entries(claude_skills, "hyperresearch-*")
        or _has_managed_entries(claude_agents, "hyperresearch-*.md")
    ):
        installed.append("claude")
    if (
        _has_managed_doc(root / "AGENTS.md")
        or (codex_skills / "hyperresearch").is_dir()
        or _has_manaed_entries(codex_skills, "hyperresearch-*")
        or _has_managed_entries(codex_agents, "hyperresearch-*.toml")
    ):
        installed.append("codex")
    return tuple(installed) or ("claude",)


def resolve_agent_selection(root: Path, value: str) -> tuple[str, ...]:
    """Resolve an explicit platform selection or auto-detect installed layouts."""
    if value.strip().lower() == "auto":
        return detect_installed_agents(root)
    return selected_agents(value)


def invocation_hint(platforms: tuple[str, ...]) -> str:
    """Return the user-facing entry-skill invocation for installed platforms."""
    if platforms == ("claude",):
        return "/hyperresearch"
    if platforms == ("codex",):
        return "$hyperresearch"
    return "/hyperresearch (Claude Code) or $hyperresearch (Codex)"
