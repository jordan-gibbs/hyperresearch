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
    "uncurated": "Non-draft notes without tier or content_type classification",
    "workflow": "Draft or synthesis notes missing paired scaffold/comparison notes",
    "scaffold-prompt": "Scaffold notes missing the verbatim user prompt as first section (gospel rule)",
    "audit-gate": "Unresolved CRITICAL findings in research/audit_findings.json block synthesis save",
    "provenance": "Source notes with no --suggested-by breadcrumb chain (data-flow chain broken)",
    "analyst-coverage": "Fetched sources without paired extract notes (analyst skipped most sources)",
    "orphaned-raw-files": "Files in research/raw/ with no matching note (disk leak from old note rm)",
    "singleton-tags": "Tags used by only one note",
    "broken-links": "Wiki-links that don't resolve",
    "orphaned-notes": "Notes with no inbound or outbound links",
    "duplicate-ids": "Multiple notes with the same ID",
    "empty-notes": "Notes with no body content",
    "stale-indexes": "Index pages that need rebuilding",
    "expired-notes": "Notes past their expiry date",
    "stale-reviews": "Notes not reviewed in over 90 days",
}


@app.callback(invoke_without_command=True)
def lint(
    ctx: typer.Context,
    fix: bool = typer.Option(False, "--fix", help="Auto-fix what's possible"),
    rule: str | None = typer.Option(None, "--rule", "-r", help="Run specific rule only"),
    audit_file: str | None = typer.Option(
        None,
        "--audit-file",
        help=(
            "Path (relative to vault root) to the audit_findings.json file the "
            "audit-gate rule reads. Defaults to research/audit_findings.json. "
            "Ensemble sub-runs pass research/audit_findings-run-{a,b,c}.json."
        ),
    ),
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

    # Map from audit-gate CRITICAL finding id -> lint rule name that should be
    # re-run to verify the fix actually landed. Populated inside the audit-gate
    # block and consumed at the end of lint() for self-certification detection.
    # Key words in the finding description are mapped to lint rule names.
    audit_gate_guards: list[dict] = []  # [{"critical_id", "rule", "description"}]

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

    if "audit-gate" in rules_to_run:
        # Block synthesis save unless BOTH:
        #   (a) at least one `conformance` audit run exists in
        #       research/audit_findings.json, AND
        #   (b) every CRITICAL finding in the most recent conformance run has
        #       a non-null `fixed_at` timestamp (applied or explicitly resolved).
        #
        # Additionally: surface IMPORTANT findings as info-severity issues so
        # the agent sees them in the pre-save lint output. They don't block
        # save, but they do nudge the agent to review them before committing.
        #
        # Missing file = no audit has run yet. Gate is OPEN in that case so
        # early-stage lint runs don't spam errors. But once the file exists,
        # a missing conformance run is itself an error — the protocol demands
        # both modes, not just comprehensiveness.
        import json as _json
        if audit_file:
            audit_path = vault.root / audit_file
        else:
            audit_path = vault.root / "research" / "audit_findings.json"
        if audit_path.exists():
            try:
                audit_data = _json.loads(audit_path.read_text(encoding="utf-8"))
            except (OSError, _json.JSONDecodeError) as exc:
                issues.append({
                    "rule": "audit-gate",
                    "severity": "error",
                    "note_id": "<vault>",
                    "message": (
                        f"research/audit_findings.json exists but is malformed "
                        f"({type(exc).__name__}). Delete or fix it, then re-run "
                        f"the adversarial audit."
                    ),
                })
                audit_data = None

            if isinstance(audit_data, dict):
                runs = audit_data.get("runs", [])
                conformance_runs = [r for r in runs if r.get("mode") == "conformance"]
                comprehensiveness_runs = [r for r in runs if r.get("mode") == "comprehensiveness"]

                # Check (a): a conformance run must exist once any audit has happened.
                if not conformance_runs:
                    if comprehensiveness_runs:
                        issues.append({
                            "rule": "audit-gate",
                            "severity": "error",
                            "note_id": "<vault>",
                            "message": (
                                f"research/audit_findings.json has "
                                f"{len(comprehensiveness_runs)} comprehensiveness run(s) but ZERO "
                                f"conformance runs. Step 11 mandates BOTH modes in parallel. "
                                f"Spawn hyperresearch-auditor with mode=conformance and wait for "
                                f"it to append its findings to audit_findings.json before saving "
                                f"the synthesis."
                            ),
                        })
                    # No runs at all = early stage. Gate stays open.
                else:
                    # Check (b): no unresolved CRITICALs in the newest conformance run.
                    conformance_runs.sort(key=lambda r: r.get("timestamp", ""))
                    latest = conformance_runs[-1]
                    latest_status = latest.get("status", "unknown")
                    criticals = latest.get("criticals") or []
                    unresolved = [c for c in criticals if not c.get("fixed_at")]

                    if unresolved:
                        issues.append({
                            "rule": "audit-gate",
                            "severity": "error",
                            "note_id": "<vault>",
                            "message": (
                                f"Most recent conformance audit has "
                                f"{len(unresolved)} unresolved CRITICAL finding(s): "
                                + "; ".join(
                                    f"[{c.get('id','?')}] {c.get('description','?')[:80]}"
                                    for c in unresolved[:5]
                                )
                                + ". Apply the fixes in research/notes/final_report.md, "
                                + "mark each finding with `fixed_at: <ISO>` in "
                                + "research/audit_findings.json, and re-run the conformance "
                                + "auditor to verify."
                            ),
                        })
                    elif latest_status == "failed":
                        issues.append({
                            "rule": "audit-gate",
                            "severity": "error",
                            "note_id": "<vault>",
                            "message": (
                                "Most recent conformance audit returned status=failed. "
                                "Investigate the findings and re-run the auditor."
                            ),
                        })

                # Surface IMPORTANT findings from EITHER mode's newest run. Info
                # severity = advisory; does not block save, but the agent sees
                # them in the save-gate lint output and can choose to patch.
                for mode_runs, mode_label in (
                    (conformance_runs, "conformance"),
                    (comprehensiveness_runs, "comprehensiveness"),
                ):
                    if not mode_runs:
                        continue
                    mode_runs.sort(key=lambda r: r.get("timestamp", ""))
                    latest_run = mode_runs[-1]
                    important = latest_run.get("important") or []
                    unresolved_important = [i for i in important if not i.get("fixed_at")]
                    if unresolved_important:
                        issues.append({
                            "rule": "audit-gate",
                            "severity": "info",
                            "note_id": "<vault>",
                            "message": (
                                f"{len(unresolved_important)} unresolved IMPORTANT finding(s) in "
                                f"the latest {mode_label} audit (advisory, does not block save): "
                                + "; ".join(
                                    f"[{i.get('id','?')}] {i.get('description','?')[:80]}"
                                    for i in unresolved_important[:5]
                                )
                                + ". Mark `fixed_at` on each after patching the draft."
                            ),
                        })

                # Build guard-rule map: for each CRITICAL with fixed_at set,
                # extract the implied lint rule from keywords in its description
                # and queue that rule for verification. This is how audit-gate
                # detects self-certification (CRITICAL marked fixed but the
                # underlying lint rule still fails).
                #
                # The keyword list covers the natural-language variations we
                # see in real auditor outputs across modalities. Keep these
                # broad — false matches are fine (they cause a re-check
                # which passes harmlessly); missing a match is the failure
                # mode we're guarding against.
                kw_to_rule = [
                    # scaffold-prompt (verbatim prompt gospel rule)
                    ("scaffold-prompt", "scaffold-prompt"),
                    ("scaffold_prompt", "scaffold-prompt"),
                    ("scaffold_extraction_gap", "scaffold-prompt"),
                    ("scaffold extraction gap", "scaffold-prompt"),
                    ("verbatim prompt", "scaffold-prompt"),
                    ("verbatim_prompt", "scaffold-prompt"),
                    ("gospel rule", "scaffold-prompt"),
                    ("user prompt missing", "scaffold-prompt"),

                    # analyst-coverage (extract notes per source)
                    ("analyst-coverage", "analyst-coverage"),
                    ("analyst coverage", "analyst-coverage"),
                    ("analyst_coverage", "analyst-coverage"),
                    ("extract coverage", "analyst-coverage"),
                    ("extract ratio", "analyst-coverage"),
                    ("extract notes", "analyst-coverage"),
                    ("fetch:extract", "analyst-coverage"),
                    ("analyst skipped", "analyst-coverage"),
                    ("no extract", "analyst-coverage"),

                    # provenance (bouncing reading loop + --suggested-by chain)
                    ("provenance", "provenance"),
                    ("suggested-by", "provenance"),
                    ("suggested_by", "provenance"),
                    ("suggested by", "provenance"),
                    ("bouncing reading loop", "provenance"),
                    ("bouncing loop", "provenance"),
                    ("guided reading loop", "provenance"),
                    ("guided loop", "provenance"),
                    ("reading loop", "provenance"),
                    ("breadcrumb", "provenance"),
                    ("data-flow chain", "provenance"),
                    ("data flow chain", "provenance"),
                    ("data-flow broken", "provenance"),
                    ("rabbit-hole", "provenance"),
                    ("rabbit hole", "provenance"),

                    # workflow (scaffold + comparisons + extract artifacts exist)
                    ("workflow", "workflow"),
                    ("missing scaffold", "workflow"),
                    ("missing comparison", "workflow"),
                    ("missing comparisons", "workflow"),
                    ("paired scaffold", "workflow"),
                    ("no scaffold note", "workflow"),
                    ("no comparison note", "workflow"),
                    ("step 7 skipped", "workflow"),
                    ("step 8 skipped", "workflow"),

                    # uncurated (tier + content_type + summary metadata)
                    ("uncurated", "uncurated"),
                    ("tier metadata", "uncurated"),
                    ("content_type", "uncurated"),
                    ("content type", "uncurated"),
                    ("tier/content_type", "uncurated"),
                    ("tier and content_type", "uncurated"),
                    ("classification missing", "uncurated"),
                    ("metadata missing", "uncurated"),
                    ("missing tier", "uncurated"),
                    ("missing summary", "uncurated"),
                ]
                for mode_runs in (conformance_runs, comprehensiveness_runs):
                    if not mode_runs:
                        continue
                    # We already sorted conformance_runs above; sort comprehensiveness
                    # now too so we pick the newest run of each mode.
                    mode_runs_sorted = sorted(mode_runs, key=lambda r: r.get("timestamp", ""))
                    latest_run = mode_runs_sorted[-1]
                    for c in (latest_run.get("criticals") or []):
                        if not c.get("fixed_at"):
                            continue  # unresolved criticals already emitted above
                        desc = (str(c.get("description", "")) + " " +
                                str(c.get("id", ""))).lower()
                        matched = None
                        for kw, rule_name in kw_to_rule:
                            if kw in desc:
                                matched = rule_name
                                break
                        if matched:
                            audit_gate_guards.append({
                                "critical_id": c.get("id", "?"),
                                "rule": matched,
                                "description": c.get("description", "")[:120],
                            })
                            # Ensure the guard rule runs so we can check its
                            # issues in post-processing.
                            if matched not in rules_to_run:
                                rules_to_run.append(matched)
                        else:
                            # CRITICAL marked fixed_at but no known lint rule
                            # maps to its description. The fix is trust-only
                            # — we cannot machine-verify it. Surface a warning
                            # so the user knows this finding was not validated.
                            issues.append({
                                "rule": "audit-gate",
                                "severity": "warning",
                                "note_id": "<vault>",
                                "message": (
                                    f"CRITICAL [{c.get('id','?')}] was marked `fixed_at` but "
                                    f"its description doesn't map to any known lint rule: "
                                    f"'{(c.get('description','') or '')[:100]}'. The fix is "
                                    f"agent-self-reported and not machine-verified. Review the "
                                    f"draft manually to confirm the issue was actually addressed."
                                ),
                            })

    if "scaffold-prompt" in rules_to_run:
        # Enforce the gospel rule: every scaffold-tagged note must open with
        # the user's verbatim prompt as its first section. This is the single
        # machine-checkable invariant that protects the dispatcher's
        # "user prompt is gospel" commitment. Without this check, scaffolds
        # can drift — an agent writes a `## Thesis` opening, never pastes the
        # verbatim prompt, and every downstream step that re-reads the
        # scaffold (audit, draft, comparisons) loses its anchor.
        import re as _re
        _header_re = _re.compile(
            r"^\s*##\s+User\s+Prompt\s*\(\s*VERBATIM.*gospel\s*\)",
            _re.IGNORECASE,
        )
        for row in conn.execute("""
            SELECT n.id, n.path, nc.body
            FROM notes n
            JOIN note_content nc ON n.id = nc.note_id
            WHERE n.id IN (SELECT note_id FROM tags WHERE tag = 'scaffold')
        """):
            body_lines = (row["body"] or "").splitlines()
            # Look for the header within the first 20 non-blank lines
            header_line_idx = None
            seen_non_blank = 0
            for idx, line in enumerate(body_lines):
                if line.strip():
                    seen_non_blank += 1
                if _header_re.match(line):
                    header_line_idx = idx
                    break
                if seen_non_blank >= 20:
                    break

            if header_line_idx is None:
                issues.append({
                    "rule": "scaffold-prompt",
                    "severity": "error",
                    "note_id": row["id"],
                    "note_path": row["path"],
                    "message": (
                        "Scaffold is missing the verbatim user prompt as its first section. "
                        "Every scaffold MUST open with a `## User Prompt (VERBATIM — gospel)` "
                        "header followed by the user's original question as a blockquote. "
                        "This is the gospel rule — the dispatcher re-reads the prompt from "
                        "this section at every downstream step."
                    ),
                })
                continue

            # Check for non-empty blockquote after the header (>= 50 chars total,
            # which is a loose floor — a real prompt will be much longer).
            quote_chars = 0
            for line in body_lines[header_line_idx + 1:]:
                stripped = line.strip()
                if not stripped:
                    continue
                if stripped.startswith(">"):
                    quote_chars += len(stripped.lstrip("> ").strip())
                elif stripped.startswith("##"):
                    break  # hit next header without finding quoted content
                else:
                    # some scaffolds paste the prompt as plain text without
                    # the blockquote prefix — accept if substantive.
                    quote_chars += len(stripped)
                    break

            if quote_chars < 50:
                issues.append({
                    "rule": "scaffold-prompt",
                    "severity": "warning",
                    "note_id": row["id"],
                    "note_path": row["path"],
                    "message": (
                        f"Scaffold has the verbatim-prompt header but the content after it "
                        f"is empty or too short ({quote_chars} chars). Paste the user's "
                        f"full prompt as a blockquote under the header."
                    ),
                })

    if "provenance" in rules_to_run:
        # Verify the `--suggested-by` data-flow chain forms a rooted tree
        # (or forest) across all fetched source notes:
        #
        #   1. At least one seed source exists (a fetched note with no
        #      breadcrumb) — the loop has a starting point.
        #   2. Every non-seed source has at least one breadcrumb pointing at
        #      another source note that exists in the vault (reachable from
        #      a seed through one or more breadcrumb hops).
        #   3. Every breadcrumb's wiki-link target is a real note id — no
        #      dangling backlinks.
        #
        # Previous version used `breadcrumb_count < max(2, source_count // 5)`
        # which was easy to game by backfilling N//5 unrelated breadcrumbs.
        # The rooted-tree check cannot be satisfied without an actual chain.
        import re as _re
        _breadcrumb_re = _re.compile(r"\*Suggested by \[\[([^\]]+)\]\]")

        source_rows = list(conn.execute(
            "SELECT n.id, n.path, nc.body "
            "FROM notes n "
            "JOIN note_content nc ON n.id = nc.note_id "
            "WHERE n.source IS NOT NULL "
            "AND n.id NOT LIKE '\\_%' ESCAPE '\\' "
            "AND n.type NOT IN ('index','raw','moc')"
        ))

        if len(source_rows) <= 5:
            # Small corpora: bouncing loop may not have fired by design.
            # Skip the structural check; fall back to presence check only.
            pass
        else:
            all_note_ids = {
                r["id"] for r in conn.execute("SELECT id FROM notes")
            }

            source_breadcrumbs: dict[str, list[str]] = {}
            for r in source_rows:
                targets = _breadcrumb_re.findall(r["body"] or "")
                # Keep only the wiki-link name before any `|display` pipe.
                cleaned = [t.split("|", 1)[0].strip() for t in targets]
                source_breadcrumbs[r["id"]] = cleaned

            seeds = [nid for nid, crumbs in source_breadcrumbs.items() if not crumbs]
            non_seeds = [nid for nid, crumbs in source_breadcrumbs.items() if crumbs]

            # Condition 1: at least one seed.
            if not seeds:
                issues.append({
                    "rule": "provenance",
                    "severity": "error",
                    "note_id": "<vault>",
                    "message": (
                        f"Provenance graph has no seed: every one of {len(source_rows)} source notes "
                        f"carries a `*Suggested by [[...]]` breadcrumb, which is impossible for a real "
                        f"research session. The guided reading loop must start from at least one seed "
                        f"fetch with no suggester."
                    ),
                })

            # Condition 2 + 3: verify graph is rooted at seeds and no dangling targets.
            if non_seeds:
                dangling: list[tuple[str, str]] = []
                for nid in non_seeds:
                    for target in source_breadcrumbs[nid]:
                        if target not in all_note_ids:
                            dangling.append((nid, target))

                for src_id, target in dangling[:10]:  # cap output
                    issues.append({
                        "rule": "provenance",
                        "severity": "error",
                        "note_id": src_id,
                        "message": (
                            f"Breadcrumb `[[{target}]]` points at a note id that does not exist in the "
                            f"vault. Either the target was deleted, or the breadcrumb was hand-written "
                            f"without a real source. Re-fetch with `--suggested-by <real-note-id>`."
                        ),
                    })

                # BFS from seeds to verify connectivity.
                reachable = set(seeds)
                frontier = list(seeds)
                # Build reverse map: suggester -> notes it sourced
                suggester_to_sourced: dict[str, list[str]] = {}
                for nid, crumbs in source_breadcrumbs.items():
                    for t in crumbs:
                        suggester_to_sourced.setdefault(t, []).append(nid)
                while frontier:
                    current = frontier.pop()
                    for child in suggester_to_sourced.get(current, []):
                        if child not in reachable:
                            reachable.add(child)
                            frontier.append(child)

                unreachable = [nid for nid in non_seeds if nid not in reachable]
                if unreachable:
                    issues.append({
                        "rule": "provenance",
                        "severity": "error",
                        "note_id": "<vault>",
                        "message": (
                            f"{len(unreachable)} source note(s) have breadcrumbs but are not reachable "
                            f"from any seed through the provenance graph — the chain is disconnected. "
                            f"Disconnected islands usually mean an agent fabricated breadcrumbs "
                            f"retroactively without following the guided reading loop. First few: "
                            f"{', '.join(unreachable[:5])}"
                        ),
                    })

            # Condition: coverage. At least half of non-seed sources should have a breadcrumb.
            # (Cheap heuristic: the count of non-seeds is the count of sources with at least
            # one breadcrumb; compare to the count of sources that SHOULD have one.)
            non_seed_ratio = len(non_seeds) / max(len(source_rows), 1)
            # If there is exactly one seed and no non-seeds, the loop never fired.
            if len(source_rows) > 5 and len(non_seeds) == 0:
                issues.append({
                    "rule": "provenance",
                    "severity": "error",
                    "note_id": "<vault>",
                    "message": (
                        f"Vault has {len(source_rows)} fetched source notes but ZERO "
                        f"`*Suggested by [[...]]` breadcrumbs. The bouncing reading loop never "
                        f"fired — every fetch was a flat batch with no link back to the source "
                        f"that proposed it. Use `$HPR fetch ... --suggested-by <source-note-id> "
                        f"--suggested-by-reason \"<why>\"` for every follow-up fetch."
                    ),
                })
            elif non_seed_ratio < 0.3 and len(source_rows) > 10:
                # Less than 30% of the corpus came from analyst recommendations.
                # The guided reading loop effectively didn't fire — this is the
                # exact failure mode both v2 runs exhibited (3/19 and 2/33).
                # Error severity because it blocks Checkpoint 2.
                issues.append({
                    "rule": "provenance",
                    "severity": "error",
                    "note_id": "<vault>",
                    "message": (
                        f"Only {len(non_seeds)}/{len(source_rows)} source notes ({non_seed_ratio:.0%}) "
                        f"have breadcrumbs — the guided reading loop did not fire. The initial batch "
                        f"fetch is not the whole corpus; after fetching seeds you MUST spawn analysts "
                        f"to propose next targets, then fetch those with `--suggested-by`. Target: "
                        f"at least 30% of sources should come from analyst recommendations."
                    ),
                })
            elif non_seed_ratio < 0.5 and len(source_rows) > 10:
                # Between 30% and 50% — under-firing but marginal. Warning only.
                issues.append({
                    "rule": "provenance",
                    "severity": "warning",
                    "note_id": "<vault>",
                    "message": (
                        f"Only {len(non_seeds)}/{len(source_rows)} source notes ({non_seed_ratio:.0%}) "
                        f"have breadcrumbs. The bouncing reading loop is under-firing — most "
                        f"fetches look like flat seeds rather than analyst-driven discoveries."
                    ),
                })

    if "analyst-coverage" in rules_to_run:
        # Detect when source notes were fetched but few were analyzed (i.e.,
        # spawned a hyperresearch-analyst that wrote an extract note). An
        # extract note is identified by carrying the `extract` tag.
        #
        # Rule applies UNCONDITIONALLY — previous versions gated on
        # `source_count >= 10` which silently disabled the rule for small
        # corpora (a compare session with 8 named entities could ship zero
        # extracts and pass). The gate is removed.
        source_count_row = conn.execute(
            "SELECT COUNT(*) as c FROM notes n "
            "WHERE n.source IS NOT NULL "
            "AND n.id NOT LIKE '\\_%' ESCAPE '\\' "
            "AND n.type NOT IN ('index','raw','moc') "
            "AND n.id NOT IN (SELECT note_id FROM tags WHERE tag = 'extract') "
            "AND n.id NOT IN (SELECT note_id FROM tags WHERE tag = 'scaffold') "
            "AND n.id NOT IN (SELECT note_id FROM tags WHERE tag = 'comparison')"
        ).fetchone()
        source_count = source_count_row["c"] if source_count_row else 0

        extract_count_row = conn.execute(
            "SELECT COUNT(DISTINCT note_id) as c FROM tags WHERE tag = 'extract'"
        ).fetchone()
        extract_count = extract_count_row["c"] if extract_count_row else 0

        # Require 1/3 coverage (error floor at 1/4). Even a 2-source session
        # needs at least 1 extract — the analyst is mandatory, not optional.
        if source_count >= 1:
            required_extracts = max(1, source_count // 3)
            error_floor = max(1, source_count // 4)
            if extract_count < required_extracts:
                ratio = extract_count / source_count if source_count else 0
                issues.append({
                    "rule": "analyst-coverage",
                    "severity": "error" if extract_count < error_floor else "warning",
                    "note_id": "<vault>",
                    "message": (
                        f"Vault has {source_count} fetched source notes but only {extract_count} "
                        f"extract notes ({ratio:.0%} coverage, need ≥{required_extracts}). "
                        f"The analyst was skipped on most sources. Spawn "
                        f"hyperresearch-analyst (mode=extract or mode=guided) on the "
                        f"unanalyzed sources during curation. Target: at least 1 extract per "
                        f"3 sources (floor of 1 for any corpus size)."
                    ),
                })

    if "orphaned-raw-files" in rules_to_run:
        # Walk research/raw/ and flag files whose stem doesn't match any note
        # id in the vault. These are leftovers from the pre-Batch-2.5 `note rm`
        # which never touched raw files. A cheap disk-leak detector.
        raw_dir = vault.root / "research" / "raw"
        if raw_dir.is_dir():
            note_ids = {r["id"] for r in conn.execute("SELECT id FROM notes")}
            for raw_file in raw_dir.iterdir():
                if not raw_file.is_file():
                    continue
                # Only flag known raw extensions; ignore any README etc.
                if raw_file.suffix.lower() not in {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp"}:
                    continue
                if raw_file.stem not in note_ids:
                    issues.append({
                        "rule": "orphaned-raw-files",
                        "severity": "warning",
                        "note_id": raw_file.stem,
                        "note_path": str(raw_file.relative_to(vault.root).as_posix()),
                        "message": (
                            f"Raw file {raw_file.name} has no matching note in the vault. "
                            f"Likely a leftover from an old `note rm` that didn't clean up "
                            f"raw files. Delete it manually or let repair handle it."
                        ),
                    })

    if "workflow" in rules_to_run:
        # Detect research sessions that skipped the mandatory process steps.
        # Heuristic: a note with a research-output signal (final_report in id,
        # type=moc, or tag=synthesis) means a research session ran. If that
        # session didn't produce a scaffold note AND a comparison note, the
        # protocol was skipped.
        def _count_by_tag(tag: str) -> int:
            row = conn.execute(
                "SELECT COUNT(DISTINCT note_id) as c FROM tags WHERE tag = ?",
                (tag,),
            ).fetchone()
            return row["c"] if row else 0

        has_research_output = conn.execute("""
            SELECT COUNT(*) as c FROM notes n
            WHERE n.id LIKE '%final_report%'
               OR n.type = 'moc'
               OR n.id IN (SELECT note_id FROM tags WHERE tag = 'synthesis')
        """).fetchone()["c"]

        scaffold_count = _count_by_tag("scaffold")
        comparison_count = _count_by_tag("comparison")
        extract_count = _count_by_tag("extract")

        if has_research_output > 0:
            if scaffold_count == 0:
                issues.append({
                    "rule": "workflow",
                    "severity": "error",
                    "note_id": "<vault>",
                    "message": (
                        f"Vault has {has_research_output} research-output note(s) "
                        f"but 0 scaffold notes. Step 7 was skipped. "
                        f"Research sessions must produce a `scaffold` note before the draft."
                    ),
                })
            if comparison_count == 0:
                issues.append({
                    "rule": "workflow",
                    "severity": "error",
                    "note_id": "<vault>",
                    "message": (
                        f"Vault has {has_research_output} research-output note(s) "
                        f"but 0 comparison notes. Step 8 was skipped. "
                        f"Research sessions must produce a `comparison` note before the draft."
                    ),
                })

        # Flag extract notes that are missing the parent link
        for row in conn.execute("""
            SELECT n.id, n.path FROM notes n
            WHERE n.id IN (SELECT note_id FROM tags WHERE tag = 'extract')
              AND (n.parent IS NULL OR n.parent = '')
        """):
            issues.append({
                "rule": "workflow",
                "severity": "warning",
                "note_id": row["id"],
                "note_path": row["path"],
                "message": "Extract note missing --parent source-id. The chain of custody is broken.",
            })

    if "uncurated" in rules_to_run:
        # Any note that has moved past draft without tier/content_type classification
        # is a curation failure. Exempt: draft notes (expected raw), index/raw/moc
        # types (not sources), and notes whose id starts with _ (auto-generated
        # index notes like _most-linked, _stale, _orphans).
        for row in conn.execute(
            "SELECT n.id, n.path, n.status, n.tier, n.content_type FROM notes n "
            "WHERE n.type NOT IN ('index','raw','moc') "
            "AND n.id NOT LIKE '\\_%' ESCAPE '\\' "
            "AND n.status != 'draft' "
            "AND (n.tier IS NULL OR n.tier = 'unknown' "
            "     OR n.content_type IS NULL OR n.content_type = 'unknown')"
        ):
            missing = []
            if not row["tier"] or row["tier"] == "unknown":
                missing.append("tier")
            if not row["content_type"] or row["content_type"] == "unknown":
                missing.append("content_type")
            issues.append({
                "rule": "uncurated",
                "severity": "warning",
                "note_id": row["id"],
                "note_path": row["path"],
                "message": f"Note is {row['status']} but missing {'/'.join(missing)}. Run curation pass.",
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

    # Audit-gate self-certification post-check. For each CRITICAL finding
    # that was marked `fixed_at`, we queued its implied lint rule for
    # re-running via rules_to_run. Now that the full lint pass is done,
    # check whether the rule still emitted errors. If yes, the agent marked
    # a CRITICAL resolved without actually fixing the underlying vault state
    # — emit a self-cert violation error that blocks the save gate.
    if audit_gate_guards:
        for guard in audit_gate_guards:
            rule_errors = [
                i for i in issues
                if i.get("rule") == guard["rule"] and i.get("severity") == "error"
            ]
            if rule_errors:
                issues.append({
                    "rule": "audit-gate",
                    "severity": "error",
                    "note_id": "<vault>",
                    "message": (
                        f"SELF-CERTIFICATION VIOLATION: CRITICAL [{guard['critical_id']}] "
                        f"was marked `fixed_at` in research/audit_findings.json, but lint "
                        f"rule `{guard['rule']}` still returns {len(rule_errors)} error(s). "
                        f"The finding was '{guard['description']}'. The draft's `fixed_at` "
                        f"marker does not match the vault's actual state — you must fix the "
                        f"underlying issue (not just the bookkeeping). Run "
                        f"`$HPR lint --rule {guard['rule']} -j` to see what's still broken."
                    ),
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
