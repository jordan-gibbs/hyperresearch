# Changelog

## [0.8.1] - 2026-04-29

### Surface cleanup

- **`/research` alias retired.** Only `/hyperresearch` remains. The `research` skill dir is now in `_RETIRED_SKILL_DIRS` and is pruned automatically on the next `hyperresearch install`.
- **`standard` tier removed.** Only `light` and `full` remain. Step 1's classifier folds the previous standard-tier signals (surveys, multi-entity comparisons, landscape overviews) into `light`. Mid-tier fan-out (3 critics, 60–100 URLs, 40–60 claims) is gone — the simplification is intentional.
- **Time estimates re-calibrated.** Light: ~30–40 minutes (was 3–8 min). Full: ~1.5–2.5 hours (was 25–60 min). Numbers reflect realistic wall-clock times observed across recent runs, not theoretical floors.
- **README tier table** drops the cost column.

## [0.8.0] - 2026-04-29

### Architecture — V8.3 deployment release

The flagship pipeline ships as a tier-adaptive 16-step chain. The `/research-layercake` slash command is retired; the entry skill is now invokable as both `/hyperresearch` and `/research`. Internal codename "layercake" is gone — everywhere — replaced by the product name. The simple V1 single-pass research skill and its four modality variants are removed; the V8 `light` tier replaces them as the fast path for bounded queries.

### Changed
- **Entry skill aliasing.** `hyperresearch install` now writes the entry skill to both `.claude/skills/hyperresearch/SKILL.md` and `.claude/skills/research/SKILL.md` so Claude Code registers `/hyperresearch` and `/research` as independent triggers for the same V8 pipeline.
- **Step skills renamed.** All 16 step skills moved from `layercake-N-name` to `hyperresearch-N-name`. The Skill-tool invocations in every step file route to the new names. Pre-existing `layercake-*` skill directories are pruned automatically on the next `hyperresearch install`.
- **V1 skills removed.** `research.md`, `research-collect.md`, `research-compare.md`, `research-forecast.md`, `research-synthesize.md` deleted from the source tree. The V8 `light` tier (steps 1 → 2 → 10 → 15 → 16) is the fast path for short bounded queries.
- **Light tier coherence.** Step 10's light path now has explicit guidance for vault-driven evidence sourcing, structural-heading compliance, citation rendering, and hygiene rules. Step 15's integrity gate is tier-conditional — it no longer demands critic-findings or patch-log artifacts when those steps were tier-skipped.
- **Lint workflow rule** renamed from "Layercake artifacts missing" to "Hyperresearch artifacts missing" (cosmetic).

### Pruned on upgrade
- Skill dir `research-layercake` deleted (superseded by `/hyperresearch` alias).
- V1 modality files (`SKILL-collect.md`, `SKILL-synthesize.md`, `SKILL-compare.md`, `SKILL-forecast.md`) removed from the install dir.
- Legacy `layercake-*` step-skill directories cleaned up.

## [0.7.0] - 2026-04-17

### Architecture — `/research-ensemble` retired, `/hyperresearch` introduced

This release replaces the three-parallel-drafts-plus-merger ensemble design with a seven-phase layered pipeline. Width is discovered first, depth loci are derived from the width corpus (not pre-assigned framings), one draft is written from the combined evidence, three adversarial critics run in parallel against it, and the draft is then modified ONLY by surgical Edit hunks — never regenerated.

### New

- **7-phase hyperresearch pipeline** — (1) width sweep via parallel fetchers, (2) two parallel loci-analysts identify 1–8 depth loci from the corpus, (3) one depth-investigator per locus writes an `interim-<locus>.md` note, (4) orchestrator writes ONE draft, (5) dialectic / depth / width critics return structured findings JSONs, (6) the patcher applies findings as Edit hunks, (7) the polish auditor cuts filler and strips hygiene leaks via more Edit hunks. Protocol lives at `.claude/skills/hyperresearch/SKILL.md`.
- **Tool-locked patcher + polish auditor** — both agents register with tools `[Read, Edit]` ONLY. They physically cannot Write. Every hunk is capped at 500 chars of net expansion — any critic that proposes a larger patch escalates to the orchestrator instead of triggering a rewrite. This is the load-bearing invariant that enforces PATCH-NOT-REGEN at the tool level, not the prompt level.
- **`NoteType.INTERIM`** — new first-class note type for depth-investigator outputs. Persisted in the vault with `type: interim` and tagged `locus-<name>` for indexability. Added to the SQLite CHECK constraint via migration v7.
- **`locus-coverage` lint rule** — reads `research/loci.json` (Layer 2 output) and verifies every identified locus has a corresponding interim-report note. Missing interims flag as errors.
- **`patch-surgery` lint rule** — reads `research/patch-log.json` (Layer 6 output) and surfaces any critical finding the patcher skipped. The 500-char "patch too large" regeneration guard is also surfaced at warning severity.
- **`instruction-coverage` lint rule** — reads `research/prompt-decomposition.json` and verifies every atomic item (entity, required format) appears in the final report. Catches drafts that drifted from the user's explicit ask.
- **Layer 0.5 — prompt decomposition** — new orchestrator step before Layer 1 produces `research/prompt-decomposition.json`, a structured breakdown of the atomic items the user's prompt named (sub-questions, entities, required formats, required sections, time horizons, scope conditions). This becomes a first-class contract that flows through Layer 4 drafting and Layer 5 instruction-critique.
- **`hyperresearch-instruction-critic`** — fourth adversarial critic (Opus, `[Bash, Read]` only). Reads the Layer 4 draft against the prompt-decomposition and emits findings for missing / under-covered / mis-ordered / mis-formatted atomic items. Spawned in parallel with dialectic / depth / width critics in Layer 5.
- **Pipeline-awareness contract** — every subagent now receives the verbatim research_query AND an explicit pipeline-position statement in its Task prompt. The skill file documents the three-piece spawn contract (research_query / pipeline position / inputs) and provides a copy-paste template so the orchestrator applies it consistently to every Task call.
- **Schema v7 migration** — safely rebuilds the `notes` table with `'interim'` added to the type CHECK constraint on existing vaults.

### Removed

- **`/research-ensemble` skill** — the three-parallel-sub-run ensemble protocol is gone. The slash command no longer registers.
- **Retired subagents** — `hyperresearch-analyst`, `hyperresearch-auditor`, `hyperresearch-rewriter`, `hyperresearch-subrun`, `hyperresearch-merger` are no longer installed. On reinstall, any vault that had them gets them pruned automatically by `_prune_retired_agents()`.
- **`analyst-coverage` lint rule** — superseded by `locus-coverage` (extracts were the ensemble era's per-source deep-read artifact; interim notes are the hyperresearch equivalent scoped per locus).

### New subagent roster (9 agents)

| Agent | Model | Tools | Role |
|---|---|---|---|
| `hyperresearch-fetcher` | Haiku | Bash, Read | URL → vault note (unchanged) |
| `hyperresearch-loci-analyst` | Sonnet | Bash, Read, Write | Returns 1–8 depth loci from width corpus |
| `hyperresearch-depth-investigator` | Sonnet | Bash, Read, Write, Task | Investigates one locus, writes one interim note |
| `hyperresearch-dialectic-critic` | Opus | Bash, Read | Finds counter-evidence gaps |
| `hyperresearch-depth-critic` | Opus | Bash, Read | Finds shallow spots |
| `hyperresearch-width-critic` | Opus | Bash, Read | Finds topical coverage gaps |
| `hyperresearch-instruction-critic` | Opus | Bash, Read | Finds atomic items the draft missed from prompt-decomposition |
| `hyperresearch-patcher` | Sonnet | **Read, Edit** | Applies critic findings as Edit hunks |
| `hyperresearch-polish-auditor` | Sonnet | **Read, Edit** | Cuts filler + strips hygiene leaks |

### Breaking changes

- Scripts calling `hyperresearch install` on a pre-v0.7 vault will get the old agent files pruned. Pre-existing `research/audit_findings.json` and extract notes stay in the vault (no user data is deleted) but the protocol no longer references them.
- `analyst-coverage` in `hyperresearch lint --rule ...` is gone — use `locus-coverage` and `patch-surgery`.
- The `benchmark-report` lint rule is renamed to `wrapper-report`. The rule's logic is unchanged — it fires whenever `research/prompt.txt` or `research/wrapper_contract.json` is present and enforces the wrapper's contract on the final report. The rename reflects what the rule actually does (wrapper-contract enforcement) rather than the specific harness context where it was first used.

## [0.4.0] - 2026-04-13

### New

- **Request-type classification (Step 0)** — The research workflow now starts by classifying the user's request into one of 7 types (Canonical Knowledge Retrieval, Market / Landscape Mapping, Engineering / Technical How-To, Interpretive / Humanities Analysis, Comparative Evaluation, Emerging / Cutting-Edge Research, Forecast / Strategy / Recommendation) plus a General fallback. Classification happens before any searching and governs the rest of the workflow.
- **Type-specific parameter blocks** — Each of the 7 types specifies its own source strategy (count + primary/secondary mix), target length, opening-section shape, H2 heading count, analytical mode, and special rules. A humanities analysis wants 6–10 long thematic sections; a market landscape wants 8–14 vendor-cluster sections with a mandatory comparison matrix; a cutting-edge research request wants primary-heavy preprint reading with a "What we don't know yet" section. One workflow, seven parameterizations.
- **Primary-heavy vs. secondary-heavy source policy** — New explicit axis: Types 1/4/5/6 are primary-heavy (cite originals, engage deeply, prune irrelevant secondary coverage), Types 2/7 are secondary-heavy (triangulate across many descriptions), Type 3 is balanced. Source count is now a function of request type, not topic complexity.
- **Conceptual scaffold step (before writing)** — Agent must answer four questions in a scratch file before drafting: the hard question, the naive answer, the structural tension, and a dependency-ordered heading sketch. The final report's opening section must be a framework section, not a definition.
- **Cross-source comparison step** — Before writing the body, agent finds 3–5 places where sources actually disagree and captures short comparison blocks. Sources earn citations by being compared, not listed. These become the backbone of body sections.
- **Writing-draft hard constraints** — Target 400–600 words per H2, 12–20 H2s on a 10K-word report, never one-section-per-source, every section ends with an analytical beat, comparison tables not fact tables. Type-specific blocks override these (Type 4 Humanities targets 800–1500 words per section across 6–10 sections).
- **Frontmatter-first note triage (Step 4.5)** — Six-level protocol for reading notes efficiently. Always start with `note list -j` for summaries, use `note show --meta -j` for frontmatter-only reads, `search --include-body --max-tokens 6000 -j` for token-capped multi-note pulls, and **delegate notes with `word_count > 6000` to a fresh Sonnet subagent** with a pointed extraction prompt (~40× context savings per large note). Rely on the summary field first; read the body only when it earns its place.
- **Type-aware adversarial audit** — The structure-auditor subagent now checks whether the draft honors its declared type's parameter block: thematic sections for Humanities, mandatory comparison matrix for Comparative, "What we don't know yet" for Emerging, a position on winners for Market. Flags every type violation.

### Changed

- **`fit_markdown` via PruningContentFilter** — crawl4ai provider now uses `DefaultMarkdownGenerator` with `PruningContentFilter` so fetched notes contain just the main content, stripping navigation, footers, and sidebar chrome. Both `AsyncWebCrawler.arun()` and the Playwright visible-browser path use the same generator for consistent output. Applied to single fetch, batch fetch, and visible browser paths.
- **Skip numeric wiki-links in note parser** — `[[100]]`-style citation markers in bibliographies and academic papers are no longer extracted as note references. Avoids thousands of spurious broken-link warnings on papers that use numbered references.
- **"Over-collect, then prune" reframed as "over-collect, then engage deeply"** — A report built from 30 sources that disagree and force you to take positions is worth more than a report built from 80 sources that each contribute one bullet of description. Collection is a means to an argument, not the goal.
- **Scaffold and comparison artifacts are ephemeral, NOT hyperresearch notes** — Both the conceptual scaffold and the cross-source comparison blocks live in `/tmp/scaffold.md` or working memory, explicitly not as notes. Protects the research base from pre-writing scratch work.

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

[0.4.0]: https://github.com/jordan-gibbs/hyperresearch/releases/tag/v0.4.0
[0.3.0]: https://github.com/jordan-gibbs/hyperresearch/releases/tag/v0.3.0
[0.2.0]: https://github.com/jordan-gibbs/hyperresearch/releases/tag/v0.2.0
[0.1.0]: https://github.com/jordan-gibbs/hyperresearch/releases/tag/v0.1.0
