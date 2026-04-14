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


def _append_suggested_by_to_existing(
    vault_root: Path,
    note_id: str,
    suggested_by: list[str],
    reason: str | None,
) -> int:
    """Append `*Suggested by [[src]] — reason*` breadcrumb lines to an existing note.

    Idempotent: if a breadcrumb for a given source id already exists anywhere
    in the body, it is not re-added. Returns the number of new breadcrumbs
    actually added.
    """
    # Find the note file — scan research/notes/ for `<note-id>.md` or walk subdirs
    from hyperresearch.core.frontmatter import parse_frontmatter, serialize_frontmatter

    note_path = None
    for candidate in vault_root.rglob(f"{note_id}.md"):
        # Require it to be under a notes directory so we don't match index files
        if "notes" in candidate.parts:
            note_path = candidate
            break
    if note_path is None:
        return 0

    text = note_path.read_text(encoding="utf-8-sig")
    meta, body = parse_frontmatter(text)

    reason_suffix = f" — {reason}" if reason else ""
    added = 0
    new_lines = []
    for src_id in suggested_by:
        src_clean = src_id.strip()
        if not src_clean:
            continue
        # Skip if a breadcrumb for this source id already exists in the body
        existing_marker = f"[[{src_clean}]]"
        if existing_marker in body:
            continue
        new_lines.append(f"*Suggested by [[{src_clean}]]{reason_suffix}*")
        added += 1

    if added == 0:
        return 0

    # Prepend the new breadcrumb lines to the body
    breadcrumb_block = "\n".join(new_lines) + "\n\n"
    new_body = breadcrumb_block + body
    new_text = serialize_frontmatter(meta) + "\n" + new_body
    note_path.write_text(new_text, encoding="utf-8")
    return added


def _detect_tier(url: str, content_type: str) -> str:
    """Guess the epistemic tier from URL + content_type. Returns a Tier value.

    This is a coarse first pass. The curation-time agent is expected to refine
    (e.g. a medium.com post could be practitioner if it's by a named engineer,
    or commentary if it's a generic explainer — only reading can tell).

    Defaults prioritize reducing the agent's curation load: URLs with strong
    signal get a non-unknown default so the agent only needs to verify, not
    classify from scratch.
    """
    domain = urlparse(url).netloc.lower()

    # Ground truth: official primary sources — filings, specs, policy text, datasets
    if domain.endswith(".gov") or ".gov." in domain or domain.endswith(".gov.uk") or domain.endswith(".europa.eu"):
        return "ground_truth"
    if content_type == "policy":
        return "ground_truth"
    if content_type == "dataset":
        return "ground_truth"
    if content_type == "docs":
        # Official documentation IS the ground truth for a product/standard
        return "ground_truth"
    if content_type == "code":
        # Source code, README, and repo metadata are ground truth for a tool
        return "ground_truth"

    # Institutional: peer-reviewed scholarship, canonical reference works
    if content_type == "paper":
        # Default to institutional; agent may upgrade to ground_truth if the
        # paper reports original data or downgrade to commentary for derivatives
        return "institutional"
    if "wikipedia.org" in domain or "britannica.com" in domain:
        return "institutional"

    # Practitioner: forums, community threads, hands-on content
    if content_type == "forum":
        return "practitioner"
    if content_type == "review":
        return "practitioner"

    # Commentary: news articles, op-eds, blog posts without known authority
    if content_type == "article":
        return "commentary"
    if content_type == "blog":
        return "commentary"
    if content_type == "transcript":
        # Could be institutional (conference keynote) or commentary (podcast)
        # — agent must decide. Start at commentary; promote during curation.
        return "commentary"

    return "unknown"


def _detect_content_type(url: str, raw_content_type: str | None = None) -> str:
    """Guess the artifact kind from URL + MIME. Returns a ContentType value or 'unknown'.

    This is a coarse first pass. The creation-time agent is expected to refine
    during curation if the URL/MIME heuristic is wrong (e.g. a medium.com URL
    could be blog OR article).
    """
    if raw_content_type and "pdf" in raw_content_type.lower():
        return "paper"
    domain = urlparse(url).netloc.lower()
    path = urlparse(url).path.lower()

    # Papers: arxiv, doi, direct PDFs, openreview, ssrn, biorxiv, pubmed
    if any(d in domain for d in ("arxiv.org", "doi.org", "openreview.net", "ssrn.com", "biorxiv.org", "medrxiv.org", "pubmed.ncbi.nlm.nih.gov", "ncbi.nlm.nih.gov/pmc", "semanticscholar.org", "openalex.org")):
        return "paper"
    if path.endswith(".pdf"):
        return "paper"

    # Code: github, gitlab, bitbucket, pypi
    if any(d in domain for d in ("github.com", "gitlab.com", "bitbucket.org", "pypi.org", "crates.io", "npmjs.com")):
        return "code"

    # Dataset portals that happen to live on .gov domains must win first
    if domain in ("data.gov", "data.gov.uk") or (domain.startswith("data.") and (domain.endswith(".gov") or domain.endswith(".gov.uk") or domain.endswith(".europa.eu"))):
        return "dataset"

    # Policy: gov domains, EU, regulator sites
    if domain.endswith(".gov") or ".gov." in domain or domain.endswith(".gov.uk") or domain.endswith(".europa.eu") or "regulations.gov" in domain:
        return "policy"

    # Docs: common documentation platforms, docs.* subdomains, /docs paths
    if any(d in domain for d in ("readthedocs.io", "readthedocs.org", "docs.rs", "developer.mozilla.org")):
        return "docs"
    if domain.startswith("docs.") or domain.startswith("documentation.") or ".readthedocs." in domain:
        return "docs"
    if "/docs/" in path or path.endswith("/docs") or "/documentation/" in path or "/api/reference" in path or "/reference/" in path:
        return "docs"

    # Forum / community
    if any(d in domain for d in ("reddit.com", "news.ycombinator.com", "stackoverflow.com", "stackexchange.com", "lobste.rs", "lemmy.", "discourse.")):
        return "forum"

    # Blog platforms
    if any(d in domain for d in ("medium.com", "substack.com", "dev.to", "hashnode.com", "hashnode.dev", "blogspot.com", "wordpress.com", "ghost.io")):
        return "blog"

    # Transcripts / video
    if any(d in domain for d in ("youtube.com", "youtu.be", "vimeo.com")):
        return "transcript"

    # Reference articles
    if "wikipedia.org" in domain or "wikimedia.org" in domain or "britannica.com" in domain:
        return "article"

    # Datasets
    if any(d in domain for d in ("kaggle.com", "data.gov", "data.world", "zenodo.org", "figshare.com")):
        return "dataset"

    # News / magazine default
    if any(d in domain for d in ("nytimes.com", "wsj.com", "ft.com", "bloomberg.com", "reuters.com", "bbc.com", "theatlantic.com", "newyorker.com", "economist.com")):
        return "article"

    return "unknown"


@app.command("fetch")
def fetch(
    url: str = typer.Argument(..., help="URL to fetch and save as a note"),
    tags: list[str] = typer.Option([], "--tag", "-t", help="Tags (repeatable)"),
    title: str | None = typer.Option(None, "--title", help="Override title"),
    parent: str | None = typer.Option(None, "--parent", "-p", help="Parent topic"),
    provider_name: str | None = typer.Option(None, "--provider", help="Web provider override"),
    save_assets: bool = typer.Option(False, "--save-assets", "-a", help="Download images and screenshot"),
    visible: bool = typer.Option(False, "--visible", "-V", help="Run browser visibly (for stubborn auth sites)"),
    suggested_by: list[str] = typer.Option(
        [],
        "--suggested-by",
        help="Source note ID(s) that suggested this URL. Prepends a 'Suggested by [[note-id]]' breadcrumb to the new note's body, which the link extractor picks up as a wiki-link so the fetched note appears in the source's backlinks. Repeat for multiple sources.",
    ),
    suggested_by_reason: str | None = typer.Option(
        None,
        "--suggested-by-reason",
        help="One-line justification for why the suggesting source named this URL. Appears next to the [[source-id]] breadcrumb.",
    ),
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
        # Graceful duplicate handling for the guided reading loop:
        # if the caller passed --suggested-by, append the breadcrumb to the
        # existing note instead of erroring out. This lets the main agent
        # build up provenance on already-fetched URLs without needing to
        # check for dupes first.
        if suggested_by:
            added = _append_suggested_by_to_existing(
                vault.root, note_id, suggested_by, suggested_by_reason
            )
            # Re-sync so the new wiki-link gets picked up by the link extractor
            plan = compute_sync_plan(vault)
            if plan.to_update:
                execute_sync(vault, plan)

            data = {
                "note_id": note_id,
                "url": url,
                "duplicate": True,
                "backlinks_added": added,
                "message": (
                    f"URL already fetched; added {added} backlink(s) to existing note"
                    if added
                    else "URL already fetched; breadcrumb(s) already present"
                ),
            }
            if json_output:
                output(success(data, vault=str(vault.root)), json_mode=True)
            else:
                console.print(f"[yellow]Already fetched:[/] {url} → note '{note_id}'")
                console.print(f"  added {added} backlink(s) to existing note")
            return

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

    # Detect junk pages — captcha, error pages, binary garbage, empty content
    junk_reason = result.looks_like_junk()
    if junk_reason:
        msg = f"Skipped junk content from {url}: {junk_reason}"
        if json_output:
            output(error(msg, "JUNK_CONTENT"), json_mode=True)
        else:
            console.print(f"[yellow]Skipped:[/] {msg}")
        raise typer.Exit(1)

    # Write note
    note_title = title or result.title or urlparse(url).path.split("/")[-1] or "Untitled"
    domain = result.domain

    detected_content_type = _detect_content_type(url, result.raw_content_type)
    detected_tier = _detect_tier(url, detected_content_type)
    extra_meta = {
        "source": url,
        "source_domain": domain,
        "fetched_at": result.fetched_at.isoformat(),
        "fetch_provider": prov.name,
    }
    if result.metadata.get("author"):
        extra_meta["author"] = result.metadata["author"]

    # Build body with backlink breadcrumb if this fetch was suggested by another note.
    # Prepending `*Suggested by [[source-id]] — reason*` lines creates wiki-links the
    # normal link extractor will pick up, so the new note automatically appears in
    # graph backlinks of its suggester(s). Zero schema change needed.
    body_content = result.content
    if suggested_by:
        breadcrumb_lines = []
        reason_suffix = f" — {suggested_by_reason}" if suggested_by_reason else ""
        for src_id in suggested_by:
            src_id_clean = src_id.strip()
            if not src_id_clean:
                continue
            breadcrumb_lines.append(f"*Suggested by [[{src_id_clean}]]{reason_suffix}*")
        if breadcrumb_lines:
            breadcrumb = "\n".join(breadcrumb_lines) + "\n\n"
            body_content = breadcrumb + body_content

    note_path = write_note(
        vault.notes_dir,
        title=note_title,
        body=body_content,
        tags=tags,
        status="draft",
        source=url,
        parent=parent,
        tier=detected_tier,
        content_type=detected_content_type,
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
    # The agent reads the fetched content and writes meaningful summaries and tags.

    # Persist raw_file reference on the note via NoteMeta — this guarantees the
    # field survives any future re-serialization (repair, note update, etc.).
    # The text-injection approach used previously was silently dropped by
    # NoteMeta.model_config = {"extra": "ignore"} on the next parse.
    if raw_file_path:
        from hyperresearch.core.frontmatter import parse_frontmatter, render_note
        note_text = note_path.read_text(encoding="utf-8")
        meta, body = parse_frontmatter(note_text)
        if meta.raw_file != raw_file_path:
            meta.raw_file = raw_file_path
            note_path.write_text(render_note(meta, body), encoding="utf-8")

    # Sync first so the note exists in the notes table (needed for FK on sources/assets)
    note_id = note_path.stem
    plan = compute_sync_plan(vault)
    if plan.to_add or plan.to_update:
        execute_sync(vault, plan)

    # Record source in DB. Use INSERT OR IGNORE to survive a duplicate-URL
    # race: two parallel fetches on the same URL both pass the earlier
    # duplicate-check SELECT, both try to INSERT, and without IGNORE the
    # second crashes with IntegrityError leaving a stray .md file and
    # notes row but no sources row. With IGNORE the second INSERT is a
    # no-op and we detect the race by re-selecting the row afterward.
    content_hash = hashlib.sha256(result.content.encode("utf-8")).hexdigest()[:16]
    conn.execute(
        """INSERT OR IGNORE INTO sources (url, note_id, domain, fetched_at, provider, content_hash)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (url, note_id, domain, result.fetched_at.isoformat(), prov.name, content_hash),
    )
    conn.commit()

    # Detect the race: if the committed row's note_id != ours, another
    # fetch won the race. Clean up our orphan .md file and return the
    # winner's note_id so the caller can treat this as an idempotent no-op.
    winner_row = conn.execute(
        "SELECT note_id FROM sources WHERE url = ?", (url,)
    ).fetchone()
    if winner_row and winner_row["note_id"] != note_id:
        winning_note_id = winner_row["note_id"]
        # Our write lost the race. Unlink the orphan file and re-sync.
        if note_path.exists():
            try:
                note_path.unlink()
            except OSError:
                pass
            plan2 = compute_sync_plan(vault)
            if plan2.to_delete:
                execute_sync(vault, plan2)
        note_id = winning_note_id
        winner_path_row = conn.execute(
            "SELECT path FROM notes WHERE id = ?", (winning_note_id,)
        ).fetchone()
        if winner_path_row:
            note_path = vault.root / winner_path_row["path"]

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
        "raw_file": raw_file_path,
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
