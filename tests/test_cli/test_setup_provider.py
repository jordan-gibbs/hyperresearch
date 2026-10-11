"""`hyperresearch setup` step 1: provider choice, including firecrawl.

Drives the real wizard with scripted prompt answers. The browser install and
the crawl4ai profile listing are stubbed, so nothing launches.
"""

from __future__ import annotations

import importlib
import sys

import pytest

from hyperresearch.core.vault import Vault

setup_mod = importlib.import_module("hyperresearch.cli.setup")


class _TTY:
    def isatty(self) -> bool:
        return True


@pytest.fixture
def wizard(monkeypatch):
    """Run setup with scripted answers; None accepts the prompt's default."""
    monkeypatch.setattr(sys, "stdin", _TTY())
    browser_installs: list[bool] = []
    monkeypatch.setattr(setup_mod, "_ensure_browser", lambda: browser_installs.append(True))

    def run(root, answers, *, has_crawl4ai=True, profiles=()):
        monkeypatch.setattr(setup_mod, "_check_crawl4ai", lambda: has_crawl4ai)
        monkeypatch.setattr(setup_mod, "_list_profiles", lambda: list(profiles))
        pending = list(answers)
        asked: list[str] = []

        def ask(prompt, *, choices=None, default=None, **kwargs):
            asked.append(prompt.strip())
            answer = pending.pop(0) if pending else None
            assert answer is None or choices is None or answer in choices
            return default if answer is None else answer

        monkeypatch.setattr(setup_mod.Prompt, "ask", ask)
        setup_mod.setup(path=str(root), json_output=False)
        return asked, browser_installs

    return run


def _menu_number(name: str, has_crawl4ai: bool = True, current: str | None = None) -> str:
    return str(setup_mod._provider_options(has_crawl4ai, current).index(name) + 1)


def test_choosing_firecrawl_keeps_the_browser_fallback(tmp_path, wizard, monkeypatch):
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)
    root = tmp_path / "project"
    root.mkdir()

    asked, browser_installs = wizard(root, [_menu_number("firecrawl"), None])

    config = Vault.discover(root).config
    assert config.web_provider == "firecrawl"
    assert config.web_profile == ""
    assert config.web_magic is True
    assert browser_installs == [True]
    assert len(asked) == 2  # step 1 provider + step 2 profile


def test_rerun_on_firecrawl_vault_keeps_it_by_default(tmp_path, wizard):
    root = tmp_path / "project"
    vault = Vault.init(root)
    vault.config.web_provider = "firecrawl"
    vault.config.web_profile = "Scratch"
    vault.config.web_magic = True
    vault.config.save(vault.config_path)

    wizard(root, [], profiles=["Scratch"])

    config = Vault.discover(root).config
    assert config.web_provider == "firecrawl"
    assert config.web_profile == "Scratch"


def test_firecrawl_offered_without_crawl4ai(tmp_path, wizard):
    root = tmp_path / "project"
    root.mkdir()

    asked, browser_installs = wizard(
        root, [_menu_number("firecrawl", has_crawl4ai=False)], has_crawl4ai=False
    )

    config = Vault.discover(root).config
    assert config.web_provider == "firecrawl"
    assert config.web_magic is False
    assert browser_installs == []
    assert len(asked) == 1  # no browser-profile step


def test_rerun_keeps_a_provider_the_menu_does_not_list(tmp_path, wizard):
    root = tmp_path / "project"
    vault = Vault.init(root)
    vault.config.web_provider = "exa"
    vault.config.save(vault.config_path)

    wizard(root, [])

    assert Vault.discover(root).config.web_provider == "exa"
