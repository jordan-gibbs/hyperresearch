"""Run levers: shim composition, rendering CLI, and the verify gate check.

Levers own posture, profiles own numbers: the profile-number guard here is
the drift-proofing that keeps shim text from ever restating a numeric
budget (which would fight the install-time profile/golden machinery).
"""

from __future__ import annotations

import json
import re

import pytest

from hyperresearch.core.levers import (
    DEFAULT_LEVERS,
    INFERENCE_DEPTHS,
    REGISTERS,
    ROLES,
    LeverError,
    compose_shims,
    render_shims,
    set_levers,
)
from hyperresearch.core.runs import init_run, load_manifest, verify_run


def _write_decomposition(vault, tag: str, levers: dict | None) -> None:
    run_dir = vault.run_dir(tag)
    run_dir.mkdir(parents=True, exist_ok=True)
    decomp: dict = {
        "response_format": "short",
        "required_section_headings": ["## Findings"],
    }
    if levers is not None:
        decomp["levers"] = levers
    (run_dir / "prompt-decomposition.json").write_text(
        json.dumps(decomp), encoding="utf-8"
    )


class TestCompose:
    def test_all_combinations_compose_nonempty(self):
        for register in REGISTERS:
            for depth in INFERENCE_DEPTHS:
                shims = compose_shims({"register": register, "inference_depth": depth})
                assert set(shims) == set(ROLES)
                for role, text in shims.items():
                    assert text.strip(), f"{role} empty for {register}/{depth}"
                    assert "<<" not in text and ">>" not in text
                    assert text.startswith("## Run directives")
                    assert f"register: {register}" in text
                    assert f"inference depth: {depth}" in text

    def test_profile_numbers_stay_out_of_shims(self):
        # Posture, not numbers: a shim restating a numeric budget would
        # fight the profile system that owns every count.
        budget_range = re.compile(
            "\\d+\\s*[-\u2013]\\s*\\d+\\s*(sources|words|fetchers|loci|searches)"
        )
        for register in REGISTERS:
            for depth in INFERENCE_DEPTHS:
                shims = compose_shims({"register": register, "inference_depth": depth})
                for role, text in shims.items():
                    assert not budget_range.search(text), (register, depth, role)

    def test_unknown_register_rejected(self):
        with pytest.raises(LeverError, match="unknown register"):
            compose_shims({"register": "poetic"})

    def test_unknown_inference_depth_rejected(self):
        with pytest.raises(LeverError, match="unknown inference_depth"):
            compose_shims({"inference_depth": "bottomless"})

    def test_domain_notes_land_verbatim_in_research_and_drafting(self):
        notes = "Sourcing: court filings first; recency window is the last two terms."
        shims = compose_shims({**DEFAULT_LEVERS, "domain_notes": notes})
        assert notes in shims["research"]
        assert notes in shims["drafting"]
        assert notes not in shims["polish"]

    def test_register_semantics_reach_the_right_roles(self):
        survey = compose_shims({"register": "survey"})
        assert "Do not flag the absence of a committed thesis" in survey["critics"]
        assert "Do NOT strike hedges" in survey["polish"]
        teach = compose_shims({"register": "teach"})
        assert "non-specialist" in teach["drafting"]
        # Research shims carry no register posture at all.
        assert "Register posture" not in teach["research"]

    def test_deep_inference_licenses_provenance_discipline(self):
        deep = compose_shims({"inference_depth": "deep"})
        assert "provenance" in deep["drafting"].lower()
        assert "audited absences" in deep["research"].lower()


class TestRenderCli:
    def test_render_writes_files_and_manifest(self, tmp_vault, monkeypatch):
        from typer.testing import CliRunner

        from hyperresearch.cli import app

        init_run(tmp_vault, "lv-01", profile="light")
        _write_decomposition(
            tmp_vault, "lv-01",
            {"register": "survey", "inference_depth": "deep", "domain_notes": "Filings first."},
        )
        monkeypatch.chdir(tmp_vault.root)
        r = CliRunner().invoke(app, ["levers", "render", "lv-01", "--json"])
        assert r.exit_code == 0
        for role in ROLES:
            assert (tmp_vault.run_dir("lv-01") / "shims" / f"{role}.md").exists()
        manifest = load_manifest(tmp_vault, "lv-01")
        assert manifest["levers"]["register"] == "survey"
        assert manifest["levers"]["inference_depth"] == "deep"

    def test_render_defaults_when_levers_absent(self, tmp_vault, monkeypatch):
        from typer.testing import CliRunner

        from hyperresearch.cli import app

        init_run(tmp_vault, "lv-02", profile="light")
        _write_decomposition(tmp_vault, "lv-02", levers=None)
        monkeypatch.chdir(tmp_vault.root)
        r = CliRunner().invoke(app, ["levers", "render", "lv-02", "--json"])
        assert r.exit_code == 0
        research = (tmp_vault.run_dir("lv-02") / "shims" / "research.md").read_text(
            encoding="utf-8"
        )
        assert "register: analyze" in research
        assert "inference depth: standard" in research

    def test_render_rejects_unknown_enum_via_cli(self, tmp_vault, monkeypatch):
        from typer.testing import CliRunner

        from hyperresearch.cli import app

        init_run(tmp_vault, "lv-03", profile="light")
        _write_decomposition(tmp_vault, "lv-03", {"register": "poetic"})
        monkeypatch.chdir(tmp_vault.root)
        r = CliRunner().invoke(app, ["levers", "render", "lv-03", "--json"])
        assert r.exit_code == 1

    def test_set_rerender_updates_shims_and_decomposition(self, tmp_vault, monkeypatch):
        from typer.testing import CliRunner

        from hyperresearch.cli import app

        init_run(tmp_vault, "lv-04", profile="light")
        _write_decomposition(tmp_vault, "lv-04", {"register": "analyze"})
        monkeypatch.chdir(tmp_vault.root)
        runner = CliRunner()
        assert runner.invoke(app, ["levers", "render", "lv-04", "--json"]).exit_code == 0
        before = (tmp_vault.run_dir("lv-04") / "shims" / "research.md").read_text(
            encoding="utf-8"
        )

        r = runner.invoke(
            app, ["levers", "set", "lv-04", "inference_depth=deep", "--rerender", "--json"]
        )
        assert r.exit_code == 0
        after = (tmp_vault.run_dir("lv-04") / "shims" / "research.md").read_text(
            encoding="utf-8"
        )
        assert before != after
        assert "DEEP inference" in after
        decomp = json.loads(
            (tmp_vault.run_dir("lv-04") / "prompt-decomposition.json").read_text(
                encoding="utf-8"
            )
        )
        assert decomp["levers"]["inference_depth"] == "deep"

    def test_set_rejects_invalid_value_without_writing(self, tmp_vault):
        init_run(tmp_vault, "lv-05", profile="light")
        _write_decomposition(tmp_vault, "lv-05", {"register": "analyze"})
        with pytest.raises(LeverError):
            set_levers(tmp_vault, "lv-05", {"register": "poetic"})
        decomp = json.loads(
            (tmp_vault.run_dir("lv-05") / "prompt-decomposition.json").read_text(
                encoding="utf-8"
            )
        )
        assert decomp["levers"]["register"] == "analyze"


class TestVerifyGate:
    def _report(self, vault, tag: str) -> None:
        report = vault.root / "research" / "notes" / f"final_report_{tag}.md"
        report.write_text(
            "## Findings\n\n" + ("Evidence-bearing sentence [[src]]. " * 80),
            encoding="utf-8",
        )

    def test_declared_levers_without_shims_fails(self, tmp_vault):
        init_run(tmp_vault, "lv-06", profile="light")
        _write_decomposition(tmp_vault, "lv-06", {"register": "survey"})
        self._report(tmp_vault, "lv-06")
        result = verify_run(tmp_vault, "lv-06")
        by_name = {c["name"]: c for c in result["checks"]}
        assert not by_name["levers-rendered"]["ok"]

    def test_declared_levers_with_shims_passes(self, tmp_vault):
        init_run(tmp_vault, "lv-07", profile="light")
        _write_decomposition(tmp_vault, "lv-07", {"register": "survey"})
        render_shims(tmp_vault, "lv-07")
        self._report(tmp_vault, "lv-07")
        result = verify_run(tmp_vault, "lv-07")
        by_name = {c["name"]: c for c in result["checks"]}
        assert by_name["levers-rendered"]["ok"]

    def test_leverless_run_skips_the_check(self, tmp_vault):
        init_run(tmp_vault, "lv-08", profile="light")
        _write_decomposition(tmp_vault, "lv-08", levers=None)
        self._report(tmp_vault, "lv-08")
        result = verify_run(tmp_vault, "lv-08")
        assert "levers-rendered" not in {c["name"] for c in result["checks"]}
