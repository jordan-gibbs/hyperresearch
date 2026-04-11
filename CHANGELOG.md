# Changelog

## [0.3.0] - 2026-04-11

### New

- **Native PDF extraction** — PDFs detected by URL pattern, downloaded directly with httpx, text extracted with pymupdf. No browser needed. arXiv `/abs/` links auto-convert to `/pdf/`.
- **Raw file storage** — PDF bytes saved to `research/raw/<note-id>.pdf`, linked from note frontmatter via `raw_file:` field. Agent can read the raw PDF directly.
- **Junk page detection** — `WebResult.looks_like_junk()` catches Cloudflare captchas, error pages, cookie walls, binary garbage, reCAPTCHA, and empty content before saving. Returns `JUNK_CONTENT` error instead of creating useless notes.
- **Gap analysis step** — after drafting the report, agent re-reads the original query word by word, identifies gaps, and does another full round of research to fill them.
- **Adversarial audit** — two subagents (comprehensiveness auditor + logic/structure auditor) review the draft in parallel. Runs up to 2 loops. Agent uses wait time productively to improve summaries and tags.
- **Source checkpoint** — agent must review collected sources before writing any draft. Checks coverage breadth, missing angles, uncited references. Expects 50-100+ sources on complex topics.
- **Scholarly API guidance** — CLAUDE.md and `/research` skill now encourage use of arXiv, Semantic Scholar, CrossRef, and PubMed APIs for academic research.
- **Date injection** — today's date injected programmatically into CLAUDE.md at install time.
- **Multi-round research emphasis** — agent docs stress multiple rounds of search → fetch → follow links, spawning 10-20 fetcher agents per round.

### Changed

- **Agent-driven curation replaces auto-enrich** — removed the keyword-matching `enrich_note_file()` from the fetch pipeline. Fetcher subagents now read content, write real summaries, add meaningful tags, and quality-check each source (deprecating junk/off-topic notes).
- **Fetcher subagent quality gate** — subagent now checks relevance, content quality, and duplicates. Deprecates bad notes instead of leaving them as drafts.
- **`_resolve_executable()` prioritizes venv** — checks venv `Scripts/` dir before PATH, preventing system-wide installs from overriding the project's venv.
- **PDF binary detection improved** — checks for `endstream`, `endobj`, `/FlateDecode`, `%PDF-` markers and non-printable character ratios. Catches binary garbage in both single-fetch and batch-fetch paths.
- **Junk detection thresholds raised** — empty content threshold: 100→300 chars, cookie page threshold: 500→1500 chars. Added `recaptcha`, `checking your browser`, `verify you are human` to bot detection signals.
- **SSL verification disabled for PDF downloads** — academic sites often have self-signed certs. `httpx.get(verify=False)` for PDF fetches only.
- **PDF fetch logging** — `_fetch_pdf` failures now logged via `logging.getLogger("hyperresearch.pdf")` instead of silently returning None.
- **Fetcher subagent continues on failure** — no longer stops on first fetch error, tries all URLs and reports failures individually.

### Added dependencies

- `pymupdf>=1.24` — PDF text extraction
- `httpx>=0.27` — direct HTTP downloads for PDFs (bypasses browser)

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

[0.3.0]: https://github.com/jordan-gibbs/hyperresearch/releases/tag/v0.3.0
[0.2.0]: https://github.com/jordan-gibbs/hyperresearch/releases/tag/v0.2.0
[0.1.0]: https://github.com/jordan-gibbs/hyperresearch/releases/tag/v0.1.0
