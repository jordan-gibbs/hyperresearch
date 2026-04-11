"""Fetch and websearch commands — save web content as research notes."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import typer

from hyperresearch.cli._output import console, output
from hyperresearch.models.output import error, success

app = typer.Typer()

# Max images to download per fetch
MAX_IMAGES = 5
# Skip small images (icons, logos, spacers, tracking pixels, nav elements)
MIN_IMAGE_BYTES = 50_000
# URL patterns that are almost never content images
SKIP_URL_PATTERNS = (
    "logo", "icon", "favicon", "badge", "avatar", "sprite", "banner",
    "ad-", "ads/", "advert", "tracking", "pixel", "analytics",
    "button", "arrow", "caret", "spinner", "loader",
    "gravatar.com", "googleusercontent.com/a/", "shields.io",
    "github.com/fluidicon", "platform-lookaside", "syndication",
    "facebook.com", "twitter.com/favicon", "linkedin.com/li/",
)


@app.command("fetch")
def fetch(
    url: str = typer.Argument(..., help="URL to fetch and save as a note"),
    tags: list[str] = typer.Option([], "--tag", "-t", help="Tags (repeatable)"),
    title: str | None = typer.Option(None, "--title", help="Override title"),
    parent: str | None = typer.Option(None, "--parent", "-p", help="Parent topic"),
    provider_name: str | None = typer.Option(None, "--provider", help="Web provider override"),
    save_assets: bool = typer.Option(False, "--save-assets", "-a", help="Download images and screenshot"),
    visible: bool = typer.Option(False, "--visible", "-V", help="Run browser visibly (for stubborn auth sites)"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Fetch a URL and save its content as a research note."""
    from hyperresearch.core.note import write_note
    from hyperresearch.core.sync import compute_sync_plan, execute_sync
    from hyperresearch.core.vault import Vault, VaultError
    from hyperresearch.web.base import get_provider

    try:
        vault = Vault.discover()
    except VaultError as e:
        if json_output:
            output(error(str(e), "NO_VAULT"), json_mode=True)
        else:
            console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)

    vault.auto_sync()
    conn = vault.db

    # Check if URL already fetched
    existing = conn.execute("SELECT note_id FROM sources WHERE url = ?", (url,)).fetchone()
    if existing:
        note_id = existing["note_id"]
        if json_output:
            output(
                error(f"URL already fetched as note '{note_id}'", "DUPLICATE_URL"),
                json_mode=True,
            )
        else:
            console.print(f"[yellow]Already fetched:[/] {url} → note '{note_id}'")
        raise typer.Exit(1)

    # Auto-visible for sites that kill headless sessions on first contact
    if not visible and vault.config.web_profile:
        from urllib.parse import urlparse as _urlparse

        domain = _urlparse(url).netloc.lower()
        _auth_aggressive_domains = (
            "linkedin.com", "twitter.com", "x.com", "facebook.com",
            "instagram.com", "tiktok.com",
        )
        if any(d in domain for d in _auth_aggressive_domains):
            visible = True

    # Fetch content
    prov = get_provider(
        provider_name or vault.config.web_provider,
        profile=vault.config.web_profile,
        magic=vault.config.web_magic,
        headless=not visible,
    )
    if not json_output:
        console.print(f"[dim]Fetching with {prov.name}...[/]")

    try:
        result = prov.fetch(url)
    except Exception as e:
        if json_output:
            output(error(str(e), "FETCH_ERROR"), json_mode=True)
        else:
            console.print(f"[red]Fetch failed:[/] {e}")
        raise typer.Exit(1)

    # Detect login redirects — abort instead of saving login page junk
    if result.looks_like_login_wall(url):
        msg = (
            f"Redirected to login page ({result.title}). "
            "Try --visible flag (runs browser non-headless, sites are less aggressive). "
            "If that fails, re-create your login profile with 'hyperresearch setup'."
        )
        if json_output:
            output(error(msg, "AUTH_REQUIRED"), json_mode=True)
        else:
            console.print(f"[red]Auth required:[/] {msg}")
        raise typer.Exit(1)

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

    # Auto-enrich: add suggested tags and summary before sync
    from hyperresearch.core.enrich import enrich_note_file

    enrich_note_file(note_path, conn, tags)

    # Sync first so the note exists in the notes table (needed for FK on sources/assets)
    note_id = note_path.stem
    plan = compute_sync_plan(vault)
    if plan.to_add or plan.to_update:
        execute_sync(vault, plan)

    # Record source in DB
    content_hash = hashlib.sha256(result.content.encode("utf-8")).hexdigest()[:16]
    conn.execute(
        """INSERT INTO sources (url, note_id, domain, fetched_at, provider, content_hash)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (url, note_id, domain, result.fetched_at.isoformat(), prov.name, content_hash),
    )
    conn.commit()

    # Save assets (screenshot + images) — only when requested
    saved_assets: list[dict] = []
    if save_assets:
        assets_dir = vault.root / "research" / "assets" / note_id
        saved_assets = _save_assets(conn, result, note_id, assets_dir)

    data = {
        "note_id": note_id,
        "title": note_title,
        "url": url,
        "domain": domain,
        "provider": prov.name,
        "path": str(note_path.relative_to(vault.root)),
        "word_count": len(result.content.split()),
        "assets": saved_assets,
    }

    if json_output:
        output(success(data, vault=str(vault.root)), json_mode=True)
    else:
        console.print(f"[green]Saved:[/] {note_title}")
        console.print(f"  ID: {note_id}")
        console.print(f"  Source: {url}")
        console.print(f"  Words: {data['word_count']}")
        if saved_assets:
            console.print(f"  Assets: {len(saved_assets)} saved to research/assets/{note_id}/")


def _save_assets(conn, result, note_id: str, assets_dir: Path) -> list[dict]:
    """Save screenshot and images to assets dir, record in DB. Returns list of saved asset info."""
    saved: list[dict] = []
    now = datetime.now(UTC).isoformat()

    # Save screenshot
    if result.screenshot:
        assets_dir.mkdir(parents=True, exist_ok=True)
        screenshot_path = assets_dir / "screenshot.png"
        screenshot_path.write_bytes(result.screenshot)
        conn.execute(
            """INSERT INTO assets (note_id, type, filename, alt_text, content_type, size_bytes, created_at)
               VALUES (?, 'screenshot', ?, 'Page screenshot', 'image/png', ?, ?)""",
            (note_id, str(screenshot_path), len(result.screenshot), now),
        )
        saved.append({
            "type": "screenshot",
            "path": str(screenshot_path),
            "size_bytes": len(result.screenshot),
        })

    # Download images — only content-relevant ones
    if result.media:
        # Filter out junk before sorting
        candidates = []
        for img in result.media:
            img_url = img.get("src", "")
            if not img_url or not img_url.startswith("http"):
                continue
            url_lower = img_url.lower()
            if any(skip in url_lower for skip in SKIP_URL_PATTERNS):
                continue
            # Skip SVGs (usually icons/diagrams that don't render well saved)
            if url_lower.endswith(".svg"):
                continue
            candidates.append(img)

        # Sort by score descending, take top N
        candidates.sort(key=lambda m: m.get("score", 0), reverse=True)
        for img in candidates[:MAX_IMAGES]:
            img_url = img.get("src", "")
            alt = img.get("alt", "") or ""
            asset_info = _download_image(conn, note_id, img_url, alt, assets_dir, now)
            if asset_info:
                saved.append(asset_info)

    if saved:
        conn.commit()

    return saved


def _download_image(conn, note_id: str, img_url: str, alt: str, assets_dir: Path, now: str) -> dict | None:
    """Download a single image. Returns asset info dict or None if skipped."""
    import urllib.request

    # Generate filename from URL
    parsed = urlparse(img_url)
    url_path = parsed.path.rstrip("/")
    ext = Path(url_path).suffix.lower() if url_path else ""
    if ext not in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".avif"):
        ext = ".jpg"

    # Clean filename from URL path
    raw_name = Path(url_path).stem if url_path else "image"
    clean_name = re.sub(r"[^\w\-.]", "_", raw_name)[:80]
    filename = f"{clean_name}{ext}"

    assets_dir.mkdir(parents=True, exist_ok=True)
    file_path = assets_dir / filename

    # Handle collision
    counter = 2
    while file_path.exists():
        file_path = assets_dir / f"{clean_name}-{counter}{ext}"
        counter += 1

    try:
        req = urllib.request.Request(img_url, headers={"User-Agent": "hyperresearch/0.1"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read()
            content_type = resp.headers.get("Content-Type", "")
    except Exception:
        return None

    # Skip tiny images (icons, spacers, tracking pixels)
    if len(data) < MIN_IMAGE_BYTES:
        return None

    file_path.write_bytes(data)

    conn.execute(
        """INSERT INTO assets (note_id, type, filename, url, alt_text, content_type, size_bytes, created_at)
           VALUES (?, 'image', ?, ?, ?, ?, ?, ?)""",
        (note_id, str(file_path), img_url, alt, content_type, len(data), now),
    )

    return {
        "type": "image",
        "path": str(file_path),
        "url": img_url,
        "alt": alt,
        "size_bytes": len(data),
    }
