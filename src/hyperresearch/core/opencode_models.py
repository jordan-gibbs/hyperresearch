"""OpenCode model resolution for hyperresearch agent generation.

Claude Code supports convenient model aliases like ``opus`` and ``sonnet`` in
agent frontmatter. OpenCode expects concrete ``provider/model`` IDs. This module
maps hyperresearch's Claude roles onto the user's active OpenCode models while
preserving quality intent:

- ``opus`` -> strongest reasoning model available
- ``sonnet`` -> balanced, high-throughput model available
- ``haiku`` -> fast/cheap model available

If the same underlying model is available through a flat-rate provider and a
metered provider, the flat-rate provider wins.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

FLAT_RATE_PROVIDERS = {
    "opencode-go",
    "openai-codex",
    "google-antigravity",
    "copilot",
    "github-copilot",
}

CONFIG_FILENAMES = (
    "opencode.json",
    "oh-my-openagent.json",
    "oh-my-opencode.json",
    "oh-my-opencode-slim.json",
)

FALLBACK_MODELS = {
    "opus": "anthropic/claude-opus-4-1",
    "sonnet": "anthropic/claude-sonnet-4-5",
    "haiku": "anthropic/claude-haiku-4-5",
}


@dataclass(frozen=True)
class OpenCodeModelChoice:
    model: str
    variant: str | None = None
    source: str = "fallback"

    @property
    def provider(self) -> str:
        return self.model.split("/", 1)[0] if "/" in self.model else ""

    @property
    def flat_rate(self) -> bool:
        return self.provider in FLAT_RATE_PROVIDERS


def resolve_opencode_model_choices(vault_root: Path | None = None) -> dict[str, OpenCodeModelChoice]:
    """Resolve concrete OpenCode models for hyperresearch's model roles.

    The resolver reads project and user OpenCode config files, extracts every
    declared model, deduplicates equivalent provider/model pairs, then chooses
    defaults for the ``opus``, ``sonnet``, and ``haiku`` roles.
    """
    active_models = _active_models(vault_root)
    if not active_models:
        return {
            role: OpenCodeModelChoice(model=model, source="fallback")
            for role, model in FALLBACK_MODELS.items()
        }

    active_models = _dedupe_equivalent_models(active_models)
    return {
        role: _choose_for_role(role, active_models)
        for role in ("opus", "sonnet", "haiku")
    }


def _active_models(vault_root: Path | None) -> list[OpenCodeModelChoice]:
    config_files = _config_files(vault_root)
    choices: list[OpenCodeModelChoice] = []
    for path in config_files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        choices.extend(_extract_models(data, source=str(path)))
    return choices


def _config_files(vault_root: Path | None) -> list[Path]:
    files: list[Path] = []

    if vault_root is not None:
        root = vault_root.resolve()
        for name in CONFIG_FILENAMES:
            files.append(root / name)
            files.append(root / ".opencode" / name)

    env_dir = os.environ.get("HYPERRESEARCH_OPENCODE_CONFIG_DIR")
    config_root = (
        Path(env_dir).expanduser()
        if env_dir
        else Path.home() / ".config" / "opencode"
    )

    for name in CONFIG_FILENAMES:
        files.append(config_root / name)

    seen: set[Path] = set()
    existing: list[Path] = []
    for path in files:
        path = path.expanduser()
        if path in seen:
            continue
        seen.add(path)
        if path.exists():
            existing.append(path)
    return existing


def _extract_models(node: Any, source: str, inherited_variant: str | None = None) -> list[OpenCodeModelChoice]:
    choices: list[OpenCodeModelChoice] = []

    if isinstance(node, dict):
        variant = node.get("variant") if isinstance(node.get("variant"), str) else inherited_variant
        for key, value in node.items():
            if key in {"model", "small_model"} and isinstance(value, str):
                choices.append(OpenCodeModelChoice(value, variant=variant, source=source))
            else:
                choices.extend(_extract_models(value, source=source, inherited_variant=variant))
    elif isinstance(node, list):
        for item in node:
            choices.extend(_extract_models(item, source=source, inherited_variant=inherited_variant))

    return choices


def _dedupe_equivalent_models(models: list[OpenCodeModelChoice]) -> list[OpenCodeModelChoice]:
    by_key: dict[str, OpenCodeModelChoice] = {}
    for choice in models:
        key = _model_key(choice.model)
        existing = by_key.get(key)
        if existing is None or _prefer_same_model(choice, existing):
            by_key[key] = choice
    return list(by_key.values())


def _prefer_same_model(candidate: OpenCodeModelChoice, existing: OpenCodeModelChoice) -> bool:
    if candidate.flat_rate != existing.flat_rate:
        return candidate.flat_rate
    return _variant_score(candidate.variant) > _variant_score(existing.variant)


def _choose_for_role(role: str, models: list[OpenCodeModelChoice]) -> OpenCodeModelChoice:
    scored = sorted(
        models,
        key=lambda choice: (
            _role_score(role, choice),
            1 if choice.flat_rate else 0,
            _variant_score(choice.variant),
            choice.model,
        ),
        reverse=True,
    )
    best = scored[0]
    if _role_score(role, best) <= 0:
        return OpenCodeModelChoice(FALLBACK_MODELS[role], source="fallback")
    return best


def _model_key(model: str) -> str:
    if "/" in model:
        return model.split("/", 1)[1].lower()
    return model.lower()


def _role_score(role: str, choice: OpenCodeModelChoice) -> int:
    model = _model_key(choice.model)
    score = _base_role_score(role, model)
    score += _variant_score(choice.variant)
    # Prefer flat-rate only as a tie-breaker or near-tie. A weaker flat-rate
    # model should not replace a materially stronger reasoning model.
    if choice.flat_rate:
        score += 3
    return score


def _base_role_score(role: str, model: str) -> int:
    if role == "opus":
        return _score_opus(model)
    if role == "sonnet":
        return _score_sonnet(model)
    if role == "haiku":
        return _score_haiku(model)
    return 0


def _score_opus(model: str) -> int:
    patterns = [
        (r"opus", 110),
        (r"gpt-5\.5", 100),
        (r"gpt-5\.4", 92),
        (r"glm-5", 88),
        (r"kimi-k2\.6", 86),
        (r"sonnet", 84),
        (r"minimax-m2\.7", 70),
    ]
    return _pattern_score(model, patterns)


def _score_sonnet(model: str) -> int:
    patterns = [
        (r"sonnet", 110),
        (r"kimi-k2\.6", 96),
        (r"glm-5", 94),
        (r"gpt-5\.4", 92),
        (r"minimax-m2\.7", 86),
        (r"gpt-5\.5", 82),
        (r"haiku", 58),
    ]
    return _pattern_score(model, patterns)


def _score_haiku(model: str) -> int:
    patterns = [
        (r"haiku", 110),
        (r"mini", 96),
        (r"nano", 92),
        (r"highspeed", 88),
        (r"minimax-m2\.7", 84),
        (r"kimi-k2\.6", 74),
        (r"sonnet", 60),
        (r"gpt-5\.5", 45),
    ]
    return _pattern_score(model, patterns)


def _pattern_score(model: str, patterns: list[tuple[str, int]]) -> int:
    for pattern, score in patterns:
        if re.search(pattern, model):
            return score
    return 0


def _variant_score(variant: str | None) -> int:
    if variant is None:
        return 0
    return {
        "xhigh": 8,
        "high": 5,
        "medium": 2,
        "low": -1,
    }.get(variant.lower(), 0)
