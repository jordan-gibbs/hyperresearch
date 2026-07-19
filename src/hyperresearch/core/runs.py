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
from datetime import UTC, datetime
from pathlib import Path

MANIFEST_VERSION = 1
MANIFEST_NAME = "run.json"
EVENTS_NAME = "events.jsonl"

RUN_STATUSES = ("running", "paused", "blocked", "done", "failed", "aborted")
STEP_STATUSES = ("pending", "running", "done", "skipped", "failed")

# A run whose manifest hasn't been touched in this long is flagged
# possibly-stalled by `hpr run status`.
STALL_MINUTES = 30


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
) -> dict:
    """Scaffold research/runs/<vault_tag>/ and write a fresh manifest.

    Idempotent: re-running on an existing run returns the existing manifest
    unchanged (so a recovering orchestrator can call it safely).
    """
    from hyperresearch.core.profiles import resolve_profile

    run_dir = vault.run_dir(vault_tag)
    mpath = run_dir / MANIFEST_NAME
    if mpath.exists():
        return load_manifest(vault, vault_tag)

    resolved = resolve_profile(profile, vault.config_path)

    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "temp").mkdir(exist_ok=True)

    if query is not None:
        (run_dir / "query.md").write_text(query, encoding="utf-8")

    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "vault_tag": vault_tag,
        "profile": profile,
        "profile_steps": [str(s) for s in resolved.steps],
        "status": "running",
        "started_at": _now(),
        "updated_at": _now(),
        "budget_usd": budget_usd,
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
    """Append one event to events.jsonl and touch the manifest heartbeat."""
    run_dir = vault.run_dir(vault_tag)
    if not (run_dir / MANIFEST_NAME).exists():
        raise RunError(f"no run '{vault_tag}'")
    event = {"at": _now(), **event}
    with open(run_dir / EVENTS_NAME, "a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")
    manifest = load_manifest(vault, vault_tag)
    _save(vault, vault_tag, manifest)  # heartbeat


def set_step(
    vault,
    vault_tag: str,
    step: str,
    status: str,
    chapter: str | None = None,
) -> dict:
    """Mark a step's status. Steps are keyed as strings ("1", "1.5", "11g")."""
    if status not in STEP_STATUSES:
        raise RunError(f"invalid step status '{status}' (one of {STEP_STATUSES})")
    manifest = load_manifest(vault, vault_tag)
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
    record_event(vault, vault_tag, {"type": "step", "step": str(step), "status": status, "chapter": chapter})
    return manifest


def set_chapter(vault, vault_tag: str, chapter: str, **fields) -> dict:
    """Create/update a chapter entry (title, status, sources, ...)."""
    manifest = load_manifest(vault, vault_tag)
    ch = manifest["chapters"].setdefault(chapter, {})
    ch.update({k: v for k, v in fields.items() if v is not None})
    _save(vault, vault_tag, manifest)
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
    next_step is None when every profile step is done.
    """
    profile_steps = manifest.get("profile_steps", [])
    steps = manifest.get("steps", {})
    done = [s for s in profile_steps if steps.get(s, {}).get("status") in ("done", "skipped")]
    remaining = [s for s in profile_steps if s not in done]
    chapters_pending = [
        name
        for name, ch in manifest.get("chapters", {}).items()
        if ch.get("status") not in ("done", None) and not str(ch.get("status", "")).endswith("-done")
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
        if decomp_path.exists():
            try:
                decomp = json.loads(decomp_path.read_text(encoding="utf-8-sig"))
                response_format = decomp.get("response_format")
                required_headings = decomp.get("required_section_headings", []) or []
            except json.JSONDecodeError:
                check("decomposition-readable", False, "prompt-decomposition.json is not valid JSON")

        if response_format and response_format in profile.word_targets:
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

        cites = len(_re.findall(r"\[\d{1,3}\]", report_text)) + len(
            _re.findall(r"\[\[[^\]]+\]\]", report_text)
        )
        density = cites / max(1, len(report_text)) * 1000
        floor = 1.5  # instruction-critic's re-count trigger
        check(
            "citation-density",
            density >= floor,
            f"{density:.2f} citations/1000 chars (floor {floor})",
        )

        check(
            "no-scaffold-leak",
            "## User Prompt (VERBATIM" not in report_text,
            "scaffold gospel header must not ship",
        )

    # Tier-mandated artifacts
    steps = set(manifest.get("profile_steps", []))
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
