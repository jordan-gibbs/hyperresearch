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
    meta._extra = {k: v for k, v in data.items() if k not in NoteMeta.model_fields}
    meta._key_order = list(data)
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
    if meta._extra:
        data = _restore_extra_keys(data, meta._extra, meta._key_order)

    yaml_str = yaml.dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True)
    return f"---\n{yaml_str}---\n"


def _restore_extra_keys(data: dict, extra: dict, key_order: list) -> dict:
    """Merge the keys NoteMeta does not model back into the dumped fields.

    Each one goes right after the key it followed in the file (or first, if
    nothing it followed is still written). The modeled keys keep the order
    they have always been written in, so a note without extra keys
    serializes exactly as before.
    """
    keys = list(data)
    for key in extra:
        before = [k for k in key_order[: key_order.index(key)] if k in keys]
        keys.insert(keys.index(before[-1]) + 1 if before else 0, key)
    # Raw YAML values, not a JSON dump: a date stays a date on the next read.
    return {k: data[k] if k in data else extra[k] for k in keys}


def render_note(meta: NoteMeta, body: str) -> str:
    """Render a full markdown note with frontmatter + body."""
    return serialize_frontmatter(meta) + "\n" + body
