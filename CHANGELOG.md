# Changelog

## [0.2.0] - 2026-04-10

### New

- **`/research` skill** — Scripted deep research workflow as a Claude Code slash command. Clarifies ambiguous requests, searches broadly, fetches aggressively, follows rabbit holes, auto-curates, synthesizes, and presents findings with hub notes
- **`hyperresearch setup`** — Interactive TUI onboarding: web provider, browser profile selection/creation, agent hooks. Auto-launches on first `install`
- **`hyperresearch fetch-batch`** — Concurrent multi-URL fetch with batched sync (O(1) syncs instead of O(n))
- **`hyperresearch link --auto`** — Holistic auto-linking: scans notes for mentions of other notes' titles and appends wiki-links
- **`hyperresearch assets list/path`** — Browse downloaded screenshots and images
- **`--save-assets` flag** — Opt-in screenshot + content image download on fetch
- **`--visible` flag** — Non-headless browser for stubborn auth sites (auto-enabled for LinkedIn, Twitter, Facebook, Instagram, TikTok)
- **`--max-tokens` on search** — Token budget truncation for context-aware agents
- **Auto-curation at fetch time** — Notes arrive with auto-generated tags and summaries
- **MCP write tools** — `fetch_url`, `create_note`, `update_note` (MCP server is now read-write)
- **MinHash+LSH dedup** — O(n) approximate dedup for large vaults (200+ notes), falls back to brute-force for small vaults
- **Hub notes auto-surfaced** after research sessions
- **Synthesis notes** saved as feedback loop (agent Q&A becomes searchable)
- **`hyperresearch-fetcher` subagent** — Haiku-powered URL fetcher installed to `.claude/agents/`
- **Login wall detection** — `AUTH_REQUIRED` error instead of saving login page junk
- **Smart SPA wait** — Polls DOM stability (2s initial + 10s ceiling) instead of fixed delays

### Changed

- **crawl4ai is the sole browser provider** — Removed firecrawl, tavily, trafilatura
- **crawl4ai v0.8.x API** — AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, arun/arun_many
- **Authenticated crawling** via crawl4ai browser profiles (`crwl profiles` or setup TUI)
- **CLI path baked into CLAUDE.md** — Works without venv activation (forward slashes for Windows bash)
- **Deep research philosophy** — Agent docs say "over-collect, then prune" and "go down rabbit holes"
- **Windows encoding fix** — `stream.reconfigure(encoding="utf-8")` at startup, no more charmap crashes
- **Note slugs capped at 80 chars** — Avoids Windows MAX_PATH issues
- **Anti-bot stealth always on** when crawl4ai is used (no setup question)
- **Config commands** now support `web.provider`, `web.profile`, `web.magic`

### Removed

- Dead fields: `confidence`, `superseded_by`, `llm_compiled`, `llm_model`, `compile_source`
- Tag plural normalization (use explicit `tag_aliases` instead)
- `deprecated-no-successor` and `low-confidence` lint rules
- Firecrawl, Tavily, Trafilatura web providers

## [0.1.0] - 2026-04-09

Initial release. Forked from [llm-kasten](https://github.com/jordan-gibbs/llm-kasten) and repositioned for agent-driven research workflows.

### New

- **`hyperresearch install`** — One-step setup: init vault + inject agent docs + install PreToolUse hooks for Claude Code, Codex, Cursor, Gemini CLI
- **`hyperresearch fetch <url>`** — Fetch a URL, extract content, save as a research note with source tracking
- **`hyperresearch research <topic>`** — Deep research: web search, fetch results, follow links, save as linked notes, generate synthesis MOC
- **`hyperresearch sources list/check`** — List and query fetched web sources
- **Web provider plugin system** — Pluggable backends: builtin (stdlib), crawl4ai (local headless browser)
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

[0.2.0]: https://github.com/jordan-gibbs/hyperresearch/releases/tag/v0.2.0
[0.1.0]: https://github.com/jordan-gibbs/hyperresearch/releases/tag/v0.1.0
