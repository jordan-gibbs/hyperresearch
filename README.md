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

**Hyperresearch turns Claude Code into a deep research agent: one that currently leads the DeepResearch-Bench RACE leaderboard (benchmarked internally).** A tier-adaptive 16-step pipeline takes one prompt and produces an adversarially-audited report with full source provenance. Every source it reads lands in a persistent, searchable vault, so each session starts smarter than the last.

<p align="center">
  <img src="assets/benchmark.png" alt="DeepResearch-Bench top-5 hyperresearch leads the chart ahead of Grep Deep Research, Cellcog Max, nvidia-aiq, Gemini Deep Research, and OpenAI Deep Research" width="780">
</p>

<p align="center"><sub>Forward-looking projection from a stratified pilot against the DeepResearch-Bench leaderboard snapshot (https://huggingface.co/spaces/muset-ai/DeepResearch-Bench-Leaderboard). Third party validation is pending.</sub></p>

## Why it wins

- **250+ sources in a single run.** The `premier` scale profile targets 100–130 in the width sweep alone; citation chasing and gap-fill fetches more than double what actually lands in the corpus.
- **Every citation is verified before the report ships.** A skeptical cite-checker audits whether each cited source actually supports its sentence. Hallucinated quotes and unacknowledged retractions are hard blocks at the gate.
- **Syndication doesn't count as consensus.** An independence audit clusters derivative copies, so five reprints of one press release argue with the weight of one source.
- **Adversarial by construction.** Four critics attack every draft in parallel, and a tool-locked patcher can only apply surgical edits. It physically cannot rewrite the report.
- **Nothing is thrown away.** Every source lands in a searchable markdown-plus-SQLite vault that your next session reuses before it fetches anything new.
- **Crashed runs resume.** Each run keeps a manifest; `run resume` picks up at the exact step where it died.
- **Scales from 30 minutes to a dissertation.** Bounded queries auto-route to a 5-step fast path. Opt-in dissertation runs write 25K–80K words across chapters, from 300–450 sources.

## Install

```bash
cd your-project
pip install hyperresearch && hyperresearch install
```

Then `/hyperresearch <anything>` in Claude Code.

> Python 3.11–3.13. (3.14 not yet supported. Use `pyenv install 3.13`, `uv venv -p 3.13`, or `py -3.13 -m venv .venv`.)
>
> Power users: `hyperresearch install --global` makes `/hyperresearch` reachable from every Claude Code session anywhere, at the cost of ~15 lines in every session's system reminder. Per-project install (above) keeps unrelated CC sessions clean.

---

## The 16-step research pipeline

The entry skill is a thin router. It pins down the canonical research query, then invokes one step skill per phase via Claude Code's `Skill` tool. Each step's procedure loads into context only when that step actually runs. That's what stops a long pipeline from quietly dropping steps as its context rots.

| # | Step | What it does | Tiers |
|---|---|---|---|
| 1 | Decompose | Canonical query → atomic items + coverage matrix + tier classification | all |
| 1.5 | Chapter partition | Group atomic items into 4–10 chapters; steps 2–10 then loop per chapter | dissertation |
| 2 | Width sweep | Multi-perspective search plan + parallel fetcher waves | all |
| 3 | Contradiction graph | Pair contradictions across the corpus into ranked clusters | full |
| 4 | Loci analysis | Two parallel loci-analysts → scored loci with source budgets | full |
| 5 | Depth investigation | K parallel depth-investigators → interim notes with committed positions | full |
| 6 | Cross-locus reconcile | Reconcile committed positions → comparisons.md | full |
| 7 | Source tensions | Extract expert disagreements → source-tensions.json | full |
| 8 | Corpus critic | "What source would overturn this?" + targeted gap-fill fetch | full |
| 9 | Evidence digest | Top claims + verbatim quotes → evidence-digest.md | full |
| 10 | Triple draft | Per-angle source curation + 3 parallel draft sub-orchestrators (light: single draft) | all |
| 11 | Synthesize | Plan + outline + spawn synthesizer subagent → final_report.md | full |
| 12 | Critics | 4 adversarial critics in parallel → findings JSONs | full |
| 13 | Gap-fetch | Targeted fetch wave for critic-identified vault gaps | full |
| 14 | Patcher | Surgical Edit hunks applied to draft (tool-locked Read+Edit) | full |
| 14.5 | Cite-check | Verify citation-sentence bindings; skeptical LLM spot-check; second surgical patch pass | full |
| 15 | Polish | Hygiene + filler pass (tool-locked Read+Edit subagent) | all |
| 16 | Readability audit | Recommender writes JSON suggestions; orchestrator selectively applies | all |

### Tiers and gears: the two scale levers

**Tiers** route per query. Step 1 auto-classifies `light` vs `full`. `dissertation` is opt-in only; ask for it in your prompt.

| Tier | What runs | Typical time |
|---|---|---|
| `light` | bounded factual queries, surveys, comparisons: 1 → 2 → 10 → 15 → 16 | ~30–40 min |
| `full` (default) | deep argumentative analysis with adversarial review: all 16 steps + cite-check | ~1.5–2.5 h at `full` gear |
| `dissertation` | chaptered mega-runs: 300–450 sources across 4–10 chapters, 25K–80K words | ~4–8 hours |

**Gears** set the scale of the standard pipeline: the source targets, depth budgets, and word targets rendered into the step skills.

```bash
hyperresearch profile list           # all profiles + descriptions + current gear
hyperresearch profile use premier    # 100–130 sources, doubled depth budget (~3–5 h)
hyperresearch profile use full       # back to the 55–80-source baseline
```

The gear persists per project and survives reinstalls. Custom gears: define `[profile.<name>]` in `.hyperresearch/config.toml` (any knob: source targets, loci caps, draft counts, word targets, per-agent models) and `profile use <name>`.

### The two load-bearing principles

1. **Patch, never regenerate.** After step 11 produces the synthesized report (or step 10 for light tier), the only modifications are surgical Edit hunks. The patcher and polish auditor are tool-locked to `[Read, Edit]` at the Claude Code allowlist level so they physically cannot Write a new draft. Per-hunk caps make "just rewrite it" mechanically impossible. Critic findings that don't fit a small hunk escalate as structural issues.

2. **Canonical research query is gospel.** The verbatim user prompt is persisted to `research/runs/<vault_tag>/query.md` once and re-read by every subsequent step and every spawned subagent. Wrapper requirements (save paths, citation format, terminal sections) are a separate contract.

### Subagent roster

Models are profile config, not hardcode. The table shows the shipped defaults, and you can override any of them in `.hyperresearch/config.toml`: `[profile.full]` with `models = { fetcher = "haiku" }` swaps every fetcher to Haiku on the next install or `profile use`.

| Agent | Default model | Role |
|---|---|---|
| `hyperresearch-fetcher` | Sonnet | URL fetching via crawl4ai; runs 8–12 in parallel per wave |
| `hyperresearch-source-analyst` | Sonnet | End-to-end digest of any single long source >5000 words |
| `hyperresearch-loci-analyst` | Sonnet | Reads the width corpus, returns 1–8 depth loci with rationale |
| `hyperresearch-depth-investigator` | Sonnet | Investigates one locus, writes one interim note with a committed position |
| `hyperresearch-corpus-critic` | Sonnet | "What source would overturn the current direction?" pre-draft gap analysis |
| `hyperresearch-draft-orchestrator` | Opus | One per draft angle; reads its curated source list and writes one draft |
| `hyperresearch-synthesizer` | Opus | Reads all 3 drafts, writes the final report (two-pass write, Read+Write locked) |
| `hyperresearch-dialectic-critic` | Opus | Counter-evidence the draft missed |
| `hyperresearch-depth-critic` | Opus | Shallow spots interim notes could fill |
| `hyperresearch-width-critic` | Opus | Topical corners the corpus supports but the draft ignores |
| `hyperresearch-instruction-critic` | Opus | Structural mismatches against the prompt's atomic items |
| `hyperresearch-patcher` | Opus | Tool-locked `[Read, Edit]`. Applies critic findings as surgical Edit hunks |
| `hyperresearch-cite-checker` | Sonnet | Skeptically verifies sampled citation-sentence bindings before ship |
| `hyperresearch-polish-auditor` | Opus | Tool-locked `[Read, Edit]`. Cuts filler, strips hygiene leaks |
| `hyperresearch-readability-recommender` | Opus | Writes JSON suggestions for paragraph rhythm and list/table conversion |
| `hyperresearch-browser-fetcher` | Sonnet | Drains the escalation queue by driving your real Chrome (Claude-in-Chrome) |

---

## The vault: persistent, searchable, compounding

Most deep research harnesses are one-shot: report out, everything else discarded. Hyperresearch keeps what it reads. Every fetched source lands in a SQLite-indexed vault that future sessions search before they fetch.

```bash
hyperresearch search "ion-trap gate fidelity" -j           # Full-text search
hyperresearch search "quantum" --include-body -j           # Full-body search
hyperresearch note show <id1> <id2> <id3> -j               # Batch-read notes
hyperresearch graph hubs -j                                # Most-connected notes
hyperresearch graph backlinks <id> -j                      # Reverse links
hyperresearch lint -j                                      # Health check (broken links, missing tags)
```

**Markdown is truth, SQLite is cache.** Notes live as plain markdown with YAML frontmatter in `research/notes/`. The SQLite index is fully rebuildable: delete it and `hyperresearch sync` reconstructs it from the markdown. Open the vault in any editor, version it in git. You don't need the tool installed to read your own research.

**PDFs fetch directly.** `hyperresearch fetch` auto-detects PDF URLs (arXiv, NBER, SSRN, direct `.pdf` links) and extracts full text via pymupdf. Raw PDFs land in `research/raw/<note-id>.pdf` and the note's `raw_file:` frontmatter links back.

**Provenance breadcrumbs.** Every fetched source carries a `--suggested-by` link back to whatever surfaced it. The chain forms a rooted tree from seed fetches; the `provenance` lint rule catches disconnected components.

**Semantic search, if you want it.** `hyperresearch embed sync` populates embeddings (provider-pluggable: `voyage`, `openai`, or the default `none`, which needs zero API keys) and `search --semantic` blends vector similarity with full-text ranking.

---

## Source ranking: quality is persistent, not vibes

Every source accumulates a composite `quality_score` built from source-type tier, fetch-time utility, citation authority (from OpenAlex / Semantic Scholar, including **retraction flags**), and vault PageRank centrality:

```bash
hyperresearch sources score -j             # Enrich DOI-bearing notes: citations, venue, retractions
hyperresearch graph rank -j                # PageRank over the link + provenance graph
hyperresearch search "q" --ranked -j       # Quality-weighted full-text search
hyperresearch sources independence -j      # Cluster syndicated/derivative copies: 5 copies of one press release = 1 vote
hyperresearch claims search "q" -j         # Query extracted claims across all sources
```

Retracted sources are floored to near-zero quality, and a ship-time retraction sweep re-checks every cited DOI fresh, so a retraction published yesterday is caught today. Even on vault sources reused from old runs.

---

## Runs: resumable, budgeted, verified

Every run owns an isolated workspace (`research/runs/<vault_tag>/`) and a manifest. Concurrent runs never collide, and a crashed run resumes exactly where it stopped:

```bash
hyperresearch run status -j          # Step-by-step status, spend, escalation queue depth
hyperresearch run resume -j          # Exact next step + Skill invocation to continue
hyperresearch run report -j          # Per-step wall-time / spend / source-yield telemetry
hyperresearch run verify <tag> -j    # Ship gate: headings, length, citation density, cite-check resolution
```

`run init --budget 50` caps estimated API-equivalent spend; crossing the cap blocks the run rather than letting it quietly balloon. And before any report ships, the verification battery runs: **quote-integrity** (every quoted span must exist verbatim in a vault note), **retracted-citations** (citing a retracted source unacknowledged blocks the ship), **numeric-consistency** (numbers untraceable to evidence get flagged), plus the cite-check step's per-citation binding audit.

---

## What's structurally enforced

- **Verbatim prompt as gospel.** `scaffold-prompt` lint blocks if the scaffold doesn't open with the user's exact prompt
- **Locus coverage.** Every step 4 locus must have a step 5 interim note; missing interims flag as errors
- **Patch-only modification.** Steps 14, 15, 16 are tool-locked to `[Read, Edit]`. They cannot regenerate the draft
- **Critical findings never silently skip.** `patch-surgery` lint surfaces any critical finding the patcher couldn't apply
- **Quoted text must exist.** `quote-integrity` lint blocks any quoted span that doesn't appear verbatim in a vault note; hallucinated quotes cannot ship
- **Retractions block the ship.** Citing a retracted source without acknowledging the retraction is a hard error at the final gate
- **Schema integrity.** `tier`, `content_type`, and `type` are SQLite CHECK-constrained vocabularies; corrupted frontmatter cannot poison the index
- **Hygiene leaks caught on the way out.** Scaffold sections, YAML frontmatter, and prompt echoes are stripped by step 15 before ship

---

## Authenticated crawling + the browser lane

Fetch from LinkedIn, Twitter, paywalled sites or anything you can log into:

```bash
hyperresearch setup       # Browser opens. Log into your sites. Done.
```

LinkedIn, Twitter, Facebook, Instagram, and TikTok automatically use a visible browser to avoid session kills.

**Blocked fetches escalate instead of dying.** When headless crawling hits a login wall or bot wall mid-run, the URL queues as an escalation (`hyperresearch escalation list -j`). If you have the [Claude-in-Chrome](https://claude.com/chrome) extension, the browser-fetcher agent drains the queue by driving your real, logged-in Chrome. Hard boundary: **CAPTCHAs, 2FA, and logins are never solved automatically.** They're consolidated into one message and handed to you.

---

## Academic APIs before web search

For any topic with a research literature, hit academic APIs BEFORE web search. They return citation-ranked canonical papers; web search returns derivative commentary.

- **Semantic Scholar:** `https://api.semanticscholar.org/graph/v1/paper/search`
- **arXiv:** `https://export.arxiv.org/api/query`
- **OpenAlex:** `https://api.openalex.org/works`
- **PubMed:** `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi`

After the academic sweep, run web searches for context, news, non-academic angles, and at least one adversarial search ("criticism of X", "limitations of X").

---

## What it doesn't do

- It doesn't replace your judgment on which sources matter. The agent picks, you steer.
- It can't fetch what's behind a paywall you haven't logged into.
- It runs on Anthropic models via the subagent roster (per-agent assignments come from the profile's model map). Usage scales with tier, gear, and corpus size. If anyone wants to port this to Codex, put up a PR! 
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
