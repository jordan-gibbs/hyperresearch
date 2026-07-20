"""Run commands — per-run workspaces, manifest, resume, budget."""

from __future__ import annotations

import json

import typer

from hyperresearch.cli._output import console, output
from hyperresearch.models.output import error, success

app = typer.Typer()


def _vault_or_exit(json_output: bool):
    from hyperresearch.core.vault import Vault, VaultError

    try:
        return Vault.discover()
    except VaultError as e:
        if json_output:
            output(error(str(e), "NO_VAULT"), json_mode=True)
        else:
            console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)


def _resolve_tag(vault, tag: str | None, json_output: bool) -> str:
    from hyperresearch.core.runs import latest_run_tag

    if tag:
        return tag
    latest = latest_run_tag(vault)
    if latest is None:
        if json_output:
            output(error("no runs exist yet", "NO_RUNS"), json_mode=True)
        else:
            console.print("[red]Error:[/] no runs exist yet")
        raise typer.Exit(1)
    return latest


@app.command("init")
def run_init(
    vault_tag: str = typer.Argument(..., help="Collision-safe run tag (mint via `hyperresearch vault-tag <slug>`)"),
    profile: str = typer.Option("full", "--profile", help="Pipeline profile for this run"),
    budget: float | None = typer.Option(None, "--budget", help="Hard ceiling on estimated API-equivalent spend (the run blocks when the estimate crosses it; a value measure, not a bill, on subscription billing)"),
    query_file: str | None = typer.Option(None, "--query-file", help="File whose verbatim contents become runs/<tag>/query.md"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Scaffold research/runs/<vault_tag>/ with a fresh manifest (idempotent)."""
    from pathlib import Path

    from hyperresearch.core.runs import RunError, init_run

    vault = _vault_or_exit(json_output)
    query = None
    if query_file:
        query = Path(query_file).read_text(encoding="utf-8-sig")
    try:
        manifest = init_run(vault, vault_tag, profile=profile, budget_usd=budget, query=query)
    except RunError as e:
        if json_output:
            output(error(str(e), "RUN_ERROR"), json_mode=True)
        else:
            console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)

    data = {"run_dir": str(vault.run_dir(vault_tag)), "manifest": manifest}
    if json_output:
        output(success(data, vault=str(vault.root)), json_mode=True)
    else:
        console.print(f"[green]Run initialized:[/] {data['run_dir']}")
        console.print(f"  profile: {manifest['profile']}  budget: {manifest.get('budget_usd')}")


@app.command("status")
def run_status(
    vault_tag: str | None = typer.Argument(None, help="Run tag (default: newest run)"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Show a run's manifest + resume position + stall/budget state."""
    from hyperresearch.core.runs import RunError, status_summary

    vault = _vault_or_exit(json_output)
    tag = _resolve_tag(vault, vault_tag, json_output)
    try:
        summary = status_summary(vault, tag)
    except RunError as e:
        if json_output:
            output(error(str(e), "RUN_ERROR"), json_mode=True)
        else:
            console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)

    # Browser-lane queue depth for this run
    try:
        from hyperresearch.core.escalation import queue_stats

        summary["escalations"] = queue_stats(vault.db, vault_tag=tag)
    except Exception:
        summary["escalations"] = None

    if json_output:
        output(success(summary, vault=str(vault.root)), json_mode=True)
    else:
        console.print(f"[bold]{summary['vault_tag']}[/]  ({summary['profile']})  status: {summary['status']}")
        esc = summary.get("escalations")
        if esc and (esc.get("queued") or esc.get("needs_human")):
            console.print(
                f"  [yellow]escalations:[/] {esc['queued']} queued, {esc['needs_human']} need the human"
            )
        if summary.get("possibly_stalled"):
            console.print("  [yellow]possibly stalled — no manifest update recently[/]")
        resume = summary["resume"]
        console.print(f"  done: {', '.join(resume['done_steps']) or '-'}")
        console.print(f"  next: {resume['next_step'] or '(complete)'}")
        spend = summary.get("spend", {})
        console.print(
            f"  API-equiv spend: ~${spend.get('estimated_usd', 0)} | {spend.get('sources_fetched', 0)} sources "
            f"| {spend.get('agents_spawned', 0)} agents"
        )
        if "budget_remaining_usd" in summary:
            console.print(f"  budget remaining (API-equiv): ${summary['budget_remaining_usd']}")


@app.command("list")
def run_list(
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """List all runs, newest first."""
    from hyperresearch.core.runs import list_runs

    vault = _vault_or_exit(json_output)
    runs = list_runs(vault)
    rows = [
        {
            "vault_tag": m.get("vault_tag"),
            "status": m.get("status"),
            "profile": m.get("profile"),
            "started_at": m.get("started_at"),
        }
        for m in runs
    ]
    if json_output:
        output(success({"runs": rows}, count=len(rows), vault=str(vault.root)), json_mode=True)
    else:
        for r in rows:
            console.print(f"  [cyan]{r['vault_tag']}[/] {r['status']} ({r['profile']}) {r['started_at']}")


@app.command("resume")
def run_resume(
    vault_tag: str | None = typer.Argument(None, help="Run tag (default: newest run)"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Print the exact position a recovering orchestrator should continue from."""
    from hyperresearch.core.runs import RunError, load_manifest, resume_position, set_status

    vault = _vault_or_exit(json_output)
    tag = _resolve_tag(vault, vault_tag, json_output)
    try:
        manifest = load_manifest(vault, tag)
    except RunError as e:
        if json_output:
            output(error(str(e), "RUN_ERROR"), json_mode=True)
        else:
            console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)

    position = resume_position(manifest)
    if manifest["status"] in ("paused", "blocked", "failed"):
        set_status(vault, tag, "running")

    data = {
        "vault_tag": tag,
        "run_dir": str(vault.run_dir(tag)),
        "profile": manifest["profile"],
        **position,
        "skill_to_invoke": (
            f"hyperresearch-{position['next_step'].replace('.', '-')}"
            if position["next_step"]
            else None
        ),
    }
    if json_output:
        output(success(data, vault=str(vault.root)), json_mode=True)
    else:
        if position["next_step"] is None:
            console.print(f"[green]{tag}[/] — all profile steps complete.")
        else:
            console.print(f"[green]{tag}[/] — resume at step {position['next_step']}")
            console.print(f"  Skill(skill: \"{data['skill_to_invoke']}\")")


@app.command("abort")
def run_abort(
    vault_tag: str = typer.Argument(..., help="Run tag"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Mark a run aborted (artifacts stay on disk)."""
    from hyperresearch.core.runs import RunError, set_status

    vault = _vault_or_exit(json_output)
    try:
        manifest = set_status(vault, vault_tag, "aborted")
    except RunError as e:
        if json_output:
            output(error(str(e), "RUN_ERROR"), json_mode=True)
        else:
            console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)
    if json_output:
        output(success(manifest, vault=str(vault.root)), json_mode=True)
    else:
        console.print(f"[yellow]Aborted:[/] {vault_tag}")


@app.command("step")
def run_step(
    vault_tag: str = typer.Argument(..., help="Run tag"),
    step: str = typer.Argument(..., help='Step id ("1", "1.5", "11g", ...)'),
    status: str = typer.Option(..., "--status", "-s", help="pending|running|done|skipped|failed"),
    chapter: str | None = typer.Option(None, "--chapter", help="Chapter id for chaptered steps (e.g. ch3)"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Record a step-status transition in the manifest."""
    from hyperresearch.core.runs import RunError, set_step

    vault = _vault_or_exit(json_output)
    try:
        manifest = set_step(vault, vault_tag, step, status, chapter=chapter)
    except RunError as e:
        if json_output:
            output(error(str(e), "RUN_ERROR"), json_mode=True)
        else:
            console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)
    if json_output:
        output(success({"steps": manifest["steps"]}, vault=str(vault.root)), json_mode=True)
    else:
        console.print(f"  step {step} -> {status}")


@app.command("spend")
def run_spend(
    vault_tag: str = typer.Argument(..., help="Run tag"),
    usd: float = typer.Option(0.0, "--usd", help="Estimated API-equivalent spend to add"),
    sources: int = typer.Option(0, "--sources", help="Sources fetched to add"),
    notes: int = typer.Option(0, "--notes", help="Notes written to add"),
    agents: int = typer.Option(0, "--agents", help="Subagents spawned to add"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Add spend counters. Crossing --budget flips the run to blocked."""
    from hyperresearch.core.runs import RunError, add_spend

    vault = _vault_or_exit(json_output)
    try:
        manifest = add_spend(
            vault, vault_tag,
            estimated_usd=usd, sources_fetched=sources,
            notes_written=notes, agents_spawned=agents,
        )
    except RunError as e:
        if json_output:
            output(error(str(e), "RUN_ERROR"), json_mode=True)
        else:
            console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)
    data = {"spend": manifest["spend"], "status": manifest["status"], "blocked_on": manifest["blocked_on"]}
    if json_output:
        output(success(data, vault=str(vault.root)), json_mode=True)
    else:
        console.print(f"  spend: {data['spend']}  status: {data['status']}")


@app.command("event")
def run_event(
    vault_tag: str = typer.Argument(..., help="Run tag"),
    type_: str = typer.Option(..., "--type", help="Event type (spawn, fetch-wave, escalation, note)"),
    data: str | None = typer.Option(None, "--data", help="JSON payload for the event"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Append an event to events.jsonl (also heartbeats the manifest)."""
    from hyperresearch.core.runs import RunError, record_event

    vault = _vault_or_exit(json_output)
    payload = {"type": type_}
    if data:
        try:
            payload.update(json.loads(data))
        except json.JSONDecodeError as e:
            if json_output:
                output(error(f"--data is not valid JSON: {e}", "BAD_JSON"), json_mode=True)
            else:
                console.print(f"[red]Error:[/] --data is not valid JSON: {e}")
            raise typer.Exit(1)
    try:
        record_event(vault, vault_tag, payload)
    except RunError as e:
        if json_output:
            output(error(str(e), "RUN_ERROR"), json_mode=True)
        else:
            console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)
    if json_output:
        output(success({"recorded": payload}, vault=str(vault.root)), json_mode=True)
    else:
        console.print("  event recorded")


@app.command("block")
def run_block(
    vault_tag: str = typer.Argument(..., help="Run tag"),
    on: str = typer.Option(..., "--on", help="What the run is blocked on (e.g. human-challenges, budget)"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Mark a run blocked (e.g. on human browser challenges). `run resume` unblocks."""
    from hyperresearch.core.runs import RunError, set_status

    vault = _vault_or_exit(json_output)
    try:
        manifest = set_status(vault, vault_tag, "blocked", blocked_on=on)
    except RunError as e:
        if json_output:
            output(error(str(e), "RUN_ERROR"), json_mode=True)
        else:
            console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)
    if json_output:
        output(success({"status": manifest["status"], "blocked_on": manifest["blocked_on"]}, vault=str(vault.root)), json_mode=True)
    else:
        console.print(f"[yellow]Blocked:[/] {vault_tag} on {on}")


@app.command("report")
def run_report(
    vault_tag: str | None = typer.Argument(None, help="Run tag (default: newest run); ignored with --all"),
    all_runs: bool = typer.Option(False, "--all", help="Aggregate across every run"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Post-run telemetry: per-step wall-time, spend, and yield.

    The feedback loop for profile tuning — replace inherited constants with
    observed yield curves ("what does wave 2 actually produce?").
    """
    from hyperresearch.core.runs import RunError, list_runs, load_manifest, run_report_data

    vault = _vault_or_exit(json_output)

    if all_runs:
        reports = []
        for manifest in list_runs(vault):
            tag = manifest.get("vault_tag")
            if not tag or manifest.get("status") == "corrupt-manifest":
                continue
            try:
                reports.append(run_report_data(vault, tag))
            except RunError:
                continue
        agg = {
            "runs": len(reports),
            "total_estimated_usd": round(sum(r["spend"]["estimated_usd"] for r in reports), 2),
            "total_sources": sum(r["spend"]["sources_fetched"] for r in reports),
            "total_agents": sum(r["spend"]["agents_spawned"] for r in reports),
            "by_run": reports,
        }
        if json_output:
            output(success(agg, count=len(reports), vault=str(vault.root)), json_mode=True)
        else:
            console.print(f"[bold]{agg['runs']} runs[/] — ~${agg['total_estimated_usd']} API-equiv, "
                          f"{agg['total_sources']} sources, {agg['total_agents']} agents")
            for r in reports:
                console.print(f"  [cyan]{r['vault_tag']}[/] {r['status']} ~${r['spend']['estimated_usd']} "
                              f"{r['spend']['sources_fetched']}src {r['total_wall_minutes']}min")
        return

    tag = _resolve_tag(vault, vault_tag, json_output)
    try:
        load_manifest(vault, tag)
        report = run_report_data(vault, tag)
    except RunError as e:
        if json_output:
            output(error(str(e), "RUN_ERROR"), json_mode=True)
        else:
            console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)

    if json_output:
        output(success(report, vault=str(vault.root)), json_mode=True)
    else:
        console.print(f"[bold]{report['vault_tag']}[/] ({report['profile']}) — {report['status']}, "
                      f"{report['total_wall_minutes']} min total")
        for step in report["steps"]:
            console.print(f"  step {step['step']:>4}: {step['status']:<8} {step['minutes']} min")
        spend = report["spend"]
        console.print(f"  API-equiv spend: ~${spend['estimated_usd']} | {spend['sources_fetched']} sources | "
                      f"{spend['agents_spawned']} agents | {spend['notes_written']} notes")
        ev = report["events"]
        if ev:
            console.print(f"  events: {ev}")


@app.command("verify")
def run_verify(
    vault_tag: str | None = typer.Argument(None, help="Run tag (default: newest run)"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Structural verification battery (exit 1 on failure) — the CI-able gate.

    Report exists / headings honored / length in profile range / citation
    density above floor / tier artifacts present / cite-check resolved.
    Pair with `hyperresearch lint -j` for the content rules.
    """
    from hyperresearch.core.runs import RunError, verify_run

    vault = _vault_or_exit(json_output)
    tag = _resolve_tag(vault, vault_tag, json_output)
    try:
        result = verify_run(vault, tag)
    except RunError as e:
        if json_output:
            output(error(str(e), "RUN_ERROR"), json_mode=True)
        else:
            console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)

    if json_output:
        output(success(result, vault=str(vault.root)), json_mode=True)
    else:
        for c in result["checks"]:
            mark = "[green]ok[/]" if c["ok"] else "[red]FAIL[/]"
            console.print(f"  {mark} {c['name']}: {c['detail']}")
        console.print("[green]PASSED[/]" if result["passed"] else "[red]FAILED[/]")
    if not result["passed"]:
        raise typer.Exit(1)


@app.command("finish")
def run_finish(
    vault_tag: str | None = typer.Argument(None, help="Run tag (default: newest run)"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Terminal ship gate: verify the run, then flip the manifest.

    Pass -> status "done". Fail -> status "blocked" (blocked_on: verify),
    exit 1. This is the ONLY way a run reaches "done"; the fix for a failed
    gate is changing the report until the gate passes, never re-running the
    checks by hand and re-interpreting the results.
    """
    from hyperresearch.core.runs import RunError, finish_run

    vault = _vault_or_exit(json_output)
    tag = _resolve_tag(vault, vault_tag, json_output)
    try:
        result = finish_run(vault, tag)
    except RunError as e:
        if json_output:
            output(error(str(e), "RUN_ERROR"), json_mode=True)
        else:
            console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)

    verify = result["verify"]
    if json_output:
        output(success(result, vault=str(vault.root)), json_mode=True)
    else:
        for c in verify["checks"]:
            mark = "[green]ok[/]" if c["ok"] else "[red]FAIL[/]"
            console.print(f"  {mark} {c['name']}: {c['detail']}")
        status = result["manifest"]["status"]
        if verify["passed"]:
            console.print(f"[green]SHIPPED[/] — run status: {status}")
        else:
            console.print(
                f"[red]BLOCKED[/] — run status: {status} (blocked_on: verify). "
                "Fix the report, then run finish again."
            )
    if not verify["passed"]:
        raise typer.Exit(1)
