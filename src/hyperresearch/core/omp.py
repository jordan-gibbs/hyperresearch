"""OMP (oh-my-pi) translation layer — agent markdown, tool vocabulary.

The pipeline's subagent prompts are written once, as Claude Code markdown
agents (YAML frontmatter + body) in core/hooks.py. OMP wants task agents as
markdown too (`.omp/agents/<name>.md`), so the conversion is small — but the
two conventions are not identical:

    frontmatter name / description  -> name / description (one line, so the
                                       agent roster does not fold it)
    frontmatter tools               -> the OMP tool names (read, write, edit,
                                       bash, web_search, task, eval), CSV
    frontmatter color               -> dropped (Claude Code only)
    frontmatter model               -> `thinking-level` (high for opus-class
                                       roles, else medium); a `model` key only
                                       when the profile sets an `omp_models`
                                       override for the role, so by default the
                                       subagent inherits the OMP session model
    body                            -> body, after a short vocabulary preamble
                                       (plus a per-role note where the body
                                       assumes a Claude-only toolchain — the
                                       browser-fetcher's Chrome lane)

Unlike Codex, OMP has the tools the Claude prompts assume (read / write / edit
/ bash / task), so the preamble only translates vocabulary — the licenses in
the `tools:` line are enforced by OMP itself.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from hyperresearch.core.codex import parse_tools, reasoning_effort_for, split_frontmatter
from hyperresearch.core.render import insert_after_frontmatter

# Claude tool vocabulary -> OMP tool names. OMP auto-adds its hidden `yield`
# tool to any explicit list, so the lists stay 1:1 with the Claude originals.
_OMP_TOOLS: dict[str, str] = {
    "read": "read",
    "write": "write",
    "edit": "edit",
    "bash": "bash",
    "websearch": "web_search",
    "task": "task",
    # The browser-fetcher drives Chrome through Claude-in-Chrome's ToolSearch
    # lane; on OMP the equivalent is the eval tool's `browser` facade.
    "toolsearch": "eval",
}


def tools_to_omp(value: object) -> list[str]:
    """Frontmatter `tools:` (comma string or YAML list) -> OMP tool names.

    Unknown names are kept verbatim (lowercased): a new Claude tool must not
    silently vanish from an agent's license.
    """
    return [_OMP_TOOLS.get(name.lower(), name.lower()) for name in parse_tools(value)]


# Prepended to every agent body. OMP maps the Claude vocabulary onto its own
# tools 1:1, so this is vocabulary only; `_OMP_AGENT_NOTES` carries the rare
# per-role rewrite (the browser-fetcher's Chrome lane).
_OMP_TOOL_MAP = """\
## OMP runtime notes (read first — these override conflicting tool wording below)

You are running as an OMP task agent. The instructions below were written for
Claude Code; translate their tool vocabulary as follows:

- **Read** / **Write** / **Edit** / **Bash** -> the `read` / `write` / `edit` /
  `bash` tools. `edit` takes `old_string` / `new_string`: re-read the file
  first so the anchors are current, and keep every change surgical.
- **WebSearch** -> the `web_search` tool. Never browse or web-fetch a source
  page — fetch it with the hyperresearch CLI (`... fetch "<url>" -j`), exactly
  as spelled below.
- **ToolSearch** (the browser-fetcher's Chrome lane) -> the `eval` tool's
  `browser` facade; that agent's per-role note below spells out the calls.
- **TodoWrite** / `update_plan` -> the `todo` tool.
- "Task result" / "subagent result (final message)" -> the output of the spawn
  you requested, which is delivered back to you as a follow-up message.
- Subagent spawn templates below use `agent:` / `task:` / `solutionSpace:` /
  `prompt:` — those map onto the `task` tool's arguments
  (`{context, tasks: [{agent, task, solutionSpace}]}`): the agent name goes in
  `agent`, the `prompt:` block in `task`, and one line describing how open the
  investigation is in `solutionSpace`.

---

"""


def stopgate_extension(hpr_path: str) -> str:
    """The `.omp/extensions/hyperresearch.ts` source, with the CLI path filled in.

    The extension shells out to `hyperresearch run stop-gate --platform omp`,
    so the resolved CLI path is baked into the file at install time — the same
    contract as the Claude/Codex hooks. No imports: the module is plain
    JS-in-TS, which any OMP runtime (Bun-compiled included) resolves.
    """
    return _read_extension_template().replace("{hpr_path}", hpr_path.replace("\\", "/"))


def _read_extension_template() -> str:
    """Read the packaged stop-gate extension, falling back to the source tree."""
    import importlib.resources

    try:
        return (
            importlib.resources.files("hyperresearch.omp")
            .joinpath("extension_template.ts")
            .read_text(encoding="utf-8")
        )
    except Exception:
        template = Path(__file__).resolve().parent.parent / "omp" / "extension_template.ts"
        return template.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Markdown agent -> OMP agent file
# ---------------------------------------------------------------------------


# Per-role additions for OMP, appended after the vocabulary preamble. The
# browser-fetcher's body is written for Claude-in-Chrome's MCP tools, which do
# not exist on OMP — that lane runs on the `eval` tool's browser facade.
_OMP_AGENT_NOTES: dict[str, str] = {
    "hyperresearch-browser-fetcher": """\
### Browser lane on OMP — replaces the ToolSearch setup below

There is no `ToolSearch` and no `mcp__claude-in-chrome__*` tool here. Drive the
browser from the `eval` tool's `browser` facade instead:

```js
const tab = await browser.open({ app: { relay: true }, name: "hyperresearch-escalations" });
await tab.goto("<the escalation url>");
const text = await tab.extract("markdown");   // or await tab.observe() / await tab.text()
await tab.close();
```

- `app.relay: true` attaches to the user's real, logged-in Chrome through the
  OMP relay (`omp browser-relay` runs that relay). Name a dedicated tab; never
  navigate the visible tab without authorization.
- No relay? Fall back to a managed browser —
  `browser.open({ name: "hyperresearch-escalations", url: "<url>", headed: true })`,
  which installs its own Chromium on first use. It is not logged in, so
  login-gated pages still end as `needs_human`.
- Read with `tab.observe()`, `tab.text()`, `tab.html()`, `tab.extract(...)`; act
  with `tab.click` / `tab.fill` / `tab.press` / `tab.select`; pass
  `persist: true` on `open` for a multi-step login.
- Everything below still stands: CAPTCHAs / logins / 2FA are the human's, mark
  them `needs_human`, and write the note with the same `fetch_provider` value.

""",
}


def agent_markdown_to_omp(
    rendered: str,
    *,
    header_comment: str,
    omp_model: str | None = None,
) -> str:
    """Translate one rendered Claude markdown agent into an OMP agent file.

    `rendered` is the agent prompt after template rendering (frontmatter +
    body, no provenance line). `header_comment` becomes the provenance comment
    after the frontmatter — the marker the pruner uses to recognize our files.
    """
    meta, body = split_frontmatter(rendered)
    name = str(meta.get("name", "")).strip()
    if not name:
        raise ValueError("agent frontmatter has no name")
    description = " ".join(str(meta.get("description", "")).split())
    tools = tools_to_omp(meta.get("tools"))

    front: dict[str, str] = {
        "name": name,
        "description": description,
        "tools": ", ".join(tools),
    }
    if omp_model:
        front["model"] = omp_model
    front["thinking-level"] = reasoning_effort_for(meta.get("model"))

    frontmatter = yaml.safe_dump(
        front,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
        width=10**6,
    )
    content = (
        "---\n"
        + frontmatter
        + "---\n"
        + _OMP_TOOL_MAP
        + _OMP_AGENT_NOTES.get(name, "")
        + body.lstrip("\n")
    )
    return insert_after_frontmatter(content, header_comment)
