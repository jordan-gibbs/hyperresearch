# Changelog

## [Unreleased]

## [0.12.0] - 2026-09-24

- **The repo is a Claude Code plugin marketplace.** `/plugin marketplace add jordan-gibbs/hyperresearch` then `/plugin install hyperresearch@hyperresearch` adds one skill, `deep-research`, at `skills/deep-research/SKILL.md`. It checks for the `hyperresearch` CLI, runs `hyperresearch install` in the current project, and hands off to `/hyperresearch`. It holds no pipeline steps; those still come from the Python package.
- Add scholarly metadata filters and metadata-only browsing to CLI and MCP search, including semantic filtering and a cache upgrade that preserves unchecked retraction status.
- **BEHAVIOR CHANGE — crawl4ai's headless browser verifies TLS certificates (#137).** crawl4ai defaults `BrowserConfig.ignore_https_errors` to True and launches Chromium with `--ignore-certificate-errors` on every start, so the provider `hpr install` switches a vault to fetched most HTML with verification off. Setting `ignore_https_errors = False` alone changes nothing (checked against a self-signed server on crawl4ai 0.8.6); the provider now also drops those launch flags, on both the plain launch and the login-profile (managed browser) launch, and refuses to start if a crawl4ai release moves the code it overrides. A refused certificate raises `CertVerificationError` naming the code (`ERR_CERT_AUTHORITY_INVALID`, ...) and the new opt-out, `[fetch] browser_verify_tls = false`. Before, it came back as an empty page and was reported as junk. As on the builtin and PDF lanes, the failure is final: no unverified retry, no escalation. In a batch it is a logged skip. The visible-window lane (`--visible` with a login profile) still ignores certificate errors, since some of the walled sites it serves have broken chains. Batch fetches also stopped mislabelling results: `arun_many` returns them in completion order, and they were paired with the requested URLs by position.
- **An OpenAlex outage no longer erases a known retraction.** Only OpenAlex reports retractions; when it errors, `lookup_metadata` falls through to Semantic Scholar, which answers "unknown". `sources score --fresh` (and the ship-time `sources retractions` sweep) wrote that unknown over a stored `is_retracted = 1`, so a retracted citation passed the gate. Unknown now keeps a stored retraction. A stored false is still replaced, since older versions wrote an unchecked false for every S2 result.
- **A run tag is a slug (#116).** `Vault.run_dir()` joined the tag onto `research/runs/` unchecked, and pathlib replaces the base on an absolute segment, so `hpr run init ../../x` or `hpr run init C:/anything` scaffolded a run workspace outside the vault and every later `run` subcommand followed it there. Tags are now validated at that one seam: letters, digits, `-`, `_` and `.`, starting with a letter or digit, which is what `hpr vault-tag` mints. `run`, `levers` and `citecheck` report a bad tag as a clean error instead of a traceback. Same bug class as the `claims ingest --tag` traversal fixed in 0.11.1; exposure is low because the tag comes from the operator or the orchestrating agent, not from fetched content.
- **The builtin provider fetches PDFs (#82, reported by @earldodd).** The PDF lane (`_is_pdf_url` / `_fetch_pdf`) lived inside the crawl4ai provider only, so a vault still on `provider = "builtin"` (the default until `hpr install` switches it) had no PDF handling at all: a direct `.pdf` link was decoded as HTML text and rejected by the junk gate as "Binary PDF garbage in content", identically for every mirror of the same document, and an arXiv `/abs/` link saved the 900-word abstract page instead of the paper. The lane now lives in `web/pdf.py` and both providers use it; the crawl4ai module keeps the old names. The builtin provider also detects a PDF from its bytes when the URL does not look like one. When the PDF lane declines a URL and the HTML fallback turns out to be junk, `hpr fetch -j` now says why the lane declined it (`PDF lane: HTTP 403`, `no extractable text layer`, ...) instead of the generic junk verdict, and the pymupdf document handle is closed on the exception path instead of leaking one per encrypted PDF.
- **`serply` web provider.** Google organic results with page fetch through the same `SERPLY_API_KEY`; opt-in via `[web] provider = "serply"`, no new dependency.
- **Quote integrity pairs short quoted spans (#120 reported by @earldodd, #122 from @akshaypal912).** `_QUOTE_SPAN_RE` required 20+ characters between quote marks, so a short quoted term ("TVL") failed to match at its opening mark; the scan then treated its closing mark as a new opening mark and reported the unquoted prose up to the next quote character as a hallucinated quote. One real report turned 38 legitimate short quotes into 42 false errors. The regex now matches any span up to 600 characters, and the existing fewer-than-5-words skip decides what gets verified.
- **The SSRF gate classifies IPv4-mapped IPv6 by its embedded IPv4 (#127, from @fduple).** On Python 3.12+ the stdlib `is_*` properties see through `::ffff:a.b.c.d` to ranges they don't flag, and the CGNAT check only looked at IPv4 objects, so `::ffff:100.64.0.1` was fetchable. On 3.11 the opposite held: `::ffff:8.8.8.8` was refused. Mapped addresses are unmapped before classification on every version. An `allow_private_hosts` entry of the form `host:port` or `[v6]:port` now raises a clear error; it never matched anything, but note that it surfaces on every fetch while it is in the config. Bracketed IPv6 entries (`[::1]`) now parse.
- **A bad TLS certificate on the builtin provider raises `CertVerificationError` (#130, from @fduple).** It surfaced as a bare `httpx.ConnectError`. The failure is still final: nothing retries without verification, and the fetch is not queued as an escalation. The crawl4ai provider raises the same error on its PDF lane, and now on its headless browser lane too (#137).
- **Note ids are fixed points of the slugifier, and the link validator rejects shell fragments and traversal (#126, from @fduple).** `write_note` built the filename from the raw id while the frontmatter id was slugified, and `repair` / `graph stub` pass broken-link text through as the id, so fetched content chose the path: `[[../../outside]]` wrote outside the vault, and `[[-n "$kernel"]]` crashed on Windows. Stub files now get slug filenames. `is_valid_wiki_link_target` also refuses targets containing `$ " \` = \ < > ;`, a leading `-` or `!`, or a `.`/`..` segment. Slug ids never contain those, but a title or alias link such as `[[E=mc2]]` that used to resolve by title will drop out of the links table on the next sync.
- **`note mv` keeps notes where sync can see them (#128, from @fduple).** The destination was joined onto the vault root verbatim, so a bare name landed at the root with no `.md` and left the index, `../x.md` wrote outside the vault, and an existing file was overwritten (POSIX) or crashed the command (Windows). A bare name now lands in `research/notes/` with `.md` added; destinations outside `research/notes/` and `research/temp/` are refused with `OUTSIDE_SYNCED_TREE`, and an existing file with `DESTINATION_EXISTS`. `research/index/` is refused too, since `repair` regenerates it and deletes every `.md` there. Case-only renames work on case-insensitive filesystems. The docstring no longer claims `mv` updates references; the id lives in frontmatter, so it never needed to.
- **The builtin provider keeps fetched code as markdown code (#129, from @fduple).** `<pre>` blocks and inline `<code>` were flattened to prose, so bash test syntax (`[[ -n "$k" ]]`) reached the wiki-link parser and `repair` minted stub notes named after shell fragments. `<pre>` now becomes a fenced block whose fence outruns any backtick run inside it, inline `<code>` becomes a backtick span, and indentation survives in the stdlib fallback. Because `strip_markdown` drops code before indexing, code on builtin-fetched pages is no longer in full-text search, embeddings, or the quote-integrity comparison, which is how crawl4ai-fetched pages already behaved. A report that quotes a sentence containing an inline identifier can now fail quote integrity where it passed before.
- **Code stripping honours fence length (#140).** The strip that runs before wiki-link parsing closed a fenced block at the first ```` ``` ```` whatever the opening fence was, and an inline span at the first backtick. #129 fences fetched code with a run longer than any inside it, so a `<pre>` holding an odd number of ```` ``` ```` leaked its `[[ ]]` into the link parser. `CODE_BLOCK_RE` and `INLINE_CODE_RE` are replaced by `strip_code()`, a linear scanner that follows CommonMark: a fence opens on a line starting with 3+ backticks and closes on a line holding only at least as many; an opener nothing later can close is literal text (CommonMark would run it to the end of the note, which let a prose line starting with ```` ``` ```` drop the rest from links and search); an inline span of N backticks closes only at the next run of exactly N, and an unmatched run is literal. Stripped code now leaves its newlines behind, so the `links` table's line numbers match the note. The builtin provider's inline `<code>` delimiter also outgrows the backtick runs inside it, which the fixed ```` `` ```` did not.
- **Skills name the CLI by its resolved path (#133, reported by @blrain3).** 14 of the 19 installed skills spelled the CLI `$HPR`, which nothing defined, so `$HPR run finish <tag>` (the ship gate) ran as `run finish` and the shell answered `command not found`. Skills now carry the `{hpr_path}` placeholder the agent prompts already used, and `install` (including `install --steps-only`, the entry skill's bootstrap) fills it with the same absolute path CLAUDE.md shows. The corpus-critic step had one literal `{hpr_path}` that was never substituted; it resolves now too. Re-run `hyperresearch install` to pick this up.
- **The open-access URL gate uses the SSRF gate's address rules (#138).** `check_oa_url` classified resolved addresses with `is_global`, which on Python 3.11 passes IPv4-mapped and 6to4-wrapped CGNAT (`::ffff:100.64.0.1`, `2002:6440:1::`) — the addresses #127 closed on the fetch path. It now calls `safe_http.check_url` after its own credential and bare-hostname checks, and ignores `allow_private_hosts`. Europe PMC JATS downloads now go through `safe_get`, so a redirect to a private host is refused instead of followed.
- **Cite-check samples at the configured rate.** `sample_needs_llm` kept every `round(1 / rate)`-th weak pair, so the default 0.6 sampled 50% and 0.3 sampled 33%. It now keeps exactly `rate` of them, spread evenly, still without an RNG.
- **Python 3.14 (#81, requested by @cjangrist).** `requires-python` is now `<3.15`, and CI runs 3.14. No code changes were needed; the full suite passes on 3.14.2.
- **The dissertation tier is labelled experimental (#103).** Its word, read-budget and citation targets are defined in the profile but no prompt or check reads them. README and the router now say so, and the router tells the orchestrator to warn the user before starting one.

## [0.11.1] - 2026-09-11

### Seven fixes from the backlog sweep

- **Markdown links no longer mint stub notes (#93, reported by @ThiagoMafra-Integrare).** `[[Label]](https://…)` — everywhere on GitHub READMEs, awesome-lists and Wikipedia-shaped pages — parsed as a wikilink, and `repair --stub` (default on, and mandated after every session) turned each one into a real note that then topped `_most-linked` and inflated PageRank. `WIKI_LINK_RE` now refuses a `]]` immediately followed by `(`; the hygiene filter also rejects unsubstituted `{…}` placeholders and unbalanced brackets. Resolver-minted stubs are excluded from both rankers and have their stale centrality zeroed, so vaults polluted before this fix recover on the next `graph rank`. The stub marker is centralized so the minting sites and the filter cannot drift.
- **`claims ingest` finds the claims (#69, reported by @fduple).** The default scan read only the legacy `research/temp/`, while every producer and consumer had moved to `research/runs/<tag>/temp/` — so the claims table was empty in every real run and `claims matrix` / `targets` were dead on arrival. The default now scans both; `--tag` narrows to the run. A zero-file default scan prints a hint instead of a bare zero.
- **A Semantic Scholar rate limit is reported as a rate limit (#70, reported by @fduple).** A 429 was folded into "No metadata found" — an affirmatively wrong diagnosis. 429s now retry three times with backoff (honouring `Retry-After`), and an exhausted budget surfaces as `rate_limited` in `sources score` output rather than `missing`. Nothing is cached for a throttle, so the next run retries. Optional `S2_API_KEY` support, scoped to `semanticscholar.org` hosts only — the fetch helper is shared with Unpaywall and Europe PMC, and an unscoped header would have shipped the key to them.
- **`run resume` names a skill that exists, chapters reach the manifest, step 8 keeps its preflight gaps (#100, from @darlingm's contract audit in #88).** `resume` printed `hyperresearch-2` for a skill named `hyperresearch-2-width-sweep`, and CLAUDE.md advertises `resume` as the recovery path — the slug now comes from the installer's own step table. `set_chapter()` had zero callers; it is gone, and the `chapter-plan` event the partition skill already emits now registers the chapter, so a resumed dissertation reports what is actually pending. Step 8's subagent wrote to the same file the preflight had just written; it gets its own output and a merge step, and gap records carry the `id` the dispatch already referenced.
- **Every pipeline constant is authored once (#101, from @darlingm's contract audit in #88).** `citation_density_min` sat unread on the profile while two gates hardcoded their own number; the draft orchestrator hardcoded word targets the synthesizer templated, so on `premier` the two halves of a run were 60% apart; step 4 templated `loci_analysts` and then said "both" and wrote `loci-a.json` / `loci-b.json`. A new test asserts every `Profile` field is read somewhere outside `profiles.py` — and it found **eight more** dead fields (`comparisons_tensions`, `source_tensions`, `tension_survey`, `tension_full_reads`, `corpus_critic_fetchers`, `citation_totals`, `utility_scoring`, `vault_check_interval_s`), all now wired into the prose that had been hardcoding them. `char_targets_no_word_boundary` is authored per gear at the 3:1 ratio the profile already used, which moved full's argumentative range from 20000–25000 to 15000–30000 — the old span was 1.25× against a 2× word span.
- **Citation density is per 1000 effective words, not per 1000 characters (#76).** The floor meant something roughly 3× stricter for CJK than for English. The denominator reuses #64's boundary detection: whitespace tokens where they exist, characters ÷ `chars_per_word_no_word_boundary` (3.0) where they don't. The floor is re-derived as `citation_density_min = 9.0` per 1000 words, which is what 1.5 per 1000 characters worked out to for English prose — English verdicts are unchanged at the boundary; CJK reports are now held to the same standard per unit of content rather than a looser one.
- **`hpr serve` binds its port exclusively on Windows and reports the port it bound (#104).** `SO_REUSEADDR` means "reclaim TIME_WAIT" on POSIX and "share a live port" on Winsock; a second bind on a running server's port succeeded on Windows. The server class now leaves it off there. `run_server` returns and prints the actually-bound port instead of `http://127.0.0.1:0`, so the tests stopped monkeypatching `server_activate`. CI gains a single `windows-latest` job on 3.11 — the platform this project is developed on — with the required-check names held stable.

### Security review of the sweep

A review pass over the seven fixes above found six medium-severity problems — two of them pre-existing on `main` — and fixed each with a regression test.

- **A hostile page could hang `hpr sync`.** `WIKI_LINK_RE` was quadratic on bracket floods: 20 KB of `[[` took 4.8 s, 40 KB took 19 s, and 100 KB did not finish in two minutes — and the pattern runs on the whole body of every fetched page. Excluding `[` from both character classes makes it linear (a 300 KB flood scans in under a millisecond). Pre-existing; surfaced because #93 touched the pattern.
- **The Semantic Scholar key followed cross-host redirects.** httpx strips `Authorization` on a cross-origin hop but not `x-api-key`, so a 302 from semanticscholar.org would have carried the key to any host. Redirects are followed manually now, at most five, http(s) only, with headers recomputed from each hop's URL. Separately, the host check was a bare `endswith` on the raw netloc, which `evilsemanticscholar.org` and a userinfo trick both passed; it is now an exact-or-subdomain match on the parsed hostname.
- **`claims ingest --tag ../../..` scanned outside the vault**, because pathlib replaces the base on an absolute segment. A tag narrows the scan only when the resolved directory sits under `research/runs/`; files that resolve outside the vault root — symlinks — are skipped.
- **One malformed claims file aborted the whole ingest.** Claims JSON is agent-written from fetched content: a dict where a string was expected raised out of `.strip()`, a list confidence raised out of sqlite, and 200 000 nested brackets hit `RecursionError`. Files are size-capped at 8 MB before reading, text fields are typed and bounded, and one bad claim becomes one error entry instead of a dead run.
- **A crafted `chapter-plan` event could corrupt the manifest.** The fold introduced by #100 stringified any `chapter` value into a key and stored any `title` verbatim; a non-dict `chapters` crashed `resume_position`. Only a string or int id and a string title fold, both bounded; everything else stays in `events.jsonl`.
- **`Retry-After` was already clamped to sixty seconds** — confirmed with a parametrized test over `nan`, `inf`, negatives and forty-digit values, all of which fall back to the 2 s / 4 s ladder.

Deferred to its own issue: `hpr run init` applies no validation to the vault tag at all, so `../../x` scaffolds outside the vault. Same bug class as the claims fix, but it touches every run command.

## [0.11.0] - 2026-09-11

### SSRF gate + size caps for fetches (builtin, crawl4ai entry points, PDF and image downloads)

- **The builtin provider, the crawl4ai entry points, and PDF and image downloads now go through an SSRF gate** (`web/safe_http.py`): http/https only; hostnames resolving to private, loopback, link-local, multicast, reserved, CGNAT (RFC 6598), or unspecified addresses are refused (cloud metadata, RFC1918, `[::1]`, `100.64.0.0/10`, …). Not covered: the fixed-host API calls in `core/embed.py` and `core/scholar.py`, which take no attacker-influenced URLs. On the `safe_get` paths (builtin provider, PDF and image downloads) redirects are followed manually and every hop is revalidated. The browser lanes (crawl4ai `fetch()`, `fetch_many()`, and the visible-window path) are gated at entry AND re-checked on the URL the browser actually landed on — the browser follows redirects internally, so the entry check alone cannot vouch for the destination. A post-hoc recheck cannot stop the request that already fired (blind SSRF survives it), but it keeps private-network content out of the vault; the same-host case skips the extra DNS lookup. Refused URLs in a batch are logged and skipped, not fatal. The hostname check is best-effort against DNS rebinding (httpx re-resolves at connect time); the residual window is documented in the module docstring.
- **`[fetch] allow_private_hosts`** — escape hatch for self-hosted mirrors and intranet sources: hostnames (exact, case-insensitive) or CIDRs that may be fetched despite resolving to private space. Empty by default; consulted by `check_url` everywhere, including redirect hops and the final-URL recheck. A malformed CIDR entry errors loudly instead of being silently ignored.
- **Response-size caps**, streamed and enforced mid-body so a lying or chunked server cannot exhaust memory. Configurable via new `[fetch]` settings `max_html_bytes` (10 MiB), `max_pdf_bytes` (25 MiB), `max_image_bytes` (2 MiB). A gate refusal on an image download is printed, not silently swallowed.
- **No unverified-TLS retry.** A certificate failure on a PDF fetch is a refusal that names the existing `pdf_verify_tls = false` opt-out — never an automatic verify-off retry, which a MITM could force with a bad cert. The refusal is its own exception type (`CertVerificationError`), and a cert-refused PDF is never handed to the browser fallback lane: that lane runs with TLS errors ignored, so "falling back" there would be the automatic unverified retry by another name. In a batch it is a loud skip instead.

### Scholarly discovery: eight sources through one client layer

Academic discovery used to be four URL templates rendered into the agent's instructions by `core/agent_docs.py`, which the model was trusted to assemble and call by hand. No retry, no rate limiting, no dedup, no offline tests — and one of those templates shipped `mailto=research@example.com`, a shared placeholder on every install, which is exactly the anti-pattern the open-access resolver refuses to commit for Unpaywall. It is now a real package.

- **`hpr scholar search` and `hpr scholar sources`.** One query hits every configured provider, merges records that are the same work, and returns one list. `sources` lists what is wired, what each covers, and why anything is unavailable — so a user is never guessing which source to reach for.
- **Dedup is by DOI first, then normalized title within ±1 year.** The year tolerance is deliberate: providers disagree systematically about online-first versus print year for the same article. Two *different* DOIs never merge regardless of title, which is what stops four 2025 reprints of a famous paper from collapsing into one record. A work confirmed by several providers carries them in `also_in`, with the highest citation count and the longest abstract.
- **`--limit` is per provider, not a cap on the merged list.** A post-merge cap would show only the first provider's records at small limits and make every other source look empty.
- **Providers: OpenAlex, Crossref, CORE, DOAB, ClinicalTrials.gov, SEC EDGAR, FRED.** Each is a real client through one cache-first, rate-limited HTTP seam (`scholar/base.py`), with fixtures matching live response shapes. OpenAlex's abstracts arrive as an inverted word-position index and are reconstructed; Crossref's arrive as JATS XML and are stripped; ClinicalTrials.gov and EDGAR were verified against the live services, including EDGAR's User-Agent gate.
- **Non-STEM coverage is a first-class goal.** OpenAlex and DOAB return books and book chapters, which matters because in the humanities the book is the unit of publication and nothing in the stack could find one before. DOAB is the only source that finds *the book* rather than a review of it.
- **RePEc is listed as unavailable, on purpose.** Their API documents that it has no search function. Shipping an honest "cannot search" with a pointer to OpenAlex for the DOI-bearing series beats silently omitting the field.
- **`HYPERRESEARCH_CONTACT_EMAIL` replaces the placeholder.** Set it and OpenAlex and Crossref serve you from their polite pools, and SEC EDGAR — which rejects any request without a contact address — becomes available. Unset, no address is sent at all.
- **Specialist records are tagged, not disguised.** Trials, filings and economic series come back with `work_type` set so the pipeline never treats a 10-K as a paper.
- **`FRED_API_KEY` is never cached.** FRED authenticates by query parameter and the cache keys on URL, so FRED requests bypass the cache rather than write the key into the vault's SQLite in plaintext.

### CORE is the third open-access resolver

Recovery used to ask Unpaywall, then Europe PMC. But `contact_email` is empty by default, which disables Unpaywall, and Europe PMC is biomedical only — so a stock install's open-access recovery covered almost nothing outside biomedicine while the 0.10.0 notes presented it as a headline feature. [CORE](https://core.ac.uk/) now runs third: it is the largest full-text open-access aggregator, and unlike Unpaywall it hosts the plain text directly rather than pointing at a repository that may 403.

- Activates when `CORE_API_KEY` is set; skipped silently otherwise, the same way Unpaywall is skipped without a contact address.
- Every existing invariant holds and is tested: a candidate is accepted only if it is longer than what we had and clears `oa_min_full_text_chars`; failure is soft; resolver URLs go through `check_oa_url`; `oa_max_attempts` is honoured; the four-place disclosure contract is populated; `oa_source` gains the value `core`.
- **Version is recorded honestly.** CORE does not reliably say which version it holds, so `oa_version` stays unset unless CORE marks the record a preprint — and the banner then says the version is unrecorded and tells the reader to quote with care, rather than implying version of record.

### Agent prose now points at the client

The "Academic APIs before web search" section of the injected agent instructions tells agents to run `hpr scholar search` and not to hand-assemble API URLs, and explains what each source is for.

### Contributed fixes

- **`run finish` no longer blocks every light-classified run started on the installed gear (@maximilliangrand in #95).** `verify_run()` took its required-artifact step set from the manifest's `profile_steps`, so a run initialized with `--profile full` whose step-1 decomposition classified it `light` was asked for `critic-findings-*.json` and `patch-log.json` — artifacts the light tier correctly never writes, because steps 12 and 14 are skipped by the tier gate. The run did all its light-tier work and then sat at `blocked (verify)` with no legitimate way to pass. The gate now resolves the tier declared in `prompt-decomposition.json` when it disagrees with the manifest profile, which is what the router already documents ("the manifest's profile field is informational — the decomposition's tier rules"). A missing, unreadable or unknown tier still falls back to `profile_steps`.
- **The MCP `fetch_url` tool works again, and a deleted note's URL can be fetched again (#84, fixed by @AmirF194 in #86).** Two bugs on the same path. `Crawl4AIProvider.fetch()` and `fetch_many()` called `asyncio.run()`, which raises before the coroutine runs when the caller already has a loop — and the MCP server dispatches sync tools on its own loop thread, so the tool failed on every call while the CLI never noticed. Both now go through a wrapper that runs the coroutine on a dedicated thread when a loop is present. Separately, `sources.note_id` is `ON DELETE SET NULL`, so deleting a note leaves its row behind with a NULL id; every duplicate-URL check tested row truthiness, so that URL was `DUPLICATE_URL` ("already fetched as note 'None'") forever. All four fetch paths (`fetch_and_save`, `hpr fetch`, `hpr fetch-batch`, `hpr research`) now share one orphan-aware check. The three CLI paths also record the source with `INSERT OR IGNORE`, which was a no-op on the orphaned row too — so the new note was left with no source record, and `hpr fetch`'s duplicate-race detector then deleted the note it had just written and reported `note_id: null`. Those paths now reclaim the orphaned row after the insert; the guard on `note_id IS NULL` leaves a genuine race winner untouched.
- **The PreToolUse reminder now reaches the model (#94; @dajiaohuang in #97 and #98).** The installed hook wrote its reminder to stderr and exited 0, and for PreToolUse that channel is discarded — so the "check the research base before searching the web" nudge shipped since 0.x had never once been delivered. It is emitted as `hookSpecificOutput.additionalContext` now, which is the documented injection channel. The matcher is narrowed to `WebSearch|WebFetch`: on `Glob` and `Grep` the advice is noise, and delivering it there for the first time would have made every local vault operation pay for a reminder about the web.
- **Parallel Search is a fifth web provider (@georgeatparallel in #57).** `[web] provider = "parallel"` searches through Parallel's keyless Search MCP endpoint — the first search-capable provider that needs no account, since `builtin` cannot search at all and `exa` and `tavily` both need a key. Search only: bulk fetch waves degrade to per-URL, so it complements the crawl4ai fetch path rather than replacing it. The README gained a **Web providers** section listing all five on equal footing; none had been documented there before. This PR had been red on CI since August for an `asyncio.run()`-inside-a-running-loop error — the same class of bug #86 fixed — and got the same loop-safe runner.


## [0.10.1] - 2026-09-11

A maintenance release. Everything here is a contributed fix, and two of them unblock users who could not ship a run at all.

- **The `length-in-range` verify gate no longer measures CJK reports with a Latin-script ruler (#71, fixed by @tetra4rnav in #64).** `verify_run` counted whitespace-separated tokens, which in Japanese or Chinese counts almost nothing — a correctly-sized report measured roughly 20x short and `run finish` hard-blocked it, with no honest way past the gate. Length is now measured in characters when whitespace doesn't segment the text, against a new `char_targets_no_word_boundary` profile field. Detection is by average token length rather than Unicode range, which matters: Hangul *is* space-delimited, and a range-based check would have broken Korean while fixing Japanese. This shipped to `main` three days after the 0.10.0 tag and has been sitting unreleased since.

- **`hpr serve` no longer hangs on an idle browser connection (#87, reported by @muppavv, fixed by @maximilliangrand in #96).** The viewer ran a single-threaded `HTTPServer` whose handler set no read timeout, so one socket that connected and sent nothing starved every other client — and Chrome opens exactly such a preconnect socket, which meant the first page load with `--open` could poison the server. The symptom was indistinguishable from a hang: no error, no CPU. Now `ThreadingHTTPServer` with a handler read timeout. The shared SQLite connection that made threading unsafe was correctly retired at the same time, rather than papered over with a lock.

- **An invalid `--status` is rejected instead of silently corrupting a note (@MarceloSenai in #89).** `NoteMeta` had no `validate_assignment`, so `note update --status evergreeen` wrote the typo straight to frontmatter. The note then failed validation on the next sync, dropped out of the index, and `note list` kept serving the stale row — every later edit to that note going unindexed too. The valid set is read from the `NoteStatus` enum rather than a hand-maintained list, so it can't drift.

- **"Purchase this article" is recognised as a paywall (@MarceloSenai in #91).** The phrase list had "buy this article" and "purchase pdf" but not this one, so those interstitials passed as full text and open-access recovery never ran — the note kept an abstract while the report cited it as though the paper had been read. The gate's own comment used this exact phrase as its worked example.

- **The registered PreToolUse hook command quotes the script path (@dajiaohuang in #98).** `install` wrote `node <path>` into `.claude/settings.json` unquoted, and a hook command runs through a shell — so a project directory containing a space split the path there and node was handed a truncated script, making the hook exit 1 on every `Glob`, `Grep`, `WebSearch` and `WebFetch` call. Paths with spaces are ordinary (a Windows user directory, anything under `My Documents`). Installs written before this change keep the old entry, because the installer treats any existing hyperresearch hook as already installed; removing that entry and re-running `install` picks up the fix.

## [0.10.0] - 2026-08-01

### Open-access full-text recovery (Unpaywall + Europe PMC)

A paywalled paper used to enter the vault as an abstract. `extract_doi` stamped the DOI, the junk gate passed the landing page (an abstract is not junk), and depth investigators then reasoned over ~1,500 characters while the report cited the work as though the paper had been read.

- **Thin DOI-bearing fetches now look for a legal open-access copy.** `core/oa.py` asks Unpaywall, then Europe PMC, and stores the recovered full text in the note body. Wired into both `hpr fetch` and `hpr fetch-batch` — the batch path writes its own notes and previously never even captured a DOI, so it now does that too.
- **The substitution is disclosed in four places**, because a note whose body did not come from its `source:` is a trap otherwise: a banner at the top of the body, `oa_url` / `oa_source` / `oa_version` / `oa_license` frontmatter, an `oa` block in `note show -j` carrying `body_is_not_from_source: true`, and a line in the fetch output. The `oa` block sits outside the `<untrusted-source>` fence and is the authority.
- **Version honesty.** Unpaywall returns accepted manuscripts and preprints when no published copy is open. The resolver prefers the version of record, records what it actually got, and the body banner tells the reader to check quotations against the published paper when it isn't one.
- **Opt-in for Unpaywall, zero-config for Europe PMC.** `[scholar] contact_email` is empty by default, which skips Unpaywall entirely — their terms require a real address, and a shared placeholder shipped to every install would get that placeholder rate-limited for everyone. Europe PMC needs no key, so recovery over its open-access subset works out of the box. `oa_recovery = false` turns the whole thing off.
- **Candidate fallback, not one shot.** Publishers 403 their own open-access PDFs often enough that a single attempt loses papers sitting in a repository two candidates down — verified against live DOIs. The resolver now yields an ordered candidate list (every Unpaywall PDF, then landing pages, then Europe PMC) and tries up to `oa_max_attempts` of them. Europe PMC resolves lazily, so the extra API call only happens when Unpaywall is exhausted.
- **Europe PMC full text arrives as JATS, not PDF.** `/fullTextPDF` 404s; `/fullTextXML` is the documented route, and its structured markup parses better than pymupdf on a two-column PDF anyway. The converter keeps title, abstract, and body with section hierarchy, drops back matter, and preserves the tail text after dropped inline elements — losing an `<xref>`'s tail silently truncates a sentence after every citation marker.
- **Failure is always soft, and quality can only go up.** A lookup that errors, a URL that fails the safety check, or a PDF that extracts badly leaves the original untouched. A candidate is accepted only if it is both longer than what we already had *and* long enough to clear `oa_min_full_text_chars` — the second bar stops a repository record page from passing for full text on the strength of being slightly longer than an abstract.
- **Resolver-supplied URLs are treated as hostile input.** They arrive inside a third-party API response, so a poisoned DOI record could otherwise steer the fetcher at internal hosts. `check_oa_url` enforces http(s), no embedded credentials, and publicly-routable resolution. This duplicates the intent of `web/safe_http.check_url` (PR #53) and should collapse into it once that lands.
- **Blocked sources are rescued too.** A fetch that could not be read at all — a 403, a login wall, a bot wall — used to abort long before recovery ran, which meant the feature was absent from exactly the case where a paper is most completely lost and an open-access copy is most likely to exist. All three of those exits now attempt a rescue first. On a default `builtin` install this was the common case, and invisible on a crawl4ai one: `doi.org/10.1093/nar/gkw1099` went from a hard 403 with no note to a 39,609-character note. Rescue only ever turns a failure into a note; a blocked source with no open-access copy fails exactly as before.
- **A rescued note is marked as a stronger claim than a substitution**, because it is one: nothing in it came from `source:`, not the body, not the title, not the authors. `oa_recovery_kind: rescued` in frontmatter, `kind` + `nothing_from_source` in `note show -j` and the fetch output, and a banner that says the source URL was never read. `oa_rescue_blocked = false` disables the path for anyone who would rather have no note than a note assembled entirely from a substitute. A rescued source is not queued for browser escalation — the paper is already in hand.
- **Rescue needs a DOI and there is no page to read one out of**, so it fires only when the DOI is in the URL (a `doi.org` link) or in a wall page's `citation_doi` meta tag. A wall page's body text is never trusted for a DOI. This limit is documented rather than papered over.
- **Schema v11** adds the four `oa_*` columns and **v12** adds `oa_recovery_kind`, both additive and idempotent. Two versions rather than one: v11 is idempotent by column name, so a database already stamped v11 would have skipped a late-added fifth column forever. Existing notes keep NULLs — there is no way to know after the fact whether an old note's body came from its source URL.
- **Config files are now written as UTF-8 explicitly.** `VaultConfig.save` took the platform default, so on Windows a single non-ASCII character in any comment or value produced a `config.toml` that `VaultConfig.load` — which reads it as UTF-8, per the TOML spec — could not parse. Latent until this branch's comments happened to be the first non-ASCII bytes in the file.

### Two safety fixes in the viewer and the installer

- **Stored XSS in `hpr serve` (#72, reported by @letospace).** `_serve_search` escaped every interpolated value except the FTS snippet, and the snippet is note body text — remote page content, for a fetched note. `strip_markdown` was not a defense: its tag regex needs a closing `>`, so an unterminated `<img src=x onerror=...` passed into `body_plain` intact, and the `>` of the `</mark>` the search page injects finished the tag. The snippet is escaped before the markers are substituted now, so the `<mark>` tags are the only markup that survives. Bounded by the server binding `127.0.0.1` and being read-only, but the script ran same-origin with the wiki and could read every note the viewer could reach. Link and image URLs in the renderer also got a scheme allowlist, so a note body can no longer render a `javascript:` or `data:` link.
- **`install --global` deleted `~/.claude/skills/research/` on a name match alone (#73, reported by @letospace).** `research` is an ordinary word and an obvious name for a hand-written personal skill, and `--global` puts the prune in a user-level directory shared across every project, so anyone with one lost it silently on their first upgrade. A marker file cannot fix this — the directories being pruned predate any marker we could have written — so the check is on the content we shipped into them: every `SKILL.md` this project has ever installed names the project. Anything else is left alone and reported in the install output, which previously listed what it installed but never what it deleted.

### Contributed fixes

- **Browser setup installs (and pre-checks) patchright's chromium when
  patchright is present.** The stealth adapter (`UndetectedAdapter`) launches
  patchright's pinned chromium, which lives in a separate registry from plain
  playwright's, so `playwright install chromium` alone produces a machine
  where every preflight passes and every browser fetch dies at launch with a
  missing-executable error, while the PDF lane keeps working. Both setup
  surfaces (`hyperresearch setup` and `install`) now check against the stack
  the provider actually launches and prefer `python -m patchright install
  chromium`, falling back to plain playwright for non-stealth installs; the
  manual-install hint names both commands. Thanks @fduple (#67).
- **Collision note ids survive the frontmatter re-parse** (an orphan-note
  foreign-key crash). `write_note()` appended `-2` to a slug already sitting on
  `slugify()`'s 80-char cap, producing an 82-char id whose next parse
  re-slugified it back under the cap: the suffix fell off, the second note
  collapsed into the base id, sync refused the duplicate, and the `sources`
  insert died with `IntegrityError: FOREIGN KEY constraint failed`, leaving the
  `.md` file on disk but permanently unregistered. Collision ids are now built
  by trimming the base so base+suffix fits both the 80-char and 200-byte caps,
  then normalized once, so the disk id equals its own re-parse; short-title
  collisions keep their existing `-2` ids, so existing vaults do not shift.
  Thanks @fduple (#66).
- **The `mcp` extra is upper-bounded to `<2`.** mcp 2.0 removed `mcp.server.fastmcp`, which every tool in `hyperresearch/mcp/server.py` is built on, so an unbounded `pip install hyperresearch[mcp]` resolved 2.x and `hyperresearch mcp` died on import while reporting the extra as missing. All 13 tools verified against 1.29.0.
- **Test isolation for the process-global render context.** `install_hooks()` sets a module-level profile context that direct `_install_*` calls reuse, so a test installing with a profile overlay leaked its numbers into every later install in the same process. Confirmed outside the suite too: a clean vault rendered another vault's `source_min`. Thanks @fduple (#65).

## [0.9.1] - 2026-07-25

### Four silent-failure leaks closed (tags, FTS syntax, batch PDFs, cache-busting date)

- **Tag filtering:** frontmatter tags are now lowercased before the alias lookup and before storage, matching the lowercase alias keys and the lowercasing `SearchFilters` does on the query side — `--tag llm` now finds notes tagged `LLM`, including through aliases.
- **FTS queries:** stray unbalanced double-quotes in bare words are stripped instead of raising an FTS5 syntax error that the caller saw as zero results. Hyphenated words are left intact — they were already valid inside the emitted quoted phrase tokens.
- **Batch PDF fetches:** in `fetch_many`, a PDF whose direct download fails (parser failure, non-PDF body at a `.pdf` URL) now falls back to the browser path, mirroring single-fetch behaviour instead of being silently dropped. `fetch-batch` also falls back to per-URL fetches when a whole batch fails, and reports `failed_urls` in its output instead of losing them silently.
- **Prompt-cache-busting date:** the vault CLAUDE.md blurb no longer interpolates `Today is YYYY-MM-DD`, which busted Claude Code's prompt cache once per day.

### Fetched note bodies are wrapped as untrusted data (core/untrusted.py)

- **Prompt-injection fence:** note bodies fetched from the web (http/https `source`, non-summary type) now arrive wrapped in `<untrusted-source url="...">` … `</untrusted-source>` delimiters with an inline treat-as-data preamble, on BOTH body-serving paths: `note show` (single, batch, `-j`) and `search` with bodies included. Notes produced by our own pipeline subagents (`interim`, `source-analysis`, `moc`, `index`) pass through unwrapped.
- **Fence hardening:** forged fence tags inside a fetched body — opening or closing, any case, any internal whitespace — are neutralized to `untrusted-source-inner` (kept visible for forensics), and the `url` attribute is HTML-escaped with control characters stripped, so neither the body nor a crafted source URL can plant text outside the fence. In `search`, wrapping runs after token-budget truncation so the closing fence is never severed.
- **Agent prompts updated:** the researcher, depth-investigator, draft-orchestrator, and source-analyst prompts and the vault CLAUDE.md blurb gained an "Untrusted content policy" block instructing agents to treat fenced content as data, never instructions, and not to launder its directives into trusted outputs.

## [0.9.0] - 2026-07-23

### Coverage before elegance: the synthesizer stops trading substance for prose

A rerun of a comparison query scored below its own older baseline on comprehensiveness and insight, and reading both reports side by side showed why: same word count, spent differently. The humanization work (primers, calm citations, one committed thesis) had quietly taught the synthesizer to dissolve a systematic ten-axis comparison into an elegant narrative and to compress a fully developed quantitative mechanism down to a one-line mention. Cleaner to read, and worse on exactly the axes a "compare X, Y, Z" prompt is graded on. The prompts were conflating two different edits: cutting prose, which is right, and cutting substance, which is not.

- **The synthesizer now treats coverage and mechanism depth as content, not optional structure.** On a compare or survey task, every decision-relevant dimension the corpus names gets explicit coverage, and a mechanism the sources develop (a named decomposition, a formula with its terms, a causal chain with its numbers) gets developed in the report rather than gestured at. The rule it now follows: elegance is spent on the words between points, never on the number of points.
- **"Selectivity" is now defined precisely.** The anti-sprawl guidance used to read as license to drop points; it now says selectivity means choosing which sources to cite for a point, not which points to make. Dropping a comparison axis or compressing a mechanism is a coverage gap, not economy.
- **The length pass cuts prose, never points.** When trimming to the word ceiling, redundancy and filler go first; a comparison dimension, a developed mechanism, a counterargument, and a load-bearing primary source are off limits. If prose cuts do not get under the ceiling, the report has too many words per point, not too many points.
- **Two adversarial backstops.** The depth critic now flags a developed quantitative mechanism compressed to a bare mention as the highest-insight loss a draft can take. The instruction critic gains a comparison-axis coverage check (register-independent, since a comparison prompt needs its axes covered whatever the register) that names dropped or compressed dimensions.

### Run levers: auto-selected register, domain notes, and inference depth

The pipeline had one hard-coded voice (evaluative-argumentative), so a "teach me X" or "survey the landscape" query got an opinionated verdict report. The Q62 register experiment showed the judge prices register heavily (+2.5 RACE from register alone), so register is now a run-time lever instead of a constant.

- **Three levers, auto-selected in step 1** and written into the decomposition: `register` (`teach` / `survey` / `analyze` / `advocate`, classified from the query's verb shape, defaulting to `analyze` — today's behavior — unless the signal is strong; explicit user directives always win), freeform `domain_notes` (sourcing strategy, evidence norms, recency window), and `inference_depth` (`surface` / `standard` / `deep` — the rabbithole dial; step 4 may upgrade it after seeing the actual corpus via `hpr levers set <tag> inference_depth=deep --rerender`).
- **`hpr levers render <tag>`** materializes the levers into four role-scoped shim files (`shims/{research,drafting,critics,polish}.md`) that spawn templates paste VERBATIM into subagent prompts — the orchestrator never composes posture text. Shims compose additively (register block + domain block + depth block), and division of labor is strict: profiles own every number, levers own posture only (drift-proofed by a test that rejects numeric budget ranges in shim text).
- **The critics and polish auditor are register-aware**, so the pipeline can't undo its own mode: in survey/teach register the dialectic critic flags unfair representation instead of missing commitment, the instruction critic stops demanding rankings the prompt never asked for, and the polish auditor's hedge-striking stands down. In advocate register all three tighten instead. The cite-checker and ship gate receive NO shim — verification never softens by mode.
- **Graceful degradation everywhere:** agents proceed with today's defaults when no directives block arrives, lever-less runs skip the new `levers-rendered` verify check, and `run status` surfaces the chosen levers so a misclassification is visible before hours of pipeline run on it.

### Ship gate enforcement: `run finish` (lessons from the first premier run)

The first end-to-end premier benchmark run exposed both prose-only gates failing exactly the way prose gates fail: the orchestrator never invoked `run verify` (a 25,647-word report shipped against a 16K ceiling), and when lint flagged 24 hallucinated/mangled quotes it wrote itself a "false positives" memo and shipped anyway.

- **`hpr run finish <tag>`** is the new terminal gate and the ONLY path to manifest status `done`. It runs the full verification battery and flips the run to `done` on pass or `blocked (verify)` on fail, recording the verdict in the manifest either way. The router's final gate now centers on it, with explicit no-override language (gate errors are fixed by changing the report, never re-interpreted), a bounded 3-round fix loop, and a new invariant: a run is complete only when `finish` reports `passed: true`.
- **`verify_run` now includes the blocking content lints** (`quote-integrity`, `retracted-citations`) in-process, so one command carries the whole verdict and there is no seam where a failing rule can be run separately and argued with.
- **Length enforcement moved upstream too.** Step 11 gains a mechanical word-count gate with the one permitted fix (a single synthesizer compression respawn, cheapest at that moment); the synthesizer's word-target table is now rendered from the profile (it was hardcoded to full-gear numbers, so premier's 8-16K target never reached the prompt) with the high end stated as a hard ceiling; the polish auditor strips quotation marks from non-verbatim rhetorical framing before the gate ever sees them.

### Report register: pedagogy primers, calm citations, and de-AI'd prose

- **Pedagogy primers.** A four-report comparison on bench Q62 (benchmark reference vs. two pipeline generations) showed the judge's only consistent losses were pedagogy and audience adaptation, never coverage or insight: the reference teaches each concept before judging it; our reports open expert-dense. Every major body section now starts with a 3-5 sentence plain-language primer (what the thing is, how it works, why it matters here) before the analysis. Written by the synthesizer (pass-1 requirement + pass-2 structural gate), enforced by a new instruction-critic check (`missing-section-primers`).
- **Calm citation style.** Stacked brackets (`[7][8][79]`) made claim-dense prose read like a parts list. New style: one citation point per sentence at the sentence end, multiple sources grouped in a single bracket (`[7, 12]`, capped at 3), same-source sentence runs consolidated to one marker, and number-bearing or quoting sentences always keeping their own anchor so cite-check pair verification stays exact. All four mechanical consumers understand grouped markers (cite-check triage splits them into per-source pairs; `run verify` citation density counts cited sources rather than brackets, so grouping never lowers measured density; the quote/numeric lint strips them; style-preservation accepts them). The polish auditor's one permitted citation edit is merging an adjacent stack into a grouped bracket, numbers verbatim.
- **Register discipline, distilled from a humanization ruleset.** The synthesizer's pass-2 audit and the polish auditor now target the two loudest machine-writing tells in past reports: meta-descriptive text (narrating what the report or section is doing instead of saying it; self-describing prose; section-number cross-references) is deleted on sight, and hedging is restricted to unverified specifics — provenance-stated scoping stays, but conclusions the report argues for are asserted bare, and hedge-stacks ("may potentially indicate") always collapse. Dramatic standalone kicker sentences are rationed to one per section, and the primers double as rhythm breaks so density stays readable.

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

## [0.8.7] - 2026-07-18

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
