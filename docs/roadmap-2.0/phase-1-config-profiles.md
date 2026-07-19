# Phase 1 — Config extraction + pipeline profiles

## Goal

Every number that governs behavior lives in config, and every number that governs *research scale* lives in a named **pipeline profile**. The 17 skills and 15 agent prompts become Jinja templates rendered from a profile at install time, so "scale up" is a profile edit, not a 30-file prose rewrite. Ship `light` and `full` profiles that reproduce today's exact behavior; later phases add `dissertation`.

## Non-goals

No new pipeline capabilities, no schema changes (Phase 2), no per-run workspaces (Phase 3). Rendered output under the default `full` profile must be semantically identical to today's skills/agents.

## Current state (audit anchors, v0.8.7)

**Python-layer hardcoded values (representative — full inventory below):**

| Anchor | Value | Meaning |
|---|---|---|
| `web/crawl4ai_provider.py:119` | `timeout=30, verify=False` | PDF download timeout + **silent TLS-verification disable** |
| `web/crawl4ai_provider.py:143` | `< 100` bytes | min valid PDF size |
| `web/crawl4ai_provider.py:244` | `page_timeout=30000` | crawl page timeout |
| `web/crawl4ai_provider.py:220-235` | 2000ms initial / 500ms poll / 2 stable / 16 checks | smart-wait DOM-stability loop |
| `web/base.py:95` | `< 300` chars | empty-content junk gate |
| `web/base.py:131` + `crawl4ai_provider.py:65` | ratio `> 0.05` | binary-garbage threshold |
| `web/base.py:135` | `< 1500` chars | cookie-wall gate |
| `web/base.py:71-73` | `< 1000` chars + keyword | login-wall gate |
| `web/base.py:60-63,99-141` | inline keyword tuples | login/cloudflare/error/cookie signal lists |
| `cli/fetch.py:19,21` | `MAX_IMAGES=5`, `MIN_IMAGE_BYTES=50_000` | asset caps |
| `core/fetcher.py:42-45` | domain list | visible-browser (auth-aggressive) domains |
| `core/similarity.py:12,29,51` | shingle n=3, num_perm=128, bands=16 | MinHash/LSH params |
| `cli/dedup.py:17` | `LSH_THRESHOLD=200` | brute↔LSH switchover |
| `cli/lint.py:917,975,1556` | 150 words, //3 ratio, 90 days | extract-coverage + stale-review thresholds |
| `cli/search.py:30,32` | limit 20, 4 chars/token | search defaults |
| `core/enrich.py:41,69` | 5 tags, 120-char summary | enrich caps |

**Skill/agent-prose hardcoded parameters (the scale knobs — full inventory from the 2026-07-19 skills audit):**

- Tier routing: light = steps 1→2→10→15→16; full = all 16 (router skill).
- Source gates: light min 10 / target 15–25; full min 45 / target 55–80; "beyond ~80 diminishing returns" ceiling rationale (width-sweep ~line 227).
- Fan-out: 40–100 planned searches; 80–120 candidate URLs; 60–100 deduped; 10–12 batches × 8–12 URLs; Wave 1 = 10–12 fetchers; Wave 2 = 3–5; Wave 3 = 2–3; ≥5 adversarial searches; 80%-of-queue wave-done threshold; ≤1 vault check/min.
- Utility scoring: 6 dims × 0–3, max 18; ≥3 candidate URLs per atomic item floor.
- Source-analyst: >5000-word trigger, cap 6 per query.
- Loci: 2 analysts; clamp 6; 4 scoring dims × 0–10; total depth budget 40; brackets 30–40→≤15, 20–29→≤10, 10–19→≤5, <10→0–3.
- Depth: K ≤ 6 investigators; default budget 10; >50% failure abort.
- Tensions: comparisons 3–5; source-tensions 3–7 from top 8–12 full-body reads (15–20 surveyed).
- Corpus critic: 3–8 gaps; 2–4 fill fetchers. Evidence digest: 80–120 claims cap, 30 min. Gap-fetch: cap 5.
- Drafting: exactly 3 drafts; must-read 20–50 (argumentative 35–50 / structured 25–40 / short 20–30); word targets 500–2000 / 2000–5000 / 5000–10000; citation density ≥2 per 1000 chars; synthesizer totals 80–150 / 40–80 / 15–30 citations.
- Critics: finding caps 12 / 12 / 10 / 15; readability recommender cap 50; polish thresholds (50-word sentences, 200-word paragraphs).
- Model map (frozen per agent): sonnet = fetcher, source-analyst, loci-analyst, depth-investigator, corpus-critic; opus = everything else.

## Workstreams

### WS1 — Python settings extraction (M)

**Design.** Extend `VaultConfig` (`core/config.py`) with new dataclass sections; all defaults equal to today's literals so absent config keys change nothing.

```toml
[fetch]
page_timeout_ms = 30000
pdf_timeout_s = 30
pdf_verify_tls = true          # NEW default: flips the current silent verify=False to secure-by-default; document the change
min_pdf_bytes = 100
wait_initial_ms = 2000
poll_interval_ms = 500
stable_checks = 2
max_checks = 16
visible_browser_domains = ["linkedin.com", "twitter.com", "x.com", "facebook.com", "instagram.com", "tiktok.com"]
image_timeout_s = 15

[junk]
min_content_chars = 300
login_wall_max_chars = 1000
cookie_wall_max_chars = 1500
binary_garbage_ratio = 0.05
sample_window = 2000
extra_login_signals = []       # appended to built-in lists, not replacing them
extra_junk_domains = []

[assets]
max_images = 5
min_image_bytes = 50000

[dedup]
shingle_size = 3
minhash_perm = 128
lsh_bands = 16
lsh_switchover = 200
default_threshold = 0.6

[lint]
extract_min_words = 150
extract_coverage_divisor = 3
stale_review_days = 90

[search]  # existing section gains:
default_limit = 20
chars_per_token = 4
snippet_len = 200
```

**Changes.** Thread config through call sites (fetch providers get a config object at `get_provider()` time; lint rules read `vault.config`). Signal keyword lists stay as code constants but gain `extra_*` config extension points — replacing them wholesale is a footgun. **Note the one intentional behavior change:** `pdf_verify_tls` defaults to `true`, fixing the silent `verify=False` at `crawl4ai_provider.py:119`; users hitting cert-broken mirrors set it to `false` explicitly. CHANGELOG this.

### WS2 — Pipeline profile schema (M)

**Design.** Profiles live in `.hyperresearch/config.toml` under `[profile.<name>]`, with built-in `light` and `full` defined in code (overridable). A profile is a flat parameter set + a model map:

```toml
[profile.full]                    # shipped defaults == today's prose values
steps = [1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16]
source_min = 45
source_target_low = 55
source_target_high = 80
planned_searches = [40, 100]
candidate_urls = [80, 120]
batch_size = [8, 12]
wave1_fetchers = [10, 12]
wave2_fetchers = [3, 5]
adversarial_searches_min = 5
utility_scoring = true
source_analyst_cap = 6
source_analyst_word_trigger = 5000
loci_analysts = 2
loci_max = 6
depth_budget_total = 40
depth_budget_brackets = [[30, 15], [20, 10], [10, 5], [0, 3]]
investigator_max = 6
comparisons_tensions = [3, 5]
source_tensions = [3, 7]
tension_full_reads = [8, 12]
corpus_critic_gaps = [3, 8]
claims_cap = [80, 120]
claims_min = 30
draft_count = 3
must_read = { argumentative = [35, 50], structured = [25, 40], short = [20, 30] }
word_targets = { short = [500, 2000], structured = [2000, 5000], argumentative = [5000, 10000] }
citation_density_min = 2.0        # per 1000 chars
critic_finding_caps = { dialectic = 12, depth = 12, width = 10, instruction = 15 }
gap_fetch_cap = 5
readability_rec_cap = 50
vault_check_interval_s = 60
wave_done_ratio = 0.8

[profile.full.models]
fetcher = "sonnet"
source_analyst = "sonnet"
loci_analyst = "sonnet"
depth_investigator = "sonnet"
corpus_critic = "sonnet"
draft_orchestrator = "opus"
synthesizer = "opus"
critics = "opus"
patcher = "opus"
polish_auditor = "opus"
readability_recommender = "opus"
```

`[profile.light]` mirrors today's light tier (steps `[1,2,10,15,16]`, source_min 10, target 15–25, wave1_fetchers [3,5], utility_scoring false, etc.). A `hpr profile show <name> -j` command prints the resolved profile for agents to read.

**Loader.** `core/profiles.py`: built-in dicts + TOML overlay + validation (pydantic model; ranges as 2-lists; unknown keys warn). `hpr profile list/show/validate`.

### WS3 — Prompt templating + render pipeline (L)

**Design.** Skills and agent `.md` files (post-Phase-0 they're package data) become Jinja2 templates (`jinja2` is already a dependency). Literals become variables: `"Target {{ p.source_target_low }}–{{ p.source_target_high }} curated sources"`, `"spawn {{ p.wave1_fetchers[0] }}–{{ p.wave1_fetchers[1] }} fetcher subagents in ONE message"`. Model frontmatter in agent files renders from the profile's model map.

**Render points.**
- `hyperresearch install [--profile NAME]` renders templates → `.claude/skills/` + `.claude/agents/` (default profile: `full` — matching today's install output).
- Rendered files carry a header comment: `<!-- rendered from profile "full" (hyperresearch 2.0.0) — edit the profile, not this file -->`.
- Step 1's tier classifier maps tier → profile name; the router reads the resolved profile via `hpr profile show` rather than a prose table. Tier switching at run time = both profiles' skills are pre-rendered; the router table itself becomes generated.

**Drift prevention.**
- Test: render `full`, diff against a checked-in golden copy of the 1.x prose values → any numeric drift is a deliberate golden update.
- Test: grep templates for bare load-bearing numbers that should be variables (maintain an allowlist for genuinely fixed numbers like "step 14").
- Keep templates readable: only *scale* parameters templated; procedural prose stays literal.

### WS4 — Tier/profile plumbing (S)

- Step-1 decompose skill writes `pipeline_profile` (not just `pipeline_tier`) into `research/prompt-decomposition.json`; downstream steps read parameters from `hpr profile show <name> -j` when they need a number at run time (e.g., gap caps), rather than trusting possibly-stale rendered prose.
- Router's tier table and time/cost estimates render from profiles.
- `wrapper_contract.json` gains an optional `profile` override so harnesses (bench) can pin one.

## Dependencies

Phase 0 (WS1/WS2 there must land first — templates are edited as package-data markdown).

## Acceptance criteria

- [ ] All Python-layer values from the WS1 table read from config; defaults reproduce current behavior; `pdf_verify_tls` change CHANGELOG'd.
- [ ] `hpr profile list/show/validate` work; built-in `light`/`full` resolve; user overlay merges.
- [ ] `hyperresearch install` renders templates; rendered `full` output is semantically identical to 1.x skills/agents (golden-diff test).
- [ ] No load-bearing magic numbers remain in templates (grep test with allowlist).
- [ ] A custom profile with `source_min = 200` renders skills that say 200 — end-to-end template test.
- [ ] Full test suite green.

## Risks & mitigations

- **Template rot** — prose edited without noticing it's a template. Mitigation: render header comment + golden tests + CONTRIBUTING note.
- **Prompt quality regression from mechanical substitution** — a range variable can read awkwardly mid-sentence. Mitigation: hand-review every substitution site once; the golden diff makes review tractable.
- **Config sprawl** — 40+ new keys. Mitigation: everything defaults; `config show` groups by section; docs list only the 6–8 keys users realistically touch.
- **Run-time vs render-time skew** — an installed render from profile A while decomposition says profile B. Mitigation: router asserts rendered-profile header matches `pipeline_profile`, re-runs `install --profile` if not (install is idempotent and fast).

## Effort

| WS | Size |
|---|---|
| WS1 settings extraction | M |
| WS2 profile schema | M |
| WS3 templating | L |
| WS4 plumbing | S |
