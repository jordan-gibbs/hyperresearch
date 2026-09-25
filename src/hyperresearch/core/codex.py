"""OpenAI Codex translation layer — agent TOML, skill metadata, Stop hook, stop gate.

The pipeline's subagent prompts are written once, as Claude Code markdown
agents (YAML frontmatter + body) in core/hooks.py. Codex wants custom agents
as TOML (`.codex/agents/<name>.toml`) with `name`, `description`, and
`developer_instructions`, and has no per-agent tool allowlist, no Task tool,
and no Read/Write/Edit tools. This module converts one to the other:

    frontmatter name / description  -> TOML name / description (one line)
    frontmatter model               -> model_reasoning_effort ("high" for
                                       opus-class roles, else "medium"); a
                                       `model` key only when the profile sets
                                       a `codex_models` override for the role
    frontmatter tools               -> a preamble prepended to the body that
                                       maps the tool vocabulary and turns the
                                       tool lock into instruction discipline
    body                            -> developer_instructions

It also owns the Codex Stop hook (`.codex/hooks.json`) and the decision
logic behind `hyperresearch run stop-gate`, which keeps a Codex session from
ending while the newest run is mid-pipeline — Codex's documented failure mode
on this pipeline is answering the question inline and skipping the steps.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

import yaml

# ---------------------------------------------------------------------------
# TOML string encoding. No TOML writer is a dependency, and every value we
# emit is a string — short scalars plus one long prompt body.
# ---------------------------------------------------------------------------

_BASIC_ESCAPES = {
    "\\": "\\\\",
    '"': '\\"',
    "\b": "\\b",
    "\t": "\\t",
    "\n": "\\n",
    "\f": "\\f",
    "\r": "\\r",
}

# Control characters a TOML literal string may not contain (tab is allowed;
# newlines are allowed only inside multi-line strings, handled separately).
_LITERAL_FORBIDDEN = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def toml_basic_string(value: str) -> str:
    """Encode `value` as a single-line TOML basic string ("...")."""
    out: list[str] = []
    for ch in value:
        if ch in _BASIC_ESCAPES:
            out.append(_BASIC_ESCAPES[ch])
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            out.append(f"\\u{ord(ch):04X}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def toml_text_block(value: str) -> str:
    """Encode a long body as a TOML string that round-trips exactly.

    Prefers a multi-line literal string (`'''` + newline + body + `'''`) —
    readable, no escaping, and the newline right after the opening delimiter
    is trimmed by the parser. Falls back to an escaped basic string when the
    body contains `'''`, ends in a quote (which would merge into the closing
    delimiter), or carries a control character a literal string cannot hold.
    """
    # Carriage returns force the basic string too: parsers normalize CRLF
    # inside multi-line strings, which would break the exact round trip.
    literal_ok = (
        "'''" not in value
        and not value.endswith("'")
        and not _LITERAL_FORBIDDEN.search(value)
    )
    if literal_ok:
        return "'''\n" + value + "'''"
    return toml_basic_string(value)


# ---------------------------------------------------------------------------
# Markdown agent -> Codex TOML
# ---------------------------------------------------------------------------


def split_frontmatter(text: str) -> tuple[dict, str]:
    """Split a markdown agent file into (frontmatter dict, body)."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    meta = yaml.safe_load(text[3:end]) or {}
    rest = text[end + 4 :]
    # Drop the remainder of the closing-delimiter line.
    newline = rest.find("\n")
    body = rest[newline + 1 :] if newline != -1 else ""
    return (meta if isinstance(meta, dict) else {}), body


def parse_tools(value) -> list[str]:
    """Frontmatter `tools:` (comma string or YAML list) -> tool names."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(t).strip() for t in value if str(t).strip()]
    return [t.strip() for t in str(value).split(",") if t.strip()]


def reasoning_effort_for(claude_model: str | None) -> str:
    """Roles Claude runs on an opus-class model get high effort on Codex."""
    return "high" if claude_model and "opus" in claude_model.lower() else "medium"


# Codex renderings of the Claude tool vocabulary. Every agent gets these.
_TOOL_MAP = """\
## Codex runtime notes (read first — these override conflicting tool wording below)

You are running as an OpenAI Codex custom agent. The instructions below were
written for Claude Code; translate their tool vocabulary as follows:

- **Read** a file -> read it with the shell (`cat`, `sed -n '1,200p' <file>`,
  or `Get-Content` on Windows). Read long files in chunks; do not skip parts
  you were told to read in full.
- **Write** a new file / **Edit** an existing file -> use `apply_patch`.
- **Bash** -> the shell tool.
- **Task** / **Skill** tools do not exist here. You cannot spawn subagents.
- Never use a browsing tool for source pages; fetch them with the
  hyperresearch CLI (`... fetch "<url>" -j`), exactly as spelled below.
"""

def _tool_discipline(tools: list[str]) -> list[str]:
    """Instruction-level rules that stand in for the Claude tool allowlist.

    Codex has no per-agent tool allowlist, so the lock a Claude agent gets
    from its `tools:` line becomes discipline stated in the prompt.
    """
    have = set(tools)
    rules: list[str] = []
    if tools:
        rules.append(
            f"- Your role is limited to these capabilities: {', '.join(tools)}. "
            "Codex cannot enforce that list, so you must."
        )
    if "Bash" not in have:
        rules.append(
            "- You have no general shell access in this role. The ONLY shell "
            "commands you may run are read-only file reads (`cat`, `sed -n`, "
            "`Get-Content`). Do not run the hyperresearch CLI, scripts, or any "
            "command that changes state."
        )
    if "Edit" in have and "Write" not in have:
        rules.append(
            "- You may ONLY make surgical `apply_patch` update hunks to the files "
            "your task names (the report and its pre-stubbed log). Never create, "
            "delete, rename, or wholesale rewrite a file — replacing a whole "
            "file is regeneration, which this role forbids."
        )
    if "Write" in have and "Edit" not in have:
        rules.append(
            "- You may create or overwrite only the output files your task "
            "names (plus whatever the hyperresearch CLI writes for you). Never "
            "hand-edit a file another stage owns — in particular, never patch a "
            "report or draft you were given as input."
        )
    if "Task" in have:
        rules.append(
            "- Wherever the instructions below tell you to delegate fetching to "
            "`hyperresearch-fetcher` subagents via the Task tool, or tell you NOT "
            "to call `fetch` yourself: that does not apply on Codex. Subagent "
            "spawning is unavailable to you. Run the hyperresearch CLI's `fetch` "
            "(one URL) or `fetch-batch` (many URLs) yourself, with the same tags "
            "and run tag the spawn would have passed, then do the fetcher's job "
            "on each new note: read it, fill in its summary and tags, and chase "
            "primary sources within your source budget."
        )
    if "WebSearch" in have:
        rules.append(
            "- **WebSearch** -> Codex's built-in web search tool when it is "
            "enabled; if it is not, use the hyperresearch CLI's `scholar search` "
            "and fetch candidate URLs directly."
        )
    if "ToolSearch" in have:
        rules.append("- ToolSearch has no Codex equivalent; ignore steps that depend on it.")
    return rules


# Per-agent additions beyond what the `tools:` line implies.
CODEX_AGENT_NOTES: dict[str, str] = {
    "hyperresearch-patcher": (
        "- The patch log was pre-stubbed by the orchestrator because this role "
        "cannot create files. Append to it with `apply_patch`; do not recreate it."
    ),
    "hyperresearch-polish-auditor": (
        "- The polish log was pre-stubbed by the orchestrator because this role "
        "cannot create files. Append to it with `apply_patch`; do not recreate it."
    ),
    "hyperresearch-synthesizer": (
        "- Write the final report as a fresh file with `apply_patch` (an "
        "`*** Add File` or full replacement hunk). Do not graft sections from "
        "the drafts by editing them in place."
    ),
    "hyperresearch-readability-recommender": (
        "- Your only output is the recommendations JSON file. The orchestrator "
        "applies recommendations; you never touch the report."
    ),
    "hyperresearch-depth-investigator": (
        "- You are a leaf agent on Codex: finish your locus with your own "
        "fetches and reads, then write the interim note."
    ),
}


def codex_agent_preamble(name: str, tools: list[str]) -> str:
    """Build the Codex preamble prepended to one agent's developer_instructions."""
    rules = _tool_discipline(tools)
    note = CODEX_AGENT_NOTES.get(name)
    if note:
        rules.append(note)
    parts = [_TOOL_MAP.rstrip("\n")]
    if rules:
        parts.append("\n### Discipline for this role\n\n" + "\n".join(rules))
    return "\n".join(parts) + "\n\n---\n\n"


def agent_markdown_to_toml(
    rendered: str,
    *,
    header_comment: str,
    codex_model: str | None = None,
) -> str:
    """Translate one rendered Claude markdown agent into Codex agent TOML.

    `rendered` is the agent prompt after template rendering (frontmatter +
    body, no provenance line). `header_comment` becomes a leading TOML
    comment — the provenance marker the pruner uses to recognize our files.
    """
    meta, body = split_frontmatter(rendered)
    name = str(meta.get("name", "")).strip()
    if not name:
        raise ValueError("agent frontmatter has no name")
    description = " ".join(str(meta.get("description", "")).split())
    tools = parse_tools(meta.get("tools"))
    effort = reasoning_effort_for(meta.get("model"))
    instructions = codex_agent_preamble(name, tools) + body.lstrip("\n")

    lines = [
        f"# {header_comment}",
        f"name = {toml_basic_string(name)}",
        f"description = {toml_basic_string(description)}",
    ]
    if codex_model:
        lines.append(f"model = {toml_basic_string(codex_model)}")
    lines += [
        f"model_reasoning_effort = {toml_basic_string(effort)}",
        f"sandbox_mode = {toml_basic_string('workspace-write')}",
        f"developer_instructions = {toml_text_block(instructions)}",
    ]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Entry skill metadata (`agents/openai.yaml` beside SKILL.md)
# ---------------------------------------------------------------------------

OPENAI_SKILL_YAML = """\
# Installed by hyperresearch — Codex skill metadata for $hyperresearch.
interface:
  display_name: "Hyperresearch"
  short_description: "Deep research pipeline: fetch sources, critique, ship a cited report"
  default_prompt: "Use $hyperresearch to research: "
policy:
  allow_implicit_invocation: true
"""


# ---------------------------------------------------------------------------
# Stop hook (`.codex/hooks.json`)
# ---------------------------------------------------------------------------

STOP_GATE_SUBCOMMAND = "run stop-gate"


def stop_hook_command(hpr_path: str) -> str:
    """The Stop hook command line — the resolved CLI path plus the subcommand.

    The path is quoted only when it contains whitespace: a bare path runs
    unchanged under sh, cmd, and PowerShell, while a quoted leading token is
    a parse error in PowerShell (it wants `& "..."`).
    """
    exe = hpr_path.replace("\\", "/")
    if any(ch.isspace() for ch in exe):
        exe = f'"{exe}"'
    return f"{exe} {STOP_GATE_SUBCOMMAND}"


def _is_our_stop_entry(entry) -> bool:
    if not isinstance(entry, dict):
        return False
    hooks = entry.get("hooks")
    if not isinstance(hooks, list):
        return False
    return any(
        isinstance(h, dict) and STOP_GATE_SUBCOMMAND in str(h.get("command", ""))
        for h in hooks
    )


def merge_stop_hook(settings: dict, hpr_path: str) -> dict:
    """Return `settings` with exactly one hyperresearch Stop hook entry.

    Foreign hooks — other events, and other Stop entries — are preserved in
    order; only an existing stop-gate entry is replaced.
    """
    merged = dict(settings)
    hooks = merged.get("hooks")
    hooks = dict(hooks) if isinstance(hooks, dict) else {}
    stop = hooks.get("Stop")
    stop = [e for e in stop if not _is_our_stop_entry(e)] if isinstance(stop, list) else []
    stop.append({"hooks": [{"type": "command", "command": stop_hook_command(hpr_path)}]})
    hooks["Stop"] = stop
    merged["hooks"] = hooks
    return merged


# ---------------------------------------------------------------------------
# Stop gate — the decision behind `hyperresearch run stop-gate`
# ---------------------------------------------------------------------------

# Only a run touched this recently can be the one the session is driving; an
# older unfinished manifest is an abandoned run, not a reason to trap the user.
STOP_GATE_WINDOW = timedelta(hours=6)

# Run statuses in which the pipeline is actively expected to continue. A
# paused, blocked (human challenges, budget, failed verify), failed, aborted,
# or done run may legitimately end the turn.
_ACTIVE_STATUSES = ("running",)

STOP_GATE_ENV = "HYPERRESEARCH_STOP_GATE"


def stop_gate_decision(vault, now: datetime | None = None) -> dict | None:
    """The Stop hook's block decision for the newest run in `vault`, or None.

    Blocks only when the newest run is active, touched within
    STOP_GATE_WINDOW, and still has a next step.
    """
    from hyperresearch.core.hooks import step_skill_slug
    from hyperresearch.core.platforms import CODEX, paths_for
    from hyperresearch.core.runs import list_runs, run_resume_position

    runs = list_runs(vault)
    if not runs:
        return None
    manifest = runs[0]
    if manifest.get("status") not in _ACTIVE_STATUSES:
        return None
    try:
        updated = datetime.fromisoformat(manifest["updated_at"])
    except (KeyError, TypeError, ValueError):
        return None
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=UTC)
    now = now or datetime.now(UTC)
    if now - updated > STOP_GATE_WINDOW:
        return None

    next_step = run_resume_position(vault, manifest)["next_step"]
    if next_step is None:
        return None
    skill = step_skill_slug(next_step) or f"step {next_step}"
    step_file = f"{paths_for(CODEX).steps_dir}/{skill}.md"
    tag = manifest.get("vault_tag", "the current run")
    return {
        "decision": "block",
        "reason": (
            f"{tag} is at step {next_step} ({skill}). Continue the pipeline: read "
            f"{step_file} and follow it. Answering without finishing the pipeline "
            "is a failure."
        ),
    }
