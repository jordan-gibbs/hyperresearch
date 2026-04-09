# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-04-07

### Added

- MCP server with 8 read-only tools (`pip install llm-kasten[mcp]`)
- `kasten mcp` command (stdio transport for Claude Desktop, Cursor)
- `kasten tags --min N` to filter out low-count tags
- `kasten tag alias` and `kasten tag suggest` for tag management
- `kasten note update` for single-note metadata changes
- `kasten note new --body-file` to avoid shell escaping
- `kasten note new` returns `existing_tags` in JSON to reduce tag noise
- `kasten search` auto-includes note bodies in JSON mode
- `kasten search --linked-from`, `--linked-to`, `--min-inbound` graph filters
- `kasten repair --enrich` auto-fills missing tags and summaries
- `kasten graph stub` creates stub notes for all broken links
- `kasten serve` with interactive force-directed knowledge graph
- `kasten dedup` for content similarity detection
- Auto-inject docs into CLAUDE.md, AGENTS.md, GEMINI.md, copilot-instructions.md
- Temporal index pages: by-month, stale notes, most-linked
- `-j` short flag for `--json` on every command
- Alphanumeric search tokenization (mamba3 matches mamba 3)
- Plural tag normalization during sync
- Note lifecycle: draft, review, evergreen, stale, deprecated, archive
- `missing-summary` and `singleton-tags` lint rules
- Built-in note templates: concept, reference, guide, comparison, moc
- Vintage cream/brown theme for web UI

### Removed

- External LLM dependencies (OpenAI, Anthropic, Ollama providers)
- `kasten compile` and `kasten ask` commands (agents drive everything)
- `kasten ingest` (file, web, pdf) -- agents write files directly
- Semantic search and ranking modules (dead code)
- `kasten promote` and `kasten diff` (redundant with repair and sync --dry-run)

### Fixed

- Wiki-link parser strips trailing backslash from shell escaping artifacts
- URLs in `[[https://...]]` no longer treated as broken note references
- Index generator deletes stale pages before regenerating
- XSS protection in web UI
- Ctrl+C works on Windows for `kasten serve`
- FTS5 BM25 weights now read from config (were hardcoded)
- Import writes to knowledge directory, not vault root
- Batch operations validate status values and handle per-file errors

## [0.1.0] - 2026-04-06

Initial release.

### Core

- Markdown files with YAML frontmatter as source of truth
- SQLite FTS5 full-text search with BM25 ranking and porter stemming
- `[[wiki-link]]` parsing with backlink tracking and broken link detection
- mtime + SHA-256 change detection with atomic transactions

### CLI

- `kasten init`, `status`, `sync`, `search`, `note` CRUD, `graph`, `lint`, `repair`
- `kasten index build` auto-generated wiki pages
- `kasten batch` bulk operations
- `kasten export json` and `export vault`
- `kasten import`, `watch`, `serve`, `git log`
- `--json` on every command with consistent envelope format

[0.2.0]: https://github.com/jordan-gibbs/llm-kasten/releases/tag/v0.2.0
[0.1.0]: https://github.com/jordan-gibbs/llm-kasten/releases/tag/v0.1.0
