# Changelog

## [0.1.0] - 2026-04-09

Initial release. Forked from [llm-kasten](https://github.com/jordan-gibbs/llm-kasten) and repositioned for agent-driven research workflows.

### New

- **`hyperresearch install`** — One-step setup: init vault + inject agent docs + install PreToolUse hooks for Claude Code, Codex, Cursor, Gemini CLI
- **`hyperresearch fetch <url>`** — Fetch a URL, extract content, save as a research note with source tracking
- **`hyperresearch research <topic>`** — Deep research: web search, fetch results, follow links, save as linked notes, generate synthesis MOC
- **`hyperresearch sources list/check`** — List and query fetched web sources
- **Web provider plugin system** — Pluggable backends: builtin (stdlib), crawl4ai, tavily, firecrawl, trafilatura
- **Agent hook system** — PreToolUse hooks that remind agents to check the research base before web searches
- **Sources table** — URL deduplication, domain tracking, fetch metadata
- **Extended frontmatter** — `source_domain`, `fetched_at`, `fetch_provider` fields
- **MCP server** with 10 tools including `check_source` and `list_sources`

### From kasten (the backbone)

- SQLite FTS5 full-text search with BM25 ranking
- Markdown notes with YAML frontmatter as source of truth
- `[[wiki-link]]` tracking with backlinks
- `--json` / `-j` structured output on every command
- Note lifecycle: draft → review → evergreen → stale → deprecated → archive
- Auto-sync (mtime + SHA-256 change detection)
- Agent doc injection (CLAUDE.md, AGENTS.md, GEMINI.md, copilot-instructions.md)
- Web viewer with force-directed knowledge graph
- 70 tests

[0.1.0]: https://github.com/jordan-gibbs/hyperresearch/releases/tag/v0.1.0
