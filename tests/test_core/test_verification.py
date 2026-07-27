"""Phase-5 tests: cite-check, verification lints, independence, telemetry, verify."""

from __future__ import annotations

import json

import pytest

from hyperresearch.core.citecheck import (
    extract_pairs,
    parse_sources_section,
    sample_needs_llm,
    triage_pairs,
)
from hyperresearch.core.independence import canonical_url, compute_independence
from hyperresearch.core.runs import init_run, run_report_data, set_step, verify_run


@pytest.fixture
def cited_vault(seeded_vault):
    """Seeded vault + claims + a source row so citations resolve."""
    from hyperresearch.core.claims import ingest_claims_dir

    temp = seeded_vault.root / "research" / "temp"
    temp.mkdir(parents=True, exist_ok=True)
    (temp / "claims-python-async-patterns.json").write_text(json.dumps([
        {"claim": "Async improves throughput by 10x for network-bound workloads",
         "quoted_support": "async/await syntax enables concurrent I/O with a 10x gain",
         "numbers": ["10x"], "confidence": "high", "evidence_type": "empirical"},
    ]), encoding="utf-8")
    ingest_claims_dir(seeded_vault, vault_tag="cc-run")
    seeded_vault.db.execute(
        "INSERT OR IGNORE INTO sources (url, note_id, domain, fetched_at, provider, content_hash) "
        "VALUES ('https://example.com/async', 'python-async-patterns', 'example.com', '2026-01-01', 'test', 'x')"
    )
    seeded_vault.db.commit()
    return seeded_vault


class TestCiteCheckExtraction:
    def test_wikilink_pairs(self, cited_vault):
        report = "Async gives a 10x gain [[python-async-patterns]]. Rust is safe [[rust-ownership]]."
        pairs = extract_pairs(report, cited_vault.db)
        assert len(pairs) == 2
        assert pairs[0]["note_id"] == "python-async-patterns"
        assert pairs[0]["numbers"] == ["10"] or "10x" in pairs[0]["sentence"]

    def test_numbered_pairs_resolve_via_sources_section(self, cited_vault):
        report = (
            "Throughput improves 10x [1].\n\n"
            "## Sources\n[1] Python Async Patterns. https://example.com/async\n"
        )
        mapping = parse_sources_section(report, cited_vault.db)
        assert mapping["1"] == "python-async-patterns"
        pairs = extract_pairs(report, cited_vault.db)
        assert len(pairs) == 1
        assert pairs[0]["note_id"] == "python-async-patterns"

    def test_grouped_citation_pairs_split_per_source(self, cited_vault):
        report = (
            "Throughput improves 10x under load [1, 2].\n\n"
            "## Sources\n[1] Python Async Patterns. https://example.com/async\n"
            "[2] Unrelated Study. https://example.com/other\n"
        )
        pairs = extract_pairs(report, cited_vault.db)
        assert len(pairs) == 2
        assert pairs[0]["note_id"] == "python-async-patterns"
        assert pairs[1]["note_id"] is None

    def test_dangling_citation_detected(self, cited_vault):
        report = "A bold claim [[no-such-note]]."
        pairs = extract_pairs(report, cited_vault.db)
        assert pairs[0]["note_id"] is None
        triaged = triage_pairs(pairs, cited_vault.db)
        assert triaged["dangling"] == 1

    def test_triage_auto_passes_number_match(self, cited_vault):
        pairs = extract_pairs(
            "Async improves throughput by 10x [[python-async-patterns]].", cited_vault.db
        )
        triaged = triage_pairs(pairs, cited_vault.db)
        assert triaged["supported_mechanical"] == 1
        assert triaged["needs_llm"] == 0

    def test_triage_flags_unsupported_for_llm(self, cited_vault):
        pairs = extract_pairs(
            "Async cures all database contention problems entirely [[python-async-patterns]].",
            cited_vault.db,
        )
        triaged = triage_pairs(pairs, cited_vault.db)
        assert triaged["needs_llm"] == 1

    def test_sampling_keeps_all_strong(self):
        pairs = [
            {"verdict": "needs-llm", "strong": True, "sentence": f"s{i}", "numbers": ["5"]}
            for i in range(5)
        ] + [
            {"verdict": "needs-llm", "strong": False, "sentence": f"w{i}", "numbers": []}
            for i in range(10)
        ]
        sampled = sample_needs_llm(pairs, sample_rate=0.5)
        strong = [p for p in sampled if p["strong"]]
        weak = [p for p in sampled if not p["strong"]]
        assert len(strong) == 5      # 100% of number-bearing
        assert len(weak) == 5        # every 2nd weak pair

    def test_citecheck_cli(self, cited_vault, monkeypatch):
        from typer.testing import CliRunner

        from hyperresearch.cli import app

        init_run(cited_vault, "cc-run")
        report = cited_vault.root / "research" / "notes" / "final_report_cc-run.md"
        report.write_text(
            "Async improves throughput by 10x [[python-async-patterns]]. "
            "Also a dangling one [[ghost-note]].",
            encoding="utf-8",
        )
        monkeypatch.chdir(cited_vault.root)
        runner = CliRunner()
        r = runner.invoke(app, ["citecheck", "extract", "cc-run", "--json"])
        assert r.exit_code == 0
        data = json.loads(r.stdout)["data"]
        assert data["summary"]["supported_mechanical"] == 1
        assert data["dangling"] == 1
        assert (cited_vault.run_dir("cc-run") / "cite-check-pairs.json").exists()


class TestVerificationLints:
    def _lint(self, vault, rule, monkeypatch):
        from typer.testing import CliRunner

        from hyperresearch.cli import app

        monkeypatch.chdir(vault.root)
        r = CliRunner().invoke(app, ["lint", "--rule", rule, "--json"])
        return json.loads(r.stdout)

    def test_quote_integrity_catches_fabrication(self, seeded_vault, monkeypatch):
        report = seeded_vault.root / "research" / "notes" / "final_report_q.md"
        report.write_text(
            'The paper concludes that "quantum entanglement reverses causality in every measurable frame of reference".',
            encoding="utf-8",
        )
        payload = self._lint(seeded_vault, "quote-integrity", monkeypatch)
        issues = [i for i in payload["data"]["issues"] if i["rule"] == "quote-integrity"]
        assert len(issues) == 1
        assert issues[0]["severity"] == "error"

    def test_quote_integrity_passes_real_quote(self, seeded_vault, monkeypatch):
        report = seeded_vault.root / "research" / "notes" / "final_report_q.md"
        # This sentence exists verbatim in the seeded python-async-patterns note
        report.write_text(
            'As the note says, "Python\'s async/await syntax enables concurrent I/O" today.',
            encoding="utf-8",
        )
        payload = self._lint(seeded_vault, "quote-integrity", monkeypatch)
        issues = [i for i in payload["data"]["issues"] if i["rule"] == "quote-integrity"]
        assert issues == []

    def test_numeric_consistency_flags_untraceable(self, cited_vault, monkeypatch):
        report = cited_vault.root / "research" / "notes" / "final_report_n.md"
        report.write_text("Revenue grew 47.3% while costs fell 1,234,567 dollars.", encoding="utf-8")
        payload = self._lint(cited_vault, "numeric-consistency", monkeypatch)
        issues = [i for i in payload["data"]["issues"] if i["rule"] == "numeric-consistency"]
        assert len(issues) == 2
        assert all(i["severity"] == "warning" for i in issues)

    def test_retracted_citation_blocks_unless_marked(self, seeded_vault, monkeypatch):
        conn = seeded_vault.db
        conn.execute("UPDATE notes SET is_retracted = 1 WHERE id = 'rust-ownership'")
        conn.commit()
        report = seeded_vault.root / "research" / "notes" / "final_report_r.md"
        report.write_text("Rust guarantees safety [[rust-ownership]].", encoding="utf-8")
        payload = self._lint(seeded_vault, "retracted-citations", monkeypatch)
        issues = [i for i in payload["data"]["issues"] if i["rule"] == "retracted-citations"]
        assert len(issues) == 1 and issues[0]["severity"] == "error"

        # Acknowledged retraction passes
        report.write_text(
            "One early study claimed safety guarantees [[rust-ownership]] (retracted 2025).",
            encoding="utf-8",
        )
        payload = self._lint(seeded_vault, "retracted-citations", monkeypatch)
        issues = [i for i in payload["data"]["issues"] if i["rule"] == "retracted-citations"]
        assert issues == []


class TestIndependence:
    def test_canonical_url(self):
        assert canonical_url("https://www.Example.com/a/?utm_source=x") == canonical_url("http://example.com/a")

    def test_wire_cluster_discounts_members(self, tmp_vault):
        from hyperresearch.core.note import write_note
        from hyperresearch.core.sync import compute_sync_plan, execute_sync

        pr = "NEW YORK, PRNewswire — MegaCorp announces quantum widget breakthrough today."
        for i, (title, when) in enumerate([("MegaCorp Breakthrough", "2026-01-01"),
                                           ("MegaCorp Announces Widget", "2026-01-02"),
                                           ("Quantum Widget from MegaCorp", "2026-01-03")]):
            write_note(
                tmp_vault.notes_dir, title, body=pr + f" Outlet {i} adds a sentence.",
                source=f"https://outlet{i}.com/story", tags=["ind-run"],
                extra_frontmatter={"created": when + "T00:00:00+00:00"},
            )
        write_note(
            tmp_vault.notes_dir, "Independent Analysis",
            body="A genuinely independent, differently-worded long analysis of quantum widgets and their many limitations in practice.",
            source="https://analyst.com/deep-dive", tags=["ind-run"],
        )
        plan = compute_sync_plan(tmp_vault, force=True)
        execute_sync(tmp_vault, plan)

        result = compute_independence(tmp_vault, tag="ind-run")
        assert len(result["clusters"]) == 1
        cluster = result["clusters"][0]
        assert cluster["size"] == 3
        assert "wire" in cluster["kind"]

        scores = {r["id"]: r["independence"] for r in tmp_vault.db.execute(
            "SELECT id, independence FROM notes WHERE independence IS NOT NULL"
        )}
        assert scores[cluster["root"]] == 1.0
        assert scores["independent-analysis"] == 1.0
        for member in cluster["members"]:
            assert scores[member] == pytest.approx(1 / 3, abs=0.001)

    def test_same_canonical_url_clusters(self, tmp_vault):
        from hyperresearch.core.note import write_note
        from hyperresearch.core.sync import compute_sync_plan, execute_sync

        write_note(tmp_vault.notes_dir, "Copy A", body="Some words here for the body.",
                   source="https://www.site.com/story?utm_source=feed")
        write_note(tmp_vault.notes_dir, "Copy B", body="Entirely different words in this body text.",
                   source="https://site.com/story/")
        plan = compute_sync_plan(tmp_vault, force=True)
        execute_sync(tmp_vault, plan)
        result = compute_independence(tmp_vault)
        assert any(c["kind"] == "url" for c in result["clusters"])


class TestCJKLengthCheck:
    """`str.split()` word counts collapse to near-zero for prose in scripts
    that don't delimit words with ASCII whitespace (Chinese, Japanese,
    Korean, Thai, ...), so a report that is squarely within its documented
    character-count target must not fail length-in-range on a spurious
    word count. The detector is a structural heuristic (average
    whitespace-delimited token length), not a hardcoded script allowlist --
    it must generalize to any such script without code changes."""

    def test_lacks_word_boundaries(self):
        from hyperresearch.core.runs import _lacks_word_boundaries

        # Japanese (kana + kanji) and Chinese (hanzi) prose is written with
        # no spaces between words at all.
        assert _lacks_word_boundaries("この文章はほぼ全て日本語の文字で構成されています。")
        assert _lacks_word_boundaries("这是一段中文测试文本内容和证据。")
        # Structural-only proof of generality to a non-CJK, non-Latin
        # script family (Thai) -- no claim about grammaticality, just that
        # a long run of a spaceless script's characters trips the same
        # heuristic without any script-specific code.
        assert _lacks_word_boundaries("คำ" * 30)
        # Korean is the counter-example that justifies a *structural*
        # heuristic over a hardcoded script list: unlike Chinese/Japanese,
        # modern Korean orthography IS space-delimited, so str.split()
        # word counts are meaningful for it and it must NOT trip this
        # branch. A script-identity allowlist would get this wrong.
        assert not _lacks_word_boundaries(
            "이것은 한국어 문장으로 구성된 테스트입니다 그리고 띄어쓰기를 사용합니다."
        )
        assert not _lacks_word_boundaries(
            "This paragraph is entirely English prose with no CJK content at all."
        )
        # A handful of long wikilink citation keys inside a mostly-English
        # report should not trip the branch -- many short real words still
        # dominate the average token length.
        assert not _lacks_word_boundaries(
            "This is an English report with real citations. "
            "[[dagitty-a-graphical-tool-for-analyzing-causal-diagrams-semantic-scholar]] " * 15
        )

    def test_verify_passes_cjk_report_within_char_target_despite_low_word_count(
        self, tmp_vault
    ):
        init_run(tmp_vault, "cjk-01", profile="light")
        run_dir = tmp_vault.run_dir("cjk-01")
        (run_dir / "prompt-decomposition.json").write_text(json.dumps({
            "response_format": "short",
            "required_section_headings": ["## 結果"],
        }), encoding="utf-8")
        (run_dir / "polish-log.json").write_text('{"applied": []}', encoding="utf-8")
        # light/short CJK char target is 1500-6000; this Japanese sentence
        # has almost no ASCII whitespace, so str.split() would count only a
        # handful of "words" despite being solidly in-range by characters.
        sentence = "これは実質的な証拠を伴う文章である[[src-note]]。"
        report = tmp_vault.root / "research" / "notes" / "final_report_cjk-01.md"
        body = "## 結果\n\n" + (sentence * 90)
        report.write_text(body, encoding="utf-8")

        word_count = len(body.split())
        assert word_count < 500  # would fail the English word-count target

        result = verify_run(tmp_vault, "cjk-01")
        by_name = {c["name"]: c for c in result["checks"]}
        assert by_name["length-in-range"]["ok"] is True
        assert "chars" in by_name["length-in-range"]["detail"]
        assert result["passed"] is True

    def test_verify_still_fails_cjk_report_far_outside_char_target(self, tmp_vault):
        init_run(tmp_vault, "cjk-02", profile="light")
        run_dir = tmp_vault.run_dir("cjk-02")
        (run_dir / "prompt-decomposition.json").write_text(json.dumps({
            "response_format": "short",
            "required_section_headings": ["## 結果"],
        }), encoding="utf-8")
        # Well under the 1500-char floor (even with the 20% tolerance) --
        # the CJK branch must still be a real length check, not a bypass.
        report = tmp_vault.root / "research" / "notes" / "final_report_cjk-02.md"
        report.write_text("## 結果\n\n短い。", encoding="utf-8")

        result = verify_run(tmp_vault, "cjk-02")
        by_name = {c["name"]: c for c in result["checks"]}
        assert by_name["length-in-range"]["ok"] is False
        assert result["passed"] is False

    def test_verify_respects_profile_override_for_non_cjk_script(self, tmp_vault):
        """End-to-end proof that a deployment serving a non-CJK,
        non-word-boundary script (simulated here with a spaceless Thai-script
        blob) is not stuck with CJK-calibrated numbers: it configures its own
        char_targets_no_word_boundary via the standard profile-overlay
        mechanism, and verify_run honors it -- no code change needed to
        support a script this project has no real usage data for."""
        cfg_dir = tmp_vault.root / ".hyperresearch"
        cfg_dir.mkdir(parents=True, exist_ok=True)
        (cfg_dir / "config.toml").write_text(
            "[profile.light]\n"
            "char_targets_no_word_boundary = { short = [300, 900] }\n",
            encoding="utf-8",
        )
        init_run(tmp_vault, "th-01", profile="light")
        run_dir = tmp_vault.run_dir("th-01")
        (run_dir / "prompt-decomposition.json").write_text(json.dumps({
            "response_format": "short",
            "required_section_headings": ["## Results"],
        }), encoding="utf-8")
        (run_dir / "polish-log.json").write_text('{"applied": []}', encoding="utf-8")
        # A spaceless Thai-script blob: within the overridden 300-900 char
        # target, but far below the shipped CJK default's 1500-char floor --
        # this only passes if the override is actually being read.
        report = tmp_vault.root / "research" / "notes" / "final_report_th-01.md"
        report.write_text("## Results\n\n" + ("คำ" * 250), encoding="utf-8")

        result = verify_run(tmp_vault, "th-01")
        by_name = {c["name"]: c for c in result["checks"]}
        assert by_name["length-in-range"]["ok"] is True
        assert "300-900" in by_name["length-in-range"]["detail"]


class TestTelemetryAndVerify:
    def test_run_report_rollup(self, tmp_vault):
        init_run(tmp_vault, "tel-01", profile="light")
        set_step(tmp_vault, "tel-01", "1", "running")
        set_step(tmp_vault, "tel-01", "1", "done")
        report = run_report_data(tmp_vault, "tel-01")
        step1 = next(s for s in report["steps"] if s["step"] == "1")
        assert step1["status"] == "done"
        assert step1["minutes"] is not None
        assert report["events"]["step"] >= 2

    def test_verify_passes_well_formed_light_run(self, tmp_vault):
        init_run(tmp_vault, "vf-01", profile="light")
        run_dir = tmp_vault.run_dir("vf-01")
        (run_dir / "prompt-decomposition.json").write_text(json.dumps({
            "response_format": "short",
            "required_section_headings": ["## Findings"],
        }), encoding="utf-8")
        (run_dir / "polish-log.json").write_text('{"applied": []}', encoding="utf-8")
        report = tmp_vault.root / "research" / "notes" / "final_report_vf-01.md"
        body = "## Findings\n\n" + ("Substantive sentence with real evidence attached [[src-note]]. " * 80)
        report.write_text(body, encoding="utf-8")

        result = verify_run(tmp_vault, "vf-01")
        by_name = {c["name"]: c for c in result["checks"]}
        assert by_name["report-exists"]["ok"]
        assert by_name["required-headings"]["ok"]
        assert by_name["length-in-range"]["ok"]
        assert by_name["citation-density"]["ok"]
        assert result["passed"] is True

    def test_verify_density_counts_each_grouped_source(self, tmp_vault):
        init_run(tmp_vault, "vf-04", profile="light")
        run_dir = tmp_vault.run_dir("vf-04")
        (run_dir / "prompt-decomposition.json").write_text(json.dumps({
            "response_format": "short",
            "required_section_headings": ["## Findings"],
        }), encoding="utf-8")
        report = tmp_vault.root / "research" / "notes" / "final_report_vf-04.md"
        filler = "Substantive analysis continues with replicated evidence in view. " * 11
        block = filler + "The consensus across measurements holds [1, 2, 3]. "
        report.write_text("## Findings\n\n" + block * 8, encoding="utf-8")

        result = verify_run(tmp_vault, "vf-04")
        by_name = {c["name"]: c for c in result["checks"]}
        # One bracket per ~770 chars sits under the 1.5/1000 floor; the three
        # sources inside each grouped bracket clear it. Counting markers
        # instead of cited-source numbers would fail this check.
        assert by_name["citation-density"]["ok"]

    def test_verify_fails_on_missing_heading_and_report(self, tmp_vault):
        init_run(tmp_vault, "vf-02", profile="light")
        result = verify_run(tmp_vault, "vf-02")
        assert result["passed"] is False

    def test_verify_cli_exit_code(self, tmp_vault, monkeypatch):
        from typer.testing import CliRunner

        from hyperresearch.cli import app

        init_run(tmp_vault, "vf-03", profile="light")
        monkeypatch.chdir(tmp_vault.root)
        r = CliRunner().invoke(app, ["run", "verify", "vf-03", "--json"])
        assert r.exit_code == 1  # no report -> fail


class TestFinishGate:
    """`run finish` is the terminal gate: it must be impossible to reach
    status "done" past a failing check, and the two Q62 failure modes
    (hallucinated quotes assessed away, length gate never run) must now be
    mechanically blocking."""

    def _well_formed_light_run(self, tmp_vault, tag: str, body: str | None = None):
        init_run(tmp_vault, tag, profile="light")
        run_dir = tmp_vault.run_dir(tag)
        (run_dir / "prompt-decomposition.json").write_text(json.dumps({
            "response_format": "short",
            "required_section_headings": ["## Findings"],
        }), encoding="utf-8")
        (run_dir / "polish-log.json").write_text('{"applied": []}', encoding="utf-8")
        report = tmp_vault.root / "research" / "notes" / f"final_report_{tag}.md"
        if body is None:
            body = "## Findings\n\n" + (
                "Substantive sentence with real evidence attached [[src-note]]. " * 80
            )
        report.write_text(body, encoding="utf-8")
        return report

    def test_finish_marks_clean_run_done(self, tmp_vault):
        from hyperresearch.core.runs import finish_run, load_manifest

        self._well_formed_light_run(tmp_vault, "fin-01")
        result = finish_run(tmp_vault, "fin-01")
        assert result["verify"]["passed"] is True
        manifest = load_manifest(tmp_vault, "fin-01")
        assert manifest["status"] == "done"
        assert manifest["blocked_on"] is None
        assert manifest["verify"]["passed"] is True
        assert manifest["verify"]["failed_checks"] == []

    def test_finish_blocks_hallucinated_quote(self, tmp_vault):
        from hyperresearch.core.runs import finish_run, load_manifest

        body = "## Findings\n\n" + (
            "Substantive sentence with real evidence attached [[src-note]]. " * 80
        ) + '\n\nAs one expert put it, "this quotation was never fetched into any vault note anywhere."\n'
        self._well_formed_light_run(tmp_vault, "fin-02", body=body)
        result = finish_run(tmp_vault, "fin-02")
        assert result["verify"]["passed"] is False
        by_name = {c["name"]: c for c in result["verify"]["checks"]}
        assert by_name["quote-integrity"]["ok"] is False
        manifest = load_manifest(tmp_vault, "fin-02")
        assert manifest["status"] == "blocked"
        assert manifest["blocked_on"] == "verify"
        assert "quote-integrity" in manifest["verify"]["failed_checks"]

    def test_finish_blocks_over_length_report(self, tmp_vault):
        from hyperresearch.core.runs import finish_run, load_manifest

        # light/short target is 500-2000 words; 20% tolerance caps at 2400.
        body = "## Findings\n\n" + (
            "Substantive sentence with real evidence attached [[src-note]]. " * 500
        )
        self._well_formed_light_run(tmp_vault, "fin-03", body=body)
        result = finish_run(tmp_vault, "fin-03")
        assert result["verify"]["passed"] is False
        by_name = {c["name"]: c for c in result["verify"]["checks"]}
        assert by_name["length-in-range"]["ok"] is False
        manifest = load_manifest(tmp_vault, "fin-03")
        assert manifest["status"] == "blocked"
        assert manifest["blocked_on"] == "verify"

    def test_finish_then_fix_then_done(self, tmp_vault):
        """The intended loop: blocked -> fix the report -> finish passes."""
        from hyperresearch.core.runs import finish_run, load_manifest

        body = "## Findings\n\n" + (
            "Substantive sentence with real evidence attached [[src-note]]. " * 80
        ) + '\n\nAs one expert put it, "this quotation was never fetched into any vault note anywhere."\n'
        report = self._well_formed_light_run(tmp_vault, "fin-04", body=body)
        assert finish_run(tmp_vault, "fin-04")["verify"]["passed"] is False

        # The prescribed fix: drop the quotation marks, not the gate.
        fixed = report.read_text(encoding="utf-8").replace(
            '"this quotation was never fetched into any vault note anywhere."',
            "this claim stands as the report's own framing.",
        )
        report.write_text(fixed, encoding="utf-8")
        assert finish_run(tmp_vault, "fin-04")["verify"]["passed"] is True
        assert load_manifest(tmp_vault, "fin-04")["status"] == "done"

    def test_finish_cli_exit_code(self, tmp_vault, monkeypatch):
        from typer.testing import CliRunner

        from hyperresearch.cli import app

        init_run(tmp_vault, "fin-05", profile="light")
        monkeypatch.chdir(tmp_vault.root)
        r = CliRunner().invoke(app, ["run", "finish", "fin-05", "--json"])
        assert r.exit_code == 1  # no report -> gate fails -> blocked
        from hyperresearch.core.runs import load_manifest

        assert load_manifest(tmp_vault, "fin-05")["status"] == "blocked"

    def test_verify_includes_content_gates(self, tmp_vault):
        """verify_run itself must carry quote-integrity + retracted-citations
        checks — one command, whole verdict."""
        self._well_formed_light_run(tmp_vault, "fin-06")
        result = verify_run(tmp_vault, "fin-06")
        names = {c["name"] for c in result["checks"]}
        assert "quote-integrity" in names
        assert "retracted-citations" in names

    def test_cite_check_findings_accepts_both_shapes(self, tmp_vault):
        """The pipeline writes {"findings": [...]}; verify must not crash on
        it (it did, on the first live gate run) and must still resolve
        criticals for the bare-list shape."""
        from hyperresearch.core.runs import set_step

        for tag, payload in (
            ("fin-07", {"findings": [{"severity": "critical", "verdict": "unsupported"}]}),
            ("fin-08", [{"severity": "critical", "verdict": "unsupported"}]),
        ):
            self._well_formed_light_run(tmp_vault, tag)
            run_dir = tmp_vault.run_dir(tag)
            set_step(tmp_vault, tag, "14.5", "done")
            (run_dir / "cite-check-findings.json").write_text(
                json.dumps(payload), encoding="utf-8"
            )
            result = verify_run(tmp_vault, tag)  # must not raise
            by_name = {c["name"]: c for c in result["checks"]}
            # A critical finding with no patch log fails the check cleanly.
            assert by_name["cite-check-resolved"]["ok"] is False
            (run_dir / "cite-check-patch-log.json").write_text("[]", encoding="utf-8")
            result = verify_run(tmp_vault, tag)
            by_name = {c["name"]: c for c in result["checks"]}
            assert by_name["cite-check-resolved"]["ok"] is True


class TestCiteCheckerAgentInstall:
    def test_agent_installs(self, tmp_vault):
        from hyperresearch.core.hooks import _install_cite_checker_agent

        result = _install_cite_checker_agent(tmp_vault.root, "hyperresearch")
        assert result is not None
        body = (tmp_vault.root / ".claude" / "agents" / "hyperresearch-cite-checker.md").read_text(encoding="utf-8")
        assert "name: hyperresearch-cite-checker" in body
        assert "model: sonnet" in body
        assert "wrong-source" in body
        assert "SKEPTICAL" in body
        assert "{hpr_path}" not in body
        assert "<<" not in body
