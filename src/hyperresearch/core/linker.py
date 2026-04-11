"""Auto-linker: discover and insert wiki-links between related notes."""

from __future__ import annotations

import re
from pathlib import Path

# Minimum title length to consider for auto-linking (avoids false positives on short generic titles)
MIN_TITLE_LEN = 15


def auto_link(vault, note_ids: list[str] | None = None) -> dict:
    """Scan notes for mentions of other notes' titles and add wiki-links.

    Args:
        vault: The Vault instance.
        note_ids: If given, only process these notes. Otherwise process all.

    Returns:
        Dict mapping note_id -> list of note_ids that were linked to.
    """
    conn = vault.db

    # Build reference vocabulary: {lowercase_title: note_id, lowercase_alias: note_id}
    ref_vocab: dict[str, str] = {}
    for row in conn.execute("SELECT id, title FROM notes WHERE type != 'index'"):
        title = row["title"]
        nid = row["id"]
        if len(title) >= MIN_TITLE_LEN:
            ref_vocab[title.lower()] = nid
        # Always include note IDs as matchable references
        ref_vocab[nid.lower()] = nid

    for row in conn.execute("SELECT note_id, alias FROM aliases"):
        alias = row["alias"]
        if len(alias) >= MIN_TITLE_LEN:
            ref_vocab[alias.lower()] = row["note_id"]

    if not ref_vocab:
        return {}

    # Determine which notes to process
    if note_ids:
        placeholders = ",".join("?" for _ in note_ids)
        rows = conn.execute(
            f"SELECT id, path FROM notes WHERE id IN ({placeholders})", note_ids
        ).fetchall()
    else:
        rows = conn.execute("SELECT id, path FROM notes WHERE type != 'index'").fetchall()

    # Process each note
    report: dict[str, list[str]] = {}
    for row in rows:
        nid = row["id"]
        note_path = vault.root / row["path"]
        if not note_path.exists():
            continue

        linked = _link_note(note_path, nid, ref_vocab)
        if linked:
            report[nid] = linked

    return report


def _link_note(note_path: Path, note_id: str, ref_vocab: dict[str, str]) -> list[str]:
    """Scan a single note for mentions of other notes and append a Related section.

    Returns list of note IDs that were linked.
    """
    content = note_path.read_text(encoding="utf-8-sig")

    # Split frontmatter and body
    parts = content.split("---", 2)
    body = parts[2] if len(parts) >= 3 else content

    body_lower = body.lower()

    # Find existing wiki-links so we don't duplicate
    existing_links = set(re.findall(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", body))

    # Find mentions of other notes' titles in the body
    found_links: list[str] = []
    for ref_text, ref_id in ref_vocab.items():
        # Skip self-references
        if ref_id == note_id:
            continue
        # Skip if already linked
        if ref_id in existing_links:
            continue
        # Check for whole-word match (not inside code blocks or existing links)
        # Use word boundary matching
        pattern = r"(?<!\[\[)\b" + re.escape(ref_text) + r"\b"
        if re.search(pattern, body_lower):
            # Verify it's not inside a code block
            match = re.search(pattern, body_lower)
            if match and not _in_code_block(body, match.start()):
                found_links.append(ref_id)

    if not found_links:
        return []

    # Deduplicate (multiple refs can point to same note)
    found_links = list(dict.fromkeys(found_links))

    # Append Related section if we found new links
    related_lines = "\n".join(f"- [[{nid}]]" for nid in found_links)
    related_section = f"\n\n## Related\n\n{related_lines}\n"

    # Check if there's already a ## Related section
    if re.search(r"^## Related\s*$", body, re.MULTILINE):
        # Append to existing Related section
        body_with_links = re.sub(
            r"(^## Related\s*\n)",
            rf"\1{related_lines}\n",
            body,
            count=1,
            flags=re.MULTILINE,
        )
    else:
        body_with_links = body.rstrip() + related_section

    # Reconstruct the file
    if len(parts) >= 3:
        new_content = parts[0] + "---" + parts[1] + "---" + body_with_links
    else:
        new_content = body_with_links

    note_path.write_text(new_content, encoding="utf-8")
    return found_links


def _in_code_block(text: str, pos: int) -> bool:
    """Check if a position in text is inside a fenced code block."""
    # Count ``` before this position
    fences_before = text[:pos].count("```")
    # Odd number means we're inside a code block
    return fences_before % 2 == 1
