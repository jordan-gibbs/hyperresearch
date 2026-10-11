"""YAML frontmatter parsing and serialization."""

from __future__ import annotations

import re
from pathlib import Path

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


# Every note write_note() produces opens with a YAML header, and sync treats a
# .md without one as agent scratch that stays out of the index (#25). The one
# designed exception is the pipeline's deliverable,
# research/notes/final_report_<vault_tag>.md: steps 10, 11 and 15 forbid a
# header on it and the polish step strips any that leaks in. It is still
# indexed (core/note.py derives its metadata from the file), so every command
# that selects notes can reach it, and none of them may write a header into
# it: every writer that round-trips parse -> mutate -> serialize -> write goes
# through write_frontmatter(), which refuses that one file.
_FRONTMATTER_PROBE = re.compile(rb"^---[ \t]*\r?\n")
# The bare final_report.md is deliberately NOT matched: older fixtures use that
# name for header-less scratch files.
_FINAL_REPORT_FILE_RE = re.compile(r"^final_report_.+\.md$")


def has_frontmatter(path: Path) -> bool:
    """Cheap content probe: true iff the file opens with a YAML frontmatter
    delimiter (matching FRONTMATTER_RE, with an optional UTF-8 BOM)."""
    try:
        with path.open("rb") as f:
            head = f.read(16)
    except OSError:
        return False
    if head.startswith(b"\xef\xbb\xbf"):
        head = head[3:]
    return _FRONTMATTER_PROBE.match(head) is not None


def is_final_report_path(path: Path) -> bool:
    """True for notes/final_report_<vault_tag>.md, the pipeline's deliverable.

    Only the name and the parent directory's name are tested. Sync and
    `note mv` also require the parent to be the vault's own notes
    directory, so a copy under another directory named `notes` is not
    indexed.
    """
    return path.parent.name == "notes" and _FINAL_REPORT_FILE_RE.match(path.name) is not None


def is_frontmatterless_report(path: Path) -> bool:
    """A final report with no YAML header: indexed from derived metadata, never rewritten."""
    return is_final_report_path(path) and not has_frontmatter(path)


class FrontmatterWriteRefusedError(ValueError):
    """Raised instead of writing a YAML header into a header-less final report."""

    def __init__(self, path: Path, vault_root: Path | None = None) -> None:
        self.path = path
        try:
            shown = path.relative_to(vault_root).as_posix() if vault_root else str(path)
        except ValueError:  # not under vault_root: show it as given
            shown = str(path)
        super().__init__(
            f"{shown} is a final report without YAML frontmatter; writing a header "
            "into it would put scaffold text into the deliverable. Its metadata is "
            "derived from the file at sync time; edit the report body directly instead."
        )


def write_frontmatter(
    path: Path, meta: NoteMeta, body: str, vault_root: Path | None = None
) -> None:
    """Write a note back as frontmatter + body, the counterpart of parse_frontmatter().

    Every round-trip writer uses this instead of serializing inline, so the
    header-less final report is refused in one place. `vault_root` only
    shortens the path in the error message.
    """
    if is_frontmatterless_report(path):
        raise FrontmatterWriteRefusedError(path, vault_root)
    path.write_text(render_note(meta, body), encoding="utf-8")
