"""Vault configuration management (.hyperresearch/config.toml)."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path


@dataclass(frozen=True)
class FetchSettings:
    """Network/browser behavior for web fetching ([fetch] section)."""

    page_timeout_ms: int = 30000
    pdf_timeout_s: int = 30
    # NOTE: default True is a deliberate 2.0 change — the pre-2.0 code silently
    # disabled TLS verification for PDF downloads. Set to false only for
    # cert-broken mirrors you explicitly trust.
    pdf_verify_tls: bool = True
    min_pdf_bytes: int = 100
    # Response-size caps enforced by the SSRF gate (web/safe_http.py).
    # Defaults mirror the MAX_BYTES_* constants there.
    max_html_bytes: int = 10 * 1024 * 1024
    max_pdf_bytes: int = 25 * 1024 * 1024
    max_image_bytes: int = 2 * 1024 * 1024
    # Smart-wait DOM-stability loop (shared by headless and visible paths)
    wait_initial_ms: int = 2000
    poll_interval_ms: int = 500
    stable_checks: int = 2
    max_checks: int = 16
    image_timeout_s: int = 15
    # Sites that kill headless sessions on first contact → auto-visible browser
    visible_browser_domains: tuple[str, ...] = (
        "linkedin.com", "twitter.com", "x.com", "facebook.com",
        "instagram.com", "tiktok.com",
    )


@dataclass(frozen=True)
class JunkGates:
    """Thresholds for the junk/login-wall content gates ([junk] section)."""

    min_content_chars: int = 300
    login_wall_max_chars: int = 1000
    cookie_wall_max_chars: int = 1500
    binary_garbage_ratio: float = 0.05
    sample_window: int = 2000
    login_sample_chars: int = 500
    # Appended to the built-in signal lists — never replacing them
    extra_login_signals: tuple[str, ...] = ()
    extra_junk_signals: tuple[str, ...] = ()


@dataclass(frozen=True)
class AssetSettings:
    """Screenshot/image saving behavior ([assets] section)."""

    max_images: int = 5
    min_image_bytes: int = 50_000


@dataclass(frozen=True)
class DedupSettings:
    """Near-duplicate detection parameters ([dedup] section)."""

    shingle_size: int = 3
    minhash_perm: int = 128
    lsh_bands: int = 16
    lsh_switchover: int = 200
    default_threshold: float = 0.6


@dataclass(frozen=True)
class ChromeSettings:
    """Browser-lane escalation behavior ([chrome] section).

    The Chrome lane drives the user's real browser (via Claude-in-Chrome)
    for sources headless crawling can't reach. `enabled` gates ENQUEUEING
    of blocked fetches; draining requires the Claude-in-Chrome extension.
    Hard scope boundary: CAPTCHAs/2FA/logins are ALWAYS handed to the human
    (`needs_human`) — never solved automatically.
    """

    enabled: bool = True
    # Blocked URLs below this utility score are abandoned, not escalated —
    # the lane is serial and precious. None-scored URLs are escalated.
    escalation_utility_threshold: float = 8.0
    max_items_per_run: int = 25
    drain_batch_size: int = 10
    scholar_enabled: bool = True


@dataclass(frozen=True)
class RankingSettings:
    """Composite source-quality scoring weights ([ranking] section).

    quality = renormalized weighted sum of the available components
    (tier weight, utility/18, authority percentile, vault centrality).
    Missing components renormalize rather than zeroing. Retracted sources
    are floored at `retraction_floor` regardless of other components.
    """

    w_tier: float = 0.35
    w_utility: float = 0.20
    w_authority: float = 0.25
    w_centrality: float = 0.20
    tier_ground_truth: float = 1.0
    tier_institutional: float = 0.85
    tier_practitioner: float = 0.7
    tier_commentary: float = 0.4
    tier_unknown: float = 0.6
    retraction_floor: float = 0.05
    api_cache_ttl_days: int = 30

    def tier_weight(self, tier: str | None) -> float | None:
        if tier is None:
            return None
        return {
            "ground_truth": self.tier_ground_truth,
            "institutional": self.tier_institutional,
            "practitioner": self.tier_practitioner,
            "commentary": self.tier_commentary,
            "unknown": self.tier_unknown,
        }.get(tier)


@dataclass(frozen=True)
class EmbeddingSettings:
    """Semantic-search embedding provider ([embeddings] section).

    provider "none" (default) disables semantic search entirely — no API key
    needed for any core functionality. "voyage" and "openai" call the
    respective APIs (VOYAGE_API_KEY / OPENAI_API_KEY env vars).
    """

    provider: str = "none"  # none | voyage | openai
    model: str = ""  # provider default when empty
    # How much of each note to embed: title + summary + first N body chars
    body_chars: int = 1500


@dataclass(frozen=True)
class LintSettings:
    """Lint rule thresholds ([lint] section)."""

    extract_min_words: int = 150
    extract_coverage_divisor: int = 3
    stale_review_days: int = 90


def _build_section(section_cls, data: dict):
    """Build a frozen settings dataclass from a TOML section dict.

    Unknown keys are ignored (forward compatibility); TOML arrays are converted
    to tuples for tuple-typed fields.
    """
    kwargs = {}
    for f in fields(section_cls):
        if f.name not in data:
            continue
        value = data[f.name]
        if isinstance(value, list):
            value = tuple(value)
        kwargs[f.name] = value
    return section_cls(**kwargs)


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
    # Search output defaults
    search_default_limit: int = 20
    search_chars_per_token: int = 4
    search_snippet_len: int = 200

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
    web_profile: str = ""  # crawl4ai browser profile name (created via `crwl profiles`)
    web_magic: bool = False  # crawl4ai magic mode (anti-bot stealth)

    # Pipeline scale gear ([pipeline] section) — the profile whose numbers are
    # rendered into installed skills/agents. Set via `hpr profile use <name>`.
    pipeline_profile: str = "full"
    # Raw [profile.<name>] overlay tables, round-tripped verbatim on save()
    # so that saving config never destroys user-defined profiles.
    profile_overlays: dict = field(default_factory=dict)

    # Behavior settings sections
    fetch: FetchSettings = field(default_factory=FetchSettings)
    junk: JunkGates = field(default_factory=JunkGates)
    assets: AssetSettings = field(default_factory=AssetSettings)
    dedup: DedupSettings = field(default_factory=DedupSettings)
    lint: LintSettings = field(default_factory=LintSettings)
    ranking: RankingSettings = field(default_factory=RankingSettings)
    embeddings: EmbeddingSettings = field(default_factory=EmbeddingSettings)
    chrome: ChromeSettings = field(default_factory=ChromeSettings)

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
        pipeline = data.get("pipeline", {})

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
            search_default_limit=search.get("default_limit", cls.search_default_limit),
            search_chars_per_token=search.get("chars_per_token", cls.search_chars_per_token),
            search_snippet_len=search.get("snippet_len", cls.search_snippet_len),
            web_provider=web.get("provider", cls.web_provider),
            web_profile=web.get("profile", cls.web_profile),
            web_magic=web.get("magic", cls.web_magic),
            pipeline_profile=pipeline.get("profile", cls.pipeline_profile),
            profile_overlays=data.get("profile", {}),
            fetch=_build_section(FetchSettings, data.get("fetch", {})),
            junk=_build_section(JunkGates, data.get("junk", {})),
            assets=_build_section(AssetSettings, data.get("assets", {})),
            dedup=_build_section(DedupSettings, data.get("dedup", {})),
            lint=_build_section(LintSettings, data.get("lint", {})),
            ranking=_build_section(RankingSettings, data.get("ranking", {})),
            embeddings=_build_section(EmbeddingSettings, data.get("embeddings", {})),
            chrome=_build_section(ChromeSettings, data.get("chrome", {})),
            auto_sync=sync.get("auto_sync", cls.auto_sync),
            exclude_patterns=sync.get("exclude_patterns", cls().exclude_patterns),
            auto_build_index=index.get("auto_build", cls.auto_build_index),
            index_pages=index.get("pages", cls().index_pages),
        )

    @staticmethod
    def _toml_array(items) -> str:
        quoted = ", ".join(f'"{item}"' for item in items)
        return f"[{quoted}]"

    @staticmethod
    def _toml_value(value) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (list, tuple)):
            return "[" + ", ".join(VaultConfig._toml_value(v) for v in value) + "]"
        if isinstance(value, dict):
            inner = ", ".join(f"{k} = {VaultConfig._toml_value(v)}" for k, v in value.items())
            return "{ " + inner + " }"
        if isinstance(value, str):
            return f'"{value}"'
        return str(value)

    def _section_lines(self, header: str, section) -> list[str]:
        lines = [f"[{header}]"]
        for f in fields(section):
            lines.append(f"{f.name} = {self._toml_value(getattr(section, f.name))}")
        lines.append("")
        return lines

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
            f"default_limit = {self.search_default_limit}",
            f"chars_per_token = {self.search_chars_per_token}",
            f"snippet_len = {self.search_snippet_len}",
            "",
            "[web]",
            f'provider = "{self.web_provider}"',
            f'profile = "{self.web_profile}"',
            f"magic = {'true' if self.web_magic else 'false'}",
            "",
            "[pipeline]",
            f'profile = "{self.pipeline_profile}"',
            "",
        ]
        lines += self._section_lines("fetch", self.fetch)
        lines += self._section_lines("junk", self.junk)
        lines += self._section_lines("assets", self.assets)
        lines += self._section_lines("dedup", self.dedup)
        lines += self._section_lines("lint", self.lint)
        lines += self._section_lines("ranking", self.ranking)
        lines += self._section_lines("embeddings", self.embeddings)
        lines += self._section_lines("chrome", self.chrome)
        lines += [
            "[sync]",
            f"auto_sync = {'true' if self.auto_sync else 'false'}",
            f"exclude_patterns = {self._toml_array(self.exclude_patterns)}",
            "",
            "[index]",
            f"auto_build = {'true' if self.auto_build_index else 'false'}",
            f"pages = {self._toml_array(self.index_pages)}",
        ]
        # Round-trip user-defined [profile.<name>] overlays verbatim — losing
        # them on save would silently destroy custom pipeline profiles.
        for overlay_name, table in self.profile_overlays.items():
            lines += ["", f"[profile.{overlay_name}]"]
            lines += [f"{k} = {self._toml_value(v)}" for k, v in table.items()]
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text("\n".join(lines) + "\n")
