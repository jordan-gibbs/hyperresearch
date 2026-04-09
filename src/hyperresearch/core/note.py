"""Note file operations — read, write, list from disk."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path

from hyperresearch.core.frontmatter import parse_frontmatter, render_note
from hyperresearch.core.patterns import CODE_BLOCK_RE, INLINE_CODE_RE, WIKI_LINK_RE
from hyperresearch.models.note import Note, NoteMeta, slugify


def read_note(file_path: Path, vault_root: Path) -> Note:
    """Read a markdown file and parse into a Note."""
    raw_bytes = file_path.read_bytes()
    content_hash = hashlib.sha256(raw_bytes).hexdigest()
    content = raw_bytes.decode("utf-8-sig")  # Handles BOM
    meta, body = parse_frontmatter(content)

    rel_path = file_path.relative_to(vault_root).as_posix()

    # Derive ID from filename if not set in frontmatter
    if not meta.id:
        meta.id = slugify(file_path.stem)

    # Extract outgoing wiki links
    cleaned = CODE_BLOCK_RE.sub("", body)
    cleaned = INLINE_CODE_RE.sub("", cleaned)
    raw_links = (m.group(1).strip().rstrip("\\") for m in WIKI_LINK_RE.finditer(cleaned))
    outgoing = list(dict.fromkeys(
        ref for ref in raw_links
        if ref and not ref.startswith(("http://", "https://", "ftp://", "mailto:"))
    ))

    # Word count (simple split)
    word_count = len(body.split())

    return Note(
        meta=meta,
        body=body,
        path=rel_path,
        content_hash=content_hash,
        word_count=word_count,
        outgoing_links=outgoing,
    )


def write_note(
    notes_dir: Path,
    title: str,
    body: str = "",
    *,
    note_id: str | None = None,
    tags: list[str] | None = None,
    status: str = "draft",
    note_type: str = "note",
    parent: str | None = None,
    source: str | None = None,
    summary: str | None = None,
    extra_frontmatter: dict | None = None,
) -> Path:
    """Create a new note file on disk. Returns the file path.

    Args:
        notes_dir: The directory to write into (e.g. vault.notes_dir).
        extra_frontmatter: Additional fields to set on NoteMeta (e.g. source_domain, fetched_at).
    """
    nid = note_id or slugify(title)
    kwargs: dict = dict(
        title=title,
        id=nid,
        tags=tags or [],
        status=status,
        type=note_type,
        parent=parent,
        source=source,
        summary=summary,
        created=datetime.now(UTC),
    )
    if extra_frontmatter:
        kwargs.update(extra_frontmatter)
    meta = NoteMeta(**kwargs)

    # Determine output path, avoid collisions
    target_dir = notes_dir
    if parent:
        target_dir = target_dir / slugify(parent)
    target_dir.mkdir(parents=True, exist_ok=True)

    file_path = target_dir / f"{nid}.md"
    counter = 2
    while file_path.exists():
        file_path = target_dir / f"{nid}-{counter}.md"
        meta.id = f"{nid}-{counter}"
        counter += 1

    content = render_note(meta, body)
    file_path.write_text(content, encoding="utf-8")
    return file_path


def strip_markdown(text: str) -> str:
    """Strip markdown formatting to plain text for FTS indexing."""
    text = CODE_BLOCK_RE.sub("", text)
    text = INLINE_CODE_RE.sub("", text)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", text)
    text = re.sub(r"_{1,3}([^_]+)_{1,3}", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", text)
    text = re.sub(r"\[\[([^\]]+)\]\]", r"\1", text)
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()
