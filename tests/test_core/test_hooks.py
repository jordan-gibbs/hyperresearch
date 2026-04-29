"""Tests for hook installer and skill file provisioning (hyperresearch roster)."""

from __future__ import annotations

from hyperresearch.core.hooks import (
    _RETIRED_AGENT_FILES,
    _RETIRED_SKILL_DIRS,
    _install_depth_critic_agent,
    _install_depth_investigator_agent,
    _install_dialectic_critic_agent,
    _install_hyperresearch_skill,
    _install_instruction_critic_agent,
    _install_loci_analyst_agent,
    _install_patcher_agent,
    _install_polish_auditor_agent,
    _install_researcher_agent,
    _install_source_analyst_agent,
    _install_width_critic_agent,
    _prune_retired_agents,
    install_hooks,
)

# ---------------------------------------------------------------------------
# Entry skill — installs at both /hyperresearch and /research
# ---------------------------------------------------------------------------


def test_install_hyperresearch_skill_creates_both_aliases(tmp_vault):
    """The entry skill installs at .claude/skills/hyperresearch/SKILL.md and
    .claude/skills/research/SKILL.md so Claude Code registers BOTH
    `/hyperresearch` and `/research` as slash-command triggers. Same content,
    different `name:` frontmatter.
    """
    result = _install_hyperresearch_skill(tmp_vault.root)
    assert result is not None

    hyper_path = tmp_vault.root / ".claude" / "skills" / "hyperresearch" / "SKILL.md"
    research_path = tmp_vault.root / ".claude" / "skills" / "research" / "SKILL.md"
    assert hyper_path.exists()
    assert research_path.exists()

    hyper_body = hyper_path.read_text(encoding="utf-8")
    research_body = research_path.read_text(encoding="utf-8")
    assert "name: hyperresearch" in hyper_body
    assert "name: research" in research_body
    # Body content (everything after the name line) is identical
    assert hyper_body.replace("name: hyperresearch", "") == research_body.replace(
        "name: research", ""
    )

    # Entry skill is the chain router — must reference step skills
    assert "hyperresearch-1-decompose" in hyper_body
    assert "hyperresearch-10-triple-draft" in hyper_body
    assert "hyperresearch-11-synthesize" in hyper_body
    assert "hyperresearch-16-readability-audit" in hyper_body
    # Chain mechanics: must explain Skill tool invocation
    assert "Skill" in hyper_body
    # Patching invariant must appear in the skill prose
    assert "PATCH" in hyper_body
    # The most common V7 failure mode (single-draft instead of ensemble) must be
    # called out by name in the entry skill
    assert "PIPELINE VIOLATION" in hyper_body


def test_install_hyperresearch_skill_idempotent(tmp_vault):
    first = _install_hyperresearch_skill(tmp_vault.root)
    assert first is not None
    second = _install_hyperresearch_skill(tmp_vault.root)
    assert second is None


def test_install_hyperresearch_step_skills_creates_all_16(tmp_vault):
    """Each step skill lives at .claude/skills/hyperresearch-N-name/SKILL.md so the
    orchestrator can invoke it via the Skill tool. All 16 must install on a
    fresh vault."""
    from hyperresearch.core.hooks import (
        _HYPERRESEARCH_STEP_SKILLS,
        _install_hyperresearch_step_skills,
    )

    result = _install_hyperresearch_step_skills(tmp_vault.root)
    assert result is not None
    assert len(_HYPERRESEARCH_STEP_SKILLS) == 16

    skills_root = tmp_vault.root / ".claude" / "skills"
    for skill_name in _HYPERRESEARCH_STEP_SKILLS:
        skill_path = skills_root / skill_name / "SKILL.md"
        assert skill_path.exists(), f"missing step skill: {skill_name}"

        body = skill_path.read_text(encoding="utf-8")
        # Every step skill must have its name in frontmatter so the Skill tool
        # can invoke it
        assert f"name: {skill_name}" in body
        # Every step skill (except 16, the terminal step) must point to the
        # next step via the Skill tool
        if skill_name != "hyperresearch-16-readability-audit":
            assert "Skill" in body


def test_install_hyperresearch_step_skills_idempotent(tmp_vault):
    from hyperresearch.core.hooks import _install_hyperresearch_step_skills

    first = _install_hyperresearch_step_skills(tmp_vault.root)
    assert first is not None
    second = _install_hyperresearch_step_skills(tmp_vault.root)
    assert second is None


# ---------------------------------------------------------------------------
# Subagent installers — per-agent sanity checks
# ---------------------------------------------------------------------------


def test_install_fetcher_agent(tmp_vault):
    result = _install_researcher_agent(tmp_vault.root, "hyperresearch")
    agent_path = tmp_vault.root / ".claude" / "agents" / "hyperresearch-fetcher.md"
    assert agent_path.exists()
    body = agent_path.read_text(encoding="utf-8")
    assert "model: sonnet" in body
    # Summary policy is length-proportional — no hard one-sentence cap.
    # Long sources should get multi-paragraph summaries, short ones stay
    # short. The prompt must discuss both ends of that range AND flag
    # long-source delegation to hyperresearch-source-analyst.
    assert "proportional" in body.lower()
    assert "hyperresearch-source-analyst" in body
    assert "5000 words" in body
    assert result is not None


def test_install_loci_analyst_agent(tmp_vault):
    result = _install_loci_analyst_agent(tmp_vault.root, "hyperresearch")
    agent_path = tmp_vault.root / ".claude" / "agents" / "hyperresearch-loci-analyst.md"
    assert agent_path.exists()
    body = agent_path.read_text(encoding="utf-8")
    assert "model: sonnet" in body
    assert "corpus_evidence" in body
    assert "analyst_id" in body
    assert result is not None


def test_install_depth_investigator_agent(tmp_vault):
    result = _install_depth_investigator_agent(tmp_vault.root, "hyperresearch")
    agent_path = tmp_vault.root / ".claude" / "agents" / "hyperresearch-depth-investigator.md"
    assert agent_path.exists()
    body = agent_path.read_text(encoding="utf-8")
    assert "model: sonnet" in body
    # Depth investigator must have Task tool so it can spawn fetcher subagents
    assert "Task" in body
    assert "interim" in body.lower()
    assert "10 new" in body  # the fetch budget rule
    assert result is not None


def test_install_source_analyst_agent(tmp_vault):
    """The source-analyst reads ONE long source end-to-end on Sonnet's 1M
    context window and produces a structured source-analysis note
    backlinked to the original. Leaf subagent — no Task tool (no
    recursive spawns)."""
    result = _install_source_analyst_agent(tmp_vault.root, "hyperresearch")
    agent_path = tmp_vault.root / ".claude" / "agents" / "hyperresearch-source-analyst.md"
    assert agent_path.exists()
    body = agent_path.read_text(encoding="utf-8")
    assert "model: sonnet" in body
    # Leaf subagent: no Task, cannot spawn other subagents
    assert "tools: Bash, Read, Write" in body
    tools_line = body.split("tools:")[1].split("\n")[0]
    assert "Task" not in tools_line
    # Must produce a source-analysis note (canonical NoteType value)
    assert "source-analysis" in body
    # Structural template sections the prompt mandates
    assert "Thesis / Central claim" in body
    assert "Methodology / Basis of claims" in body
    assert "Key findings" in body
    assert "Load-bearing citations" in body
    assert "Relevance to research_query" in body
    # Backlink mechanism via body breadcrumb (no custom CLI flag needed)
    assert "Suggested by" in body
    # Word-count threshold that decides whether the analyst is appropriate
    assert "5000" in body
    assert result is not None


def test_install_dialectic_critic_agent(tmp_vault):
    result = _install_dialectic_critic_agent(tmp_vault.root, "hyperresearch")
    agent_path = tmp_vault.root / ".claude" / "agents" / "hyperresearch-dialectic-critic.md"
    assert agent_path.exists()
    body = agent_path.read_text(encoding="utf-8")
    assert "model: opus" in body
    # Critics have Bash + Read + Write (Write for JSON output; no Edit
    # since they don't mutate the draft — that's the revisor's job)
    assert "tools: Bash, Read, Write" in body
    assert "recommendation" in body
    assert "location" in body
    assert "surgical" in body.lower()
    assert result is not None


def test_install_depth_critic_agent(tmp_vault):
    result = _install_depth_critic_agent(tmp_vault.root, "hyperresearch")
    agent_path = tmp_vault.root / ".claude" / "agents" / "hyperresearch-depth-critic.md"
    assert agent_path.exists()
    body = agent_path.read_text(encoding="utf-8")
    assert "model: opus" in body
    assert "tools: Bash, Read" in body
    assert "interim" in body.lower()
    assert result is not None


def test_install_width_critic_agent(tmp_vault):
    result = _install_width_critic_agent(tmp_vault.root, "hyperresearch")
    agent_path = tmp_vault.root / ".claude" / "agents" / "hyperresearch-width-critic.md"
    assert agent_path.exists()
    body = agent_path.read_text(encoding="utf-8")
    assert "model: opus" in body
    assert "tools: Bash, Read" in body
    assert "coverage" in body.lower()
    assert result is not None


def test_install_instruction_critic_agent(tmp_vault):
    """Instruction-critic specifically targets the instruction-following
    dimension by checking the draft against prompt-decomposition atomic
    items. Read-only tool lock — it produces findings, never patches."""
    result = _install_instruction_critic_agent(tmp_vault.root, "hyperresearch")
    agent_path = (
        tmp_vault.root / ".claude" / "agents" / "hyperresearch-instruction-critic.md"
    )
    assert agent_path.exists()
    body = agent_path.read_text(encoding="utf-8")
    assert "model: opus" in body
    assert "tools: Bash, Read" in body
    # The critic explicitly consumes the decomposition artifact
    assert "prompt-decomposition.json" in body
    assert "atomic_item" in body
    # Failure modes it tracks
    assert "missing|under-covered|wrong-order|wrong-format" in body
    # Structural-mirror check: runs FIRST, emits findings against
    # required_section_headings. This is the highest-leverage InstF lever.
    assert "STRUCTURAL MIRROR CHECK" in body
    assert "required_section_headings" in body
    # Escalation field for restructures the patcher cannot handle
    assert "requires_orchestrator_restructure" in body
    assert result is not None


def test_install_patcher_agent_is_edit_only(tmp_vault):
    """The revisor (patcher) MUST be tool-locked to Read + Edit only — no
    Write, no Bash. This is the load-bearing invariant that enforces
    REVISE-NOT-REGEN."""
    result = _install_patcher_agent(tmp_vault.root, "hyperresearch")
    agent_path = tmp_vault.root / ".claude" / "agents" / "hyperresearch-patcher.md"
    assert agent_path.exists()
    body = agent_path.read_text(encoding="utf-8")
    # Opus: substance-integration judgment about which findings serve
    # the research_query is a reasoning task Sonnet underperforms on.
    assert "model: opus" in body
    # Tool lock: must be exactly "Read, Edit" — not Write, not Bash. The
    # tool lock is what enforces the no-regeneration invariant.
    assert "tools: Read, Edit" in body
    assert "tools: Bash" not in body
    assert "Write" not in body.split("tools:")[1].split("\n")[0]
    assert "regenerat" in body.lower()  # the invariant spelled out
    assert "surgical" in body.lower()
    # Integrate-don't-caveat rule lifts insight score by preventing
    # hedge-appending edits that dilute committed claims.
    assert "Integrate, don't caveat" in body
    assert "scoping the claim" in body
    # Dynamic revision: revisor reads findings with location/issue/
    # recommendation fields and applies edits using its own judgment.
    assert "location" in body
    assert "recommendation" in body
    assert "requires_orchestrator_restructure" in body
    assert result is not None


def test_install_polish_auditor_agent_is_edit_only(tmp_vault):
    """The polish auditor is the second tool-locked [Read, Edit] agent.
    Same invariant: no regeneration path."""
    result = _install_polish_auditor_agent(tmp_vault.root, "hyperresearch")
    agent_path = tmp_vault.root / ".claude" / "agents" / "hyperresearch-polish-auditor.md"
    assert agent_path.exists()
    body = agent_path.read_text(encoding="utf-8")
    # Opus: semantic rewrites of scaffold vocabulary + hedge-language
    # judgment need strong prose comprehension.
    assert "model: opus" in body
    assert "tools: Read, Edit" in body
    assert "tools: Bash" not in body
    # scaffold-only section list must be injected
    assert "User Prompt (VERBATIM" in body
    # Hedge-language cutting category — strikes softeners on claims the
    # paragraph already supports with evidence. Highest-leverage polish cut.
    assert "Hedge language that softens committed claims" in body
    assert "suggests that" in body
    assert result is not None


# ---------------------------------------------------------------------------
# Idempotency — at least one agent confirms the pattern holds
# ---------------------------------------------------------------------------


def test_loci_analyst_install_idempotent(tmp_vault):
    first = _install_loci_analyst_agent(tmp_vault.root, "hyperresearch")
    assert first is not None
    second = _install_loci_analyst_agent(tmp_vault.root, "hyperresearch")
    assert second is None


def test_patcher_install_idempotent(tmp_vault):
    first = _install_patcher_agent(tmp_vault.root, "hyperresearch")
    assert first is not None
    second = _install_patcher_agent(tmp_vault.root, "hyperresearch")
    assert second is None


# ---------------------------------------------------------------------------
# Retired-roster pruning
# ---------------------------------------------------------------------------


def test_prune_retired_agents_removes_old_files(tmp_vault):
    """Pre-hyperresearch vaults have analyst/auditor/rewriter/subrun/merger agent
    files and a research-ensemble skill dir. Installing onto such a vault
    must prune those so the installed state matches the current architecture."""
    agents_dir = tmp_vault.root / ".claude" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    for name in _RETIRED_AGENT_FILES:
        (agents_dir / name).write_text("pre-hyperresearch content\n", encoding="utf-8")

    skills_dir = tmp_vault.root / ".claude" / "skills"
    for name in _RETIRED_SKILL_DIRS:
        retired_skill = skills_dir / name
        retired_skill.mkdir(parents=True, exist_ok=True)
        (retired_skill / "SKILL.md").write_text("old skill\n", encoding="utf-8")

    result = _prune_retired_agents(tmp_vault.root)
    assert result is not None
    assert "Pruned retired" in result

    for name in _RETIRED_AGENT_FILES:
        assert not (agents_dir / name).exists(), f"{name} still present"
    for name in _RETIRED_SKILL_DIRS:
        assert not (skills_dir / name).exists(), f"skill dir {name} still present"


def test_prune_retired_agents_noop_on_clean_vault(tmp_vault):
    """On a fresh vault, prune is a no-op."""
    result = _prune_retired_agents(tmp_vault.root)
    assert result is None


# ---------------------------------------------------------------------------
# install_hooks — end-to-end integration
# ---------------------------------------------------------------------------


def test_install_hooks_registers_full_hyperresearch_roster(tmp_vault):
    """install_hooks wires the hook, both entry-skill aliases, and the agent roster."""
    actions = install_hooks(tmp_vault.root, "hyperresearch")
    assert actions  # something happened

    # All agent files must be present
    agents_dir = tmp_vault.root / ".claude" / "agents"
    expected_agents = {
        "hyperresearch-fetcher.md",
        "hyperresearch-loci-analyst.md",
        "hyperresearch-depth-investigator.md",
        "hyperresearch-source-analyst.md",
        "hyperresearch-corpus-critic.md",
        "hyperresearch-dialectic-critic.md",
        "hyperresearch-depth-critic.md",
        "hyperresearch-width-critic.md",
        "hyperresearch-instruction-critic.md",
        "hyperresearch-patcher.md",
        "hyperresearch-polish-auditor.md",
        "hyperresearch-readability-recommender.md",
        "hyperresearch-draft-orchestrator.md",
        "hyperresearch-synthesizer.md",
    }
    actual_agents = {p.name for p in agents_dir.iterdir() if p.is_file()}
    assert expected_agents == actual_agents, (
        f"missing: {expected_agents - actual_agents}, extra: {actual_agents - expected_agents}"
    )

    # Both entry-skill aliases registered (/hyperresearch and /research)
    assert (tmp_vault.root / ".claude" / "skills" / "hyperresearch" / "SKILL.md").exists()
    assert (tmp_vault.root / ".claude" / "skills" / "research" / "SKILL.md").exists()

    # Hook settings written
    assert (tmp_vault.root / ".claude" / "settings.json").exists()
    assert (tmp_vault.root / ".hyperresearch" / "hook.js").exists()


def test_install_hooks_second_run_is_noop(tmp_vault):
    first = install_hooks(tmp_vault.root, "hyperresearch")
    assert first
    second = install_hooks(tmp_vault.root, "hyperresearch")
    # Hook installer may still report the hook is already installed → no
    # actions or a trivial subset. Must not crash, must not reinstall files.
    assert not second or all("pruned" not in a.lower() for a in second)
