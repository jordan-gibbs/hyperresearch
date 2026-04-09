"""Lint / health-check CLI commands."""

from __future__ import annotations

from datetime import UTC

import typer

from hyperresearch.cli._output import console, output
from hyperresearch.models.output import success

app = typer.Typer(invoke_without_command=True)

RULES = {
    "missing-title": "Notes without a title",
    "missing-tags": "Notes without any tags",
    "missing-summary": "Notes without a summary",
    "singleton-tags": "Tags used by only one note",
    "broken-links": "Wiki-links that don't resolve",
    "orphaned-notes": "Notes with no inbound or outbound links",
    "duplicate-ids": "Multiple notes with the same ID",
    "empty-notes": "Notes with no body content",
    "stale-indexes": "Index pages that need rebuilding",
    "expired-notes": "Notes past their expiry date",
    "deprecated-no-successor": "Deprecated notes without a superseded_by link",
    "stale-reviews": "Notes not reviewed in over 90 days",
    "low-confidence": "Notes with confidence < 0.5",
}


@app.callback(invoke_without_command=True)
def lint(
    ctx: typer.Context,
    fix: bool = typer.Option(False, "--fix", help="Auto-fix what's possible"),
    rule: str | None = typer.Option(None, "--rule", "-r", help="Run specific rule only"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Health-check the vault."""
    if ctx.invoked_subcommand is not None:
        return

    from hyperresearch.core.vault import Vault

    vault = Vault.discover()
    vault.auto_sync()
    conn = vault.db

    issues: list[dict] = []

    rules_to_run = [rule] if rule else list(RULES.keys())

    if "missing-title" in rules_to_run:
        for row in conn.execute("SELECT id, path FROM notes WHERE title = '' OR title = 'Untitled'"):
            issues.append({
                "rule": "missing-title",
                "severity": "warning",
                "note_id": row["id"],
                "note_path": row["path"],
                "message": "Note has no meaningful title.",
            })

    if "missing-tags" in rules_to_run:
        for row in conn.execute(
            "SELECT n.id, n.path FROM notes n "
            "WHERE n.type NOT IN ('index','raw') "
            "AND n.id NOT IN (SELECT DISTINCT note_id FROM tags)"
        ):
            issues.append({
                "rule": "missing-tags",
                "severity": "warning",
                "note_id": row["id"],
                "note_path": row["path"],
                "message": "Note has no tags.",
            })

    if "missing-summary" in rules_to_run:
        for row in conn.execute(
            "SELECT n.id, n.path FROM notes n "
            "WHERE n.type NOT IN ('index','raw') "
            "AND (n.summary IS NULL OR LENGTH(TRIM(n.summary)) = 0)"
        ):
            issues.append({
                "rule": "missing-summary",
                "severity": "warning",
                "note_id": row["id"],
                "note_path": row["path"],
                "message": "Note has no summary. Add one for better search and listings.",
            })

    if "singleton-tags" in rules_to_run:
        for row in conn.execute(
            "SELECT tag, COUNT(*) as c FROM tags GROUP BY tag HAVING c = 1"
        ):
            issues.append({
                "rule": "singleton-tags",
                "severity": "info",
                "note_id": row["tag"],
                "message": f"Tag '{row['tag']}' is used by only 1 note. Consider merging.",
            })

    if "broken-links" in rules_to_run:
        for row in conn.execute(
            "SELECT l.source_id, n.path, l.target_ref, l.line_number "
            "FROM links l JOIN notes n ON l.source_id = n.id "
            "WHERE l.target_id IS NULL"
        ):
            issues.append({
                "rule": "broken-links",
                "severity": "warning",
                "note_id": row["source_id"],
                "note_path": row["path"],
                "line": row["line_number"],
                "message": f"Broken link: [[{row['target_ref']}]]",
            })

    if "orphaned-notes" in rules_to_run:
        for row in conn.execute("""
            SELECT n.id, n.path FROM notes n
            WHERE n.type NOT IN ('index', 'raw')
              AND n.id NOT IN (SELECT DISTINCT target_id FROM links WHERE target_id IS NOT NULL)
              AND n.id NOT IN (SELECT DISTINCT source_id FROM links)
        """):
            issues.append({
                "rule": "orphaned-notes",
                "severity": "info",
                "note_id": row["id"],
                "note_path": row["path"],
                "message": "Note is orphaned (no links in or out).",
            })

    if "duplicate-ids" in rules_to_run:
        for row in conn.execute(
            "SELECT id, COUNT(*) as c FROM notes GROUP BY id HAVING c > 1"
        ):
            issues.append({
                "rule": "duplicate-ids",
                "severity": "error",
                "note_id": row["id"],
                "message": f"Duplicate ID found {row['c']} times.",
            })

    if "empty-notes" in rules_to_run:
        for row in conn.execute(
            "SELECT n.id, n.path FROM notes n "
            "JOIN note_content nc ON n.id = nc.note_id "
            "WHERE LENGTH(TRIM(nc.body)) < 10 AND n.type NOT IN ('index')"
        ):
            issues.append({
                "rule": "empty-notes",
                "severity": "info",
                "note_id": row["id"],
                "note_path": row["path"],
                "message": "Note has little or no content.",
            })

    if "expired-notes" in rules_to_run:
        from datetime import datetime
        now_iso = datetime.now(UTC).isoformat()
        for row in conn.execute(
            "SELECT id, path, expires FROM notes WHERE expires IS NOT NULL AND expires < ?",
            (now_iso,),
        ):
            issues.append({
                "rule": "expired-notes",
                "severity": "warning",
                "note_id": row["id"],
                "note_path": row["path"],
                "message": f"Note expired on {row['expires']}. Review or update.",
            })

    if "deprecated-no-successor" in rules_to_run:
        for row in conn.execute(
            "SELECT id, path FROM notes "
            "WHERE (deprecated = 1 OR status = 'deprecated') AND superseded_by IS NULL"
        ):
            issues.append({
                "rule": "deprecated-no-successor",
                "severity": "warning",
                "note_id": row["id"],
                "note_path": row["path"],
                "message": "Deprecated but no superseded_by link. What replaces this?",
            })

    if "stale-reviews" in rules_to_run:
        from datetime import datetime, timedelta
        cutoff = (datetime.now(UTC) - timedelta(days=90)).isoformat()
        for row in conn.execute(
            "SELECT id, path, reviewed FROM notes "
            "WHERE reviewed IS NOT NULL AND reviewed < ? AND status = 'evergreen'",
            (cutoff,),
        ):
            issues.append({
                "rule": "stale-reviews",
                "severity": "info",
                "note_id": row["id"],
                "note_path": row["path"],
                "message": f"Last reviewed {row['reviewed'][:10]}. Consider re-reviewing.",
            })

    if "low-confidence" in rules_to_run:
        for row in conn.execute(
            "SELECT id, path, confidence FROM notes "
            "WHERE confidence IS NOT NULL AND confidence < 0.5 AND status != 'deprecated'"
        ):
            issues.append({
                "rule": "low-confidence",
                "severity": "info",
                "note_id": row["id"],
                "note_path": row["path"],
                "message": f"Low confidence ({row['confidence']:.1%}). Verify or flag.",
            })

    summary = {
        "errors": sum(1 for i in issues if i.get("severity") == "error"),
        "warnings": sum(1 for i in issues if i.get("severity") == "warning"),
        "info": sum(1 for i in issues if i.get("severity") == "info"),
        "total": len(issues),
    }

    if json_output:
        output(
            success({"issues": issues, "summary": summary}, count=len(issues), vault=str(vault.root)),
            json_mode=True,
        )
    else:
        if not issues:
            console.print("[green]Vault is healthy. No issues found.[/]")
            return

        severity_style = {"error": "red bold", "warning": "yellow", "info": "dim"}
        for issue in issues:
            style = severity_style.get(issue.get("severity", "info"), "dim")
            loc = issue.get("note_path", issue.get("note_id", ""))
            line = f" line {issue['line']}" if issue.get("line") else ""
            console.print(f"  [{style}]{issue['rule']}[/] {loc}{line}: {issue['message']}")

        console.print(
            f"\n[bold]Summary:[/] {summary['errors']} errors, "
            f"{summary['warnings']} warnings, {summary['info']} info"
        )
