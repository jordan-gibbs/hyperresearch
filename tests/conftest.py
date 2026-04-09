"""Shared test fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from hyperresearch.core.vault import Vault


@pytest.fixture
def tmp_vault(tmp_path: Path) -> Vault:
    """Create a temporary vault for testing."""
    vault = Vault.init(tmp_path / "test-vault", name="Test Vault")
    return vault


@pytest.fixture
def seeded_vault(tmp_vault: Vault) -> Vault:
    """A vault with sample notes pre-populated."""
    from hyperresearch.core.note import write_note

    # Create interconnected notes
    write_note(
        tmp_vault.notes_dir,
        "Python Async Patterns",
        body=(
            "# Python Async Patterns\n\n"
            "Python's async/await syntax enables concurrent I/O.\n\n"
            "See also [[concurrency]] and [[rust-ownership]].\n"
        ),
        tags=["python", "async", "concurrency"],
        status="evergreen",
        parent="python",
        summary="Guide to async/await in Python",
    )

    write_note(
        tmp_vault.notes_dir,
        "Rust Ownership",
        body=(
            "# Rust Ownership\n\n"
            "Rust's ownership model ensures memory safety without GC.\n\n"
            "Related: [[python-async-patterns]] and [[concurrency]].\n"
        ),
        tags=["rust", "memory", "concurrency"],
        status="evergreen",
        parent="rust",
        summary="Rust's ownership and borrowing system",
    )

    write_note(
        tmp_vault.notes_dir,
        "Concurrency",
        body=(
            "# Concurrency\n\n"
            "Fundamental patterns for concurrent programming.\n\n"
            "- [[python-async-patterns]]\n"
            "- [[rust-ownership]]\n"
            "- [[nonexistent-topic]]\n"
        ),
        tags=["concurrency", "concepts"],
        status="evergreen",
        note_type="moc",
        summary="Map of content for concurrency topics",
    )

    write_note(
        tmp_vault.notes_dir,
        "Orphan Note",
        body="# Orphan\n\nThis note links to nothing and nothing links to it.\n",
        tags=["test"],
        status="draft",
    )

    # Sync to populate DB
    from hyperresearch.core.sync import compute_sync_plan, execute_sync

    plan = compute_sync_plan(tmp_vault, force=True)
    execute_sync(tmp_vault, plan)

    return tmp_vault
