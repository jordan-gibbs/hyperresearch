"""Tests for lint rules — especially the gospel-enforcing scaffold-prompt rule."""

from __future__ import annotations

from typer.testing import CliRunner

from hyperresearch.cli.lint import app as lint_app
from hyperresearch.core.note import write_note


def _run_lint(vault, rule: str | None = None, audit_file: str | None = None) -> tuple[int, str]:
    """Invoke `hyperresearch lint` CLI against a vault. Returns (exit_code, stdout)."""
    import os

    runner = CliRunner()
    prev_cwd = os.getcwd()
    try:
        os.chdir(vault.root)
        args: list[str] = ["--json"]
        if rule:
            args = ["--rule", rule, *args]
        if audit_file:
            args = [*args, "--audit-file", audit_file]
        result = runner.invoke(lint_app, args, catch_exceptions=False)
        return result.exit_code, result.output
    finally:
        os.chdir(prev_cwd)


def _write_scaffold(vault, body: str, note_id: str = "scaffold-test"):
    write_note(
        vault.notes_dir,
        "Scaffold: Test",
        body=body,
        tags=["scaffold"],
        note_id=note_id,
    )
    vault.auto_sync()


def test_scaffold_prompt_passes_with_verbatim_prompt(tmp_vault):
    _write_scaffold(
        tmp_vault,
        body=(
            "## User Prompt (VERBATIM — gospel)\n"
            "> I would like a detailed analysis of the Saint Seiya franchise and its armor classes. "
            "For each significant character please describe techniques and fate.\n\n"
            "## What the user explicitly asked for\n"
            "- Entity enumeration\n"
        ),
    )
    code, out = _run_lint(tmp_vault, rule="scaffold-prompt")
    assert code == 0
    # Output should contain no scaffold-prompt issues
    import json
    data = json.loads(out)
    issues = data.get("data", {}).get("issues", [])
    scaffold_issues = [i for i in issues if i.get("rule") == "scaffold-prompt"]
    assert scaffold_issues == []


def test_scaffold_prompt_fails_when_header_missing(tmp_vault):
    _write_scaffold(
        tmp_vault,
        body=(
            "## Thesis\n"
            "Saint Seiya's armor hierarchy encodes a theology of sacrifice.\n\n"
            "## Heading progression\n"
            "1. Cosmology\n"
        ),
    )
    _, out = _run_lint(tmp_vault, rule="scaffold-prompt")
    import json
    data = json.loads(out)
    issues = data.get("data", {}).get("issues", [])
    scaffold_issues = [i for i in issues if i.get("rule") == "scaffold-prompt"]
    assert len(scaffold_issues) == 1
    assert scaffold_issues[0]["severity"] == "error"
    assert "verbatim" in scaffold_issues[0]["message"].lower()


def test_scaffold_prompt_warns_when_quote_too_short(tmp_vault):
    _write_scaffold(
        tmp_vault,
        body=(
            "## User Prompt (VERBATIM — gospel)\n"
            "> hi\n\n"
            "## What the user explicitly asked for\n"
            "- thing\n"
        ),
    )
    _, out = _run_lint(tmp_vault, rule="scaffold-prompt")
    import json
    data = json.loads(out)
    issues = data.get("data", {}).get("issues", [])
    scaffold_issues = [i for i in issues if i.get("rule") == "scaffold-prompt"]
    assert len(scaffold_issues) == 1
    assert scaffold_issues[0]["severity"] == "warning"


def test_scaffold_prompt_fails_when_canonical_prompt_mismatch(tmp_vault):
    (tmp_vault.root / "research" / "prompt.txt").write_text(
        "Exact benchmark prompt text.\nSecond line.",
        encoding="utf-8",
    )
    _write_scaffold(
        tmp_vault,
        body=(
            "## User Prompt (VERBATIM — gospel)\n"
            "> Exact benchmark prompt text.\n"
            "> Second line with drift.\n\n"
            "## What the user explicitly asked for\n"
            "- thing\n"
        ),
    )
    _, out = _run_lint(tmp_vault, rule="scaffold-prompt")
    import json
    data = json.loads(out)
    issues = [i for i in data.get("data", {}).get("issues", []) if i.get("rule") == "scaffold-prompt"]
    assert len(issues) == 1
    assert issues[0]["severity"] == "error"
    assert "research/prompt.txt" in issues[0]["message"]


def test_scaffold_prompt_no_scaffold_notes_is_noop(tmp_vault):
    # A vault with no scaffold-tagged notes should produce no issues for this rule.
    code, out = _run_lint(tmp_vault, rule="scaffold-prompt")
    assert code == 0
    import json
    data = json.loads(out)
    issues = data.get("data", {}).get("issues", [])
    scaffold_issues = [i for i in issues if i.get("rule") == "scaffold-prompt"]
    assert scaffold_issues == []


def _write_wrapper_contract(vault, **fields):
    """Persist a research/wrapper_contract.json at the vault root."""
    import json
    (vault.root / "research" / "wrapper_contract.json").write_text(
        json.dumps(fields), encoding="utf-8",
    )


def test_benchmark_report_requires_terminal_sections_from_wrapper_contract(tmp_vault):
    """When wrapper_contract.json declares required_terminal_sections, the
    benchmark-report rule must fail if any are missing from the final report."""
    (tmp_vault.root / "research" / "prompt.txt").write_text(
        "Exact benchmark prompt text.",
        encoding="utf-8",
    )
    _write_wrapper_contract(
        tmp_vault,
        required_terminal_sections=[
            "## Opinionated Synthesis",
            "### Concluding Thoughts",
        ],
    )
    (tmp_vault.root / "research" / "notes" / "final_report.md").write_text(
        "# Report\n\n## Body\nSome benchmark content.\n",
        encoding="utf-8",
    )

    _, out = _run_lint(tmp_vault, rule="benchmark-report")
    import json
    data = json.loads(out)
    issues = [i for i in data.get("data", {}).get("issues", []) if i.get("rule") == "benchmark-report"]
    assert len(issues) == 1
    assert issues[0]["severity"] == "error"
    assert "required_terminal_sections" in issues[0]["message"]
    assert "Opinionated Synthesis" in issues[0]["message"]
    assert "Concluding Thoughts" in issues[0]["message"]


def test_benchmark_report_passes_when_required_sections_present(tmp_vault):
    """Wrapper contract + report with all declared sections => no issues."""
    (tmp_vault.root / "research" / "prompt.txt").write_text(
        "Exact benchmark prompt text.",
        encoding="utf-8",
    )
    _write_wrapper_contract(
        tmp_vault,
        required_terminal_sections=[
            "## Opinionated Synthesis",
            "### Concluding Thoughts",
        ],
    )
    (tmp_vault.root / "research" / "notes" / "final_report.md").write_text(
        (
            "# Report\n\n"
            "## Body\nSome benchmark content.\n\n"
            "## Opinionated Synthesis\n\n"
            "### Concluding Thoughts\nE\n"
        ),
        encoding="utf-8",
    )

    _, out = _run_lint(tmp_vault, rule="benchmark-report")
    import json
    data = json.loads(out)
    issues = [i for i in data.get("data", {}).get("issues", []) if i.get("rule") == "benchmark-report"]
    assert issues == []


def test_benchmark_report_without_contract_only_checks_hygiene(tmp_vault):
    """With prompt.txt but no wrapper_contract.json, the rule should NOT
    flag missing terminal sections (since nothing was declared required).
    Scaffold-leak hygiene is still enforced."""
    (tmp_vault.root / "research" / "prompt.txt").write_text(
        "Exact benchmark prompt text.",
        encoding="utf-8",
    )
    (tmp_vault.root / "research" / "notes" / "final_report.md").write_text(
        "# Report\n\n## Body\nSome content, no synthesis tail.\n",
        encoding="utf-8",
    )

    _, out = _run_lint(tmp_vault, rule="benchmark-report")
    import json
    data = json.loads(out)
    issues = [i for i in data.get("data", {}).get("issues", []) if i.get("rule") == "benchmark-report"]
    assert issues == []


def test_benchmark_report_forbids_scaffold_leaks_without_contract(tmp_vault):
    """Scaffold-leak hygiene runs regardless of whether wrapper_contract.json
    declares forbidden_body_sections — the canonical base list from
    SCAFFOLD_ONLY_SECTION_HEADERS is always forbidden."""
    (tmp_vault.root / "research" / "prompt.txt").write_text(
        "Exact benchmark prompt text.",
        encoding="utf-8",
    )
    (tmp_vault.root / "research" / "notes" / "final_report.md").write_text(
        (
            "# Report\n\n"
            "## User Prompt (VERBATIM — gospel)\n"
            "> Exact benchmark prompt text.\n\n"
            "## Body\nContent.\n"
        ),
        encoding="utf-8",
    )

    _, out = _run_lint(tmp_vault, rule="benchmark-report")
    import json
    data = json.loads(out)
    issues = [i for i in data.get("data", {}).get("issues", []) if i.get("rule") == "benchmark-report"]
    assert len(issues) == 1
    assert issues[0]["severity"] == "error"
    assert "leaking scaffold-only sections" in issues[0]["message"]
    assert "User Prompt (VERBATIM" in issues[0]["message"]


def test_benchmark_report_honors_wrapper_extra_forbidden_sections(tmp_vault):
    """A wrapper can declare ADDITIONAL forbidden body sections on top of the
    canonical base list."""
    _write_wrapper_contract(
        tmp_vault,
        forbidden_body_sections=["## Internal-only scratch"],
    )
    (tmp_vault.root / "research" / "notes" / "final_report.md").write_text(
        (
            "# Report\n\n"
            "## Body\nContent.\n\n"
            "## Internal-only scratch\nLeaked note.\n"
        ),
        encoding="utf-8",
    )

    _, out = _run_lint(tmp_vault, rule="benchmark-report")
    import json
    data = json.loads(out)
    issues = [i for i in data.get("data", {}).get("issues", []) if i.get("rule") == "benchmark-report"]
    assert len(issues) == 1
    assert "Internal-only scratch" in issues[0]["message"]


def test_benchmark_report_inactive_without_signals(tmp_vault):
    """No prompt.txt, no wrapper_contract.json => rule is inactive, no issues."""
    (tmp_vault.root / "research" / "notes" / "final_report.md").write_text(
        "# Report\n\n## Body\nRegular /research output.\n",
        encoding="utf-8",
    )

    _, out = _run_lint(tmp_vault, rule="benchmark-report")
    import json
    data = json.loads(out)
    issues = [i for i in data.get("data", {}).get("issues", []) if i.get("rule") == "benchmark-report"]
    assert issues == []


def test_benchmark_report_unreadable_contract_surfaces_error(tmp_vault):
    """Malformed wrapper_contract.json produces an error rather than silently
    disabling the rule."""
    (tmp_vault.root / "research" / "wrapper_contract.json").write_text(
        "{not valid json",
        encoding="utf-8",
    )
    _, out = _run_lint(tmp_vault, rule="benchmark-report")
    import json
    data = json.loads(out)
    issues = [i for i in data.get("data", {}).get("issues", []) if i.get("rule") == "benchmark-report"]
    assert any("wrapper_contract.json" in i["message"] for i in issues)


def _write_source(vault, title: str, note_id: str, body: str = "Source content."):
    write_note(
        vault.notes_dir,
        title,
        body=body,
        note_id=note_id,
        source=f"https://example.com/{note_id}",
        tier="institutional",
        content_type="article",
    )


def _write_extract(
    vault,
    note_id: str,
    word_count_target: int,
    run_tag: str | None = None,
    parent: str | None = None,
    dud: bool = False,
):
    """Write an extract note with a body of roughly `word_count_target` words.

    When `dud=True`, the extract is tagged `dud` — marking it as an honest
    "source had no extractable content" placeholder. The analyst-coverage
    lint excludes dud notes from both its numerator and denominator.
    """
    body = "word " * word_count_target
    tags = ["extract"]
    if run_tag:
        tags.append(run_tag)
    if dud:
        tags.append("dud")
    write_note(
        vault.notes_dir,
        f"Extract {note_id}",
        body=body,
        note_id=note_id,
        tags=tags,
        parent=parent,
    )


def _write_dud_source(vault, title: str, note_id: str, body: str = "Dud source content."):
    """Write a source note that is also tagged `dud` — simulating a fetch
    that returned something but the body is genuinely unextractable."""
    write_note(
        vault.notes_dir,
        title,
        body=body,
        note_id=note_id,
        source=f"https://example.com/{note_id}",
        tier="institutional",
        content_type="article",
        tags=["dud"],
    )


def test_provenance_rooted_tree_passes_with_valid_chain(tmp_vault):
    # Build a valid chain: seed → child1 → child2, plus a few more non-seeds
    # pointing at the seed or each other. 6+ sources so the rule activates.
    _write_source(tmp_vault, "Seed Source", "seed-one", body="Seminal paper on X.")
    _write_source(tmp_vault, "Child A", "child-a", body="*Suggested by [[seed-one]] — follow-up citation*\n\nDerivative work.")
    _write_source(tmp_vault, "Child B", "child-b", body="*Suggested by [[seed-one]] — cross-reference*\n\nRelated analysis.")
    _write_source(tmp_vault, "Grandchild", "grandchild", body="*Suggested by [[child-a]] — deeper dive*\n\nMore content.")
    _write_source(tmp_vault, "Extra seed", "seed-two", body="Another primary source.")
    _write_source(tmp_vault, "Child C", "child-c", body="*Suggested by [[seed-two]] — reply*\n\nCritical response.")
    tmp_vault.auto_sync()

    _, out = _run_lint(tmp_vault, rule="provenance")
    import json
    data = json.loads(out)
    issues = [i for i in data.get("data", {}).get("issues", []) if i.get("rule") == "provenance"]
    assert issues == [], f"expected no issues, got: {issues}"


def test_provenance_fails_when_all_sources_are_seeds(tmp_vault):
    # 6 sources, zero breadcrumbs — flat batch, rule must fire.
    for i in range(6):
        _write_source(tmp_vault, f"Source {i}", f"source-{i}")
    tmp_vault.auto_sync()

    _, out = _run_lint(tmp_vault, rule="provenance")
    import json
    data = json.loads(out)
    issues = [i for i in data.get("data", {}).get("issues", []) if i.get("rule") == "provenance"]
    assert len(issues) >= 1
    assert any("ZERO" in i["message"] or "no seed" in i["message"].lower() or "bouncing reading loop" in i["message"] for i in issues)


def test_provenance_fails_on_dangling_breadcrumb(tmp_vault):
    # Six sources; one of them references a non-existent note.
    _write_source(tmp_vault, "Seed", "seed-one")
    _write_source(tmp_vault, "Child A", "child-a", body="*Suggested by [[seed-one]] — real*\n")
    _write_source(tmp_vault, "Child B", "child-b", body="*Suggested by [[seed-one]] — real*\n")
    _write_source(tmp_vault, "Dangler", "dangler", body="*Suggested by [[nonexistent-note]] — fake*\n")
    _write_source(tmp_vault, "Child C", "child-c", body="*Suggested by [[seed-one]] — real*\n")
    _write_source(tmp_vault, "Child D", "child-d", body="*Suggested by [[seed-one]] — real*\n")
    tmp_vault.auto_sync()

    _, out = _run_lint(tmp_vault, rule="provenance")
    import json
    data = json.loads(out)
    issues = [i for i in data.get("data", {}).get("issues", []) if i.get("rule") == "provenance"]
    assert any("nonexistent-note" in i["message"] for i in issues), (
        f"expected dangling breadcrumb issue, got: {issues}"
    )


def test_provenance_small_corpus_is_skipped(tmp_vault):
    # <= 5 sources, rule should not complain (loop may not have fired by design).
    for i in range(3):
        _write_source(tmp_vault, f"Source {i}", f"source-{i}")
    tmp_vault.auto_sync()

    _, out = _run_lint(tmp_vault, rule="provenance")
    import json
    data = json.loads(out)
    issues = [i for i in data.get("data", {}).get("issues", []) if i.get("rule") == "provenance"]
    assert issues == []


def test_provenance_errors_on_under_30pct_non_seed_ratio(tmp_vault):
    """The guided reading loop must actually fire. A large corpus with only
    a token 1-2 breadcrumbs should ERROR, not just warn. This is the exact
    failure mode both v2 runs exhibited (3/19 and 2/33 breadcrumbs)."""
    # 11 sources, 2 of them with breadcrumbs = 18% non-seed (below 30%)
    _write_source(tmp_vault, "Seed 1", "seed-one")
    _write_source(tmp_vault, "Seed 2", "seed-two")
    for i in range(9):
        # 2 of the 9 have breadcrumbs; rest are seeds
        if i < 2:
            body = f"*Suggested by [[seed-one]] — from analyst*\n\nContent {i}"
        else:
            body = f"Content {i}"
        _write_source(tmp_vault, f"Source {i}", f"source-{i}", body=body)
    tmp_vault.auto_sync()

    _, out = _run_lint(tmp_vault, rule="provenance")
    import json
    data = json.loads(out)
    issues = [i for i in data.get("data", {}).get("issues", []) if i.get("rule") == "provenance"]
    errors = [i for i in issues if i.get("severity") == "error"]
    assert len(errors) >= 1
    assert "guided reading loop did not fire" in errors[0]["message"]


def test_orphaned_raw_files_flags_disk_leak(tmp_vault):
    """Files in research/raw/ with no matching note should be flagged."""
    raw_dir = tmp_vault.root / "research" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    # Create a raw file whose stem doesn't match any note.
    (raw_dir / "orphan-note.pdf").write_bytes(b"%PDF-1.4 dummy")
    tmp_vault.auto_sync()

    _, out = _run_lint(tmp_vault, rule="orphaned-raw-files")
    import json
    data = json.loads(out)
    issues = [i for i in data.get("data", {}).get("issues", []) if i.get("rule") == "orphaned-raw-files"]
    assert len(issues) == 1
    assert "orphan-note" in issues[0]["message"]


def _write_audit_findings(vault, data: dict, path: str = "research/audit_findings.json") -> None:
    import json as _json
    audit_path = vault.root / path
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(_json.dumps(data, indent=2), encoding="utf-8")


def test_audit_gate_accepts_custom_audit_file_flag(tmp_vault):
    """Ensemble sub-runs need to point audit-gate at per-run audit files."""
    # Parent audit_findings.json has unresolved CRITICALs — would normally block.
    _write_audit_findings(tmp_vault, {
        "runs": [
            {
                "mode": "conformance",
                "timestamp": "2026-04-14T10:00:00Z",
                "status": "needs_fixes",
                "criticals": [{"id": "C0", "description": "parent gap", "fixed_at": None}],
                "important": [],
                "minor": [],
            }
        ],
    })
    # But the per-run file for run-a is clean. Gate should pass when pointed there.
    _write_audit_findings(tmp_vault, {
        "runs": [
            {
                "mode": "comprehensiveness",
                "timestamp": "2026-04-14T10:00:00Z",
                "status": "pass",
                "criticals": [],
                "important": [],
                "minor": [],
            },
            {
                "mode": "conformance",
                "timestamp": "2026-04-14T10:01:00Z",
                "status": "pass",
                "criticals": [],
                "important": [],
                "minor": [],
            },
        ],
    }, path="research/audit_findings-run-a.json")

    _, out = _run_lint(
        tmp_vault,
        rule="audit-gate",
        audit_file="research/audit_findings-run-a.json",
    )
    import json
    data = json.loads(out)
    issues = [i for i in data.get("data", {}).get("issues", []) if i.get("rule") == "audit-gate"]
    assert issues == [], f"sub-run gate should pass, got: {issues}"

    # Sanity: the DEFAULT path (parent's) still blocks — the flag is scoped, not global.
    _, out = _run_lint(tmp_vault, rule="audit-gate")
    data = json.loads(out)
    issues = [i for i in data.get("data", {}).get("issues", []) if i.get("rule") == "audit-gate"]
    assert len(issues) >= 1, "parent gate should still block"


def test_audit_gate_missing_file_is_open(tmp_vault):
    """No audit file = gate is OPEN (early-stage research)."""
    code, out = _run_lint(tmp_vault, rule="audit-gate")
    assert code == 0
    import json
    data = json.loads(out)
    issues = [i for i in data.get("data", {}).get("issues", []) if i.get("rule") == "audit-gate"]
    assert issues == []


def test_audit_gate_blocks_unresolved_criticals(tmp_vault):
    _write_audit_findings(tmp_vault, {
        "runs": [
            {
                "mode": "conformance",
                "timestamp": "2026-04-14T10:00:00Z",
                "status": "needs_fixes",
                "criticals": [
                    {"id": "C0", "description": "Scaffold missing verbatim prompt", "fixed_at": None},
                    {"id": "C1", "description": "Silver Saints omitted", "fixed_at": None},
                ],
                "important": [],
                "minor": [],
            }
        ]
    })
    _, out = _run_lint(tmp_vault, rule="audit-gate")
    import json
    data = json.loads(out)
    issues = [i for i in data.get("data", {}).get("issues", []) if i.get("rule") == "audit-gate"]
    assert len(issues) == 1
    assert "2 unresolved CRITICAL" in issues[0]["message"]


def test_audit_gate_passes_when_all_criticals_fixed(tmp_vault):
    """A CRITICAL with a vague description that doesn't map to any lint rule
    should emit a WARNING (unverified agent self-report) but NOT an error —
    the save gate still opens because warnings don't block."""
    _write_audit_findings(tmp_vault, {
        "runs": [
            {
                "mode": "conformance",
                "timestamp": "2026-04-14T10:00:00Z",
                "status": "pass",
                "criticals": [
                    {"id": "C0", "description": "generic content fix", "fixed_at": "2026-04-14T11:00:00Z"},
                ],
                "important": [],
                "minor": [],
            }
        ]
    })
    _, out = _run_lint(tmp_vault, rule="audit-gate")
    import json
    data = json.loads(out)
    issues = [i for i in data.get("data", {}).get("issues", []) if i.get("rule") == "audit-gate"]
    errors = [i for i in issues if i.get("severity") == "error"]
    warnings = [i for i in issues if i.get("severity") == "warning"]
    # Save gate stays open (no errors) but emits a warning about the
    # unverified self-report.
    assert errors == []
    assert len(warnings) == 1
    assert "not machine-verified" in warnings[0]["message"]


def test_audit_gate_uses_most_recent_conformance_run(tmp_vault):
    """If a later run has fixes applied, the gate should pass even if older
    runs had unresolved findings."""
    _write_audit_findings(tmp_vault, {
        "runs": [
            {
                "mode": "conformance",
                "timestamp": "2026-04-14T10:00:00Z",
                "status": "needs_fixes",
                "criticals": [
                    {"id": "C0", "description": "old finding", "fixed_at": None},
                ],
                "important": [], "minor": [],
            },
            {
                "mode": "conformance",
                "timestamp": "2026-04-14T12:00:00Z",
                "status": "pass",
                "criticals": [],
                "important": [], "minor": [],
            },
        ]
    })
    _, out = _run_lint(tmp_vault, rule="audit-gate")
    import json
    data = json.loads(out)
    issues = [i for i in data.get("data", {}).get("issues", []) if i.get("rule") == "audit-gate"]
    assert issues == []


def test_audit_gate_fails_when_only_comprehensiveness_run_exists(tmp_vault):
    """A file with only comprehensiveness runs means the conformance auditor
    never fired. The save gate must fail in that case."""
    _write_audit_findings(tmp_vault, {
        "runs": [
            {
                "mode": "comprehensiveness",
                "timestamp": "2026-04-14T10:00:00Z",
                "status": "needs_fixes",
                "criticals": [],
                "important": [
                    {"id": "I1", "description": "some gap", "fixed_at": None},
                ],
                "minor": [],
            }
        ]
    })
    _, out = _run_lint(tmp_vault, rule="audit-gate")
    import json
    data = json.loads(out)
    issues = [i for i in data.get("data", {}).get("issues", []) if i.get("rule") == "audit-gate"]
    # Expect: one error for missing conformance, one info for important findings.
    errors = [i for i in issues if i.get("severity") == "error"]
    infos = [i for i in issues if i.get("severity") == "info"]
    assert len(errors) == 1
    assert "ZERO" in errors[0]["message"] and "conformance" in errors[0]["message"]
    assert len(infos) == 1
    assert "IMPORTANT" in infos[0]["message"]


def test_audit_gate_surfaces_important_findings_as_info(tmp_vault):
    """Unresolved IMPORTANT findings should surface as info-severity issues
    (advisory), not block save."""
    _write_audit_findings(tmp_vault, {
        "runs": [
            {
                "mode": "conformance",
                "timestamp": "2026-04-14T10:00:00Z",
                "status": "pass",
                "criticals": [],
                "important": [
                    {"id": "I1", "description": "Proportional depth uneven", "fixed_at": None},
                    {"id": "I2", "description": "Citation to unfetched source", "fixed_at": None},
                ],
                "minor": [],
            }
        ]
    })
    _, out = _run_lint(tmp_vault, rule="audit-gate")
    import json
    data = json.loads(out)
    issues = [i for i in data.get("data", {}).get("issues", []) if i.get("rule") == "audit-gate"]
    errors = [i for i in issues if i.get("severity") == "error"]
    infos = [i for i in issues if i.get("severity") == "info"]
    assert errors == []  # save is NOT blocked by IMPORTANT alone
    assert len(infos) == 1
    assert "2 unresolved IMPORTANT" in infos[0]["message"]


def test_audit_gate_catches_self_certification_on_provenance(tmp_vault):
    """Regression test: when a CRITICAL finding mentions provenance AND is
    marked `fixed_at`, but the provenance rule still returns errors, the
    audit-gate must emit a SELF-CERTIFICATION VIOLATION error.

    This is exactly the Q62 failure mode — the agent marked the C1
    provenance finding as fixed with a justification string, but the
    vault's actual breadcrumb graph was still broken.
    """
    # Build a vault where provenance is genuinely broken (12 sources, none
    # with breadcrumbs — classic flat batch).
    for i in range(12):
        _write_source(tmp_vault, f"Source {i}", f"source-{i}")
    tmp_vault.auto_sync()

    # Audit findings file: conformance run with a CRITICAL marked fixed_at
    # that references provenance. The "fix" is a lie — the vault still fails
    # the provenance rule.
    _write_audit_findings(tmp_vault, {
        "runs": [
            {
                "mode": "conformance",
                "timestamp": "2026-04-14T20:00:00Z",
                "status": "pass",
                "criticals": [
                    {
                        "id": "C1",
                        "description": "Provenance chain broken — no --suggested-by breadcrumbs in corpus",
                        "fixed_at": "2026-04-14T20:20:00Z",
                    }
                ],
                "important": [],
                "minor": [],
            }
        ]
    })

    _, out = _run_lint(tmp_vault, rule="audit-gate")
    import json
    data = json.loads(out)
    issues = data.get("data", {}).get("issues", [])
    audit_errors = [
        i for i in issues
        if i.get("rule") == "audit-gate" and i.get("severity") == "error"
    ]
    self_cert_errors = [
        i for i in audit_errors if "SELF-CERTIFICATION VIOLATION" in i["message"]
    ]
    assert len(self_cert_errors) == 1, f"expected self-cert violation, got: {audit_errors}"
    assert "C1" in self_cert_errors[0]["message"]
    assert "provenance" in self_cert_errors[0]["message"]


def test_audit_gate_no_self_cert_when_fix_genuinely_landed(tmp_vault):
    """Control: when CRITICAL fixed_at IS set AND the underlying lint rule
    genuinely passes, the audit-gate should NOT emit a self-cert violation."""
    # Build a vault where provenance is healthy (seed + 6 non-seeds, all
    # pointing at real notes).
    _write_source(tmp_vault, "Seed", "seed-one")
    for i in range(6):
        _write_source(
            tmp_vault, f"Child {i}", f"child-{i}",
            body=f"*Suggested by [[seed-one]] — real*\n\nContent {i}"
        )
    tmp_vault.auto_sync()

    _write_audit_findings(tmp_vault, {
        "runs": [
            {
                "mode": "conformance",
                "timestamp": "2026-04-14T20:00:00Z",
                "status": "pass",
                "criticals": [
                    {
                        "id": "C1",
                        "description": "provenance was broken earlier",
                        "fixed_at": "2026-04-14T20:20:00Z",
                    }
                ],
                "important": [],
                "minor": [],
            }
        ]
    })

    _, out = _run_lint(tmp_vault, rule="audit-gate")
    import json
    data = json.loads(out)
    issues = data.get("data", {}).get("issues", [])
    self_cert_errors = [
        i for i in issues
        if i.get("rule") == "audit-gate" and "SELF-CERTIFICATION VIOLATION" in i.get("message", "")
    ]
    assert self_cert_errors == [], f"false-positive self-cert: {self_cert_errors}"


def test_audit_gate_handles_malformed_file(tmp_vault):
    audit_path = tmp_vault.root / "research" / "audit_findings.json"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path.write_text("{ not valid json }", encoding="utf-8")
    _, out = _run_lint(tmp_vault, rule="audit-gate")
    import json
    data = json.loads(out)
    issues = [i for i in data.get("data", {}).get("issues", []) if i.get("rule") == "audit-gate"]
    assert len(issues) == 1
    assert "malformed" in issues[0]["message"]


def test_orphaned_raw_files_ignores_matched_raw(tmp_vault):
    """Raw files whose stem matches a note id are not orphans."""
    write_note(
        tmp_vault.notes_dir,
        "PDF Note",
        note_id="real-pdf-note",
        source="https://example.com/paper.pdf",
        tier="ground_truth",
        content_type="paper",
        extra_frontmatter={"raw_file": "raw/real-pdf-note.pdf"},
    )
    raw_dir = tmp_vault.root / "research" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "real-pdf-note.pdf").write_bytes(b"%PDF-1.4 dummy")
    tmp_vault.auto_sync()

    _, out = _run_lint(tmp_vault, rule="orphaned-raw-files")
    import json
    data = json.loads(out)
    issues = [i for i in data.get("data", {}).get("issues", []) if i.get("rule") == "orphaned-raw-files"]
    assert issues == []



# ---------------------------------------------------------------------------
# locus-coverage (layercake Layer 3 — every locus must have an interim note)
# ---------------------------------------------------------------------------


def _write_loci_json(vault, loci: list[dict]) -> None:
    """Write research/loci.json so the locus-coverage rule has something to read."""
    import json
    research_dir = vault.root / "research"
    research_dir.mkdir(parents=True, exist_ok=True)
    (research_dir / "loci.json").write_text(
        json.dumps({"loci": loci}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_interim(vault, locus_name: str, note_id: str | None = None) -> None:
    """Write an interim-report note for a given locus. Mimics the Layer 3
    depth-investigator output shape: type=interim, tag=locus-<name>."""
    from hyperresearch.core.note import write_note
    nid = note_id or f"interim-{locus_name}"
    write_note(
        vault.notes_dir,
        f"Interim report {locus_name}",
        body="Interim synthesis for locus.",
        note_id=nid,
        tags=["interim", f"locus-{locus_name}"],
        note_type="interim",
    )


def test_locus_coverage_passes_when_every_locus_has_interim(tmp_vault):
    _write_loci_json(tmp_vault, [
        {"name": "alpha", "one_line": "Q1"},
        {"name": "beta",  "one_line": "Q2"},
    ])
    _write_interim(tmp_vault, "alpha")
    _write_interim(tmp_vault, "beta")
    tmp_vault.auto_sync()

    _, out = _run_lint(tmp_vault, rule="locus-coverage")
    import json
    data = json.loads(out)
    issues = [i for i in data.get("data", {}).get("issues", []) if i.get("rule") == "locus-coverage"]
    assert issues == []


def test_locus_coverage_flags_missing_interim(tmp_vault):
    _write_loci_json(tmp_vault, [
        {"name": "alpha", "one_line": "Q1"},
        {"name": "beta",  "one_line": "Q2"},
        {"name": "gamma", "one_line": "Q3"},
    ])
    # Only alpha got investigated; beta and gamma are orphans
    _write_interim(tmp_vault, "alpha")
    tmp_vault.auto_sync()

    _, out = _run_lint(tmp_vault, rule="locus-coverage")
    import json
    data = json.loads(out)
    issues = [i for i in data.get("data", {}).get("issues", []) if i.get("rule") == "locus-coverage"]
    assert len(issues) == 1
    msg = issues[0]["message"]
    assert "2 of 3" in msg
    assert "beta" in msg
    assert "gamma" in msg
    # 2 missing -> error severity (threshold at 2)
    assert issues[0]["severity"] == "error"


def test_locus_coverage_noop_when_no_loci_json(tmp_vault):
    """A vault from a single-pass /research run has no loci.json; the rule
    must stay silent in that case, not misfire."""
    _, out = _run_lint(tmp_vault, rule="locus-coverage")
    import json
    data = json.loads(out)
    issues = [i for i in data.get("data", {}).get("issues", []) if i.get("rule") == "locus-coverage"]
    assert issues == []


# ---------------------------------------------------------------------------
# patch-surgery (layercake Layer 6 — patcher must not skip critical findings)
# ---------------------------------------------------------------------------


def _write_patch_log(vault, applied=None, skipped=None, conflicts=None) -> None:
    import json
    research_dir = vault.root / "research"
    research_dir.mkdir(parents=True, exist_ok=True)
    (research_dir / "patch-log.json").write_text(
        json.dumps({
            "applied": applied or [],
            "skipped": skipped or [],
            "conflicts": conflicts or [],
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def test_patch_surgery_passes_with_clean_log(tmp_vault):
    _write_patch_log(tmp_vault, applied=[
        {"finding_id": 0, "severity": "critical", "critic": "dialectic", "chars_added": 87},
        {"finding_id": 1, "severity": "major",    "critic": "depth",     "chars_added": 54},
    ])
    _, out = _run_lint(tmp_vault, rule="patch-surgery")
    import json
    data = json.loads(out)
    issues = [i for i in data.get("data", {}).get("issues", []) if i.get("rule") == "patch-surgery"]
    assert issues == []


def test_patch_surgery_flags_critical_skip(tmp_vault):
    _write_patch_log(tmp_vault,
        applied=[
            {"finding_id": 0, "severity": "major", "critic": "depth", "chars_added": 50},
        ],
        skipped=[
            {"finding_id": 1, "severity": "critical", "critic": "dialectic",
             "reason": "anchor drifted"},
        ],
    )
    _, out = _run_lint(tmp_vault, rule="patch-surgery")
    import json
    data = json.loads(out)
    issues = [i for i in data.get("data", {}).get("issues", []) if i.get("rule") == "patch-surgery"]
    assert len(issues) == 1
    assert issues[0]["severity"] == "error"
    assert "1 critical" in issues[0]["message"]
    assert "dialectic" in issues[0]["message"]


def test_patch_surgery_flags_regeneration_attempt(tmp_vault):
    """The 500-char 'patch too large' guard catches critics trying to
    regenerate under the patch-only rule. Surfaces as a warning."""
    _write_patch_log(tmp_vault, skipped=[
        {"finding_id": 3, "severity": "major", "critic": "width",
         "reason": "patch too large (+612 chars)"},
    ])
    _, out = _run_lint(tmp_vault, rule="patch-surgery")
    import json
    data = json.loads(out)
    issues = [i for i in data.get("data", {}).get("issues", []) if i.get("rule") == "patch-surgery"]
    # Should see the "patch too large" warning (severity = warning, not error,
    # because the finding was major not critical)
    assert any(i.get("severity") == "warning" and "too large" in i["message"] for i in issues)


def test_patch_surgery_noop_when_no_patch_log(tmp_vault):
    """Single-pass /research runs produce no patch-log.json. Rule stays silent."""
    _, out = _run_lint(tmp_vault, rule="patch-surgery")
    import json
    data = json.loads(out)
    issues = [i for i in data.get("data", {}).get("issues", []) if i.get("rule") == "patch-surgery"]
    assert issues == []


# ---------------------------------------------------------------------------
# workflow — comparisons.md gate for layercake runs with 2+ loci
# ---------------------------------------------------------------------------


def test_workflow_flags_missing_comparisons_when_multiple_loci(tmp_vault):
    """2+ loci without research/comparisons.md is a Layer 3.5 skip — the
    insight-killing failure mode the cross-locus reconciliation step was
    added to prevent."""
    from hyperresearch.core.note import write_note
    # Layercake final-report signal
    write_note(
        tmp_vault.notes_dir,
        "final_report",
        body="Some draft content.",
        note_id="final_report",
        tags=["synthesis"],
    )
    # Scaffold artifact so the scaffold check passes
    (tmp_vault.root / "research" / "scaffold.md").write_text(
        "scaffold\n", encoding="utf-8"
    )
    # 2 loci, 2 interim notes — but NO comparisons.md
    _write_loci_json(tmp_vault, [
        {"name": "alpha", "one_line": "Q1"},
        {"name": "beta",  "one_line": "Q2"},
    ])
    _write_interim(tmp_vault, "alpha")
    _write_interim(tmp_vault, "beta")
    tmp_vault.auto_sync()

    _, out = _run_lint(tmp_vault, rule="workflow")
    import json
    data = json.loads(out)
    issues = [
        i for i in data.get("data", {}).get("issues", [])
        if i.get("rule") == "workflow"
    ]
    comparisons_issues = [i for i in issues if "comparisons.md" in i["message"]]
    assert len(comparisons_issues) == 1
    assert comparisons_issues[0]["severity"] == "error"
    assert "2 loci" in comparisons_issues[0]["message"]
    assert "Layer 3.5" in comparisons_issues[0]["message"]


def test_workflow_passes_with_comparisons_md(tmp_vault):
    """With comparisons.md present alongside 2+ loci, workflow rule stays silent."""
    from hyperresearch.core.note import write_note
    write_note(
        tmp_vault.notes_dir,
        "final_report",
        body="Draft.",
        note_id="final_report",
        tags=["synthesis"],
    )
    (tmp_vault.root / "research" / "scaffold.md").write_text(
        "scaffold\n", encoding="utf-8"
    )
    (tmp_vault.root / "research" / "comparisons.md").write_text(
        "# Cross-locus comparisons\n\n## Tension 1\n...", encoding="utf-8"
    )
    _write_loci_json(tmp_vault, [
        {"name": "alpha", "one_line": "Q1"},
        {"name": "beta",  "one_line": "Q2"},
    ])
    _write_interim(tmp_vault, "alpha")
    _write_interim(tmp_vault, "beta")
    tmp_vault.auto_sync()

    _, out = _run_lint(tmp_vault, rule="workflow")
    import json
    data = json.loads(out)
    issues = [
        i for i in data.get("data", {}).get("issues", [])
        if i.get("rule") == "workflow" and "comparisons.md" in i["message"]
    ]
    assert issues == []


def test_workflow_skips_comparisons_gate_when_single_locus(tmp_vault):
    """1 locus → nothing to compare → comparisons.md legitimately absent."""
    from hyperresearch.core.note import write_note
    write_note(
        tmp_vault.notes_dir,
        "final_report",
        body="Draft.",
        note_id="final_report",
        tags=["synthesis"],
    )
    (tmp_vault.root / "research" / "scaffold.md").write_text(
        "scaffold\n", encoding="utf-8"
    )
    _write_loci_json(tmp_vault, [
        {"name": "alpha", "one_line": "Q1"},
    ])
    _write_interim(tmp_vault, "alpha")
    tmp_vault.auto_sync()

    _, out = _run_lint(tmp_vault, rule="workflow")
    import json
    data = json.loads(out)
    issues = [
        i for i in data.get("data", {}).get("issues", [])
        if i.get("rule") == "workflow" and "comparisons.md" in i["message"]
    ]
    assert issues == []


# ---------------------------------------------------------------------------
# provenance — layercake-aware: skip breadcrumb coverage ratio checks when
# research/loci.json exists (layercake's fetch pattern is not bouncing-loop)
# ---------------------------------------------------------------------------


def test_provenance_skips_coverage_ratio_on_layercake_runs(tmp_vault):
    """A layercake run with many flat-seed fetches should NOT fail provenance's
    coverage-ratio check. Structural invariants (seeds exist, no dangling) still
    enforced."""
    # 15 source notes, ALL seeds (no --suggested-by breadcrumbs) — would be
    # an instant failure under the old ensemble provenance rule.
    for i in range(15):
        _write_source(tmp_vault, f"Source {i}", f"source-{i}")
    # Add the layercake marker
    _write_loci_json(tmp_vault, [
        {"name": "alpha", "one_line": "Q"},
        {"name": "beta",  "one_line": "Q"},
    ])
    tmp_vault.auto_sync()

    _, out = _run_lint(tmp_vault, rule="provenance")
    import json
    data = json.loads(out)
    issues = [
        i for i in data.get("data", {}).get("issues", [])
        if i.get("rule") == "provenance" and i.get("severity") in ("error", "warning")
    ]
    # No ratio-based errors on layercake runs
    assert issues == [], f"expected no coverage issues on layercake, got: {issues}"


def test_provenance_still_fires_coverage_check_on_non_layercake_runs(tmp_vault):
    """Ensemble / single-pass runs (no loci.json) should still get the
    bouncing-loop coverage check — nothing about this fix changes that."""
    for i in range(15):
        _write_source(tmp_vault, f"Source {i}", f"source-{i}")
    # NO loci.json → non-layercake run
    tmp_vault.auto_sync()

    _, out = _run_lint(tmp_vault, rule="provenance")
    import json
    data = json.loads(out)
    issues = [
        i for i in data.get("data", {}).get("issues", [])
        if i.get("rule") == "provenance"
    ]
    # Old behavior: zero breadcrumbs on >5 sources = error
    assert any(i["severity"] == "error" for i in issues)


# ---------------------------------------------------------------------------
# locus-coverage — flag duplicate interim notes on the same locus
# ---------------------------------------------------------------------------


def test_locus_coverage_flags_duplicate_interim_notes(tmp_vault):
    """Q4 hit this: the technical-support-resistance locus had 3 interim
    notes instead of 1. Inflates source count and confuses critics."""
    _write_loci_json(tmp_vault, [
        {"name": "alpha", "one_line": "Q1"},
    ])
    _write_interim(tmp_vault, "alpha", note_id="interim-alpha-1")
    _write_interim(tmp_vault, "alpha", note_id="interim-alpha-2")
    _write_interim(tmp_vault, "alpha", note_id="interim-alpha-3")
    tmp_vault.auto_sync()

    _, out = _run_lint(tmp_vault, rule="locus-coverage")
    import json
    data = json.loads(out)
    issues = [
        i for i in data.get("data", {}).get("issues", [])
        if i.get("rule") == "locus-coverage"
    ]
    dup_issues = [i for i in issues if "duplicate" in i["message"]]
    assert len(dup_issues) == 1
    assert "alpha (3)" in dup_issues[0]["message"]
    assert dup_issues[0]["severity"] == "warning"


# ---------------------------------------------------------------------------
# patch-surgery — empty log vs real zero-apply distinction
# ---------------------------------------------------------------------------


def test_patch_surgery_flags_empty_log_with_findings_present(tmp_vault):
    """When critics returned findings and the draft exists, but the patch
    log is empty, the patcher's log was lost. Warn so the operator knows."""
    import json as _json
    # Draft exists
    notes_dir = tmp_vault.root / "research" / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)
    (notes_dir / "final_report.md").write_text("# Report\n\nBody.", encoding="utf-8")
    # Critic findings with 12 findings
    research = tmp_vault.root / "research"
    research.mkdir(parents=True, exist_ok=True)
    (research / "critic-findings-dialectic.json").write_text(
        _json.dumps({"findings": [{"severity": "major"} for _ in range(12)]}),
        encoding="utf-8",
    )
    # Empty stub patch log
    _write_patch_log(tmp_vault)

    _, out = _run_lint(tmp_vault, rule="patch-surgery")
    data = _json.loads(out)
    issues = [
        i for i in data.get("data", {}).get("issues", [])
        if i.get("rule") == "patch-surgery" and "log was almost certainly lost" in i["message"]
    ]
    assert len(issues) == 1
    assert issues[0]["severity"] == "warning"


def test_patch_surgery_empty_log_without_findings_is_silent(tmp_vault):
    """If no critic findings exist, an empty patch log is correct (nothing
    to apply), not a warning."""
    import json as _json
    _write_patch_log(tmp_vault)

    _, out = _run_lint(tmp_vault, rule="patch-surgery")
    data = _json.loads(out)
    issues = [
        i for i in data.get("data", {}).get("issues", [])
        if i.get("rule") == "patch-surgery"
    ]
    assert issues == []
