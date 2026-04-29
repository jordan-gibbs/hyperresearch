---
name: hyperresearch-2-width-sweep
description: >
  Step 2 of the hyperresearch V8 pipeline. Multi-perspective search planning
  (breadth / depth / adversarial lenses) followed by parallel fetcher waves.
  Achieves comprehensive topical coverage with 40-100 curated sources for
  standard/full tiers. Includes coverage check, evidence redundancy audit,
  and source count gating. Invoked via Skill tool from the entry skill
  after step 1 completes.
---

# Step 2 — Width sweep

**Tier gate:** Runs for ALL tiers. For `light` tier: skip academic APIs, target 12–20 sources, limit to 2–3 fetcher batches. For `standard` and `full`: run the full procedure below.

**Goal:** achieve comprehensive topical coverage — every atomic item from the decomposition must have at least 3 supporting sources by the end of this step. Target 40–80 curated sources for `full` tier.

---

## Recover state

Read these inputs:
- `research/scaffold.md` — vault_tag (in Run config), modality
- `research/prompt-decomposition.json` — atomic items, sub_questions, entities, pipeline_tier
- `research/temp/coverage-matrix.md` — verbatim query phrases mapped to atomic items
- `research/query-<vault_tag>.md` — canonical research query (GOSPEL)

---

## Step 2.1 — Multi-perspective search planning

Before spawning any fetchers, produce a **search plan** that maps the decomposition to concrete searches from **three independent perspectives**. This is the single highest-leverage step for comprehensiveness — an ad-hoc search finds 40 sources on the same 3 sub-topics; a multi-perspective planned search distributes sources across all atomic items from angles a single researcher would miss.

1. **Read the decomposition.** Extract every `sub_question` and every `entity` with its `required_fields`.

2. **Generate searches from three lenses.** For EACH atomic item, generate searches from all three perspectives:

   **Lens A — Breadth coverage (systematic):**
   - One search for the core factual content of that item
   - One search for recent developments / state-of-the-art (last 2 years)
   - One search for each named entity or sub-concept within the item
   - Goal: no atomic item left uncovered. Cast wide.

   **Lens B — Citation-chain depth (academic/canonical):**
   - Academic API queries (Semantic Scholar, arXiv, OpenAlex, PubMed) for each item with research literature
   - Searches targeting canonical/seminal works, foundational papers, authoritative reports
   - Searches for the upstream sources that derivative commentary cites ("original study", "primary data", "foundational paper")
   - Goal: find the load-bearing sources that secondary commentary is built on.

   **Lens C — Adversarial/contrarian (dialectical):**
   - "criticism of X", "limitations of X", "problems with X", "why X doesn't work" for each item
   - Searches for competing frameworks, alternative explanations, dissenting experts
   - Searches for failure cases, negative results, counter-examples
   - At least one "X is wrong" or "against X" search per major atomic item
   - Goal: ensure the corpus includes the strongest case AGAINST the emerging consensus.

   **Lens D — Period-pinned primary sources (MANDATORY when `time_periods` is non-empty in the decomposition):**
   - For EVERY entry in `prompt-decomposition.json -> time_periods`, generate at least one search that targets the **primary filing for that exact period** — not the most recent filing, not narrative commentary, not earnings-call summaries.
   - **SEC EDGAR (US public companies):** target the filing index for the named period. Example queries: `site:sec.gov 10-Q "period ended September 30, 2024" <company>` or `site:sec.gov/cgi-bin/browse-edgar <CIK> 10-Q dateb=20241231`. Open the EDGAR filing-history page directly when CIK is known.
   - **Companies House (UK):** target the filing-history view, NOT the search index. Example: `site:find-and-update.company-information.service.gov.uk <company> filing-history`. Then fetch the specific accounts PDF made up to the named period.
   - **Earnings releases / press releases:** target the dated press release for that period, not coverage of it. Example: `<company> "third quarter 2024" results press release`.
   - **Government / central-bank releases, regulatory disclosures, statutory accounts:** target the publication for the exact reporting period.
   - **Earnings-call transcripts are insufficient on their own.** Transcripts narrate already-rounded numbers ("revenue grew about 27%"); rubrics demand the tabular line items from the filing itself. If the prompt names a fiscal period, the search plan MUST include a query for the filing PDF, not just the transcript.
   - Goal: every period in `time_periods` has at least one search that, if successful, fetches the filing's tabular data — not a paraphrase of it.

3. **Write the combined search plan to `research/temp/search-plan.md`** — a table with a `Lens` column:
   ```markdown
   | Atomic item | Search query | Type | Lens | Target |
   |---|---|---|---|---|
   | Sub-Q1 | "China financial industry growth trends 2025" | web | breadth | factual |
   | Sub-Q1 | "China financial sector structural risks" | web | adversarial | contrarian |
   | Sub-Q1 | "financial repression China scholarly analysis" | academic | depth | canonical |
   | Entity: PE | "China private equity returns academic study" | academic | depth | canonical |
   ```

   Plan typically has **40–100 planned searches** for a `full` query.

4. **Search gap check.** Cross-check the search plan against `research/temp/coverage-matrix.md`. For every row in the coverage matrix, verify at least one search in the plan targets that query phrase's atomic item. Re-read the verbatim query and check: is there any significant topic, entity, or category in the query that has ZERO rows in the search plan?

   Common failure modes this catches:
   - Decomposition correctly listed "rugged tablets" but search plan has no queries for tablet manufacturers, enterprise mobility, or field-service devices
   - Query mentions "Southeast Asia" but all regional searches target only "North America" and "Japan/Korea"
   - Query says "SaaS applications" but every search is about "payment terminals"

   If gaps exist: add the missing searches to the plan NOW, before proceeding. Do NOT proceed to fetching with known search gaps — a missing search now becomes a missing section in step 10.

5. **Execute searches from ALL three lenses.** Do not shortcut by running only Lens A. The adversarial and depth lenses produce qualitatively different URLs that breadth searching misses.

6. **Minimum adversarial coverage:** at least **5 adversarial searches total**. The dialectic critic will punish one-sided coverage.

---

## Step 2.2 — Execute searches and build URL queue

1. **Academic APIs first.** For topics with a research literature, hit Semantic Scholar / arXiv / OpenAlex / PubMed BEFORE web search. Academic APIs return citation-ranked canonical papers.

2. **Web searches from the plan.** Execute ALL planned searches across all three lenses. Aim for **80–120 candidate URLs** before deduplication for `full` tier, 60–100 for `standard`.

3. **Build and deduplicate the master URL queue.** Remove exact-URL duplicates. Remove obvious junk domains. The deduplicated queue should have **60–100 URLs** for `full` tier, 50–80 for `standard`.

   **Wikipedia SOURCE HUB rule:** Include Wikipedia URLs in the queue — they're valuable for discovery — but treat them as SOURCE HUBS, not as citable sources. When a fetcher processes a Wikipedia article, it extracts the references/citations Wikipedia links to. Those primary sources go into Wave 2 (or the same wave if capacity permits). Wikipedia itself is NEVER cited in the final report.

4. **Partition the queue into non-overlapping batches.** Split the master queue into **10–12 batches** of **8–12 URLs each**. Each batch goes to exactly ONE fetcher. **Zero overlap.**

---

## Step 2.3 — Utility scoring and selection

**Tier gate:** SKIP for `light`. Run for `standard` and `full`.

Before batching URLs, score each candidate URL on six dimensions (0–3 each, max composite 18):

1. **Authority (0–3):** Primary data / government / academic (3) > institutional report (2) > quality journalism (1) > blog (0)
2. **Novelty (0–3):** Unique domain or perspective (3) > partially overlapping (1) > redundant (0)
3. **Stance diversity (0–3):** Adversarial / contrarian (3) > mixed-stance (2) > neutral (1) > same-stance majority (0)
4. **Coverage (0–3):** Targets uncovered atomic item (3) > thin item (2) > adequate item (1) > well-covered (0)
5. **Redundancy (0–3):** Likely novel content (3) > possibly overlapping (1) > almost certainly a rewrite (0)
6. **Freshness (0–3):** For temporal topics: last 12 months (3), 1–3 years (2), 3–5 years (1), older (0). For foundational topics: canonical/seminal (3), recent derivative (1).

**Selection rule:** Rank by composite utility score. Select the top N URLs (where N = batch capacity × batch count). Hard constraint: every atomic item must have ≥3 candidate URLs before low-utility URLs from well-covered items are included.

Write to `research/temp/scored-urls.md`.

---

## Step 2.4 — Parallel fetcher waves

**Wave 1 (main wave):** Spawn **10–12 fetcher subagents in ONE message** — true parallel execution. Each fetcher gets its own non-overlapping batch.

**Subagent type:** `hyperresearch-fetcher`

**Spawn template (use the standard 3-piece contract):**
```
subagent_type: hyperresearch-fetcher
prompt: |
  RESEARCH QUERY (verbatim, gospel):
  > {{paste contents of research/query-<vault_tag>.md}}

  QUERY FILE: research/query-<vault_tag>.md

  PIPELINE POSITION: You are step 2 (width-sweep fetcher) of the
  hyperresearch V8 pipeline. The orchestrator partitioned the URL queue into
  non-overlapping batches; you fetch ONLY the URLs in your batch. Do not
  search for additional URLs. After you return, the orchestrator runs a
  coverage check (step 2.5) and may dispatch wave 2 fetchers.

  YOUR INPUTS:
  - vault_tag: <vault_tag>
  - urls: [<batch URLs, exactly as assigned>]
  - batch_id: <number>
```

**CRITICAL: no token waste.** Each fetcher gets ONLY its batch. No fetcher searches for new URLs or duplicates another fetcher's work. If a fetcher finishes early, it's done.

**CRITICAL: never emit bare text while waiting.** In `-p` mode, a text-only response triggers `end_turn`.

**Use wait time to think.** While subagents are working, write evolving thoughts to `research/temp/orchestrator-notes.md`:
- What patterns are emerging from sources?
- What tensions or contradictions do you expect?
- What's the strongest thesis forming? What could overturn it?
- How will atomic items map to sections?
- What's the narrative arc?

Append a few lines with `Edit` or `Write` every 30-60 seconds. Productive thinking time AND keeps the turn alive.

**Vault count check** — once every 60 seconds max:
```bash
PYTHONIOENCODING=utf-8 $HPR search "" --tag <vault_tag> --json | python -c "import sys,json; d=json.load(sys.stdin); print(f'Notes in vault: {len(d.get(\"data\",{}).get(\"results\",[]))}')"
```

The wave is done when the vault note count is ≥80% of total URLs queued.

---

## Step 2.5 — Coverage check (MANDATORY)

After Wave 1 returns, run the coverage check before proceeding:

1. **List fetched sources:** `$HPR search "" --tag <vault_tag> --json` — count substantive (non-deprecated) notes.

2. **Map sources → atomic items.** For each atomic item in the decomposition, identify which fetched sources serve it. Mark each item as:
   - **Well-covered** (4+ relevant sources)
   - **Adequate** (2–3 sources)
   - **Thin** (1 source)
   - **Uncovered** (0 sources)

3. **Wave 2 fetch for gaps.** For every `thin` or `uncovered` item:
   - Run 2–3 targeted searches specifically for that item
   - Spawn 3–5 fetchers with gap-filling URLs (non-overlapping batches)
   - This wave is smaller (typically 20–40 URLs) but surgically targeted

4. **Write coverage report** to `research/temp/coverage-gaps.md`:
   - List every atomic item with its coverage status and source count
   - Any item still at 0 sources after Wave 2 is a genuine gap — flag it prominently

**Do NOT skip the coverage check.** Comprehensiveness scores directly with how many atomic items have multi-source coverage.

---

## Step 2.6 — Evidence redundancy audit

**Tier gate:** SKIP for `light`. Run for `standard` and `full`.

**Goal:** detect when N sources are really 1 source in N outfits.

1. **Collect all claims.** Read `research/temp/claims-<note-id>.json` for every non-deprecated note tagged `<vault_tag>`. If no claim files exist, skip this step.

2. **Cluster by content overlap.** Sources sharing >60% of their `quoted_support` passages are likely derivative.

3. **Cluster by citation ancestry.** Use `suggested-by` links in the vault graph.

4. **For each cluster, identify the canonical upstream source.** Tag derivative sources with `derivative-of`. Do NOT deprecate them — discount them in coverage counting.

5. **Write `research/temp/redundancy-audit.md`** — clusters, adjusted coverage counts, atomic items dropping below 2 → flag for Wave 3.

6. **Wave 3 fetch (conditional).** If any atomic item's independent source count drops below 2, run targeted searches for INDEPENDENT sources. Spawn 2-3 fetchers.

---

## Source count targets

| Tier | Minimum sources | Target sources | Fetchers per wave | Waves |
|------|----------------|---------------|-------------------|-------|
| `light` | 10 | 15–25 | 3–5 | 1–2 |
| `standard` | 30 | 40–70 | 8–10 | 2 |
| `full` | 45 | 55–80 | 8–12 | 2–3 |

Substantive (non-deprecated) note counts. Quality over quantity — reference reports average ~65 sources. Beyond ~80, each additional source yields diminishing returns while degrading summarizer quality.

---

## Long-source delegation (any time during step 2)

When a single long source (>5000 words) is load-bearing, delegate end-to-end analysis to `hyperresearch-source-analyst` (Sonnet, 1M context):

Trigger conditions (ALL three must hold):
1. **Length:** source's `word_count` (visible on `$HPR note show <id> -j`) exceeds ~5000 words
2. **Relevance:** source is relevant to the research_query
3. **No existing analysis:** no `type: source-analysis` note already exists for this source

**Cap: at most 6 source-analysts per query.**

Spawn template:
```
subagent_type: hyperresearch-source-analyst
prompt: |
  RESEARCH QUERY (verbatim, gospel):
  > {{paste research/query-<vault_tag>.md body}}

  QUERY FILE: research/query-<vault_tag>.md

  PIPELINE POSITION: You are a leaf subagent for deep end-to-end analysis
  of ONE long source. Your digest feeds downstream hyperresearch V8 steps. You
  do NOT spawn other subagents.

  YOUR INPUTS:
  - source_note_id: <vault note id of the long source>
  - output_path: research/temp/source-analysis-<source_note_id>.md
  - vault_tag: <vault_tag>
```

---

## Exit criterion

- Minimum source count met (per tier table)
- Coverage check shows no `uncovered` atomic items (thin is acceptable)
- `research/temp/coverage-gaps.md` written
- (For std/full): `research/temp/redundancy-audit.md` written if any claim files existed

If you fall short after two waves, proceed anyway but ensure `coverage-gaps.md` lists what's missing so the drafter handles it.

---

## Next step

Return to the entry skill (`hyperresearch`). Tier-based routing:

- **light tier:** Skip directly to step 10 — invoke `Skill(skill: "hyperresearch-10-triple-draft")` (light tier writes a single draft, not the ensemble)
- **standard / full tier:** Invoke `Skill(skill: "hyperresearch-3-contradiction-graph")`
