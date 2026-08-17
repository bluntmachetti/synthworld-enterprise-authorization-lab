#!/usr/bin/env python3
"""Print stable SHA-256 fingerprints for reproducibility-scoped outputs."""

from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TREES = (
    "01-source/generated",
    "02-synthworld-public",
    "03-topaz-input",
    "06-evaluator",
    "07-reports",
    "viz",
)
FILES = (
    "04-topaz-results/raw/decisions.jsonl",
    "04-topaz-results/normalized/decisions.json",
    "04-topaz-results/normalized/role-sets.json",
    "04-topaz-results/adversarial/raw-decisions.jsonl",
    "04-topaz-results/adversarial/decisions.json",
    "04-topaz-results/adversarial/run-report.json",
    "04-topaz-results/isolation-report.json",
    "05-submission/abac-prediction.json",
    "05-submission/adversarial-authorization-prediction.json",
    "05-submission/directory-rbac-prediction.json",
    "05-submission/enterprise-authorization-prediction.json",
    "05-submission/rebac-prediction.json",
)


def main() -> int:
    paths = {ROOT / name for name in FILES}
    for tree in TREES:
        paths.update(path for path in (ROOT / tree).rglob("*") if path.is_file())
    missing = sorted(path for path in paths if not path.is_file())
    if missing:
        raise SystemExit(f"missing reproducibility output: {missing[0]}")
    for path in sorted(paths):
        relative = path.relative_to(ROOT).as_posix()
        print(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {relative}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
