"""OMP translation layer — entry skill, step files, agents, stop-gate extension.

OMP (oh-my-pi) runs Claude and OpenAI models behind one tool set — `read`,
`write`, `edit`, `bash`, `web_search`, `task` (subagents), `todo` — so one
install serves either model family. The pipeline prompts already have a
layout that fits it: the Codex branches of the templates (plain step files,
spawned custom agents, no Skill tool, no browser lane). hyperresearch renders
those branches and translates the Codex vocabulary instead of adding a third
branch to every template:

    .hyperresearch/codex/steps/        -> .hyperresearch/omp/steps/
    cat <step file>                    -> read <step file>:raw
    custom agent .codex/agents/X.toml  -> OMP agent X, spawned with the task tool
    apply_patch / update_plan          -> edit / todo
    $hyperresearch / codex exec        -> /skill:hyperresearch / omp -p
    the per-project Stop hook          -> the hyperresearch extension

Agents are the Claude Code markdown agents with OMP frontmatter. OMP enforces
an agent's `tools:` list, as Claude Code does, so the tool locks carry over.
There is no `model` key: a subagent runs on the session's model, Claude or
OpenAI, unless OMP's own `task.agentModelOverrides` routes it. `thinking-level`
follows the role's model class, and `read-summarize: false` keeps OMP's read
tool from returning structural summaries where the prompts require full text.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import yaml

from hyperresearch.core.codex import parse_tools, reasoning_effort_for, split_frontmatter

EXTENSION_FILENAME = "hyperresearch.ts"


def user_omp_agent_dir(home: Path | None = None) -> Path:
    """OMP's user-level agent directory: $PI_CODING_AGENT_DIR, else ~/.omp/agent."""
    configured = os.environ.get("PI_CODING_AGENT_DIR", "").strip()
    if configured:
        return Path(configured).expanduser()
    return (home or Path.home()) / ".omp" / "agent"


# ---------------------------------------------------------------------------
# Skills: Codex render -> OMP
# ---------------------------------------------------------------------------

_AGENT_NAME = r"hyperresearch-[a-z0-9<>-]+"

# Order matters: specific phrasings before the generic fallbacks.
_SKILL_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    # The Codex Stop hook is a per-project file the sandbox keeps read-only;
    # on OMP the stop gate is the hyperresearch extension, already installed.
    (
        re.compile(r", plus the Stop hook in `\.codex/hooks\.json`\.[^\n]*?carry on without the hook\."),
        ".",
    ),
    (re.compile(r"\.hyperresearch/codex/steps/"), ".hyperresearch/omp/steps/"),
    (re.compile(r"\bcat (\.hyperresearch/omp/steps/[^\s`]+\.md)"), r"read \1:raw"),
    (re.compile(r"\bcat \.agents/skills/hyperresearch/SKILL\.md"), "read skill://hyperresearch"),
    (
        re.compile(
            rf"custom_agent: ({_AGENT_NAME})(\s+)# spawn the custom agent defined in "
            rf"\.codex/agents/{_AGENT_NAME}\.toml"
        ),
        r"agent: \1\2# task tool: set `agent` to this name",
    ),
    (
        re.compile(r"custom agent \(defined in `\.codex/agents/`\)"),
        "OMP agent (spawned with the `task` tool, `agent` set to its name)",
    ),
    (
        re.compile(r"a custom agent in `\.codex/agents/`"),
        "an OMP agent (spawn it with the `task` tool)",
    ),
    (re.compile(rf"custom[- ]agent `\.codex/agents/({_AGENT_NAME})\.toml`"), r"OMP agent `\1`"),
    (re.compile(rf" ?\(`\.codex/agents/{_AGENT_NAME}\.toml`\)"), ""),
    (re.compile(rf"`\.codex/agents/({_AGENT_NAME})\.toml`"), r"OMP agent `\1`"),
    (re.compile(r"[Cc]ustom[- ]agent subagents"), "OMP subagents"),
    (re.compile(r"[Cc]ustom[- ]agent"), "OMP agent"),
    (re.compile(r"\bapply_patch\b"), "edit"),
    (re.compile(r"\bupdate_plan\b"), "todo"),
    (re.compile(r"\bcodex exec\b"), "omp -p"),
    (re.compile(r"--target codex\b"), "--target omp"),
    (re.compile(r"\$hyperresearch\b"), "/skill:hyperresearch"),
    (re.compile(r"\bCodex\b"), "OMP"),
)

_ENTRY_NOTE = (
    "> **Running in OMP.** Read every step file in full with `read <path>:raw`, page by "
    "page; never act on an elided view. Spawn subagents with the `task` tool: one "
    "`tasks[]` item per subagent, `agent` set to the `hyperresearch-*` name, the spawn "
    "prompt as `task`. They run in the background and their results arrive on their "
    "own: keep working, or call `wait` when you have nothing else to do. Plan with "
    "`todo`, patch with `edit`, run the CLI with `bash`. Subagents run on this "
    "session's model, Claude or OpenAI, unless OMP's `task.agentModelOverrides` routes "
    "them.\n"
)

_STEP_NOTE = (
    "> **OMP:** spawn subagents with the `task` tool (`agent` = the `hyperresearch-*` "
    "name); read files in full with `read <path>:raw`; patch with `edit`.\n"
)

_H1_RE = re.compile(r"^# .*$", re.MULTILINE)


def _insert_note(text: str, note: str) -> str:
    """Insert `note` as its own paragraph after the first H1 (or at the top)."""
    match = _H1_RE.search(text)
    if match is None:
        return note + "\n" + text
    end = match.end()
    return text[:end] + "\n\n" + note.rstrip("\n") + text[end:]


def translate_skill(text: str, *, entry: bool) -> str:
    """Translate a Codex-rendered skill or step file into its OMP form."""
    for pattern, replacement in _SKILL_RULES:
        text = pattern.sub(replacement, text)
    return _insert_note(text, _ENTRY_NOTE if entry else _STEP_NOTE)


# ---------------------------------------------------------------------------
# Agents: Claude markdown -> OMP agent markdown
# ---------------------------------------------------------------------------

_TOOLS: dict[str, str] = {
    "Read": "read",
    "Write": "write",
    "Edit": "edit",
    "Bash": "bash",
    "Glob": "glob",
    "Grep": "grep",
    "WebSearch": "web_search",
    "WebFetch": "read",
    "Task": "task",
    "TodoWrite": "todo",
}

# Agents that delegate to other pipeline agents, and which ones they spawn.
_SPAWNS: dict[str, tuple[str, ...]] = {
    "hyperresearch-depth-investigator": ("hyperresearch-fetcher",),
}


def _agent_preamble(tools: list[str]) -> str:
    lines = [
        "## OMP runtime notes (read first; these override conflicting tool wording below)",
        "",
        "You are running as an OMP subagent. The instructions below were written for "
        "Claude Code; their tool names map as follows:",
        "",
        "- **Read** -> `read`. Read files in full: use the `:raw` selector or explicit "
        "line ranges, page through long files, and never act on an elided or "
        "summarized view.",
    ]
    if "write" in tools:
        lines.append("- **Write** -> `write`.")
    if "edit" in tools:
        lines.append("- **Edit** -> `edit`, with surgical hunks only.")
    if "bash" in tools:
        lines.append("- **Bash** -> `bash`.")
    if "web_search" in tools:
        lines.append("- **WebSearch** -> `web_search`.")
    if "task" in tools:
        lines.append(
            "- **Task** -> the `task` tool: one `tasks[]` item per subagent, `agent` set "
            "to the agent name, the spawn prompt as `task`. Results arrive on their own; "
            "call `wait` when you have nothing else to do."
        )
    else:
        lines.append("- You cannot spawn subagents.")
    lines.append(
        "- Never use a browsing tool for source pages; fetch them with the hyperresearch "
        'CLI (`... fetch "<url>" -j`), exactly as spelled below.'
    )
    return "\n".join(lines) + "\n\n---\n\n"


def agent_markdown_to_omp(rendered: str, *, header: str) -> str:
    """Translate one rendered Claude markdown agent into an OMP agent file.

    `rendered` is the agent prompt after template rendering (frontmatter +
    body, no provenance line); `header` is the provenance line placed after
    the frontmatter, which the pruner uses to recognize our files.
    """
    meta, body = split_frontmatter(rendered)
    name = str(meta.get("name", "")).strip()
    if not name:
        raise ValueError("agent frontmatter has no name")
    tools: list[str] = []
    for claude_tool in parse_tools(meta.get("tools")):
        mapped = _TOOLS.get(claude_tool)
        if mapped and mapped not in tools:
            tools.append(mapped)

    front: dict[str, Any] = {
        "name": name,
        "description": " ".join(str(meta.get("description", "")).split()),
        "tools": tools,
    }
    if "task" in tools and name in _SPAWNS:
        front["spawns"] = list(_SPAWNS[name])
    front["thinking-level"] = reasoning_effort_for(meta.get("model"))
    front["read-summarize"] = False

    frontmatter = yaml.safe_dump(front, sort_keys=False, allow_unicode=True, width=1_000_000)
    return f"---\n{frontmatter}---\n{header}\n\n{_agent_preamble(tools)}{body.lstrip(chr(10))}"


# ---------------------------------------------------------------------------
# Stop gate: an OMP extension instead of a hook file
# ---------------------------------------------------------------------------

_EXTENSION_TEMPLATE = """\
// Installed by hyperresearch (`hyperresearch install --target omp`). Re-running
// the install overwrites this file.
//
// Keeps an OMP session on the hyperresearch pipeline it is running. The
// orchestrator records every step with `hyperresearch run init` / `run step`;
// once this session has run one of those, its `session_stop` asks
// `hyperresearch run stop-gate` whether the newest run in the session's vault is
// mid-pipeline and, if so, sends the agent back to the next step. OMP caps these
// advisory continuations. Sessions that never ran the pipeline are left alone,
// so a vault in a parent directory cannot pull unrelated sessions into a run.
// Set HYPERRESEARCH_STOP_GATE=0 to turn the gate off.

const HPR = __HPR__;
const RUN_COMMAND = /\\b(?:hyperresearch|hpr)\\b[^\\n]*\\brun\\s+(?:init|step)\\b/;

interface ToolResultEvent {
  toolName?: string;
  input?: { command?: unknown };
  isError?: boolean;
}
interface Context {
  cwd?: string;
  agent?: { kind?: string };
}
interface ExecResult {
  stdout?: string;
}
interface ExtensionApi {
  on(event: string, handler: (event: unknown, ctx: Context) => unknown): void;
  exec(command: string, args: string[], options?: { cwd?: string }): Promise<ExecResult>;
}

export default function hyperresearch(pi: ExtensionApi): void {
  // Factories are bound once per session, so this flag is per session.
  let driving = false;

  pi.on("session_start", () => {
    driving = false;
  });
  pi.on("session_switch", () => {
    driving = false;
  });
  pi.on("tool_result", (event, ctx) => {
    const e = event as ToolResultEvent;
    if (e.toolName !== "bash" || e.isError || ctx.agent?.kind === "sub") return;
    if (RUN_COMMAND.test(String(e.input?.command ?? ""))) driving = true;
  });
  pi.on("session_stop", async (_event, ctx) => {
    if (!driving || !ctx.cwd) return;
    try {
      const result = await pi.exec(
        HPR,
        ["run", "stop-gate", "--cwd", ctx.cwd, "--platform", "omp"],
        { cwd: ctx.cwd },
      );
      const lines = String(result?.stdout ?? "").trim().split("\\n");
      const last = lines[lines.length - 1];
      if (!last) return;
      const decision = JSON.parse(last) as { decision?: string; reason?: string };
      if (decision.decision === "block" && decision.reason) {
        return { continue: true, additionalContext: decision.reason };
      }
    } catch {
      return;
    }
  });
}
"""


def extension_source(hpr_path: str) -> str:
    """The stop-gate extension, with the resolved CLI path baked in."""
    return _EXTENSION_TEMPLATE.replace("__HPR__", json.dumps(hpr_path.replace("\\", "/")))
