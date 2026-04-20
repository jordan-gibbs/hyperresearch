<p align="center">
  <img src="assets/banner.png" alt="HYPERRESEARCH" width="700">
</p>

<h3 align="center">The Most Intelligent Deep Research Agent Harness</h3>

<p align="center">
  <a href="https://pypi.org/project/hyperresearch/"><img src="https://img.shields.io/pypi/v/hyperresearch" alt="PyPI version"></a>
  <a href="https://pypi.org/project/hyperresearch/"><img src="https://img.shields.io/pypi/pyversions/hyperresearch" alt="Python 3.11+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/jordan-gibbs/hyperresearch" alt="License: MIT"></a>
  <a href="https://github.com/jordan-gibbs/hyperresearch"><img src="https://img.shields.io/github/stars/jordan-gibbs/hyperresearch?style=social" alt="GitHub stars"></a>
</p>

---

**HyperResearch is a deep research harness for Claude Code, currently leading the deep research bench internally. Produces adversarially-audited reports with full source provenance and creates a persistent, searchable knowledge base that compounds across sessions.**

<p align="center">
  <img src="assets/benchmark.png" alt="DeepResearch-Bench top-5 — hyperresearch leads the chart ahead of Grep Deep Research, Cellcog Max, nvidia-aiq, Gemini Deep Research, and OpenAI Deep Research" width="780">
</p>

<p align="center"><sub>Preliminary — fleet projection from a 16-query layercake pilot against the current DeepResearch-Bench leaderboard snapshot (muset-ai/DeepResearch-Bench-Leaderboard). Full 100-query sweep pending.</sub></p>

## Installation

```bash
pip install hyperresearch
hyperresearch install
```

In Claude Code, type `/research-layercake <anything>` and the full flagship protocol fires — **a 7-phase pipeline that discovers width first, derives depth loci from the width corpus, runs parallel depth investigations, drafts once, and patches the draft via adversarial critics (no regeneration).** This is the default way to use hyperresearch. If you want a faster single-pass run instead, type `/research <anything>`.

That single install command creates a v7 SQLite vault, auto-installs Chromium for headless browsing, generates `CLAUDE.md`, installs both skills (`/research-layercake` and `/research`), registers eight subagents (fetcher / loci-analyst / depth-investigator / dialectic-critic / depth-critic / width-critic / patcher / polish-auditor) into `.claude/agents/`, and wires PreToolUse hooks.

---

## What it actually produces

Every research session leaves three load-bearing artifacts on disk. These are real excerpts from a recent run on *"Is there a general method for solving asymmetric first-price sealed-bid auctions?"*

### Provenance breadcrumbs in every fetched note

```
asymmetric-auctions-with-more-than-two.md

*Suggested by [[games-and-economic-behavior-73-2011-479495]] — Hubbard on
asymmetric auctions with more than two bidders*
```

Every fetched source carries a wiki-link breadcrumb back to whatever source recommended it. The chain forms a rooted tree from the seed fetches. The `provenance` lint rule catches disconnected components and flat-batch fetches.

### Persisted audit findings

```json
{
  "mode": "comprehensiveness",
  "status": "needs_fixes",
  "criticals": [
    {
      "id": "C1",
      "description": "Provenance lint error: 6 source notes have breadcrumbs
       but are disconnected from the provenance graph...",
      "fixed_at": "2026-04-15T00:23:00Z",
      "notes": "Provenance ratio is 40% (above 30% threshold).
       Disconnected graph is from retroactive backlinks added to existing
       seeds, not fabricated provenance."
    }
  ],
  "important": [
    { "id": "I1", "description": "Zero non-academic voices...", "fixed_at": "..." }
  ]
}
```

Both audit modes (comprehensiveness + conformance, both Opus) persist their findings to `research/audit_findings.json`. The agent applies fixes and marks each finding `fixed_at: <timestamp>`.

### Self-certification detector blocks save

The `audit-gate` lint rule extracts the keyword from each CRITICAL's description, **re-runs the underlying lint rule**, and emits this if the rule still fails:

```
SELF-CERTIFICATION VIOLATION: CRITICAL [C1] was marked `fixed_at` in
research/audit_findings.json, but lint rule `provenance` still returns
3 error(s). The draft's `fixed_at` marker does not match the vault's
actual state — you must fix the underlying issue (not just the
bookkeeping). Run `$HPR lint --rule provenance -j` to see what's
still broken.
```

The save gate blocks until every CRITICAL is **genuinely** resolved. Bookkeeping fixes get caught.

---

## `/research-layercake` — 7 phases, one draft, patched not regenerated (the default)

The flagship research surface and the default way to use hyperresearch. Type `/research-layercake <query>` in Claude Code.

**Width before depth, then one draft patched by adversarial critics.** An Opus orchestrator walks a seven-phase pipeline: wide corpus sweep → rabbithole identification → parallel depth investigations → single draft → three adversarial readings → surgical patch pass → polish audit.

### The 7 phases

1. **Width sweep.** The orchestrator spawns parallel `hyperresearch-fetcher` Haiku agents to build a 30–80 source corpus covering the topic's corners. Academic APIs (Semantic Scholar, arXiv, OpenAlex, PubMed) run BEFORE web search — citation-ranked canonical papers before derivative commentary.
2. **Loci analysis.** Two `hyperresearch-loci-analyst` Sonnet agents read the width corpus in parallel and each returns 1–8 specific "depth loci" — questions where deeper investigation would meaningfully improve the final report. The orchestrator dedupes their outputs and clamps to 6.
3. **Depth investigation.** One `hyperresearch-depth-investigator` Sonnet agent per locus, in parallel. Each investigator can spawn its own fetchers (capped at 10 new sources), reads the existing vault, and writes ONE `interim-<locus>.md` note with dense synthesis, direct quotes, and citations. The orchestrator consumes these interim notes during Layer 4.
4. **Draft.** The orchestrator writes `research/notes/final_report.md` ONCE, weaving the width corpus with the interim notes under the modality file's substance rules (collect / synthesize / compare / forecast).
5. **Adversarial critique.** Three Opus critics fire in parallel: `dialectic-critic` (counter-evidence the draft missed), `depth-critic` (shallow spots the interim notes could fill), `width-critic` (topical corners the draft ignores despite the corpus supporting them). Each returns a findings JSON with structured `suggested_patch` entries — never a rewrite.
6. **Patch pass.** `hyperresearch-patcher` (Sonnet, **tool-locked to `[Read, Edit]`**) reads all three findings files and applies them as surgical Edit hunks. Per-hunk cap: `new_string` may be at most 500 chars longer than `old_string`. The patcher physically cannot Write — it has no path to regenerate the draft.
7. **Polish audit.** `hyperresearch-polish-auditor` (Sonnet, also `[Read, Edit]` only) strips hygiene leaks (YAML frontmatter, scaffold sections, prompt echoes), cuts filler phrases ("Importantly", "It is worth noting"), removes redundancy, and breaks long sentences — all via surgical Edits. Structural mismatches (wrong format for the prompt, missing sections) escalate to the orchestrator rather than getting force-patched.

### Why the tool lock matters

The load-bearing invariant of layercake is: **after Layer 4 the draft is only ever modified by small Edit hunks.** This is enforced at the Claude Code tool-allowlist level — the patcher and polish auditor do not have `Write` or `Bash`. If a critic's finding cannot fit into a ≤500-char hunk, it escalates to the orchestrator as a structural issue instead of triggering a regeneration. This prevents the "just rewrite it" failure mode that plagues post-hoc review in long-running agent pipelines.

### Opting out — faster single-pass mode

Layercake is the default because width-plus-depth-plus-adversarial-review beats a single investigator on almost every real research query. If you want a faster single-pass run — e.g., for a quick sanity-check or a prompt where one pass is plenty — type `/research <query>` instead. Single-pass fires the same modality rules on one Sonnet agent, no loci analysis, no critics, no patcher.

A rule of thumb: use `/research-layercake` for anything you would want a human researcher to take seriously. Use `/research` when you just want the vault populated and a first-pass draft in front of you quickly.

---

## The vault: persistent, searchable, compounding

hyperresearch is not a one-shot report generator. Every fetched source lands in a durable SQLite-indexed vault that every future research session can reuse. Knowledge compounds across sessions; the tool's value grows with the corpus.

### What persists

- **Raw source material, not rewritten summaries.** Fetched content keeps its original formatting — headings, tables, code blocks, technical details. If the source is a PDF, pymupdf extracts the full text and the original PDF lives at `research/raw/<note-id>.pdf`. Every note carries its source URL, fetch timestamp, tier classification, and `--suggested-by` breadcrumb pointing at whichever note surfaced it.
- **Extract notes** — per-source analyst reads with direct quotes, context markers, one-line summaries, and inherited tier + content-type tags. These are the second derivative of raw content and stay in the vault as first-class, queryable notes.
- **Scaffolds, comparisons, audit findings** — every research session's planning artifacts and adversarial review trail persist alongside the sources they drew on. Past synthesis notes are discoverable next to the raw sources that justified them.
- **The knowledge graph** — `[[wiki-links]]` between notes form a queryable graph. `hyperresearch graph hubs` surfaces the most-connected notes in a domain; `hyperresearch graph backlinks <id>` shows every note that references a given source.

### Searchability

Before any web search the vault gets queried first — the hook reminds Claude Code, and the protocol checks explicitly:

```bash
hyperresearch search "ion-trap gate fidelity" -j           # Full-text across every note
hyperresearch search "quantum" --tier ground_truth -j      # Filter by epistemic tier
hyperresearch search "attention" --include-body -j         # Full-body search, not just titles
hyperresearch note show <id> <id> <id> -j                  # Batch-read notes in one call
```

When the vault already holds ≥10 relevant notes on a topic, `/research` tells the user so and asks whether to dig deeper, take a new angle, or synthesize from the existing corpus — instead of re-fetching what's already there. The sunk-cost of past research pays forward.

### Markdown is truth, SQLite is cache

Notes live as plain markdown with YAML frontmatter in `research/notes/`. The SQLite index is fully rebuildable — delete it and `hyperresearch sync` reconstructs it from the markdown. The vault is inspectable in any editor, version-controllable in git, and readable without the tool installed. hyperresearch stores and indexes; it does not hide data behind the tool.

---

## Why it works on hard research

Your AI agent searches the web, skims sources, writes an answer that sounds good, and ships it. There's no scaffold, no audit, no source-vs-source comparison, no provenance, no way to know if it actually engaged with the strongest counter-position. Hyperresearch breaks that pattern through structural enforcement:

- **Verbatim user prompt is gospel** — pasted into the scaffold's first section, re-read at every step, machine-checked at the save gate
- **Bouncing reading loop** — fetch a seed, an analyst reads it and proposes next URLs, main agent fetches those WITH `--suggested-by` provenance, loop. Builds a rooted research graph instead of a flat batch.
- **Per-source analyst extraction** — every fetched source gets a Sonnet subagent that reads it with the research goal in hand
- **Adversarial dissent is mandatory** — Checkpoint 1 fails until at least one source explicitly contradicts the dominant view
- **Two-mode adversarial audit (Opus)** — comprehensiveness finds gaps vs the verbatim prompt; conformance checks modality rules
- **Save is blocked** until every CRITICAL is verified-resolved by the audit-gate detector

---

## How it works — the contextual flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                                                                     │
│   USER PROMPT  (verbatim, gospel)                                   │
│        │                                                            │
│        ▼                                                            │
│   ┌─────────────────────────────────────────────────────────────┐   │
│   │             MAIN AGENT (your Claude Code session)            │  │
│   │       classify → seed fetch → guided loop → audit → save     │  │
│   └──────┬──────────────────┬──────────────────┬─────────────────┘  │
│          │                  │                  │                    │
│   spawn  ▼            spawn ▼            spawn ▼                    │
│   ┌───────────┐      ┌───────────┐      ┌───────────┐               │
│   │  FETCHER  │      │  ANALYST  │      │  AUDITOR  │               │
│   │  (Haiku)  │      │  (Sonnet) │      │   (Opus)  │               │
│   │           │      │           │      │           │               │
│   │ crawl4ai  │      │ read note │      │ check vs  │               │
│   │ +headless │      │ extract + │      │ verbatim  │               │
│   │  Chromium │      │ next URLs │      │  prompt   │               │
│   └─────┬─────┘      └─────┬─────┘      └─────┬─────┘               │
│         │                  │                  │                     │
│         │ note +           │ extract +        │ findings.json       │
│         │ raw.pdf          │ next_targets     │                     │
│         ▼                  ▼                  ▼                     │
│   ┌─────────────────────────────────────────────────────────────┐   │
│   │              VAULT  (SQLite v6 + markdown)                  │   │
│   │   notes/*.md   raw/*.pdf   scaffold.md   comparisons.md     │   │
│   │   audit_findings.json  ←── audit-gate lint blocks save      │   │
│   └─────────────────────────────────────────────────────────────┘   │
│         ▲                                                           │
│         │ analyst's next_targets re-enter FETCHER with              │
│         │ --suggested-by, building a rooted provenance tree         │
│         └─────────── bouncing reading loop ─────────────────────────┘
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

**Subagent roster**, each picked for its job:

| Agent | Model | Role |
|---|---|---|
| `hyperresearch-fetcher` | **Haiku** | Mechanical URL fetching via crawl4ai. Cheap, fast, parallel. |
| `hyperresearch-loci-analyst` | **Sonnet** | Reads the width corpus, returns 1–8 depth loci with rationale. Spawn 2 in parallel, dedupe. |
| `hyperresearch-depth-investigator` | **Sonnet** | Investigates one locus: fetches new sources, writes one interim-report note per locus. |
| `hyperresearch-dialectic-critic` | **Opus** | Finds counter-evidence the draft missed, emits structured findings with surgical patches. |
| `hyperresearch-depth-critic` | **Opus** | Finds shallow spots where interim notes could fill specifics. |
| `hyperresearch-width-critic` | **Opus** | Finds topical corners the corpus supports but the draft ignores. |
| `hyperresearch-patcher` | **Sonnet** | Tool-locked `[Read, Edit]`. Applies critic findings as surgical Edit hunks. Cannot regenerate. |
| `hyperresearch-polish-auditor` | **Sonnet** | Tool-locked `[Read, Edit]`. Cuts filler, strips hygiene leaks, breaks long sentences. |

**Routing** — the dispatcher classifies every request by **what the output needs to do**, not what the subject is:

```
collect    →  enumerative coverage with per-entity fields
synthesize →  defended thesis grounded in evidence
compare    →  per-entity evaluation + committed recommendation
forecast   →  committed prediction with explicit time horizon
```

A query about a fictional franchise can be `collect` (per-character enumeration), `synthesize` (a thesis about meaning), `compare` (this vs another), or `forecast` (will the sequel succeed). Subject doesn't decide; activity does.

---

## What's enforced

Nine invariants the protocol structurally prevents from breaking:

1. **Verbatim prompt as gospel** — `scaffold-prompt` lint blocks if the scaffold doesn't open with the user's exact prompt
2. **Rooted-tree provenance** — `--suggested-by` chain must form a real tree from at least one seed; isolated breadcrumbs flagged
3. **Locus coverage** — every Layer 2 locus must have a Layer 3 `interim-<name>.md` note; missing interims flag as errors
4. **Patch-only draft modification** — after Layer 4, the patcher and polish auditor are tool-locked to `[Read, Edit]`. They cannot regenerate; the ≤500-char hunk-expansion cap is a mechanical tripwire
5. **Critical findings never silently skip** — `patch-surgery` lint surfaces any critical finding the patcher couldn't apply
6. **Schema integrity** — `tier`, `content_type`, and `type` are SQLite CHECK-constrained vocabularies; corrupted frontmatter cannot poison the index
7. **PDF + raw artifact persistence** — fetched PDFs land in `research/raw/` and the `raw_file` frontmatter field survives every re-serialization
8. **Interim notes are persisted, not ephemeral** — depth-investigator outputs stay in the vault forever; future sessions can query them
9. **Hygiene leaks caught on the way out** — scaffold sections, YAML frontmatter, and prompt echoes are stripped by the polish auditor before ship

---

## What hyperresearch doesn't do

- It doesn't replace your judgment on which sources matter — the agent picks, you steer
- It can't fetch what's behind a paywall you haven't logged into (but it tries: `--visible` flag bypasses many bot-detectors, and configured login profiles work transparently)
- It runs on Anthropic models — Opus + Sonnet + Haiku via the subagent triad. Costs scale with corpus size; expect $5-15 per deep research session.
- The audit gate catches **structural** failures (missing scaffold, broken provenance, unresolved CRITICALs). It cannot guarantee factual accuracy — that's still your call.
- Network fetches fail. The protocol surfaces failures explicitly and walks a fallback chain (alternative URLs → visible browser → summary fallback), but some sources won't ever be fetchable.

---

## Use cases

- **Deep technical research** — "What does the literature say about ion-trap quantum scaling?" → 25+ academic sources, full provenance graph, dissenting voices, primary papers quoted directly
- **Comparative evaluation** — "TigerBeetle vs Postgres vs FoundationDB for write-heavy workloads" → per-entity coverage, comparison matrix, committed pick, mandatory critical voice on the leader
- **Forecasting + strategy** — "Will US inflation stay above 3% through 2026?" → ground-truth statistics + institutional analysis + named contrarians, probability language not hedge
- **Interpretive analysis** — "What does *Blood Meridian*'s violence mean?" → primary text + critical tradition + dissenting reading, every paragraph fuses fact with interpretive claim
- **Enumerative coverage** — "For each Napoleonic marshal, cover key campaigns and fate" → every named entity gets every requested field, no silent downgrades

All of the above run under the default [`/research-layercake`](#research-layercake--7-phases-one-draft-patched-not-regenerated-the-default) mode: width sweep → loci analysis → depth investigations → one draft → three adversarial critics → surgical patch pass → polish audit. For faster turnaround when the query doesn't warrant the full pipeline, type `/research <query>` for a single-pass run.

---

## What `hyperresearch install` wires into Claude Code

One command sets up the full integration:

- **`.claude/settings.json`** — PreToolUse hook that nudges Claude Code to check the vault before any raw web search
- **`.claude/skills/hyperresearch/`** — `/research` skill (dispatcher + 4 modality files: collect / synthesize / compare / forecast)
- **`.claude/skills/research-layercake/`** — `/research-layercake` skill (the 7-phase pipeline)
- **`.claude/agents/`** — eight registered subagents: `hyperresearch-fetcher` (Haiku), `hyperresearch-loci-analyst` (Sonnet), `hyperresearch-depth-investigator` (Sonnet), `hyperresearch-dialectic-critic` (Opus), `hyperresearch-depth-critic` (Opus), `hyperresearch-width-critic` (Opus), `hyperresearch-patcher` (Sonnet, `[Read, Edit]`-locked), `hyperresearch-polish-auditor` (Sonnet, `[Read, Edit]`-locked)
- **`CLAUDE.md`** at the vault root — the full research workflow, automatically loaded by Claude Code on every session

hyperresearch is Claude Code-only for now. Codex, Cursor, and Gemini support was trimmed from v0.6 to focus the surface area — may return as real integrations later.

---

## Commands

```bash
# Research workflow
hyperresearch fetch <url> --tag t -j                       # Fetch a URL into the KB
hyperresearch fetch <url> --suggested-by <id> -j           # Track provenance during the guided loop
hyperresearch fetch <url> --visible -j                     # Bypass bot detection with a visible browser

# Search + read
hyperresearch search "query" -j                            # Full-text search
hyperresearch search "query" --tier ground_truth -j        # Filter by epistemic tier
hyperresearch search "query" --content-type paper -j       # Filter by artifact kind
hyperresearch note show <id> -j                            # Read a note
hyperresearch note show <id> --meta -j                     # Frontmatter only (cheap triage)
hyperresearch note list --status draft -j                  # List notes with summaries

# Knowledge graph
hyperresearch link --auto -j                               # Auto-link related notes
hyperresearch graph hubs -j                                # Most-connected notes
hyperresearch graph backlinks <id> -j                      # What links to this note

# Health checks
hyperresearch lint -j                                      # Run all rules
hyperresearch lint --rule scaffold-prompt -j               # Verbatim prompt gospel rule
hyperresearch lint --rule provenance -j                    # Rooted-tree breadcrumb chain
hyperresearch lint --rule audit-gate -j                    # Self-certification detector
hyperresearch lint --rule analyst-coverage -j              # Extract:source ratio
hyperresearch repair -j                                    # Fix links, rebuild indexes
```

Every command returns `{"ok": true, "data": {...}}` with `-j`.

---

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

---

## Philosophy

- **Process is load-bearing.** A draft without a scaffold, comparisons, audit findings, and a clean provenance graph is unfinished — regardless of how good the prose reads.
- **The user's prompt is the only authority.** Activity classification, source strategy, writing constraints all serve the prompt. Substance rules never override what the user actually asked for.
- **No LLM calls inside the tool.** Hyperresearch stores, indexes, lints, and orchestrates. Your agent is the LLM.
- **Markdown is truth, SQLite is cache.** Notes are plain files. Delete the DB; `hyperresearch sync` rebuilds it.
- **Audit findings are artifacts, not just outputs.** They persist to JSON, get verified by lint rules, and gate the save. Self-certification is structurally prevented.
- **Exhaustive and deep.** v0.5.0 seeds 10-15 sources, iterates the bouncing loop 8 rounds, and typically produces drafts anchored in 40-80 fetched-and-analyst-read sources with 40+ inline citations. Depth AND breadth — not a tradeoff.

---

## Requirements

- Python 3.11+
- [Claude Code](https://claude.com/claude-code) with Anthropic API access
- API key with access to Opus, Sonnet, and Haiku — one key powers the full subagent triad
- Windows, macOS, Linux

---

## License

[MIT](LICENSE)

---

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=jordan-gibbs/hyperresearch&type=Date)](https://star-history.com/#jordan-gibbs/hyperresearch&Date)
