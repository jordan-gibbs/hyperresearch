"""YAML frontmatter parsing and serialization."""

from __future__ import annotations

import re

import yaml

from hyperresearch.models.note import NoteMeta

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


def parse_frontmatter(content: str) -> tuple[NoteMeta, str]:
    """Parse YAML frontmatter from markdown content.

    Returns (metadata, body) where body is the content after frontmatter.
    """
    match = FRONTMATTER_RE.match(content)
    if not match:
        return NoteMeta(title="Untitled"), content

    yaml_str = match.group(1)
    body = content[match.end():]

    data = yaml.safe_load(yaml_str) or {}
    if not isinstance(data, dict):
        return NoteMeta(title="Untitled"), content

    # Handle missing title gracefully
    if "title" not in data:
        data["title"] = "Untitled"

    meta = NoteMeta.model_validate(data)
    return meta, body


def serialize_frontmatter(meta: NoteMeta) -> str:
    """Serialize NoteMeta to YAML frontmatter string."""
    data = meta.model_dump(mode="json", exclude_none=True, exclude_defaults=False)
    # Remove empty lists
    for key in ("tags", "aliases"):
        if key in data and not data[key]:
            del data[key]
    # Remove empty id
    if "id" in data and not data["id"]:
        del data["id"]

    yaml_str = yaml.dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True)
    return f"---\n{yaml_str}---\n"


def render_note(meta: NoteMeta, body: str) -> str:
    """Render a full markdown note with frontmatter + body."""
    return serialize_frontmatter(meta) + "\n" + body
