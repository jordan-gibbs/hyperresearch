"""Auto-enrichment: keyword-based tagging and first-line summary extraction."""

from __future__ import annotations

import re


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
