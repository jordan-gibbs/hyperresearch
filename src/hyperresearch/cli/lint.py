"""Lint / health-check CLI commands."""

from __future__ import annotations

import json
from datetime import UTC

import typer

from hyperresearch.cli._output import console, output
from hyperresearch.core.hooks import SCAFFOLD_ONLY_SECTION_HEADERS
from hyperresearch.models.output import success

app = typer.Typer(invoke_without_command=True)

RULES = {
    "missing-title": "Notes without a title",
    "missing-tags": "Notes without any tags",
    "missing-summary": "Notes without a summary",
    "uncurated": "Non-draft notes without tier or content_type classification",
    "workflow": "Layercake artifacts missing (scaffold, loci, interim notes)",
    "scaffold-prompt": "Scaffold notes missing the verbatim user prompt as first section (gospel rule)",
    "wrapper-report": "Final report missing required wrapper contract sections when a harness pinned the canonical query",
    "audit-gate": "Unresolved CRITICAL findings in research/audit_findings.json block synthesis save",
    "provenance": "Source notes with no --suggested-by breadcrumb chain (data-flow chain broken)",
    "locus-coverage": "Loci identified in Layer 2 missing their interim-report notes (depth investigator skipped)",
    "patch-surgery": "Critical critic findings skipped by the patcher (Layer 6 regeneration guard tripped)",
    "instruction-coverage": "Atomic items from prompt-decomposition missing from the final report (draft drifted from user's ask)",
    "extract-coverage": "Single-pass /research runs with fetched sources but no paired extract notes (reading loop skipped or source-analyst not delegated for long sources)",
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

                    # locus-coverage (interim note per identified locus)
                    ("locus-coverage", "locus-coverage"),
                    ("locus coverage", "locus-coverage"),
                    ("locus_coverage", "locus-coverage"),
                    ("missing interim", "locus-coverage"),
                    ("interim note", "locus-coverage"),
                    ("depth investigator", "locus-coverage"),

                    # extract-coverage (single-pass extract:source ratio)
                    ("extract-coverage", "extract-coverage"),
                    ("extract coverage", "extract-coverage"),
                    ("extract_coverage", "extract-coverage"),
                    ("extract ratio", "extract-coverage"),
                    ("extract notes", "extract-coverage"),
                    ("fetch:extract", "extract-coverage"),
                    ("analyst skipped", "extract-coverage"),  # legacy keyword
                    ("source-analyst skipped", "extract-coverage"),
                    ("no extract", "extract-coverage"),

                    # patch-surgery (patcher didn't apply critical findings)
                    ("patch-surgery", "patch-surgery"),
                    ("patch surgery", "patch-surgery"),
                    ("patch_surgery", "patch-surgery"),
                    ("patch log", "patch-surgery"),
                    ("critical finding skipped", "patch-surgery"),
                    ("regeneration", "patch-surgery"),

                    # instruction-coverage (decomposition items in final report)
                    ("instruction-coverage", "instruction-coverage"),
                    ("instruction coverage", "instruction-coverage"),
                    ("instruction_coverage", "instruction-coverage"),
                    ("prompt decomposition", "instruction-coverage"),
                    ("prompt-decomposition", "instruction-coverage"),
                    ("atomic item", "instruction-coverage"),
                    ("atomic items", "instruction-coverage"),

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
        prompt_path = vault.root / "research" / "prompt.txt"
        canonical_prompt: str | None = None
        if prompt_path.exists():
            try:
                canonical_prompt = (
                    prompt_path.read_text(encoding="utf-8-sig")
                    .replace("\r\n", "\n")
                    .rstrip("\n")
                )
            except OSError:
                canonical_prompt = None

        def _extract_prompt_text(body_lines: list[str], header_line_idx: int) -> str:
            prompt_lines: list[str] = []
            for line in body_lines[header_line_idx + 1:]:
                stripped = line.rstrip("\r\n")
                if stripped.lstrip().startswith("##"):
                    break
                if stripped.lstrip().startswith(">"):
                    raw = stripped.lstrip()[1:]
                    if raw.startswith(" "):
                        raw = raw[1:]
                    prompt_lines.append(raw)
                else:
                    prompt_lines.append(stripped)
            while prompt_lines and not prompt_lines[0]:
                prompt_lines.pop(0)
            while prompt_lines and not prompt_lines[-1]:
                prompt_lines.pop()
            return "\n".join(prompt_lines).replace("\r\n", "\n")

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

            extracted_prompt = _extract_prompt_text(body_lines, header_line_idx)

            # When a canonical prompt artifact exists, require exact equality
            # (modulo line-ending normalization only). This turns the scaffold
            # rule from "has something prompt-like" into a real contract check.
            if canonical_prompt is not None:
                if extracted_prompt != canonical_prompt:
                    issues.append({
                        "rule": "scaffold-prompt",
                        "severity": "error",
                        "note_id": row["id"],
                        "note_path": row["path"],
                        "message": (
                            "Scaffold prompt does not exactly match research/prompt.txt. "
                            "The verbatim prompt is a hard contract when a harness pins it — "
                            "re-copy it character-for-character under the "
                            "`## User Prompt (VERBATIM — gospel)` header."
                        ),
                    })
                continue

            # Fallback for vaults without a canonical-prompt artifact with no canonical prompt artifact:
            # require non-trivial content after the header so the rule still
            # protects against empty placeholder scaffolds.
            quote_chars = len(extracted_prompt)
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

    if "wrapper-report" in rules_to_run:
        # The rule activates when either signals a wrapped harness context:
        #   - research/prompt.txt exists (harness pinned the canonical query)
        #   - research/wrapper_contract.json exists (harness declared packaging)
        #
        # Required terminal sections are READ from wrapper_contract.json, not
        # hardcoded. This keeps the lint mechanism-focused — any wrapper can
        # declare its own packaging contract and the rule will enforce it
        # verbatim. No wrapper declared => skip the terminal-section check
        # but still enforce scaffold-leak hygiene (always wrong regardless
        # of wrapper).
        prompt_path = vault.root / "research" / "prompt.txt"
        contract_path = vault.root / "research" / "wrapper_contract.json"
        wrapper_contract: dict | None = None
        if contract_path.exists():
            try:
                wrapper_contract = json.loads(
                    contract_path.read_text(encoding="utf-8-sig")
                )
            except (OSError, json.JSONDecodeError) as exc:
                issues.append({
                    "rule": "wrapper-report",
                    "severity": "error",
                    "note_id": "<vault>",
                    "message": (
                        f"wrapper_contract.json exists but is unreadable: "
                        f"{type(exc).__name__}: {exc}. Fix the JSON or remove "
                        f"the file."
                    ),
                })
                wrapper_contract = None

        if prompt_path.exists() or wrapper_contract is not None:
            report_path = vault.root / "research" / "notes" / "final_report.md"
            if not report_path.exists():
                issues.append({
                    "rule": "wrapper-report",
                    "severity": "error",
                    "note_id": "<vault>",
                    "message": (
                        "Wrapped research context detected (prompt.txt or "
                        "wrapper_contract.json present) but "
                        "`research/notes/final_report.md` is missing. "
                        "The final report must exist before export."
                    ),
                })
            else:
                try:
                    report_body = report_path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
                except OSError as exc:
                    issues.append({
                        "rule": "wrapper-report",
                        "severity": "error",
                        "note_id": "<vault>",
                        "message": (
                            f"Could not read final report at {report_path}: "
                            f"{type(exc).__name__}."
                        ),
                    })
                    report_body = ""

                # Wrapper-declared required terminal sections (optional).
                required_headers: list[str] = []
                if wrapper_contract is not None:
                    raw = wrapper_contract.get("required_terminal_sections", [])
                    if isinstance(raw, list):
                        required_headers = [str(h) for h in raw if isinstance(h, str)]
                missing_headers = [h for h in required_headers if h not in report_body]
                if missing_headers:
                    issues.append({
                        "rule": "wrapper-report",
                        "severity": "error",
                        "note_id": "<vault>",
                        "message": (
                            "wrapper_contract.json declares required_terminal_sections "
                            "that are missing from the final report. Missing: "
                            f"{', '.join(missing_headers)}."
                        ),
                    })

                # Scaffold-leak hygiene: ALWAYS enforced. Base list comes from
                # the canonical SCAFFOLD_ONLY_SECTION_HEADERS constant in
                # hooks.py (shared with the three agent prompts). Wrapper can
                # declare additional forbidden body sections on top.
                forbidden_headers = list(SCAFFOLD_ONLY_SECTION_HEADERS)
                if wrapper_contract is not None:
                    extra = wrapper_contract.get("forbidden_body_sections", [])
                    if isinstance(extra, list):
                        for h in extra:
                            if isinstance(h, str) and h not in forbidden_headers:
                                forbidden_headers.append(h)

                leaked = [h for h in forbidden_headers if h in report_body]
                if leaked:
                    issues.append({
                        "rule": "wrapper-report",
                        "severity": "error",
                        "note_id": "<vault>",
                        "message": (
                            "Final report is leaking scaffold-only sections into "
                            "the deliverable. Remove: "
                            f"{', '.join(leaked)}."
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

            # Coverage / bouncing-loop heuristic: DOES NOT APPLY to layercake runs.
            #
            # The ensemble architecture uses an analyst-driven bouncing reading
            # loop (seed → analyst proposes next → fetch with --suggested-by).
            # Under that pattern, 30-50% of sources should carry breadcrumbs.
            #
            # Layercake's fetch pattern is different:
            #   - Layer 1 width sweep: orchestrator plans ~30-80 URL queue
            #     from academic APIs + search; fetched as parallel seed batches.
            #     These are SEEDS by design, not bouncing-loop discoveries.
            #   - Layer 3 depth investigators: each can spawn fetchers with
            #     --suggested-by when URLs come from corpus notes, but most
            #     depth fetches are also driven by locus planning, not
            #     analyst-hop chaining.
            #
            # The rooted-tree structural checks above (seeds exist, no dangling
            # breadcrumbs, reachability from seeds) still apply — they catch
            # fabricated provenance. The coverage ratio does not. Skip the
            # ratio checks when the vault is a layercake run (loci.json exists).
            is_layercake_run = (vault.root / "research" / "loci.json").exists()

            non_seed_ratio = len(non_seeds) / max(len(source_rows), 1)
            if is_layercake_run:
                # Layercake: skip coverage checks. Structural invariants above
                # were sufficient. If the architecture changes and the depth
                # investigators need an analyst-driven loop, this can be
                # revisited.
                pass
            elif len(source_rows) > 5 and len(non_seeds) == 0:
                # Non-layercake (ensemble / single-pass) runs: the bouncing
                # loop must fire. Zero breadcrumbs on >5 sources = flat batch.
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

    if "locus-coverage" in rules_to_run:
        # Layercake Layer 2 produces `research/loci.json` (the deduped loci list
        # the orchestrator commits to). Layer 3 must produce one interim note
        # per locus, tagged `locus-<locus-name>` with `type: interim`. This
        # rule catches depth investigators that failed or were skipped.
        loci_path = vault.root / "research" / "loci.json"
        if loci_path.exists():
            try:
                loci_data = json.loads(loci_path.read_text(encoding="utf-8"))
                loci_list = loci_data.get("loci", []) if isinstance(loci_data, dict) else loci_data
            except (json.JSONDecodeError, OSError):
                loci_list = []
                issues.append({
                    "rule": "locus-coverage",
                    "severity": "error",
                    "note_id": "<vault>",
                    "message": (
                        "research/loci.json exists but is not valid JSON. "
                        "Layer 2 output corrupted — re-run loci analysis."
                    ),
                })

            missing_loci: list[str] = []
            for locus in loci_list:
                if not isinstance(locus, dict):
                    continue
                name = locus.get("name")
                if not name:
                    continue
                tag = f"locus-{name}"
                row = conn.execute(
                    "SELECT COUNT(*) as c FROM notes n "
                    "JOIN tags t ON t.note_id = n.id "
                    "WHERE t.tag = ? AND n.type = 'interim'",
                    (tag,),
                ).fetchone()
                interim_count = row["c"] if row else 0
                if interim_count == 0:
                    missing_loci.append(name)

            if missing_loci:
                severity = "error" if len(missing_loci) >= 2 else "warning"
                issues.append({
                    "rule": "locus-coverage",
                    "severity": severity,
                    "note_id": "<vault>",
                    "message": (
                        f"{len(missing_loci)} of {len(loci_list)} loci have no interim note: "
                        f"{', '.join(missing_loci[:6])}{'...' if len(missing_loci) > 6 else ''}. "
                        "The depth investigator either failed or was skipped. "
                        "Layer 3 must produce one `interim-<locus>.md` note per locus "
                        "with `type: interim` and `tag: locus-<name>`."
                    ),
                })

            # Duplicate interim notes on the same locus — a past failure
            # mode where one locus accumulated 3 interim notes. Inflates
            # source count and confuses Layer 5 critics. Warn when any
            # locus has >1 interim.
            duplicate_loci: list[tuple[str, int]] = []
            for locus in loci_list:
                if not isinstance(locus, dict):
                    continue
                name = locus.get("name")
                if not name:
                    continue
                tag = f"locus-{name}"
                row = conn.execute(
                    "SELECT COUNT(*) as c FROM notes n "
                    "JOIN tags t ON t.note_id = n.id "
                    "WHERE t.tag = ? AND n.type = 'interim'",
                    (tag,),
                ).fetchone()
                c = row["c"] if row else 0
                if c > 1:
                    duplicate_loci.append((name, c))

            if duplicate_loci:
                summary = ", ".join(f"{n} ({c})" for n, c in duplicate_loci[:6])
                issues.append({
                    "rule": "locus-coverage",
                    "severity": "warning",
                    "note_id": "<vault>",
                    "message": (
                        f"{len(duplicate_loci)} locus/loci have duplicate interim notes: "
                        f"{summary}. Depth investigators must check for an existing "
                        "interim note on their locus before calling `note new`; if one "
                        "exists, use `note update` or report back to the orchestrator. "
                        "Delete the weaker copies manually."
                    ),
                })

    if "extract-coverage" in rules_to_run:
        # Single-pass /research runs use the "bouncing reading loop": fetch a
        # seed, analyst reads it and proposes next URLs, main agent fetches
        # those, loop. Each fetched source should have a paired extract note
        # (tagged `extract`) with ≥150 words of real content. This rule
        # enforces that discipline — it catches flat-batch fetchers who never
        # spawned an analyst, AND it catches stub-padding attacks where the
        # agent mints hollow extract notes to pass numerical coverage.
        #
        # Layercake runs use a different artifact shape (interim notes per
        # locus, checked by `locus-coverage`). Skip this rule when
        # `research/loci.json` exists — that signals a layercake run.
        is_layercake_run = (vault.root / "research" / "loci.json").exists()
        if not is_layercake_run:
            extract_min_words = 150

            source_count_row = conn.execute(
                "SELECT COUNT(*) as c FROM notes n "
                "WHERE n.source IS NOT NULL "
                "AND n.id NOT LIKE '\\_%' ESCAPE '\\' "
                "AND n.type NOT IN ('index','raw','moc') "
                "AND n.id NOT IN (SELECT note_id FROM tags WHERE tag = 'extract') "
                "AND n.id NOT IN (SELECT note_id FROM tags WHERE tag = 'scaffold') "
                "AND n.id NOT IN (SELECT note_id FROM tags WHERE tag = 'comparison') "
                "AND n.id NOT IN (SELECT note_id FROM tags WHERE tag = 'dud')"
            ).fetchone()
            source_count = source_count_row["c"] if source_count_row else 0

            # REAL extracts: tagged `extract`, body ≥150 words, with parent
            # pointing at a real source note (chain of custody). Stubs and
            # unlinked real-looking extracts don't satisfy.
            extract_count_row = conn.execute(
                "SELECT COUNT(DISTINCT n.id) as c FROM notes n "
                "JOIN tags t ON t.note_id = n.id "
                "WHERE t.tag = 'extract' "
                "AND n.word_count >= ? "
                "AND n.parent IS NOT NULL AND n.parent != '' "
                "AND n.parent IN (SELECT id FROM notes WHERE source IS NOT NULL) "
                "AND n.id NOT IN (SELECT note_id FROM tags WHERE tag = 'dud')",
                (extract_min_words,),
            ).fetchone()
            extract_count = extract_count_row["c"] if extract_count_row else 0

            # Count stubs separately so the lint message stays honest — a
            # vault with 13 real + 45 stub extracts should show that, not
            # silently collapse to "13 extracts".
            stub_count_row = conn.execute(
                "SELECT COUNT(DISTINCT n.id) as c FROM notes n "
                "JOIN tags t ON t.note_id = n.id "
                "WHERE t.tag = 'extract' AND n.word_count < ? "
                "AND n.id NOT IN (SELECT note_id FROM tags WHERE tag = 'dud')",
                (extract_min_words,),
            ).fetchone()
            stub_count = stub_count_row["c"] if stub_count_row else 0

            # Real extracts with no valid parent — broken chain of custody.
            unlinked_real_row = conn.execute(
                "SELECT COUNT(DISTINCT n.id) as c FROM notes n "
                "JOIN tags t ON t.note_id = n.id "
                "WHERE t.tag = 'extract' "
                "AND n.word_count >= ? "
                "AND (n.parent IS NULL OR n.parent = '' "
                "     OR n.parent NOT IN (SELECT id FROM notes WHERE source IS NOT NULL)) "
                "AND n.id NOT IN (SELECT note_id FROM tags WHERE tag = 'dud')",
                (extract_min_words,),
            ).fetchone()
            unlinked_real = unlinked_real_row["c"] if unlinked_real_row else 0

            # Require 1/3 coverage (error floor at 1/4). Even a 2-source
            # session needs at least 1 extract — the analyst is mandatory
            # on single-pass runs, not optional.
            if source_count >= 1:
                required_extracts = max(1, source_count // 3)
                error_floor = max(1, source_count // 4)
                if extract_count < required_extracts:
                    ratio = extract_count / source_count if source_count else 0
                    notes_parts = []
                    if stub_count:
                        notes_parts.append(
                            f"{stub_count} stub notes under {extract_min_words} words, not counted"
                        )
                    if unlinked_real:
                        notes_parts.append(
                            f"{unlinked_real} unlinked real extracts missing a valid parent source-id, not counted"
                        )
                    stub_note = f" (plus {'; '.join(notes_parts)})" if notes_parts else ""
                    issues.append({
                        "rule": "extract-coverage",
                        "severity": "error" if extract_count < error_floor else "warning",
                        "note_id": "<vault>",
                        "message": (
                            f"Vault has {source_count} fetched source notes but only {extract_count} "
                            f"real source-linked extract notes{stub_note} "
                            f"({ratio:.0%} coverage, need ≥{required_extracts}). "
                            f"The analyst was skipped on most sources or the source->extract chain "
                            f"of custody is broken. Spawn an analyst subagent on the unanalyzed "
                            f"sources during curation. Target: at least 1 extract "
                            f"(≥{extract_min_words} words, with `parent=<source-note-id>`) per 3 "
                            f"sources (floor of 1 for any corpus size). Minting stub notes to "
                            f"pass this gate is lint-gaming and will not satisfy."
                        ),
                    })

    if "patch-surgery" in rules_to_run:
        # Layer 6 writes research/patch-log.json. The log records applied,
        # skipped, and conflicted findings. Skipped `critical` findings are
        # blockers — the draft shipped with a critical critique unresolved.
        # This rule surfaces that.
        patch_log_path = vault.root / "research" / "patch-log.json"
        if patch_log_path.exists():
            try:
                log = json.loads(patch_log_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                issues.append({
                    "rule": "patch-surgery",
                    "severity": "error",
                    "note_id": "<vault>",
                    "message": (
                        "research/patch-log.json exists but is not valid JSON. "
                        "Layer 6 output corrupted."
                    ),
                })
                log = {}

            skipped = log.get("skipped", []) if isinstance(log, dict) else []
            critical_skipped = [
                e for e in skipped
                if isinstance(e, dict) and e.get("severity") == "critical"
            ]
            if critical_skipped:
                names = ", ".join(
                    f"#{e.get('finding_id', '?')} ({e.get('critic', '?')})"
                    for e in critical_skipped[:5]
                )
                issues.append({
                    "rule": "patch-surgery",
                    "severity": "error",
                    "note_id": "<vault>",
                    "message": (
                        f"{len(critical_skipped)} critical finding(s) skipped by patcher: "
                        f"{names}. The draft shipped with known-critical issues unresolved. "
                        "Inspect research/patch-log.json and either hand-craft Edits or "
                        "re-spawn the critics with more specific recommendations."
                    ),
                })

            # "Empty log" detector — distinguishes "patcher ran, log lost" from
            # "patcher ran, applied nothing legitimately".
            #
            # If: (a) there are critic findings files with >0 findings AND
            #     (b) the final report exists AND
            #     (c) the patch log's applied+skipped+conflicts total is 0
            # then the patcher's log was lost in transit (e.g., the log-stub
            # file wasn't pre-created, so the Edit-only patcher couldn't
            # populate it and inlined the log in its Task result). The real
            # patches DID get applied to the draft, but the audit trail is
            # gone — we can't verify what the patcher did.
            applied = log.get("applied", []) if isinstance(log, dict) else []
            conflicts = log.get("conflicts", []) if isinstance(log, dict) else []
            total_logged = len(applied) + len(skipped) + len(conflicts)

            # Only flag when there WERE findings to apply.
            critic_totals = 0
            for name in ("dialectic", "depth", "width"):
                cf = vault.root / "research" / f"critic-findings-{name}.json"
                if cf.exists():
                    try:
                        cdata = json.loads(cf.read_text(encoding="utf-8"))
                        critic_totals += len(cdata.get("findings", []))
                    except (json.JSONDecodeError, OSError):
                        pass

            final_report = vault.root / "research" / "notes" / "final_report.md"
            if (
                total_logged == 0
                and critic_totals > 0
                and final_report.exists()
            ):
                issues.append({
                    "rule": "patch-surgery",
                    "severity": "warning",
                    "note_id": "<vault>",
                    "message": (
                        f"Patch log is empty (applied=0, skipped=0, conflicts=0) "
                        f"but critics returned {critic_totals} findings and the "
                        "final report exists. The patcher's log was almost "
                        "certainly lost in transit — Layer 6 orchestrator "
                        "didn't pre-create `research/patch-log.json` as an "
                        "empty stub, so the tool-locked patcher (`[Read, Edit]` "
                        "only) couldn't populate it and inlined the log in its "
                        "Task result instead. The draft WAS patched — you can "
                        "verify via `git diff` on the L4 draft snapshot — but "
                        "the audit trail is gone. Fix: orchestrator must "
                        "`echo '{\"applied\":[], \"skipped\":[], \"conflicts\":[]}' "
                        "> research/patch-log.json` before spawning the patcher."
                    ),
                })

    if "instruction-coverage" in rules_to_run:
        # Layer 0.5 produces `research/prompt-decomposition.json` — a structured
        # breakdown of the atomic items the user's prompt named (sub-questions,
        # entities, required formats, etc.). The final_report.md is expected to
        # cover every atomic item. This rule does a lightweight text-presence
        # check: for each named entity or sub-question in the decomposition,
        # verify the final report mentions it.
        #
        # This is a shallow check — surface presence, not structural mirroring.
        # The instruction-critic agent (Layer 5) does the deeper structural
        # audit. This lint rule is the final post-patch gate that catches
        # items the critic flagged but the patcher couldn't apply.
        decomp_path = vault.root / "research" / "prompt-decomposition.json"
        final_report = vault.root / "research" / "notes" / "final_report.md"
        if decomp_path.exists() and final_report.exists():
            try:
                decomp = json.loads(decomp_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                issues.append({
                    "rule": "instruction-coverage",
                    "severity": "error",
                    "note_id": "<vault>",
                    "message": (
                        f"research/prompt-decomposition.json exists but is "
                        f"not valid JSON: {exc}. Layer 0.5 output corrupted."
                    ),
                })
                decomp = None

            if isinstance(decomp, dict):
                try:
                    report_text = final_report.read_text(encoding="utf-8")
                except OSError:
                    report_text = ""
                report_lower = report_text.lower()

                missing_entities: list[str] = []
                entities = decomp.get("entities", []) or []
                for ent in entities:
                    if not isinstance(ent, dict):
                        continue
                    name = ent.get("name") or ""
                    if name and name.lower() not in report_lower:
                        missing_entities.append(name)

                if missing_entities:
                    severity = "error" if len(missing_entities) >= 3 else "warning"
                    preview = ", ".join(missing_entities[:8])
                    if len(missing_entities) > 8:
                        preview += f", ... (+{len(missing_entities) - 8} more)"
                    issues.append({
                        "rule": "instruction-coverage",
                        "severity": severity,
                        "note_id": "<vault>",
                        "message": (
                            f"{len(missing_entities)} atomic entity/entities "
                            f"from prompt-decomposition.json are missing from "
                            f"the final report: {preview}. The draft drifted "
                            "from the user's explicit ask. Re-spawn the "
                            "instruction-critic with the missing items "
                            "flagged, or hand-craft Edits to restore them."
                        ),
                    })

                # Required formats are a more structural check — we can't
                # reliably grep for "is this a mind map" — but if the format
                # name is literally missing from the prose, that's a signal.
                missing_formats: list[str] = []
                for fmt in (decomp.get("required_formats", []) or []):
                    if not isinstance(fmt, str):
                        continue
                    # Pull the content-word from the format spec (e.g., "mind
                    # map of causal structure" → "mind map")
                    head = fmt.split(" of ")[0].strip().lower()
                    if head and head not in report_lower:
                        missing_formats.append(fmt)
                if missing_formats:
                    issues.append({
                        "rule": "instruction-coverage",
                        "severity": "warning",
                        "note_id": "<vault>",
                        "message": (
                            f"Required format(s) from prompt-decomposition not "
                            f"visibly present in draft: {', '.join(missing_formats[:5])}. "
                            "This may be a false positive if the format is "
                            "rendered without the spec word in the prose — "
                            "review manually."
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
        # Detect research sessions that skipped required process artifacts.
        #
        # Layercake required artifacts when a final_report exists:
        #   - research/scaffold.md       (Layer 0 planning document)
        #   - research/loci.json         (Layer 2 deduped loci list, if depth ran)
        #   - interim notes              (Layer 3 depth investigator outputs)
        #   - research/comparisons.md    (Layer 3.5 cross-locus reconciliation,
        #                                 required when loci.json has 2+ entries)
        #
        # The single-pass /research protocol also produces a scaffold note but
        # has no loci/interim/comparisons artifacts. This rule checks scaffold
        # universally and layercake-specific artifacts only when loci.json exists.
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
        scaffold_md_exists = (vault.root / "research" / "scaffold.md").exists()
        loci_json_exists = (vault.root / "research" / "loci.json").exists()
        interim_count_row = conn.execute(
            "SELECT COUNT(*) as c FROM notes n WHERE n.type = 'interim'"
        ).fetchone()
        interim_count = interim_count_row["c"] if interim_count_row else 0

        if has_research_output > 0:
            # A scaffold note or scaffold.md file satisfies the scaffold
            # requirement. Either artifact is proof that Layer 0 ran.
            if scaffold_count == 0 and not scaffold_md_exists:
                issues.append({
                    "rule": "workflow",
                    "severity": "error",
                    "note_id": "<vault>",
                    "message": (
                        f"Vault has {has_research_output} research-output note(s) "
                        f"but no scaffold artifact (neither a scaffold-tagged note "
                        f"nor research/scaffold.md). Research sessions must produce "
                        f"a scaffold before the draft."
                    ),
                })

            # Layercake-specific: if loci.json exists, the run was layercake and
            # must have produced interim notes.
            if loci_json_exists and interim_count == 0:
                issues.append({
                    "rule": "workflow",
                    "severity": "error",
                    "note_id": "<vault>",
                    "message": (
                        "research/loci.json exists but no interim notes found. "
                        "Layer 3 depth investigation was skipped entirely. "
                        "See locus-coverage rule for per-locus details."
                    ),
                })

            # Layercake-specific: if loci.json has 2+ entries, Layer 3.5 must
            # have produced research/comparisons.md. A single locus means
            # there's nothing to compare and the bridge step is legitimately
            # skipped; 2+ loci means the orchestrator needed to reconcile
            # them before drafting, and skipping that step is the failure
            # mode that tanks the insight score.
            if loci_json_exists:
                try:
                    loci_data = json.loads(
                        (vault.root / "research" / "loci.json").read_text(encoding="utf-8")
                    )
                    loci_list = (
                        loci_data.get("loci", [])
                        if isinstance(loci_data, dict)
                        else loci_data
                    )
                    locus_count = sum(1 for x in loci_list if isinstance(x, dict))
                except (json.JSONDecodeError, OSError):
                    locus_count = 0

                comparisons_exists = (
                    vault.root / "research" / "comparisons.md"
                ).exists()
                if locus_count >= 1 and not comparisons_exists:
                    issues.append({
                        "rule": "workflow",
                        "severity": "error",
                        "note_id": "<vault>",
                        "message": (
                            f"research/loci.json has {locus_count} loci but "
                            "research/comparisons.md is missing. Layer 3.5 "
                            "(cross-locus reconciliation) was skipped. Layer "
                            "3.5 is always-on now — it writes the argumentative "
                            "spine the draft will engage, and single-locus "
                            "runs produce a comparisons.md with that locus's "
                            "committed position as the lone anchor. Spawn the "
                            "orchestrator to produce comparisons.md before the "
                            "next draft."
                        ),
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
