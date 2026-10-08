---
name: deep-research
description: Deep research with hyperresearch, for Claude Code, OpenAI Codex, and OMP. Use when the user asks for deep research, a research report, a literature review, or a multi-source analysis with verified citations. Checks that the hyperresearch CLI is installed, sets it up in the current project for the agent you are running in, then hands off to the hyperresearch pipeline (a tier-adaptive 16-step pipeline with a persistent source vault). Not for quick lookups one or two searches can answer.
license: MIT
compatibility: Requires Python 3.11+ and the hyperresearch CLI (pip install hyperresearch), plus network access for fetching sources. Works in Claude Code, the OpenAI Codex CLI, and OMP (oh-my-pi); under Codex the session needs a writable workspace with network enabled.
---

# Deep research with hyperresearch

This skill is a bootstrap. The research pipeline itself is an entry skill plus
16 step procedures and a set of subagents, which the `hyperresearch` Python
package renders and installs into the project. This file does not contain the
pipeline. Do not try to run the research from here, and do not answer the
research question from your own knowledge: the pipeline is the deliverable.

## 1. Check the CLI

Run:

```bash
hyperresearch --version
```

If the command is not found, stop and tell the user:

> hyperresearch is not installed. Install it with `pip install hyperresearch`
> (Python 3.11 to 3.14), then ask again.

You may run `pip install hyperresearch` yourself only if the user says to.

## 2. Pick your branch

You know which agent you are. Follow exactly one branch.

- **Claude Code** (you have `Skill` and `Task` tools): section 3A.
- **OpenAI Codex** (you edit files with `apply_patch`, spawn custom agents,
  and skills are invoked as `$name`): section 3B.
- **OMP (oh-my-pi)** (you have `read`/`write`/`edit`/`bash` tools, a `task`
  tool that dispatches agents, and skills reachable as `skill://name`):
  section 3C.

If you genuinely cannot tell, look at the working directory: a `.codex/` or
`.agents/` directory and no `.claude/` means Codex; a `.omp/` directory means
OMP; the reverse means Claude Code. Still unsure: ask the user which one they
are using.

## 3A. Claude Code

If `.claude/skills/hyperresearch/SKILL.md` does not exist in the working
directory, run:

```bash
hyperresearch install . --json
```

This creates the vault (`.hyperresearch/`, `research/`), adds a short block to
`CLAUDE.md`, and installs the entry skill, the 16 step skills, the subagents
and a PreToolUse hook under `.claude/`. It is safe to re-run; it no-ops on
files that are already current. Tell the user in one line what was installed.

Then invoke the installed router with the user's research request, verbatim:

```
Skill(skill: "hyperresearch", args: "<the user's research request>")
```

From then on, follow the `hyperresearch` skill. It owns the query, the tier
choice, and every step.

If the `hyperresearch` skill is not available yet (Claude Code loads new
subagents at session start, and some versions do the same for skills), tell
the user that setup is done and ask them to restart Claude Code in this
directory and run:

```
/hyperresearch <their research request>
```

## 3B. OpenAI Codex

If `.agents/skills/hyperresearch/SKILL.md` does not exist in the working
directory, run:

```bash
hyperresearch install . --target codex --json
```

This creates the vault (`.hyperresearch/`, `research/`), adds a short block to
`AGENTS.md`, and installs the entry skill at `.agents/skills/hyperresearch/`,
the step procedures under `.hyperresearch/codex/steps/`, the custom agents
under `.codex/agents/`, and a Stop hook in `.codex/hooks.json`. It is safe to
re-run. Tell the user in one line what was installed.

If the install (or any later `hyperresearch fetch`) fails with a permission or
network error, the session is sandboxed read-only or offline. Stop and tell
the user to restart Codex with a writable workspace and network access, for
example:

```bash
codex --sandbox workspace-write -c sandbox_workspace_write.network_access=true
```

Then hand off. Codex discovers skills when a session starts, so a skill
installed a moment ago may not be listed yet. The robust path is to read the
entry skill directly and follow it:

1. Read `.agents/skills/hyperresearch/SKILL.md` in full (for example
   `cat .agents/skills/hyperresearch/SKILL.md`).
2. Follow it with the user's research request, verbatim, as the query. It is
   the same procedure `$hyperresearch <request>` would load. It owns the
   query, the tier choice, and every step, and each step tells you which
   procedure file under `.hyperresearch/codex/steps/` to read next.

If `$hyperresearch` already appears in your skill list, invoking it with the
request is equivalent. In later sessions the user can start a run directly
with `$hyperresearch <question>`.

Two things differ from Claude Code, and the entry skill covers both: there is
no browser lane (blocked fetches stay queued and are listed for the user at
the end), and the Stop hook, once Codex trusts the project's hooks, will not
let the session finish while a run is mid-pipeline.

## 3C. OMP (oh-my-pi)

If `.omp/skills/hyperresearch/SKILL.md` does not exist in the working
directory, run:

```bash
hyperresearch install . --target omp --json
```

This creates the vault (`.hyperresearch/`, `research/`), adds a short block to
`AGENTS.md`, and installs the entry skill at `.omp/skills/hyperresearch/`, the
`/hyperresearch` command at `.omp/commands/hyperresearch.md`, the step
procedures under `.hyperresearch/omp/steps/`, the subagents under
`.omp/agents/`, and a stop-gate extension at `.omp/extensions/`. It is safe to
re-run. Tell the user in one line what was installed.

Then hand off. OMP discovers skills when a session starts, so one installed a
moment ago may not be listed yet. The robust path is to read the entry skill
directly and follow it:

1. Read the entry skill in full — `read skill://hyperresearch` resolves the
   file OMP discovered.
2. Follow it with the user's research request, verbatim, as the query. It owns
   the query, the tier choice, and every step, and each step tells you which
   procedure file under `.hyperresearch/omp/steps/` to read next. Spawns go
   through the `task` tool: one `agent` + `task` + `solutionSpace` item per
   subagent, several items in one call for a parallel wave.

If `/hyperresearch` already appears in your command list, invoking it with the
request is equivalent. In later sessions the user can start a run directly
with `/hyperresearch <question>`.

Unlike Codex, OMP keeps the browser lane (the browser-fetcher drives a real
browser through the `eval` tool's `browser` facade), and the stop gate is
advisory: it asks for one continuation per stop, capped at 8, instead of
refusing. Both are covered by the entry skill.
