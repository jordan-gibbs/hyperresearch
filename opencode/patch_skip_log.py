#!/usr/bin/env python3
"""Write the minimal patch log used when step 14 is skipped by the invoker.

Usage:
    python patch_skip_log.py <vault_tag> [--root PATH]

ROOT defaults to the current working directory.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("vault_tag")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="project root (default: cwd)")
    args = parser.parse_args()

    run = args.root.expanduser().resolve() / "research" / "runs" / args.vault_tag
    names = [
        "critic-findings-dialectic.json",
        "critic-findings-depth.json",
        "critic-findings-width.json",
        "critic-findings-instruction.json",
    ]
    total = 0
    for name in names:
        path = run / name
        if path.is_file():
            try:
                total += len(json.loads(path.read_text(encoding="utf-8")).get("findings", []))
            except (OSError, ValueError):
                pass

    log = {
        "total_findings": total,
        "applied": [],
        "skipped": [{"reason": "patcher-skipped-by-invoker"}],
        "conflicts": [],
        "orchestrator_escalated": [],
    }
    out = run / "patch-log.json"
    out.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {out} (total_findings={total})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
