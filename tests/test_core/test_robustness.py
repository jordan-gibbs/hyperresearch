"""Regression tests: configurable research_dir, profile-driven density floor,
manifest locking under concurrent writers, and bounded vault discovery."""

from __future__ import annotations

import json
import multiprocessing as mp
import threading
from pathlib import Path

import pytest

from hyperresearch.core.runs import (
    add_spend,
    init_run,
    load_manifest,
    manifest_lock,
    set_step,
    verify_run,
)
from hyperresearch.core.vault import Vault, VaultError


def _write_light_run(vault: Vault, tag: str, body: str) -> None:
    init_run(vault, tag, profile="light")
    run_dir = vault.run_dir(tag)
    (run_dir / "prompt-decomposition.json").write_text(
        json.dumps({"response_format": "short", "required_section_headings": ["## Findings"]}),
        encoding="utf-8",
    )
    (run_dir / "polish-log.json").write_text('{"applied": []}', encoding="utf-8")
    (vault.notes_dir / f"final_report_{tag}.md").write_text(body, encoding="utf-8")


WELL_CITED = "## Findings\n\n" + (
    "Substantive sentence with real evidence attached [[src-note]]. " * 80
)


class TestCustomResearchDir:
    def test_verify_finds_report_under_custom_research_dir(self, tmp_path: Path):
        vault = Vault.init(tmp_path / "kb", research_dir="docs")
        _write_light_run(vault, "rd-01", WELL_CITED)
        assert (tmp_path / "kb" / "docs" / "notes" / "final_report_rd-01.md").exists()
        assert not (tmp_path / "kb" / "research").exists()

        result = verify_run(vault, "rd-01")
        by_name = {c["name"]: c for c in result["checks"]}
        assert by_name["report-exists"]["ok"], by_name["report-exists"]["detail"]
        assert result["passed"] is True


class TestDensityFloorFromProfile:
    def test_default_floor_matches_profile(self, tmp_vault):
        _write_light_run(tmp_vault, "df-01", WELL_CITED)
        check = next(
            c for c in verify_run(tmp_vault, "df-01")["checks"] if c["name"] == "citation-density"
        )
        assert check["ok"]
        assert "(floor 1.5)" in check["detail"]

    def test_profile_override_raises_the_floor(self, tmp_vault):
        with open(tmp_vault.config_path, "a", encoding="utf-8") as f:
            f.write("\n[profile.light]\ncitation_density_min = 50.0\n")
        _write_light_run(tmp_vault, "df-02", WELL_CITED)
        check = next(
            c for c in verify_run(tmp_vault, "df-02")["checks"] if c["name"] == "citation-density"
        )
        assert not check["ok"]
        assert "(floor 50.0)" in check["detail"]


def _spend_worker(root: str, tag: str, n: int) -> None:
    vault = Vault(Path(root))
    try:
        for _ in range(n):
            add_spend(vault, tag, estimated_usd=0.01, sources_fetched=1)
    finally:
        vault.close()


class TestManifestLock:
    def test_concurrent_processes_lose_no_updates(self, tmp_vault):
        init_run(tmp_vault, "lk-01", profile="light")
        procs, per = 4, 25
        ctx = mp.get_context("spawn")
        workers = [
            ctx.Process(target=_spend_worker, args=(str(tmp_vault.root), "lk-01", per))
            for _ in range(procs)
        ]
        for w in workers:
            w.start()
        for w in workers:
            w.join(timeout=120)
            assert w.exitcode == 0
        spend = load_manifest(tmp_vault, "lk-01")["spend"]
        assert spend["sources_fetched"] == procs * per
        assert spend["estimated_usd"] == pytest.approx(procs * per * 0.01)

    def test_concurrent_threads_lose_no_updates(self, tmp_vault):
        init_run(tmp_vault, "lk-02", profile="light")
        threads = [
            threading.Thread(
                target=lambda: [add_spend(tmp_vault, "lk-02", sources_fetched=1) for _ in range(20)]
            )
            for _ in range(4)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert load_manifest(tmp_vault, "lk-02")["spend"]["sources_fetched"] == 80

    def test_lock_is_reentrant(self, tmp_vault):
        init_run(tmp_vault, "lk-03", profile="light")
        with manifest_lock(tmp_vault, "lk-03"), manifest_lock(tmp_vault, "lk-03"):
            # set_step takes the lock again, then record_event does too.
            set_step(tmp_vault, "lk-03", "1", "done")
        assert load_manifest(tmp_vault, "lk-03")["steps"]["1"]["status"] == "done"


class TestDiscoveryCeiling:
    @pytest.fixture
    def fake_home(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        home = (tmp_path / "home").resolve()
        home.mkdir()
        monkeypatch.setattr(Vault, "_discovery_ceiling", staticmethod(lambda: home))
        return home

    def test_home_vault_does_not_capture_subdirectories(self, fake_home: Path):
        Vault.init(fake_home)
        sub = fake_home / "projects" / "other"
        sub.mkdir(parents=True)
        with pytest.raises(VaultError, match="home directory"):
            Vault.discover(start=sub)

    def test_starting_at_home_still_finds_home_vault(self, fake_home: Path):
        Vault.init(fake_home)
        assert Vault.discover(start=fake_home).root == fake_home

    def test_project_vault_under_home_is_found(self, fake_home: Path):
        Vault.init(fake_home)
        project = Vault.init(fake_home / "proj")
        deep = project.notes_dir / "x"
        deep.mkdir()
        assert Vault.discover(start=deep).root == project.root

    def test_explicit_env_var_wins(self, fake_home: Path, tmp_path: Path, monkeypatch):
        target = Vault.init(tmp_path / "elsewhere")
        monkeypatch.setenv("HYPERRESEARCH_VAULT", str(target.root))
        assert Vault.discover(start=fake_home).root == target.root

    def test_explicit_env_var_without_vault_errors(self, tmp_path: Path, monkeypatch):
        monkeypatch.setenv("HYPERRESEARCH_VAULT", str(tmp_path))
        with pytest.raises(VaultError, match="HYPERRESEARCH_VAULT"):
            Vault.discover()
