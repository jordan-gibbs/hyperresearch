# Phase 0 — Cleanup: clear the debt before building on it

## Goal

Remove the structural debt that makes every later phase harder: prompt text trapped in a 3,495-line Python module, stale V7 vocabulary in 11 of 14 agent prompts, three parallel fetch implementations with a core→cli layering inversion, and confirmed dead code. After Phase 0, prompts are diffable markdown, there is exactly one fetch engine, and the tree contains nothing that lies about the current architecture.

## Non-goals

No behavior changes to the pipeline, no new features, no config work (that's Phase 1). A run before and after Phase 0 should produce equivalent output. The human-facing PKM surface (`serve/`, `indexgen/`, `topic`, `template`, `git`, `watch`, `link`, `dedup`) is *not* deleted — see WS6 for the packaging decision.

## Current state (audit anchors, v0.8.7)

- `core/hooks.py` is 3,495 lines; ~83% (lines ~53–2953) is 15 triple-quoted agent-prompt string constants plus `HOOK_SCRIPT_TEMPLATE` (`hooks.py:2911`); only ~540 lines (2954–3495) are install logic.
- 11 of 14 agent prompts describe the retired V7 "7-phase / Layer N" pipeline: loci-analyst (`hooks.py:76`), depth-investigator (`:283`), dialectic-critic (`:549`), depth-critic (`:672`), width-critic (`:775`), instruction-critic (`:936`), patcher (`:1219`), polish-auditor (`:1390`), source-analyst (`:2408`), fetcher (`:2561`), corpus-critic (`:2819`). Only draft-orchestrator (`:1705`), synthesizer (`:1889`), and readability-reformatter (`:2196`) speak V8 "step N". The roster comment (`:2957-2962`) and lint rule descriptions (`cli/lint.py:26-27,750,753`) also carry Layer language.
- Three fetch implementations: `cli/fetch.py:205-611` (the feature-complete one: tier/content-type detection, `--suggested-by` breadcrumbs, idempotent dup handling), `core/fetcher.py` (`fetch_and_save`, used only by `mcp/server.py:291-298`), `cli/research.py:_save_result`. Layering inversion at `core/fetcher.py:148` (`from hyperresearch.cli.fetch import _save_assets`).
- Triplicated visible-browser domain list: `core/fetcher.py:42-45`, `cli/fetch.py:293-296`, `cli/fetch_batch.py:58-61`. Duplicated smart-wait JS: `web/crawl4ai_provider.py:220-235` vs `:308-320`. Duplicated garbage-ratio threshold: `web/base.py:131` vs `web/crawl4ai_provider.py:65` (the comment at `:62-64` warns about exactly this drift).
- Confirmed dead: `embeddings` table (`core/db.py:88-94`, zero readers/writers), `models/graph.py` (21 lines) and `models/search.py` (24 lines) with zero import sites, empty stub packages `graph/` and `export/`.
- `cli/research.py` (313 lines) is superseded by the skill pipeline and only functions with exa/tavily (crawl4ai raises `NotImplementedError` for `search()`, `crawl4ai_provider.py:469`).
- `core/enrich.py` heuristics compete with agent curation; `core/fetcher.py:115` itself comments that curation "is the agent's job." Callers: `cli/fetch_batch.py:168`, `cli/research.py:271`, `mcp/server.py:343`, `cli/repair.py:91`.
- Width-sweep skill states the full-tier source target three inconsistent ways: "40–100" (frontmatter description), "40–80" (goal, ~line 17), "55–80" (table, ~line 222).
- Legacy `layercake-*` migration cruft: `hooks.py:3319` (`research-layercake` in retired dirs), `:3333-3480` (`_prune_retired_agents` + legacy dir cleanup).

## Workstreams

### WS1 — Extract prompts from `hooks.py` to package data (L)

**Design.** Agent prompts become `.md` files with YAML frontmatter (they are already written in that shape inside the strings), shipped as package data next to the existing 17 skills. New layout:

```
src/hyperresearch/skills/          # existing: 17 skill .md files + .hyperresearch/hook.js
src/hyperresearch/agents/          # new: 15 agent .md files (loci-analyst.md, fetcher.md, ...)
```

**Changes.**
- Move each `*_AGENT` constant's content verbatim (minus V7 fixes from WS2) into `src/hyperresearch/agents/hyperresearch-<name>.md`.
- Add a loader mirroring `_read_skill_source` (`hooks.py:~3437`): `importlib.resources` first, source-tree fallback. Reuse, don't fork — factor a shared `_read_package_md(package, name)`.
- `install_hooks` / `install_global_hooks` / `_install_*_agent` helpers read files instead of constants. `hooks.py` shrinks to install logic only (~500 lines).
- `hook.js` already ships as package data (`skills/.hyperresearch/hook.js`) — keep; delete the redundant `HOOK_SCRIPT_TEMPLATE` constant if it duplicates the file, or make the file the single source.
- Update `pyproject.toml` hatch wheel config if needed so `agents/` package data ships (packages are included via `packages = ["src/hyperresearch"]`; verify with a wheel-content test — there is precedent in the 0.8.7 packaging regression tests).

**Migration.** None for users — `hyperresearch install` output is byte-identical (modulo WS2 text fixes).

### WS2 — V7 → V8 vocabulary unification (M)

**Design.** One vocabulary: "step N of the 16-step V8 pipeline." The Layer→step mapping for rewriting: Layer 1 → step 2 (width sweep), Layer 2 → step 4 (loci), Layer 3 → step 5 (depth), Layer 3.5 → step 6 (reconcile), Layer 3.7 → step 8 (corpus critic), Layer 4 → steps 10–11 (draft/synthesize), Layer 5 → step 12 (critics), Layer 6 → step 14 (patcher), Layer 7 → step 15 (polish).

**Changes.**
- Rewrite the pipeline-position paragraphs in the 11 stale agent files (post-WS1 they are markdown — do WS1 first, then WS2 edits the .md files).
- Keep each agent's *description* frontmatter in sync — the `.claude/agents/` descriptions surface in Claude Code's agent list and several still say "Layer N" (e.g. corpus-critic says "Layer 3.7").
- Fix lint rule descriptions: `cli/lint.py:26-27` ("Layer 2 … Layer 6"), `:750,753` ("Layer 1 width sweep", "Layer 3 depth investigators").
- Fix roster comment `hooks.py:2957-2962` ("as of v7") and install labels (`:3291,:3302`).
- Add a regression test: grep the shipped skills + agents package data for `Layer \d|7-phase|layercake` → must be zero matches (allowlist the migration-pruning code itself).

### WS3 — One fetch engine (L)

**Design.** `core/fetcher.py` becomes the single engine; `cli/fetch.py` and `mcp/server.py` become thin callers. The cli implementation is the feature superset, so consolidation direction is: port cli features *into* core, then delete the cli duplicate.

**Changes.**
- Move into `core/fetcher.py`: tier/content-type auto-detection (`cli/fetch.py:85-201` `_detect_tier`/`_detect_content_type`), `--suggested-by` breadcrumb prepend + idempotent duplicate handling, the `INSERT OR IGNORE` race guard, and `_save_assets` (currently `cli/fetch.py:508`, imported backwards at `core/fetcher.py:148`). Assets code moves to `core/assets.py` or into `core/fetcher.py`; core must import nothing from `cli`.
- `fetch_and_save()` signature grows the cli-only options (suggested_by, save_assets, tags, tier/content_type overrides). `cli/fetch.py` keeps CLI parsing + output rendering only.
- `cli/fetch_batch.py` calls the same engine per URL with one deferred sync at the end (preserve its single-batched-sync behavior).
- Single `AUTH_AGGRESSIVE_DOMAINS` constant in `core/fetcher.py` (until Phase 1 makes it config); the other two copies import it.
- Extract the smart-wait JS into one module-level constant in `crawl4ai_provider.py` used by both `_make_run_config` and `_fetch_visible`.
- Single junk threshold: `crawl4ai_provider.py:65` imports the ratio-check helper from `web/base.py` instead of re-hardcoding `0.05` (the shared `binary_garbage_ratio` function already exists — share the *threshold comparison* too, e.g. `is_binary_garbage(sample)`).
- Tests: existing `tests/` fetch tests must pass unchanged; add one test asserting `core` has no `cli` imports (walk `core/*.py` ASTs).

### WS4 — Dead code removal (S)

**Changes.**
- Delete `models/graph.py`, `models/search.py`, and the empty `graph/`, `export/` packages (real functionality lives in `cli/graph.py`, `cli/export.py` — untouched).
- **Keep** the `embeddings` table (`core/db.py:88-94`) — Phase 2 WS6 revives it. Add a comment: `-- dormant; populated by Phase 2 semantic search (docs/roadmap-2.0/phase-2-source-ranking.md)`.
- Retire `cli/research.py`: remove the command registration from `cli/__init__.py`, delete the module, note in CHANGELOG ("`hyperresearch research` retired; use `/hyperresearch`"). Its unique helper `_extract_links_from_results` dies with it.
- Demote `core/enrich.py` to repair-only: drop calls from `cli/fetch_batch.py:168` and `mcp/server.py:343`; keep the `cli/repair.py:91` call (repair is the "fix a neglected vault" path where heuristics beat nothing). Update the MCP `create_note` docstring accordingly.

### WS5 — Consistency fixes (S)

**Changes.**
- Width-sweep skill (`src/hyperresearch/skills/hyperresearch-2-width-sweep.md` + installed copy): one source-target statement. Pick the table values (min 45 / target 55–80) as canonical; header and goal line reference them. (Phase 1 turns these into template variables; this WS just stops the file disagreeing with itself.)
- Sunset `layercake-*` pruning (`hooks.py:3319,3333-3480`): v0.8.x installs have had two-plus release cycles to migrate. Keep `_prune_retired_agents` (it serves the current roster) but drop the layercake-specific dir list, or gate it behind a `--prune-legacy` flag. Note in CHANGELOG that pre-0.8.0 installs should run 0.8.7's installer once before upgrading.

### WS6 — PKM surface packaging decision (S, decision + docs only)

**Design.** `serve/` (717 lines), `indexgen/` (256), `topic`, `template`, `git`, `watch`, `link`, `dedup` are never used by the pipeline but are legitimate human-vault features. Decision: keep them in-tree, but document the boundary — add a "pipeline-critical vs. vault-convenience" module map to `CONTRIBUTING.md` so contributors know what the agent path depends on. Revisit extras-group split (`pip install hyperresearch[pkm]`) only if install size becomes a complaint; a code split now would churn imports for little gain.

## Dependencies

None — Phase 0 is the root of the graph. WS2 depends on WS1 (edit prompts as markdown, not as Python strings).

## Acceptance criteria

- [ ] `core/hooks.py` < 600 lines; all agent prompts exist as `.md` package data; `pip install` + `hyperresearch install` produces the same `.claude/` tree as before (diff-tested).
- [ ] Zero matches for `Layer \d|7-phase|layercake` in shipped skills/agents (regression test in CI).
- [ ] Exactly one fetch implementation; `core/` imports nothing from `cli/` (AST test); MCP `fetch_url` and CLI `fetch` both route through `core/fetcher.py`; full test suite green.
- [ ] `models/graph.py`, `models/search.py`, `graph/`, `export/` gone; `cli/research.py` retired; `enrich` called only from `repair`.
- [ ] Width-sweep skill states the source target once.
- [ ] CHANGELOG entries for the retirements.

## Risks & mitigations

- **Prompt-extraction transcription errors** — a dropped line in a 200-line prompt silently degrades an agent. Mitigation: extraction is mechanical (script it: write each constant to file, then assert file content == constant before deleting the constant).
- **Fetch consolidation regressions** — cli fetch has subtle behaviors (idempotent re-fetch appends breadcrumbs, orphan cleanup). Mitigation: write characterization tests against current `cli/fetch.py` behavior *before* moving code.
- **`hyperresearch install` diff churn** for existing users — WS2 rewrites agent text, so installed agents change on upgrade. That's intended; call it out in CHANGELOG.

## Effort

| WS | Size |
|---|---|
| WS1 prompt extraction | L |
| WS2 vocabulary | M |
| WS3 fetch engine | L |
| WS4 dead code | S |
| WS5 consistency | S |
| WS6 packaging decision | S |
