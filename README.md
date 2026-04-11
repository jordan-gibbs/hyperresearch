<p align="center">
  <img src="assets/banner.png" alt="HYPERRESEARCH" width="700">
</p>

<h3 align="center">Deep, persistent web research for AI agents</h3>

<p align="center">
  <a href="https://pypi.org/project/hyperresearch/"><img src="https://img.shields.io/pypi/v/hyperresearch" alt="PyPI version"></a>
  <a href="https://pypi.org/project/hyperresearch/"><img src="https://img.shields.io/pypi/pyversions/hyperresearch" alt="Python 3.11+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/jordan-gibbs/hyperresearch" alt="License: MIT"></a>
  <a href="https://github.com/jordan-gibbs/hyperresearch"><img src="https://img.shields.io/github/stars/jordan-gibbs/hyperresearch?style=social" alt="GitHub stars"></a>
</p>

---

Your AI agent searches the web, finds great sources, synthesizes an answer — then the session ends and everything is gone. Next time, it starts from zero.

**Hyperresearch makes research persist.** Every source your agent finds is fetched with a real headless browser, saved as searchable markdown, and indexed into a knowledge base that compounds across sessions.

```bash
pip install hyperresearch[crawl4ai]
hyperresearch install
```

## What people use it for

- **In-depth topic research** — "Research the latest advances in state space models" → agent fetches 20+ papers, docs, and blog posts, follows citations to primary sources, builds a linked knowledge graph
- **News tracking over time** — run research sessions weekly on a topic, each session builds on what's already collected, nothing gets re-fetched
- **State-of-the-art surveys** — "What's the current SOTA for speech recognition?" → agent goes down rabbit holes, collects benchmarks, papers, and implementations
- **Competitive analysis** — scrape company pages, LinkedIn profiles, product docs, news articles into a persistent, searchable corpus
- **Due diligence** — aggregate everything about a person, company, or technology from across the web with authenticated crawling (LinkedIn, Twitter, paywalled sites)

## How it works

1. **You ask your agent to research something**
2. **Agent searches the web** — multiple queries, different angles
3. **Fetches every source** with a real headless browser (crawl4ai) — JS rendering, bot detection bypass, login-gated content
4. **Saves each page** as a searchable markdown note with tags, summary, and source tracking
5. **Follows links** to primary sources — the paper, not the blog post about the paper
6. **Auto-links related notes** with `[[wiki-links]]` across the knowledge graph
7. **Synthesizes findings** into a summary note linking all sources
8. **Next session** — agent checks the KB before searching the web. Knowledge compounds.

```
your-repo/
  .hyperresearch/        # Config + SQLite FTS5 index (rebuildable)
  research/
    notes/               # Markdown notes — the source of truth
    index/               # Auto-generated wiki pages
  CLAUDE.md              # Agent docs (auto-injected)
```

## Works with every major agent

`hyperresearch install` hooks into your agent in one step:

| Platform | Hook | Trigger |
|----------|------|---------|
| **Claude Code** | `.claude/settings.json` + `/research` skill | Before WebSearch, WebFetch |
| **Codex** | `.codex/hooks.json` | Before Bash |
| **Cursor** | `.cursor/rules/hyperresearch.mdc` | Always-apply rule |
| **Gemini CLI** | `.gemini/settings.json` | Before tool calls |

```bash
hyperresearch install --platform all    # Hook every platform at once
```

## Key features

- **Real headless browser** — crawl4ai runs local Chromium. Handles JavaScript, bypasses bot detection, renders SPAs. Not a simple HTTP fetch.
- **Authenticated crawling** — log into LinkedIn, Twitter, paywalled news. Your sessions persist across fetches.
- **Auto-curation** — every fetched note gets auto-tagged, auto-summarized, and auto-linked to related notes
- **Smart SPA wait** — polls DOM stability instead of fixed delays. Fast pages finish instantly, SPAs get up to 10 seconds.
- **Cheap parallel fetching** — ships a Haiku-powered subagent that fetches URLs in parallel for pennies
- **`/research` skill** — scripted deep research workflow. Clarifies ambiguous requests, searches broadly, fetches aggressively, follows rabbit holes, curates, synthesizes.
- **Login wall detection** — detects auth redirects and tells you to set up a profile instead of saving junk
- **FTS5 search** — instant full-text search across thousands of notes with BM25 ranking
- **Knowledge graph** — `[[wiki-links]]`, backlinks, hub detection, auto-linking
- **MCP server** — 13 tools (read + write) for Claude Desktop, Cursor, or any MCP client
- **Note lifecycle** — draft → review → evergreen → stale → deprecated → archive

## Commands

```bash
# Research
hyperresearch fetch <url> --tag t -j           # Fetch a URL into the KB
hyperresearch fetch-batch <urls...> -j         # Fetch many URLs at once
hyperresearch research "topic" --max 5 -j      # Full pipeline: search → fetch → link → synthesize

# Search
hyperresearch search "query" -j                # Full-text search
hyperresearch search "query" --max-tokens 8000 # Stay within context budget
hyperresearch note show <id> -j                # Read a note

# Knowledge graph
hyperresearch link --auto -j                   # Auto-link related notes
hyperresearch graph hubs -j                    # Most-connected notes
hyperresearch graph backlinks <id> -j          # What links to this note

# Manage
hyperresearch sources list -j                  # Every URL ever fetched
hyperresearch lint -j                          # Health check
hyperresearch repair -j                        # Fix links, rebuild indexes
```

Every command returns `{"ok": true, "data": {...}}` with `-j`.

## Authenticated crawling

Fetch from LinkedIn, Twitter, paywalled sites — anything you can log into:

```bash
hyperresearch setup       # Browser opens. Log into your sites. Done.
```

```toml
# .hyperresearch/config.toml
[web]
provider = "crawl4ai"
profile = "research"
```

LinkedIn, Twitter, Facebook, Instagram, and TikTok automatically use a visible browser to avoid session kills.

## Philosophy

- **No LLM calls.** Hyperresearch stores, indexes, and searches. Your agent is the LLM.
- **Markdown is truth.** Notes are plain files. SQLite is a rebuildable cache.
- **Over-collect, then prune.** Fetch aggressively. Deprecate what you don't need.
- **Check before you fetch.** Hooks kill redundant searches across sessions.
- **Raw content is king.** Save the original with formatting, not a rewritten summary.

## Requirements

- Python 3.11+
- Windows, macOS, Linux

## License

[MIT](LICENSE)

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=jordan-gibbs/hyperresearch&type=Date)](https://star-history.com/#jordan-gibbs/hyperresearch&Date)
