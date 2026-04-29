<p align="center">
  <img src="assets/banner.png" alt="HYPERRESEARCH" width="700">
</p>

<h3 align="center">The Most Powerful Deep Research Harness</h3>

<p align="center">
  <a href="https://pypi.org/project/hyperresearch/"><img src="https://img.shields.io/pypi/v/hyperresearch" alt="PyPI version"></a>
  <a href="https://pypi.org/project/hyperresearch/"><img src="https://img.shields.io/pypi/pyversions/hyperresearch" alt="Python 3.11+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/jordan-gibbs/hyperresearch" alt="License: MIT"></a>
  <a href="https://github.com/jordan-gibbs/hyperresearch"><img src="https://img.shields.io/github/stars/jordan-gibbs/hyperresearch?style=social" alt="GitHub stars"></a>
</p>

---

**Hyperresearch turns Claude Code into a deep research agent. and currently leads the DeepResearch-Bench RACE leaderboard (benchmarked internally).** A tier-adaptive 16-step pipeline produces adversarially-audited reports with full source provenance. Every fetched source lands in a persistent, searchable vault that compounds across sessions.

<p align="center">
  <img src="assets/benchmark.png" alt="DeepResearch-Bench top-5 — hyperresearch leads the chart ahead of Grep Deep Research, Cellcog Max, nvidia-aiq, Gemini Deep Research, and OpenAI Deep Research" width="780">
</p>

<p align="center"><sub>Forward-looking projection from a stratified pilot against the DeepResearch-Bench leaderboard snapshot (https://huggingface.co/spaces/muset-ai/DeepResearch-Bench-Leaderboard). Third party validation is pending.</sub></p>

## Install

```bash
pip install hyperresearch
hyperresearch install
```

Then, in a fresh Claude Code session, type `/hyperresearch <anything>`.

> **Python 3.11–3.13 only.** 3.14 isn't supported yet Use `pyenv install 3.13`, `uv venv -p 3.13 .venv`, or `py -3.13 -m venv .venv` to create a compatible environment.

---

## The 16-step research pipeline

The entry skill is a thin router. It bootstraps the canonical research query, then invokes one step skill per pipeline phase via Claude Code's `Skill` tool. Each step's procedure is loaded fresh into context only when needed defeating context-rot problems that makes long pipelines silently drop steps.

| # | Step | What it does | Tiers |
|---|---|---|---|
| 1 | Decompose | Canonical query → atomic items + coverage matrix + tier classification | both |
| 2 | Width sweep | Multi-perspective search plan + parallel fetcher waves (Haiku) | both |
| 3 | Contradiction graph | Pair contradictions across the corpus into ranked clusters | full |
| 4 | Loci analysis | Two parallel loci-analysts → scored loci with source budgets | full |
| 5 | Depth investigation | K parallel depth-investigators → interim notes with committed positions | full |
| 6 | Cross-locus reconcile | Reconcile committed positions → comparisons.md | full |
| 7 | Source tensions | Extract expert disagreements → source-tensions.json | full |
| 8 | Corpus critic | "What source would overturn this?" + targeted gap-fill fetch | full |
| 9 | Evidence digest | Top claims + verbatim quotes → evidence-digest.md | full |
| 10 | Triple draft | Per-angle source curation + 3 parallel draft sub-orchestrators (light: single draft) | both |
| 11 | Synthesize | Plan + outline + spawn synthesizer subagent → final_report.md | full |
| 12 | Critics | 4 adversarial critics in parallel → findings JSONs | full |
| 13 | Gap-fetch | Targeted fetch wave for critic-identified vault gaps | full |
| 14 | Patcher | Surgical Edit hunks applied to draft (tool-locked Read+Edit) | full |
| 15 | Polish | Hygiene + filler pass (tool-locked Read+Edit subagent) | both |
| 16 | Readability audit | Recommender writes JSON suggestions; orchestrator selectively applies | both |

### Depth Modes 

In your prompt, you can request one of two tiers and the rest of the pipeline scales accordingly. Full mode is default.

| Tier | Steps that run | Typical time |
|---|---|---|
| `light` | bounded factual queries, surveys, comparisons — 1 → 2 → 10 → 15 → 16 | ~30–40 min |
| `full` | deep argumentative analysis with adversarial review — all 16 steps | ~1.5–2.5 hours |

### The two load-bearing principles

1. **Patch, never regenerate.** After step 11 produces the synthesized report (or step 10 for light tier), the only modifications are surgical Edit hunks. The patcher and polish auditor are tool-locked to `[Read, Edit]` at the Claude Code allowlist level so they physically cannot Write a new draft. Per-hunk caps make "just rewrite it" mechanically impossible. Critic findings that don't fit a small hunk escalate as structural issues.

2. **Canonical research query is gospel.** The verbatim user prompt is persisted to `research/query-<vault_tag>.md` once and re-read by every subsequent step and every spawned subagent. Wrapper requirements (save paths, citation format, terminal sections) are a separate contract.

### Subagent roster

| Agent | Model | Role |
|---|---|---|
| `hyperresearch-fetcher` | Haiku | URL fetching via crawl4ai; runs 8–12 in parallel per wave |
| `hyperresearch-source-analyst` | Sonnet (1M ctx) | End-to-end digest of any single long source >5000 words |
| `hyperresearch-loci-analyst` | Sonnet | Reads the width corpus, returns 1–8 depth loci with rationale |
| `hyperresearch-depth-investigator` | Sonnet | Investigates one locus, writes one interim note with a committed position |
| `hyperresearch-corpus-critic` | Sonnet | "What source would overturn the current direction?" pre-draft gap analysis |
| `hyperresearch-draft-orchestrator` | Sonnet | One per draft angle; reads its curated source list and writes one draft |
| `hyperresearch-synthesizer` | Opus | Reads all 3 drafts, writes the final report (two-pass write, Read+Write locked) |
| `hyperresearch-dialectic-critic` | Opus | Counter-evidence the draft missed |
| `hyperresearch-depth-critic` | Opus | Shallow spots interim notes could fill |
| `hyperresearch-width-critic` | Opus | Topical corners the corpus supports but the draft ignores |
| `hyperresearch-instruction-critic` | Opus | Structural mismatches against the prompt's atomic items |
| `hyperresearch-patcher` | Opus | Tool-locked `[Read, Edit]`. Applies critic findings as surgical Edit hunks |
| `hyperresearch-polish-auditor` | Opus | Tool-locked `[Read, Edit]`. Cuts filler, strips hygiene leaks |
| `hyperresearch-readability-recommender` | Opus | Writes JSON suggestions for paragraph rhythm and list/table conversion |

---

## The vault: persistent, searchable, compounding

Hyperresearch is not a one-shot report generator like most other Deep research harnesses. Every fetched source lands in a SQLite-indexed vault that every future research session can reuse.

```bash
hyperresearch search "ion-trap gate fidelity" -j           # Full-text search
hyperresearch search "quantum" --include-body -j           # Full-body search
hyperresearch note show <id1> <id2> <id3> -j               # Batch-read notes
hyperresearch graph hubs -j                                # Most-connected notes
hyperresearch graph backlinks <id> -j                      # Reverse links
hyperresearch lint -j                                      # Health check (broken links, missing tags)
```

**Markdown is truth, SQLite is cache.** Notes live as plain markdown with YAML frontmatter in `research/notes/`. The SQLite index is fully rebuildable. Delete it and `hyperresearch sync` reconstructs it from the markdown. The vault is inspectable in any editor, version-controllable in git, and readable without the tool installed.

**PDFs fetch directly.** `hyperresearch fetch` auto-detects PDF URLs (arXiv, NBER, SSRN, direct `.pdf` links) and extracts full text via pymupdf. Raw PDFs land in `research/raw/<note-id>.pdf` and the note's `raw_file:` frontmatter links back.

**Provenance breadcrumbs.** Every fetched source carries a `--suggested-by` link back to whatever surfaced it. The chain forms a rooted tree from seed fetches; the `provenance` lint rule catches disconnected components.

---

## What's structurally enforced

- **Verbatim prompt as gospel** — `scaffold-prompt` lint blocks if the scaffold doesn't open with the user's exact prompt
- **Locus coverage** — every step 4 locus must have a step 5 interim note; missing interims flag as errors
- **Patch-only modification** — steps 14, 15, 16 are tool-locked to `[Read, Edit]`. They cannot regenerate the draft
- **Critical findings never silently skip** — `patch-surgery` lint surfaces any critical finding the patcher couldn't apply
- **Schema integrity** — `tier`, `content_type`, and `type` are SQLite CHECK-constrained vocabularies; corrupted frontmatter cannot poison the index
- **Hygiene leaks caught on the way out** — scaffold sections, YAML frontmatter, and prompt echoes are stripped by step 15 before ship

---

## Authenticated crawling

Fetch from LinkedIn, Twitter, paywalled sites or anything you can log into:

```bash
hyperresearch setup       # Browser opens. Log into your sites. Done.
```

LinkedIn, Twitter, Facebook, Instagram, and TikTok automatically use a visible browser to avoid session kills.

---

## Academic APIs before web search

For any topic with a research literature, hit academic APIs BEFORE web search. They return citation-ranked canonical papers; web search returns derivative commentary.

- **Semantic Scholar** — `https://api.semanticscholar.org/graph/v1/paper/search`
- **arXiv** — `https://export.arxiv.org/api/query`
- **OpenAlex** — `https://api.openalex.org/works`
- **PubMed** — `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi`

After the academic sweep, run web searches for context, news, non-academic angles, and at least one adversarial search ("criticism of X", "limitations of X").

---

## What it doesn't do

- It doesn't replace your judgment on which sources matter. The agent picks, you steer.
- It can't fetch what's behind a paywall you haven't logged into.
- It runs on Anthropic models Opus + Sonnet + Haiku via the subagent roster. Costs scale with tier and corpus size. If anyone wants to port this to Codex, put up a PR! 
- The lint gate catches **structural** failures (missing scaffold, broken provenance, unresolved CRITICALs). It cannot guarantee factual accuracy, that's still your call.

---

## Requirements

- Python 3.11+
- [Claude Code](https://claude.com/claude-code)

---

## License

[MIT](LICENSE)

---

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=jordan-gibbs/hyperresearch&type=Date)](https://star-history.com/#jordan-gibbs/hyperresearch&Date)
