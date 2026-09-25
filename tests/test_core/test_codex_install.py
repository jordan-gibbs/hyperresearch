"""Codex install plumbing: agent TOML translation, install tree, Stop hook, stop gate."""

from __future__ import annotations

import json
import tomllib
from datetime import UTC, datetime, timedelta

import pytest

from hyperresearch.core import codex
from hyperresearch.core.hooks import install_global_hooks, install_hooks

EXPECTED_CODEX_AGENTS = {
    "hyperresearch-fetcher.toml",
    "hyperresearch-loci-analyst.toml",
    "hyperresearch-depth-investigator.toml",
    "hyperresearch-source-analyst.toml",
    "hyperresearch-corpus-critic.toml",
    "hyperresearch-dialectic-critic.toml",
    "hyperresearch-depth-critic.toml",
    "hyperresearch-width-critic.toml",
    "hyperresearch-instruction-critic.toml",
    "hyperresearch-patcher.toml",
    "hyperresearch-polish-auditor.toml",
    "hyperresearch-readability-recommender.toml",
    "hyperresearch-draft-orchestrator.toml",
    "hyperresearch-synthesizer.toml",
    "hyperresearch-cite-checker.toml",
}


def _load_agents(root) -> dict[str, dict]:
    agents_dir = root / ".codex" / "agents"
    return {
        p.name: tomllib.loads(p.read_text(encoding="utf-8"))
        for p in agents_dir.glob("*.toml")
    }


# ---------------------------------------------------------------------------
# TOML encoding helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "plain text",
        'quotes " and \\ backslashes',
        "tab\tnewline\nform\fcarriage\rbell\x07del\x7f",
        "unicode — ✓ 字",
        "",
    ],
)
def test_toml_basic_string_round_trips(value):
    doc = f"x = {codex.toml_basic_string(value)}\n"
    assert tomllib.loads(doc)["x"] == value


@pytest.mark.parametrize(
    "value",
    [
        "multi\nline\nbody with 'single' and '' quotes and \\ backslash\n",
        "no trailing newline",
        "contains ''' a triple quote\n",
        "ends in a quote'",
        "ends in two quotes''",
        "has a\x00control char\n",
        "windows\r\nline endings\r\n",
        "\nleading newline\n",
    ],
)
def test_toml_text_block_round_trips(value):
    doc = f"x = {codex.toml_text_block(value)}\n"
    assert tomllib.loads(doc)["x"] == value


def test_toml_text_block_prefers_literal_when_safe():
    assert codex.toml_text_block("a\nb\n").startswith("'''\n")
    assert codex.toml_text_block("a ''' b").startswith('"')


# ---------------------------------------------------------------------------
# Markdown agent -> TOML translation
# ---------------------------------------------------------------------------

_SAMPLE_AGENT = """\
---
name: hyperresearch-sample
description: >
  First line of a folded
  description.
model: opus
tools: Read, Edit
color: red
---

You are a sample agent. It's got 'quotes' and \\backslashes\\.
"""


def test_agent_markdown_to_toml_fields():
    out = codex.agent_markdown_to_toml(_SAMPLE_AGENT, header_comment="<!-- prov -->")
    assert out.startswith("# <!-- prov -->\n")
    data = tomllib.loads(out)
    assert data["name"] == "hyperresearch-sample"
    assert data["description"] == "First line of a folded description."
    assert data["model_reasoning_effort"] == "high"
    assert data["sandbox_mode"] == "workspace-write"
    assert "model" not in data
    body = "You are a sample agent. It's got 'quotes' and \\backslashes\\.\n"
    assert data["developer_instructions"].endswith(body)
    assert data["developer_instructions"].startswith("## Codex runtime notes")


def test_agent_markdown_to_toml_model_override_and_effort():
    md = _SAMPLE_AGENT.replace("model: opus", "model: sonnet")
    data = tomllib.loads(
        codex.agent_markdown_to_toml(md, header_comment="x", codex_model="gpt-5.4-mini")
    )
    assert data["model"] == "gpt-5.4-mini"
    assert data["model_reasoning_effort"] == "medium"


def test_developer_instructions_round_trip_exactly():
    """The body survives TOML encoding byte for byte (preamble + body)."""
    meta, body = codex.split_frontmatter(_SAMPLE_AGENT)
    tools = codex.parse_tools(meta["tools"])
    expected = codex.codex_agent_preamble(meta["name"], tools) + body.lstrip("\n")
    data = tomllib.loads(codex.agent_markdown_to_toml(_SAMPLE_AGENT, header_comment="x"))
    assert data["developer_instructions"] == expected


def test_preamble_derives_discipline_from_tools():
    edit_only = codex.codex_agent_preamble("hyperresearch-patcher", ["Read", "Edit"])
    assert "ONLY make surgical `apply_patch`" in edit_only
    assert "no general shell access" in edit_only

    write_only = codex.codex_agent_preamble("hyperresearch-synthesizer", ["Read", "Write"])
    assert "create or overwrite only the output files" in write_only
    assert "ONLY make surgical" not in write_only

    with_task = codex.codex_agent_preamble("x", ["Bash", "Read", "Write", "Task"])
    assert "Subagent spawning is unavailable to you" in with_task
    assert "fetch-batch" in with_task
    assert "no general shell access" not in with_task


# ---------------------------------------------------------------------------
# install_hooks(platform="codex") — the installed tree
# ---------------------------------------------------------------------------


def test_codex_install_tree(tmp_vault):
    root = tmp_vault.root
    actions = install_hooks(root, "hyperresearch", platform="codex")
    assert actions and all(a.startswith("Codex: ") for a in actions)

    # Nothing for Claude Code: a codex-only install never creates .claude/
    assert not (root / ".claude").exists()

    skill = root / ".agents" / "skills" / "hyperresearch" / "SKILL.md"
    assert skill.is_file()
    meta, _ = codex.split_frontmatter(skill.read_text(encoding="utf-8"))
    assert meta["name"] == "hyperresearch"
    assert len(" ".join(str(meta["description"]).split())) <= 1024

    import yaml

    openai = yaml.safe_load(
        (skill.parent / "agents" / "openai.yaml").read_text(encoding="utf-8")
    )
    assert openai["interface"]["display_name"] == "Hyperresearch"
    assert openai["interface"]["short_description"]
    assert "$hyperresearch" in openai["interface"]["default_prompt"]
    assert openai["policy"]["allow_implicit_invocation"] is True

    from hyperresearch.core.hooks import _HYPERRESEARCH_STEP_SKILLS

    steps_dir = root / ".hyperresearch" / "codex" / "steps"
    assert {p.stem for p in steps_dir.glob("*.md")} == set(_HYPERRESEARCH_STEP_SKILLS)
    assert "rendered from profile" in (steps_dir / "hyperresearch-1-decompose.md").read_text(
        encoding="utf-8"
    )

    agents = _load_agents(root)
    assert set(agents) == EXPECTED_CODEX_AGENTS  # no browser-fetcher on Codex
    for filename, data in agents.items():
        assert data["name"] == filename.removesuffix(".toml")
        assert data["description"] and "\n" not in data["description"]
        assert data["developer_instructions"].startswith("## Codex runtime notes")
        assert data["model_reasoning_effort"] in ("high", "medium")
        assert data["sandbox_mode"] == "workspace-write"
        assert "model" not in data  # inherit the session model by default

    # opus-class Claude roles get high effort, sonnet roles medium
    assert agents["hyperresearch-synthesizer.toml"]["model_reasoning_effort"] == "high"
    assert agents["hyperresearch-fetcher.toml"]["model_reasoning_effort"] == "medium"

    hooks = json.loads((root / ".codex" / "hooks.json").read_text(encoding="utf-8"))
    assert list(hooks["hooks"]) == ["Stop"]  # no PreToolUse on Codex
    (entry,) = hooks["hooks"]["Stop"]
    assert entry["hooks"][0]["command"] == "hyperresearch run stop-gate"


def test_codex_agent_body_matches_rendered_claude_body(tmp_vault):
    """The TOML body is the Claude agent body plus the preamble — no drift."""
    from hyperresearch.core import hooks as hooks_mod

    root = tmp_vault.root
    install_hooks(root, "hyperresearch", platform="codex")
    hooks_mod._set_render_state("full", None, "codex")
    rendered = hooks_mod._render_installed(hooks_mod.PATCHER_AGENT, header=False)
    meta, body = codex.split_frontmatter(rendered)
    data = _load_agents(root)["hyperresearch-patcher.toml"]
    expected = codex.codex_agent_preamble(meta["name"], ["Read", "Edit"]) + body.lstrip("\n")
    assert data["developer_instructions"] == expected


def test_codex_reinstall_is_idempotent(tmp_vault):
    first = install_hooks(tmp_vault.root, "hyperresearch", platform="codex")
    assert first
    assert install_hooks(tmp_vault.root, "hyperresearch", platform="codex") == []


def test_codex_model_override_from_profile(tmp_vault):
    cfg = tmp_vault.root / ".hyperresearch" / "config.toml"
    cfg.write_text(
        cfg.read_text(encoding="utf-8")
        + '\n[profile.full]\ncodex_models = { fetcher = "gpt-5.4-mini", critics = "gpt-5.5" }\n',
        encoding="utf-8",
    )
    install_hooks(tmp_vault.root, "hyperresearch", platform="codex")
    agents = _load_agents(tmp_vault.root)
    assert agents["hyperresearch-fetcher.toml"]["model"] == "gpt-5.4-mini"
    assert agents["hyperresearch-dialectic-critic.toml"]["model"] == "gpt-5.5"
    assert agents["hyperresearch-width-critic.toml"]["model"] == "gpt-5.5"
    assert "model" not in agents["hyperresearch-patcher.toml"]


def test_codex_models_default_to_none_and_validate():
    from hyperresearch.core.profiles import CodexModelMap, ModelMap, resolve_profile

    assert set(CodexModelMap.model_fields) == set(ModelMap.model_fields)
    p = resolve_profile("full")
    assert all(v is None for v in p.codex_models.model_dump().values())
    with pytest.raises(ValueError):
        CodexModelMap(fetcher="  ")


def test_claude_and_codex_installs_coexist(tmp_vault):
    root = tmp_vault.root
    claude_actions = install_hooks(root, "hyperresearch")
    install_hooks(root, "hyperresearch", platform="codex")
    assert (root / ".claude" / "agents" / "hyperresearch-browser-fetcher.md").is_file()
    assert (root / ".codex" / "agents" / "hyperresearch-fetcher.toml").is_file()
    # Re-running either platform is still a no-op afterwards
    assert install_hooks(root, "hyperresearch", platform="codex") == []
    again = install_hooks(root, "hyperresearch")
    assert not again or all("pruned" not in a.lower() for a in again)
    assert claude_actions


def test_codex_prunes_only_our_stale_files(tmp_vault):
    root = tmp_vault.root
    install_hooks(root, "hyperresearch", platform="codex")
    agents_dir = root / ".codex" / "agents"
    steps_dir = root / ".hyperresearch" / "codex" / "steps"

    # A retired agent we wrote (provenance comment) vs. one the user wrote
    ours = agents_dir / "hyperresearch-retired.toml"
    ours.write_text(
        (agents_dir / "hyperresearch-patcher.toml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    theirs = agents_dir / "hyperresearch-mine.toml"
    theirs.write_text('name = "hyperresearch-mine"\n', encoding="utf-8")
    unrelated = agents_dir / "reviewer.toml"
    unrelated.write_text('name = "reviewer"\n', encoding="utf-8")
    stale_step = steps_dir / "hyperresearch-99-retired.md"
    stale_step.write_text("<!-- rendered from profile \"full\" -->\n", encoding="utf-8")
    user_step = steps_dir / "hyperresearch-notes.md"
    user_step.write_text("my own notes\n", encoding="utf-8")

    actions = install_hooks(root, "hyperresearch", platform="codex")
    assert any("pruned" in a for a in actions)
    assert not ours.exists()
    assert not stale_step.exists()
    assert theirs.exists() and unrelated.exists() and user_step.exists()


def test_codex_global_install(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    actions = install_global_hooks(home, "hyperresearch", platform="codex")
    assert actions
    assert (home / ".agents" / "skills" / "hyperresearch" / "SKILL.md").is_file()
    assert (home / ".agents" / "skills" / "hyperresearch" / "agents" / "openai.yaml").is_file()
    assert set(_load_agents(home)) == EXPECTED_CODEX_AGENTS
    # Global Codex install never touches user-level Codex config or hooks,
    # never installs step files globally, and never touches ~/.claude
    assert not (home / ".codex" / "config.toml").exists()
    assert not (home / ".codex" / "hooks.json").exists()
    assert not (home / ".hyperresearch").exists()
    assert not (home / ".claude").exists()
    assert install_global_hooks(home, "hyperresearch", platform="codex") == []


def test_unknown_platform_rejected(tmp_vault):
    from hyperresearch.core.platforms import PlatformError

    with pytest.raises(PlatformError):
        install_hooks(tmp_vault.root, "hyperresearch", platform="gemini")


# ---------------------------------------------------------------------------
# .codex/hooks.json merge
# ---------------------------------------------------------------------------


def test_stop_hook_merge_preserves_foreign_hooks(tmp_vault):
    from hyperresearch.core.hooks import _install_codex_stop_hook

    hooks_path = tmp_vault.root / ".codex" / "hooks.json"
    hooks_path.parent.mkdir(parents=True)
    foreign = {
        "hooks": {
            "PreToolUse": [{"matcher": "shell", "hooks": [{"type": "command", "command": "lint"}]}],
            "Stop": [
                {"hooks": [{"type": "command", "command": "notify-done"}]},
                {"hooks": [{"type": "command", "command": "/old/hyperresearch run stop-gate"}]},
            ],
        },
        "other": 1,
    }
    hooks_path.write_text(json.dumps(foreign), encoding="utf-8")

    assert _install_codex_stop_hook(tmp_vault.root, "C:/Program Files/hpr.exe")
    merged = json.loads(hooks_path.read_text(encoding="utf-8"))
    assert merged["other"] == 1
    assert merged["hooks"]["PreToolUse"] == foreign["hooks"]["PreToolUse"]
    commands = [e["hooks"][0]["command"] for e in merged["hooks"]["Stop"]]
    # Foreign Stop entry kept, our old entry replaced (exactly one of ours)
    assert commands == ["notify-done", '"C:/Program Files/hpr.exe" run stop-gate']

    # Idempotent
    assert _install_codex_stop_hook(tmp_vault.root, "C:/Program Files/hpr.exe") is None


def test_stop_hook_leaves_unparseable_hooks_json_alone(tmp_vault):
    from hyperresearch.core.hooks import _install_codex_stop_hook

    hooks_path = tmp_vault.root / ".codex" / "hooks.json"
    hooks_path.parent.mkdir(parents=True)
    hooks_path.write_text("{ not json", encoding="utf-8")
    result = _install_codex_stop_hook(tmp_vault.root, "hyperresearch")
    assert result and "NOT installed" in result
    assert hooks_path.read_text(encoding="utf-8") == "{ not json"


def test_stop_hook_command_quotes_only_paths_with_spaces():
    assert codex.stop_hook_command("C:\\venv\\hpr.exe") == "C:/venv/hpr.exe run stop-gate"
    assert codex.stop_hook_command("/a b/hpr") == '"/a b/hpr" run stop-gate'


# ---------------------------------------------------------------------------
# Stop gate decision
# ---------------------------------------------------------------------------


def test_stop_gate_no_runs(tmp_vault):
    assert codex.stop_gate_decision(tmp_vault) is None


def test_stop_gate_blocks_in_progress_run(tmp_vault):
    from hyperresearch.core.runs import init_run, set_step

    init_run(tmp_vault, "gate-run")
    set_step(tmp_vault, "gate-run", "1", "done")
    decision = codex.stop_gate_decision(tmp_vault)
    assert decision is not None
    assert decision["decision"] == "block"
    assert "gate-run is at step 2 (hyperresearch-2-width-sweep)" in decision["reason"]
    assert ".hyperresearch/codex/steps/hyperresearch-2-width-sweep.md" in decision["reason"]


@pytest.mark.parametrize("status", ["done", "aborted", "failed", "paused", "blocked"])
def test_stop_gate_silent_for_inactive_runs(tmp_vault, status):
    from hyperresearch.core.runs import init_run, set_status

    init_run(tmp_vault, "gate-run")
    set_status(tmp_vault, "gate-run", status, blocked_on="x" if status == "blocked" else None)
    assert codex.stop_gate_decision(tmp_vault) is None


def test_stop_gate_silent_when_all_steps_done(tmp_vault):
    from hyperresearch.core.runs import init_run, load_manifest, set_step

    init_run(tmp_vault, "gate-run", profile="light")
    for step in load_manifest(tmp_vault, "gate-run")["profile_steps"]:
        set_step(tmp_vault, "gate-run", step, "done")
    assert codex.stop_gate_decision(tmp_vault) is None


def test_stop_gate_silent_for_stale_run(tmp_vault):
    from hyperresearch.core.runs import init_run

    init_run(tmp_vault, "gate-run")
    later = datetime.now(UTC) + timedelta(hours=7)
    assert codex.stop_gate_decision(tmp_vault, now=later) is None
    soon = datetime.now(UTC) + timedelta(hours=5)
    assert codex.stop_gate_decision(tmp_vault, now=soon) is not None


# ---------------------------------------------------------------------------
# AGENTS.md injection
# ---------------------------------------------------------------------------


def test_codex_agent_docs(tmp_vault):
    from hyperresearch.core.agent_docs import (
        HYPERRESEARCH_SECTION_MARKER,
        inject_agent_docs,
    )

    agents_md = tmp_vault.root / "AGENTS.md"
    agents_md.write_text("# My project\n\nKeep this.\n", encoding="utf-8")
    claude_before = (tmp_vault.root / "CLAUDE.md").read_text(encoding="utf-8")

    assert inject_agent_docs(tmp_vault.root, platform="codex") == ["AGENTS.md (appended)"]
    text = agents_md.read_text(encoding="utf-8")
    assert text.startswith("# My project\n\nKeep this.\n")
    assert HYPERRESEARCH_SECTION_MARKER in text
    assert "$hyperresearch <query>" in text
    assert ".agents/skills/hyperresearch/SKILL.md" in text
    assert ".hyperresearch/codex/steps/" in text
    assert ".codex/agents/" in text
    assert "sandbox_workspace_write.network_access=true" in text
    assert "--dangerously-bypass-hook-trust" in text
    assert "`/hyperresearch" not in text  # no Claude slash command
    assert len(text.encode("utf-8")) < 16 * 1024  # well under Codex's 32 KiB cap

    # Idempotent, and CLAUDE.md is untouched
    assert inject_agent_docs(tmp_vault.root, platform="codex") == []
    assert (tmp_vault.root / "CLAUDE.md").read_text(encoding="utf-8") == claude_before


def test_vault_init_codex_only_writes_agents_md_not_claude_md(tmp_path):
    from hyperresearch.core.vault import Vault

    vault = Vault.init(tmp_path / "v", platforms=("codex",))
    assert (vault.root / "AGENTS.md").is_file()
    assert not (vault.root / "CLAUDE.md").exists()

    default = Vault.init(tmp_path / "d")
    assert (default.root / "CLAUDE.md").is_file()
    assert not (default.root / "AGENTS.md").exists()
