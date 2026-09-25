"""Phase-3 tests: per-run workspaces, run manifest, resume, budget governor."""

from __future__ import annotations

import json

import pytest

from hyperresearch.core import runs as runs_mod
from hyperresearch.core.runs import (
    RunError,
    add_spend,
    init_run,
    list_runs,
    load_manifest,
    resume_position,
    run_resume_position,
    set_step,
    status_summary,
)


class TestRunInit:
    def test_scaffolds_workspace(self, tmp_vault):
        manifest = init_run(tmp_vault, "topic-abc123", profile="full", query="What is X?")
        run_dir = tmp_vault.run_dir("topic-abc123")
        assert (run_dir / "run.json").exists()
        assert (run_dir / "temp").is_dir()
        assert (run_dir / "query.md").read_text(encoding="utf-8") == "What is X?"
        assert manifest["status"] == "running"
        assert manifest["profile_steps"][0] == "1"
        assert manifest["profile_steps"][-1] == "16"

    def test_idempotent_reinit(self, tmp_vault):
        first = init_run(tmp_vault, "topic-abc123", profile="light")
        set_step(tmp_vault, "topic-abc123", "1", "done")
        again = init_run(tmp_vault, "topic-abc123", profile="full")  # different args ignored
        assert again["profile"] == "light"  # original manifest wins
        assert again["steps"]["1"]["status"] == "done"
        assert first["started_at"] == again["started_at"]

    def test_unknown_profile_rejected(self, tmp_vault):
        from hyperresearch.core.profiles import ProfileError

        with pytest.raises(ProfileError):
            init_run(tmp_vault, "topic-x", profile="bogus")

    def test_two_runs_are_disjoint(self, tmp_vault):
        init_run(tmp_vault, "alpha-111111")
        init_run(tmp_vault, "beta-222222")
        set_step(tmp_vault, "alpha-111111", "2", "done")
        beta = load_manifest(tmp_vault, "beta-222222")
        assert "2" not in beta["steps"]
        assert len(list_runs(tmp_vault)) == 2


class TestStepsAndResume:
    def test_step_transitions_and_resume(self, tmp_vault):
        init_run(tmp_vault, "t-000001", profile="light")
        set_step(tmp_vault, "t-000001", "1", "done")
        set_step(tmp_vault, "t-000001", "2", "done")
        manifest = load_manifest(tmp_vault, "t-000001")
        pos = resume_position(manifest)
        # light steps: 1,2,10,15,16
        assert pos["next_step"] == "10"
        assert pos["done_steps"] == ["1", "2"]
        assert pos["remaining_steps"] == ["10", "15", "16"]

    def test_fractional_and_chapter_steps(self, tmp_vault):
        init_run(tmp_vault, "t-000002", profile="dissertation")
        set_step(tmp_vault, "t-000002", "1", "done")
        set_step(tmp_vault, "t-000002", "1.5", "done")
        set_step(tmp_vault, "t-000002", "2", "done", chapter="ch1")
        manifest = load_manifest(tmp_vault, "t-000002")
        assert manifest["steps"]["1.5"]["status"] == "done"
        assert manifest["steps"]["2"]["chapter"] == "ch1"
        assert "ch1" in manifest["chapters"]

    def test_all_done_gives_none(self, tmp_vault):
        init_run(tmp_vault, "t-000003", profile="light")
        for s in ["1", "2", "10", "15", "16"]:
            set_step(tmp_vault, "t-000003", s, "done")
        assert resume_position(load_manifest(tmp_vault, "t-000003"))["next_step"] is None

    def test_declared_light_tier_resumes_past_skipped_steps(self, tmp_vault):
        """A full-gear run that step 1 classified `light` resumes at step 10,
        not at step 3 — the tier's step set wins, as in the ship gate."""
        init_run(tmp_vault, "t-000006", profile="full")
        (tmp_vault.run_dir("t-000006") / "prompt-decomposition.json").write_text(
            json.dumps({"pipeline_tier": "light"}), encoding="utf-8"
        )
        set_step(tmp_vault, "t-000006", "1", "done")
        set_step(tmp_vault, "t-000006", "2", "done")
        manifest = load_manifest(tmp_vault, "t-000006")
        pos = run_resume_position(tmp_vault, manifest)
        assert pos["next_step"] == "10"
        assert pos["remaining_steps"] == ["10", "15", "16"]
        assert status_summary(tmp_vault, "t-000006")["resume"]["next_step"] == "10"

    def test_no_declared_tier_keeps_profile_steps(self, tmp_vault):
        init_run(tmp_vault, "t-000007", profile="full")
        set_step(tmp_vault, "t-000007", "1", "done")
        set_step(tmp_vault, "t-000007", "2", "done")
        pos = run_resume_position(tmp_vault, load_manifest(tmp_vault, "t-000007"))
        assert pos["next_step"] == "3"

    def test_invalid_status_rejected(self, tmp_vault):
        init_run(tmp_vault, "t-000004")
        with pytest.raises(RunError, match="invalid step status"):
            set_step(tmp_vault, "t-000004", "1", "finished")

    def test_events_logged(self, tmp_vault):
        init_run(tmp_vault, "t-000005")
        set_step(tmp_vault, "t-000005", "1", "running")
        events_file = tmp_vault.run_dir("t-000005") / "events.jsonl"
        lines = events_file.read_text(encoding="utf-8").strip().splitlines()
        assert any(json.loads(ln)["type"] == "step" for ln in lines)


class TestBudgetGovernor:
    def test_spend_accumulates(self, tmp_vault):
        init_run(tmp_vault, "b-000001", budget_usd=100.0)
        add_spend(tmp_vault, "b-000001", estimated_usd=12.5, sources_fetched=30, agents_spawned=8)
        m = add_spend(tmp_vault, "b-000001", estimated_usd=7.5, sources_fetched=10)
        assert m["spend"]["estimated_usd"] == 20.0
        assert m["spend"]["sources_fetched"] == 40
        assert m["status"] == "running"

    def test_crossing_budget_blocks(self, tmp_vault):
        init_run(tmp_vault, "b-000002", budget_usd=10.0)
        m = add_spend(tmp_vault, "b-000002", estimated_usd=10.0)
        assert m["status"] == "blocked"
        assert m["blocked_on"] == "budget"
        summary = status_summary(tmp_vault, "b-000002")
        assert summary["budget_remaining_usd"] == 0.0

    def test_no_budget_never_blocks(self, tmp_vault):
        init_run(tmp_vault, "b-000003")
        m = add_spend(tmp_vault, "b-000003", estimated_usd=99999)
        assert m["status"] == "running"

    def test_resume_unblocks(self, tmp_vault, monkeypatch):
        from typer.testing import CliRunner

        from hyperresearch.cli import app

        init_run(tmp_vault, "b-000004", budget_usd=5.0)
        add_spend(tmp_vault, "b-000004", estimated_usd=6.0)
        monkeypatch.chdir(tmp_vault.root)
        runner = CliRunner()
        result = runner.invoke(app, ["run", "resume", "b-000004", "--json"])
        assert result.exit_code == 0
        assert load_manifest(tmp_vault, "b-000004")["status"] == "running"


class TestStatusSummary:
    def test_stall_detection(self, tmp_vault, monkeypatch):
        init_run(tmp_vault, "s-000001")
        summary = status_summary(tmp_vault, "s-000001")
        assert summary["possibly_stalled"] is False
        # Backdate the heartbeat
        m = load_manifest(tmp_vault, "s-000001")
        m["updated_at"] = "2020-01-01T00:00:00+00:00"
        mpath = runs_mod.manifest_path(tmp_vault, "s-000001")
        mpath.write_text(json.dumps(m), encoding="utf-8")
        assert status_summary(tmp_vault, "s-000001")["possibly_stalled"] is True

    def test_missing_run_errors(self, tmp_vault):
        with pytest.raises(RunError, match="no run"):
            status_summary(tmp_vault, "nope-000000")


class TestRunCli:
    def test_init_status_resume_roundtrip(self, tmp_vault, monkeypatch):
        from typer.testing import CliRunner

        from hyperresearch.cli import app

        monkeypatch.chdir(tmp_vault.root)
        runner = CliRunner()

        r = runner.invoke(app, ["run", "init", "cli-run-000001", "--profile", "light", "--budget", "50", "--json"])
        assert r.exit_code == 0

        r = runner.invoke(app, ["run", "step", "cli-run-000001", "1", "--status", "done", "--json"])
        assert r.exit_code == 0

        r = runner.invoke(app, ["run", "resume", "--json"])
        assert r.exit_code == 0
        data = json.loads(r.stdout)["data"]
        assert data["vault_tag"] == "cli-run-000001"
        assert data["next_step"] == "2"
        # The full installed slug, not a bare `hyperresearch-2` that the
        # Skill tool cannot resolve (#100).
        assert data["skill_to_invoke"] == "hyperresearch-2-width-sweep"

        r = runner.invoke(app, ["run", "abort", "cli-run-000001", "--json"])
        assert r.exit_code == 0
        assert json.loads(r.stdout)["data"]["status"] == "aborted"

    def test_resume_maps_fractional_step_to_skill(self, tmp_vault, monkeypatch):
        from typer.testing import CliRunner

        from hyperresearch.cli import app

        monkeypatch.chdir(tmp_vault.root)
        runner = CliRunner()
        runner.invoke(app, ["run", "init", "dis-run-000001", "--profile", "dissertation", "--json"])
        # Manifest profile_steps for dissertation are 1..16; mark 1 done and
        # verify the mapping convention for step ids with dots.
        runner.invoke(app, ["run", "step", "dis-run-000001", "1", "--status", "done", "--json"])
        r = runner.invoke(app, ["run", "status", "dis-run-000001", "--json"])
        payload = json.loads(r.stdout)["data"]
        assert payload["profile"] == "dissertation"

        # The slug map must know the half-steps too — the old string
        # substitution spelled them `hyperresearch-1-5` / `hyperresearch-14-5`.
        from hyperresearch.core.hooks import step_skill_slug

        assert step_skill_slug("1.5") == "hyperresearch-1-5-chapter-partition"
        assert step_skill_slug("14.5") == "hyperresearch-14-5-cite-check"
        assert step_skill_slug("2") == "hyperresearch-2-width-sweep"
        assert step_skill_slug(None) is None
        assert step_skill_slug("11g") is None
        r = runner.invoke(app, ["run", "resume", "dis-run-000001", "--json"])
        assert json.loads(r.stdout)["data"]["skill_to_invoke"] == "hyperresearch-2-width-sweep"

    def test_every_step_id_maps_to_a_shipped_skill(self, tmp_vault):
        """`run resume` must only ever suggest a skill the installer ships:
        every step id in every built-in profile (plus the half-steps 1.5 and
        14.5) maps to a slug whose source template exists under
        src/hyperresearch/skills/ and which installs as a skill directory."""
        from pathlib import Path

        import hyperresearch.skills as skills_pkg
        from hyperresearch.core.hooks import (
            STEP_SKILL_BY_ID,
            _install_hyperresearch_step_skills,
            step_skill_slug,
        )
        from hyperresearch.core.profiles import BUILTIN_PROFILES, resolve_profile

        skills_src = Path(skills_pkg.__file__).parent
        _install_hyperresearch_step_skills(tmp_vault.root)
        installed_root = tmp_vault.root / ".claude" / "skills"

        wanted: set[str] = {"1.5", "14.5"}
        for name in BUILTIN_PROFILES:
            wanted.update(str(s) for s in resolve_profile(name).steps)
        for step_id in sorted(wanted, key=float):
            slug = step_skill_slug(step_id)
            assert slug, f"step {step_id} has no skill slug"
            assert (skills_src / f"{slug}.md").is_file(), f"{slug}.md missing from package"
            assert (installed_root / slug / "SKILL.md").is_file(), f"{slug} did not install"
        # And the map has no entries that don't correspond to a step id
        for step_id, slug in STEP_SKILL_BY_ID.items():
            assert step_id and all(part.isdigit() for part in step_id.split(".")), (step_id, slug)


class TestChapterRegistration:
    """Step 1.5 registers chapters by emitting `chapter-plan` events; the
    manifest must reflect them so a resumed dissertation run knows which
    chapters are still pending (#100)."""

    def _plan(self, vault, tag, *chapters):
        from hyperresearch.core.runs import record_event

        for cid, title in chapters:
            record_event(vault, tag, {"type": "chapter-plan", "chapter": cid, "title": title})

    def test_chapter_plan_event_registers_chapter(self, tmp_vault):
        init_run(tmp_vault, "ch-000001", profile="dissertation")
        set_step(tmp_vault, "ch-000001", "1", "done")
        self._plan(tmp_vault, "ch-000001", ("ch1", "Origins"), ("ch2", "Mechanisms"))
        set_step(tmp_vault, "ch-000001", "1.5", "done")

        manifest = load_manifest(tmp_vault, "ch-000001")
        assert manifest["chapters"]["ch1"] == {"status": "planned", "title": "Origins"}
        assert manifest["chapters"]["ch2"]["title"] == "Mechanisms"
        assert resume_position(manifest)["chapters_pending"] == ["ch1", "ch2"]

    def test_chapter_stays_pending_until_its_last_step(self, tmp_vault):
        init_run(tmp_vault, "ch-000002", profile="dissertation")
        self._plan(tmp_vault, "ch-000002", ("ch1", "Origins"), ("ch2", "Mechanisms"))
        # Finishing an early looped step must not retire the chapter.
        set_step(tmp_vault, "ch-000002", "2", "done", chapter="ch1")
        pos = resume_position(load_manifest(tmp_vault, "ch-000002"))
        assert pos["chapters_pending"] == ["ch1", "ch2"]
        # Step 10 is the last per-chapter step; done there closes the chapter.
        set_step(tmp_vault, "ch-000002", "10", "done", chapter="ch1")
        pos = resume_position(load_manifest(tmp_vault, "ch-000002"))
        assert pos["chapters_pending"] == ["ch2"]

    def test_replanning_never_regresses_progress(self, tmp_vault):
        init_run(tmp_vault, "ch-000003", profile="dissertation")
        self._plan(tmp_vault, "ch-000003", ("ch1", "Origins"))
        set_step(tmp_vault, "ch-000003", "10", "done", chapter="ch1")
        self._plan(tmp_vault, "ch-000003", ("ch1", "Origins (retitled)"))
        ch = load_manifest(tmp_vault, "ch-000003")["chapters"]["ch1"]
        assert ch["status"] == "step-10-done"
        assert ch["title"] == "Origins (retitled)"

    def test_other_events_do_not_touch_chapters(self, tmp_vault):
        from hyperresearch.core.runs import record_event

        init_run(tmp_vault, "ch-000004", profile="dissertation")
        record_event(tmp_vault, "ch-000004", {"type": "spawn", "chapter": "ch9"})
        assert load_manifest(tmp_vault, "ch-000004")["chapters"] == {}

    def test_cli_event_then_resume_reports_pending_chapters(self, tmp_vault, monkeypatch):
        from typer.testing import CliRunner

        from hyperresearch.cli import app

        monkeypatch.chdir(tmp_vault.root)
        runner = CliRunner()
        runner.invoke(app, ["run", "init", "ch-cli-000001", "--profile", "dissertation", "--json"])
        runner.invoke(app, ["run", "step", "ch-cli-000001", "1", "--status", "done", "--json"])
        for cid in ("ch1", "ch2", "ch3"):
            r = runner.invoke(app, [
                "run", "event", "ch-cli-000001", "--type", "chapter-plan",
                "--data", json.dumps({"chapter": cid, "title": f"Chapter {cid}"}), "--json",
            ])
            assert r.exit_code == 0, r.stdout
        runner.invoke(app, ["run", "step", "ch-cli-000001", "1.5", "--status", "done", "--json"])

        r = runner.invoke(app, ["run", "resume", "ch-cli-000001", "--json"])
        assert r.exit_code == 0
        data = json.loads(r.stdout)["data"]
        assert data["chapters_pending"] == ["ch1", "ch2", "ch3"]
        assert data["next_step"] == "2"
        assert data["skill_to_invoke"] == "hyperresearch-2-width-sweep"


class TestWorkspaceIsolation:
    def test_run_files_not_synced_as_notes(self, tmp_vault):
        from hyperresearch.core.sync import compute_sync_plan

        init_run(tmp_vault, "iso-000001")
        run_dir = tmp_vault.run_dir("iso-000001")
        # A markdown file WITH frontmatter inside the run workspace must not
        # become a vault note.
        (run_dir / "scaffold.md").write_text(
            "---\ntitle: Scaffold\n---\n\n## User Prompt (VERBATIM — gospel)\nx\n",
            encoding="utf-8",
        )
        (run_dir / "temp" / "draft-a.md").write_text(
            "---\ntitle: Draft A\n---\n\nbody\n", encoding="utf-8"
        )
        plan = compute_sync_plan(tmp_vault, force=True)
        paths = [str(p) for p in plan.to_add]
        assert not any("runs" in p for p in paths)

    def test_vault_tag_collision_includes_run_dirs(self, tmp_vault):
        from hyperresearch.cli.vault_tag import _existing_tags

        init_run(tmp_vault, "topic-aaaaaa")
        tags = _existing_tags(tmp_vault.root, tmp_vault.research_dir)
        assert "topic-aaaaaa" in tags

    def test_lint_resolves_run_scoped_loci(self, tmp_vault):
        from hyperresearch.cli.lint import _run_artifact

        init_run(tmp_vault, "lint-000001")
        loci = tmp_vault.run_dir("lint-000001") / "loci.json"
        loci.write_text('{"loci": []}', encoding="utf-8")
        resolved = _run_artifact(tmp_vault, "loci.json")
        assert resolved == loci

    def test_lint_falls_back_to_legacy_flat_path(self, tmp_vault):
        from hyperresearch.cli.lint import _run_artifact

        flat = tmp_vault.root / "research" / "loci.json"
        flat.write_text('{"loci": []}', encoding="utf-8")
        assert _run_artifact(tmp_vault, "loci.json") == flat

    def test_lint_query_files_both_layouts(self, tmp_vault):
        from hyperresearch.cli.lint import _query_files

        init_run(tmp_vault, "q-000001", query="the question")
        legacy = tmp_vault.root / "research" / "query-old-tag.md"
        legacy.write_text("old question", encoding="utf-8")
        files = _query_files(tmp_vault)
        names = [f.name for f in files]
        assert names[0] == "query.md"  # newest run first
        assert "query-old-tag.md" in names


class TestChapterPlanEventHardening:
    """Security review of #100: `hpr run event --data` is agent-authored
    JSON. A crafted chapter-plan payload must not corrupt the manifest or
    crash `resume_position`; only a short scalar id and string title fold."""

    def _event(self, vault, tag, **payload):
        from hyperresearch.core.runs import record_event

        record_event(vault, tag, {"type": "chapter-plan", **payload})

    def test_non_scalar_chapter_ids_are_ignored(self, tmp_vault):
        init_run(tmp_vault, "hard-000001", profile="dissertation")
        for bad in ({"a": 1}, ["ch1"], 1.5, True, None, "", "   ", "x" * 65):
            self._event(tmp_vault, "hard-000001", chapter=bad, title="T")
        assert load_manifest(tmp_vault, "hard-000001")["chapters"] == {}
        assert resume_position(load_manifest(tmp_vault, "hard-000001"))["chapters_pending"] == []

    def test_int_chapter_id_and_whitespace_are_normalised(self, tmp_vault):
        init_run(tmp_vault, "hard-000002", profile="dissertation")
        self._event(tmp_vault, "hard-000002", chapter=3, title="Three")
        self._event(tmp_vault, "hard-000002", chapter="  ch4 ", title="Four")
        chapters = load_manifest(tmp_vault, "hard-000002")["chapters"]
        assert set(chapters) == {"3", "ch4"}

    def test_non_string_or_huge_titles_are_dropped_or_bounded(self, tmp_vault):
        from hyperresearch.core.runs import CHAPTER_TITLE_MAX_CHARS

        init_run(tmp_vault, "hard-000003", profile="dissertation")
        self._event(tmp_vault, "hard-000003", chapter="ch1", title={"evil": "dict"})
        self._event(tmp_vault, "hard-000003", chapter="ch2", title=["list"])
        self._event(tmp_vault, "hard-000003", chapter="ch3", title="t" * 10_000)
        chapters = load_manifest(tmp_vault, "hard-000003")["chapters"]
        assert chapters["ch1"] == {"status": "planned"}
        assert chapters["ch2"] == {"status": "planned"}
        assert len(chapters["ch3"]["title"]) == CHAPTER_TITLE_MAX_CHARS

    def test_extra_payload_keys_never_reach_the_manifest(self, tmp_vault):
        init_run(tmp_vault, "hard-000004", profile="dissertation")
        self._event(
            tmp_vault, "hard-000004", chapter="ch1", title="T",
            status="done", steps={"2": {"status": "done"}}, profile_steps=[], spend={"usd": 1},
        )
        manifest = load_manifest(tmp_vault, "hard-000004")
        assert manifest["chapters"]["ch1"] == {"status": "planned", "title": "T"}
        assert manifest["profile_steps"]  # untouched
        assert resume_position(manifest)["chapters_pending"] == ["ch1"]

    def test_corrupt_chapters_shape_is_repaired_not_crashed(self, tmp_vault):
        init_run(tmp_vault, "hard-000005", profile="dissertation")
        mpath = runs_mod.manifest_path(tmp_vault, "hard-000005")
        manifest = json.loads(mpath.read_text(encoding="utf-8"))
        manifest["chapters"] = ["not", "a", "dict"]
        mpath.write_text(json.dumps(manifest), encoding="utf-8")
        assert resume_position(manifest)["chapters_pending"] == []
        self._event(tmp_vault, "hard-000005", chapter="ch1", title="T")
        manifest = load_manifest(tmp_vault, "hard-000005")
        assert manifest["chapters"] == {"ch1": {"status": "planned", "title": "T"}}

        manifest["chapters"]["ch2"] = "planned"  # scalar entry
        assert resume_position(manifest)["chapters_pending"] == ["ch1", "ch2"]
        mpath.write_text(json.dumps(manifest), encoding="utf-8")
        self._event(tmp_vault, "hard-000005", chapter="ch2", title="Two")
        assert load_manifest(tmp_vault, "hard-000005")["chapters"]["ch2"] == {
            "status": "planned", "title": "Two",
        }
