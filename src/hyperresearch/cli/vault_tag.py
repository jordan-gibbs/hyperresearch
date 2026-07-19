"""vault-tag: mint a guaranteed-unique vault_tag for a /hyperresearch run.

The entry skill's bootstrap turns the canonical research query into a short
topical slug (e.g. `efield-dft-sac`). On its own that slug is not unique:
two different queries can slug-collide on shared lexical material, and a
re-run of the same query produces the same slug. Either case would cause
the next run's `research/query-<tag>.md` and final
`research/notes/final_report_<tag>.md` to overwrite the prior run's, since
those are the two filenames the pipeline keys off the vault_tag.

This command takes the topical slug and appends a random 6-hex-char suffix
that's verified unique against every prior run's artifacts in the live
vault (existing query-*.md and final_report_*.md). The result —
`efield-dft-sac-a3f9b7` — is collision-safe across:

  - re-runs of the same query
  - different queries that happen to slug to the same prefix
  - legacy without-suffix tags from older runs (no overlap by construction)
"""

from __future__ import annotations

import re
import secrets
from pathlib import Path

import typer

from hyperresearch.cli._output import console, output
from hyperresearch.models.output import error, success

# Topical slug: lowercase, starts with alnum, allows alnum + dashes, up to
# 60 chars. This is intentionally permissive — the orchestrator already
# produces conservative slugs, and we don't want to bounce an otherwise
# fine input on a strict regex.
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,59}$")

_QUERY_FILE_RE = re.compile(r"^query-(.+)\.md$")
_REPORT_FILE_RE = re.compile(r"^final_report_(.+)\.md$")

_SUFFIX_BYTES = 3  # 6 hex chars → 16M-name space
_MAX_RETRIES = 100  # 16M^100 collisions before this trips — astronomical


def _existing_tags(vault_root: Path, research_dir: Path) -> set[str]:
    """Collect every vault_tag the vault already references on disk.

    Sources:
      - `research/query-*.md` — canonical query files (one per run)
      - `research/notes/final_report_*.md` — final reports

    Archived runs under `research/runs/archive-*/` are deliberately ignored:
    those filenames embed the OLD tag, but they don't collide with NEW
    filenames because the new ones live at the research root and the
    notes dir. Including them would only narrow the suffix space for no
    benefit.
    """
    tags: set[str] = set()
    if research_dir.is_dir():
        for p in research_dir.glob("query-*.md"):
            m = _QUERY_FILE_RE.match(p.name)
            if m:
                tags.add(m.group(1))
    notes_dir = research_dir / "notes"
    if notes_dir.is_dir():
        for p in notes_dir.glob("final_report_*.md"):
            m = _REPORT_FILE_RE.match(p.name)
            if m:
                tags.add(m.group(1))
    # 3.0 per-run workspaces: every research/runs/<tag>/ directory IS a tag
    # (excluding archive-* dirs from `archive-run`, which embed old tags with
    # a prefix that can't collide with fresh mints).
    runs_dir = research_dir / "runs"
    if runs_dir.is_dir():
        for d in runs_dir.iterdir():
            if d.is_dir() and not d.name.startswith("archive-"):
                tags.add(d.name)
    return tags


def vault_tag(
    slug: str = typer.Argument(
        ...,
        help=(
            "Topical slug derived from the canonical research query "
            "(e.g. 'efield-dft-sac'). Lowercase, starts with alnum, "
            "alnum + dashes, up to 60 chars."
        ),
    ),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Mint a unique vault_tag of the form `<slug>-<6-hex>`.

    The 6-char suffix is verified against every prior run's query and
    final-report filenames in the live vault, so a fresh /hyperresearch
    invocation can never silently overwrite a prior run's outputs even
    when the topical slug repeats.
    """
    from hyperresearch.core.vault import Vault, VaultError

    if not _SLUG_RE.match(slug):
        msg = (
            f"Invalid slug '{slug}'. Must be lowercase, start with alnum, "
            "contain only alnum + dashes, up to 60 chars."
        )
        if json_output:
            output(error(msg, "INVALID_SLUG"), json_mode=True)
        else:
            console.print(f"[red]{msg}[/]")
        raise typer.Exit(1)

    try:
        vault = Vault.discover()
    except VaultError as e:
        if json_output:
            output(error(str(e), "NO_VAULT"), json_mode=True)
        else:
            console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)

    taken = _existing_tags(vault.root, vault.research_dir)

    for _ in range(_MAX_RETRIES):
        suffix = secrets.token_hex(_SUFFIX_BYTES)
        candidate = f"{slug}-{suffix}"
        if candidate not in taken:
            data = {"vault_tag": candidate, "slug": slug, "suffix": suffix}
            if json_output:
                output(success(data, vault=str(vault.root)), json_mode=True)
            else:
                console.print(candidate)
            return

    msg = (
        f"Could not mint a unique vault_tag for slug '{slug}' after "
        f"{_MAX_RETRIES} retries. Suffix space ({_SUFFIX_BYTES * 2} hex chars) "
        "exhausted — your vault has an implausibly large number of prior runs "
        "of this exact slug. Pick a more specific slug."
    )
    if json_output:
        output(error(msg, "TAG_SPACE_EXHAUSTED"), json_mode=True)
    else:
        console.print(f"[red]{msg}[/]")
    raise typer.Exit(1)
