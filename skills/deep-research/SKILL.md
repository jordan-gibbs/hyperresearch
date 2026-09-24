---
name: deep-research
description: Deep research in Claude Code with hyperresearch. Use when the user asks for deep research, a research report, a literature review, or a multi-source analysis with verified citations. Checks that the hyperresearch CLI is installed, sets it up in the current project, then hands off to the /hyperresearch pipeline (a tier-adaptive 16-step pipeline with a persistent source vault). Not for quick lookups one or two searches can answer.
---

# Deep research with hyperresearch

This skill is a bootstrap. The research pipeline itself is the `hyperresearch`
skill plus 16 step skills and a set of subagents, which the `hyperresearch`
Python package renders and installs into the project's `.claude/` directory.
This file does not contain the pipeline. Do not try to run the research from
here.

## 1. Check the CLI

Run:

```bash
hyperresearch --version
```

If the command is not found, stop and tell the user:

> hyperresearch is not installed. Install it with `pip install hyperresearch`
> (Python 3.11 to 3.14), then ask again.

You may run `pip install hyperresearch` yourself only if the user says to.

## 2. Install into this project

If `.claude/skills/hyperresearch/SKILL.md` does not exist in the working
directory, run:

```bash
hyperresearch install . --json
```

This creates the vault (`.hyperresearch/`, `research/`), adds a short block to
`CLAUDE.md`, and installs the entry skill, the 16 step skills, the subagents
and a PreToolUse hook under `.claude/`. It is safe to re-run; it no-ops on
files that are already current.

Tell the user in one line what was installed.

## 3. Hand off

Invoke the installed router with the user's research request, verbatim:

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
