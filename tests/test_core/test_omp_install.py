"""OMP install plumbing: agent translation, install tree, command, stop-gate extension."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from hyperresearch.core import omp
from hyperresearch.core.hooks import install_global_hooks, install_hooks

EXPECTED_OMP_AGENTS = {
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
    # OMP keeps the browser lane: its eval tool drives a real browser.
    "hyperresearch-browser-fetcher.md",
    "hyperresearch-cite-checker.md",
}


def _load_agents(root: Path, agents_dir: Path | None = None) -> dict[str, dict]:
    directory = agents_dir if agents_dir is not None else root / ".omp" / "agents"
    out = {}
    for path in sorted(directory.glob("*.md")):
        meta, _ = omp.split_frontmatter(path.read_text(encoding="utf-8"))
        out[path.name] = meta
    return out


def _agent_body(text: str) -> str:
    """The body of an installed agent file, without the provenance line."""
    _, body = omp.split_frontmatter(text)
    return body.split("\n", 1)[1]


_SAMPLE_AGENT = """\
---
name: hyperresearch-sample
description: >
  A sample agent whose description
  folds across lines.
color: red
model: opus
tools: Read, Write, Edit, Bash, WebSearch, ToolSearch
---

Body line one.

Body line two.
"""


# ---------------------------------------------------------------------------
# Markdown agent -> OMP agent
# ---------------------------------------------------------------------------


def test_agent_markdown_to_omp_fields():
    out = omp.agent_markdown_to_omp(_SAMPLE_AGENT, header_comment="<!-- prov -->")
    meta, _ = omp.split_frontmatter(out)
    assert meta["name"] == "hyperresearch-sample"
    assert meta["description"] == (
        "A sample agent whose description folds across lines."
    )
    assert meta["tools"] == "read, write, edit, bash, web_search, eval"
    assert meta["thinking-level"] == "high"  # opus-class role
    assert "model" not in meta  # inherit the OMP session model by default
    assert "color" not in meta  # Claude Code only
    # Provenance sits after the frontmatter, where the pruner looks for it.
    assert out.split("---\n", 2)[2].startswith("<!-- prov -->\n")
    assert _agent_body(out).startswith("## OMP runtime notes")
    assert _agent_body(out).rstrip().endswith("Body line two.")


def test_agent_markdown_to_omp_keeps_body_verbatim():
    out = omp.agent_markdown_to_omp(_SAMPLE_AGENT, header_comment="<!-- prov -->")
    assert _agent_body(out) == omp._OMP_TOOL_MAP + "Body line one.\n\nBody line two.\n"


def test_agent_markdown_to_omp_model_override():
    out = omp.agent_markdown_to_omp(
        _SAMPLE_AGENT, header_comment="<!-- prov -->", omp_model="@slow"
    )
    meta, _ = omp.split_frontmatter(out)
    assert meta["model"] == "@slow"
    assert meta["thinking-level"] == "high"


def test_agent_markdown_to_omp_requires_a_name():
    with pytest.raises(ValueError, match="no name"):
        omp.agent_markdown_to_omp("no frontmatter here\n", header_comment="<!-- prov -->")


@pytest.mark.parametrize(
    ("tools", "expected"),
    [
        ("Read, Edit", ["read", "edit"]),
        (["Bash", "Read", "Write"], ["bash", "read", "write"]),
        ("WebSearch", ["web_search"]),
        ("ToolSearch", ["eval"]),
        # Unknown Claude tools keep their name rather than vanishing.
        ("Read, Mystery", ["read", "mystery"]),
        (None, []),
    ],
)
def test_tools_to_omp(tools, expected):
    assert omp.tools_to_omp(tools) == expected


def test_effort_follows_the_claude_model():
    assert omp.agent_markdown_to_omp(
        _SAMPLE_AGENT.replace("model: opus", "model: sonnet"), header_comment="<!-- p -->"
    ).count("thinking-level: medium") == 1


# ---------------------------------------------------------------------------
# install_hooks(platform="omp") — the installed tree
# ---------------------------------------------------------------------------


def test_omp_install_tree(tmp_vault):
    root = tmp_vault.root
    actions = install_hooks(root, "hyperresearch", platform="omp")
    assert actions and all(a.startswith("OMP: ") for a in actions)

    # An OMP-only install writes nothing for the other runtimes.
    assert not (root / ".claude").exists()
    assert not (root / ".codex").exists()
    assert not (root / ".agents").exists()

    skill = root / ".omp" / "skills" / "hyperresearch" / "SKILL.md"
    assert skill.is_file()
    meta, _ = omp.split_frontmatter(skill.read_text(encoding="utf-8"))
    assert meta["name"] == "hyperresearch"
    # OMP's native skill provider requires a description.
    assert len(" ".join(str(meta["description"]).split())) <= 1024
    assert not (skill.parent / "agents" / "openai.yaml").exists()

    from hyperresearch.core.hooks import _HYPERRESEARCH_STEP_SKILLS

    steps_dir = root / ".hyperresearch" / "omp" / "steps"
    assert {p.stem for p in steps_dir.glob("*.md")} == set(_HYPERRESEARCH_STEP_SKILLS)
    assert "rendered from profile" in (steps_dir / "hyperresearch-1-decompose.md").read_text(
        encoding="utf-8"
    )
    # Step procedures are files, never skills: no step skill dirs on OMP.
    assert not list((root / ".omp" / "skills").glob("hyperresearch-[0-9]*"))

    agents = _load_agents(root)
    assert set(agents) == EXPECTED_OMP_AGENTS  # browser-fetcher stays on OMP
    for filename, meta in agents.items():
        assert meta["name"] == filename.removesuffix(".md")
        assert meta["description"] and "\n" not in meta["description"]
        assert meta["thinking-level"] in ("high", "medium")
        assert "model" not in meta  # inherit the session model by default
    assert agents["hyperresearch-synthesizer.md"]["thinking-level"] == "high"
    assert agents["hyperresearch-fetcher.md"]["thinking-level"] == "medium"
    assert agents["hyperresearch-patcher.md"]["tools"] == "read, edit"
    assert agents["hyperresearch-browser-fetcher.md"]["tools"] == "bash, read, write, eval"

    command = (root / ".omp" / "commands" / "hyperresearch.md").read_text(encoding="utf-8")
    assert "$ARGUMENTS" in command
    assert "skill://hyperresearch" in command

    extension = (root / ".omp" / "extensions" / "hyperresearch.ts").read_text(encoding="utf-8")
    assert 'pi.on("session_stop"' in extension
    assert '"run", "stop-gate", "--platform", "omp"' in extension


def test_browser_fetcher_gets_the_omp_browser_note(tmp_vault):
    """The Claude-in-Chrome lane is rewritten onto OMP's eval browser facade."""
    root = tmp_vault.root
    install_hooks(root, "hyperresearch", platform="omp")
    agents = _load_agents(root)
    body = _agent_body(
        (root / ".omp" / "agents" / "hyperresearch-browser-fetcher.md").read_text(encoding="utf-8")
    )
    assert "Browser lane on OMP" in body
    assert "browser.open({ app: { relay: true }" in body
    assert "omp browser-relay" in body
    # The note lands before the Claude-in-Chrome setup it replaces.
    assert body.index("Browser lane on OMP") < body.index("Load the Chrome tools in ONE batched")
    assert agents["hyperresearch-browser-fetcher.md"]["tools"] == "bash, read, write, eval"
    # No other agent carries it.
    for other in ("hyperresearch-fetcher.md", "hyperresearch-patcher.md"):
        assert "Browser lane on OMP" not in _agent_body(
            (root / ".omp" / "agents" / other).read_text(encoding="utf-8")
        )


def test_omp_agent_body_matches_rendered_claude_body(tmp_vault):
    """The OMP body is the Claude agent body behind the vocabulary preamble."""
    from hyperresearch.core import hooks as hooks_mod

    root = tmp_vault.root
    install_hooks(root, "hyperresearch", platform="omp")
    hooks_mod._set_render_state("full", None, "omp")
    rendered = hooks_mod._render_installed(hooks_mod.PATCHER_AGENT, header=False)
    _, claude_body = omp.split_frontmatter(rendered)
    body = _agent_body(
        (root / ".omp" / "agents" / "hyperresearch-patcher.md").read_text(encoding="utf-8")
    )
    assert body == omp._OMP_TOOL_MAP + claude_body.lstrip("\n")


def test_omp_reinstall_is_idempotent(tmp_vault):
    first = install_hooks(tmp_vault.root, "hyperresearch", platform="omp")
    assert first
    assert install_hooks(tmp_vault.root, "hyperresearch", platform="omp") == []


def test_omp_model_override_from_profile(tmp_vault):
    cfg = tmp_vault.root / ".hyperresearch" / "config.toml"
    cfg.write_text(
        cfg.read_text(encoding="utf-8")
        + '\n[profile.full]\nomp_models = { fetcher = "anthropic/claude-haiku-4-5", critics = "@slow" }\n',
        encoding="utf-8",
    )
    install_hooks(tmp_vault.root, "hyperresearch", platform="omp")
    agents = _load_agents(tmp_vault.root)
    assert agents["hyperresearch-fetcher.md"]["model"] == "anthropic/claude-haiku-4-5"
    assert agents["hyperresearch-depth-critic.md"]["model"] == "@slow"
    assert "model" not in agents["hyperresearch-patcher.md"]


def test_omp_models_default_to_none_and_validate():
    from hyperresearch.core.profiles import ModelMap, OmpModelMap, resolve_profile

    p = resolve_profile("full")
    assert all(v is None for v in p.omp_models.model_dump().values())
    assert set(p.omp_models.model_dump()) == set(ModelMap().model_dump())
    assert p.omp_models.fetcher is None
    with pytest.raises(ValueError):
        OmpModelMap(fetcher="  ")
    with pytest.raises(ValueError):
        OmpModelMap(nope="x")


def test_omp_prunes_only_our_stale_files(tmp_vault):
    root = tmp_vault.root
    install_hooks(root, "hyperresearch", platform="omp")
    agents_dir = root / ".omp" / "agents"
    steps_dir = root / ".hyperresearch" / "omp" / "steps"

    ours = agents_dir / "hyperresearch-retired.md"
    ours.write_text(
        (agents_dir / "hyperresearch-patcher.md").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    theirs = agents_dir / "hyperresearch-mine.md"
    theirs.write_text("---\nname: hyperresearch-mine\ndescription: mine\n---\n", encoding="utf-8")
    unrelated = agents_dir / "reviewer.md"
    unrelated.write_text("---\nname: reviewer\ndescription: review\n---\n", encoding="utf-8")
    stale_step = steps_dir / "hyperresearch-99-retired.md"
    stale_step.write_text('<!-- rendered from profile "full" -->\n', encoding="utf-8")
    user_step = steps_dir / "hyperresearch-notes.md"
    user_step.write_text("my own notes\n", encoding="utf-8")

    actions = install_hooks(root, "hyperresearch", platform="omp")
    assert any("pruned" in a for a in actions)
    assert not ours.exists()
    assert not stale_step.exists()
    assert theirs.exists() and unrelated.exists() and user_step.exists()


def test_omp_and_claude_and_codex_installs_coexist(tmp_vault):
    root = tmp_vault.root
    assert install_hooks(root, "hyperresearch", platform="claude")
    assert install_hooks(root, "hyperresearch", platform="codex")
    assert install_hooks(root, "hyperresearch", platform="omp")
    assert (root / ".claude" / "agents" / "hyperresearch-fetcher.md").is_file()
    assert (root / ".codex" / "agents" / "hyperresearch-fetcher.toml").is_file()
    assert (root / ".omp" / "agents" / "hyperresearch-fetcher.md").is_file()
    # The OMP agent is not the Claude agent file copied verbatim.
    assert (root / ".omp" / "agents" / "hyperresearch-fetcher.md").read_text(
        encoding="utf-8"
    ) != (root / ".claude" / "agents" / "hyperresearch-fetcher.md").read_text(encoding="utf-8")


def test_omp_global_install_uses_the_agent_dir(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    actions = install_global_hooks(home, "hyperresearch", platform="omp")
    assert actions

    # OMP's user root is ~/.omp/agent — not ~/.omp.
    assert (home / ".omp" / "agent" / "skills" / "hyperresearch" / "SKILL.md").is_file()
    assert (home / ".omp" / "agent" / "commands" / "hyperresearch.md").is_file()
    assert set(_load_agents(home, home / ".omp" / "agent" / "agents")) == EXPECTED_OMP_AGENTS
    for stray in ("skills", "agents", "commands", "extensions"):
        assert not (home / ".omp" / stray).exists(), stray
    # No step files, no stop-gate extension, no vault, nothing for other runtimes.
    assert not (home / ".hyperresearch").exists()
    assert not (home / ".omp" / "agent" / "extensions").exists()
    assert not (home / ".claude").exists()
    assert not (home / ".codex").exists()
    assert install_global_hooks(home, "hyperresearch", platform="omp") == []


def test_unknown_platform_rejected(tmp_vault):
    from hyperresearch.core.platforms import PlatformError

    with pytest.raises(PlatformError):
        install_hooks(tmp_vault.root, "hyperresearch", platform="gemini")


# ---------------------------------------------------------------------------
# The stop-gate extension + command
# ---------------------------------------------------------------------------


def test_stopgate_extension_substitutes_the_cli_path():
    src = omp.stopgate_extension("/a b/hpr")
    assert "{hpr_path}" not in src
    assert 'pi.exec("/a b/hpr", ["run", "stop-gate", "--platform", "omp"]' in src
    # Windows paths are posix-normalized, same rule as the Claude/Codex hooks.
    assert '"/opt/hpr"' in omp.stopgate_extension("\\opt\\hpr")
    # The packaged template is the only source: nothing is templated but the path.
    assert omp.stopgate_extension("{hpr_path}").count("pi.on(") == 1


def test_omp_command_is_profile_independent(tmp_vault):
    from hyperresearch.core.hooks import OMP_COMMAND_TEMPLATE

    install_hooks(tmp_vault.root, "hyperresearch", profile="premier", platform="omp")
    command = tmp_vault.root / ".omp" / "commands" / "hyperresearch.md"
    assert command.read_text(encoding="utf-8") == OMP_COMMAND_TEMPLATE
    assert yaml.safe_load(command.read_text(encoding="utf-8").split("---")[1])["argument-hint"]


# ---------------------------------------------------------------------------
# Stop gate decision
# ---------------------------------------------------------------------------


def test_stop_gate_decision_quotes_the_omp_step_file(tmp_vault):
    from hyperresearch.core.codex import stop_gate_decision
    from hyperresearch.core.runs import init_run, set_step

    init_run(tmp_vault, "gate-run", profile="full")
    set_step(tmp_vault, "gate-run", 1, "done")
    decision = stop_gate_decision(tmp_vault, platform="omp")
    assert decision is not None
    assert ".hyperresearch/omp/steps/hyperresearch-2-width-sweep.md" in decision["reason"]


def test_stop_gate_decision_defaults_to_codex(tmp_vault):
    from hyperresearch.core.codex import stop_gate_decision
    from hyperresearch.core.runs import init_run, set_step

    init_run(tmp_vault, "gate-run", profile="full")
    set_step(tmp_vault, "gate-run", 1, "done")
    assert stop_gate_decision(tmp_vault) == stop_gate_decision(tmp_vault, platform="codex")
    assert ".hyperresearch/codex/steps/" in stop_gate_decision(tmp_vault)["reason"]


def test_unknown_stop_gate_platform_rejected(tmp_vault):
    from hyperresearch.core.codex import stop_gate_decision
    from hyperresearch.core.platforms import PlatformError
    from hyperresearch.core.runs import init_run

    init_run(tmp_vault, "gate-run", profile="full")
    with pytest.raises(PlatformError):
        stop_gate_decision(tmp_vault, platform="gemini")


# ---------------------------------------------------------------------------
# AGENTS.md injection
# ---------------------------------------------------------------------------


def test_omp_agent_docs_blurb(tmp_vault):
    from hyperresearch.core.agent_docs import inject_agent_docs

    root = tmp_vault.root
    claude_md = root / "CLAUDE.md"
    claude_before = claude_md.read_text(encoding="utf-8") if claude_md.exists() else None
    assert inject_agent_docs(root, platform="omp") == ["AGENTS.md (created)"]
    text = (root / "AGENTS.md").read_text(encoding="utf-8")
    assert "/hyperresearch <query>" in text
    assert "skill://hyperresearch" in text
    assert ".omp/skills/hyperresearch/SKILL.md" in text
    assert "omp_step_file" in text
    assert "<!-- hyperresearch:start -->" in text
    # An OMP install never rewrites the Claude Code docs file.
    assert (claude_md.read_text(encoding="utf-8") if claude_md.exists() else None) == claude_before
    # Re-injecting is a no-op.
    assert inject_agent_docs(root, platform="omp") == []
