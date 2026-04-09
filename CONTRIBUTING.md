# Contributing to kasten

Thank you for your interest in contributing.

## Development setup

```bash
git clone https://github.com/jordan-gibbs/kasten.git
cd kasten
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -e ".[dev]"
```

## Running tests

```bash
python -m pytest tests/ -v
```

All tests must pass before submitting a PR. The test suite runs in under 30 seconds.

## Code style

This project uses [ruff](https://docs.astral.sh/ruff/) for linting:

```bash
ruff check src/
ruff format src/
```

Configuration is in `pyproject.toml`. Line length is 100 characters.

## Type checking

```bash
mypy src/kasten/
```

Strict mode is enabled in `pyproject.toml`.

## Submitting changes

1. Fork the repository.
2. Create a branch from `main`.
3. Make your changes with tests.
4. Run `ruff check src/` and `python -m pytest tests/`.
5. Open a pull request against `main`.

Keep PRs focused on a single change. Include a clear description of what changed and why.

## Reporting issues

Open an issue at [github.com/jordan-gibbs/kasten/issues](https://github.com/jordan-gibbs/kasten/issues). Include:

- What you expected to happen
- What actually happened
- Steps to reproduce
- kasten version (`kasten --version`)
- Python version and OS

## Architecture overview

- `src/kasten/core/` -- vault management, sync engine, frontmatter parsing, SQLite schema
- `src/kasten/cli/` -- typer CLI commands, output formatting
- `src/kasten/search/` -- FTS5 search engine, filters, ranking
- `src/kasten/models/` -- Pydantic models for notes, output envelopes
- `src/kasten/graph/` -- link parsing (shared patterns)
- `src/kasten/indexgen/` -- auto-generated index page builder
- `src/kasten/ingest/` -- file, web, PDF ingestion
- `src/kasten/compile/` -- LLM compilation pipeline
- `src/kasten/llm/` -- provider abstraction (OpenAI, Anthropic, Ollama)
- `src/kasten/serve/` -- lightweight web UI server
- `tests/` -- pytest test suite

The key design principle: markdown files are the source of truth, SQLite is a derived cache that can be rebuilt at any time with `kasten sync --force`.
