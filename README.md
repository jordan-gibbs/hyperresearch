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

**Hyperresearch turns Claude Code or Codex into a deep research agent: one that currently leads the DeepResearch-Bench RACE leaderboard (benchmarked internally).** A tier-adaptive 16-step pipeline takes one prompt and produces an adversarially-audited report with full source provenance. Every source it reads lands in a persistent, searchable vault, so each session starts smarter than the last.

<p align="center">
  <img src="assets/benchmark.png" alt="DeepResearch-Bench top-5 hyperresearch leads the chart ahead of Grep Deep Research, Cellcog Max, nvidia-aiq, Gemini Deep Research, and OpenAI Deep Research" width="780">
</p>

<p align="center"><sub>Forward-looking projection from a stratified pilot against the DeepResearch-Bench leaderboard snapshot (https://huggingface.co/spaces/muset-ai/DeepResearch-Bench-Leaderboard). Third party validation is pending.</sub></p>

## Why it wins

- **250+ sources in a single run.** The `premier` scale profile targets 100–130 in the width sweep alone; citation chasing and gap-fill fetches more than double what actually lands in the corpus.
- **Every citation is verified before the report ships.** A skeptical cite-checker audits whether each cited source actually supports its sentence. Hallucinated quotes and unacknowledged retractions are hard blocks at the gate.
- **Syndication doesn't count as consensus.** An independence audit clusters derivative copies, so five reprints of one press release argue with the weight of one source.
- **Adversarial by construction.** Four critics attack every draft in parallel, and a tool-locked patcher can only apply surgical edits. It physically cannot rewrite the report.
- **Paywalled papers get read, not skimmed.** A closed paper normally enters a vault as a 1,500-character abstract that the report then cites as though it had been read. Hyperresearch asks Unpaywall and Europe PMC for a legal open-access copy and stores the full text instead, even when the publisher blocks the fetch outright. Every substitution is disclosed in the note, the frontmatter, and the CLI output.
- **Nothing is thrown away.** Every source lands in a searchable markdown-plus-SQLite vault that your next session reuses before it fetches anything new.
- **Crashed runs resume.** Each run keeps a manifest; `run resume` picks up at the exact step where it died.
- **Scales from 30 minutes to a dissertation.** Bounded queries auto-route to a 5-step fast path. Opt-in dissertation runs write 25K–80K words across chapters, from 300–450 sources.

## Install

```bash
cd your-project
pip install hyperresearch && hyperresearch install
```

Then `/hyperresearch <anything>` in Claude Code or `$hyperresearch <anything>` in Codex.

> Python 3.11–3.13. (3.14 not yet supported. Use `pyenv install 3.13`, `uv venv -p 3.13`, or `py -3.13 -m venv .venv`.)
>
> Power users: `hyperresearch install --global` installs the entry skill and subagents for both Claude Code and Codex. Per-project install (above) keeps unrelated sessions clean.

---

## The 16-step research pipeline

The entry skill is a thin router. It pins down the canonical research query, then invokes one step skill per phase through the host agent's skill mechanism. Each step's procedure loads into context only when that step actually runs. That's what stops a long pipeline from quietly dropping steps as its context rots.

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

### Run levers: what voice the report is written in

Tiers and gears set how much work happens. Levers set what kind of report comes out, and step 1 picks them from your prompt's verb shape. An explicit directive in your prompt always wins.

| Lever | Values | What changes |
|---|---|---|
| `register` | `teach` / `survey` / `analyze` / `advocate` | "Teach me X" gets a pedagogical explainer; "what's the landscape" gets a map of the field with no verdict; `analyze` (the default) gets the evaluative argument; `advocate` defends one named thesis |
| `domain_notes` | freeform | Sourcing strategy, evidence norms, recency window for the field in question |
| `inference_depth` | `surface` / `standard` / `deep` | The rabbithole dial. Step 4 can upgrade it after seeing what the corpus actually holds |

The levers render into role-scoped shim files that spawn templates paste verbatim into subagent prompts, so the critics move with the register instead of undoing it. In `survey` register the dialectic critic flags unfair representation rather than missing commitment, and the polish auditor stops striking hedges. In `advocate` all of them tighten instead.

The cite-checker and the ship gate receive no shim at all. Verification never softens by mode.

```bash
hyperresearch levers set <tag> inference_depth=deep --rerender   # go deeper mid-run
hyperresearch run status -j                                      # see what step 1 chose
```

### The two load-bearing principles

1. **Patch, never regenerate.** After step 11 produces the synthesized report (or step 10 for light tier), the only modifications are surgical Edit hunks. The patcher and polish auditor are tool-locked to `[Read, Edit]` at the Claude Code allowlist level so they physically cannot Write a new draft. Per-hunk caps make "just rewrite it" mechanically impossible. Critic findings that don't fit a small hunk escalate as structural issues.

2. **Canonical research query is gospel.** The verbatim user prompt is persisted to `research/runs/<vault_tag>/query.md` once and re-read by every subsequent step and every spawned subagent. Wrapper requirements (save paths, citation format, terminal sections) are a separate contract.

### Subagent roster

Models are profile config, not hardcode. The table shows the shipped defaults, and you can override any of them in `.hyperresearch/config.toml`: `[profile.full]` with `models = { fetcher = "haiku" }` swaps every fetcher to Haiku on the next install or `profile use`.

Codex custom agents inherit the parent Codex model and tool surface; their generated developer instructions preserve the roster's behavioral tool limits. Claude Code continues to enforce the rendered model and tool allowlists directly.

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

### Curation: notes have a lifecycle

Every session ends with a curation pass, and notes move through `draft` → `review` → `evergreen`, or `stale` → `deprecated` → `archive` as material ages out. That's what keeps a vault from turning into a landfill of half-read pages.

```bash
hyperresearch note update <id> --summary "..." --add-tag <t> -j   # promote a draft
hyperresearch dedup -j                                            # near-duplicate pairs by content similarity
hyperresearch topic tree -j                                       # the topic hierarchy
hyperresearch index build -j                                      # regenerate index pages
hyperresearch batch set-status stale --tag <t> -j                 # bulk lifecycle moves
hyperresearch link --note <id> --dry-run -j                       # wiki-links the linker would add
```

### You are not locked in

The vault is markdown in a directory. Everything below is a convenience on top of that, not a dependency.

```bash
hyperresearch export json -o out.json # every note as structured JSON
hyperresearch export vault <dir>      # a filtered subset to another directory
hyperresearch import <dir>            # pull an existing markdown collection in
hyperresearch git changed -j          # notes with uncommitted changes
hyperresearch git log -j              # notes touched by recent commits
hyperresearch watch                   # auto-sync while you edit in your own editor
```

---

## Use the vault outside Claude Code

**An MCP server.** `pip install hyperresearch[mcp]`, then `hyperresearch mcp` speaks stdio, so Claude Desktop, Cursor, or anything else that speaks MCP can work the same vault. Thirteen tools: `search_notes`, `read_note`, `read_many`, `list_notes`, `get_backlinks`, `get_hubs`, `vault_status`, `lint_vault`, `check_source`, `list_sources`, `fetch_url`, `create_note`, `update_note`.

**A local web UI.** `hyperresearch serve --open` starts a stdlib HTTP server on port 8080 with note browsing, tag pages, search, and an interactive link graph. No build step and no JavaScript dependencies.

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
- **Fetched text is data, never instructions.** Web-fetched bodies are served inside an `<untrusted-source>` fence on both `note show` and `search`, so a page telling the agent to ignore its instructions is read as content

---

## The web is hostile input

A research agent reads hundreds of pages it did not choose, and any one of them can contain text addressed to the agent rather than to you.

Every body fetched from the web is served wrapped in `<untrusted-source url="...">` delimiters with an inline treat-as-data preamble, on both paths that serve bodies (`note show` in single, batch, and JSON forms, and `search` with bodies included). Notes your own pipeline subagents wrote pass through unwrapped. Forged fence tags inside a fetched body are neutralized and left visible for forensics, the `url` attribute is HTML-escaped with control characters stripped, and in `search` the wrapping happens after token-budget truncation so the closing fence can never be severed. The fetcher, depth-investigator, draft-orchestrator, and source-analyst prompts all carry a policy block telling them not to launder a fenced page's directives into trusted output.

Resolved URLs from third-party APIs get the same treatment. An open-access location arrives inside someone else's JSON, so it's checked for scheme, embedded credentials, and publicly-routable resolution before anything fetches it.

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

## Open-access full text: read this before you cite

A paywalled paper otherwise enters the vault as an abstract, and the pipeline then reasons over ~1,500 characters while citing the work as though the paper had been read. To close that, when a fetch lands a thin page carrying a DOI, hyperresearch asks [Unpaywall](https://unpaywall.org/) and [Europe PMC](https://europepmc.org/) for a legal open-access copy and stores **that** text in the note body instead.

**The note's `source:` still points at the URL you asked for. The body may have come from somewhere else.** That substitution is disclosed in four places, and you should know all of them:

1. A banner at the top of the note body, naming the URL the text actually came from and which version it is.
2. `oa_url` / `oa_source` / `oa_version` / `oa_license` / `oa_recovery_kind` in the note's frontmatter.
3. An `oa` block in `hpr note show <id> --json`, carrying `body_is_not_from_source: true`.
4. A line in the output of `hpr fetch` and `hpr fetch-batch`.

### Rescued notes: nothing in them came from the source

The same lookup runs when a source can't be read **at all** — a 403, a login wall, a bot wall. Those are where a paywalled paper is most completely lost, and, since a DOI identifies the work rather than the host, where a legal copy is most likely to exist elsewhere.

A note built that way is a stronger claim than a substitution, and it is marked differently: `oa_recovery_kind: rescued`, `nothing_from_source: true` in `note show`, and a banner that says the source URL was never read. Take it literally. The title, the authors, and every word of the body are the open-access copy's — nothing was read from the URL in `source:`. If you would rather have no note than a note assembled entirely from a substitute, set `oa_rescue_blocked = false`.

Two limits worth knowing. Rescue needs a DOI, and a source that returned nothing offers no page to read one out of, so it only fires when the DOI is in the URL itself (a `doi.org` link) or in a wall page's `citation_doi` meta tag. A bare publisher URL with no DOI in it fails exactly as it did before. And a rescued source is **not** queued for the browser-escalation lane, because the paper is already in hand — if you want the publisher's own page specifically, fetch it through that lane yourself.

**Versions are not interchangeable.** Unpaywall will happily hand back an accepted manuscript or a submitted preprint when no published copy is open. hyperresearch prefers the version of record and records what it got in `oa_version`, but if that says `acceptedVersion` or `submittedVersion`, check any direct quotation against the published paper before it reaches a report. The body banner says so too.

Configure it under `[scholar]` in `.hyperresearch/config.toml`:

```toml
[scholar]
oa_recovery = true              # set false to disable entirely
contact_email = ""              # REQUIRED by Unpaywall's terms — empty means Unpaywall is skipped
oa_min_full_text_chars = 6000   # bodies shorter than this trigger a lookup
oa_prefer_published = true      # version of record over preprints
oa_max_attempts = 3             # candidate copies to try before giving up
oa_rescue_blocked = true        # also run when the source can't be read at all
```

Out of the box `contact_email` is empty, so only Europe PMC runs and recovery is limited to papers in its **open-access subset**. Set it to a real address to enable Unpaywall — their terms require one, and shipping a shared placeholder would get that placeholder rate-limited for every hyperresearch user at once.

Publishers block their own open-access PDFs often enough that one attempt isn't enough, so hyperresearch walks a candidate list: every PDF Unpaywall knows about, then the landing pages, then Europe PMC's structured full text (parsed from JATS, which beats pymupdf on a two-column PDF — real section boundaries, no header bleed, no column interleaving). Europe PMC is only queried once Unpaywall's copies are exhausted.

**Recovery never fails a fetch and never lowers quality.** A candidate has to clear two bars to be accepted: more text than you already had, *and* enough text to clear `oa_min_full_text_chars`. That second bar is what stops a repository record page — title, authors, a 200-word summary — from passing for full text just by being marginally longer than the publisher's abstract. If no candidate clears both, you keep the abstract and no `oa` block appears. Rescue only ever turns a failed fetch into a note, never the reverse: when a blocked source has no open-access copy, the command fails exactly as it always did.

---

## What it doesn't do

- It doesn't replace your judgment on which sources matter. The agent picks, you steer.
- It can't fetch what's behind a paywall you haven't logged into. Open-access recovery finds a legal free copy when one exists — even when the publisher blocks the fetch outright — but when none exists you get the abstract, or nothing, and the note says so.
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

<a href="https://www.star-history.com/?repos=jordan-gibbs%2Fhyperresearch&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=jordan-gibbs/hyperresearch&type=date&theme=dark&legend=top-left&sealed_token=O15PJBZHscunDCjQoz5Uy-Ou7UFPsBi6XuY3Phok5EA_dC2WKUCI6og8VtOCv-6bHUPJZz51wpUoi6rAmsQzG6QTaxaZ58kyZ3GvRbOJv-vPJBtG7zD4ow" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=jordan-gibbs/hyperresearch&type=date&legend=top-left&sealed_token=O15PJBZHscunDCjQoz5Uy-Ou7UFPsBi6XuY3Phok5EA_dC2WKUCI6og8VtOCv-6bHUPJZz51wpUoi6rAmsQzG6QTaxaZ58kyZ3GvRbOJv-vPJBtG7zD4ow" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=jordan-gibbs/hyperresearch&type=date&legend=top-left&sealed_token=O15PJBZHscunDCjQoz5Uy-Ou7UFPsBi6XuY3Phok5EA_dC2WKUCI6og8VtOCv-6bHUPJZz51wpUoi6rAmsQzG6QTaxaZ58kyZ3GvRbOJv-vPJBtG7zD4ow" />
 </picture>
</a>
