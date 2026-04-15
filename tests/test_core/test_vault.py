"""Tests for vault initialization and discovery."""

from pathlib import Path

import pytest

from hyperresearch.core.vault import Vault, VaultError


def test_init_creates_structure(tmp_path: Path):
    vault = Vault.init(tmp_path / "kb", name="My KB")
    assert vault.is_initialized
    assert (vault.root / ".hyperresearch").is_dir()
    assert (vault.root / ".hyperresearch" / "config.toml").exists()
    assert (vault.root / ".hyperresearch" / "hyperresearch.db").exists()
    assert (vault.root / ".hyperresearch" / "templates").is_dir()
    assert (vault.root / ".hyperresearch" / "exports").is_dir()
    # One visible directory
    assert vault.research_dir.is_dir()
    assert vault.notes_dir.is_dir()
    assert vault.index_dir.is_dir()
    # Sidelined artifacts (stubs, drift) go here so notes/ stays clean
    assert vault.temp_dir.is_dir()
    assert vault.temp_dir.parent == vault.research_dir
    assert vault.temp_dir.name == "temp"


def test_init_custom_dir(tmp_path: Path):
    vault = Vault.init(tmp_path / "kb", name="Custom", research_dir="docs/wiki")
    assert (vault.root / "docs" / "wiki" / "notes").is_dir()
    assert vault.config.research_dir == "docs/wiki"


def test_init_double_init_raises(tmp_path: Path):
    Vault.init(tmp_path / "kb")
    with pytest.raises(VaultError, match="already initialized"):
        Vault.init(tmp_path / "kb")


def test_discover_finds_vault(tmp_path: Path):
    vault = Vault.init(tmp_path / "kb")
    # Discover from a subdirectory
    sub = vault.notes_dir / "deep"
    sub.mkdir(parents=True)
    found = Vault.discover(start=sub)
    assert found.root == vault.root


def test_discover_raises_when_no_vault(tmp_path: Path):
    with pytest.raises(VaultError, match="No hyperresearch vault"):
        Vault.discover(start=tmp_path)


def test_config_loaded(tmp_vault: Vault):
    assert tmp_vault.config.name == "Test Vault"
    assert tmp_vault.config.auto_sync is True


def test_agent_docs_created(tmp_path: Path):
    vault = Vault.init(tmp_path / "kb")
    assert (vault.root / "CLAUDE.md").exists()
    content = (vault.root / "CLAUDE.md").read_text()
    assert "hyperresearch" in content


def test_init_only_creates_claude_md(tmp_path: Path):
    """Vault.init writes CLAUDE.md ONLY — no AGENTS.md, GEMINI.md, or
    .github/copilot-instructions.md. hyperresearch is Claude Code-only;
    multi-platform doc generation was removed in v0.6."""
    vault = Vault.init(tmp_path / "kb-claude-only")
    assert (vault.root / "CLAUDE.md").exists()
    assert not (vault.root / "AGENTS.md").exists()
    assert not (vault.root / "GEMINI.md").exists()
    assert not (vault.root / ".github" / "copilot-instructions.md").exists()
