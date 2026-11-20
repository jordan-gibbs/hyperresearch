#!/usr/bin/env python3
"""Structural + CLI smoke tests for a rendered hyperresearch OpenCode install.

Usage:
    python test_opencode.py --repo F:/hyperresearch-skill --scope global
    python test_opencode.py --repo F:/hyperresearch-skill --scope project --project F:/hyperresearch-skill

Checks the rendered files, config merge, translation fidelity, and boots a
vault in a temporary directory to prove the CLI works from any location.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

EXPECTED_SKILLS = {
    "hyperresearch",
    "hyperresearch-1-decompose",
    "hyperresearch-1-5-chapter-partition",
    "hyperresearch-2-width-sweep",
    "hyperresearch-3-contradiction-graph",
    "hyperresearch-4-loci-analysis",
    "hyperresearch-5-depth-investigation",
    "hyperresearch-6-cross-locus-reconcile",
    "hyperresearch-7-source-tensions",
    "hyperresearch-8-corpus-critic",
    "hyperresearch-9-evidence-digest",
    "hyperresearch-10-triple-draft",
    "hyperresearch-11-synthesize",
    "hyperresearch-12-critics",
    "hyperresearch-13-gap-fetch",
    "hyperresearch-14-patcher",
    "hyperresearch-14-5-cite-check",
    "hyperresearch-15-polish",
    "hyperresearch-16-readability-audit",
}

STALE_TOKENS = (
    "Skill(skill:",
    "subagent_type:",
    "TodoWrite",
    "ToolSearch",
    "```bash",
    "for f in research/runs",
    "test -f",
)

failures: list[str] = []
checks = 0


def check(condition: bool, message: str) -> None:
    global checks
    checks += 1
    status = "PASS" if condition else "FAIL"
    print(f"  {status}  {message}")
    if not condition:
        failures.append(message)


def detect_repo() -> Path | None:
    env = os.getenv("HYPERRESEARCH_REPO")
    if env:
        return Path(env).expanduser().resolve()
    script_dir = Path(__file__).resolve().parent
    for candidate in (script_dir, script_dir.parent):
        if (candidate / ".claude" / "skills").is_dir():
            return candidate
    return None


def cli_for(repo: Path) -> Path:
    bin_dir = repo / ".venv" / ("Scripts" if sys.platform == "win32" else "bin")
    cli = bin_dir / ("hyperresearch.exe" if sys.platform == "win32" else "hyperresearch")
    if not cli.is_file():
        on_path = shutil.which("hyperresearch")
        if on_path:
            return Path(on_path)
    return cli


def run_cli(cli: Path, args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(cli), *args], cwd=str(cwd), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=120,
    )


def test_install(base: Path, scope: str, repo: Path, adapter: Path, global_root: Path) -> None:
    print(f"\n[{scope}] structure: {base}")
    skills = base / "skills"
    agents = base / "agents"
    commands = base / "commands"

    found = {p.parent.name for p in skills.glob("*/SKILL.md")}
    check(found == EXPECTED_SKILLS, f"19 expected skill IDs (found {len(found)})")
    check(all((skills / sid / "SKILL.md").is_file() for sid in EXPECTED_SKILLS), "every step SKILL.md exists")

    agent_files = sorted(agents.glob("hyperresearch-*.md"))
    check(len(agent_files) == 16, f"16 subagents (found {len(agent_files)})")
    for agent in agent_files:
        head = "\n".join(agent.read_text(encoding="utf-8").splitlines()[:30])
        check("mode: subagent" in head and "permissions:" in head, f"{agent.name}: mode + permissions")

    check((commands / "hyperresearch.md").is_file(), "/hyperresearch command exists")

    print(f"\n[{scope}] content translation")
    stale: list[str] = []
    for path in [*skills.glob("*/SKILL.md"), *agent_files]:
        text = path.read_text(encoding="utf-8")
        for token in STALE_TOKENS:
            if token in text:
                stale.append(f"{path.name}: {token}")
    check(not stale, f"no stale Claude/Codex tokens ({'; '.join(stale[:3]) or 'clean'})")

    cli = cli_for(repo).as_posix()
    entry_text = (skills / "hyperresearch" / "SKILL.md").read_text(encoding="utf-8")
    check(cli in entry_text, f"entry points at the CLI from --repo ({cli})")
    check('skill(id: "hyperresearch-1-decompose")' in entry_text, "entry uses skill(id:) routing")
    check("subagent" in entry_text.lower() and "todowrite" in entry_text, "entry documents subagent + todowrite")

    if scope == "global":
        print("\n[global] configuration")
        cfg = global_root / "opencode.jsonc"
        if not cfg.exists():
            cfg = global_root / "opencode.json"
        check(cfg.is_file(), f"global config exists: {cfg}")
        if cfg.is_file():
            try:
                data = json.loads(cfg.read_text(encoding="utf-8"))
            except ValueError:
                data = {}
            check(data.get("experimental", {}).get("todo") is True, "experimental.todo enabled")
            resources = {r.get("resource") for r in data.get("permissions", []) if isinstance(r, dict)}
            check("hyperresearch*" in resources and "hyperresearch-*" in resources, "skill + subagent permissions present")
            check(any("OPENCODE_INSTRUCTIONS.md" in str(i) for i in data.get("instructions", [])),
                  "global routing instructions registered")
        check((adapter / "OPENCODE_INSTRUCTIONS.md").is_file(), "instructions template exists")
        check("GLOBALLY" in entry_text or "Global install" in entry_text, "entry explains global-vault behaviour")
    else:
        check((base.parent / "opencode.jsonc").is_file(), "project opencode.jsonc exists")
        check("<!-- opencode-adapter:start -->" in (base.parent / "AGENTS.md").read_text(encoding="utf-8"),
              "AGENTS.md has OpenCode section")


def test_cli(repo: Path) -> None:
    print("\n[cli] bootstrap from an arbitrary directory")
    cli = cli_for(repo)
    tmp = Path(tempfile.mkdtemp(prefix="hyperresearch-opencode-test-"))
    try:
        version = run_cli(cli, ["--version"], tmp)
        check(version.returncode == 0 and "hyperresearch" in version.stdout.lower(),
              f"CLI --version ({(version.stdout or version.stderr).strip()[:50]})")
        init = run_cli(cli, ["init", ".", "--json"], tmp)
        check(init.returncode == 0, "vault init in temp directory")
        check((tmp / ".hyperresearch").is_dir() and (tmp / "research").is_dir(), "vault + research dirs created")
        tag_result = run_cli(cli, ["vault-tag", "opencode-smoke", "--json"], tmp)
        check(tag_result.returncode == 0, "vault-tag command")
        tag = ""
        if tag_result.returncode == 0:
            try:
                tag = json.loads(tag_result.stdout)["data"]["vault_tag"]
            except (ValueError, KeyError):
                pass
        check(bool(tag), f"parsed vault_tag ({tag or 'none'})")
        if tag:
            run_init = run_cli(cli, ["run", "init", tag, "--profile", "light", "--json"], tmp)
            check(run_init.returncode == 0, "run init")
            check((tmp / "research" / "runs" / tag / "run.json").is_file(), "run manifest created")
            (tmp / "research" / "runs" / tag / "query.md").write_text("smoke test query", encoding="utf-8")
            check(run_cli(cli, ["run", "step", tag, "1", "--status", "done", "-j"], tmp).returncode == 0,
                  "run step recorded")
            check(run_cli(cli, ["run", "status", tag, "-j"], tmp).returncode == 0, "run status readable")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", type=Path, default=None)
    parser.add_argument("--scope", choices=("global", "project"), default="global")
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--global-dir", type=Path, default=Path.home() / ".config" / "opencode")
    args = parser.parse_args()

    repo = (args.repo or detect_repo())
    if repo is None:
        print("error: pass --repo <path> or set HYPERRESEARCH_REPO", file=sys.stderr)
        return 2
    repo = repo.expanduser().resolve()
    adapter = Path(__file__).resolve().parent
    global_root = args.global_dir.expanduser().resolve()
    project = args.project.expanduser().resolve()
    base = global_root if args.scope == "global" else project / ".opencode"

    if not base.is_dir():
        print(f"error: {base} does not exist; run build_opencode.py --scope {args.scope} --repo {repo} first")
        return 2

    test_install(base, args.scope, repo, adapter, global_root)
    test_cli(repo)

    print(f"\n{checks} checks, {len(failures)} failures")
    if failures:
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
