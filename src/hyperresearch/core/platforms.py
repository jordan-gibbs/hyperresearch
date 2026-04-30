"""Supported agent-harness platform selection."""

from __future__ import annotations

from collections.abc import Iterable

SUPPORTED_PLATFORMS = frozenset({"claude", "opencode"})
PLATFORM_ALIASES = {
    "claude-code": "claude",
    "claude_code": "claude",
    "claudecode": "claude",
    "cc": "claude",
    "open-code": "opencode",
    "open_code": "opencode",
    "oc": "opencode",
}


def normalize_platforms(platforms: str | Iterable[str] | None = None) -> set[str]:
    """Normalize a platform selector into ``{"claude", "opencode"}`` subset.

    Accepts ``both``/``all`` or comma-separated strings for CLI ergonomics.
    """
    if platforms is None:
        return set(SUPPORTED_PLATFORMS)

    if isinstance(platforms, str):
        raw_items = [part.strip() for part in platforms.split(",")]
    else:
        raw_items = []
        for item in platforms:
            raw_items.extend(part.strip() for part in item.split(","))

    selected: set[str] = set()
    for item in raw_items:
        if not item:
            continue
        normalized = item.lower()
        if normalized in {"both", "all"}:
            selected.update(SUPPORTED_PLATFORMS)
            continue
        normalized = PLATFORM_ALIASES.get(normalized, normalized)
        if normalized not in SUPPORTED_PLATFORMS:
            valid = ", ".join(sorted(SUPPORTED_PLATFORMS | {"both"}))
            raise ValueError(f"Unknown platform '{item}'. Valid values: {valid}")
        selected.add(normalized)

    if not selected:
        raise ValueError("At least one platform must be selected: claude, opencode, or both")
    return selected
