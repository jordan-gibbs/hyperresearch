# Contributing to hyperresearch

Thank you for your interest in contributing.

## Development setup

```bash
git clone https://github.com/jordan-gibbs/hyperresearch.git
cd hyperresearch
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -e ".[dev]"
```

## Running tests

```bash
python -m pytest tests/ -v
```

All tests must pass before submitting a PR. The full suite takes a minute or two; run a single file while iterating.

## Code style

This project uses [ruff](https://docs.astral.sh/ruff/) for linting:

```bash
ruff check src/ tests/
```

Configuration is in `pyproject.toml`. Line length is 100 characters.

## Type checking

```bash
mypy src/hyperresearch/
```

Strict mode is enabled in `pyproject.toml`.

## Submitting changes

1. Fork the repository.
2. Create a branch from `main`.
3. Make your changes with tests.
4. Run `ruff check src/ tests/` and `python -m pytest tests/`.
5. Open a pull request against `main`.

Keep PRs focused on a single change. Include a clear description of what changed and why.

## Reporting issues

Open an issue at [github.com/jordan-gibbs/hyperresearch/issues](https://github.com/jordan-gibbs/hyperresearch/issues). Include:

- What you expected to happen
- What actually happened
- Steps to reproduce
- hyperresearch version (`hyperresearch --version`)
- Python version and OS

## Architecture overview

- `src/hyperresearch/core/` -- vault management, sync engine, frontmatter parsing, SQLite schema
- `src/hyperresearch/cli/` -- typer CLI commands, output formatting
- `src/hyperresearch/search/` -- FTS5 search engine, filters, ranking
- `src/hyperresearch/models/` -- Pydantic models for notes, output envelopes
- `src/hyperresearch/graph/` -- link parsing (shared patterns)
- `src/hyperresearch/indexgen/` -- auto-generated index page builder
- `src/hyperresearch/web/` -- pluggable web providers (fetch and search backends)
- `src/hyperresearch/export/` -- export formatters
- `src/hyperresearch/mcp/` -- MCP server exposing research-base tools to agents
- `src/hyperresearch/skills/` -- bundled research skills installed into the harness
- `src/hyperresearch/serve/` -- lightweight web UI server
- `tests/` -- pytest test suite

The key design principle: markdown files are the source of truth, SQLite is a derived cache that can be rebuilt at any time with `hyperresearch sync --force`.
