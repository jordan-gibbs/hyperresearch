"""Browser-setup installer preference: patchright's chromium when present.

The stealth adapter (UndetectedAdapter) launches patchright's pinned chromium,
which lives in a separate registry from plain playwright's. A setup that only
runs `playwright install chromium` produces a machine where every preflight
passes and every browser fetch dies at launch. These tests pin the installer
order without touching the network or any real browser registry.
"""

from __future__ import annotations

import sys

import pytest

pytest.importorskip("crawl4ai", reason="crawl4ai extra not installed")

from hyperresearch.cli.install import _setup_crawl4ai


@pytest.fixture
def _no_working_browser(monkeypatch):
    """Force the availability check down the install path: both sync_api
    imports fail, so _setup_crawl4ai must decide which installer to run."""
    monkeypatch.setitem(sys.modules, "patchright.sync_api", None)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", None)


def _capture_installs(monkeypatch, fail_mods=()):
    calls: list[str] = []

    def fake_run(cmd, check, capture_output):
        mod = cmd[2]
        calls.append(mod)
        if mod in fail_mods:
            import subprocess

            raise subprocess.CalledProcessError(1, cmd)
        return None

    monkeypatch.setattr("subprocess.run", fake_run)
    return calls


def test_patchright_chromium_preferred_when_patchright_present(
        tmp_vault, monkeypatch, _no_working_browser):
    monkeypatch.setattr("importlib.util.find_spec", lambda name: object())
    calls = _capture_installs(monkeypatch)

    assert _setup_crawl4ai(tmp_vault) == "browser_installed"
    assert calls == ["patchright"], (
        "with patchright installed, its own chromium must be installed first; "
        "plain `playwright install chromium` does not provide it"
    )


def test_plain_playwright_used_when_patchright_absent(
        tmp_vault, monkeypatch, _no_working_browser):
    monkeypatch.setattr("importlib.util.find_spec", lambda name: None)
    calls = _capture_installs(monkeypatch)

    assert _setup_crawl4ai(tmp_vault) == "browser_installed"
    assert calls == ["playwright"]


def test_failed_patchright_install_falls_back_to_playwright(
        tmp_vault, monkeypatch, _no_working_browser):
    monkeypatch.setattr("importlib.util.find_spec", lambda name: object())
    calls = _capture_installs(monkeypatch, fail_mods=("patchright",))

    assert _setup_crawl4ai(tmp_vault) == "browser_installed"
    assert calls == ["patchright", "playwright"]
