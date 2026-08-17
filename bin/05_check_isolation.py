#!/usr/bin/env python3
"""Fail unless the SUT container has no evaluator filesystem capability."""

from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORT = Path(
    os.environ.get("ISOLATION_REPORT", str(ROOT / "04-topaz-results/isolation-report.json"))
)
FORBIDDEN = (Path("/evaluator"), ROOT / "06-evaluator")


def canonical_json(document: object) -> bytes:
    return (
        json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode("utf-8")


def main() -> int:
    present = [str(path) for path in FORBIDDEN if path.exists()]
    evaluator_environment = sorted(name for name in os.environ if "EVALUATOR" in name.upper())
    mountinfo = Path("/proc/self/mountinfo").read_text("utf-8")
    suspicious_mounts = sorted(
        line for line in mountinfo.splitlines() if "06-evaluator" in line or " /evaluator " in line
    )
    public_index = ROOT / "02-synthworld-public/PUBLIC-INDEX.json"
    public_mount = next(
        (
            line
            for line in mountinfo.splitlines()
            if len(line.split()) > 5 and line.split()[4] == str(ROOT / "02-synthworld-public")
        ),
        None,
    )
    public_read_only = bool(public_mount and "ro" in public_mount.split()[5].split(","))
    failures = []
    if present:
        failures.append("evaluator path is present")
    if evaluator_environment:
        failures.append("evaluator-named environment capability is present")
    if suspicious_mounts:
        failures.append("evaluator mount is present")
    if not public_index.is_file():
        failures.append("public artifact index is absent")
    if not public_read_only:
        failures.append("public artifact mount is not demonstrably read-only")
    report = {
        "schema_version": "synthworld-enterprise-authorization-isolation-report/1",
        "public_input_mounted": public_index.is_file(),
        "public_input_read_only": public_read_only,
        "evaluator_paths_present": present,
        "evaluator_environment_names": evaluator_environment,
        "evaluator_mounts_present": bool(suspicious_mounts),
        "passed": not failures,
        "threat_model": "accidental evaluator leakage, not hostile host administration",
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_bytes(canonical_json(report))
    print(json.dumps(report, indent=1, sort_keys=True))
    if failures:
        raise SystemExit("ISOLATION VIOLATION: " + "; ".join(failures))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
