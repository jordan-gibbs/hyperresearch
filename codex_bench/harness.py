#!/usr/bin/env python3
"""
DeepResearch-Bench harness for hyperresearch on OpenAI Codex CLI.

Each benchmark query runs in its own throwaway project under
codex_bench/runs/query_<id>/: `git init`, `hyperresearch install . --target
codex`, the verbatim prompt in research/prompt.txt, then one
`codex exec` session that is told to run `$hyperresearch`. The harness
records the report plus pipeline-adherence metrics (vault notes, run
manifest steps, subagent spawns, `run verify`) so an inline answer that
skipped the pipeline shows up as PIPELINE_SKIPPED instead of a "result".

Usage:
    python codex_bench/harness.py --download-only           # fetch query.jsonl
    python codex_bench/harness.py --query-id 52 --dry-run   # set up, print the codex command
    python codex_bench/harness.py --query-id 52             # run one query
    python codex_bench/harness.py --limit 5 --only-en       # first 5 English queries
    python codex_bench/harness.py --resume                  # skip ids with a result.json
    python codex_bench/harness.py --summary                 # adherence table
    python codex_bench/harness.py --export                  # RACE-compatible JSONL

Prerequisites: codex CLI installed and logged in (`codex --version`,
`codex login`); hyperresearch installed (the repo's .venv or PATH) at a
version that supports `install --target codex`.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BENCH_DIR.parent
DATA_DIR = BENCH_DIR / "data"
RESULTS_DIR = BENCH_DIR / "results"
RUNS_DIR = BENCH_DIR / "runs"
QUERY_FILE = DATA_DIR / "query.jsonl"
QUERY_URL = "https://raw.githubusercontent.com/Ayanami0730/deep_research_bench/main/data/prompt_data/query.jsonl"

DEFAULT_TIMEOUT_S = 3 * 3600

# ---------------------------------------------------------------------------
# Prompt. Mirrors bench/harness.py's PIPELINE_RESEARCH_PROMPT (the Claude
# run): the query goes to the pipeline's entry skill, research/prompt.txt is
# the gospel copy, research/wrapper_contract.json forces inline citations.
# Codex-specific additions: invoke `$hyperresearch` (with a read-the-file
# fallback, since discovery can lag), and an explicit statement that an
# inline answer is a failure — the April 2026 attempt did exactly that.
# ---------------------------------------------------------------------------
RESEARCH_PROMPT = """\
$hyperresearch {prompt}

Run the hyperresearch pipeline on the research request above. The entry skill is
`.agents/skills/hyperresearch/SKILL.md`; if its instructions are not already loaded,
read that file in full before doing anything else and follow it step by step, reading
each step file under `.hyperresearch/codex/steps/` when the router tells you to.
Writing the report from your own knowledge, or without fetching sources into the vault
with `hyperresearch fetch`, is a failure of this task: the harness checks the vault
notes and the run manifest (`research/runs/<vault_tag>/run.json`), not just the report.

A canonical copy of the user's exact prompt is stored in `research/prompt.txt`. The
scaffold's `## User Prompt (VERBATIM — gospel)` section must match that file exactly.

The packaging contract is in `research/wrapper_contract.json` and is BINDING. It sets
`citation_style: "inline"`: the report must carry numbered `[N]` markers with a matching
`## Sources` list of real URLs at the end. Vault-internal `[[note-id]]` wikilinks are NOT
acceptable in this deliverable: the benchmark's citation evaluator reads URLs.

Mirror the user's requested structure directly. If the prompt names distinct components,
classes, categories, or entities, create dedicated sections using those names.

The report MUST end with a section titled `## Opinionated Synthesis` containing:
`### Comparative Analysis`, `### Thematic Threads`, `### Reasoned Position`,
`### Open Questions`, `### Concluding Thoughts`.

Save the final report where the pipeline puts it: `research/notes/final_report_<vault_tag>.md`,
relative to the current working directory. This is the file the benchmark harness reads.

This is a non-interactive run. Nobody will answer questions, so do not stop to ask for
confirmation; make the call yourself and keep going until the pipeline's final step is done.

The user's prompt above is GOSPEL at every step. Any drift is a CRITICAL violation.
"""

# Same packaging contract bench/harness.py writes. Step 1 reads it and lets
# it override the vault's default wikilink citation style.
WRAPPER_CONTRACT = {
    "citation_style": "inline",
    "required_terminal_sections": [
        "## Opinionated Synthesis",
        "### Comparative Analysis",
        "### Thematic Threads",
        "### Reasoned Position",
        "### Open Questions",
        "### Concluding Thoughts",
    ],
}

# Log lines that mean the sandbox refused a command. The April run's shell
# calls all died with "rejected: blocked by policy" under a read-only sandbox.
_SANDBOX_REJECTION_RE = re.compile(
    r"blocked by policy|sandbox (?:denied|error)|Access is denied|Operation not permitted|"
    r"Read-only file system",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------

def download_queries() -> bool:
    """Download query.jsonl from the benchmark repo if not present."""
    if QUERY_FILE.exists():
        count = sum(1 for _ in QUERY_FILE.open(encoding="utf-8"))
        print(f"[OK] query.jsonl already exists ({count} queries)")
        return True

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    print("Downloading query.jsonl from benchmark repo...")
    try:
        import urllib.request

        with urllib.request.urlopen(QUERY_URL, timeout=60) as resp:
            data = resp.read()
        QUERY_FILE.write_bytes(data)
        count = sum(1 for _ in QUERY_FILE.open(encoding="utf-8"))
        print(f"[OK] Downloaded {count} queries to {QUERY_FILE}")
        return True
    except Exception as e:
        print(f"[ERROR] Failed to download queries: {e}")
        return False


def load_queries(only_lang: str | None = None) -> list[dict]:
    queries = []
    with QUERY_FILE.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            if only_lang and item.get("language") != only_lang:
                continue
            queries.append(item)
    return queries


# ---------------------------------------------------------------------------
# Executables
# ---------------------------------------------------------------------------

def _resolve_codex() -> str:
    """Find the codex CLI. On Windows npm installs it as codex.cmd."""
    which = shutil.which("codex")
    if which:
        return which
    candidates = [
        Path.home() / "AppData" / "Roaming" / "npm" / "codex.cmd",
        Path.home() / "AppData" / "Roaming" / "npm" / "codex",
        Path("/usr/local/bin/codex"),
        Path("/opt/homebrew/bin/codex"),
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return "codex"


def _resolve_hpr_exe() -> str:
    """The repo's venv hyperresearch if present, else whatever is on PATH."""
    for candidate in (
        PROJECT_ROOT / ".venv" / "Scripts" / "hyperresearch.exe",
        PROJECT_ROOT / ".venv" / "bin" / "hyperresearch",
    ):
        if candidate.exists():
            return str(candidate)
    return shutil.which("hyperresearch") or "hyperresearch"


def _project_gear() -> str | None:
    """The scale gear persisted in the repo's own vault config, if any."""
    cfg = PROJECT_ROOT / ".hyperresearch" / "config.toml"
    if not cfg.exists():
        return None
    try:
        import tomllib

        data = tomllib.loads(cfg.read_text(encoding="utf-8"))
        return data.get("pipeline", {}).get("profile")
    except Exception:
        return None


def _child_env() -> dict:
    """Environment for codex and hyperresearch subprocesses.

    Puts the resolved hyperresearch executable's directory first on PATH so a
    bare `hyperresearch` inside the Codex session hits the same build the run
    dir was installed with.
    """
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    hpr_dir = str(Path(_resolve_hpr_exe()).parent)
    if hpr_dir and hpr_dir != ".":
        env["PATH"] = hpr_dir + os.pathsep + env.get("PATH", "")
    return env


def _hpr_json(args: list[str], cwd: Path, timeout: int = 120) -> tuple[int, dict | None, str]:
    """Run a hyperresearch command with -j/--json and parse its envelope."""
    proc = subprocess.run(
        [_resolve_hpr_exe(), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env=_child_env(),
    )
    out = proc.stdout.strip()
    try:
        data = json.loads(out) if out else None
    except json.JSONDecodeError:
        data = None
    return proc.returncode, data, (proc.stderr or out)[-800:]


# ---------------------------------------------------------------------------
# Run directory setup
# ---------------------------------------------------------------------------

def _fresh_dir(task_id: int) -> Path:
    """Create an empty runs/query_<id>/, falling back to a suffixed dir if
    a prior run left locked files behind (Windows browser handles)."""
    run_dir = RUNS_DIR / f"query_{task_id}"
    if run_dir.exists():
        for _ in range(3):
            try:
                shutil.rmtree(run_dir)
                break
            except OSError:
                time.sleep(1.5)
        if run_dir.exists():
            run_dir = RUNS_DIR / f"query_{task_id}_{datetime.now().strftime('%H%M%S')}"
            print(f"  [WARN] previous run dir locked; using {run_dir.name}")
    run_dir.mkdir(parents=True)
    return run_dir


def setup_run_dir(task_id: int, prompt_text: str, gear: str | None, copy_config: bool) -> tuple[Path, dict]:
    """Build the isolated project Codex will run in.

    git init (Codex treats the git root as the project root, so skill /
    AGENTS.md discovery stops here instead of walking up into this repo),
    then `hyperresearch install . --target codex --json`, which writes the
    vault, AGENTS.md, .agents/skills/hyperresearch/, the step files, the
    .codex/agents/*.toml roster and the Stop hook. Nothing is hand-written.

    The vault is created with an explicit `init` first: codex_bench/runs/
    sits inside this repo, and `install` discovers vaults by walking up, so
    on its own it would adopt the repo's vault and leave the run dir without
    one (every note would then land in the repo's research/).
    """
    run_dir = _fresh_dir(task_id)
    subprocess.run(["git", "init", "-q"], cwd=str(run_dir), capture_output=True, timeout=30)

    rc, data, tail = _hpr_json(["init", ".", "--json"], run_dir, timeout=120)
    if rc != 0 or not (run_dir / ".hyperresearch").is_dir():
        raise RuntimeError(f"`hyperresearch init . --json` failed (exit {rc}): {tail}")

    install_args = ["install", ".", "--target", "codex", "--json"]
    if gear:
        install_args += ["--profile", gear]
    rc, data, tail = _hpr_json(install_args, run_dir, timeout=300)
    if rc != 0 or not data or not data.get("ok"):
        raise RuntimeError(f"`hyperresearch {' '.join(install_args)}` failed (exit {rc}): {tail}")
    vault_path = (data.get("data") or {}).get("vault_path")
    if vault_path and Path(vault_path).resolve() != run_dir.resolve():
        raise RuntimeError(f"install used the vault at {vault_path}, not the run dir")

    # Carry the repo's vault config (web provider, scholar settings, gear)
    # into the run vault, as bench/harness.py does. The install above was
    # already rendered at the same gear, so skills and config agree.
    src_config = PROJECT_ROOT / ".hyperresearch" / "config.toml"
    if copy_config and src_config.exists():
        shutil.copy2(src_config, run_dir / ".hyperresearch" / "config.toml")

    research_dir = run_dir / "research"
    research_dir.mkdir(parents=True, exist_ok=True)
    (research_dir / "prompt.txt").write_text(prompt_text, encoding="utf-8")
    (research_dir / "wrapper_contract.json").write_text(
        json.dumps(WRAPPER_CONTRACT, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    expected = [
        run_dir / ".agents" / "skills" / "hyperresearch" / "SKILL.md",
        run_dir / ".codex" / "hooks.json",
        run_dir / "AGENTS.md",
    ]
    missing = [str(p.relative_to(run_dir)) for p in expected if not p.exists()]
    if missing:
        raise RuntimeError(f"install --target codex did not produce: {', '.join(missing)}")
    return run_dir, data.get("data", {})


# ---------------------------------------------------------------------------
# Codex command
# ---------------------------------------------------------------------------

def build_codex_cmd(args: argparse.Namespace, run_dir: Path) -> list[str]:
    """The `codex exec` invocation. The prompt goes in on stdin (`-`): a
    multi-line argument does not survive codex.cmd's trip through cmd.exe."""
    cmd = [
        _resolve_codex(), "exec",
        "--json",
        "-o", str(run_dir / "last_message.txt"),
        "--skip-git-repo-check",
        "-C", str(run_dir),
    ]
    if args.yolo:
        cmd.append("--dangerously-bypass-approvals-and-sandbox")
    else:
        cmd += [
            "--sandbox", "workspace-write",
            "-c", "sandbox_workspace_write.network_access=true",
        ]
        for extra in _writable_dirs(args):
            cmd += ["--add-dir", extra]
    if args.hook_trust:
        # Project hooks need persisted trust; without this the Stop gate
        # (`hyperresearch run stop-gate`) never fires in a fresh run dir.
        cmd.append("--dangerously-bypass-hook-trust")
    if args.model:
        cmd += ["-m", args.model]
    if args.reasoning_effort:
        cmd += ["-c", f"model_reasoning_effort={args.reasoning_effort}"]
    if args.web_search:
        cmd += ["-c", f"web_search={args.web_search}"]
    if args.ephemeral:
        cmd.append("--ephemeral")
    for override in args.config or []:
        cmd += ["-c", override]
    cmd.append("-")
    return cmd


def _writable_dirs(args: argparse.Namespace) -> list[str]:
    """Extra writable roots for the workspace-write sandbox.

    crawl4ai keeps its state in ~/.crawl4ai; under a workspace-write sandbox a
    write there is outside the workspace. Added automatically when it exists.
    """
    dirs = list(args.add_dir or [])
    if args.auto_add_dirs:
        c4 = Path.home() / ".crawl4ai"
        if c4.exists():
            dirs.append(str(c4))
    return dirs


def _fmt_cmd(cmd: list[str]) -> str:
    return subprocess.list2cmdline(cmd) if os.name == "nt" else " ".join(
        a if re.fullmatch(r"[\w./:=@,+-]+", a) else "'" + a.replace("'", "'\\''") + "'" for a in cmd
    )


def _kill_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
    else:
        proc.kill()


# ---------------------------------------------------------------------------
# Event stream
# ---------------------------------------------------------------------------

class EventStats:
    """Counts from the `codex exec --json` JSONL stream.

    The schema is Codex's (thread.started / turn.* / item.started|completed
    with item.type = agent_message | reasoning | command_execution |
    file_change | web_search | collab_tool_call | ...). Spawns are matched
    loosely (any item whose type or tool name mentions spawn) so a renamed
    multi-agent item still counts.
    """

    def __init__(self) -> None:
        self.thread_id: str | None = None
        self.turns = 0
        self.commands = 0
        self.hpr_calls = 0
        self.fetch_calls = 0
        self.run_step_calls = 0
        self.web_searches = 0
        self.file_changes = 0
        self.spawns = 0
        self.sandbox_rejections = 0
        self.input_tokens = 0
        self.cached_input_tokens = 0
        self.output_tokens = 0
        self.errors: list[str] = []
        self.item_types: dict[str, int] = {}
        self._seen: set[str] = set()

    def as_dict(self) -> dict:
        return {
            "thread_id": self.thread_id,
            "turns": self.turns,
            "commands": self.commands,
            "hyperresearch_calls": self.hpr_calls,
            "fetch_calls": self.fetch_calls,
            "run_step_calls": self.run_step_calls,
            "web_searches": self.web_searches,
            "file_changes": self.file_changes,
            "subagent_spawns": self.spawns,
            "sandbox_rejections": self.sandbox_rejections,
            "tokens": {
                "input": self.input_tokens,
                "cached_input": self.cached_input_tokens,
                "output": self.output_tokens,
            },
            "item_types": self.item_types,
            "errors": self.errors[-5:],
        }

    def feed(self, raw_line: str, elapsed: float, verbose: bool) -> None:
        if _SANDBOX_REJECTION_RE.search(raw_line):
            self.sandbox_rejections += 1
        try:
            event = json.loads(raw_line)
        except json.JSONDecodeError:
            return
        if not isinstance(event, dict):
            return
        etype = event.get("type", "")
        if etype == "thread.started":
            self.thread_id = event.get("thread_id")
        elif etype == "turn.completed":
            self.turns += 1
            usage = event.get("usage") or {}
            self.input_tokens += int(usage.get("input_tokens") or 0)
            self.cached_input_tokens += int(usage.get("cached_input_tokens") or 0)
            self.output_tokens += int(usage.get("output_tokens") or 0)
        elif etype in ("turn.failed", "error"):
            msg = event.get("message") or (event.get("error") or {}).get("message") or str(event)[:300]
            self.errors.append(str(msg)[:300])
            print(f"    [{elapsed:.0f}s] ERROR: {str(msg)[:160]}")
        elif etype in ("item.started", "item.completed"):
            self._item(event.get("item") or {}, etype, elapsed, verbose)

    def _item(self, item: dict, etype: str, elapsed: float, verbose: bool) -> None:
        itype = str(item.get("type", "?"))
        item_id = str(item.get("id", ""))
        first_sight = item_id not in self._seen
        if item_id:
            self._seen.add(item_id)
        if not first_sight and etype == "item.completed" and itype != "agent_message":
            return
        if first_sight:
            self.item_types[itype] = self.item_types.get(itype, 0) + 1

        tool = str(item.get("tool") or item.get("name") or "")
        if first_sight and ("spawn" in tool.lower() or "spawn" in itype.lower()):
            self.spawns += 1
            target = item.get("agent_type") or item.get("receiver_thread_ids") or item.get("prompt") or ""
            print(f"    [{elapsed:.0f}s] spawn: {str(target)[:110]}")
        elif itype == "command_execution" and first_sight:
            self.commands += 1
            command = str(item.get("command", ""))
            if "hyperresearch" in command:
                self.hpr_calls += 1
                if re.search(r"\bfetch\b", command):
                    self.fetch_calls += 1
                if re.search(r"\brun\s+step\b", command):
                    self.run_step_calls += 1
                    print(f"    [{elapsed:.0f}s] {command[-110:]}")
                elif verbose or re.search(r"\b(fetch|search|run\s+(init|finish|verify))\b", command):
                    print(f"    [{elapsed:.0f}s] $ {command[-110:]}")
            elif verbose:
                print(f"    [{elapsed:.0f}s] $ {command[:110]}")
        elif itype == "web_search" and first_sight:
            self.web_searches += 1
            if verbose:
                print(f"    [{elapsed:.0f}s] web_search: {str(item.get('query', ''))[:100]}")
        elif itype == "file_change" and first_sight:
            self.file_changes += 1
        elif itype == "agent_message" and etype == "item.completed":
            text = str(item.get("text", "")).strip()
            if text:
                print(f"    [{elapsed:.0f}s] {text[:120].replace(chr(10), ' ')}")
        elif itype == "error":
            self.errors.append(str(item.get("message", ""))[:300])


# ---------------------------------------------------------------------------
# Adherence metrics
# ---------------------------------------------------------------------------

def _strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[end + 4:].lstrip("\n").strip()
    return text.strip()


def _load_manifests(run_dir: Path) -> list[dict]:
    manifests = []
    runs_root = run_dir / "research" / "runs"
    if not runs_root.is_dir():
        return manifests
    for mpath in runs_root.glob("*/run.json"):
        try:
            m = json.loads(mpath.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(m, dict):
            m.setdefault("vault_tag", mpath.parent.name)
            manifests.append(m)
    manifests.sort(key=lambda m: str(m.get("started_at", "")))
    return manifests


def _find_report(run_dir: Path, tag: str | None) -> Path | None:
    notes = run_dir / "research" / "notes"
    if tag and (notes / f"final_report_{tag}.md").exists():
        return notes / f"final_report_{tag}.md"
    candidates = sorted(notes.glob("final_report_*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    if candidates:
        return candidates[0]
    legacy = notes / "final_report.md"
    return legacy if legacy.exists() else None


def collect_adherence(run_dir: Path) -> dict:
    """What the pipeline actually did, read from disk after the session."""
    notes_dir = run_dir / "research" / "notes"
    notes = [p for p in notes_dir.glob("*.md") if not p.name.startswith("final_report")] if notes_dir.is_dir() else []

    manifests = _load_manifests(run_dir)
    manifest = manifests[-1] if manifests else None
    tag = manifest.get("vault_tag") if manifest else None
    report = _find_report(run_dir, tag)
    if manifest is None and report is not None and report.stem.startswith("final_report_"):
        tag = report.stem[len("final_report_"):]

    info: dict = {
        "notes": len(notes),
        "runs": [m.get("vault_tag") for m in manifests],
        "vault_tag": tag,
        "manifest": manifest is not None,
        "report_file": str(report.relative_to(run_dir)) if report else None,
    }

    if manifest is not None:
        steps = manifest.get("steps", {}) or {}
        profile_steps = [str(s) for s in manifest.get("profile_steps", [])]
        done = [s for s, e in steps.items() if isinstance(e, dict) and e.get("status") == "done"]
        skipped = [s for s, e in steps.items() if isinstance(e, dict) and e.get("status") == "skipped"]
        failed = [s for s, e in steps.items() if isinstance(e, dict) and e.get("status") == "failed"]
        spend = dict(manifest.get("spend") or {})
        spend.pop("estimated_usd", None)  # no dollar figures in bench output
        info.update({
            "run_status": manifest.get("status"),
            "blocked_on": manifest.get("blocked_on"),
            "profile": manifest.get("profile"),
            "steps_done": done,
            "steps_skipped": skipped,
            "steps_failed": failed,
            "steps_not_done": [s for s in profile_steps if s not in done and s not in skipped],
            "manifest_counters": spend,
        })
        decomp = run_dir / "research" / "runs" / str(tag) / "prompt-decomposition.json"
        try:
            info["tier"] = json.loads(decomp.read_text(encoding="utf-8")).get("pipeline_tier")
        except (OSError, json.JSONDecodeError, AttributeError):
            info["tier"] = None

        try:
            _rc, data, tail = _hpr_json(["run", "verify", str(tag), "-j"], run_dir)
            payload = (data or {}).get("data") or {}
            info["verify"] = {
                "passed": bool(payload.get("passed")) if payload else False,
                "failed_checks": [c.get("name") for c in payload.get("checks", []) if not c.get("ok")],
                "error": None if payload else tail[-300:],
            }
        except (OSError, subprocess.TimeoutExpired) as e:
            info["verify"] = {"passed": False, "failed_checks": [], "error": str(e)}

    esc_rc, esc, _ = _safe_hpr(["escalation", "list", "--status", "queued", "-j"], run_dir)
    if esc_rc == 0 and esc:
        items = esc.get("data")
        if isinstance(items, dict):
            items = items.get("escalations") or items.get("items") or []
        info["escalations_queued"] = len(items) if isinstance(items, list) else None
    return info


def _safe_hpr(args: list[str], cwd: Path) -> tuple[int, dict | None, str]:
    try:
        return _hpr_json(args, cwd)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, None, str(e)


def classify(adherence: dict, article: str, last_message: str) -> tuple[str | None, str | None]:
    """(error_code, message) for a finished session, or (None, None)."""
    if not adherence.get("manifest") and adherence.get("notes", 0) == 0:
        answered = len(last_message) > 1500 or bool(article)
        detail = "answered inline" if answered else "no output"
        return "PIPELINE_SKIPPED", (
            f"pipeline never ran: 0 vault notes, no run manifest ({detail})"
        )
    if not article:
        return "NO_REPORT", "pipeline started but no research/notes/final_report_*.md was written"
    return None, None


# ---------------------------------------------------------------------------
# One query
# ---------------------------------------------------------------------------

def _base_result(query: dict, run_dir: Path | None) -> dict:
    return {
        "id": query["id"],
        "prompt": query["prompt"],
        "article": "",
        "error": None,
        "error_code": None,
        "duration_s": 0,
        "run_dir": str(run_dir) if run_dir else None,
    }


def run_single_query(query: dict, args: argparse.Namespace) -> dict:
    task_id = query["id"]
    prompt_text = query["prompt"]

    try:
        run_dir, install_data = setup_run_dir(task_id, prompt_text, args.gear, args.copy_config)
    except Exception as e:
        result = _base_result(query, None)
        result.update(error=f"setup failed: {e}", error_code="SETUP_FAILED")
        return result

    result = _base_result(query, run_dir)
    cmd = build_codex_cmd(args, run_dir)
    # Probe the model-visible context (no model call) for the name Codex
    # listed the entry skill under: a `.codex-plugin/plugin.json` in any
    # ancestor directory namespaces project skills (`<plugin>:hyperresearch`),
    # and this repo ships one, so runs nested under it get a prefixed name.
    probe = _probe_skill_visibility(args, run_dir)
    skill_name = probe.get("skill_name") or "hyperresearch"
    prompt = RESEARCH_PROMPT.format(prompt=prompt_text).replace("$hyperresearch ", f"${skill_name} ", 1)
    (run_dir / "codex_prompt.txt").write_text(prompt, encoding="utf-8")
    (run_dir / "codex_cmd.txt").write_text(_fmt_cmd(cmd) + "\n", encoding="utf-8")
    result["probe"] = probe

    if args.dry_run:
        print(f"  run dir: {run_dir}")
        print(f"  installed: {len(install_data.get('hooks_installed', []))} codex artifacts")
        print("  command (prompt on stdin, saved to codex_prompt.txt):")
        print("    " + _fmt_cmd(cmd))
        print(f"  prompt-input probe: {json.dumps(probe)}")
        print(f"  prompt starts: {prompt.splitlines()[0][:100]}")
        result.update(error="dry run", error_code="DRY_RUN", dry_run={"cmd": cmd})
        return result
    if probe.get("ok") and not probe.get("skill_name"):
        print("  [WARN] hyperresearch skill not listed by Codex; the prompt's read-the-file fallback applies")

    log_file = run_dir / "run.log"
    stats = EventStats()
    timed_out = threading.Event()
    start = time.monotonic()
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(run_dir),
            env=_child_env(),
        )
    except FileNotFoundError:
        result.update(error="codex CLI not found. Install: npm install -g @openai/codex", error_code="CODEX_NOT_FOUND")
        return result

    def _on_timeout() -> None:
        timed_out.set()
        _kill_tree(proc)

    watchdog = threading.Timer(args.timeout, _on_timeout)
    watchdog.daemon = True
    watchdog.start()
    try:
        proc.stdin.write(prompt)
        proc.stdin.close()
        with log_file.open("w", encoding="utf-8") as lf:
            for raw_line in proc.stdout:
                lf.write(raw_line)
                lf.flush()
                line = raw_line.strip()
                if line:
                    stats.feed(line, time.monotonic() - start, args.verbose)
        proc.wait()
    finally:
        watchdog.cancel()
    elapsed = round(time.monotonic() - start, 1)

    last_message_file = run_dir / "last_message.txt"
    last_message = last_message_file.read_text(encoding="utf-8", errors="replace") if last_message_file.exists() else ""
    adherence = collect_adherence(run_dir)
    report_rel = adherence.get("report_file")
    article = _strip_frontmatter((run_dir / report_rel).read_text(encoding="utf-8")) if report_rel else ""

    result.update(
        article=article,
        duration_s=elapsed,
        exit_code=proc.returncode,
        events=stats.as_dict(),
        adherence=adherence,
        last_message_chars=len(last_message),
    )
    code, message = classify(adherence, article, last_message)
    if timed_out.is_set():
        code, message = "TIMEOUT", f"timed out after {args.timeout}s (see {log_file})"
    elif proc.returncode != 0 and code is None:
        code, message = "CODEX_ERROR", f"codex exit code {proc.returncode} (see {log_file})"
    elif proc.returncode != 0:
        message = f"{message}; codex exit code {proc.returncode}"
    result.update(error_code=code, error=message)
    return result


def _probe_skill_visibility(args: argparse.Namespace, run_dir: Path) -> dict:
    """Pre-flight check with `codex debug prompt-input`, which renders the
    model-visible context without calling a model: is the hyperresearch
    skill listed, is AGENTS.md loaded, and does the sandbox config give
    network access?"""
    cmd = [_resolve_codex(), "debug", "prompt-input"]
    if not args.yolo:
        cmd += ["-c", "sandbox_mode=workspace-write", "-c", "sandbox_workspace_write.network_access=true"]
    cmd.append("hi")
    try:
        proc = subprocess.run(
            cmd, cwd=str(run_dir), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=120, env=_child_env(),
        )
        items = json.loads(proc.stdout)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        return {"ok": False, "error": str(e)[:200]}
    text = "\n".join(
        c.get("text", "") for it in items if isinstance(it, dict) for c in it.get("content", []) if isinstance(c, dict)
    )
    listed = re.search(
        r"^- ((?:[\w.-]+:)?hyperresearch): .*\(file: [^)]*hyperresearch[/\\]SKILL\.md\)\s*$", text, re.M
    )
    return {
        "ok": True,
        "skill_name": listed.group(1) if listed else None,
        "agents_md_loaded": "hyperresearch:start" in text,
        "network_enabled": "Network access is enabled" in text or bool(args.yolo),
    }


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

def write_result(result: dict) -> None:
    run_dir = Path(result["run_dir"]) if result.get("run_dir") else RUNS_DIR / f"query_{result['id']}"
    run_dir.mkdir(parents=True, exist_ok=True)
    try:
        git_hash = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5, cwd=str(PROJECT_ROOT),
        ).stdout.strip()
    except Exception:
        git_hash = "unknown"
    record = dict(result)
    record.pop("dry_run", None)
    record["timestamp"] = datetime.now(UTC).isoformat()
    record["git_commit"] = git_hash
    (run_dir / "result.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")


def collect_results() -> list[dict]:
    results = []
    if not RUNS_DIR.exists():
        return results
    for run_dir in sorted(RUNS_DIR.iterdir()):
        result_file = run_dir / "result.json"
        if result_file.exists():
            try:
                r = json.loads(result_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if r.get("error_code") != "DRY_RUN":
                results.append(r)
    results.sort(key=lambda x: x.get("id", 0))
    return results


def export_benchmark_jsonl(export_file: Path) -> None:
    """RACE-compatible JSONL ({id, prompt, article}); errored runs excluded."""
    results = collect_results()
    records = [
        {"id": r["id"], "prompt": r["prompt"], "article": r["article"]}
        for r in results
        if r.get("article") and not r.get("error")
    ]
    export_file.parent.mkdir(parents=True, exist_ok=True)
    with export_file.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\n[OK] Exported {len(records)} results to {export_file}")
    skipped = [(r["id"], r.get("error_code")) for r in results if r.get("error") or not r.get("article")]
    if skipped:
        print(f"[SKIP] Not exported: {skipped}")


def print_summary() -> None:
    results = collect_results()
    if not results:
        print("\n[No results found in codex_bench/runs/]")
        return
    ok = [r for r in results if r.get("article") and not r.get("error")]
    print("\n" + "=" * 96)
    print("CODEX BENCHMARK SUMMARY")
    print("=" * 96)
    print(f"{'id':>4}  {'status':<17} {'min':>5} {'words':>6} {'notes':>5} {'tier':<6} {'steps':>7} {'spawns':>6} {'verify':<7}")
    for r in results:
        a = r.get("adherence") or {}
        e = r.get("events") or {}
        done = len(a.get("steps_done", []))
        total = done + len(a.get("steps_not_done", [])) + len(a.get("steps_skipped", []))
        verify = a.get("verify") or {}
        # Records without an adherence block predate this harness (April 2026).
        status = r.get("error_code") or ("OK" if "adherence" in r else "LEGACY")
        print(
            f"{r['id']:>4}  {status:<17} {r.get('duration_s', 0) / 60:>5.0f} "
            f"{len(r.get('article', '').split()):>6} {a.get('notes', 0):>5} {a.get('tier') or '-'!s:<6} "
            f"{(f'{done}/{total}' if a.get('manifest') else '-'):>7} {e.get('subagent_spawns', 0):>6} "
            f"{('pass' if verify.get('passed') else ('FAIL' if verify else '-')):<7}"
        )
    print("-" * 96)
    print(f"  Total: {len(results)}   OK: {len(ok)}   Failed: {len(results) - len(ok)}")
    skipped = [r["id"] for r in results if r.get("error_code") == "PIPELINE_SKIPPED"]
    if skipped:
        print(f"  PIPELINE_SKIPPED: {skipped}")
    print("=" * 96)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _export_name(args: argparse.Namespace) -> str:
    return f"hyperresearch-codex-{args.model or 'default'}.jsonl"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run DeepResearch-Bench on hyperresearch + OpenAI Codex CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python codex_bench/harness.py --download-only
  python codex_bench/harness.py --query-id 52 --dry-run
  python codex_bench/harness.py --query-id 52 --query-id 61 -m gpt-5.5 --reasoning-effort high
  python codex_bench/harness.py --limit 3 --only-en --resume
  python codex_bench/harness.py --summary
  python codex_bench/harness.py --export
        """,
    )
    sel = parser.add_argument_group("query selection")
    sel.add_argument("--query-id", type=int, action="append", help="Run this benchmark id (repeatable)")
    sel.add_argument("--limit", type=int, default=None, help="Max number of queries to run")
    sel.add_argument("--offset", type=int, default=0, help="Skip the first N queries")
    sel.add_argument("--only-en", action="store_true", help="English queries only")
    sel.add_argument("--only-zh", action="store_true", help="Chinese queries only")
    sel.add_argument("--resume", action="store_true", help="Skip ids that already have a result.json")

    cx = parser.add_argument_group("codex")
    cx.add_argument("-m", "--model", default=None, help="Codex model (default: unset, Codex's configured default)")
    cx.add_argument(
        "--reasoning-effort", choices=["minimal", "low", "medium", "high", "xhigh"], default=None,
        help="Passed as -c model_reasoning_effort=<value>",
    )
    cx.add_argument(
        "--web-search", choices=["live", "cached", "disabled"], default=None,
        help="Passed as -c web_search=<value> (default: unset, Codex's default)",
    )
    cx.add_argument(
        "--yolo", action="store_true",
        help="--dangerously-bypass-approvals-and-sandbox instead of the workspace-write + network sandbox. "
             "Only in a throwaway run dir; use if sandboxed fetches fail with permission errors.",
    )
    cx.add_argument("--add-dir", action="append", help="Extra writable root for the sandbox (repeatable)")
    cx.add_argument(
        "--no-auto-add-dirs", dest="auto_add_dirs", action="store_false",
        help="Do not add ~/.crawl4ai as a writable root automatically",
    )
    cx.add_argument(
        "--no-hook-trust", dest="hook_trust", action="store_false",
        help="Omit --dangerously-bypass-hook-trust (the Stop gate will then not run in a fresh run dir)",
    )
    cx.add_argument("--ephemeral", action="store_true", help="Do not persist the Codex session to disk")
    cx.add_argument("-c", "--config", action="append", help="Extra `codex exec -c key=value` override (repeatable)")
    cx.add_argument(
        "--timeout", type=int, default=DEFAULT_TIMEOUT_S,
        help=f"Per-query timeout in seconds (default {DEFAULT_TIMEOUT_S} = 3h; light-tier queries finish well inside it)",
    )

    hr = parser.add_argument_group("hyperresearch")
    hr.add_argument(
        "--gear", default=None,
        help="Scale gear for `install --profile` (default: the gear persisted in this repo's .hyperresearch/config.toml)",
    )
    hr.add_argument(
        "--no-copy-config", dest="copy_config", action="store_false",
        help="Do not copy this repo's .hyperresearch/config.toml into each run vault",
    )

    mode = parser.add_argument_group("modes")
    mode.add_argument("--download-only", action="store_true", help="Download query.jsonl and exit")
    mode.add_argument("--dry-run", action="store_true",
                      help="Set up the run dir(s) via install and print the exact codex command without running it")
    mode.add_argument("--export", action="store_true", help="Write RACE-compatible JSONL from existing results and exit")
    mode.add_argument("--summary", action="store_true", help="Print the adherence summary of existing results and exit")
    mode.add_argument("--verbose", action="store_true", help="Echo every command and web search from the event stream")
    args = parser.parse_args()

    if not download_queries():
        sys.exit(1)
    if args.download_only:
        return
    if args.export:
        export_benchmark_jsonl(RESULTS_DIR / _export_name(args))
        return
    if args.summary:
        print_summary()
        return

    if args.gear is None:
        args.gear = _project_gear()

    lang = "en" if args.only_en else ("zh" if args.only_zh else None)
    queries = load_queries(only_lang=lang)
    if args.query_id:
        wanted = set(args.query_id)
        queries = [q for q in load_queries() if q["id"] in wanted]
        missing = wanted - {q["id"] for q in queries}
        if missing:
            print(f"[ERROR] Query id(s) not found: {sorted(missing)}")
            sys.exit(1)
    else:
        queries = queries[args.offset:]
        if args.limit is not None:
            queries = queries[: args.limit]

    if args.resume and not args.dry_run:
        done_ids = {r["id"] for r in collect_results()}
        before = len(queries)
        queries = [q for q in queries if q["id"] not in done_ids]
        print(f"[RESUME] Skipping {before - len(queries)} completed queries, {len(queries)} remaining")
    if not queries:
        print("[OK] Nothing to run.")
        print_summary()
        return

    codex_bin = _resolve_codex()
    try:
        ver = subprocess.run([codex_bin, "--version"], capture_output=True, text=True, timeout=30)
        print(f"[OK] Codex CLI: {ver.stdout.strip() or ver.stderr.strip()} ({codex_bin})")
    except (FileNotFoundError, subprocess.TimeoutExpired):
        print(f"[ERROR] codex CLI not found at '{codex_bin}'. Install: npm install -g @openai/codex")
        sys.exit(1)
    print(f"[OK] hyperresearch: {_resolve_hpr_exe()}  gear={args.gear or 'default'}")
    sandbox = "none (--yolo)" if args.yolo else "workspace-write + network"
    print(
        f"\nRunning {len(queries)} quer{'y' if len(queries) == 1 else 'ies'}: model={args.model or 'codex default'}, "
        f"effort={args.reasoning_effort or 'default'}, sandbox={sandbox}, timeout={args.timeout}s"
        f"{' [DRY RUN]' if args.dry_run else ''}"
    )
    print(f"Run dirs: {RUNS_DIR}\n")

    for i, query in enumerate(queries, 1):
        preview = query["prompt"][:80].replace("\n", " ")
        print(f"[{i}/{len(queries)}] Query #{query['id']} ({query.get('language', '?')}, {query.get('topic', '')}): {preview}...")
        result = run_single_query(query, args)
        if args.dry_run:
            if result.get("error_code") == "SETUP_FAILED":
                print(f"  SETUP_FAILED: {result['error'][:300]}")
            continue
        write_result(result)
        a = result.get("adherence") or {}
        if result.get("error"):
            print(f"  {result['error_code']} ({result.get('duration_s', 0):.0f}s): {result['error'][:160]}")
        else:
            print(
                f"  OK: {len(result['article'].split())} words, {a.get('notes', 0)} notes, "
                f"tier={a.get('tier')}, verify={'pass' if (a.get('verify') or {}).get('passed') else 'FAIL'}, "
                f"{result.get('duration_s', 0) / 60:.0f} min"
            )

    if not args.dry_run:
        print_summary()


if __name__ == "__main__":
    main()
