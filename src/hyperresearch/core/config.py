"""Vault configuration management (.hyperresearch/config.toml)."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class VaultConfig:
    name: str = "Research Base"
    default_status: str = "draft"
    research_dir: str = "research"

    # Search ranking
    search_title_weight: float = 10.0
    search_body_weight: float = 1.0
    search_tags_weight: float = 5.0
    search_aliases_weight: float = 3.0
    search_boost_evergreen: float = 1.5
    search_penalize_deprecated: float = 0.3
    search_penalize_stale: float = 0.7

    # Sync
    auto_sync: bool = True
    exclude_patterns: list[str] = field(
        default_factory=lambda: [
            ".hyperresearch/*", "exports/*", ".git/*", ".venv/*", "node_modules/*", "templates/*",
            "CLAUDE.md", "AGENTS.md", "agents.md", "GEMINI.md", "README.md", "CHANGELOG.md",
        ]
    )

    # Web provider
    web_provider: str = "builtin"

    # Index
    auto_build_index: bool = True
    index_pages: list[str] = field(
        default_factory=lambda: ["_index", "_tags", "_recent", "_orphans", "_stats"]
    )

    @classmethod
    def load(cls, config_path: Path) -> VaultConfig:
        if not config_path.exists():
            return cls()
        with open(config_path, "rb") as f:
            data = tomllib.load(f)

        vault = data.get("vault", {})
        sync = data.get("sync", {})
        index = data.get("index", {})
        search = data.get("search", {})
        web = data.get("web", {})

        return cls(
            name=vault.get("name", cls.name),
            default_status=vault.get("default_status", cls.default_status),
            research_dir=vault.get("research_dir", cls.research_dir),
            search_title_weight=search.get("title_weight", cls.search_title_weight),
            search_body_weight=search.get("body_weight", cls.search_body_weight),
            search_tags_weight=search.get("tags_weight", cls.search_tags_weight),
            search_aliases_weight=search.get("aliases_weight", cls.search_aliases_weight),
            search_boost_evergreen=search.get("boost_evergreen", cls.search_boost_evergreen),
            search_penalize_deprecated=search.get("penalize_deprecated", cls.search_penalize_deprecated),
            search_penalize_stale=search.get("penalize_stale", cls.search_penalize_stale),
            web_provider=web.get("provider", cls.web_provider),
            auto_sync=sync.get("auto_sync", cls.auto_sync),
            exclude_patterns=sync.get("exclude_patterns", cls().exclude_patterns),
            auto_build_index=index.get("auto_build", cls.auto_build_index),
            index_pages=index.get("pages", cls().index_pages),
        )

    @staticmethod
    def _toml_array(items: list[str]) -> str:
        quoted = ", ".join(f'"{item}"' for item in items)
        return f"[{quoted}]"

    def save(self, config_path: Path) -> None:
        lines = [
            "[vault]",
            f'name = "{self.name}"',
            f'default_status = "{self.default_status}"',
            f'research_dir = "{self.research_dir}"',
            "",
            "[search]",
            f"title_weight = {self.search_title_weight}",
            f"body_weight = {self.search_body_weight}",
            f"tags_weight = {self.search_tags_weight}",
            f"aliases_weight = {self.search_aliases_weight}",
            f"boost_evergreen = {self.search_boost_evergreen}",
            f"penalize_deprecated = {self.search_penalize_deprecated}",
            f"penalize_stale = {self.search_penalize_stale}",
            "",
            "[web]",
            f'provider = "{self.web_provider}"',
            "",
            "[sync]",
            f"auto_sync = {'true' if self.auto_sync else 'false'}",
            f"exclude_patterns = {self._toml_array(self.exclude_patterns)}",
            "",
            "[index]",
            f"auto_build = {'true' if self.auto_build_index else 'false'}",
            f"pages = {self._toml_array(self.index_pages)}",
        ]
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text("\n".join(lines) + "\n")
