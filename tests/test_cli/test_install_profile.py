"""Tests for `hyperresearch install --profile` plumbing."""

from __future__ import annotations

from typer.testing import CliRunner

from hyperresearch.cli import app

runner = CliRunner()


def _sweep_text(vault) -> str:
    p = vault.root / ".claude" / "skills" / "hyperresearch-2-width-sweep" / "SKILL.md"
    return p.read_text(encoding="utf-8")


def test_install_default_profile_is_full(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)
    result = runner.invoke(app, ["install", str(tmp_vault.root), "--json"])
    assert result.exit_code == 0
    sweep = _sweep_text(tmp_vault)
    assert "**40–100 planned searches**" in sweep  # full profile primary
    assert 'rendered from profile "full"' in sweep


def test_install_profile_light_changes_primary(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)
    result = runner.invoke(
        app, ["install", str(tmp_vault.root), "--profile", "light", "--json"]
    )
    assert result.exit_code == 0
    sweep = _sweep_text(tmp_vault)
    # `p` (primary) is now light: planned_searches renders (8, 20)
    assert "**8–20 planned searches**" in sweep
    assert 'rendered from profile "light"' in sweep
    # The `full` tier row follows the gear (p.*): it shows what a full-tier
    # run will actually target under the installed profile. The `light` row
    # stays profile-qualified.
    assert "| `full` | 10 | 15–25 |" in sweep
    assert "| `light` | 10 | 15–25 |" in sweep


def test_install_unknown_profile_fails_cleanly(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)
    result = runner.invoke(
        app, ["install", str(tmp_vault.root), "--profile", "bogus", "--json"]
    )
    assert result.exit_code == 1
    # No half-written render should exist from the failed run: install validates
    # the profile before writing (the file may exist from vault init defaults,
    # but must not claim a bogus profile)
    p = tmp_vault.root / ".claude" / "skills" / "hyperresearch-2-width-sweep" / "SKILL.md"
    if p.exists():
        assert 'rendered from profile "bogus"' not in p.read_text(encoding="utf-8")


def test_install_steps_only_renders(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)
    result = runner.invoke(
        app, ["install", str(tmp_vault.root), "--steps-only", "--json"]
    )
    assert result.exit_code == 0
    sweep = _sweep_text(tmp_vault)
    assert "<<" not in sweep
    assert 'rendered from profile "full"' in sweep


def test_reinstall_is_idempotent_per_profile(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)
    first = runner.invoke(app, ["install", str(tmp_vault.root), "--json"])
    assert first.exit_code == 0
    before = _sweep_text(tmp_vault)
    second = runner.invoke(app, ["install", str(tmp_vault.root), "--json"])
    assert second.exit_code == 0
    assert _sweep_text(tmp_vault) == before


def test_profile_use_premier_switches_gear(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)
    result = runner.invoke(app, ["profile", "use", "premier", "--json"])
    assert result.exit_code == 0
    # Skills re-rendered at premier scale
    sweep = _sweep_text(tmp_vault)
    assert 'rendered from profile "premier"' in sweep
    assert "**80–160 planned searches**" in sweep
    assert "| `full` | 90 | 100–130 |" in sweep
    # Gear persisted in config
    cfg_text = tmp_vault.config_path.read_text(encoding="utf-8")
    assert '[pipeline]' in cfg_text
    assert 'profile = "premier"' in cfg_text


def test_bare_install_keeps_persisted_gear(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)
    use = runner.invoke(app, ["profile", "use", "premier", "--json"])
    assert use.exit_code == 0
    # A later bare install (e.g. after a package upgrade) must NOT silently
    # downshift the gear back to full.
    result = runner.invoke(app, ["install", str(tmp_vault.root), "--json"])
    assert result.exit_code == 0
    sweep = _sweep_text(tmp_vault)
    assert 'rendered from profile "premier"' in sweep
    # An explicit --profile still overrides the persisted gear
    result = runner.invoke(
        app, ["install", str(tmp_vault.root), "--profile", "full", "--json"]
    )
    assert result.exit_code == 0
    assert 'rendered from profile "full"' in _sweep_text(tmp_vault)


def test_profile_use_rejects_tiers(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)
    for tier in ("light", "dissertation"):
        result = runner.invoke(app, ["profile", "use", tier, "--json"])
        assert result.exit_code == 1, tier
        assert "tier" in result.stdout.lower()


def test_profile_use_unknown_fails_cleanly(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)
    result = runner.invoke(app, ["profile", "use", "bogus", "--json"])
    assert result.exit_code == 1
    # Config must not have been touched
    cfg_text = tmp_vault.config_path.read_text(encoding="utf-8")
    assert 'profile = "bogus"' not in cfg_text


def test_profile_use_preserves_user_overlays(tmp_vault, monkeypatch):
    # Regression: config.save() used to drop [profile.*] tables, destroying
    # user-defined profiles on any config write.
    cfg_path = tmp_vault.config_path
    cfg_path.write_text(
        cfg_path.read_text(encoding="utf-8")
        + "\n[profile.megareview]\nsource_min = 250\nloci_max = 20\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_vault.root)
    result = runner.invoke(app, ["profile", "use", "premier", "--json"])
    assert result.exit_code == 0
    cfg_text = cfg_path.read_text(encoding="utf-8")
    assert "[profile.megareview]" in cfg_text
    assert "source_min = 250" in cfg_text
    # And the overlay still resolves after the round-trip
    from hyperresearch.core.profiles import resolve_profile

    p = resolve_profile("megareview", cfg_path)
    assert p.source_min == 250
    assert p.loci_max == 20
