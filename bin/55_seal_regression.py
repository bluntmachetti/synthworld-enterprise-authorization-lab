#!/usr/bin/env python3
"""Exercise seal refusal paths before any successful scoring run."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "05-submission"
OUTPUT = ROOT / "07-reports/seal-negative-controls.json"


def canonical_bytes(document: object) -> bytes:
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def rewrite_seal(path: Path, mutate) -> None:
    seal = json.loads(path.read_text("utf-8"))
    seal.pop("seal_sha256")
    mutate(seal)
    seal["seal_sha256"] = hashlib.sha256(canonical_bytes(seal)).hexdigest()
    path.write_text(json.dumps(seal, indent=1, sort_keys=True) + "\n", "utf-8")


def run_case(name: str, mutate, expected: str) -> dict:
    with tempfile.TemporaryDirectory(prefix="synthworld-seal-") as temp:
        submission = Path(temp) / "submission"
        shutil.copytree(SOURCE, submission)
        mutate(submission)
        completed = subprocess.run(
            [
                sys.executable,
                "bin/60_score.py",
                "--submission",
                str(submission),
                "--out",
                str(Path(temp) / "out"),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        combined = completed.stdout + completed.stderr
        return {
            "control": name,
            "exit_code": completed.returncode,
            "expected_diagnostic": expected,
            "passed": completed.returncode != 0 and expected in combined,
        }


def main() -> int:
    def remove_seal(submission: Path) -> None:
        (submission / "SUBMISSION-SEAL.json").unlink()

    def mutate_prediction(submission: Path) -> None:
        path = submission / "enterprise-authorization-prediction.json"
        path.write_bytes(path.read_bytes() + b" ")

    def cross_artifact(submission: Path) -> None:
        def mutate(seal: dict) -> None:
            first = sorted(seal["public_artifact_sha256"])[0]
            seal["public_artifact_sha256"][first] = "0" * 64

        rewrite_seal(submission / "SUBMISSION-SEAL.json", mutate)

    def version_mismatch(submission: Path) -> None:
        rewrite_seal(
            submission / "SUBMISSION-SEAL.json",
            lambda seal: seal["provenance"]["synthworld"].__setitem__("version", "0.0.0"),
        )

    controls = [
        run_case("unsealed submission", remove_seal, "SUBMISSION SEAL ABSENT"),
        run_case("mutated prediction", mutate_prediction, "SUBMISSION DIGEST MISMATCH"),
        run_case(
            "cross-artifact public inventory",
            cross_artifact,
            "public artifact inventory differs",
        ),
        run_case("package version mismatch", version_mismatch, "package version differs"),
    ]
    report = {
        "schema_version": "synthworld-enterprise-authorization-seal-controls/1",
        "controls": controls,
        "controls_total": len(controls),
        "controls_passed": sum(control["passed"] for control in controls),
        "passed": all(control["passed"] for control in controls),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n", "utf-8")
    print(json.dumps(report, indent=1, sort_keys=True))
    if not report["passed"]:
        raise SystemExit("a seal negative control was not refused as expected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
