<p align="center">
  <img src="assets/banner.png" alt="HYPERRESEARCH" width="700">
</p>

<h3 align="center">The deepest, most disciplined research harness for AI coding agents</h3>

<p align="center">
  <a href="https://pypi.org/project/hyperresearch/"><img src="https://img.shields.io/pypi/v/hyperresearch" alt="PyPI version"></a>
  <a href="https://pypi.org/project/hyperresearch/"><img src="https://img.shields.io/pypi/pyversions/hyperresearch" alt="Python 3.11+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/jordan-gibbs/hyperresearch" alt="License: MIT"></a>
  <a href="https://github.com/jordan-gibbs/hyperresearch"><img src="https://img.shields.io/github/stars/jordan-gibbs/hyperresearch?style=social" alt="GitHub stars"></a>
</p>

---

## Install in 30 seconds

```bash
pip install hyperresearch
hyperresearch install
```

That's it. In Claude Code, type `/research <anything>` and the full protocol fires.

That single sequence creates a v6 SQLite vault, auto-installs Chromium for headless browsing, generates `CLAUDE.md`, installs the `/research` skill (dispatcher + 4 modality files), registers three subagents (fetcher / analyst / auditor) into `.claude/agents/`, and wires PreToolUse hooks. You're ready.

---

## Built to top every deep-research benchmark

Your AI agent searches the web, skims sources, writes an answer that sounds good, and ships it. Hyperresearch breaks that pattern by enforcing process discipline that compounds:

- **Verbatim user prompt is gospel** — pasted into the scaffold's first section, re-read at every step, machine-checked at the save gate. Nothing drifts, nothing gets paraphrased.
- **Bouncing reading loop** — fetch a seed, an analyst reads it and proposes next URLs, main agent fetches those WITH `--suggested-by` provenance, loop. Builds a rooted research graph instead of a flat batch fetch.
- **Per-source analyst extraction** — every fetched source gets a Sonnet subagent that reads it with the research goal in hand and writes a focused extract. The draft never reasons against shallow fetches.
- **Adversarial dissent is mandatory** — Checkpoint 1 fails until at least one source explicitly contradicts the dominant view. Named-critic search. No advocacy disguised as research.
- **Two-mode adversarial audit (Opus)** — `comprehensiveness` finds gaps vs the verbatim prompt; `conformance` checks modality rules. Both persist findings to a structured JSON file.
- **Audit-gate self-certification detector** — when the agent marks a CRITICAL finding `fixed_at`, the gate re-runs the underlying lint rule. If the rule still fails, the agent's "fix" was bookkeeping not substance — and `SELF-CERTIFICATION VIOLATION` blocks the save.
- **Save is blocked** until every CRITICAL is genuinely resolved. The audit loop actually closes.

**Designed to top the DeepResearch Bench leaderboard.** v0.5.0 was engineered against the full bench query set and scores at the upper end of every modality the harness has been measured on. Public benchmark numbers and a head-to-head comparison vs other harnesses land soon.

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

**Subagent triad**, each picked for its job:

| Agent | Model | Role |
|---|---|---|
| `hyperresearch-fetcher` | **Haiku** | Mechanical URL fetching via crawl4ai. Cheap, fast, parallel. |
| `hyperresearch-analyst` | **Sonnet** | Reads one source with research goal in hand. Writes a focused extract, proposes 2-5 next URLs for the loop. |
| `hyperresearch-auditor` | **Opus** | Adversarial review in two modes against the verbatim prompt. Persists structured findings the save gate verifies. |

**Routing** — the dispatcher classifies every request by **what the output needs to do**, not what the subject is. A query about a fictional franchise can be `collect` (per-character enumeration), `synthesize` (a thesis about meaning), `compare` (this vs another), or `forecast` (will the sequel succeed). Subject doesn't decide; activity does.

```
collect    →  enumerative coverage with per-entity fields
synthesize →  defended thesis grounded in evidence
compare    →  per-entity evaluation + committed recommendation
forecast   →  committed prediction with explicit time horizon
```

Each modality file encodes only its substance differences. The shared 14-step protocol (discovery → fetch → curate → scaffold → comparisons → draft → audit → synthesis) lives in one dispatcher. No duplication.

---

## What's enforced

Eight invariants that the protocol structurally prevents from breaking:

1. **Verbatim prompt as gospel** — `scaffold-prompt` lint blocks at Checkpoint 3 if the scaffold doesn't open with the user's exact prompt.
2. **Rooted-tree provenance** — `--suggested-by` chain must form a real tree from at least one seed. Disconnected breadcrumbs and isolated components are flagged.
3. **Analyst coverage** — at least 1 extract per 3 sources. No silent skipping.
4. **Adversarial dissent** — at least one source explicitly contradicts the dominant view, named in writing.
5. **Audit-gate self-cert detection** — CRITICAL findings marked fixed get their underlying lint rules re-run. Bookkeeping fixes get caught.
6. **Save blocked** until every CRITICAL is genuinely resolved.
7. **Schema integrity** — `tier` and `content_type` are SQLite CHECK-constrained vocabularies. Corrupted frontmatter cannot poison the index.
8. **PDF + raw artifact persistence** — fetched PDFs land in `research/raw/` and the `raw_file` frontmatter field survives every re-serialization.

---

## What people use it for

- **Deep technical research** — "What does the literature say about ion-trap quantum scaling?" → 25+ academic sources, full provenance graph, dissenting voices, primary papers quoted directly
- **Comparative evaluation** — "TigerBeetle vs Postgres vs FoundationDB for write-heavy workloads" → per-entity coverage, comparison matrix, committed pick, mandatory critical voice on the leader
- **Forecasting + strategy** — "Will US inflation stay above 3% through 2026?" → ground-truth statistics + institutional analysis + named contrarians, probability language not hedge
- **Interpretive analysis** — "What does Blood Meridian's violence mean?" → primary text + critical tradition + dissenting reading, every paragraph fuses fact with interpretive claim
- **Enumerative coverage** — "For each Napoleonic marshal, cover key campaigns and fate" → every named entity gets every requested field, no silent downgrades
- **Persistent knowledge base** — every source ever fetched stays searchable. Future sessions check the vault before searching the web. Knowledge compounds across runs.

---

## Hooks for every major agent

`hyperresearch install` wires in one step:

| Platform | Hook | Trigger |
|----------|------|---------|
| **Claude Code** | `.claude/settings.json` + `/research` skill + 3 subagents | Before WebSearch, WebFetch |
| **Codex** | `.codex/hooks.json` | Before Bash |
| **Cursor** | `.cursor/rules/hyperresearch.mdc` | Always-apply rule |
| **Gemini CLI** | `.gemini/settings.json` | Before tool calls |

```bash
hyperresearch install --platform all    # Hook every platform at once
```

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
- **Deeper-not-broader.** v0.5.0 prefers 15 well-extracted sources over 50 skim-fetched ones. The protocol enforces analyst coverage, not source count.

---

## Requirements

- Python 3.11+
- Claude Code (or Codex / Cursor / Gemini CLI) with API access
- Anthropic API key with access to Opus, Sonnet, and Haiku — one key powers the full subagent triad
- Windows, macOS, Linux

---

## License

[MIT](LICENSE)

---

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=jordan-gibbs/hyperresearch&type=Date)](https://star-history.com/#jordan-gibbs/hyperresearch&Date)
