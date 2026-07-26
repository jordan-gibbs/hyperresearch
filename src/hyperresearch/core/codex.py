"""Codex integration — install skills and reusable role prompts.

Codex discovers repository skills under ``.agents/skills`` and durable project
instructions in ``AGENTS.md``.  Hyperresearch's Claude integration remains the
default; this module is an additive adapter over the same prompt sources.
"""

from __future__ import annotations

import re
from pathlib import Path

from hyperresearch.core import hooks

_ROLE_PROMPTS: tuple[tuple[str, str, str], ...] = (
    ("hyperresearch-fetcher.md", "fetcher", "RESEARCHER_AGENT"),
    ("hyperresearch-loci-analyst.md", "loci analyst", "LOCI_ANALYST_AGENT"),
    (
        "hyperresearch-depth-investigator.md",
        "depth investigator",
        "DEPTH_INVESTIGATOR_AGENT",
    ),
    ("hyperresearch-source-analyst.md", "source analyst", "SOURCE_ANALYST_AGENT"),
    ("hyperresearch-dialectic-critic.md", "dialectic critic", "DIALECTIC_CRITIC_AGENT"),
    ("hyperresearch-instruction-critic.md", "instruction critic", "INSTRUCTION_CRITIC_AGENT"),
    ("hyperresearch-depth-critic.md", "depth critic", "DEPTH_CRITIC_AGENT"),
    ("hyperresearch-width-critic.md", "width critic", "WIDTH_CRITIC_AGENT"),
    ("hyperresearch-patcher.md", "patcher", "PATCHER_AGENT"),
    ("hyperresearch-polish-auditor.md", "polish auditor", "POLISH_AUDITOR_AGENT"),
    (
        "hyperresearch-readability-recommender.md",
        "readability recommender",
        "READABILITY_REFORMATTER_AGENT",
    ),
    ("hyperresearch-corpus-critic.md", "corpus critic", "CORPUS_CRITIC_AGENT"),
    (
        "hyperresearch-draft-orchestrator.md",
        "draft orchestrator",
        "DRAFT_ORCHESTRATOR_AGENT",
    ),
    ("hyperresearch-synthesizer.md", "synthesizer", "SYNTHESIZER_AGENT"),
    ("hyperresearch-browser-fetcher.md", "browser fetcher", "BROWSER_FETCHER_AGENT"),
    ("hyperresearch-cite-checker.md", "cite checker", "CITE_CHECKER_AGENT"),
)

_CODEX_PREAMBLE = """
## Codex execution adapter

This skill was rendered for Codex. Treat the run manifest and the Codex plan as
the durable record of progress. When a procedure names a role prompt, read the
matching file under
`.agents/skills/hyperresearch/references/agents/` completely before delegating.
Use generic subagents when available; the role prompt supplies the specialization.
If delegation is unavailable, execute the role locally while preserving its
input, output, and tool-boundary contract.
"""


def _strip_frontmatter(content: str) -> str:
    if not content.startswith("---\n"):
        return content
    end = content.find("\n---\n", 4)
    return content[end + 5 :] if end >= 0 else content


def _codexify(content: str) -> str:
    """Translate Claude-only orchestration vocabulary to Codex conventions."""
    content = content.replace(".claude/skills", ".agents/skills")
    content = content.replace("Claude Code", "Codex")
    content = content.replace("TodoWrite list", "Codex plan")
    content = content.replace("TodoWrite", "Codex plan")
    content = content.replace("Task call", "subagent delegation")
    content = content.replace("Task prompt", "subagent prompt")
    content = content.replace("Task tool", "subagent delegation")
    content = content.replace("Claude-in-Chrome extension", "authenticated browser integration")
    content = content.replace(
        "hyperresearch init . --json",
        "hyperresearch init . --platform codex --json",
    )
    content = content.replace(
        "hyperresearch install --steps-only . --json",
        "hyperresearch install --steps-only . --platform codex --json",
    )

    content = re.sub(
        r'`?Skill\(skill: "([^"]+)"\)`?',
        r"read and follow `.agents/skills/\1/SKILL.md` completely",
        content,
    )
    content = re.sub(
        r"^(\s*)subagent_type:\s*(hyperresearch-\S+)\s*$",
        (
            r"\1role_prompt: "
            r".agents/skills/hyperresearch/references/agents/\2.md"
        ),
        content,
        flags=re.MULTILINE,
    )

    marker = "\n---\n"
    end = content.find(marker, 4) if content.startswith("---\n") else -1
    if end >= 0:
        insert_at = end + len(marker)
        content = content[:insert_at] + _CODEX_PREAMBLE + "\n" + content[insert_at:]
    else:
        content = _CODEX_PREAMBLE.lstrip() + "\n" + content
    return content


def _write_if_changed(path: Path, content: str) -> bool:
    if path.exists() and path.read_text(encoding="utf-8") == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def _render_skill(source_name: str) -> str | None:
    content = hooks._read_skill_source(source_name)
    if content is None:
        return None
    return _codexify(hooks._render_installed(content))


def _install_entry_skill(root: Path) -> str | None:
    content = _render_skill("hyperresearch.md")
    if content is None:
        return None
    path = root / ".agents" / "skills" / "hyperresearch" / "SKILL.md"
    if not _write_if_changed(path, content):
        return None
    return "Codex: .agents/skills/hyperresearch/SKILL.md"


def install_codex_step_skills(root: Path) -> str | None:
    """Install the pipeline step skills under the Codex project skill root."""
    skills_root = root / ".agents" / "skills"
    expected = set(hooks._HYPERRESEARCH_STEP_SKILLS)
    installed: list[str] = []
    pruned: list[str] = []

    for skill_name in hooks._HYPERRESEARCH_STEP_SKILLS:
        content = _render_skill(f"{skill_name}.md")
        if content is None:
            continue
        path = skills_root / skill_name / "SKILL.md"
        if _write_if_changed(path, content):
            installed.append(skill_name)

    if skills_root.exists():
        for child in skills_root.iterdir():
            stale = (
                child.is_dir()
                and child.name.startswith("hyperresearch-")
                and child.name not in expected
            )
            if not stale:
                continue
            import shutil

            shutil.rmtree(child)
            pruned.append(child.name)

    if not installed and not pruned:
        return None
    parts = []
    if installed:
        parts.append(f"{len(installed)} step skills")
    if pruned:
        parts.append(f"pruned: {', '.join(pruned)}")
    return f"Codex: .agents/skills/hyperresearch-N-*/SKILL.md ({'; '.join(parts)})"


def _install_role_prompts(root: Path, hpr_path: str) -> str | None:
    base = root / ".agents" / "skills" / "hyperresearch" / "references" / "agents"
    installed: list[str] = []
    hpr_posix = hpr_path.replace("\\", "/")

    for filename, label, constant_name in _ROLE_PROMPTS:
        content = getattr(hooks, constant_name)
        content = content.replace("{hpr_path}", hpr_posix)
        if constant_name == "POLISH_AUDITOR_AGENT":
            content = content.format(
                scaffold_only_sections=hooks._render_scaffold_only_bullets(indent="- ")
            )
        content = hooks._render_installed(content)
        body = _strip_frontmatter(content)
        rendered = (
            f"# Hyperresearch role: {label}\n\n"
            "Use this as the complete role prompt for a Codex subagent. The orchestrating "
            "skill supplies the canonical query, pipeline position, specific inputs, and "
            "required shim.\n\n"
            f"{_codexify(body)}"
        )
        if _write_if_changed(base / filename, rendered):
            installed.append(filename)

    if not installed:
        return None
    return f"Codex: {len(installed)} reusable role prompts"


def install_codex(
    root: Path,
    hpr_path: str = "hyperresearch",
    profile: str = "full",
    *,
    include_steps: bool = True,
) -> list[str]:
    """Install Codex skills and role prompts. Returns actions taken."""
    config_path = root / ".hyperresearch" / "config.toml"
    hooks._set_render_state(profile, config_path if config_path.exists() else None)
    actions: list[str] = []
    installers = [
        lambda: _install_entry_skill(root),
        lambda: _install_role_prompts(root, hpr_path),
    ]
    if include_steps:
        installers.insert(1, lambda: install_codex_step_skills(root))
    for installer in installers:
        result = installer()
        if result:
            actions.append(result)
    return actions
