#!/usr/bin/env python3
"""Cross-platform replacement for the bash `for f in ...; test -f` artifact check.

Usage:
    python artifact_gate.py <vault_tag> [--root PATH]

ROOT defaults to the current working directory (the project the agent is
researching). Prints `MISSING: <path>` for each absent required artifact and
exits 1 if any are missing. Light tier requires only polish-log.json.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

FULL_REQUIRED = [
    "critic-findings-dialectic.json",
    "critic-findings-depth.json",
    "critic-findings-width.json",
    "critic-findings-instruction.json",
    "patch-log.json",
    "polish-log.json",
]
LIGHT_REQUIRED = ["polish-log.json"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("vault_tag")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="project root (default: cwd)")
    args = parser.parse_args()

    run = args.root.expanduser().resolve() / "research" / "runs" / args.vault_tag
    required = FULL_REQUIRED
    decomposition = run / "prompt-decomposition.json"
    if decomposition.is_file():
        try:
            tier = json.loads(decomposition.read_text(encoding="utf-8")).get("pipeline_tier")
            if tier == "light":
                required = LIGHT_REQUIRED
        except (OSError, ValueError):
            pass

    missing = [name for name in required if not (run / name).is_file()]
    for name in missing:
        print(f"MISSING: research/runs/{args.vault_tag}/{name}")
    if missing:
        return 1
    print(f"All {len(required)} required artifacts present for {args.vault_tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
