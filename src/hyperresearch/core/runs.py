"""Per-run workspaces and the run manifest.

A run is one /hyperresearch invocation. Everything run-scoped lives under
`research/runs/<vault_tag>/`:

    run.json          — the manifest (this module's contract)
    events.jsonl      — append-only event log (step boundaries, spawns, fetches)
    query.md          — canonical verbatim research query
    scaffold.md, prompt-decomposition.json, loci.json, comparisons.md, ...
    temp/             — scratch artifacts (claims JSONs, drafts, notes)
    chapters/chN/     — per-chapter artifact sets (dissertation profile)

The manifest replaces the 1.x "find the highest-numbered artifact on disk"
recovery heuristic with explicit, durable state: per-step status, per-chapter
status, spend counters, and a budget ceiling. The orchestrator updates it at
step boundaries via `hpr run ...` commands; `hpr run resume <tag>` computes
the exact next position.

Vault notes stay global — runs are ephemeral workspaces over the compounding
vault. Final reports ship to `research/notes/final_report_<vault_tag>.md`.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

MANIFEST_VERSION = 1
MANIFEST_NAME = "run.json"

# Avg. chars per ASCII-whitespace token above which str.split() word counts
# are no longer trustworthy (see _lacks_word_boundaries).
_NO_WORD_BOUNDARY_AVG_TOKEN_CHARS = 15.0


def _lacks_word_boundaries(text: str) -> bool:
    """True if ASCII-whitespace doesn't meaningfully segment `text` into words."""
    tokens = text.split()
    if not tokens:
        return False
    avg_token_chars = sum(len(t) for t in tokens) / len(tokens)
    return avg_token_chars >= _NO_WORD_BOUNDARY_AVG_TOKEN_CHARS


def _effective_word_count(text: str, chars_per_word: float) -> float:
    """Script-neutral word count: `str.split()` where whitespace delimits
    words, else characters / `chars_per_word` (the profile's ratio for
    scripts like Chinese, Japanese or Thai). Korean is space-delimited and
    takes the split path."""
    if _lacks_word_boundaries(text):
        return len(text) / chars_per_word
    return len(text.split())


EVENTS_NAME = "events.jsonl"

RUN_STATUSES = ("running", "paused", "blocked", "done", "failed", "aborted")
STEP_STATUSES = ("pending", "running", "done", "skipped", "failed")

# Step 1.5 (chapter partition) registers each chapter by emitting this event
# type with {"chapter": <id>, "title": <title>}; record_event folds it into
# manifest["chapters"] so resume_position sees the chapter as pending. This
# is the ONLY registration path — there is no separate chapter command.
CHAPTER_PLAN_EVENT = "chapter-plan"

# Chaptered profiles loop steps 2..10 per chapter (see the step-1.5 skill's
# "Chapter execution loop"); a chapter is complete once its step 10 is done.
CHAPTER_LAST_STEP = "10"

# A run whose manifest hasn't been touched in this long is flagged
# possibly-stalled by `hpr run status`.
STALL_MINUTES = 30

# Only these blocks can be cleared by `run step --force`. budget/verify stay.
_COUNT_BLOCK_REASONS = ("max_sources", "max_notes")

# When a run is blocked_on a count ceiling, `run step --force` clears the
# block so resume can proceed. Cap force-clears so a resume cannot spin.
_MAX_COUNT_FORCE_CLEARS = 3


class RunError(Exception):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat()


def manifest_path(vault, vault_tag: str) -> Path:
    return vault.run_dir(vault_tag) / MANIFEST_NAME


def init_run(
    vault,
    vault_tag: str,
    profile: str = "full",
    budget_usd: float | None = None,
    query: str | None = None,
    max_sources: int | None = None,
    max_notes: int | None = None,
) -> dict:
    """Scaffold research/runs/<vault_tag>/ and write a fresh manifest.

    Idempotent: re-running on an existing run returns the existing manifest
    unchanged (so a recovering orchestrator can call it safely).

    ``max_sources`` / ``max_notes`` are optional observable ceilings checked
    at step-done against vault_tag-filtered counts (not mtime).
    """
    from hyperresearch.core.profiles import resolve_profile

    if max_sources is not None and max_sources <= 0:
        raise RunError("--max-sources must be a positive integer")
    if max_notes is not None and max_notes <= 0:
        raise RunError("--max-notes must be a positive integer")

    run_dir = vault.run_dir(vault_tag)
    mpath = run_dir / MANIFEST_NAME
    if mpath.exists():
        return load_manifest(vault, vault_tag)

    resolved = resolve_profile(profile, vault.config_path)

    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "temp").mkdir(exist_ok=True)

    if query is not None:
        (run_dir / "query.md").write_text(query, encoding="utf-8")

    now = _now()
    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "vault_tag": vault_tag,
        "profile": profile,
        "profile_steps": [str(s) for s in resolved.steps],
        "status": "running",
        "started_at": now,
        "updated_at": now,
        "budget_usd": budget_usd,
        "max_sources": max_sources,
        "max_notes": max_notes,
        "counts_force_cleared": 0,
        "blocked_on": None,
        "steps": {},
        "chapters": {},
        "spend": {
            "estimated_usd": 0.0,
            "sources_fetched": 0,
            "notes_written": 0,
            "agents_spawned": 0,
        },
    }
    _save(vault, vault_tag, manifest)
    return manifest


def load_manifest(vault, vault_tag: str) -> dict:
    mpath = manifest_path(vault, vault_tag)
    if not mpath.exists():
        raise RunError(f"no run '{vault_tag}' (missing {mpath})")
    try:
        return json.loads(mpath.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise RunError(f"corrupt manifest for run '{vault_tag}': {e}") from e


def _save(vault, vault_tag: str, manifest: dict) -> None:
    manifest["updated_at"] = _now()
    mpath = manifest_path(vault, vault_tag)
    tmp = mpath.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    tmp.replace(mpath)  # atomic on same filesystem


def record_event(vault, vault_tag: str, event: dict) -> None:
    """Append one event to events.jsonl and touch updated_at for stall detection.

    A `chapter-plan` event (step 1.5) also registers its chapter in
    `manifest["chapters"]` — status "planned", plus the title when given —
    so the manifest, not the events log, stays the single input to
    `resume_position`. Re-emitting the event for a chapter that already
    has step progress never regresses its status.
    """
    run_dir = vault.run_dir(vault_tag)
    if not (run_dir / MANIFEST_NAME).exists():
        raise RunError(f"no run '{vault_tag}'")
    event = {"at": _now(), **event}
    with open(run_dir / EVENTS_NAME, "a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")
    manifest = load_manifest(vault, vault_tag)
    if event.get("type") == CHAPTER_PLAN_EVENT:
        _fold_chapter_plan(manifest, event)
    _save(vault, vault_tag, manifest)  # touch updated_at for stall detection


# Bounds on what a chapter-plan event may write into the manifest. Events
# come from `hpr run event --data <json>` — agent-authored, so the payload
# shape is not trusted: only a short scalar chapter id and a short string
# title are folded; every other key is left in events.jsonl.
CHAPTER_ID_MAX_CHARS = 64
CHAPTER_TITLE_MAX_CHARS = 500


def _chapter_id_of(value) -> str | None:
    """A chapter id is a short non-empty string or int; anything else is
    ignored (bools, floats, lists, dicts, None)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        value = str(value)
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > CHAPTER_ID_MAX_CHARS:
        return None
    return value


def _fold_chapter_plan(manifest: dict, event: dict) -> None:
    chapter = _chapter_id_of(event.get("chapter"))
    if chapter is None:
        return
    chapters = manifest.get("chapters")
    if not isinstance(chapters, dict):
        chapters = manifest["chapters"] = {}
    ch = chapters.get(chapter)
    if not isinstance(ch, dict):
        ch = chapters[chapter] = {}
    ch.setdefault("status", "planned")
    title = event.get("title")
    if isinstance(title, str) and title.strip():
        ch["title"] = title.strip()[:CHAPTER_TITLE_MAX_CHARS]


def set_step(
    vault,
    vault_tag: str,
    step: str,
    status: str,
    chapter: str | None = None,
    force: bool = False,
) -> dict:
    """Mark a step's status. Steps are keyed as strings ("1", "1.5", "11g").

    On ``done``, reconciles vault_tag-filtered counts and applies max_sources /
    max_notes. A run blocked on a count ceiling refuses ``done`` unless
    ``force``; budget/verify blocks cannot be cleared with force.
    """
    if status not in STEP_STATUSES:
        raise RunError(f"invalid step status '{status}' (one of {STEP_STATUSES})")
    manifest = load_manifest(vault, vault_tag)
    blocked_on = manifest.get("blocked_on") if manifest.get("status") == "blocked" else None

    if (
        status == "done"
        and blocked_on is not None
        and (blocked_on not in _COUNT_BLOCK_REASONS or not force)
    ):
        if blocked_on in _COUNT_BLOCK_REASONS:
            raise RunError(
                f"run '{vault_tag}' is blocked on {blocked_on!r}; "
                "resolve the limit or re-run step done with --force"
            )
        raise RunError(
            f"run '{vault_tag}' is blocked on {blocked_on!r}; "
            "this block cannot be cleared with --force"
        )

    entry = manifest["steps"].setdefault(str(step), {})
    entry["status"] = status
    if status == "running" and "started_at" not in entry:
        entry["started_at"] = _now()
    if status in ("done", "skipped", "failed"):
        entry["finished_at"] = _now()
    if chapter:
        entry["chapter"] = chapter
        ch = manifest["chapters"].setdefault(chapter, {})
        ch["status"] = f"step-{step}-{status}"
    _save(vault, vault_tag, manifest)
    record_event(
        vault,
        vault_tag,
        {
            "type": "step",
            "step": str(step),
            "status": status,
            "chapter": chapter,
            "force": bool(force),
        },
    )
    # Agents rarely call `hpr run spend`; reconciling at step boundaries is
    # what lets count ceilings fire mid-run instead of only at `run finish` (#92).
    if status == "done":
        was_blocked_on_count = force and blocked_on in _COUNT_BLOCK_REASONS
        if was_blocked_on_count:
            # Unblock first so reconcile runs against a running manifest.
            manifest["status"] = "running"
            manifest["blocked_on"] = None
            _save(vault, vault_tag, manifest)
        reconcile_spend_from_disk(vault, vault_tag)
        manifest = load_manifest(vault, vault_tag)
        # Only clear a re-block when this done started from a count block.
        # A ceiling crossed in this same done stays blocked; the next
        # done --force clears it.
        if was_blocked_on_count and manifest.get("blocked_on") in _COUNT_BLOCK_REASONS:
            cleared = int(manifest.get("counts_force_cleared", 0) or 0)
            if cleared < _MAX_COUNT_FORCE_CLEARS:
                manifest["counts_force_cleared"] = cleared + 1
                manifest["status"] = "running"
                manifest["blocked_on"] = None
                _save(vault, vault_tag, manifest)
                record_event(
                    vault,
                    vault_tag,
                    {"type": "counts_force_clear", "cleared": cleared + 1},
                )
                manifest = load_manifest(vault, vault_tag)
    return manifest


def add_spend(
    vault,
    vault_tag: str,
    estimated_usd: float = 0.0,
    sources_fetched: int = 0,
    notes_written: int = 0,
    agents_spawned: int = 0,
) -> dict:
    manifest = load_manifest(vault, vault_tag)
    spend = manifest["spend"]
    spend["estimated_usd"] = round(spend.get("estimated_usd", 0.0) + estimated_usd, 4)
    spend["sources_fetched"] = spend.get("sources_fetched", 0) + sources_fetched
    spend["notes_written"] = spend.get("notes_written", 0) + notes_written
    spend["agents_spawned"] = spend.get("agents_spawned", 0) + agents_spawned

    # Budget governor: crossing the ceiling flips the run to blocked. The
    # orchestrator checks `hpr run status` at step boundaries and must pause
    # (never silently skip tier-mandated steps — shrink fan-out instead).
    budget = manifest.get("budget_usd")
    if budget is not None and spend["estimated_usd"] >= budget and manifest["status"] == "running":
        manifest["status"] = "blocked"
        manifest["blocked_on"] = "budget"
    _save(vault, vault_tag, manifest)
    return manifest


def _count_notes_and_raw(vault, vault_tag: str) -> tuple[int, int]:
    """Count notes tagged with this run's vault_tag, plus their raw files.

    Concurrent runs share the vault and note update / repair / sources score
    rewrite files, so mtime is not a valid run filter. Count by tag; raw
    sources come from each note's ``raw_file`` frontmatter.
    """
    from hyperresearch.core.note import read_note

    tag = (vault_tag or "").strip().lower()
    conn = vault.db
    try:
        rows = conn.execute(
            """
            SELECT n.path AS path
            FROM notes n
            WHERE n.id IN (
                SELECT note_id FROM tags WHERE tag = ?
            )
            """,
            (tag,),
        ).fetchall()
    except sqlite3.Error as e:
        # Do not invent zero counts — that is the #92 failure mode.
        raise RunError(f"failed to count notes for '{vault_tag}': {e}") from e

    notes_count = 0
    raw_seen: set[str] = set()
    research_dir = vault.research_dir
    for row in rows:
        path_val = row["path"]
        notes_count += 1
        if not path_val:
            continue
        full = vault.root / path_val
        if not full.is_file():
            continue
        try:
            note = read_note(full, vault.root)
            raw_file = note.meta.raw_file
        except Exception:
            continue
        if not raw_file:
            continue
        rel = raw_file[4:] if raw_file.startswith("raw/") else raw_file
        raw_path = research_dir / "raw" / Path(rel).name
        if raw_path.is_file():
            try:
                raw_seen.add(str(raw_path.resolve()))
            except OSError:
                raw_seen.add(str(raw_path))
    return notes_count, len(raw_seen)


def _count_agent_spawns(vault, vault_tag: str) -> int:
    events_file = vault.run_dir(vault_tag) / EVENTS_NAME
    if not events_file.exists():
        return 0
    count = 0
    for line in events_file.read_text(encoding="utf-8").splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") in ("agent_spawn", "spawn", "agent"):
            count += 1
    return count


def _apply_count_ceilings(manifest: dict) -> None:
    """Flip to blocked when max_sources / max_notes are crossed (running only)."""
    if manifest.get("status") != "running":
        return
    spend = manifest.get("spend", {})
    max_sources = manifest.get("max_sources")
    max_notes = manifest.get("max_notes")
    if max_sources is not None and int(spend.get("sources_fetched", 0) or 0) >= max_sources:
        manifest["status"] = "blocked"
        manifest["blocked_on"] = "max_sources"
        return
    if max_notes is not None and int(spend.get("notes_written", 0) or 0) >= max_notes:
        manifest["status"] = "blocked"
        manifest["blocked_on"] = "max_notes"


def reconcile_spend_from_disk(vault, vault_tag: str) -> dict:
    """Fold vault_tag-filtered notes/raw sources and spawn events into spend.

    Pipeline agents often never call `hpr run spend` (#92). Counts come from
    the vault DB (tag + raw_file), not mtime. Agent-reported estimated_usd is
    left alone — this repo does not carry unit prices.
    """
    manifest = load_manifest(vault, vault_tag)

    notes, sources = _count_notes_and_raw(vault, vault_tag)
    agents = max(
        _count_agent_spawns(vault, vault_tag),
        int(manifest.get("spend", {}).get("agents_spawned", 0) or 0),
    )

    spend = manifest.setdefault("spend", {})
    spend["sources_fetched"] = sources
    spend["notes_written"] = notes
    spend["agents_spawned"] = agents
    # estimated_usd only moves via add_spend / hpr run spend.

    _apply_count_ceilings(manifest)

    _save(vault, vault_tag, manifest)
    record_event(
        vault,
        vault_tag,
        {
            "type": "spend_reconcile",
            "sources_fetched": sources,
            "notes_written": notes,
            "agents_spawned": agents,
            "estimated_usd": spend.get("estimated_usd", 0.0),
            "max_sources": manifest.get("max_sources"),
            "max_notes": manifest.get("max_notes"),
            "blocked_on": manifest.get("blocked_on"),
        },
    )
    return manifest


def set_status(vault, vault_tag: str, status: str, blocked_on: str | None = None) -> dict:
    if status not in RUN_STATUSES:
        raise RunError(f"invalid run status '{status}' (one of {RUN_STATUSES})")
    manifest = load_manifest(vault, vault_tag)
    manifest["status"] = status
    manifest["blocked_on"] = blocked_on if status == "blocked" else None
    _save(vault, vault_tag, manifest)
    return manifest


def list_runs(vault) -> list[dict]:
    """All runs, newest-started first. Tolerates corrupt manifests."""
    runs = []
    if not vault.runs_dir.is_dir():
        return runs
    for child in vault.runs_dir.iterdir():
        mpath = child / MANIFEST_NAME
        if not mpath.exists():
            continue
        try:
            m = json.loads(mpath.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            runs.append({"vault_tag": child.name, "status": "corrupt-manifest"})
            continue
        runs.append(m)
    runs.sort(key=lambda m: m.get("started_at", ""), reverse=True)
    return runs


def latest_run_tag(vault) -> str | None:
    runs = list_runs(vault)
    return runs[0]["vault_tag"] if runs else None


def resume_position(manifest: dict) -> dict:
    """Compute where a run should continue.

    Returns {next_step, done_steps, remaining_steps, chapters_pending}.
    next_step is None when every profile step is done. A registered
    chapter (see CHAPTER_PLAN_EVENT) stays pending until its last looped
    step is done — `set_step(..., chapter=)` records "step-<N>-done" per
    step, and only step CHAPTER_LAST_STEP closes the chapter.
    """
    profile_steps = manifest.get("profile_steps", [])
    steps = manifest.get("steps", {})
    done = [s for s in profile_steps if steps.get(s, {}).get("status") in ("done", "skipped")]
    remaining = [s for s in profile_steps if s not in done]
    chapter_done = ("done", f"step-{CHAPTER_LAST_STEP}-done")
    chapters = manifest.get("chapters")
    if not isinstance(chapters, dict):
        chapters = {}
    chapters_pending = [
        name
        for name, ch in chapters.items()
        if not isinstance(ch, dict) or ch.get("status") not in chapter_done
    ]
    return {
        "next_step": remaining[0] if remaining else None,
        "done_steps": done,
        "remaining_steps": remaining,
        "chapters_pending": chapters_pending,
    }


def status_summary(vault, vault_tag: str, stall_minutes: int = STALL_MINUTES) -> dict:
    """Manifest + derived fields (stall detection, resume position, budget)."""
    manifest = load_manifest(vault, vault_tag)
    summary = dict(manifest)
    summary["resume"] = resume_position(manifest)

    possibly_stalled = False
    if manifest.get("status") == "running":
        try:
            updated = datetime.fromisoformat(manifest["updated_at"])
            age_min = (datetime.now(UTC) - updated).total_seconds() / 60
            possibly_stalled = age_min > stall_minutes
        except (KeyError, ValueError):
            possibly_stalled = True
    summary["possibly_stalled"] = possibly_stalled

    budget = manifest.get("budget_usd")
    if budget:
        spent = manifest.get("spend", {}).get("estimated_usd", 0.0)
        summary["budget_remaining_usd"] = round(max(0.0, budget - spent), 4)
    return summary


def _minutes_between(start: str | None, end: str | None) -> float | None:
    if not start or not end:
        return None
    try:
        s = datetime.fromisoformat(start)
        e = datetime.fromisoformat(end)
    except ValueError:
        return None
    return round((e - s).total_seconds() / 60, 1)


def run_report_data(vault, vault_tag: str) -> dict:
    """Telemetry rollup for one run: per-step wall-time, spend, event counts."""
    manifest = load_manifest(vault, vault_tag)

    steps = []
    for step_id in manifest.get("profile_steps", []):
        entry = manifest.get("steps", {}).get(step_id, {})
        steps.append({
            "step": step_id,
            "status": entry.get("status", "pending"),
            "minutes": _minutes_between(entry.get("started_at"), entry.get("finished_at")),
            "chapter": entry.get("chapter"),
        })
    # Steps recorded outside the profile list (1.5, 11g, ...) still report
    extra = sorted(set(manifest.get("steps", {})) - set(manifest.get("profile_steps", [])))
    for step_id in extra:
        entry = manifest["steps"][step_id]
        steps.append({
            "step": step_id,
            "status": entry.get("status", "pending"),
            "minutes": _minutes_between(entry.get("started_at"), entry.get("finished_at")),
            "chapter": entry.get("chapter"),
        })

    event_counts: dict[str, int] = {}
    events_file = vault.run_dir(vault_tag) / EVENTS_NAME
    if events_file.exists():
        for line in events_file.read_text(encoding="utf-8").splitlines():
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            event_counts[ev.get("type", "unknown")] = event_counts.get(ev.get("type", "unknown"), 0) + 1

    return {
        "vault_tag": vault_tag,
        "profile": manifest.get("profile"),
        "status": manifest.get("status"),
        "total_wall_minutes": _minutes_between(manifest.get("started_at"), manifest.get("updated_at")),
        "steps": steps,
        "chapters": manifest.get("chapters", {}),
        "spend": manifest.get("spend", {}),
        "budget_usd": manifest.get("budget_usd"),
        "events": event_counts,
    }


def _declared_tier(run_dir: Path) -> str | None:
    """The `pipeline_tier` step 1 wrote into prompt-decomposition.json.

    Tolerant on purpose: a missing or unreadable decomposition just means
    "no declared tier", and verify_run reports the unreadable case through
    its own `decomposition-readable` check.
    """
    decomp_path = run_dir / "prompt-decomposition.json"
    if not decomp_path.exists():
        return None
    try:
        decomp = json.loads(decomp_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    tier = decomp.get("pipeline_tier") if isinstance(decomp, dict) else None
    return tier if isinstance(tier, str) and tier.strip() else None


def _required_step_ids(manifest: dict, run_dir: Path, config_path: Path | None) -> set[str]:
    """Step ids whose artifacts the ship gate demands.

    The router initializes a run with the installed gear and lets step 1
    reclassify it: "the manifest's profile field is informational — the
    decomposition's tier rules". So when the decomposition declares a tier
    that disagrees with the manifest profile, that tier's step set wins;
    otherwise (no tier, same tier, or a tier that resolves to nothing) the
    manifest's own `profile_steps` stand.
    """
    from hyperresearch.core.profiles import ProfileError, resolve_profile

    steps = {str(s) for s in manifest.get("profile_steps", [])}
    tier = _declared_tier(run_dir)
    if tier is None or tier == manifest.get("profile"):
        return steps
    try:
        return {str(s) for s in resolve_profile(tier, config_path).steps}
    except ProfileError:
        return steps


def verify_run(vault, vault_tag: str) -> dict:
    """Structural verification battery for a completed run.

    The CI-able gate: report exists, headings honored, length in profile
    range, citation density above floor, tier-mandated artifacts present,
    cite-check findings resolved. Returns {passed, checks: [...]} — each
    check {name, ok, detail}. Content lint rules (quote-integrity etc.)
    run separately via `hpr lint`.
    """
    from hyperresearch.core.profiles import resolve_profile

    manifest = load_manifest(vault, vault_tag)
    profile = resolve_profile(manifest.get("profile", "full"), vault.config_path)
    run_dir = vault.run_dir(vault_tag)
    checks: list[dict] = []

    def check(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    report_path = vault.root / "research" / "notes" / f"final_report_{vault_tag}.md"
    check("report-exists", report_path.exists(), str(report_path))

    report_text = ""
    if report_path.exists():
        report_text = report_path.read_text(encoding="utf-8-sig")

        decomp_path = run_dir / "prompt-decomposition.json"
        response_format = None
        required_headings: list[str] = []
        declares_levers = False
        if decomp_path.exists():
            try:
                decomp = json.loads(decomp_path.read_text(encoding="utf-8-sig"))
                response_format = decomp.get("response_format")
                required_headings = decomp.get("required_section_headings", []) or []
                declares_levers = bool(decomp.get("levers"))
            except json.JSONDecodeError:
                check("decomposition-readable", False, "prompt-decomposition.json is not valid JSON")

        # Runs that declared levers must have rendered the shim files the
        # spawn contract pastes downstream. Lever-less runs (pre-levers or
        # defaults-only) skip the check entirely.
        if declares_levers:
            from hyperresearch.core.levers import ROLES

            missing_shims = [
                role for role in ROLES
                if not (run_dir / "shims" / f"{role}.md").exists()
            ]
            check(
                "levers-rendered",
                not missing_shims,
                "all shim files present" if not missing_shims
                else f"missing shims: {missing_shims} (run `hpr levers render {vault_tag}`)",
            )

        if response_format and response_format in profile.word_targets:
            if _lacks_word_boundaries(report_text):
                # char_targets_no_word_boundary is profile-configurable per
                # response_format; falls back to word_target * chars_per_word
                # if a format has no explicit target.
                char_targets = profile.char_targets_no_word_boundary
                if response_format in char_targets:
                    low, high = char_targets[response_format]
                else:
                    low_w, high_w = profile.word_targets[response_format]
                    ratio = profile.chars_per_word_no_word_boundary
                    low, high = int(low_w * ratio), int(high_w * ratio)
                count = len(report_text)
                check(
                    "length-in-range",
                    low * 0.8 <= count <= high * 1.2,
                    f"{count} chars vs target {low}-{high} ({response_format}; char-based; ±20% tolerance)",
                )
            else:
                low, high = profile.word_targets[response_format]
                wc = len(report_text.split())
                check(
                    "length-in-range",
                    low * 0.8 <= wc <= high * 1.2,
                    f"{wc} words vs target {low}-{high} ({response_format}; ±20% tolerance)",
                )

        missing = [h for h in required_headings if h not in report_text]
        check(
            "required-headings",
            not missing,
            "all present" if not missing else f"missing: {missing}",
        )

        import re as _re

        from hyperresearch.core.patterns import WIKI_LINK_RE

        # Grouped markers ([7, 12]) count one citation per source number,
        # so consolidating stacks never lowers measured density. Wiki-link
        # citations use the shared pattern so this gate and the lint/cite-
        # check rules agree on what a [[...]] citation is.
        cites = sum(
            len(g.split(","))
            for g in _re.findall(r"\[(\d{1,3}(?:\s*,\s*\d{1,3})*)\]", report_text)
        ) + len(WIKI_LINK_RE.findall(report_text))
        # Per 1000 *effective* words, not characters: a character floor
        # means a different amount of content per script (CJK packs ~3x
        # the content per character), so the same number would be a
        # different bar for a Japanese report than for an English one.
        no_boundaries = _lacks_word_boundaries(report_text)
        effective_words = _effective_word_count(
            report_text, profile.chars_per_word_no_word_boundary
        )
        density = cites * 1000 / max(1.0, effective_words)
        floor = profile.citation_density_min  # also the instruction critic's re-count trigger
        unit = (
            f"words (chars / {profile.chars_per_word_no_word_boundary:g}; no word boundaries)"
            if no_boundaries
            else "words"
        )
        check(
            "citation-density",
            density >= floor,
            f"{density:.2f} citations/1000 {unit} (floor {floor})",
        )

        check(
            "no-scaffold-leak",
            "## User Prompt (VERBATIM" not in report_text,
            "scaffold gospel header must not ship",
        )

        # Content gates: the blocking lint rules run in-process, so this ONE
        # command carries the whole ship verdict. Bench Q62 shipped with 24
        # hallucinated-quote errors because the orchestrator ran the lint
        # separately and re-interpreted the failures as false positives —
        # folding the rules in here removes that seam.
        try:
            from hyperresearch.cli.lint import (
                _check_quote_integrity,
                _check_retracted_citations,
            )

            for rule, fn in (
                ("quote-integrity", _check_quote_integrity),
                ("retracted-citations", _check_retracted_citations),
            ):
                errors = [
                    i for i in fn(vault, vault.db, report_path, report_text)
                    if i.get("severity") == "error"
                ]
                check(
                    rule,
                    not errors,
                    "clean" if not errors else (
                        f"{len(errors)} error(s) — first: "
                        f"{errors[0].get('message', '')[:160]}"
                    ),
                )
        except Exception as exc:
            check("content-lints", False, f"content lint rules failed to run: {exc}")

    # Tier-mandated artifacts, keyed on the tier the run actually ran (see
    # _required_step_ids) rather than the profile it was initialized with.
    steps = _required_step_ids(manifest, run_dir, vault.config_path)
    if {"12", "14"} <= steps:
        for name in (
            "critic-findings-dialectic.json", "critic-findings-depth.json",
            "critic-findings-width.json", "critic-findings-instruction.json",
            "patch-log.json",
        ):
            check(f"artifact:{name}", (run_dir / name).exists(), str(run_dir / name))
    if "15" in steps:
        check("artifact:polish-log.json", (run_dir / "polish-log.json").exists(),
              str(run_dir / "polish-log.json"))

    # Cite-check (step 14.5): findings must exist and critical ones resolved
    cc_findings = run_dir / "cite-check-findings.json"
    if manifest.get("steps", {}).get("14.5", {}).get("status") == "done":
        ok = cc_findings.exists()
        detail = str(cc_findings)
        if ok:
            try:
                findings = json.loads(cc_findings.read_text(encoding="utf-8-sig"))
                # The cite-check step writes {"findings": [...]}; older runs
                # (and the original design sketch) used a bare list. Accept both.
                if isinstance(findings, dict):
                    findings = findings.get("findings", [])
                criticals = [f for f in findings if f.get("severity") == "critical"]
                if criticals:
                    log_path = run_dir / "cite-check-patch-log.json"
                    ok = log_path.exists()
                    detail = f"{len(criticals)} critical finding(s); patch log {'present' if ok else 'MISSING'}"
            except json.JSONDecodeError:
                ok = False
                detail = "cite-check-findings.json is not valid JSON"
        check("cite-check-resolved", ok, detail)

    return {"vault_tag": vault_tag, "passed": all(c["ok"] for c in checks), "checks": checks}


def finish_run(vault, vault_tag: str) -> dict:
    """The terminal ship gate: verify, then flip the manifest accordingly.

    This is the ONLY path to status "done". Verification failure flips the
    run to blocked (blocked_on="verify") instead — the caller's job is then
    to change the REPORT until the gate passes, never to re-interpret the
    checks. The verify result is recorded in the manifest either way, so
    `run status` and the bench harness can see whether a "done" run actually
    earned it.
    """
    result = verify_run(vault, vault_tag)
    # Counts come from vault_tag-filtered disk/DB so a finished run never
    # reports zero just because agents skipped `hpr run spend`.
    reconcile_spend_from_disk(vault, vault_tag)
    manifest = load_manifest(vault, vault_tag)
    manifest["verify"] = {
        "passed": result["passed"],
        "at": _now(),
        "failed_checks": [c["name"] for c in result["checks"] if not c["ok"]],
    }
    if result["passed"]:
        manifest["status"] = "done"
        manifest["blocked_on"] = None
    else:
        manifest["status"] = "blocked"
        manifest["blocked_on"] = "verify"
    _save(vault, vault_tag, manifest)
    record_event(vault, vault_tag, {
        "type": "finish",
        "passed": result["passed"],
        "failed_checks": manifest["verify"]["failed_checks"],
    })
    return {"manifest": manifest, "verify": result}
