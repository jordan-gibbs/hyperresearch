# Hyperresearch — Agent Guide

## Environment
- Python support is `>=3.11,<3.14` (3.14 is not supported).
- Use a local virtualenv for all commands:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
```

## Fast verification loop
Run these before claiming completion:

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check src tests
.venv/bin/mypy src
```

## Repo conventions
- Keep markdown as source of truth; SQLite is derived cache.
- Prefer small, surgical edits over broad rewrites.
- Preserve CLI JSON compatibility (`--json` output paths are user-facing contracts).
- Keep generated research artifacts out of `research/notes/` unless intentionally creating notes.

## Key paths
- CLI commands: `src/hyperresearch/cli/`
- Core vault/indexing logic: `src/hyperresearch/core/`
- Search: `src/hyperresearch/search/`
- Models: `src/hyperresearch/models/`
- Tests: `tests/`

## Agent docs, hooks, and skills
- Project agent docs are maintained in both `CLAUDE.md` and `AGENTS.md` by `inject_agent_docs`.
- The research-reminder hook is installed into both `.claude/settings.json` and `.claude/settings.local.json`; the hook accepts Claude-style `tool_name` and OpenCode-style lowercase `tool` payloads.
- An OpenCode-native plugin is installed at `.opencode/plugins/hyperresearch-reminder.js` and uses `tool.definition` / `tool.execute.before` hooks.
- Pipeline skills and subagent definitions are installed under `.claude/` (OpenCode reads these through Claude-compat paths).
