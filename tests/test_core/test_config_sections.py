"""Tests for the Phase-1 config sections ([fetch]/[junk]/[assets]/[dedup]/[lint])."""

from __future__ import annotations

from pathlib import Path

from hyperresearch.core.config import (
    AssetSettings,
    DedupSettings,
    FetchSettings,
    JunkGates,
    LintSettings,
    VaultConfig,
)


class TestDefaults:
    """Absent config keys must reproduce pre-2.0 behavior exactly."""

    def test_missing_file_gives_defaults(self, tmp_path: Path):
        cfg = VaultConfig.load(tmp_path / "nope.toml")
        assert cfg.fetch == FetchSettings()
        assert cfg.junk == JunkGates()
        assert cfg.assets == AssetSettings()
        assert cfg.dedup == DedupSettings()
        assert cfg.lint == LintSettings()

    def test_default_values_match_pre_20_literals(self):
        f = FetchSettings()
        assert f.page_timeout_ms == 30000
        assert f.pdf_timeout_s == 30
        assert f.min_pdf_bytes == 100
        assert f.wait_initial_ms == 2000
        assert f.poll_interval_ms == 500
        assert f.stable_checks == 2
        assert f.max_checks == 16
        assert f.image_timeout_s == 15
        assert "linkedin.com" in f.visible_browser_domains
        assert len(f.visible_browser_domains) == 6

        j = JunkGates()
        assert j.min_content_chars == 300
        assert j.login_wall_max_chars == 1000
        assert j.cookie_wall_max_chars == 1500
        assert j.binary_garbage_ratio == 0.05
        assert j.sample_window == 2000
        assert j.login_sample_chars == 500

        a = AssetSettings()
        assert a.max_images == 5
        assert a.min_image_bytes == 50_000

        d = DedupSettings()
        assert d.shingle_size == 3
        assert d.minhash_perm == 128
        assert d.lsh_bands == 16
        assert d.lsh_switchover == 200
        assert d.default_threshold == 0.6

        li = LintSettings()
        assert li.extract_min_words == 150
        assert li.extract_coverage_divisor == 3
        assert li.stale_review_days == 90

    def test_pdf_verify_tls_defaults_true(self):
        # Deliberate 2.0 behavior change: TLS verification ON by default
        # (pre-2.0 code hardcoded verify=False for PDF downloads).
        assert FetchSettings().pdf_verify_tls is True


class TestLoadOverrides:
    def test_partial_section_override(self, tmp_path: Path):
        p = tmp_path / "config.toml"
        p.write_text(
            "[fetch]\npage_timeout_ms = 60000\n\n"
            "[junk]\nmin_content_chars = 50\n\n"
            "[assets]\nmax_images = 12\n\n"
            "[dedup]\ndefault_threshold = 0.8\n\n"
            "[lint]\nstale_review_days = 30\n",
            encoding="utf-8",
        )
        cfg = VaultConfig.load(p)
        # Overridden keys take effect
        assert cfg.fetch.page_timeout_ms == 60000
        assert cfg.junk.min_content_chars == 50
        assert cfg.assets.max_images == 12
        assert cfg.dedup.default_threshold == 0.8
        assert cfg.lint.stale_review_days == 30
        # Untouched keys keep defaults
        assert cfg.fetch.pdf_timeout_s == 30
        assert cfg.junk.binary_garbage_ratio == 0.05
        assert cfg.assets.min_image_bytes == 50_000

    def test_toml_arrays_become_tuples(self, tmp_path: Path):
        p = tmp_path / "config.toml"
        p.write_text(
            '[fetch]\nvisible_browser_domains = ["example.com"]\n\n'
            '[junk]\nextra_login_signals = ["mitgliedsbereich"]\n',
            encoding="utf-8",
        )
        cfg = VaultConfig.load(p)
        assert cfg.fetch.visible_browser_domains == ("example.com",)
        assert cfg.junk.extra_login_signals == ("mitgliedsbereich",)

    def test_unknown_keys_ignored(self, tmp_path: Path):
        p = tmp_path / "config.toml"
        p.write_text("[fetch]\nfuture_knob = 42\npage_timeout_ms = 1234\n", encoding="utf-8")
        cfg = VaultConfig.load(p)
        assert cfg.fetch.page_timeout_ms == 1234

    def test_search_output_defaults(self, tmp_path: Path):
        cfg = VaultConfig.load(tmp_path / "nope.toml")
        assert cfg.search_default_limit == 20
        assert cfg.search_chars_per_token == 4
        assert cfg.search_snippet_len == 200
        p = tmp_path / "config.toml"
        p.write_text("[search]\ndefault_limit = 50\nsnippet_len = 400\n", encoding="utf-8")
        cfg2 = VaultConfig.load(p)
        assert cfg2.search_default_limit == 50
        assert cfg2.search_snippet_len == 400
        assert cfg2.search_chars_per_token == 4


class TestSaveLoadRoundtrip:
    def test_roundtrip_preserves_sections(self, tmp_path: Path):
        cfg = VaultConfig(
            fetch=FetchSettings(page_timeout_ms=45000, pdf_verify_tls=False),
            junk=JunkGates(min_content_chars=100, extra_junk_signals=("custom wall",)),
            assets=AssetSettings(max_images=9),
            dedup=DedupSettings(lsh_switchover=500),
            lint=LintSettings(extract_min_words=200),
        )
        p = tmp_path / "config.toml"
        cfg.save(p)
        loaded = VaultConfig.load(p)
        assert loaded.fetch == cfg.fetch
        assert loaded.junk == cfg.junk
        assert loaded.assets == cfg.assets
        assert loaded.dedup == cfg.dedup
        assert loaded.lint == cfg.lint

    def test_default_roundtrip_is_identity(self, tmp_path: Path):
        cfg = VaultConfig()
        p = tmp_path / "config.toml"
        cfg.save(p)
        assert VaultConfig.load(p) == cfg


class TestPipelineGear:
    def test_default_gear_is_full(self, tmp_path: Path):
        cfg = VaultConfig.load(tmp_path / "nope.toml")
        assert cfg.pipeline_profile == "full"

    def test_gear_roundtrip(self, tmp_path: Path):
        cfg = VaultConfig(pipeline_profile="premier")
        p = tmp_path / "config.toml"
        cfg.save(p)
        loaded = VaultConfig.load(p)
        assert loaded.pipeline_profile == "premier"

    def test_gear_loads_from_pipeline_section(self, tmp_path: Path):
        p = tmp_path / "config.toml"
        p.write_text('[pipeline]\nprofile = "premier"\n', encoding="utf-8")
        assert VaultConfig.load(p).pipeline_profile == "premier"


class TestProfileOverlayRoundtrip:
    """Regression: save() used to drop [profile.*] tables entirely —
    any config write silently destroyed user-defined pipeline profiles."""

    def test_overlays_survive_save(self, tmp_path: Path):
        p = tmp_path / "config.toml"
        p.write_text(
            "[profile.megareview]\n"
            "source_min = 250\n"
            "loci_max = 20\n"
            'extends = "full"\n'
            "source_target = [300, 450]\n"
            "depth_budget_brackets = [[35, 20], [0, 5]]\n"
            'must_read = { argumentative = [50, 70], short = [20, 30] }\n'
            "utility_scoring = false\n"
            'time_estimate = "~4 hours"\n',
            encoding="utf-8",
        )
        cfg = VaultConfig.load(p)
        assert "megareview" in cfg.profile_overlays
        cfg.save(p)

        # The overlay must still parse as valid TOML and resolve as a profile
        reloaded = VaultConfig.load(p)
        assert reloaded.profile_overlays == cfg.profile_overlays

        from hyperresearch.core.profiles import resolve_profile

        prof = resolve_profile("megareview", p)
        assert prof.source_min == 250
        assert prof.source_target == (300, 450)
        assert prof.depth_budget_brackets == ((35, 20), (0, 5))
        assert prof.must_read["argumentative"] == (50, 70)
        assert prof.utility_scoring is False
        assert prof.time_estimate == "~4 hours"

    def test_builtin_override_survives_save(self, tmp_path: Path):
        p = tmp_path / "config.toml"
        p.write_text("[profile.full]\nsource_min = 60\n", encoding="utf-8")
        cfg = VaultConfig.load(p)
        cfg.save(p)

        from hyperresearch.core.profiles import resolve_profile

        assert resolve_profile("full", p).source_min == 60


class TestGateThreading:
    """Custom thresholds must actually change gate behavior."""

    def _result(self, content: str, title: str = "Some Page", url: str = "https://example.com/a"):
        from hyperresearch.web.base import WebResult

        return WebResult(url=url, title=title, content=content)

    def test_min_content_chars_gate(self):
        text = "word " * 80  # 400 chars, real prose
        assert self._result(text).looks_like_junk() is None
        strict = JunkGates(min_content_chars=1000)
        assert self._result(text).looks_like_junk(strict) == "Empty or near-empty content"

    def test_binary_garbage_ratio_gate(self):
        # ~10% control characters: junk at default 0.05, fine at 0.5
        # Pad well past every length gate (cookie wall fires under 1500 chars).
        base = ("normal text with plenty of ordinary words here " * 40) + "\x01\x02" * 120
        assert self._result(base).looks_like_junk() == "High ratio of binary/non-printable content"
        lax = JunkGates(binary_garbage_ratio=0.5)
        assert self._result(base).looks_like_junk(lax) is None

    def test_extra_junk_signals(self):
        text = "This portal is protected by MegaShield gateway. " * 40
        assert self._result(text).looks_like_junk() is None
        gates = JunkGates(extra_junk_signals=("megashield gateway",))
        reason = self._result(text).looks_like_junk(gates)
        assert reason is not None and reason.startswith("Bot detection page")

    def test_login_wall_threshold(self):
        # Short page mentioning login: wall at default, passes when the
        # content-length gate is tightened below the text length.
        text = "Please login to continue reading this article about widgets."
        r = self._result(text, title="Widgets Weekly")
        assert r.looks_like_login_wall("https://example.com/a") is True
        lax = JunkGates(login_wall_max_chars=10)
        assert r.looks_like_login_wall("https://example.com/a", lax) is False

    def test_extra_login_signals(self):
        text = "Mitgliedsbereich: bitte anmelden. " + ("Inhalt " * 50)
        r = self._result(text, title="Mitgliedsbereich")
        assert r.looks_like_login_wall("https://example.com/a") is False
        gates = JunkGates(extra_login_signals=("mitgliedsbereich",))
        assert r.looks_like_login_wall("https://example.com/a", gates) is True


class TestVaultConfigIntegration:
    def test_vault_config_file_includes_sections(self, tmp_vault):
        # Vault.init saves a config that already carries the new sections
        cfg_path = tmp_vault.root / ".hyperresearch" / "config.toml"
        text = cfg_path.read_text(encoding="utf-8")
        assert "[junk]" in text and "[fetch]" in text

    def test_vault_picks_up_section_override(self, tmp_vault):
        # Edit a key inside the existing [junk] section and reload
        cfg_path = tmp_vault.root / ".hyperresearch" / "config.toml"
        existing = cfg_path.read_text(encoding="utf-8")
        assert "min_content_chars = 300" in existing
        cfg_path.write_text(
            existing.replace("min_content_chars = 300", "min_content_chars = 77"),
            encoding="utf-8",
        )
        reloaded = VaultConfig.load(cfg_path)
        assert reloaded.junk.min_content_chars == 77
