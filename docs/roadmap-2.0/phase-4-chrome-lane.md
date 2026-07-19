# Phase 4 — The Chrome lane: hard-target fetching via Claude in Chrome

## Goal

Sources that headless crawling cannot reach — login-gated, bot-walled, interactive, viewer-rendered — stop being silently lost. A blocked URL escalates to a lane that drives the user's **real Chrome browser with their real logged-in sessions** (via Claude-in-Chrome MCP tools), with a human-in-the-loop checkpoint for the challenges only a human should complete. Chrome becomes the key-master; headless crawl4ai stays the high-throughput workhorse.

## Non-goals / scope boundary

**No automated CAPTCHA solving and no bot-detection defeat.** When the lane hits a CAPTCHA, 2FA prompt, or login it cannot legitimately pass, it pauses and hands off to the human — it does not attempt to solve, spoof, or evade. This is a hard scope boundary, not a deferred feature. Also out of scope: any credential storage by hyperresearch (sessions live in the user's browser profile, where they already are), and paywall circumvention (the lane fetches what the user's own subscriptions can see).

## Current state (audit anchors, v0.8.7)

- Detection already exists, recovery doesn't: `looks_like_login_wall` / `looks_like_junk` (`web/base.py:60-143`) correctly identify blocked fetches — and then the URL is **discarded**. At dissertation scale that's dozens of silently lost sources per run.
- The visible-browser fallback (`crawl4ai_provider.py` `_fetch_visible`) and crawl4ai profiles (`~/.crawl4ai/profiles/<name>`) exist, but they are a *separate* browser identity the user must log into via `hyperresearch setup` — not their daily sessions, and prone to session kills on aggressive sites.
- Crawl4ai saves screenshots (`screenshot=True` in run config) but **nothing reads them** — no vision extraction path exists.
- Google Scholar (no API, aggressive headless blocking) is unreachable by the current stack — the single best citation-chaining surface there is.
- Provider seam is clean: `WebProvider` protocol + `WebResult` dataclass (`web/base.py:36`) — a new lane slots in without touching consumers.
- Claude-in-Chrome MCP tools (`mcp__claude-in-chrome__*`: tabs, navigate, computer, read_page, get_page_text, find, javascript_tool, read_network_requests) are available to Claude Code sessions and subagents via ToolSearch.

## Architecture: Python queues, agent drives

The Chrome lane cannot be a pure-Python `WebProvider` — Claude-in-Chrome is an MCP surface driven by an *agent*, not an importable library. The design splits accordingly:

- **Python side:** escalation queue management, queue-item lifecycle, result ingestion (reusing `write_note` + the Phase-0 unified fetch engine's note-creation path), cookie handoff.
- **Agent side:** a new `hyperresearch-browser-fetcher` subagent that drains the queue by driving Chrome tabs, extracts content, and calls `hpr` to ingest results.

## Workstreams

### WS1 — Escalation queue + ladder (M)

**Design.** The fetch engine gains an outcome taxonomy instead of discard-on-failure. On `login_wall`, `junk` (bot-block subtypes: cloudflare/captcha signals already distinguished in `base.py`), or repeated fetch failure:

```
crawl4ai (headless, parallel)
  └─ blocked → enqueue research/runs/<tag>/escalation-queue.json
       └─ browser-fetcher agent drains via Chrome
            └─ human checkpoint (WS3) only if Chrome also can't proceed
```

Queue item schema:

```json
{ "url": "...", "reason": "login_wall | bot_block | captcha | fetch_failed | interactive_needed",
  "requested_by": "step-2-wave-1", "suggested_by": "<note-id>", "utility_score": 14,
  "status": "queued | in_progress | fetched | needs_human | abandoned",
  "attempts": 1, "note_id": null }
```

**Changes.**
- `core/fetcher.py`: on gate rejection, write the queue entry (append-safe JSON-lines or lock-guarded JSON) instead of just erroring; CLI/JSON output reports `escalated` as a distinct outcome so fetcher agents don't retry.
- `hpr escalation list/add/claim/complete [-j]` — small CLI for queue lifecycle (agents interact through it; no direct file editing, avoiding races).
- Step-2 and step-13 skills: after each wave, check `hpr escalation list -j`; if high-utility items are queued (utility ≥ profile threshold), spawn the browser-fetcher to drain them while the next wave proceeds. Low-utility blocked URLs are abandoned without ceremony — the ladder climbs only when the source is worth it.

### WS2 — `hyperresearch-browser-fetcher` agent (L)

**Design.** New subagent definition (installed like the others; Phase-0 layout):

- **Tools:** `Bash, Read, ToolSearch` + the Claude-in-Chrome MCP tools (loaded via one batched ToolSearch per session, per the MCP server's own guidance). Model: sonnet.
- **Contract:** claim queue items via `hpr escalation claim`; for each: open a new tab (never reuse user tabs), navigate, wait for content, extract via `get_page_text`/`read_page`; for PDFs rendered in a viewer, trigger download or extract text from the viewer DOM; write the note via `hpr note new --body-file` with `fetch_provider: chrome` frontmatter + the standard provenance fields; mark item `fetched` with the note id.
- **Interactive extraction playbook (in the prompt):** infinite scroll (scroll-until-stable with a hard cap), "load more"/accordion expansion, in-site search when the target is a query not a URL, SPA navigation waits. Session-kill awareness: prefer reading over clicking on auth-sensitive sites; never log out, never change account state; do not navigate to URLs outside the claimed item's domain except for redirects.
- **Vision-assisted extraction:** when the page is chart/figure-heavy or text extraction is thin, screenshot and read the image, transcribing figures/axis values into the note body under a `## Extracted figures` section. (This also unlocks reading the screenshots crawl4ai already saves — add a `hpr assets path` + Read step to the source-analyst prompt as a cheap rider.)
- **Escalation out:** on CAPTCHA/2FA/login → mark item `needs_human` with a one-line description, move on. Never attempt to solve.
- Batch behavior: drain up to N items (profile) per spawn; sequential, one tab at a time (Chrome lane is precious/low-throughput by design).

**Concurrency note:** exactly one browser-fetcher at a time (the queue `claim` op enforces it) — parallel agents fighting over one browser is chaos.

### WS3 — Human-in-the-loop checkpoint (M)

**Design.** When items sit at `needs_human`, the run pauses *that lane* — not the pipeline:

- The orchestrator, at step boundaries, checks for `needs_human` items; if present and the item's utility justifies it, it surfaces a **single consolidated prompt** to the user: "3 sources need you: [site A: solve CAPTCHA], [site B: log in], [site C: 2FA]. Open them in Chrome, complete the challenge, then say 'done' (or 'skip')." In non-interactive (`-p`) runs, this writes `run.json.blocked_on = "human-challenges"` + a notification (stdout marker the harness can surface / OS notification where available) and continues with everything else; the queue drains on the next resume.
- After the human completes challenges in their own browser, the browser-fetcher retries the items — the session now carries the solved state.
- The consolidated-prompt pattern matters: one interruption per run, not one per URL. Batch `needs_human` items and raise them at natural pause points (end of wave, step boundary).

**This checkpoint is the CAPTCHA/2FA/login story, in full.** The human does human things in their own browser for ten seconds; the pipeline gets the source. Document this verbatim in the agent prompt and user docs so expectations are unambiguous.

### WS4 — Session handoff: Chrome → headless (M)

**Design.** After an interactive login succeeds in Chrome, subsequent fetches from that domain shouldn't need the Chrome lane. `hpr session handoff <domain>`:

- Export cookies for the domain from the Chrome profile into the crawl4ai profile's storage state (`~/.crawl4ai/profiles/<name>` is a Playwright `user_data_dir`; write a `storage_state.json` the provider loads, or inject cookies via Playwright's `add_cookies` on context creation — implementation detail: crawl4ai supports `storage_state` in browser config).
- Cookie *reading* from Chrome: via the Claude-in-Chrome `javascript_tool` (`document.cookie` covers non-HttpOnly only) is insufficient — instead have the browser-fetcher trigger the handoff by exporting through Chrome's DevTools-adjacent surface if available, or fall back to instructing the user to run `hyperresearch setup` for that site once (the existing flow) now that they know it's worth it. **Design honestly around the constraint: HttpOnly cookies are not scriptable from page JS.** The realistic v1: session handoff works where the site's session survives in the crawl4ai profile after one guided login there; the Chrome lane covers the rest directly.
- Track handoff domains in config so the fetch engine prefers headless-with-profile for them and only re-escalates on a fresh login wall.

**Honest framing for the doc:** WS4 is an optimization with a hard platform constraint; the Chrome lane (WS2) is the guaranteed path. Ship WS2/WS3 first, treat WS4 as best-effort.

### WS5 — Google Scholar lane (S)

**Design.** A browser-fetcher playbook specialization, not new machinery: queue items of type `scholar-search` carry a query instead of a URL; the agent searches Scholar in a tab, extracts the top-N results (title, authors, year, citation count, link, "cited by" link), and returns them as a structured result note (`type: index`, tagged `scholar-results`) that step-2's search planning consumes like an academic-API response. Cited-by chaining: enqueue follow-up items for high-value hits. Rate discipline in the prompt: human-paced interactions, small N, one query at a time — this is a courtesy lane, not a scraper.

### WS6 — Config + profile integration (S)

`[chrome]` config: `enabled`, `escalation_utility_threshold`, `max_items_per_run`, `drain_batch_size`, `scholar_enabled`. Profiles set lane budgets (light: disabled by default; full: modest; dissertation: generous). `hpr run status` shows queue depth + `needs_human` count.

## Dependencies

- Phase 0 (unified fetch engine to hook the outcome taxonomy into).
- Phase 1 (config/profile plumbing; agent prompts as templates).
- Phase 3's run dirs give the queue its home (`research/runs/<tag>/`); if Phase 4 lands first, the queue lives at `research/temp/escalation-queue.json` with a migration note.
- External: Claude-in-Chrome extension installed + site permissions granted (document in setup docs; the lane degrades to "queue accumulates, nothing drains" without it — surfaced in `run status`).

## Acceptance criteria

- [ ] A login-walled URL (test fixture site) is enqueued, not discarded; fetch JSON reports `escalated`.
- [ ] Browser-fetcher drains a queue of public-but-interactive pages (infinite scroll fixture) into well-formed notes with `fetch_provider: chrome` and correct provenance.
- [ ] A CAPTCHA/login page results in `needs_human` (never an attempted solve), consolidated into one user prompt; after manual completion, retry succeeds.
- [ ] Non-interactive run with blocked items completes everything else and records `blocked_on`; resume drains after human action.
- [ ] Scholar lane returns structured results for a query and enqueues cited-by follow-ups.
- [ ] With Chrome unavailable, the pipeline runs exactly as 1.x (lane cleanly disabled).
- [ ] Queue operations are race-safe under concurrent fetcher waves (claim/complete integration test).

## Risks & mitigations

- **Site terms-of-service and rate discipline** — the lane touches sites that resist automation. Mitigation: human-paced playbooks, per-run caps, courtesy framing in prompts, and the human checkpoint keeps a person in the loop for exactly the interactions sites gate on. The lane reads what the user's own access can see; it does not evade.
- **Browser-agent fragility** — selectors and page structures vary wildly. Mitigation: text-extraction-first (get_page_text) over DOM surgery; per-item attempt caps; abandon gracefully (an abandoned source is where we started — lost — so the floor is the status quo).
- **User interruption fatigue** — mitigation: utility threshold before anything reaches `needs_human`; consolidated prompts; skip is always an option.
- **One-browser bottleneck** — the lane is serial by design. Mitigation: it only receives high-utility escalations; throughput stays with headless waves.

## Effort

| WS | Size |
|---|---|
| WS1 queue + ladder | M |
| WS2 browser-fetcher agent | L |
| WS3 human checkpoint | M |
| WS4 session handoff | M (best-effort) |
| WS5 Scholar lane | S |
| WS6 config | S |
