"""Installing an API-backed research vault must not download Chromium."""

import builtins
import json

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.cli.install import _setup_crawl4ai
from hyperresearch.core.vault import Vault

runner = CliRunner()


@pytest.fixture
def no_browser_imports(monkeypatch):
    original = builtins.__import__

    def checked(name, *args, **kwargs):
        if name.split(".")[0] in {"crawl4ai", "patchright", "playwright"}:
            pytest.fail(f"Unexpected browser dependency import: {name}")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", checked)


@pytest.mark.parametrize("provider", ["anysearch", "exa", "tavily", "parallel", "serply"])
def test_api_provider_skips_browser_setup(tmp_vault, provider, no_browser_imports):
    tmp_vault.config.web_provider = provider
    assert _setup_crawl4ai(tmp_vault) == "skipped"
    assert tmp_vault.config.web_provider == provider


def test_install_completes_for_anysearch_and_keeps_config(tmp_vault, no_browser_imports):
    tmp_vault.config.web_provider = "anysearch"
    tmp_vault.config.save(tmp_vault.config_path)
    result = runner.invoke(app, ["install", str(tmp_vault.root), "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["data"]["crawl4ai"] == "skipped"
    assert Vault.discover(tmp_vault.root).config.web_provider == "anysearch"
    assert (tmp_vault.root / "CLAUDE.md").is_file()
    assert (tmp_vault.root / ".claude/skills/hyperresearch/SKILL.md").is_file()
    assert (tmp_vault.root / ".claude/skills/hyperresearch-2-width-sweep/SKILL.md").is_file()


def test_explicit_skip_initializes_new_vault_without_browser(tmp_path, no_browser_imports):
    root = tmp_path / "new-vault"
    result = runner.invoke(app, ["install", str(root), "--skip-browser", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["data"]["crawl4ai"] == "skipped"
    assert Vault.discover(root).config.web_provider == "builtin"
    assert (root / ".claude/skills/hyperresearch/SKILL.md").is_file()


def test_plain_install_reports_browser_skip(tmp_vault, no_browser_imports):
    tmp_vault.config.web_provider = "anysearch"
    tmp_vault.config.save(tmp_vault.config_path)
    result = runner.invoke(app, ["install", str(tmp_vault.root)])
    assert result.exit_code == 0, result.output
    assert "skipped" in result.output.lower()
    assert "browser ready" not in result.output.lower()
