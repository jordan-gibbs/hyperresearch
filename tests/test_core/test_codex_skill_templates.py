"""Codex renders of the pipeline skill templates.

The skill templates branch on the `platform` render variable. The Claude render
is pinned byte-for-byte by the golden tests (test_prompt_golden.py); this module
checks the Codex render: no Claude-only constructs leak through, and every step
file / custom agent the Codex orchestrator is told to read or spawn exists.
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

# Constructs that only exist on Claude Code. None may appear in a Codex render.
FORBIDDEN = [
    "Skill(",
    "subagent_type",
    ".claude/",
    "Task tool",
    "Task call",
    "Task result",
    "TodoWrite",
    "claude-in-chrome",
    "Claude-in-Chrome",
    "hyperresearch-browser-fetcher",
    "Claude Code",
    "CLAUDE.md",
    "PreToolUse",
    "end_turn",
    "tool-locked",
    "TOOL-LOCKED",
    "[Read, Edit]",
    "[Read, Write]",
    "Edit tool",
]

STEP_FILE_RE = re.compile(r"\.hyperresearch/codex/steps/([a-z0-9-]+)\.md")
AGENT_FILE_RE = re.compile(r"\.codex/agents/([a-z0-9-]+)\.toml")
# A complete hyperresearch-* identifier (not one broken across a line by YAML
# folding, not a `<placeholder>` form).
IDENT_RE = re.compile(r"(?<![-a-z0-9/])hyperresearch-[a-z0-9]+(?:-[a-z0-9]+)*(?![-a-z0-9<])")
# hyperresearch-* strings in the prompts that are neither steps nor agents.
NON_AGENT_IDENTS = {
    "hyperresearch-v8",  # polish: pipeline-vocabulary leak example
    "hyperresearch-locus-seed",  # loci analysis: breadcrumb placeholder to avoid
}


def _agent_names() -> set[str]:
    names = set()
    for attr in dir(hooks):
        value = getattr(hooks, attr)
        if attr.endswith("_AGENT") and isinstance(value, str):
            m = re.search(r"^name: (hyperresearch-[a-z0-9-]+)$", value, re.MULTILINE)
            if m:
                names.add(m.group(1))
    return names


AGENTS = _agent_names()
CODEX_AGENTS = AGENTS - {"hyperresearch-browser-fetcher"}
STEPS = set(hooks._HYPERRESEARCH_STEP_SKILLS)


@pytest.fixture(scope="module", params=PROFILES)
def codex_renders(request):
    ctx = build_render_context(None, primary=request.param, platform="codex")
    return {
        name: render_prompt((SKILLS_DIR / name).read_text(encoding="utf-8"), ctx)
        for name in TEMPLATES
    }


def test_roster_sanity():
    assert "hyperresearch-fetcher" in CODEX_AGENTS
    assert "hyperresearch-patcher" in CODEX_AGENTS
    assert len(STEPS) >= 16
    assert len(TEMPLATES) == len(STEPS) + 1  # step skills + the entry router


@pytest.mark.parametrize("template", TEMPLATES)
def test_codex_render_has_no_claude_constructs(template, codex_renders):
    text = codex_renders[template]
    for needle in FORBIDDEN:
        assert needle not in text, f"{template}: Codex render contains {needle!r}"
    assert not re.search(r"(?<![$\w])/hyperresearch\b", text), (
        f"{template}: Codex render uses the /hyperresearch slash command (use $hyperresearch)"
    )
    assert "<%" not in text and "%>" not in text and "<<" not in text


@pytest.mark.parametrize("template", TEMPLATES)
def test_codex_step_file_references_exist(template, codex_renders):
    for step in STEP_FILE_RE.findall(codex_renders[template]):
        assert step in STEPS, f"{template}: references unknown step file {step}.md"


@pytest.mark.parametrize("template", TEMPLATES)
def test_codex_agent_references_exist(template, codex_renders):
    text = codex_renders[template]
    for agent in AGENT_FILE_RE.findall(text):
        assert agent in CODEX_AGENTS, f"{template}: references unknown custom agent {agent}"
    for ident in IDENT_RE.findall(text):
        assert ident in STEPS or ident in CODEX_AGENTS or ident in NON_AGENT_IDENTS, (
            f"{template}: {ident!r} is neither a step file nor a Codex custom agent"
        )


def test_steps_point_to_next_step_file(codex_renders):
    """Every step template except the last hands off by naming a step file."""
    for template in TEMPLATES:
        if template in ("hyperresearch.md", "hyperresearch-16-readability-audit.md"):
            continue
        assert STEP_FILE_RE.search(codex_renders[template]), template


def test_codex_router_frontmatter_and_enforcement(codex_renders):
    text = codex_renders["hyperresearch.md"]
    fm = yaml.safe_load(text.split("---", 2)[1])
    assert fm["name"] == "hyperresearch"
    assert "hyperresearch" in fm["description"]
    assert len(fm["description"]) <= 1024
    assert "$hyperresearch" in fm["description"]
    # Anti-shortcut + explicit-spawn instructions (the April 2026 bench failure).
    assert "THE JOB IS THE PIPELINE, NOT AN ANSWER" in text
    assert "Stop hook" in text
    assert "Spawning subagents is mandatory" in text
    assert "--target codex" in text
    # Every step in the roster is reachable from the router's table.
    for step in STEPS:
        assert f"`{step}`" in text, step


@pytest.mark.parametrize("template", TEMPLATES)
def test_claude_render_keeps_claude_constructs(template):
    """Sanity check on branch direction: the default render is still Claude's."""
    ctx = build_render_context(None, primary="full")
    text = render_prompt((SKILLS_DIR / template).read_text(encoding="utf-8"), ctx)
    assert "<%" not in text
    assert "Skill(" in text or "Skill tool" in text
    assert ".hyperresearch/codex/" not in text
