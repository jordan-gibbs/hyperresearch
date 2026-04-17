"""Tests for hook installer and skill file provisioning (layercake roster)."""

from __future__ import annotations

from hyperresearch.core.hooks import (
    _RETIRED_AGENT_FILES,
    _RETIRED_SKILL_DIRS,
    _SKILL_FILES,
    _install_depth_critic_agent,
    _install_depth_investigator_agent,
    _install_dialectic_critic_agent,
    _install_layercake_skill,
    _install_loci_analyst_agent,
    _install_patcher_agent,
    _install_polish_auditor_agent,
    _install_research_skill,
    _install_researcher_agent,
    _install_width_critic_agent,
    _prune_retired_agents,
    install_hooks,
)

# ---------------------------------------------------------------------------
# /research skill (single-pass, unchanged)
# ---------------------------------------------------------------------------


def test_install_skill_writes_expected_files(tmp_vault):
    result = _install_research_skill(tmp_vault.root)
    skill_dir = tmp_vault.root / ".claude" / "skills" / "hyperresearch"
    assert skill_dir.is_dir()

    expected = {dest_name for _, dest_name in _SKILL_FILES}
    present = {p.name for p in skill_dir.glob("SKILL*.md")}
    assert expected.issubset(present)
    assert result is not None


def test_install_skill_prunes_stale_files(tmp_vault):
    skill_dir = tmp_vault.root / ".claude" / "skills" / "hyperresearch"
    skill_dir.mkdir(parents=True, exist_ok=True)

    stale_names = [
        "SKILL-humanities.md",
        "SKILL-academic.md",
        "SKILL-landscape.md",
        "SKILL-technical.md",
        "SKILL-ensemble.md",  # pre-layercake stale file
    ]
    for name in stale_names:
        (skill_dir / name).write_text("stale content\n", encoding="utf-8")

    result = _install_research_skill(tmp_vault.root)

    remaining = {p.name for p in skill_dir.glob("SKILL*.md")}
    expected = {dest_name for _, dest_name in _SKILL_FILES}
    assert remaining == expected
    for name in stale_names:
        assert not (skill_dir / name).exists(), f"stale file {name} still present"
    assert result is not None
    assert "pruned" in result


def test_install_skill_idempotent_second_run(tmp_vault):
    first = _install_research_skill(tmp_vault.root)
    assert first is not None
    second = _install_research_skill(tmp_vault.root)
    assert second is None, "second run should report no changes"


# ---------------------------------------------------------------------------
# /research-layercake skill
# ---------------------------------------------------------------------------


def test_install_layercake_skill_creates_separate_skill_dir(tmp_vault):
    """Layercake skill lives at .claude/skills/research-layercake/SKILL.md so
    Claude Code registers `/research-layercake` as its own slash-command trigger."""
    result = _install_layercake_skill(tmp_vault.root)
    own_dir_path = tmp_vault.root / ".claude" / "skills" / "research-layercake" / "SKILL.md"
    assert own_dir_path.exists()

    body = own_dir_path.read_text(encoding="utf-8")
    assert "name: research-layercake" in body
    assert "hyperresearch-loci-analyst" in body
    assert "hyperresearch-depth-investigator" in body
    assert "hyperresearch-patcher" in body
    assert "hyperresearch-polish-auditor" in body
    # Patching invariant must appear in the skill prose
    assert "PATCH" in body
    assert result is not None


def test_install_layercake_skill_idempotent(tmp_vault):
    first = _install_layercake_skill(tmp_vault.root)
    assert first is not None
    second = _install_layercake_skill(tmp_vault.root)
    assert second is None


# ---------------------------------------------------------------------------
# Subagent installers — per-agent sanity checks
# ---------------------------------------------------------------------------


def test_install_fetcher_agent(tmp_vault):
    result = _install_researcher_agent(tmp_vault.root, "hyperresearch")
    agent_path = tmp_vault.root / ".claude" / "agents" / "hyperresearch-fetcher.md"
    assert agent_path.exists()
    body = agent_path.read_text(encoding="utf-8")
    assert "model: haiku" in body
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


def test_install_dialectic_critic_agent(tmp_vault):
    result = _install_dialectic_critic_agent(tmp_vault.root, "hyperresearch")
    agent_path = tmp_vault.root / ".claude" / "agents" / "hyperresearch-dialectic-critic.md"
    assert agent_path.exists()
    body = agent_path.read_text(encoding="utf-8")
    assert "model: opus" in body
    # Critics MUST NOT have Edit or Write — only Bash + Read
    # (they produce JSON findings, they don't mutate the draft)
    assert "tools: Bash, Read" in body
    assert "suggested_patch" in body
    assert "500" in body  # the hunk size constraint
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


def test_install_patcher_agent_is_edit_only(tmp_vault):
    """The patcher MUST be tool-locked to Read + Edit only — no Write, no
    Bash. This is the load-bearing invariant that enforces PATCH-NOT-REGEN."""
    result = _install_patcher_agent(tmp_vault.root, "hyperresearch")
    agent_path = tmp_vault.root / ".claude" / "agents" / "hyperresearch-patcher.md"
    assert agent_path.exists()
    body = agent_path.read_text(encoding="utf-8")
    assert "model: sonnet" in body
    # Tool lock: must be exactly "Read, Edit" — not Write, not Bash
    assert "tools: Read, Edit" in body
    assert "tools: Bash" not in body
    assert "Write" not in body.split("tools:")[1].split("\n")[0]
    assert "500" in body  # hunk size rule
    assert "regenerat" in body.lower()  # the invariant spelled out
    # Integrate-don't-caveat rule lifts insight score by preventing
    # hedge-appending patches that dilute committed claims.
    assert "Integrate, don't caveat" in body
    assert "scoping the claim" in body
    assert result is not None


def test_install_polish_auditor_agent_is_edit_only(tmp_vault):
    """The polish auditor is the second tool-locked [Read, Edit] agent.
    Same invariant: no regeneration path."""
    result = _install_polish_auditor_agent(tmp_vault.root, "hyperresearch")
    agent_path = tmp_vault.root / ".claude" / "agents" / "hyperresearch-polish-auditor.md"
    assert agent_path.exists()
    body = agent_path.read_text(encoding="utf-8")
    assert "model: sonnet" in body
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
    """Pre-layercake vaults have analyst/auditor/rewriter/subrun/merger agent
    files and a research-ensemble skill dir. Installing onto such a vault
    must prune those so the installed state matches the current architecture."""
    agents_dir = tmp_vault.root / ".claude" / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    for name in _RETIRED_AGENT_FILES:
        (agents_dir / name).write_text("pre-layercake content\n", encoding="utf-8")

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


def test_install_hooks_registers_full_layercake_roster(tmp_vault):
    """install_hooks wires the hook + both skills + all 8 layercake agents."""
    actions = install_hooks(tmp_vault.root, "hyperresearch")
    assert actions  # something happened

    # All 8 agent files must be present
    agents_dir = tmp_vault.root / ".claude" / "agents"
    expected_agents = {
        "hyperresearch-fetcher.md",
        "hyperresearch-loci-analyst.md",
        "hyperresearch-depth-investigator.md",
        "hyperresearch-dialectic-critic.md",
        "hyperresearch-depth-critic.md",
        "hyperresearch-width-critic.md",
        "hyperresearch-patcher.md",
        "hyperresearch-polish-auditor.md",
    }
    actual_agents = {p.name for p in agents_dir.iterdir() if p.is_file()}
    assert expected_agents == actual_agents, (
        f"missing: {expected_agents - actual_agents}, extra: {actual_agents - expected_agents}"
    )

    # Both skill entry points registered
    assert (tmp_vault.root / ".claude" / "skills" / "hyperresearch" / "SKILL.md").exists()
    assert (
        tmp_vault.root / ".claude" / "skills" / "research-layercake" / "SKILL.md"
    ).exists()

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
