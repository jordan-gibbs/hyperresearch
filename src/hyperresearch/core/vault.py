"""Vault discovery, initialization, and management."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from hyperresearch.core.config import VaultConfig
from hyperresearch.core.db import get_connection, init_schema

HYPERRESEARCH_DIR = ".hyperresearch"
CONFIG_FILE = "config.toml"
DB_FILE = "hyperresearch.db"


class VaultError(Exception):
    pass


class Vault:
    """Represents a hyperresearch research base vault."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.hyperresearch_dir = self.root / HYPERRESEARCH_DIR
        self.config_path = self.hyperresearch_dir / CONFIG_FILE
        self.db_path = self.hyperresearch_dir / DB_FILE
        self._conn: sqlite3.Connection | None = None
        self._config: VaultConfig | None = None

    @property
    def config(self) -> VaultConfig:
        if self._config is None:
            self._config = VaultConfig.load(self.config_path)
        return self._config

    @property
    def db(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = get_connection(self.db_path)
            # Ensure schema is up to date — init_schema is idempotent and runs
            # any pending migrations. This fires on every vault open, which is
            # cheap when there's nothing to migrate.
            init_schema(self._conn)
        return self._conn

    @property
    def is_initialized(self) -> bool:
        return self.hyperresearch_dir.is_dir() and self.db_path.exists()

    # --- Path properties: single source of truth for directory layout ---

    @property
    def research_dir(self) -> Path:
        """The one visible directory at repo root (default: research/)."""
        return self.root / self.config.research_dir

    @property
    def notes_dir(self) -> Path:
        return self.research_dir / "notes"

    @property
    def index_dir(self) -> Path:
        return self.research_dir / "index"

    @property
    def temp_dir(self) -> Path:
        """Sidelined notes (link-auto-resolution stubs, agent-drift artifacts).

        Sibling of `notes_dir` and `index_dir`. Files here ARE still synced into
        the DB (so wiki-link targets resolve), but they're kept out of `notes/`
        so that directory listings of research content stay clean.
        """
        return self.research_dir / "temp"

    @property
    def templates_dir(self) -> Path:
        """Templates live inside .hyperresearch/ (hidden)."""
        return self.hyperresearch_dir / "templates"

    @property
    def exports_dir(self) -> Path:
        """Exports live inside .hyperresearch/ (hidden)."""
        return self.hyperresearch_dir / "exports"

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> Vault:
        return self

    def __exit__(self, *args) -> None:
        self.close()

    @staticmethod
    def init(root: Path, name: str = "Research Base", research_dir: str = "research") -> Vault:
        """Initialize a new vault at the given path."""
        root = root.resolve()
        hyperresearch_dir = root / HYPERRESEARCH_DIR

        if hyperresearch_dir.exists():
            raise VaultError(f"Vault already initialized at {root}")

        # Create .hyperresearch/ structure (hidden)
        hyperresearch_dir.mkdir(parents=True)
        (hyperresearch_dir / "templates").mkdir()
        (hyperresearch_dir / "exports").mkdir()

        # Create the one visible directory
        kb_dir = root / research_dir
        (kb_dir / "notes").mkdir(parents=True, exist_ok=True)
        (kb_dir / "index").mkdir(exist_ok=True)
        (kb_dir / "temp").mkdir(exist_ok=True)

        # Write config
        config = VaultConfig(name=name, research_dir=research_dir)
        config.save(hyperresearch_dir / CONFIG_FILE)

        # Initialize database
        vault = Vault(root)
        init_schema(vault.db)

        # Write default note template
        template_path = hyperresearch_dir / "templates" / "note.md"
        template_path.write_text(
            "---\n"
            "title: \"{{ title }}\"\n"
            "id: \"{{ id }}\"\n"
            "tags: []\n"
            "status: draft\n"
            "type: note\n"
            "created: {{ created }}\n"
            "---\n\n"
            "# {{ title }}\n\n"
        )

        # Inject CLAUDE.md at vault root
        from hyperresearch.core.agent_docs import inject_agent_docs
        inject_agent_docs(root)

        return vault

    @staticmethod
    def discover(start: Path | None = None) -> Vault:
        """Walk up from start (default: cwd) to find a vault root."""
        current = (start or Path.cwd()).resolve()
        while True:
            if (current / HYPERRESEARCH_DIR).is_dir():
                return Vault(current)
            parent = current.parent
            if parent == current:
                break
            current = parent
        raise VaultError(
            "No hyperresearch vault found. Run 'hyperresearch init' to create one."
        )

    def auto_sync(self) -> None:
        """Run an incremental sync if auto_sync is enabled."""
        if not self.config.auto_sync:
            return
        from hyperresearch.core.sync import compute_sync_plan, execute_sync

        plan = compute_sync_plan(self)
        if plan.to_add or plan.to_update or plan.to_delete:
            execute_sync(self, plan)
