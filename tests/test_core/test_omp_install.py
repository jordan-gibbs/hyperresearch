"""OMP target: translated skill/step renders, agent files, install trees, stop gate.

OMP renders the Codex branches of the templates and translates them
(core/omp.py). These tests check what an OMP session actually receives: no
Claude Code or Codex constructs, every step file and agent it is told to use
exists, agents carry OMP tool names, and the stop gate names OMP step files.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.core.hooks import (
    _HYPERRESEARCH_STEP_SKILLS,
    install_global_hooks,
    install_hooks,
)

runner = CliRunner()

EXPECTED_AGENTS = {
    "hyperresearch-fetcher",
    "hyperresearch-loci-analyst",
    "hyperresearch-depth-investigator",
    "hyperresearch-source-analyst",
    "hyperresearch-corpus-critic",
    "hyperresearch-dialectic-critic",
    "hyperresearch-depth-critic",
    "hyperresearch-width-critic",
    "hyperresearch-instruction-critic",
    "hyperresearch-patcher",
    "hyperresearch-polish-auditor",
    "hyperresearch-readability-recommender",
    "hyperresearch-draft-orchestrator",
    "hyperresearch-synthesizer",
    "hyperresearch-cite-checker",
}

# Constructs from the other runtimes. None may reach an OMP session.
FORBIDDEN = [
    # Claude Code
    "Skill(",
    "subagent_type",
    ".claude/",
    "TodoWrite",
    "Claude-in-Chrome",
    "hyperresearch-browser-fetcher",
    "CLAUDE.md",
    # Codex
    "Codex",
    "codex",
    "apply_patch",
    "update_plan",
    "custom_agent",
    "custom agent",
    ".toml",
    "$hyperresearch",
    ".agents/skills",
    "hooks.json",
]

STEP_FILE_RE = re.compile(r"\.hyperresearch/omp/steps/([a-z0-9-]+)\.md")
AGENT_REF_RE = re.compile(r"(?:agent: |OMP agent `)(hyperresearch-[a-z0-9-]+)")


@pytest.fixture(scope="module")
def omp_tree(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("omp-project")
    install_hooks(root, "/opt/hpr/hyperresearch", platform="omp")
    return root


def _rendered_skills(root: Path) -> dict[str, str]:
    files = {"hyperresearch": root / ".omp" / "skills" / "hyperresearch" / "SKILL.md"}
    for name in _HYPERRESEARCH_STEP_SKILLS:
        files[name] = root / ".hyperresearch" / "omp" / "steps" / f"{name}.md"
    return {name: path.read_text(encoding="utf-8") for name, path in files.items()}


def test_omp_renders_carry_no_foreign_constructs(omp_tree):
    leaks = {
        name: [token for token in FORBIDDEN if token in text]
        for name, text in _rendered_skills(omp_tree).items()
    }
    assert {name: found for name, found in leaks.items() if found} == {}


def test_omp_renders_reference_only_installed_steps_and_agents(omp_tree):
    agents = {p.stem for p in (omp_tree / ".omp" / "agents").glob("*.md")}
    assert agents == EXPECTED_AGENTS
    for name, text in _rendered_skills(omp_tree).items():
        for step in STEP_FILE_RE.findall(text):
            assert step in _HYPERRESEARCH_STEP_SKILLS, f"{name}: unknown step file {step}.md"
        for agent in AGENT_REF_RE.findall(text):
            assert agent in agents, f"{name}: spawns unknown agent {agent}"


def test_omp_entry_skill_is_an_omp_skill(omp_tree):
    text = (omp_tree / ".omp" / "skills" / "hyperresearch" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    meta = yaml.safe_load(text.split("---")[1])
    assert meta["name"] == "hyperresearch"
    assert "/skill:hyperresearch" in meta["description"]
    assert "--target omp" in text  # the bootstrap installs OMP step files


def _agent(root: Path, name: str) -> tuple[dict, str]:
    text = (root / ".omp" / "agents" / f"{name}.md").read_text(encoding="utf-8")
    _, front, body = text.split("---", 2)
    return yaml.safe_load(front), body


def test_omp_agents_carry_omp_tools_and_no_model(omp_tree):
    patcher, patcher_body = _agent(omp_tree, "hyperresearch-patcher")
    assert patcher["tools"] == ["read", "edit"]  # the Read+Edit lock carries over
    assert "model" not in patcher  # runs on the session's model, Claude or OpenAI
    assert patcher["read-summarize"] is False
    assert patcher["thinking-level"] == "high"
    assert "cannot spawn subagents" in patcher_body

    fetcher, _ = _agent(omp_tree, "hyperresearch-fetcher")
    assert fetcher["tools"] == ["bash", "read", "write", "web_search"]
    assert fetcher["thinking-level"] == "medium"

    investigator, _ = _agent(omp_tree, "hyperresearch-depth-investigator")
    assert "task" in investigator["tools"]
    assert investigator["spawns"] == ["hyperresearch-fetcher"]


def test_omp_project_install_writes_no_docs_file(tmp_path):
    install_hooks(tmp_path, "hyperresearch", platform="omp")
    assert (tmp_path / ".omp" / "extensions" / "hyperresearch.ts").is_file()
    assert not (tmp_path / "AGENTS.md").exists()
    assert not (tmp_path / "CLAUDE.md").exists()
    assert not (tmp_path / ".omp" / "AGENTS.md").exists()


def test_omp_global_install_goes_to_the_agent_dir(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)

    actions = install_global_hooks(home, "/opt/hpr/hyperresearch", platform="omp")

    agent_dir = home / ".omp" / "agent"
    assert actions
    assert (agent_dir / "skills" / "hyperresearch" / "SKILL.md").is_file()
    assert {p.stem for p in (agent_dir / "agents").glob("*.md")} == EXPECTED_AGENTS
    extension = (agent_dir / "extensions" / "hyperresearch.ts").read_text(encoding="utf-8")
    assert '"/opt/hpr/hyperresearch"' in extension
    # Global: no step files, nothing outside the OMP agent directory.
    assert sorted(p.name for p in home.iterdir()) == [".omp"]
    assert install_global_hooks(home, "/opt/hpr/hyperresearch", platform="omp") == []


def test_omp_global_install_honours_pi_coding_agent_dir(tmp_path, monkeypatch):
    agent_dir = tmp_path / "custom-agent-dir"
    monkeypatch.setenv("PI_CODING_AGENT_DIR", str(agent_dir))
    install_global_hooks(tmp_path / "home", "hyperresearch", platform="omp")
    assert (agent_dir / "skills" / "hyperresearch" / "SKILL.md").is_file()


def test_omp_prunes_only_its_own_stale_agents(tmp_path):
    agents_dir = tmp_path / ".omp" / "agents"
    agents_dir.mkdir(parents=True)
    ours = agents_dir / "hyperresearch-retired.md"
    ours.write_text(
        "---\nname: hyperresearch-retired\n---\n"
        "<!-- rendered from profile \"full\" (hyperresearch 0.0) -->\n",
        encoding="utf-8",
    )
    theirs = agents_dir / "hyperresearch-mine.md"
    theirs.write_text("---\nname: hyperresearch-mine\n---\nhand-written\n", encoding="utf-8")

    install_hooks(tmp_path, "hyperresearch", platform="omp")

    assert not ours.exists()
    assert theirs.exists()


# ---------------------------------------------------------------------------
# CLI: stop gate for the OMP extension, resume, steps-only, profile use
# ---------------------------------------------------------------------------


@pytest.fixture
def running_vault(tmp_vault, monkeypatch):
    from hyperresearch.core.runs import init_run

    monkeypatch.chdir(tmp_vault.root)
    monkeypatch.delenv("HYPERRESEARCH_STOP_GATE", raising=False)
    init_run(tmp_vault, "omp-run")
    return tmp_vault


def test_stop_gate_cwd_ignores_stdin_and_names_omp_step(running_vault, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # the vault is found from --cwd, not the process cwd
    result = runner.invoke(
        app,
        ["run", "stop-gate", "--cwd", str(running_vault.root), "--platform", "omp"],
        input='{"stop_hook_active": true}',  # would silence the gate if it were read
    )
    assert result.exit_code == 0
    decision = json.loads(result.stdout)
    assert decision["decision"] == "block"
    assert ".hyperresearch/omp/steps/hyperresearch-1-decompose.md" in decision["reason"]


def test_run_resume_includes_omp_step_file(running_vault):
    result = runner.invoke(app, ["run", "resume", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)["data"]
    assert data["omp_step_file"] == ".hyperresearch/omp/steps/hyperresearch-1-decompose.md"


def test_steps_only_omp_writes_just_step_files(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)
    result = runner.invoke(
        app, ["install", str(tmp_vault.root), "--steps-only", "--target", "omp", "--json"]
    )
    assert result.exit_code == 0, result.stdout
    root = tmp_vault.root
    assert (root / ".hyperresearch" / "omp" / "steps" / "hyperresearch-1-decompose.md").is_file()
    assert not (root / ".omp").exists()


def test_profile_use_rerenders_bootstrapped_omp_steps(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)
    runner.invoke(app, ["install", str(tmp_vault.root), "--steps-only", "--target", "omp"])
    result = runner.invoke(app, ["profile", "use", "premier", "--json"])
    assert result.exit_code == 0, result.stdout
    step = tmp_vault.root / ".hyperresearch" / "omp" / "steps" / "hyperresearch-2-width-sweep.md"
    assert 'rendered from profile "premier"' in step.read_text(encoding="utf-8")
    assert not (tmp_vault.root / ".omp").exists()
