"""Core fetch logic — reusable by CLI and MCP server."""

from __future__ import annotations

import hashlib
from urllib.parse import urlparse


def fetch_and_save(
    vault,
    url: str,
    tags: list[str] | None = None,
    title: str | None = None,
    parent: str | None = None,
    provider_name: str | None = None,
    save_assets: bool = False,
    visible: bool = False,
) -> dict:
    """Fetch a URL and save as a research note. Returns result dict.

    Raises:
        ValueError: If URL is already fetched.
        RuntimeError: If fetch fails.
    """
    from hyperresearch.core.note import write_note
    from hyperresearch.core.sync import compute_sync_plan, execute_sync
    from hyperresearch.web.base import get_provider

    tags = tags or []
    conn = vault.db

    # Check if URL already fetched
    existing = conn.execute("SELECT note_id FROM sources WHERE url = ?", (url,)).fetchone()
    if existing:
        raise ValueError(f"URL already fetched as note '{existing['note_id']}'")

    # Auto-visible for sites that kill headless sessions on first contact
    if not visible and vault.config.web_profile:
        from urllib.parse import urlparse as _urlparse

        domain = _urlparse(url).netloc.lower()
        _auth_aggressive = (
            "linkedin.com", "twitter.com", "x.com", "facebook.com",
            "instagram.com", "tiktok.com",
        )
        if any(d in domain for d in _auth_aggressive):
            visible = True

    # Fetch content
    prov = get_provider(
        provider_name or vault.config.web_provider,
        profile=vault.config.web_profile,
        magic=vault.config.web_magic,
        headless=not visible,
    )

    result = prov.fetch(url)

    # Detect login redirects — abort instead of saving junk
    if result.looks_like_login_wall(url):
        raise RuntimeError(
            f"Redirected to login page ({result.title}). "
            "Your browser profile session may have expired. "
            "Run 'hyperresearch setup' and create a new login profile."
        )

    # Detect junk pages — captcha, error pages, binary garbage, empty content
    junk_reason = result.looks_like_junk()
    if junk_reason:
        raise RuntimeError(f"Skipped junk content: {junk_reason}")

    # Write note
    note_title = title or result.title or urlparse(url).path.split("/")[-1] or "Untitled"
    domain = result.domain

    extra_meta = {
        "source": url,
        "source_domain": domain,
        "fetched_at": result.fetched_at.isoformat(),
        "fetch_provider": prov.name,
    }
    if result.metadata.get("author"):
        extra_meta["author"] = result.metadata["author"]

    note_path = write_note(
        vault.notes_dir,
        title=note_title,
        body=result.content,
        tags=tags,
        status="draft",
        source=url,
        parent=parent,
        extra_frontmatter=extra_meta,
    )

    # Save raw file (PDF, etc.) if present
    raw_file_path = None
    if result.raw_bytes and result.raw_content_type:
        ext_map = {
            "application/pdf": ".pdf",
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/gif": ".gif",
            "image/webp": ".webp",
        }
        ext = ext_map.get(result.raw_content_type, "")
        if ext:
            raw_dir = vault.root / "research" / "raw"
            raw_dir.mkdir(parents=True, exist_ok=True)
            raw_filename = note_path.stem + ext
            raw_file = raw_dir / raw_filename
            raw_file.write_bytes(result.raw_bytes)
            raw_file_path = f"raw/{raw_filename}"

    # Note: tagging and summarization is the agent's job, not an automatic process.

    # Add raw_file reference to frontmatter AFTER enrich (enrich rewrites frontmatter)
    if raw_file_path:
        note_text = note_path.read_text(encoding="utf-8")
        if note_text.startswith("---") and "raw_file:" not in note_text:
            end = note_text.find("---", 3)
            if end != -1:
                note_text = (
                    note_text[:end]
                    + f"raw_file: {raw_file_path}\n"
                    + note_text[end:]
                )
                note_path.write_text(note_text, encoding="utf-8")

    # Sync
    note_id = note_path.stem
    plan = compute_sync_plan(vault)
    if plan.to_add or plan.to_update:
        execute_sync(vault, plan)

    # Record source
    content_hash = hashlib.sha256(result.content.encode("utf-8")).hexdigest()[:16]
    conn.execute(
        """INSERT INTO sources (url, note_id, domain, fetched_at, provider, content_hash)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (url, note_id, domain, result.fetched_at.isoformat(), prov.name, content_hash),
    )
    conn.commit()

    # Save assets if requested
    saved_assets: list[dict] = []
    if save_assets:
        from hyperresearch.cli.fetch import _save_assets

        assets_dir = vault.root / "research" / "assets" / note_id
        saved_assets = _save_assets(conn, result, note_id, assets_dir)

    return {
        "note_id": note_id,
        "title": note_title,
        "url": url,
        "domain": domain,
        "provider": prov.name,
        "path": str(note_path.relative_to(vault.root)),
        "word_count": len(result.content.split()),
        "assets": saved_assets,
        "raw_file": raw_file_path,
    }
