# Hyperresearch: Agent-Driven Research Knowledge Base

## Context

Kasten is a write-side knowledge base tool — agents/humans manually create notes. The gap in the ecosystem is a tool that lets an agent **actively collect, browse, and synthesize research** into a persistent, searchable knowledge base. Think: "kasten backbone + web browsing + slash-command UX like Graphify."

The user wants a new repo, new CLI name (`hyperresearch`), same core engine (markdown + YAML frontmatter + SQLite FTS5 + wiki-links + JSON output), but repositioned for **research workflows** where agents crawl sources, extract findings, and build a knowledge graph over time.

## What stays from kasten (the backbone)

These modules port over nearly verbatim:

| Module | What it does | Changes needed |
|--------|-------------|----------------|
| `core/vault.py` | Vault init, discovery, path properties | Rename dirs (`research/` instead of `knowledge/`?), rebrand |
| `core/sync.py` | mtime + SHA-256 sync, link resolution | None — same engine |
| `core/db.py` | SQLite schema, FTS5, WAL mode | Add `sources` table for URL tracking |
| `core/note.py` | read/write markdown with frontmatter | Add source-aware fields |
| `core/frontmatter.py` | YAML parse/serialize | None |
| `core/config.py` | TOML config | New defaults, new sections for web providers |
| `core/patterns.py` | Regex (wiki-links, code blocks) | None |
| `core/agent_docs.py` | Inject into CLAUDE.md etc | Rewrite blurb for research workflow |
| `models/` | Note, Envelope, SearchResult | Extend with Source model |
| `search/` | FTS5 + filters | Add source/URL filters |
| `serve/` | Web viewer | Rebrand theme |
| `mcp/` | MCP server | Add research-specific tools |

## What's new

### 1. Web provider plugin system

**Architecture:** Abstract `WebProvider` protocol, concrete implementations as optional deps.

```python
# src/hyperresearch/web/base.py
class WebProvider(Protocol):
    def fetch(self, url: str) -> WebResult: ...
    def search(self, query: str, max_results: int = 5) -> list[WebResult]: ...

@dataclass
class WebResult:
    url: str
    title: str
    content: str        # clean markdown
    raw_html: str | None
    fetched_at: datetime
    metadata: dict       # author, date, domain, etc.
```

**Provider implementations (each an optional dep group):**

| Provider | Install | Cost | Best for |
|----------|---------|------|----------|
| `crawl4ai` | `pip install hyperresearch[crawl4ai]` | Free, open-source | Default. 60k stars, agentic crawling, JS rendering |
| `tavily` | `pip install hyperresearch[tavily]` | $0.008/credit, 1k free/mo | Search-first workflows (API key required) |
| `firecrawl` | `pip install hyperresearch[firecrawl]` | Free self-hosted or paid API | Best markdown output, site-wide crawling |
| `trafilatura` | `pip install hyperresearch[trafilatura]` | Free | Lightweight text extraction, no JS |
| builtin | (included) | Free | `httpx` + `beautifulsoup4` fallback, no JS rendering |

**Config in `.hyperresearch/config.toml`:**
```toml
[web]
provider = "crawl4ai"    # or "tavily", "firecrawl", "trafilatura", "builtin"
tavily_api_key = ""       # or env var TAVILY_API_KEY
firecrawl_api_key = ""    # or env var FIRECRAWL_API_KEY
```

### 2. New CLI commands (research-focused)

```bash
# Fetch a URL, extract content, save as a note
hyperresearch fetch "https://arxiv.org/abs/2401.12345" --tag transformers --tag attention

# Search the web, save top results as notes
hyperresearch websearch "state space models 2026" --max 5 --tag ssm

# Deep research: search → fetch → follow links → extract → save
hyperresearch research "mamba architecture" --depth 2 --max-pages 10

# All the kasten stuff still works
hyperresearch search "attention" -j
hyperresearch note show attention-is-all-you-need -j
hyperresearch repair -j
hyperresearch sync
```

**Command details:**

- **`fetch <url>`** — Single URL → note. Extracts clean markdown via provider, creates note with `source: <url>`, auto-tags if possible, records fetch metadata. Deduplicates by URL (warns if already fetched).

- **`websearch <query>`** — Uses provider's search API → creates one note per result. Each note links back to source URL. Returns JSON list of created note IDs.

- **`research <topic>`** — The flagship command. Agent-driven deep research:
  1. Web search for topic
  2. Fetch top N results
  3. Follow outbound links up to `--depth` levels
  4. Extract and save as notes with wiki-links between related findings
  5. Generate a synthesis note (map-of-content) linking everything found
  
  This is the command that makes it "fancy" — it's what agents invoke to build a knowledge base from scratch on a topic.

### 3. Slash-command / hook integration (like Graphify)

**This is the key adoption play.** Install hyperresearch, run one command, and every agent in the repo knows about it.

```bash
pip install hyperresearch
hyperresearch install          # sets up hooks + agent docs
```

**`hyperresearch install` does:**

1. Creates `.hyperresearch/` directory (vault init)
2. Injects research-focused blurb into agent config files
3. **Installs PreToolUse hooks** for supported platforms:

| Platform | Hook location | Trigger | What it does |
|----------|--------------|---------|--------------|
| Claude Code | `.claude/settings.json` | Before `Glob`, `Grep`, `WebSearch`, `WebFetch` | "Check hyperresearch KB first. Run `hyperresearch search <topic> -j` before raw web searches." |
| Codex | `.codex/hooks.json` | Before `Bash` | Same reminder |
| Cursor | `.cursor/rules/hyperresearch.mdc` | `alwaysApply: true` | System rule with research workflow |
| Gemini CLI | `.gemini/settings.json` | `BeforeTool` | Same pattern |

The hook script (a small JS or Python file at `.hyperresearch/hook.js`):
- Checks if a research KB exists
- If yes, reminds the agent to `hyperresearch search` before going to the web
- Prevents redundant web fetches for topics already researched

### 4. Source tracking (new DB table)

```sql
CREATE TABLE sources (
    url TEXT PRIMARY KEY,
    note_id TEXT REFERENCES notes(id) ON DELETE SET NULL,
    domain TEXT,
    fetched_at TEXT,
    provider TEXT,           -- which web provider fetched it
    content_hash TEXT,       -- detect if page changed
    status TEXT DEFAULT 'active',  -- active, dead, redirected
    CHECK (status IN ('active', 'dead', 'redirected'))
);
CREATE INDEX idx_sources_domain ON sources(domain);
CREATE INDEX idx_sources_note ON sources(note_id);
```

This lets agents ask: "have we already fetched this URL?" and "what sources did we use for this topic?"

### 5. Extended frontmatter for research notes

```yaml
---
title: "Mamba: Linear-Time Sequence Modeling"
id: mamba-linear-time-sequence-modeling
tags: [ssm, mamba, sequence-modeling]
status: review
source: https://arxiv.org/abs/2312.00752
source_domain: arxiv.org
fetched_at: 2026-04-09T12:00:00Z
fetch_provider: crawl4ai
confidence: 0.85
summary: "Mamba introduces selective state spaces that achieve transformer-quality with linear scaling."
---
```

The `source`, `source_domain`, `fetched_at`, `fetch_provider` fields are new. The rest already exists in kasten's NoteMeta.

## Project structure

```
hyperresearch/
├── pyproject.toml
├── src/hyperresearch/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli/                    # [from kasten] + new commands
│   │   ├── __init__.py         # App assembly
│   │   ├── main.py             # init, status, sync, install
│   │   ├── search.py           # [from kasten]
│   │   ├── note.py             # [from kasten]
│   │   ├── repair.py           # [from kasten]
│   │   ├── fetch.py            # NEW: fetch, websearch commands
│   │   ├── research.py         # NEW: deep research command
│   │   ├── sources.py          # NEW: source management
│   │   ├── graph.py            # [from kasten]
│   │   ├── lint.py             # [from kasten]
│   │   ├── tag.py              # [from kasten]
│   │   └── ...
│   ├── core/                   # [from kasten, nearly verbatim]
│   │   ├── vault.py
│   │   ├── sync.py
│   │   ├── db.py               # + sources table
│   │   ├── note.py
│   │   ├── config.py           # + web provider config
│   │   ├── agent_docs.py       # rewritten blurb
│   │   ├── hooks.py            # NEW: PreToolUse hook installer
│   │   └── ...
│   ├── web/                    # NEW: web provider system
│   │   ├── __init__.py
│   │   ├── base.py             # WebProvider protocol + WebResult
│   │   ├── builtin.py          # httpx + bs4 fallback
│   │   ├── crawl4ai_provider.py
│   │   ├── tavily_provider.py
│   │   ├── firecrawl_provider.py
│   │   └── trafilatura_provider.py
│   ├── models/                 # [from kasten] + Source model
│   ├── search/                 # [from kasten]
│   ├── serve/                  # [from kasten, rebranded]
│   ├── mcp/                    # [from kasten] + research tools
│   └── indexgen/               # [from kasten]
├── tests/
├── README.md
├── CLAUDE.md
└── .github/workflows/
```

## Implementation phases

### Phase 1: Fork and rebrand — NOW
**Target:** `C:\Users\Jordan\PycharmProjects\hyperresearch` (PyCharm project already created)

1. Copy kasten's `src/kasten/` → `src/hyperresearch/` (all modules)
2. Copy `tests/`, `pyproject.toml`, `LICENSE`, `CONTRIBUTING.md`
3. Global rename in all files: `kasten` → `hyperresearch`, `kas` → `hpr` (alias)
4. Rename `knowledge/` → `research/` in vault defaults
5. Rename `.kasten/` → `.hyperresearch/` in vault discovery
6. Update pyproject.toml: name, entry points, description, add httpx + bs4 to core deps
7. Verify all tests pass with new names
8. `pip install -e ".[dev]"` works
9. `git init` + initial commit

### Phase 2: Web provider system (day 2-3)
1. Define `WebProvider` protocol in `web/base.py`
2. Implement `builtin` provider (httpx + bs4, always available)
3. Implement `crawl4ai` provider (optional dep)
4. Add `[web]` section to config.toml
5. Add `sources` table to DB schema
6. Wire up provider selection in config

### Phase 3: fetch + websearch commands (day 3-4)
1. `hyperresearch fetch <url>` — single URL to note
2. `hyperresearch websearch <query>` — search and save results
3. URL deduplication via sources table
4. Source metadata in frontmatter
5. Tests for both commands

### Phase 4: Hook system + install command (day 4-5)
1. `hyperresearch install` command
2. Claude Code PreToolUse hook (`.claude/settings.json`)
3. Cursor rule (`.cursor/rules/hyperresearch.mdc`)
4. Codex hook (`.codex/hooks.json`)
5. Gemini hook (`.gemini/settings.json`)
6. Rewrite agent docs blurb for research workflow
7. Hook reminder script (JS or Python)

### Phase 5: research command (day 5-7)
1. Orchestrates websearch → fetch → follow links → save
2. Depth-limited crawling
3. Auto wiki-linking between fetched notes
4. Synthesis note generation (map-of-content)
5. This is the flagship "demo" command

### Phase 6: Additional providers + polish (day 7-8)
1. Tavily provider
2. Firecrawl provider
3. Trafilatura provider
4. MCP server with research-specific tools (fetch, websearch, sources)
5. README, demo GIF, PyPI publish

## pyproject.toml sketch

```toml
[project]
name = "hyperresearch"
version = "0.1.0"
description = "Agent-driven research knowledge base. Browse, collect, and synthesize web sources into a searchable wiki."
requires-python = ">=3.11"
dependencies = [
    "typer>=0.9.0",
    "rich>=13.0",
    "pyyaml>=6.0",
    "pydantic>=2.0",
    "jinja2>=3.1",
    "platformdirs>=4.0",
]

# httpx + bs4 NOT core — agents already have WebSearch/WebFetch

[project.optional-dependencies]
crawl4ai = ["Crawl4AI>=0.4"]
tavily = ["tavily-python>=0.5"]
firecrawl = ["firecrawl>=1.0"]
trafilatura = ["trafilatura>=2.0"]
mcp = ["mcp>=1.6"]
all = ["hyperresearch[crawl4ai,tavily,firecrawl,trafilatura,mcp]"]
dev = ["pytest", "pytest-cov", "ruff", "mypy"]

[project.scripts]
hyperresearch = "hyperresearch.cli:app"
hpr = "hyperresearch.cli:app"
```

## Key design decisions

1. **httpx + bs4 are core deps, not optional** — the builtin provider should always work without extras. This is the "it just works" baseline.

2. **crawl4ai is the recommended default** — free, open-source, 60k stars, handles JS rendering. But it's optional because it pulls in heavy deps (playwright/chromium).

3. **`install` not `init`** — Graphify uses `install` for the hook setup. We use `install` to do vault init + hook installation in one step. `init` still works as an alias for just the vault.

4. **Hooks remind, not enforce** — the PreToolUse hook says "check hyperresearch first" but doesn't block the agent. Blocking would be annoying.

5. **Notes are still files** — same as kasten philosophy. The web provider fetches content, but it gets saved as a .md file with frontmatter. Files are truth, DB is cache.

6. **No LLM calls in the tool itself** — hyperresearch doesn't call Claude/GPT to summarize or synthesize. The AGENT using hyperresearch does that. hyperresearch is still a "dumb tool" — it stores, indexes, and searches. The agent decides what to do with it.

7. **Agents already have web access** — Claude Code has WebSearch/WebFetch, Codex has browsing, etc. So the DEFAULT flow is: agent fetches content with its own tools → pipes it into hyperresearch via `--body-file` or `--body-stdin`. The optional web providers (crawl4ai, tavily, firecrawl) are extras for standalone/headless use, NOT required.

## Verification

1. `pip install -e ".[dev]"` — core install works
2. `hyperresearch install` — creates vault + hooks
3. `hyperresearch fetch "https://en.wikipedia.org/wiki/Zettelkasten"` — fetches and saves note
4. `hyperresearch search "zettelkasten" -j` — finds the fetched note
5. `hyperresearch websearch "state space models" --max 3` — searches and saves 3 notes
6. `python -m pytest tests/` — all tests pass
7. Open a Claude Code session in the repo — agent sees the hook reminder, uses `hyperresearch search` before web searches

## Name availability check needed
- PyPI: check if `hyperresearch` is taken
- GitHub: check if `hyperresearch` repo name is available
