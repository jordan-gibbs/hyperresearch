"""OMP renders of the pipeline skill templates.

The OMP target keeps the Codex mechanics (one router skill + plain step files)
with the Claude tool vocabulary (read / write / edit / bash / task). These tests
pin the routing strings the orchestrator needs and prove that no Codex- or
Claude-only construct leaks into an OMP render.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

import hyperresearch
from hyperresearch.core import hooks
from hyperresearch.core.profiles import list_profiles
from hyperresearch.core.render import build_render_context, render_prompt

SKILLS_DIR = Path(hyperresearch.__file__).parent / "skills"
TEMPLATES = sorted(p.name for p in SKILLS_DIR.glob("*.md"))
PROFILES = list_profiles(None)

# Constructs that belong to another runtime. None may appear in an OMP render.
FORBIDDEN = [
    "Skill(",
    "Skill tool",
    "subagent_type",
    ".claude/",
    ".codex/",
    "custom_agent",
    "Task tool",
    "Task call",
    "Task prompt",
    "apply_patch",
    "claude-in-chrome",
    "Claude-in-Chrome",
    "Claude Code",
    "CLAUDE.md",
    "PreToolUse",
    "codex exec",
]

OMP_STEP_FILE_RE = re.compile(r"\.hyperresearch/omp/steps/([a-z0-9-]+)\.md")
# Spawn headers, including placeholder names (`hyperresearch-<critic-name>-critic`).
OMP_AGENT_RE = re.compile(r"^[ \t]*agent: (hyperresearch-[a-z0-9<>-]+)", re.MULTILINE)

STEPS = set(hooks._HYPERRESEARCH_STEP_SKILLS)
# OMP keeps the full roster, browser-fetcher included.
AGENTS = {Path(name).stem for name in hooks._AGENT_FILENAMES.values()}
# hyperresearch-* strings in the prompts that are neither steps nor agents.
NON_AGENT_IDENTS = {
    "hyperresearch-v8",  # polish: pipeline-vocabulary leak example
    "hyperresearch-locus-seed",  # loci analysis: breadcrumb placeholder to avoid
}
IDENT_RE = re.compile(r"(?<![-a-z0-9/])hyperresearch-[a-z0-9]+(?:-[a-z0-9]+)*(?![-a-z0-9<])")


@pytest.fixture(scope="module", params=PROFILES)
def omp_renders(request):
    ctx = build_render_context(None, primary=request.param, platform="omp")
    return {
        name: render_prompt((SKILLS_DIR / name).read_text(encoding="utf-8"), ctx)
        for name in TEMPLATES
    }


def test_roster_sanity():
    assert "hyperresearch-browser-fetcher" in AGENTS
    assert len(AGENTS) == 16
    assert len(TEMPLATES) == len(STEPS) + 1  # step files + the entry router


@pytest.mark.parametrize("template", TEMPLATES)
def test_omp_render_has_no_foreign_constructs(template, omp_renders):
    text = omp_renders[template]
    for forbidden in FORBIDDEN:
        assert forbidden not in text, f"{template}: {forbidden}"
    assert "<%" not in text and "%>" not in text and "<<" not in text


@pytest.mark.parametrize("template", TEMPLATES)
def test_omp_step_file_references_exist(template, omp_renders):
    for step in OMP_STEP_FILE_RE.findall(omp_renders[template]):
        assert step in STEPS, f"{template}: references unknown step file {step}.md"


@pytest.mark.parametrize("template", TEMPLATES)
def test_omp_agent_references_exist(template, omp_renders):
    text = omp_renders[template]
    spawned = {name for name in OMP_AGENT_RE.findall(text) if "<" not in name}
    assert spawned <= AGENTS, f"{template}: unknown agents {spawned - AGENTS}"
    for ident in set(IDENT_RE.findall(text)) - STEPS - AGENTS - NON_AGENT_IDENTS:
        # Every hyperresearch-* identifier is either a step, an agent, or a
        # spawnable agent named in prose (also in AGENTS).
        assert ident in AGENTS, f"{template}: unknown identifier {ident}"


def test_steps_point_to_next_step_file(omp_renders):
    """Every step template except the last hands off by naming a step file."""
    for template in TEMPLATES:
        if template in ("hyperresearch.md", "hyperresearch-16-readability-audit.md"):
            continue
        assert OMP_STEP_FILE_RE.search(omp_renders[template]), template


def test_omp_spawn_templates_use_the_task_wire(omp_renders):
    """Every spawn template names an agent the OMP task tool can dispatch."""
    for template in TEMPLATES:
        text = omp_renders[template]
        if "prompt: |" not in text:
            continue
        assert OMP_AGENT_RE.search(text), template


def test_omp_router_frontmatter_and_enforcement(omp_renders):
    text = omp_renders["hyperresearch.md"]
    fm = yaml.safe_load(text.split("---", 2)[1])
    assert fm["name"] == "hyperresearch"
    assert "/hyperresearch" in fm["description"]
    assert ".hyperresearch/omp/steps/" in fm["description"]
    assert len(fm["description"]) <= 1024
    # Anti-shortcut + explicit-spawn instructions (the April 2026 bench failure).
    assert "THE JOB IS THE PIPELINE, NOT AN ANSWER" in text
    assert "stop-gate extension" in text
    assert "Spawning subagents is mandatory" in text
    assert "--target omp" in text
    assert "omp_step_file" in text
    assert "OMP runtime notes" in text
    assert "solutionSpace" in text
    # Every step in the roster is reachable from the router's table.
    for step in STEPS:
        assert f"`{step}`" in text, step


def test_omp_step_files_are_read_not_invoked(omp_renders):
    """Steps are read with the read tool, never invoked as a skill."""
    for template in TEMPLATES:
        # The router explains the mechanism; step 16 hands back to the entry
        # skill instead of naming a next step file.
        if template in ("hyperresearch.md", "hyperresearch-16-readability-audit.md"):
            continue
        assert "read .hyperresearch/omp/steps/" in omp_renders[template], template


def test_claude_render_keeps_claude_constructs():
    """Sanity check on branch direction: the default render is still Claude's."""
    ctx = build_render_context(None, primary="full")
    for template in TEMPLATES:
        text = render_prompt((SKILLS_DIR / template).read_text(encoding="utf-8"), ctx)
        assert "<%" not in text
        assert "Skill(" in text or "Skill tool" in text
        assert ".hyperresearch/omp/" not in text
