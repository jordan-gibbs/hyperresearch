# Codex bench harness

Runs [DeepResearch-Bench](https://github.com/Ayanami0730/deep_research_bench) queries through hyperresearch on the OpenAI Codex CLI and writes RACE-compatible JSONL (`id`, `prompt`, `article`). It is the Codex counterpart of `bench/harness.py`, and it also measures whether Codex actually ran the pipeline: an April 2026 attempt answered every query inline and wrote zero vault notes.

## What one query does

1. Creates `codex_bench/runs/query_<id>/`, runs `git init` and `hyperresearch init`, then `hyperresearch install . --target codex --json`. That writes the vault, `AGENTS.md`, `.agents/skills/hyperresearch/`, the step files under `.hyperresearch/codex/steps/`, the custom agents under `.codex/agents/`, and the Stop hook in `.codex/hooks.json`. The harness writes none of these itself. It copies this repo's `.hyperresearch/config.toml` into the run vault and renders at its gear, the same way the Claude bench does.
2. Writes `research/prompt.txt` (the verbatim query, which the pipeline treats as gospel) and `research/wrapper_contract.json` (inline `[N]` citations plus the Opinionated Synthesis sections).
3. Checks what Codex will see with `codex debug prompt-input`, which calls no model: whether the skill is listed and under what name, whether `AGENTS.md` loaded, and whether network access is on.
4. Runs `codex exec`. The prompt goes in on stdin, starting with `$hyperresearch <query>`, and the JSONL event stream goes to `run.log`.
5. Reads the report from `research/notes/final_report_<vault_tag>.md` and records adherence metrics in `result.json`.

## Prerequisites

- Codex CLI, installed and logged in (`codex --version`, `codex login`). Tested against codex-cli 0.155.1.
- hyperresearch with `install --target codex`. The harness uses the repo's `.venv` if it exists and puts that directory first on `PATH` for the Codex session.
- The query file: `python codex_bench/harness.py --download-only`.

## Sandbox and network

`codex exec` defaults to a read-only sandbox with no network. That is what killed the April run: every `hyperresearch` call came back "rejected: blocked by policy". The harness passes:

```
--sandbox workspace-write -c sandbox_workspace_write.network_access=true
```

It also adds `~/.crawl4ai` as a writable root when that directory exists (turn this off with `--no-auto-add-dirs`), and passes `--dangerously-bypass-hook-trust` so the project Stop hook (`hyperresearch run stop-gate`) runs in a run dir Codex has never seen (turn this off with `--no-hook-trust`). If sandboxed fetches still fail with permission errors, `--yolo` switches to `--dangerously-bypass-approvals-and-sandbox`. Use it only for these throwaway run dirs. Nothing here writes to `~/.codex/config.toml`.

Skill naming: Codex prefixes project skills with the name of the nearest ancestor `.codex-plugin/plugin.json`. This repo has one, so a run dir under `codex_bench/runs/` lists the skill as `hyperresearch:hyperresearch`. The harness reads the listed name from the pre-flight check and puts that name in the prompt. The prompt also tells Codex to read `.agents/skills/hyperresearch/SKILL.md` directly if the skill did not load.

## Examples

```bash
python codex_bench/harness.py --query-id 52 --dry-run      # set up, check, print the codex command
python codex_bench/harness.py --query-id 52                # one query, Codex's default model
python codex_bench/harness.py --query-id 52 --query-id 61 -m gpt-5.5 --reasoning-effort high
python codex_bench/harness.py --limit 5 --only-en --resume # first 5 English ids without a result yet
python codex_bench/harness.py --summary                    # adherence table over all runs
python codex_bench/harness.py --export                     # results/hyperresearch-codex-<model>.jsonl
```

Other options: `--timeout` (seconds per query, default 3h; light-tier queries finish well inside it), `--web-search live|cached|disabled`, `--gear`, `--add-dir`, `--ephemeral`, `-c key=value` (passed through to `codex exec`), and `--verbose`.

The old `--evaluate` flag is gone. It called `bench/evaluate.py`, which grades `bench/runs/` and never saw these results. Run `--export` and give the JSONL to the DeepResearch-Bench RACE evaluator. Forcing a tier is not supported either, because step 1 classifies the tier and nothing overrides it.

## result.json

- `article`: the report with any YAML frontmatter removed. It is exported only when `error` is null.
- `error_code`:
  - `PIPELINE_SKIPPED`: zero vault notes and no run manifest. Codex answered inline or did nothing. This is the April failure.
  - `NO_REPORT`: the pipeline started but no `final_report_*.md` was written.
  - `TIMEOUT`, `CODEX_ERROR` (non-zero exit), `SETUP_FAILED`, `CODEX_NOT_FOUND`.
- `adherence`:
  - `notes`: `.md` files in `research/notes/` other than the report. This is roughly the number of sources fetched.
  - `manifest`, `vault_tag`, `run_status`, `blocked_on`, `profile`, `tier`: read from `research/runs/<tag>/run.json` and `prompt-decomposition.json`.
  - `steps_done`, `steps_skipped`, `steps_failed`, `steps_not_done`: step status from the manifest, compared with the profile's step list. Codex records a step only when it runs `hyperresearch run step`.
  - `manifest_counters`: the manifest's source, note, and agent counters. The dollar estimate is dropped.
  - `verify`: the result of `hyperresearch run verify <tag> -j`, as passed or failed plus the names of the failed checks.
  - `escalations_queued`: blocked fetches still in the queue. Codex has no browser lane, so these stay queued.
- `events`: counts from the event stream. They cover turns, shell commands, `hyperresearch` calls, `fetch` calls, `run step` calls, web searches, file changes, subagent spawns, and sandbox rejections, plus token totals. A spawn is any event item whose type or tool name contains "spawn".
- `probe`: the pre-flight check from step 3 above.
