# Selecting sources by scholarly metadata

Use the metadata already stored in your vault to select evidence or find sources
that need another check. These filters work with text search and with the MCP
`search_notes` tool. All supplied filters are combined with AND.

```bash
# Find matching sources explicitly marked as not retracted, with at least 20 citations.
hpr search "retrieval" --retraction not-retracted --min-citations 20 -j

# Locate a source by its stored DOI (or arXiv ID), without a text query.
hpr search --doi '10.1234/example' -j

# Inspect recovered manuscript versions before using them in a report.
hpr search --oa-version submittedVersion -j

# Find notes whose retraction status has not been checked.
hpr search --retraction unchecked -j
```

| CLI option | MCP argument | Meaning |
|---|---|---|
| `--doi` | `doi` | Exact stored DOI or arXiv ID, case-insensitive |
| `--venue` | `venue` | Exact stored publication venue, case-insensitive |
| `--min-citations` | `min_citations` | Known citation count at least this nonnegative number |
| `--retraction` | `retraction` | `retracted`, `not-retracted`, or `unchecked` |
| `--oa-version` | `oa_version` | `submittedVersion`, `acceptedVersion`, or `publishedVersion` |

`not-retracted` matches explicit `is_retracted: false` metadata; an absent status
is **unchecked**, not an assurance. Similarly, `--min-citations 0` excludes notes
without a known citation count. Citation counts do not establish evidence quality.

`oa_version` describes the **retrieved text**, not necessarily the current
publication status of the paper. A submitted manuscript may later have been
published. Missing version metadata does not match a version filter.

Search results include `doi`, `venue`, `citation_count`, `is_retracted` (JSON
`true`, `false`, or `null`), and `oa_version`, so agents can inspect the reason a
source matched. Omit the text query to browse matching metadata; at least one
filter is required. These results are ordered by note creation time, newest
first, with ID as the tie-breaker, and support `--limit` and `--offset`.

With `--semantic`, a text query is required and the same filters constrain both
keyword and embedding matches before the result limit. Filtering performs no
external requests; it uses existing frontmatter metadata. Enrich or update the
source notes when fresher metadata is needed.

## Existing vaults

The SQLite cache upgrades automatically. Older caches stored unchecked and
explicitly false retraction states identically; the upgrade marks these entries
unknown and invalidates their sync fingerprints. The next normal sync restores
the exact states from Markdown without modifying the source files. If automatic
sync is disabled, run `hpr sync` before relying on the filters. Related claims,
embeddings, and links are retained during the upgrade.
