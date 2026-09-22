# AnySearch integration

[AnySearch](https://anysearch.com) provides general web search, structured vertical
search, and web-page extraction. Hyperresearch includes a native provider using
the existing `httpx` dependency. It plugs into the existing research/fetch
commands; advanced discovery and batch operations are Python methods on the
same provider.

## Setup

No extra package or account is required. Without a key, calls use anonymous
access, which has lower quotas and rate limits. For authenticated access, set
your existing key in the environment:

```bash
export ANYSEARCH_API_KEY="your-api-key"
```

Keys stay in the environment; do not commit them to the repository or put them
in a vault's config. A rejected key is reported as an error; the integration
does not silently switch to anonymous access or register an account.

To make AnySearch the default provider for `hpr research`, `hpr fetch`,
`hpr fetch-batch`, and the existing MCP `fetch_url` tool, edit
`.hyperresearch/config.toml` after initializing a vault:

```toml
[web]
provider = "anysearch"
```

To install the Claude Code research workflow with AnySearch, run:

```bash
hpr init .  # first-time vault initialization only
hpr config set web.provider anysearch
hpr install
```

Installation preserves the selected API provider and skips local Chromium
setup. You can also use `hpr install --skip-browser` to install the vault and
Claude Code skills before choosing a provider. If an older installer appears
stuck downloading Chromium, interrupt it, then rerun with `--skip-browser`.
The flag skips the first-time browser setup wizard as well; it does not change
the selected provider.

Alternatively, pass `--provider anysearch` for one command. Other providers and
the default provider are unchanged. The `research`, `fetch`, and `fetch-batch`
commands use `[fetch] page_timeout_ms` for AnySearch requests, including search
and subsequent extraction. Direct Python calls use a 30-second timeout unless
a `FetchSettings` instance is supplied.

Content checks use the vault's `[junk]` settings, including minimum content
length and additional junk/login signals, for both extraction fallback and
research's save-time login check. Python callers can pass `gates=JunkGates(...)`
to `AnySearchProvider` or `get_provider` to customize the same checks.

## General search

Use the existing research command from an initialized vault:

```bash
hpr research "quantum computing error correction" --provider anysearch --max 5 --json
```

With AnySearch, `--max` accepts 1–10 results and defaults to 5. Research searches,
attempts page extraction, and saves the resulting content to the vault. Each
result adds an Extract request. If a page fails to extract, is empty, or is
detected as a login/bot/error page, the original search excerpt is retained.
Successfully extracted content is limited to 8,000 characters. An excerpt or a
clipped page is not proof that the full source was read.

For discovery without saving notes or extracting pages, use the provider in
Python. This works outside a vault:

```python
from hyperresearch.web.anysearch_provider import AnySearchProvider

provider = AnySearchProvider(fetch_content=False)
results = provider.search("open source research agents", max_results=5, zone="intl", language="en")
for result in results:
    print(result.title, result.url, result.content)
```

Omit `fetch_content=False` to extract result pages. Results are `WebResult`
objects containing URL, title, content, retrieval time, and provider metadata.
The API's response-level search metadata (such as `total_results` and
`search_time_ms`) is preserved in each result's `metadata["anysearch_metadata"]`,
separately from the individual result's metadata. This also applies to batch
search results and searches that extract page text.

## Vertical search

First discover available tags and parameter schemas for the relevant domains.
The directory is live; do not guess a tag or assume its parameters stay fixed.
Common domains include `academic`, `code`, `finance`, `legal`, and `health`;
up to five can be requested together:

```python
from hyperresearch.web.anysearch_provider import AnySearchProvider

provider = AnySearchProvider(fetch_content=False)
capabilities = provider.get_sub_domains(["code", "academic"])
print(capabilities)
```

Then use a returned tag and its required parameters. For example, if the
directory lists `code.doc` with the required `library` parameter:

```python
results = provider.search(
    "HTTP client timeouts",
    tag="code.doc",
    params={"library": "httpx"},
    max_results=3,
)
```

`params` must be a dictionary of JSON-compatible values and requires `tag`. Include every required
parameter from discovery; preserve empty string values when a required field
does not apply. Reuse discovery results during a research session.

## Parallel batch search

Call `batch_search` with 1–5 query dictionaries:

```python
from hyperresearch.web.anysearch_provider import AnySearchProvider

provider = AnySearchProvider(fetch_content=False)
batches = provider.batch_search([
    {"query": "HTTP client retry strategies", "max_results": 3},
    {"query": "HTTP client connection pooling", "max_results": 3},
])
for batch in batches:
    if "error" in batch:
        print(batch["query"], batch["error"])
    else:
        for result in batch["results"]:
            print(batch["query"], result.title, result.url)
```

Each item supports `query`, `max_results`, `tag`, `params`, `zone`, and
`language`. Run capability discovery before choosing vertical tags in a batch.
The implementation sends one independent search request per item, with at most
five requests in flight. Each request consumes its own quota. Omit
`fetch_content=False` to also extract pages: each query's results are extracted
sequentially while queries run concurrently. Each result adds an Extract
request; failed or unusable pages retain their search excerpt.

Output preserves input order. On a partial failure, successful results remain
in the returned list. Each entry has `query` and `results` (a list of
`WebResult` objects); failed searches also have an `error` string. Inspect
those entries before retrying so successful queries are not repeated. Invalid
input raises `ValueError` before sending any search requests.

## Extract and store pages

Use the normal fetch path to extract page text and persist it with source
provenance in the vault:

```bash
hpr fetch "https://www.python.org/about/" --provider anysearch --json
hpr fetch-batch "https://www.python.org/about/" "https://www.python.org/doc/" \
  --provider anysearch --json
```

These commands retain Hyperresearch's duplicate detection, content quality
gates, note indexing, and handling of untrusted external source text. A short
or blocked page can be rejected by the normal quality gates even when the API
request succeeds. `fetch-batch` uses the existing per-URL fallback; the Python
`batch_search` method above is the concurrent search path.

When Extract returns a canonical or redirected URL, `WebResult.url` retains
that returned URL for redirect checks. `metadata["requested_url"]` records the
URL passed by the caller. Batch fetching uses the requested URL for saved
source provenance and duplicate detection, so repeating the same original URL
does not refetch it.

Extract supports HTML/XHTML, plain text, JSON, and Markdown. It does not support
PDF, DOC/DOCX, images, audio/video, archives, or other binary formats. Use
`--provider builtin` or `--provider crawl4ai` for Hyperresearch's PDF lane.
The provider caps extracted content at 8,000 characters, following the existing
Serply and Exa provider defaults. Python callers can select another positive
limit with `AnySearchProvider(max_characters=16000)`. The API itself can truncate
HTML/plain text at 50,000 characters and rejects oversized JSON/Markdown.
Review source completeness before citing it.

## Use with the research pipeline

The provider setting controls Hyperresearch commands; Claude Code's own
`WebSearch` tool is separate. To use AnySearch for a pipeline's discovery wave,
use `hpr research --provider anysearch` to search and save sources. For vertical
or batch discovery, call the provider's Python methods above, choose relevant
URLs, then use the normal fetch commands to store their page text. The
`AnySearchProvider` module is included in the installed package.

## Development and maintenance

- `src/hyperresearch/web/anysearch_provider.py` implements the existing
  `WebProvider` protocol (`search` and `fetch`) plus `get_sub_domains` and
  `batch_search`. The factory in `web/base.py` registers `anysearch`.
- The search-to-extraction flow follows the accepted
  [Serply provider PR #121](https://github.com/jordan-gibbs/hyperresearch/pull/121):
  fetch page text, keep the excerpt on fetch/quality failure, preserve search
  metadata, and cap extracted text. Python callers can use
  `AnySearchProvider(fetch_content=False)` for search-only requests.
- All AnySearch operations live in the provider module. Existing `research`,
  `fetch`, and `fetch-batch` commands reach it through `get_provider`; no
  provider-specific CLI module, separate SDK, or MCP dependency is needed.
- REST calls use `https://api.anysearch.com/v1/search`, `/v1/sub-domains`, and
  `/v1/extract`. Authentication is optional Bearer auth. The
  `X-Anysearch-Client: hyperresearch` header identifies this integration.
- The provider checks HTTP status and any explicit API envelope `code`, reports
  request IDs when available, rejects malformed responses, and closes each
  HTTP client after its request. There are no automatic retries on rate limits.
  A successful response may omit `code` when its data is valid; an explicit
  nonzero or null code, HTTP failure, or malformed data is still rejected.
- Tests use offline HTTP transports to exercise real request construction,
  normalization, batch concurrency, and error handling. The existing CLI test
  module verifies research/fetch errors and vault persistence. These tests
  require no key or internet access for AnySearch.

```bash
python -m pytest tests/test_web/test_anysearch_provider.py tests/test_cli/test_commands.py
ruff check src/ tests/
python -m pytest tests/
python -m build
```

API references: [official interface specification](https://github.com/anysearch-ai/anysearch-skill/blob/main/scripts/shared/doc_spec.md)
and [official REST client](https://github.com/anysearch-ai/anysearch-skill/blob/main/scripts/anysearch_cli.py).
