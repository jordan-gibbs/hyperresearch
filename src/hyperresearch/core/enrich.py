"""Auto-enrichment: keyword-based tagging, summary extraction, and note enrichment."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path


def auto_tag(body_plain: str, existing_tags: list[dict]) -> list[str]:
    """Suggest tags for a note based on keyword matching against existing tag vocabulary.

    Args:
        body_plain: Stripped plain text of the note body.
        existing_tags: List of {"tag": str, "count": int} from the vault.

    Returns:
        List of suggested tag strings (max 5).
    """
    if not body_plain or not existing_tags:
        return []

    body_lower = body_plain.lower()
    words = set(body_lower.split())

    scored = []
    for entry in existing_tags:
        tag = entry["tag"]
        count = entry["count"]
        # Check if tag (or hyphenated parts) appear in body
        tag_words = set(tag.replace("-", " ").split())
        matches = tag_words & words
        if matches:
            # Score: fraction of tag words found * log popularity
            import math
            frac = len(matches) / len(tag_words)
            score = frac * (1 + math.log(max(count, 1)))
            scored.append((tag, score))

    scored.sort(key=lambda x: x[1], reverse=True)
    return [tag for tag, _ in scored[:5]]


def auto_summary(body: str) -> str | None:
    """Extract a summary from the first meaningful line of the body.

    Skips headings, blank lines, and very short lines. Truncates to 120 chars.
    """
    for line in body.split("\n"):
        stripped = line.strip()
        # Skip headings, blank lines, short lines, frontmatter markers
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        if stripped.startswith("---"):
            continue
        if stripped.startswith("*Stub"):
            continue
        if len(stripped) < 25:
            continue
        # Strip markdown formatting
        clean = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", stripped)
        clean = re.sub(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", r"\1", clean)
        clean = re.sub(r"[*_`]", "", clean)
        clean = clean.strip()
        if len(clean) < 25:
            continue
        if len(clean) > 120:
            return clean[:117] + "..."
        return clean
    return None


def enrich_note_file(note_path: Path, conn: sqlite3.Connection, user_tags: list[str]) -> bool:
    """Auto-enrich a note file with tags and summary. Rewrites frontmatter in place.

    Called after write_note() but before sync. Returns True if the file was modified.
    """
    from hyperresearch.core.frontmatter import parse_frontmatter, serialize_frontmatter

    content = note_path.read_text(encoding="utf-8-sig")
    meta, body = parse_frontmatter(content)

    changed = False

    # Auto-tag: merge user tags with auto-suggested tags (cap at 8 total)
    tag_vocab = [
        {"tag": row["tag"], "count": row["c"]}
        for row in conn.execute("SELECT tag, COUNT(*) as c FROM tags GROUP BY tag ORDER BY c DESC")
    ]
    body_plain = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", body)  # strip markdown links
    body_plain = re.sub(r"[*_`#]", "", body_plain)
    suggested = auto_tag(body_plain, tag_vocab)
    merged = list(dict.fromkeys(user_tags + suggested))[:8]
    if set(merged) != set(meta.tags):
        meta.tags = merged
        changed = True

    # Auto-summary: only if not already set
    if not meta.summary:
        summary = auto_summary(body)
        if summary:
            meta.summary = summary
            changed = True

    if changed:
        note_path.write_text(serialize_frontmatter(meta) + "\n" + body, encoding="utf-8")

    return changed
