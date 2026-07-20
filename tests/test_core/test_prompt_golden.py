"""Golden tests: rendering the shipped templates with the `full` profile must
reproduce the pre-templating prompt content byte-for-byte.

The golden fixtures under tests/fixtures/golden_prompts/ were snapshotted from
the 1.x (pre-template) prompt sources. Any numeric drift between the built-in
profiles and the templates shows up here as a diff — changing a profile value
or template deliberately requires updating the golden, which makes prompt
changes reviewable instead of silent.

Deliberate deviations already folded into the goldens (2026-07-19):
  - width-sweep: the three inconsistent full-tier source-target statements
    (40-100 / 40–80 / 55–80) were unified to the profile value 55–80; the
    light target 12–20 was unified to the table value 15–25; the tier table's
    full fetchers-per-wave 8–12 was unified to the Wave-1 value 10–12.
  - Phase-2 source-ranking additions (2026-07-19): width-sweep gained the
    utility-scores-travel-with-URLs rule and step 2.7 (persist ranking
    signals: claims ingest / backfill-doi / sources score / graph rank);
    triple-draft 10.2 gained ranked-curation via `search --ranked`; the
    fetcher agent gained the `--utility-score` pass-through section.
  - Phase-3 per-run workspaces (2026-07-19): every run-scoped artifact path
    moved from flat research/ to research/runs/<vault_tag>/ (query file is
    now runs/<tag>/query.md) across ALL skills and agent prompts; the router
    gained bootstrap step 2.5 (`hpr run init`), manifest-first recovery, and
    the dissertation tier row + step 1.5 (chapter partition).
  - Phase-4 browser lane (2026-07-19): width-sweep gained step 2.8 (drain
    the escalation queue via ONE browser-fetcher; consolidated needs_human
    prompt; run block --on human-challenges for non-interactive runs); the
    router gained the "Browser-lane escalations" section; new
    BROWSER_FETCHER_AGENT golden.
  - Phase-5 verification (2026-07-19): router tier sequences gained step
    14.5 (cite-check) and the final gate gained `run verify`, the
    retraction sweep, and the three verification lint rules; new
    CITE_CHECKER_AGENT golden.
  - Scale gears (2026-07-19): the router gained the "Scale gear (tier ≠
    gear)" section (full vs premier, `profile use`), premier in the run-init
    profile list, and a gear-aware frontmatter description; width-sweep's
    diminishing-returns note now cites the gear ceiling instead of the
    hardcoded "~65 reference / beyond ~80" full-scale prose. The `full.*`
    template refs that meant "the installed scale" became `p.*` — byte-
    identical under the default gear (verified by these goldens), truthful
    under `premier`.
  - ModelMap wiring + dollar-cost removal (2026-07-19): every agent's
    `model:` frontmatter line became `<< p.models.X >>` (rendered from the
    profile's ModelMap — same values under `full`, but now overridable, e.g.
    a haiku fetcher); "Runs on Sonnet/Opus" claims left descriptions and
    prose so a model override can't be contradicted by stale text; dollar
    figures were removed repo-wide (the router tier table lost its cost
    column, gap-fetch's "+$1-3 per run" became fetcher-count overhead
    framing, the source-analyst's "$2-5 per spawn" block became "Effort
    discipline", and its Sonnet-1M context claims became model-neutral).
  - Ship-gate enforcement (2026-07-19, after bench Q62 shipped a 25.6K-word
    report with 24 hallucinated-quote lint errors "assessed as false
    positives"): the router's final gate now centers on `run finish` (verify
    + manifest flip, no-override language, bounded fix loop) instead of the
    advisory verify+lint checklist, and invariant 14 makes `passed: true`
    the only definition of complete.
  - Report register + calm citations (2026-07-20, after the Q62 four-report
    comparison showed the judge's only consistent losses were pedagogy and
    readability): the instruction critic gained check R5 (section primers)
    and R2 now counts grouped citation markers (`[7, 12]` = two citations).
    The synthesizer and polish auditor (not golden-covered) gained the
    primer requirement, the calm citation style (grouped brackets, sentence-
    end placement, run consolidation with number-bearing anchors kept), and
    register discipline (meta-discourse ban, hedging discipline, kicker
    rationing) distilled from the humanize-ai-text skill.
  - Run levers (2026-07-20): step 1 now auto-selects register / domain
    notes / inference depth and renders them to shim files via `hpr levers
    render`; the router's spawn contract gained item 4 (paste the role's
    shim verbatim) and invariant 15; every spawning skill's spawn template
    gained a RUN DIRECTIVES paste line (research/drafting/critics/polish
    roles); every shim-receiving agent gained a Run-directives acceptance
    paragraph; the dialectic and instruction critics gained
    register-conditional standards. The cite-checker and
    9-evidence-digest are deliberately untouched (no shim: verification
    is register-independent; step 9 spawns nothing).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from hyperresearch.core import hooks
from hyperresearch.core.hooks import _read_skill_source
from hyperresearch.core.render import build_render_context, render_prompt

GOLDEN_DIR = Path(__file__).parent.parent / "fixtures" / "golden_prompts"

GOLDEN_SKILLS = [
    "hyperresearch",
    "hyperresearch-2-width-sweep",
    "hyperresearch-4-loci-analysis",
    "hyperresearch-5-depth-investigation",
    "hyperresearch-9-evidence-digest",
    "hyperresearch-10-triple-draft",
    "hyperresearch-13-gap-fetch",
    "hyperresearch-16-readability-audit",
]

GOLDEN_AGENTS = [
    "DIALECTIC_CRITIC_AGENT",
    "DEPTH_CRITIC_AGENT",
    "WIDTH_CRITIC_AGENT",
    "INSTRUCTION_CRITIC_AGENT",
    "READABILITY_REFORMATTER_AGENT",
    "RESEARCHER_AGENT",
    "DEPTH_INVESTIGATOR_AGENT",
    "LOCI_ANALYST_AGENT",
    "BROWSER_FETCHER_AGENT",
    "CITE_CHECKER_AGENT",
]


@pytest.fixture(scope="module")
def ctx():
    return build_render_context(None, primary="full")


@pytest.mark.parametrize("skill_name", GOLDEN_SKILLS)
def test_skill_render_matches_golden(skill_name, ctx):
    template = _read_skill_source(f"{skill_name}.md")
    assert template is not None, f"missing skill source {skill_name}.md"
    rendered = render_prompt(template, ctx)
    golden = (GOLDEN_DIR / "skills" / f"{skill_name}.md").read_text(encoding="utf-8")
    assert rendered == golden, (
        f"render(full) of {skill_name}.md deviates from golden. If the change "
        "is deliberate, update tests/fixtures/golden_prompts/skills/ and note "
        "it in the module docstring."
    )


@pytest.mark.parametrize("const_name", GOLDEN_AGENTS)
def test_agent_render_matches_golden(const_name, ctx):
    template = getattr(hooks, const_name)
    rendered = render_prompt(template, ctx)
    golden = (GOLDEN_DIR / "agents" / f"{const_name.lower()}.md").read_text(encoding="utf-8")
    assert rendered == golden, (
        f"render(full) of {const_name} deviates from golden. If the change is "
        "deliberate, update tests/fixtures/golden_prompts/agents/."
    )


@pytest.mark.parametrize("skill_name", GOLDEN_SKILLS)
def test_no_unrendered_variables_in_skills(skill_name, ctx):
    rendered = render_prompt(_read_skill_source(f"{skill_name}.md"), ctx)
    assert "<<" not in rendered and ">>" not in rendered


def test_profile_override_changes_render(tmp_path):
    """End-to-end: a profile overlay must actually change the rendered skill."""
    cfg = tmp_path / "config.toml"
    cfg.write_text("[profile.full]\nsource_min = 200\n", encoding="utf-8")
    ctx = build_render_context(cfg, primary="full")
    rendered = render_prompt(_read_skill_source("hyperresearch-2-width-sweep.md"), ctx)
    assert "| `full` | 200 |" in rendered


@pytest.mark.parametrize("skill_name", GOLDEN_SKILLS)
def test_premier_gear_renders_cleanly(skill_name):
    """Every golden-covered skill must render without holes at premier gear,
    and the scale-bearing ones must carry premier numbers."""
    ctx = build_render_context(None, primary="premier")
    rendered = render_prompt(_read_skill_source(f"{skill_name}.md"), ctx)
    assert "<<" not in rendered and ">>" not in rendered
    if skill_name == "hyperresearch-2-width-sweep":
        assert "| `full` | 90 | 100–130 |" in rendered
        assert "beyond ~130 sources" in rendered
        # The light tier row is gear-independent
        assert "| `light` | 10 | 15–25 |" in rendered
    if skill_name == "hyperresearch":
        assert "currently `premier`" in rendered
        assert "~3–5 hours" in rendered


def test_install_writes_rendered_prompts_with_header(tmp_vault):
    """install_hooks renders templates and stamps the provenance header."""
    from hyperresearch.core.hooks import install_hooks

    install_hooks(tmp_vault.root, hpr_path="hyperresearch")

    critic = (
        tmp_vault.root / ".claude" / "agents" / "hyperresearch-dialectic-critic.md"
    ).read_text(encoding="utf-8")
    assert "At most 12 findings" in critic
    assert 'rendered from profile "full"' in critic
    assert "<<" not in critic

    sweep = (
        tmp_vault.root / ".claude" / "skills" / "hyperresearch-2-width-sweep" / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert "| `full` | 45 | 55–80 | 10–12 | 2–3 |" in sweep
    assert 'rendered from profile "full"' in sweep
    # Header must come after the frontmatter, not before it
    assert sweep.startswith("---")


def test_install_with_profile_overlay(tmp_vault):
    """A vault-config profile overlay flows into installed prompts."""
    from hyperresearch.core.hooks import install_hooks

    cfg_path = tmp_vault.config_path
    cfg_path.write_text(
        cfg_path.read_text(encoding="utf-8") + "\n[profile.full]\nsource_min = 200\n",
        encoding="utf-8",
    )
    install_hooks(tmp_vault.root, hpr_path="hyperresearch")
    sweep = (
        tmp_vault.root / ".claude" / "skills" / "hyperresearch-2-width-sweep" / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert "| `full` | 200 |" in sweep


# ---------------------------------------------------------------------------
# ModelMap wiring — the profile's per-agent model assignments must actually
# reach the installed agent frontmatter (they were decorative before 2.0).
# ---------------------------------------------------------------------------

# Installed agent file -> the ModelMap field that governs its `model:` line.
AGENT_FILE_MODEL_FIELD = {
    "hyperresearch-fetcher.md": "fetcher",
    "hyperresearch-loci-analyst.md": "loci_analyst",
    "hyperresearch-source-analyst.md": "source_analyst",
    "hyperresearch-depth-investigator.md": "depth_investigator",
    "hyperresearch-dialectic-critic.md": "critics",
    "hyperresearch-depth-critic.md": "critics",
    "hyperresearch-width-critic.md": "critics",
    "hyperresearch-instruction-critic.md": "critics",
    "hyperresearch-patcher.md": "patcher",
    "hyperresearch-synthesizer.md": "synthesizer",
    "hyperresearch-polish-auditor.md": "polish_auditor",
    "hyperresearch-readability-recommender.md": "readability_recommender",
    "hyperresearch-cite-checker.md": "cite_checker",
    "hyperresearch-browser-fetcher.md": "browser_fetcher",
    "hyperresearch-corpus-critic.md": "corpus_critic",
    "hyperresearch-draft-orchestrator.md": "draft_orchestrator",
}


def _frontmatter_model(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("model: "):
            return line.removeprefix("model: ").strip()
    raise AssertionError(f"{path.name} has no model: frontmatter line")


def test_installed_agent_models_come_from_profile(tmp_vault):
    """Every installed agent's model: line equals its ModelMap assignment."""
    from hyperresearch.core.hooks import install_hooks
    from hyperresearch.core.profiles import resolve_profile

    install_hooks(tmp_vault.root, hpr_path="hyperresearch")
    models = resolve_profile("full").models
    agents_dir = tmp_vault.root / ".claude" / "agents"
    for filename, field in AGENT_FILE_MODEL_FIELD.items():
        path = agents_dir / filename
        assert path.exists(), f"agent not installed: {filename}"
        assert _frontmatter_model(path) == getattr(models, field), filename


def test_haiku_fetcher_overlay_reaches_installed_agent(tmp_vault):
    """models = { fetcher = "haiku" } must swap ONLY the fetcher's model."""
    from hyperresearch.core.hooks import install_hooks

    cfg_path = tmp_vault.config_path
    cfg_path.write_text(
        cfg_path.read_text(encoding="utf-8")
        + '\n[profile.full]\nmodels = { fetcher = "haiku" }\n',
        encoding="utf-8",
    )
    install_hooks(tmp_vault.root, hpr_path="hyperresearch")
    agents_dir = tmp_vault.root / ".claude" / "agents"
    assert _frontmatter_model(agents_dir / "hyperresearch-fetcher.md") == "haiku"
    assert _frontmatter_model(agents_dir / "hyperresearch-source-analyst.md") == "sonnet"
    assert _frontmatter_model(agents_dir / "hyperresearch-patcher.md") == "opus"


def test_no_hardcoded_model_lines_in_agent_templates():
    """Every `model:` frontmatter line in the hooks.py agent constants must be
    a template ref (`model: << p.models.X >>`), never a literal model name —
    a literal would silently ignore the profile's ModelMap."""
    source = Path(hooks.__file__).read_text(encoding="utf-8")
    bad = [
        line.strip()
        for line in source.splitlines()
        if line.startswith("model: ") and not line.startswith("model: <<")
    ]
    assert not bad, f"hardcoded model lines in hooks.py: {bad}"


# ---------------------------------------------------------------------------
# No-contradiction sweep — rendered prompts must not carry dollar-cost ranges
# (not a bill on subscription billing) or hardcoded model-name claims that a
# ModelMap override would falsify.
# ---------------------------------------------------------------------------

_DOLLAR_RANGE = re.compile(r"\$\d+\s*[-–—]\s*\d+")
_MODEL_CLAIM = re.compile(r"[Rr]uns on (Sonnet|Opus|Haiku)")


def _all_skill_names() -> list[str]:
    import hyperresearch

    skills_dir = Path(hyperresearch.__file__).parent / "skills"
    return sorted(p.name for p in skills_dir.glob("*.md"))


ALL_AGENT_CONSTANTS = [
    "LOCI_ANALYST_AGENT", "DEPTH_INVESTIGATOR_AGENT", "DIALECTIC_CRITIC_AGENT",
    "DEPTH_CRITIC_AGENT", "WIDTH_CRITIC_AGENT", "INSTRUCTION_CRITIC_AGENT",
    "PATCHER_AGENT", "POLISH_AUDITOR_AGENT", "DRAFT_ORCHESTRATOR_AGENT",
    "SYNTHESIZER_AGENT", "READABILITY_REFORMATTER_AGENT", "SOURCE_ANALYST_AGENT",
    "RESEARCHER_AGENT", "CORPUS_CRITIC_AGENT", "BROWSER_FETCHER_AGENT",
    "CITE_CHECKER_AGENT",
]


@pytest.mark.parametrize("skill_file", _all_skill_names())
def test_rendered_skills_have_no_cost_or_model_claims(skill_file, ctx):
    rendered = render_prompt(_read_skill_source(skill_file), ctx)
    assert not _DOLLAR_RANGE.search(rendered), f"dollar-cost range in {skill_file}"
    assert not _MODEL_CLAIM.search(rendered), f"hardcoded model claim in {skill_file}"


@pytest.mark.parametrize("const_name", ALL_AGENT_CONSTANTS)
def test_rendered_agents_have_no_cost_or_model_claims(const_name, ctx):
    rendered = render_prompt(getattr(hooks, const_name), ctx)
    assert not _DOLLAR_RANGE.search(rendered), f"dollar-cost range in {const_name}"
    assert not _MODEL_CLAIM.search(rendered), f"hardcoded model claim in {const_name}"


# ---------------------------------------------------------------------------
# Lever shims: every spawning skill pastes its role's shim file; the
# cite-checker gets none (verification is register-independent).
# ---------------------------------------------------------------------------

_SKILL_SHIM_ROLES = {
    "hyperresearch-2-width-sweep": "research",
    "hyperresearch-4-loci-analysis": "research",
    "hyperresearch-5-depth-investigation": "research",
    "hyperresearch-8-corpus-critic": "research",
    "hyperresearch-13-gap-fetch": "research",
    "hyperresearch-10-triple-draft": "drafting",
    "hyperresearch-11-synthesize": "drafting",
    "hyperresearch-12-critics": "critics",
    "hyperresearch-14-patcher": "critics",
    "hyperresearch-15-polish": "polish",
    "hyperresearch-16-readability-audit": "polish",
}


@pytest.mark.parametrize("skill_name,role", sorted(_SKILL_SHIM_ROLES.items()))
def test_spawning_skills_carry_their_shim_paste_line(skill_name, role, ctx):
    rendered = render_prompt(_read_skill_source(f"{skill_name}.md"), ctx)
    assert f"shims/{role}.md" in rendered, (
        f"{skill_name} spawn template lost its shims/{role}.md paste line"
    )


def test_cite_check_skill_gets_no_shim(ctx):
    rendered = render_prompt(
        _read_skill_source("hyperresearch-14-5-cite-check.md"), ctx
    )
    assert "shims/" not in rendered
