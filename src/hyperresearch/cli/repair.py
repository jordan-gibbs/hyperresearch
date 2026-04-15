"""Repair command — fix and rebuild everything in one shot."""

from __future__ import annotations

from datetime import UTC

import typer

from hyperresearch.cli._output import console, output
from hyperresearch.models.output import error, success


def repair(
    stub_broken: bool = typer.Option(True, "--stub/--no-stub", help="Create stubs for broken links"),
    enrich: bool = typer.Option(True, "--enrich/--no-enrich", help="Auto-tag and auto-summarize notes"),
    promote_notes: bool = typer.Option(True, "--promote/--no-promote", help="Auto-promote qualifying notes"),
    rebuild_index: bool = typer.Option(True, "--index/--no-index", help="Rebuild index pages"),
    update_docs: bool = typer.Option(True, "--docs/--no-docs", help="Update CLAUDE.md"),
    json_output: bool = typer.Option(False, "--json", "-j", help="JSON output"),
) -> None:
    """Repair and rebuild the vault — full sync, fix broken links, promote notes, rebuild indexes."""
    from hyperresearch.core.vault import Vault, VaultError

    try:
        vault = Vault.discover()
    except VaultError as e:
        if json_output:
            output(error(str(e), "NO_VAULT"), json_mode=True)
        else:
            console.print(f"[red]Error:[/] {e}")
        raise typer.Exit(1)

    report: dict = {}

    # Step 1: Force sync — rebuild DB from all files
    if not json_output:
        console.print("[bold]1/6 Syncing...[/]")
    from hyperresearch.core.sync import compute_sync_plan, execute_sync
    plan = compute_sync_plan(vault, force=True)
    result = execute_sync(vault, plan)
    report["sync"] = {
        "added": result.added, "updated": result.updated,
        "deleted": result.deleted, "errors": len(result.errors),
    }
    if not json_output:
        console.print(
            f"  +{result.added} ~{result.updated} -{result.deleted} "
            f"({result.duration_ms:.0f}ms)"
        )

    # Step 2: Stub broken links
    stubs_created = 0
    if stub_broken:
        if not json_output:
            console.print("[bold]2/6 Stubbing broken links...[/]")
        from hyperresearch.core.note import write_note
        rows = vault.db.execute(
            "SELECT DISTINCT target_ref FROM links WHERE target_id IS NULL"
        ).fetchall()
        for row in rows:
            target = row["target_ref"]
            title = target.replace("-", " ").replace("_", " ").title()
            try:
                # Sideline stubs to research/temp/ — see note in cli/graph.py
                write_note(
                    vault.temp_dir, title,
                    body=f"# {title}\n\n*Stub — created to resolve a broken link. Expand this note.*\n",
                    note_id=target, status="draft",
                    summary=f"Stub for [[{target}]]",
                )
                stubs_created += 1
            except Exception:
                pass
        if stubs_created:
            plan = compute_sync_plan(vault)
            execute_sync(vault, plan)
        report["stubs"] = stubs_created
        if not json_output:
            console.print(f"  {stubs_created} stubs created")
    else:
        if not json_output:
            console.print("[dim]2/6 Skipping stubs[/]")

    # Step 3: Enrich — auto-tag and auto-summarize
    enriched_count = 0
    if enrich:
        if not json_output:
            console.print("[bold]3/6 Enriching metadata...[/]")
        from datetime import datetime as _dt

        from hyperresearch.core.enrich import auto_summary, auto_tag
        from hyperresearch.core.frontmatter import parse_frontmatter as _parse_fm
        from hyperresearch.core.frontmatter import serialize_frontmatter as _ser_fm

        # Get existing tag vocabulary
        tag_vocab = [
            {"tag": r["tag"], "count": r["c"]}
            for r in vault.db.execute("SELECT tag, COUNT(*) as c FROM tags GROUP BY tag ORDER BY c DESC")
        ]

        # Find notes missing tags or summary
        deficient = vault.db.execute(
            "SELECT n.id, n.path, n.summary FROM notes n "
            "LEFT JOIN note_content nc ON n.id = nc.note_id "
            "WHERE n.type NOT IN ('index', 'raw') AND ("
            "  n.id NOT IN (SELECT DISTINCT note_id FROM tags) OR "
            "  n.summary IS NULL OR LENGTH(TRIM(COALESCE(n.summary, ''))) = 0"
            ")"
        ).fetchall()

        for row in deficient:
            try:
                fp = vault.root / row["path"]
                meta, body = _parse_fm(fp.read_text(encoding="utf-8-sig"))
                changed = False

                # Auto-tag if no tags
                if not meta.tags:
                    from hyperresearch.core.note import strip_markdown
                    body_plain = strip_markdown(body)
                    suggested = auto_tag(body_plain, tag_vocab)
                    if suggested:
                        meta.tags = suggested
                        changed = True

                # Auto-summary if no summary
                if not meta.summary or not meta.summary.strip():
                    suggested = auto_summary(body)
                    if suggested:
                        meta.summary = suggested
                        changed = True

                if changed:
                    meta.updated = _dt.now(UTC)
                    fp.write_text(_ser_fm(meta) + "\n" + body, encoding="utf-8")
                    enriched_count += 1
            except Exception:
                pass

        if enriched_count:
            plan = compute_sync_plan(vault)
            execute_sync(vault, plan)
        report["enriched"] = enriched_count
        if not json_output:
            console.print(f"  {enriched_count} notes enriched")
    else:
        if not json_output:
            console.print("[dim]3/6 Skipping enrichment[/]")

    # Step 4: Promote notes
    promoted_count = 0
    if promote_notes:
        if not json_output:
            console.print("[bold]4/6 Promoting notes...[/]")
        from datetime import datetime

        from hyperresearch.core.frontmatter import parse_frontmatter, serialize_frontmatter

        # Draft -> Review
        drafts = vault.db.execute("""
            SELECT n.id, n.path FROM notes n
            WHERE n.status = 'draft' AND n.type NOT IN ('index')
              AND n.word_count >= 50
              AND n.summary IS NOT NULL AND LENGTH(n.summary) > 0
              AND n.id IN (SELECT note_id FROM tags)
        """).fetchall()
        for row in drafts:
            try:
                fp = vault.root / row["path"]
                meta, body = parse_frontmatter(fp.read_text(encoding="utf-8-sig"))
                meta.status = "review"
                meta.updated = datetime.now(UTC)
                fp.write_text(serialize_frontmatter(meta) + "\n" + body, encoding="utf-8")
                promoted_count += 1
            except Exception:
                pass

        # Review -> Evergreen
        reviews = vault.db.execute("""
            SELECT n.id, n.path FROM notes n
            WHERE n.status = 'review' AND n.type NOT IN ('index')
              AND n.word_count >= 100
              AND (n.id IN (SELECT DISTINCT source_id FROM links)
                   OR n.id IN (SELECT DISTINCT target_id FROM links WHERE target_id IS NOT NULL))
        """).fetchall()
        for row in reviews:
            try:
                fp = vault.root / row["path"]
                meta, body = parse_frontmatter(fp.read_text(encoding="utf-8-sig"))
                meta.status = "evergreen"
                meta.updated = datetime.now(UTC)
                fp.write_text(serialize_frontmatter(meta) + "\n" + body, encoding="utf-8")
                promoted_count += 1
            except Exception:
                pass

        if promoted_count:
            plan = compute_sync_plan(vault)
            execute_sync(vault, plan)
        report["promoted"] = promoted_count
        if not json_output:
            console.print(f"  {promoted_count} notes promoted")
    else:
        if not json_output:
            console.print("[dim]4/6 Skipping promotion[/]")

    # Step 4: Rebuild indexes
    if rebuild_index:
        if not json_output:
            console.print("[bold]5/6 Rebuilding indexes...[/]")
        from hyperresearch.indexgen.generator import IndexGenerator
        gen = IndexGenerator(vault)
        built = gen.build_all()
        # Sync the new index pages
        plan = compute_sync_plan(vault)
        execute_sync(vault, plan)
        report["indexes"] = len(built)
        if not json_output:
            console.print(f"  {len(built)} index pages built")
    else:
        if not json_output:
            console.print("[dim]5/6 Skipping indexes[/]")

    # Step 5: Update agent docs
    if update_docs:
        if not json_output:
            console.print("[bold]6/6 Updating agent docs...[/]")
        from hyperresearch.core.agent_docs import inject_agent_docs
        modified = inject_agent_docs(vault.root)
        report["agent_docs"] = modified
        if not json_output:
            if modified:
                for m in modified:
                    console.print(f"  {m}")
            else:
                console.print("  Already up to date")
    else:
        if not json_output:
            console.print("[dim]6/6 Skipping agent docs[/]")

    # Final lint summary
    broken = vault.db.execute("SELECT COUNT(*) as c FROM links WHERE target_id IS NULL").fetchone()["c"]
    orphans = vault.db.execute("""
        SELECT COUNT(*) as c FROM notes n
        WHERE n.type NOT IN ('index', 'raw')
          AND n.id NOT IN (SELECT DISTINCT target_id FROM links WHERE target_id IS NOT NULL)
          AND n.id NOT IN (SELECT DISTINCT source_id FROM links)
    """).fetchone()["c"]
    total = vault.db.execute("SELECT COUNT(*) as c FROM notes WHERE type NOT IN ('index')").fetchone()["c"]
    report["health"] = {"total_notes": total, "broken_links": broken, "orphans": orphans}

    if json_output:
        output(success(report, vault=str(vault.root)), json_mode=True)
    else:
        console.print(f"\n[bold]Done.[/] {total} notes, {broken} broken links, {orphans} orphans.")
