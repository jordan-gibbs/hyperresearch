"""Pipeline profiles — the tunable scale parameters of the research pipeline.

A profile is a named, validated bundle of every knob that governs research
scale: source-count gates, fetcher fan-out, loci caps, depth budgets, draft
counts, word targets, critic caps, and per-agent model assignments.

Built-in profiles `light` and `full` reproduce the V8 pipeline's shipped
values exactly. Users can override keys or define new profiles in
`.hyperresearch/config.toml`:

    [profile.full]                  # tweak a built-in
    source_min = 60

    [profile.dissertation]          # define a new profile
    extends = "full"
    source_min = 250
    loci_max = 20

Profiles are consumed in two places:
  1. Prompt templating (`core/render.py`) — skill/agent prompt templates
     reference profile values at install-render time.
  2. `hpr profile show <name> -j` — agents read the resolved profile at run
     time when they need a number the rendered prose doesn't carry.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

Range = tuple[int, int]


class ModelMap(BaseModel):
    """Per-agent model assignments, rendered into installed agent frontmatter.

    Values are whatever Claude Code accepts in an agent's `model:` line — an
    alias (`haiku`, `sonnet`, `opus`) or a full model ID. Override per agent
    in a `[profile.<name>]` overlay:

        [profile.premier]
        models = { fetcher = "haiku" }

    Unspecified agents keep their defaults (the dict replaces wholesale, then
    defaults fill the gaps).
    """

    model_config = ConfigDict(extra="forbid", frozen=True, protected_namespaces=())

    fetcher: str = "sonnet"
    source_analyst: str = "sonnet"
    loci_analyst: str = "sonnet"
    depth_investigator: str = "sonnet"
    corpus_critic: str = "sonnet"
    cite_checker: str = "sonnet"
    browser_fetcher: str = "sonnet"
    draft_orchestrator: str = "opus"
    synthesizer: str = "opus"
    critics: str = "opus"
    patcher: str = "opus"
    polish_auditor: str = "opus"
    readability_recommender: str = "opus"

    @field_validator("*")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not isinstance(v, str) or not v.strip():
            raise ValueError("model assignment must be a non-empty string")
        return v.strip()


class Profile(BaseModel):
    """One resolved pipeline profile. All ranges are (low, high) inclusive."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    extends: str | None = None
    # One-line human description shown by `hpr profile list`.
    description: str = ""

    # Step routing
    steps: tuple[int, ...]

    # Chaptered execution (dissertation-scale). chapters == (0, 0) means
    # unchaptered — the classic flat pipeline. When non-zero, the router
    # invokes step 1.5 (chapter partition) after decompose and loops steps
    # 2-10 per chapter, each chapter staying within chapter_source_target.
    chapters: Range = (0, 0)
    chapter_concurrency: int = 1
    chapter_source_target: Range = (40, 80)

    # Step 2 — width sweep
    source_min: int
    source_target: Range
    planned_searches: Range
    candidate_urls: Range
    deduped_urls: Range
    batch_size: Range
    batch_count: Range
    waves: Range
    wave1_fetchers: Range
    wave2_fetchers: Range
    wave3_fetchers: Range
    adversarial_searches_min: int
    utility_scoring: bool
    source_analyst_cap: int
    source_analyst_word_trigger: int
    fetcher_chase: Range
    fetcher_chase_cap: int

    # Steps 4-5 — loci + depth
    loci_analysts: int
    loci_max: int
    depth_budget_total: int
    # (min_composite_score, max_source_budget) rows, highest bracket first
    depth_budget_brackets: tuple[Range, ...]
    investigator_max: int
    depth_default_budget: int

    # Steps 6-8 — tensions + corpus critic
    comparisons_tensions: Range
    source_tensions: Range
    tension_survey: Range
    tension_full_reads: Range
    corpus_critic_gaps: Range
    corpus_critic_fetchers: Range

    # Step 9 — evidence digest
    claims_cap: Range
    claims_min: int

    # Steps 10-11 — drafting + synthesis
    draft_count: int
    single_draft_reads: Range
    must_read: dict[str, Range]
    word_targets: dict[str, Range]
    citation_density_min: float
    citation_totals: dict[str, Range]

    # Steps 12-16 — critics, gap-fetch, readability
    critic_finding_caps: dict[str, int]
    gap_fetch_cap: int
    gap_fetch_fetchers: Range
    readability_rec_cap: int

    # Pacing + expectations
    vault_check_interval_s: int
    wave_done_ratio: float
    time_estimate: str

    models: ModelMap = Field(default_factory=ModelMap)

    @field_validator(
        "source_target", "planned_searches", "candidate_urls", "deduped_urls",
        "batch_size", "batch_count", "waves", "wave1_fetchers", "wave2_fetchers",
        "wave3_fetchers", "fetcher_chase", "comparisons_tensions", "source_tensions",
        "tension_survey", "tension_full_reads", "corpus_critic_gaps",
        "corpus_critic_fetchers", "claims_cap", "single_draft_reads", "gap_fetch_fetchers",
        "chapters", "chapter_source_target",
    )
    @classmethod
    def _range_ordered(cls, v: Range) -> Range:
        low, high = v
        if low > high:
            raise ValueError(f"range low {low} > high {high}")
        return v

    @field_validator("steps")
    @classmethod
    def _steps_valid(cls, v: tuple[int, ...]) -> tuple[int, ...]:
        if not v:
            raise ValueError("steps must not be empty")
        for s in v:
            if not 1 <= s <= 16:
                raise ValueError(f"step {s} out of range 1-16")
        if list(v) != sorted(v):
            raise ValueError("steps must be ascending")
        return v


# ---------------------------------------------------------------------------
# Built-in profiles — values are the V8 pipeline's shipped constants.
# The prompt-template golden tests pin these: changing a value here without
# updating the golden fixtures is a test failure, not a silent drift.
# ---------------------------------------------------------------------------

_FULL: dict = {
    "name": "full",
    "description": "The standard adversarially-audited pipeline — 55–80 sources, triple draft, full critic suite.",
    "steps": tuple(range(1, 17)),
    "source_min": 45,
    "source_target": (55, 80),
    "planned_searches": (40, 100),
    "candidate_urls": (80, 120),
    "deduped_urls": (60, 100),
    "batch_size": (8, 12),
    "batch_count": (10, 12),
    "waves": (2, 3),
    "wave1_fetchers": (10, 12),
    "wave2_fetchers": (3, 5),
    "wave3_fetchers": (2, 3),
    "adversarial_searches_min": 5,
    "utility_scoring": True,
    "source_analyst_cap": 6,
    "source_analyst_word_trigger": 5000,
    "fetcher_chase": (3, 8),
    "fetcher_chase_cap": 8,
    "loci_analysts": 2,
    "loci_max": 6,
    "depth_budget_total": 40,
    "depth_budget_brackets": ((30, 15), (20, 10), (10, 5), (0, 3)),
    "investigator_max": 6,
    "depth_default_budget": 10,
    "comparisons_tensions": (3, 5),
    "source_tensions": (3, 7),
    "tension_survey": (15, 20),
    "tension_full_reads": (8, 12),
    "corpus_critic_gaps": (3, 8),
    "corpus_critic_fetchers": (2, 4),
    "claims_cap": (80, 120),
    "claims_min": 30,
    "draft_count": 3,
    "single_draft_reads": (8, 15),
    "must_read": {"argumentative": (35, 50), "structured": (25, 40), "short": (20, 30)},
    "word_targets": {"short": (500, 2000), "structured": (2000, 5000), "argumentative": (5000, 10000)},
    "citation_density_min": 2.0,
    "citation_totals": {"argumentative": (80, 150), "structured": (40, 80), "short": (15, 30)},
    "critic_finding_caps": {"dialectic": 12, "depth": 12, "width": 10, "instruction": 15},
    "gap_fetch_cap": 5,
    "gap_fetch_fetchers": (2, 4),
    "readability_rec_cap": 50,
    "vault_check_interval_s": 60,
    "wave_done_ratio": 0.8,
    "time_estimate": "~1.5–2.5 hours",
}

_LIGHT: dict = {
    **_FULL,
    "name": "light",
    "description": "Fast bounded answers — 5 steps, single draft, 15–25 sources, no critics.",
    "steps": (1, 2, 10, 15, 16),
    "source_min": 10,
    "source_target": (15, 25),
    "planned_searches": (8, 20),
    "candidate_urls": (20, 40),
    "deduped_urls": (15, 30),
    "batch_count": (2, 3),
    "waves": (1, 2),
    "wave1_fetchers": (3, 5),
    "utility_scoring": False,
    "draft_count": 1,
    "time_estimate": "~30–40 min",
}

_PREMIER: dict = {
    **_FULL,
    "name": "premier",
    "description": "Maximum flat-pipeline scale — 100–130 sources, double depth budget, extended reports.",
    # Width: roughly double the sweep. Every funnel stage downstream is widened
    # too — raising only the fetch targets would strand the extra corpus in the
    # vault (draft readers, claims caps, and word targets gate what reaches the
    # page).
    "source_min": 90,
    "source_target": (100, 130),
    "planned_searches": (80, 160),
    "candidate_urls": (150, 220),
    "deduped_urls": (120, 180),
    "batch_count": (14, 18),
    "wave1_fetchers": (14, 18),
    "wave2_fetchers": (5, 8),
    "wave3_fetchers": (3, 5),
    "adversarial_searches_min": 8,
    "source_analyst_cap": 10,
    # Depth: more loci, double the depth budget
    "loci_analysts": 3,
    "loci_max": 10,
    "depth_budget_total": 80,
    "depth_budget_brackets": ((30, 25), (20, 15), (10, 8), (0, 5)),
    "investigator_max": 10,
    "depth_default_budget": 15,
    # Tensions + corpus critic
    "comparisons_tensions": (4, 7),
    "source_tensions": (4, 9),
    "tension_survey": (20, 30),
    "tension_full_reads": (10, 15),
    "corpus_critic_gaps": (4, 10),
    "corpus_critic_fetchers": (3, 5),
    # Evidence funnel
    "claims_cap": (150, 220),
    "claims_min": 50,
    "must_read": {"argumentative": (50, 70), "structured": (35, 55), "short": (20, 30)},
    "word_targets": {"short": (500, 2000), "structured": (3000, 8000), "argumentative": (8000, 16000)},
    "citation_totals": {"argumentative": (120, 220), "structured": (60, 110), "short": (15, 30)},
    "critic_finding_caps": {"dialectic": 16, "depth": 16, "width": 14, "instruction": 18},
    "gap_fetch_cap": 8,
    "gap_fetch_fetchers": (3, 5),
    "readability_rec_cap": 60,
    # Longer waves → slightly relaxed pacing
    "vault_check_interval_s": 90,
    "time_estimate": "~3–5 hours",
}

_DISSERTATION: dict = {
    **_FULL,
    "name": "dissertation",
    "description": "Chaptered dissertation-scale runs — 300–450 sources across 4–10 chapters, 25K–80K words.",
    # Chaptered: steps 2-10 loop per chapter; global reconcile/synthesis on top.
    "chapters": (4, 10),
    "chapter_concurrency": 2,
    "chapter_source_target": (40, 80),
    # Global totals — allocated per chapter, each within the proven envelope.
    "source_min": 250,
    "source_target": (300, 450),
    "loci_max": 20,
    "depth_budget_total": 160,
    "claims_cap": (400, 600),
    "claims_min": 100,
    # One draft per chapter; angle diversity comes from the chapters themselves.
    "draft_count": 1,
    "must_read": {
        **_FULL["must_read"],
        "dissertation": (35, 50),  # per-chapter reading list
    },
    "word_targets": {
        **_FULL["word_targets"],
        "dissertation": (25000, 80000),
    },
    "citation_totals": {
        **_FULL["citation_totals"],
        "dissertation": (300, 600),
    },
    "critic_finding_caps": {"dialectic": 24, "depth": 24, "width": 20, "instruction": 30},
    "gap_fetch_cap": 10,
    "readability_rec_cap": 100,
    # Multi-hour pacing
    "vault_check_interval_s": 120,
    "time_estimate": "~4–8 hours",
}

# Listed in ascending scale order — `hpr profile list` follows this order.
BUILTIN_PROFILES: dict[str, dict] = {
    "light": _LIGHT,
    "full": _FULL,
    "premier": _PREMIER,
    "dissertation": _DISSERTATION,
}

# Profiles that make sense as the installed scale "gear" — the profile whose
# numbers get rendered into the step skills and agent prompts (`p.*`).
# `light` and `dissertation` are run-time TIERS: light is auto-classified by
# step 1, dissertation is opt-in per run (its chapter loop reads
# `dissertation.*` values by name and runs each chapter inside the gear's
# envelope). Installing either AS the gear would bake the wrong numbers into
# the flat pipeline.
GEAR_PROFILES: tuple[str, ...] = ("full", "premier")


class ProfileError(Exception):
    """Raised for unknown profiles or invalid profile definitions."""


def _load_user_overlays(config_path: Path | None) -> dict[str, dict]:
    """Read `[profile.<name>]` tables from a config.toml. Missing file → {}."""
    if config_path is None or not config_path.exists():
        return {}
    with open(config_path, "rb") as f:
        data = tomllib.load(f)
    profiles = data.get("profile", {})
    if not isinstance(profiles, dict):
        raise ProfileError("[profile] must be a table of profile tables")
    out: dict[str, dict] = {}
    for name, table in profiles.items():
        if not isinstance(table, dict):
            raise ProfileError(f"[profile.{name}] must be a table")
        out[name] = table
    return out


def list_profiles(config_path: Path | None = None) -> list[str]:
    """All available profile names: built-ins plus user-defined."""
    names = dict.fromkeys(BUILTIN_PROFILES)
    names.update(dict.fromkeys(_load_user_overlays(config_path)))
    return list(names)


def resolve_profile(name: str, config_path: Path | None = None) -> Profile:
    """Resolve a profile by name: built-in defaults + user overlay, validated.

    Resolution:
      - built-in name: built-in values, then user `[profile.<name>]` keys on top.
      - new name: must exist in config; starts from its `extends` base
        (default "full"), then its own keys on top.
    """
    overlays = _load_user_overlays(config_path)

    if name in BUILTIN_PROFILES:
        base = dict(BUILTIN_PROFILES[name])
    elif name in overlays:
        extends = overlays[name].get("extends", "full")
        if extends not in BUILTIN_PROFILES:
            raise ProfileError(
                f"profile '{name}' extends unknown base '{extends}' "
                f"(must be one of: {', '.join(BUILTIN_PROFILES)})"
            )
        base = dict(BUILTIN_PROFILES[extends])
    else:
        available = ", ".join(list_profiles(config_path))
        raise ProfileError(f"unknown profile '{name}'. Available: {available}")

    overlay = dict(overlays.get(name, {}))
    overlay.pop("extends", None)

    merged = {**base, **overlay, "name": name}
    if name not in BUILTIN_PROFILES:
        merged["extends"] = overlays[name].get("extends", "full")

    try:
        return Profile(**merged)
    except Exception as exc:
        raise ProfileError(f"invalid profile '{name}': {exc}") from exc
