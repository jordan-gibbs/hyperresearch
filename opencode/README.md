# OpenCode adapter (community integration)

<img src="assets/logo.svg" alt="hyperresearch-opencode" width="80" />

This directory renders the hyperresearch pipeline into **native OpenCode**
skills, subagents, commands and configuration. OpenCode is not currently an
officially supported harness, so this is a non-invasive adapter: it reads the
files produced by `hyperresearch install` and translates them. Nothing in
`src/hyperresearch/` or the existing Claude Code / Codex installs is changed.

The standalone repository is
[hyperresearch-opencode](https://github.com/zabdax/hyperresearch-opencode).

## Install from this checkout

1. Install and render the upstream pipeline as usual:

   ```bash
   python -m venv .venv
   source .venv/bin/activate          # Windows: .venv\Scripts\activate
   pip install -e .
   hyperresearch install . --target all --json
   ```

2. Render the OpenCode files:

   ```bash
   python opencode/build_opencode.py --scope global --repo .
   python opencode/test_opencode.py --repo . --scope global
   ```

   `--scope global` writes to `~/.config/opencode` so `/hyperresearch` and the
   router work from any directory. `--scope project --project <dir>` writes a
   project-local `.opencode/` instead. `--repo` may be omitted when run from
   this checkout; it can also be supplied with `HYPERRESEARCH_REPO`.

3. Run `/reload` in OpenCode (or start a new session). A skill body already
   loaded into a session stays cached until reload.

## Use it

From any directory:

```text
/hyperresearch <your research question>
```

Ask for deep research in plain language and the global routing instructions
load the router as well. `@hyperresearch` loads it explicitly. The vault is
created in the current project on first use; the report lands at
`research/notes/final_report_<vault_tag>.md`.

## What it translates

| Upstream / Claude Code | OpenCode |
|---|---|
| `Skill(skill: "x")` | `skill(id: "x")` |
| `Task` subagent dispatch | `subagent` tool (`agent`, `description`, `prompt`) |
| `TodoWrite` | `todowrite` (`experimental.todo`) |
| `Read` / `Write` / `Edit` / `Bash` | `read` / `write` / `edit` / `shell` |
| Claude-in-Chrome MCP fetcher | OpenCode Desktop `browser` namespace |
| Bash `for` / `test -f` snippets | `artifact_gate.py` / `patch_skip_log.py` |

The global config merge preserves existing MCP servers and other settings.

## Tests

```bash
python opencode/build_opencode.py --scope global --repo .
python opencode/test_opencode.py --repo . --scope global
python opencode/build_opencode.py --scope project --repo . --project .
python opencode/test_opencode.py --repo . --scope project --project .
```

The tests verify all 19 skill IDs, 16 subagents, frontmatter, config merging,
CLI path correctness, absence of stale Claude-only tokens, and boot a vault in
a temporary directory.

## Limitations

- OpenCode's `edit` permission also covers `write`, so edit-only locks are
  best-effort; permissions still block shell/web/nested subagents.
- No native Stop hook; the router tells the orchestrator not to end the turn
  while background subagents run, and `run finish` remains the gate.
- Subagents inherit the session model; profile model pins are not carried over.
- The browser lane needs OpenCode Desktop with a browser attached.
- Generated files contain an absolute CLI path; re-render after a move or a
  profile/gear change.

See the [standalone repository](https://github.com/zabdax/hyperresearch-opencode)
for the full README, CI and contribution guide.
