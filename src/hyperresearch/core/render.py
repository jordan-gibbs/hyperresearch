"""Prompt-template rendering — profile values into skill/agent prompts.

Skill files and agent prompt bodies are Jinja templates with NON-STANDARD
delimiters, because the prompts themselves legitimately contain `{{ ... }}`
(spawn-template placeholders like `{{paste research/query-<vault_tag>.md}}`)
and `{ ... }` (JSON examples):

    variables:  << p.source_min >>
    blocks:     <% if ... %> ... <% endif %>
    comments:   <# ... #>

Context exposed to templates:
    p          — the primary profile (default: full)
    <name>     — every available profile by name (e.g. `full`, `light`),
                 so tier tables can reference both tiers in one file.

Filters:
    dash    — join a (low, high) range with an en dash (U+2013)
    hyphen  — join a (low, high) range with a hyphen: (1, 2) -> "1-2"

Rendering is STRICT: an unknown variable raises instead of silently emitting
an empty string — a typo in a template must fail the install/tests, not ship
a prompt with a hole in it.
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, StrictUndefined

from hyperresearch.core.profiles import Profile, list_profiles, resolve_profile

EN_DASH = "–"


def _dash(value) -> str:
    low, high = value
    return f"{low}{EN_DASH}{high}"


def _hyphen(value) -> str:
    low, high = value
    return f"{low}-{high}"


def prompt_env() -> Environment:
    env = Environment(
        variable_start_string="<<",
        variable_end_string=">>",
        block_start_string="<%",
        block_end_string="%>",
        comment_start_string="<#",
        comment_end_string="#>",
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        autoescape=False,
    )
    env.filters["dash"] = _dash
    env.filters["hyphen"] = _hyphen
    return env


def build_render_context(
    config_path: Path | None = None,
    primary: str = "full",
) -> dict[str, Profile]:
    """Resolve every available profile; expose each by name plus `p` (primary)."""
    profiles = {name: resolve_profile(name, config_path) for name in list_profiles(config_path)}
    if primary not in profiles:
        # resolve_profile raises a helpful error for unknown names
        profiles[primary] = resolve_profile(primary, config_path)
    return {"p": profiles[primary], **profiles}


def render_prompt(text: str, context: dict[str, Profile]) -> str:
    """Render one prompt template with the given profile context."""
    return prompt_env().from_string(text).render(**context)


def render_header(profile_name: str, version: str) -> str:
    """Provenance comment for installed (rendered) prompt files.

    Inserted AFTER the YAML frontmatter block — a comment before the opening
    `---` would break frontmatter parsing.
    """
    return (
        f"<!-- rendered from profile \"{profile_name}\" (hyperresearch {version}) "
        "— edit the profile or the package template, not this file -->"
    )


def insert_after_frontmatter(content: str, line: str) -> str:
    """Insert `line` on its own line after the closing frontmatter delimiter.

    If the content has no leading frontmatter, prepend the line.
    """
    if content.startswith("---"):
        end = content.find("\n---", 3)
        if end != -1:
            insert_at = content.find("\n", end + 1)
            if insert_at != -1:
                return content[: insert_at + 1] + line + "\n" + content[insert_at + 1 :]
    return line + "\n" + content
