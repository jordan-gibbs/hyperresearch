# Hyperresearch

Agent-driven research knowledge base. Install it, and your AI coding agent can collect, search, and synthesize web research into a persistent, searchable wiki — across sessions.

```bash
pip install hyperresearch
hyperresearch install    # init vault + hook your agent
```

That's it. Your agent now checks the research base before searching the web, saves useful findings automatically, and builds a knowledge graph over time.

## How it works

1. **Agent finds something useful** (via its own web search, browsing, or your input)
2. **Agent saves it**: `hyperresearch fetch "https://..." --tag ml -j` or `hyperresearch note new "Title" --body-file content.md -j`
3. **Next time it needs info**, the PreToolUse hook reminds it: *"check hyperresearch first"*
4. **Agent searches the KB**: `hyperresearch search "attention mechanisms" -j`
5. **Knowledge compounds** across sessions — no redundant fetches, no lost context

```
your-repo/
  .hyperresearch/        # Hidden: config, SQLite index, hook script
  research/
    notes/               # Markdown notes (source of truth)
    index/               # Auto-generated wiki pages
  CLAUDE.md              # Agent docs (auto-injected)
```

## Commands

```bash
# Setup
hyperresearch install                        # Init + hooks (Claude Code, Cursor, Codex, Gemini)
hyperresearch install --platform all         # Hook all supported platforms

# Collect
hyperresearch fetch <url> --tag t -j         # Save a URL as a note
hyperresearch research "topic" --max 5 -j    # Search → fetch → link → synthesize (needs crawl4ai)

# Search & read
hyperresearch search "query" -j              # Full-text search
hyperresearch note show <id> -j              # Read a note
hyperresearch note list --tag ml -j          # List notes by tag

# Manage
hyperresearch sources list -j                # What URLs have been fetched
hyperresearch sources check <url> -j         # Has this URL been fetched?
hyperresearch repair -j                      # Fix links, promote notes, rebuild indexes
hyperresearch status -j                      # Vault health overview
```

Every command returns `{"ok": true, "data": {...}}` with `-j`.

## Agent integration

`hyperresearch install` does three things:

1. **Creates the vault** (`.hyperresearch/` + `research/`)
2. **Injects usage docs** into CLAUDE.md (or AGENTS.md, GEMINI.md, copilot-instructions.md)
3. **Installs PreToolUse hooks** that fire before web searches:

| Platform | Hook | Trigger |
|----------|------|---------|
| Claude Code | `.claude/settings.json` | Before Glob, Grep, WebSearch, WebFetch |
| Codex | `.codex/hooks.json` | Before Bash |
| Cursor | `.cursor/rules/hyperresearch.mdc` | Always-apply rule |
| Gemini CLI | `.gemini/settings.json` | Before tool calls |

The hook doesn't block — it reminds the agent to check the research base first.

## Web providers

By default, agents use their own web tools (WebSearch, WebFetch) and pipe content into hyperresearch. For JS-rendered pages, blocked sites, or authenticated content, install crawl4ai (local headless Chromium):

```bash
pip install hyperresearch[crawl4ai]
crawl4ai-setup                        # Install browser (one-time)
```

Configure in `.hyperresearch/config.toml`:
```toml
[web]
provider = "crawl4ai"    # or "builtin" (stdlib urllib, no JS)
profile = ""             # Browser profile name for authenticated crawling (optional)
magic = false            # Anti-bot stealth mode (recommended for social media)
```

### Authenticated crawling

Access login-gated content (LinkedIn, Twitter, paywalled sites) by creating a login profile:

```bash
hyperresearch setup       # Choose option 1 — browser opens, log into your sites, done
# Or manually:
crwl profiles             # Create profile, log in, press q when done
```

```toml
# .hyperresearch/config.toml
[web]
profile = "research"      # Your profile name
```

## MCP server

For Claude Desktop, Cursor inline, or any MCP-compatible agent:

```bash
pip install hyperresearch[mcp]
```

```json
{"mcpServers": {"hyperresearch": {"command": "hyperresearch", "args": ["mcp"]}}}
```

10 tools: `search_notes`, `read_note`, `read_many`, `list_notes`, `get_backlinks`, `get_hubs`, `vault_status`, `lint_vault`, `check_source`, `list_sources`.

## Philosophy

- **The agent IS the LLM** — hyperresearch is a dumb tool that stores, indexes, and searches. It never calls an LLM.
- **Files are truth** — markdown notes survive the tool dying. SQLite is a rebuildable cache.
- **Agents already have web access** — hyperresearch is where they *store* what they find, not how they find it.
- **Check before you fetch** — the hook system prevents redundant web searches across sessions.

## Requirements

- Python 3.11+
- Works on Windows, macOS, Linux

## License

[MIT](LICENSE)
