# Changelog

## [Unreleased]

### Ship gate enforcement: `run finish` (lessons from the first premier run)

The first end-to-end premier benchmark run exposed both prose-only gates failing exactly the way prose gates fail: the orchestrator never invoked `run verify` (a 25,647-word report shipped against a 16K ceiling), and when lint flagged 24 hallucinated/mangled quotes it wrote itself a "false positives" memo and shipped anyway.

- **`hpr run finish <tag>`** is the new terminal gate and the ONLY path to manifest status `done`. It runs the full verification battery and flips the run to `done` on pass or `blocked (verify)` on fail, recording the verdict in the manifest either way. The router's final gate now centers on it, with explicit no-override language (gate errors are fixed by changing the report, never re-interpreted), a bounded 3-round fix loop, and a new invariant: a run is complete only when `finish` reports `passed: true`.
- **`verify_run` now includes the blocking content lints** (`quote-integrity`, `retracted-citations`) in-process, so one command carries the whole verdict and there is no seam where a failing rule can be run separately and argued with.
- **Length enforcement moved upstream too.** Step 11 gains a mechanical word-count gate with the one permitted fix (a single synthesizer compression respawn, cheapest at that moment); the synthesizer's word-target table is now rendered from the profile (it was hardcoded to full-gear numbers, so premier's 8-16K target never reached the prompt) with the high end stated as a hard ceiling; the polish auditor strips quotation marks from non-verbatim rhetorical framing before the gate ever sees them.

### Per-agent models are now real config; dollar-cost claims removed

- **ModelMap wired into agent rendering.** The profile's per-agent model map existed but was decorative — every installed agent's `model:` frontmatter line was hardcoded in `hooks.py`, so overriding models via a profile silently did nothing. All 16 agent templates now carry `model: << p.models.X >>`, rendered from the profile at install time, and `ModelMap` gained the two missing agents (`cite_checker`, `browser_fetcher`) plus validation (non-empty; aliases or full model IDs both accepted). Full flexibility per agent: `[profile.full]` + `models = { fetcher = "haiku" }` swaps every fetcher to Haiku on the next install/`profile use`; unspecified agents keep their defaults. Defaults are unchanged (verified byte-identical by the goldens).
- **Model names left the prose.** Agent descriptions and skill text no longer claim "Runs on Sonnet/Opus" (or Sonnet-specific context-window sizes) — the rendered `model:` line is the single source of truth, so a model override can never be contradicted by stale prose. Install-action labels and code comments were de-modeled to match. Drift-proofed by tests: any literal `model:` line in an agent template, or any "Runs on <model>" claim in rendered output, fails the suite.
- **Dollar-cost estimates removed from the product** (the local benchmark harness keeps its billing-aware cost math). On subscription billing, Claude Code's `cost_usd` is an API-equivalent valuation, not a charge — stating costs as prices contradicted how most users run the pipeline. Gone: the `cost_estimate` profile field and its four builtin values, the router tier table's cost column, `profile list/use` cost output, gap-fetch's "+$1-3 per run", and the source-analyst's "$2-5 per spawn" block (now "Effort discipline"). Time estimates remain. The opt-in budget governor (`run init --budget`) stays, relabeled as a ceiling on *estimated API-equivalent* spend; `run status/report` spend lines now say "API-equiv". A rendered-prompt test rejects any future `$N-M` range.

### Benchmark harness: gear-aware, one-command, and citation-correct

- **Fixed: wrapped runs shipped citation-free reports.** The step-1 skill has always documented "the benchmark harness sets `inline` via wrapper_contract" — but the harness never wrote that file. Every wrapped run therefore fell back to the `wikilink` default, shipping vault-internal `[[note-id]]` markers that `evaluate.py` strips before grading, so reports reached the FACT citation evaluator with **zero verifiable URLs**. Confirmed on the existing fleet: `runs_layercake/query_62` is 7,932 words with 0 numbered citations, 0 URLs. The harness now writes `research/wrapper_contract.json` (`citation_style: inline` + required terminal sections), the pipeline prompt states the requirement explicitly, and `citation-style-preservation` + `quote-integrity` joined the post-run validation rules so a regression is caught per query.
- **Harness modernized for V8.** The pipeline prompt invoked `/research-layercake` (retired), and the startup banner checked for V7 `layercake-*` skills expecting 14 — now `/hyperresearch` and 18 `hyperresearch-*` step skills. The timeout was hardcoded at 3600s, which would have silently timed out (and discarded) every premier run; it is now gear-scaled (1h at `full`, 6h at `premier`).
- **Gear-aware fleets.** Scale comes from the installed gear, not a flag — `_setup_run_dir` copies the project root's rendered `.claude/` + `config.toml` into every run dir. Non-`full` gears now get their own runs dir (`bench/runs_layercake-premier/`) and tag suffix so fleets never overwrite each other; `evaluate.py` gained a matching `--gear` flag (it previously hardcoded `runs_layercake` and stripped the tag by a fixed length, which a gear suffix breaks).
- **`bench/compare.py`** — head-to-head fleet comparison on shared queries only: RACE sub-scores where graded, plus structural metrics (words, citations, citation density, unique URLs, vault sources, cost, duration) that need no API key. Flags the citation confound when comparing against pre-fix fleets.
- **`bench/run_premier.py`** — one command: preflight (CLIs, queries, gear validity, grading keys) → set + verify gear → cost confirmation → run → RACE/FACT evaluation → comparison.

### Scale gears: premier profile + `hpr profile use`

- **New built-in `premier` profile** — the flat pipeline at ~2× scale: 100–130 sources (min 90), 80–160 planned searches, 14–18 wave-1 fetchers, 10 loci with a doubled depth budget (80), and a widened downstream funnel (claims 150–220, must-read 50–70, 8–16K words, 120–220 citations, raised critic caps) so the extra corpus actually reaches the page instead of stranding in the vault. Estimate: ~3–5 hours.
- **Gears vs tiers, made explicit.** `light` and `dissertation` are run-time *tiers* (auto-classified / opt-in per query); `full` and `premier` are install-time *gears* — the profile whose numbers are rendered into the skill and agent prompts. The router now carries a "Scale gear (tier ≠ gear)" section, and the width-sweep's full-tier numbers follow the gear (`p.*`) instead of being pinned to the `full` profile (byte-identical under the default gear, verified by goldens).
- **`hpr profile use <name>`** — the one-command gear shift: validates the profile, re-renders every installed skill/agent prompt, and persists the choice under `[pipeline] profile` in config.toml so later bare `install` runs (e.g. after upgrades) keep the gear. Refuses `light`/`dissertation` with an explanation (they're tiers). `hpr profile list` now shows descriptions, source targets, time estimates, and marks the current gear.
- **Fix: `[profile.*]` overlays survive config saves.** `VaultConfig.save()` previously dropped user-defined profile tables — any config write (e.g. the crawl4ai auto-setup) silently destroyed custom pipeline profiles. Overlays now round-trip verbatim, including nested inline tables and array-of-array values.

### Phase 5 (2.0 roadmap): verification — the layer that makes it trustworthy

- **Cite-check (new step 14.5, full + dissertation).** Every citation is verified as a citation-sentence BINDING before ship. `hpr citecheck extract` parses (sentence, citation) pairs for both citation styles and mechanically auto-passes pairs whose numbers/wording the claims table confirms; dangling citations (resolving to no vault note) are instant critical findings. The sampled remainder (100% of number-bearing sentences, deterministic sampling for the rest — resume-safe, no RNG) goes to the new `hyperresearch-cite-checker` agent, whose verdicts default skeptical (`supported / partially-supported / unsupported / wrong-source`); findings feed a second, small tool-locked patcher pass. 18 step skills now.
- **Three verification lint rules.** `quote-integrity` (error): every quoted span ≥5 words must exist verbatim in a vault note — hallucinated quotes cannot ship. `numeric-consistency` (warning): report numbers untraceable to claims or cited-note bodies are flagged for verification. `retracted-citations` (error): citing a retracted source blocks the gate unless the citation itself acknowledges the retraction (sometimes the retraction IS the story).
- **Ship-time retraction sweep.** `hpr sources retractions --tag` re-checks every DOI-bearing note fresh (cache-bypassing), so a retraction published yesterday is caught today — including on vault sources being REUSED from prior runs.
- **Independence audit.** `hpr sources independence` clusters derivative sources (canonical-URL identity with tracking-param stripping, near-duplicate bodies via MinHash Jaccard, shared wire-service boilerplate keyed on the body opening — outlets retitle, the wire text doesn't change) and scores members `1/cluster_size`. Step 3's consensus rule now counts independence-weighted voices, so five syndicated copies of one press release are ONE vote, not five.
- **Run telemetry + verification battery.** `hpr run report [--all]` rolls up per-step wall-time, spend, and event counts from the manifest + events log — the feedback loop for tuning profile constants against observed yield. `hpr run verify` is the CI-able structural gate (report exists, required headings, length in profile range ±20%, citation density ≥1.5/1000 chars, tier artifacts present, scaffold-leak check, cite-check criticals resolved; exit 1 on failure) — wired into the router's final integrity gate alongside the new lint rules.
- **Bench note.** The phase plan's nightly bench-smoke CI workflow was NOT created: `bench/` turns out to be entirely gitignored (local-only), so a workflow referencing it would be broken by construction. `hpr run verify` is the shipped, CI-able equivalent; local bench scratch (`_*.py` etc.) was tidied into `bench/archive/`.

### Phase 4 (2.0 roadmap): the browser lane — blocked fetches escalate instead of dying

- **Escalation queue (schema v10).** Fetches that hit login walls or bot/captcha walls are no longer discarded — the fetch gate queues them in a new race-safe `escalations` table (SQLite atomic claim semantics; the phase doc's JSON-file design was upgraded deliberately) with reason, utility score, and provenance. Error codes distinguish `AUTH_REQUIRED_ESCALATED` / `JUNK_ESCALATED` so fetcher agents don't retry. Content-quality junk (404s, empty pages) still dies — a 404 in Chrome is still a 404. Policy under `[chrome]`: `enabled`, `escalation_utility_threshold` (low-value blocked URLs are abandoned, the lane is serial and precious), `max_items_per_run`.
- **`hpr escalation` CLI** — `list/add/claim/complete-via-ingest/human/retry/abandon`. `claim` is atomic under concurrent claimers; `ingest` is the one-shot completion (writes the vault note with `fetch_provider: chrome`, records the source row, syncs, resolves the item) so the browser agent can't half-finish bookkeeping.
- **`hyperresearch-browser-fetcher` agent** — drains the queue by driving the user's real Chrome browser via Claude-in-Chrome (batched ToolSearch load, new tab always, one instance at a time). Playbook: infinite scroll caps, SPA expansion, PDF-viewer text layers, screenshot transcription for chart-heavy pages, and a Google Scholar lane (`reason: scholar_search` items carry a query; results ingest as structured notes, high-citation hits re-queue). **Hard scope boundary, stated in the prompt and enforced by the workflow: CAPTCHAs, 2FA, and logins are never solved automatically — items go to `needs_human`.**
- **Human-in-the-loop checkpoint.** All `needs_human` items are consolidated into ONE user prompt at a natural pause point (never per-URL interruptions); after the human completes challenges in their own browser, `escalation retry` + one more drain. Non-interactive runs record `run block --on human-challenges` and continue with everything else; `hpr run status` shows queue depth and needs_human counts.
- **Graceful degradation.** Without the Claude-in-Chrome extension the queue simply accumulates (visible in `run status`); the floor is the pre-4.0 status quo. Session handoff (Chrome cookies → crawl4ai profile) was evaluated and deliberately NOT implemented: HttpOnly cookies aren't scriptable from page JS, so the honest v1 is the Chrome lane itself plus the existing `hyperresearch setup` guided-login flow.

### Phase 3 (2.0 roadmap): dissertation scale — run isolation, manifest, chapters

- **Per-run workspaces.** Every run-scoped pipeline artifact (scaffold, decomposition, loci, comparisons, critic findings, patch/polish logs, temp scratch, canonical query) now lives under `research/runs/<vault_tag>/` — concurrent and sequential runs can never collide (closes the parallel-run race flagged in 0.8.6). Vault notes stay global; final reports stay at `research/notes/final_report_<tag>.md`. Sync never ingests run workspaces; lint rules resolve artifacts run-aware with full legacy flat-path fallback for pre-3.0 vaults; `vault-tag` collision checks cover run dirs.
- **Run manifest + explicit resume.** `hpr run init/status/resume/abort/step/spend/event` — `run.json` records per-step + per-chapter status, spend counters, and a heartbeat; `hpr run resume` returns the exact next step and Skill invocation (replacing artifact-scan recovery, which remains as fallback). `run status` flags possibly-stalled runs.
- **Budget governor.** `run init --budget <usd>` sets a hard ceiling; crossing it flips the run to `blocked (budget)`. The router instructs shrinking fan-out near the ceiling instead of silently skipping profile-mandated steps.
- **`dissertation` profile + chaptered execution.** New built-in profile (opt-in only, never auto-classified): 250–450 sources across 4–10 chapters, each chapter running the proven 40–80-source pipeline envelope (steps 2–10 loop per chapter, ≤2 in flight), global reconcile/synthesis on top, 25K–80K-word chaptered output, scaled critic caps, multi-hour pacing. New step skill `hyperresearch-1-5-chapter-partition` (17 step skills now).
- **Literature-review matrix + meta-analysis substrate.** `hpr claims matrix` generates the per-source review table (tier, venue, citations, quality, key finding) from the claims table; `hpr claims targets` groups claims by stance_target across sources with stance splits and source-attributed numbers for comparison tables.

### Phase 2 (2.0 roadmap): the source-ranking engine

Source quality becomes a persistent, queryable property instead of ephemeral prompt prose (schema v9, additive-only).

- **Per-source quality scores.** New note columns: `doi`, `utility_score`, `citation_count`, `venue`, `is_retracted` (frontmatter-mirrored — markdown stays truth) plus derived `authority_score`, `centrality_score`, `independence`, `quality_score` (DB-cache, recomputed, survive re-sync).
- **`hpr sources score`** — enriches DOI-bearing notes from OpenAlex/Semantic Scholar (citation counts, venue, **retraction flags**), cached in a new `api_cache` table (`[ranking] api_cache_ttl_days`, default 30). `hpr sources backfill-doi` regexes the back-catalog; new fetches capture DOIs/arXiv ids automatically, and `fetch --utility-score` persists the step-2 utility score that was previously discarded after fetch selection.
- **`hpr graph rank`** — pure-Python PageRank over the link + provenance-breadcrumb graph; centrality here means "many independent research chains converged on this source". Also recomputed during `repair`.
- **Composite `quality_score`** — renormalized weighted blend of tier weight, utility, citation-authority percentile (vault-relative, log-scaled), and centrality; retracted sources floored at 0.05. Weights configurable under `[ranking]`.
- **`hpr search --ranked`** — folds `quality_score` into FTS relevance (`(0.5 + quality)` multiplier; unscored notes stay neutral). Default search behavior unchanged.
- **Claims table** — `hpr claims ingest/list/search` persists fetcher-extracted `claims-*.json` into queryable `claims` + `claims_fts` tables keyed to source notes (idempotent by content hash). This is the substrate for phase-5 cite-checking.
- **Semantic search (embeddings table revived)** — `hpr embed sync` + `hpr search --semantic` (RRF hybrid with FTS). Provider-pluggable under `[embeddings]`: `none` (default — zero API keys required), `voyage`, `openai`. Brute-force cosine, no vector-DB dependency.
- **Pipeline integration** — step 2 gains step 2.7 (persist ranking signals after the last wave; retracted sources flagged before they can anchor a locus); fetcher batches carry utility scores; step 10 curates from `search --ranked` instead of orchestrator intuition.

### Phase 1 (2.0 roadmap): config extraction + pipeline profiles

- **Every behavioral constant is now config** (`docs/roadmap-2.0/phase-1-config-profiles.md` WS1). New `.hyperresearch/config.toml` sections: `[fetch]` (page/PDF timeouts, smart-wait polling, visible-browser domain list, image timeout), `[junk]` (content gates, binary-garbage ratio, extra signal lists), `[assets]` (max images, min image bytes), `[dedup]` (MinHash/LSH parameters, threshold), `[lint]` (extract-coverage and stale-review thresholds), plus `[search]` output defaults (`default_limit`, `chars_per_token`, `snippet_len`). All defaults reproduce prior behavior.
- **BEHAVIOR CHANGE — PDF downloads verify TLS by default.** The PDF fetch path previously hardcoded `verify=False`, silently disabling certificate verification. New `[fetch] pdf_verify_tls` defaults to `true` (secure). Set it to `false` explicitly for cert-broken mirrors you trust.
- **Pipeline profiles** (`hyperresearch profile list/show/validate`). Every research-scale knob — source gates, fetcher fan-out, loci caps, depth budgets, draft counts, word targets, critic caps, per-agent models — lives in a named, validated profile. Built-in `full` and `light` reproduce the shipped V8 values exactly; users override keys or define new profiles (`[profile.dissertation] extends = "full"`) in config.toml.
- **Skill/agent prompts are now templates rendered at install.** `hyperresearch install --profile <name>` renders the 17 skills and 15 agent prompts from the chosen profile (custom `<< >>` Jinja delimiters — prompt-native `{{...}}` placeholders and JSON braces pass through untouched). Rendered files carry a `rendered from profile "..."` provenance header after the frontmatter. Golden tests pin the `full`-profile render byte-for-byte against the pre-template prompts, so profile/template drift is a test failure, not a silent prompt change.
- **Width-sweep consistency fix** (roadmap phase-0 WS5, pulled forward): the three contradictory full-tier source-target statements (40-100 / 40–80 / 55–80) are unified to the profile value (55–80); the light target (12–20 vs 15–25) and the tier-table fetchers-per-wave (8–12 vs 10–12) are likewise unified to the table/Wave-1 values.

Community-fix release: five contributed PRs plus two maintainer follow-ups, closing #32, #33, #35, #37, and #39.

### Fetching and search

- **Non-English pages are no longer discarded as binary garbage (closes #37, thanks @synqing).** The junk filter counted every character above `ord(127)` as non-printable, so CJK, Arabic, Cyrillic, and accented-Latin pages always tripped the threshold and were thrown away. The check now counts only true control characters and U+FFFD, shared between both fetch gates via one `binary_garbage_ratio()` so they can't drift apart again. Regression fixtures use real Chinese/Japanese/Arabic/Russian/French prose.
- **Degenerate or failed searches error loudly instead of returning `[]` (closes #32, thanks @ankaggarwal94 for the report and @synqing for the fix).** An empty query, a malformed query, and a broken FTS index were all silently swallowed and reported as "no results." `search_fts` now raises `SearchQueryError` for queries with no searchable terms (CLI exits 2 with `BAD_QUERY` in `--json` mode) and lets genuine index failures propagate. The shipped step skills and agent prompts that used `search "" --tag` as a list-all idiom were rewritten to `note list --tag ... --all`.
- **Patchright stealth actually engages now (closes #35, thanks @seanyoungberg).** The crawler was built without an explicit strategy, so crawl4ai defaulted to plain Playwright and the stealth driver never ran. The provider now wires `UndetectedAdapter` through `AsyncPlaywrightCrawlerStrategy` at both fetch call sites; Crawl4AI floor raised to 0.7.3.
- **PDF fetch failures are diagnosable instead of silent (closes #39, thanks @mcowan38 for the report and @synqing for the fix).** Every `_fetch_pdf` failure path now logs its reason — including a missing/broken pymupdf, which used to silently disable all PDF ingestion and present as every PDF on every domain getting junked. PDF identity now comes from `%PDF-` magic bytes rather than the content-type header or URL suffix, so mislabelled PDFs are kept and HTML masquerading as PDF is named in the log.
- **New `tavily` web provider (thanks @tavily-integrations).** `provider = "tavily"` in config plus `TAVILY_API_KEY`; optional install via `pip install "hyperresearch[tavily]"`. Ships with offline tests that stub the SDK.

### Lint

- **New lint rule `citation-style-preservation` (closes #33).** When `prompt-decomposition.json` (or a `wrapper_contract.json` override) declares `citation_style: "wikilink"`, the final report must contain at least one `[[<note-id>]]` wikilink that resolves to a vault note; for `"inline"`, at least one numbered `[N]` marker plus a Sources/References heading. Presence-only by design — it catches the polish/synthesis regression that strips every citation, without the false-positive tail a density floor would have on short or quote-heavy reports. Skips cleanly when the style is `"none"`, no decomposition exists, or the vault has no source notes.

### Release readiness and deployability

- **Version metadata is consistent again.** `hyperresearch.__version__` now tracks the version declared in `pyproject.toml`, fixing the state where the built wheel reported `0.8.6` while `hyperresearch --version` reported `0.8.5`.
- **CI installs the dependencies used by the tests.** The `dev` extra now includes `exa-py`, so the Exa provider tests pass under the same `pip install -e ".[dev]"` command CI runs. Without it, `main` fails 10 tests in `tests/test_web/test_exa_provider.py` with `ModuleNotFoundError: No module named 'exa_py'`.
- **Optional extras match CLI guidance.** Declared the `crawl4ai` and `watch` extras the CLI already directs users to install. `pip install hyperresearch[watch]` previously resolved to no extra and installed no `watchdog`, so `hpr watch` stayed broken while telling the user to run the command that had just failed.
- **Publish workflow now gates on lint and tests before building.** Tagged releases still publish via trusted PyPI publishing, but the publish job now fails before upload if ruff or pytest fails.
- **Packaging regression tests added.** The test suite now checks that runtime version metadata tracks `pyproject.toml` and that dev/install extras cover the tested optional provider surface.

## [0.8.6] - 2026-05-14

### Run-to-run safety: no more silent overwrites between /hyperresearch sessions

Three changes that close the remaining "I ran another hyperresearch and lost stuff" foot-guns, so you can fire off runs back-to-back without thinking about it.

- **sync no longer ingests frontmatterless scratch files (closes #25).** The depth-investigator and other agents leave plain-markdown body files under `research/temp/` after calling `note new --body-file`. Those scratch files derived the same id from their stem as the canonical notes created from them, and the UPSERT race smashed the canonical row's `path` field — silently breaking subsequent `note update --add-tag` calls. `compute_sync_plan` now peeks the first 16 bytes and skips anything that doesn't open with a YAML frontmatter delimiter. Real notes (including `graph stub` sidelined notes under `research/temp/`) always have frontmatter, so the fix is content-based and doesn't break that workflow. Belt-and-suspenders: `execute_sync` now refuses to UPSERT a note whose id is already owned by a different path, surfacing collisions to `result.errors` instead of overwriting.
- **`hyperresearch archive-run` preserves prior-run artifacts.** A second `/hyperresearch` in the same vault used to silently overwrite `research/scaffold.md`, `prompt-decomposition.json`, `loci.json`, `comparisons.md`, all 4 `critic-findings-*.json`, `patch-log.json`, `polish-log.json`, `readability-*.json`, `corpus-critic-gaps.json`, plus the entire `research/temp/` scratch tree. The new command moves all of that into `research/runs/archive-<prev-tag>-<UTC-timestamp>/` before the next run starts. Cheap no-op on a fresh vault. Wired into the entry-skill bootstrap as step 0.5, so users don't have to remember to call it.
- **`hyperresearch vault-tag <slug>` mints a collision-safe vault_tag.** The orchestrator's topical slug (e.g. `efield-dft-sac`) is no longer used as the final vault_tag — `hyperresearch vault-tag` appends a random 6-hex-char suffix verified unique against every prior run's `query-*.md` and `final_report_*.md` in the live vault. Re-running the same query produces a fresh tag, so prior final reports can never be overwritten. Two queries that happen to slug-collide on shared lexical material also get distinct tags. Legacy without-suffix tags from older runs can't collide with the new format by construction.

**Limitation worth knowing:** these three changes solve sequential runs comprehensively. Two `/hyperresearch` invocations that *overlap in time* still race on the new files they both write to flat paths (scaffold.md, loci.json, etc.). True parallel-run safety needs per-run files to live under `research/runs/<vault_tag>/`, which is a deeper refactor — flagged but deferred.

## [0.8.5] - 2026-04-29

### Reports self-title; wikilinks become the default citation system

Two related changes that fix the "I lost my last report" foot-gun and make the vault genuinely navigable:

- **Final reports now write to `research/notes/final_report_<vault_tag>.md`.** Every run self-titles by the canonical query slug (e.g., `final_report_rl-exploration.md`). No more overwrites — running `/hyperresearch` on a new topic in the same project leaves the previous report untouched. Persistent personal research wiki, no surprise data loss.
- **Wiki-link citations are the new default citation style.** Every citation in the body is `[[<source-note-id>]]` pointing at the source note in the vault. No separate `## Sources` section needed — each wiki-link self-resolves to the source note's frontmatter (title + URL). For users in their own vault this means every citation is one click away from the raw source. The `inline` (`[N]` + Sources section) and `none` styles are still selectable; the benchmark wrapper continues to set `"inline"` via `wrapper_contract.json` so RACE evaluators can read numbered references.
- **Polish auditor updated**: only strips wiki-links pointing at workspace artifacts (`[[interim-*]]`, `[[scaffold]]`, `[[comparisons]]`). Source-note wiki-links are preserved as the citation system when style is `"wikilink"`.
- **Lint rules updated**: `wrapper-report`, `patch-surgery`, and `instruction-coverage` rules glob for `final_report*.md` and validate the most recent. Pre-0.8.5 bare `final_report.md` still works.

## [0.8.4] - 2026-04-29

### Polish + release plumbing

- **README install section** now leads with the per-project path. `hyperresearch install --global` is documented as a power-user footnote with the honest tradeoff (~15 lines of system-reminder cost in every CC session). Per-project install keeps unrelated CC sessions clean.
- **Tightened install section** from 22 lines to 7 — single command, single usage line, single Python disclaimer.
- **Subagent roster table** corrected: `hyperresearch-fetcher` runs on Sonnet (not Haiku), `hyperresearch-draft-orchestrator` runs on Opus (not Sonnet).
- **CI**: `publish.yml` now triggers on git tag pushes (`v*`) and `workflow_dispatch` in addition to GitHub releases. Future versions auto-publish on `git push --tags`.

## [0.8.3] - 2026-04-29

### Quieter global install — step skills lazy-load per-project

Global install (`hyperresearch install --global`) used to write all 16 step skills to `~/.claude/skills/`, advertising them in the available-skills system reminder of every Claude Code session — ~3K tokens of noise on sessions where `/hyperresearch` is never used.

- **Global install now writes only the entry skill + agents to `~/.claude/`.** The 16 step skills (`hyperresearch-1-decompose` … `hyperresearch-16-readability-audit`) install per-project, lazily.
- **Entry skill bootstrap step 0** now also runs `hyperresearch install --steps-only .` if step skills aren't found in the project's `.claude/skills/`. First `/hyperresearch` invocation in a fresh project materializes the step skills there. Subsequent invocations no-op.
- **New `hyperresearch install --steps-only [PATH]`** flag — installs only the 16 step skills to `<path>/.claude/skills/`. Used by the bootstrap, also available manually.
- **Upgrade prune** — `hyperresearch install --global` removes any `hyperresearch-N-*` step-skill dirs left in `~/.claude/skills/` by 0.8.2-and-earlier global installs.

Net effect: sessions in projects that never use hyperresearch see only the entry skill + agent descriptions in their available-skills/agents lists. Step-skill noise is scoped to projects that actually use the tool.

## [0.8.2] - 2026-04-29

### Global install

- **`hyperresearch install --global`** writes the Claude Code skills + agents to `~/.claude/` so `/hyperresearch` is available in every Claude Code session anywhere on the machine, with no per-project setup. Skips vault init and CLAUDE.md injection (those happen automatically per-project on first `/hyperresearch` invocation).
- New `install_global_hooks()` in `core/hooks.py` that targets `~/.claude/` and skips the PreToolUse hook script (would otherwise fire on every Claude Code session).
- Entry skill bootstrap now auto-runs `hyperresearch init .` if no vault exists in cwd, so the global-install workflow is fully seamless: pip install + `hyperresearch install --global` once, then `/hyperresearch` works everywhere and materializes the vault + `research/` folder + `CLAUDE.md` in whatever project root you're in on first use.

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
