#!/usr/bin/env python3
"""Stage 50 - turn raw Topaz decisions into a blinded SynthWorld submission.

ZONE: reads 04-topaz-results and 02-synthworld-public. Writes 05-submission.
Hard-guarded against 06-evaluator: this stage runs BEFORE any answer key is
opened, and the digest it records is what makes that claim checkable after the
fact.

The submission is "blinded" in the strict sense: every value in it is a function
of (public SynthWorld artifacts, Topaz's decisions). Nothing in this file was
derived from, compared against, or tuned to evaluator truth.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FORBIDDEN = (REPO / "06-evaluator").resolve()


def guard(path: Path) -> Path:
    """Fail loudly rather than silently reading the answer key."""
    resolved = path.resolve()
    if resolved == FORBIDDEN or FORBIDDEN in resolved.parents:
        raise SystemExit(
            f"ISOLATION VIOLATION: stage 50 attempted to read evaluator artifact {resolved}"
        )
    return resolved


def read_json(path: Path):
    return json.loads(guard(path).read_text("utf-8"))


def canonical_bytes(document) -> bytes:
    """Stable serialization so the digest is reproducible byte for byte."""
    return json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--public", default=str(REPO / "02-synthworld-public"))
    ap.add_argument("--decisions", default=str(REPO / "04-topaz-results/normalized/decisions.json"))
    ap.add_argument("--out", default=str(REPO / "05-submission"))
    args = ap.parse_args()

    public = Path(args.public)
    corpus = read_json(public / "evaluation-corpus/evaluation-corpus.json")
    cell_ids = [c["cell_id"] for c in corpus["evaluation_cells"]]
    decisions = read_json(Path(args.decisions))

    missing = [c for c in cell_ids if c not in decisions]
    extra = [c for c in decisions if c not in set(cell_ids)]
    if extra:
        raise SystemExit(
            f"{len(extra)} decisions reference cells that are not in the public corpus"
        )

    # A cell Topaz never answered is submitted as an explicit deny rather than
    # dropped. Dropping would quietly shrink the denominator; an explicit wrong
    # answer is scored as wrong, which is the honest outcome.
    def verdict(value) -> str:
        return "allow" if value else "deny"

    rbac_cells = []
    abac_cells = []
    rebac_cells = []
    for cid in cell_ids:
        d = decisions.get(cid)
        if d is None:
            d = {
                "birthright": False,
                "intended": False,
                "effective": False,
                "rbac_final": False,
                "abac": "deny",
            }
        rbac_cells.append(
            {
                "cell_id": cid,
                "birthright_decision": verdict(d["birthright"]),
                "intended_decision": verdict(d["intended"]),
                "effective_decision": verdict(d["effective"]),
                # SynthWorld's directory-RBAC family gates `effective` by account binding
                # and lifecycle ONLY. The ABAC guard is a separate mechanism with its own
                # truth and its own scorer, so it must NOT be folded in here. Topaz emitted
                # both: `rbac_final` (guard-free, this family) and `final` (composed).
                "final_decision": verdict(d["rbac_final"]),
                # effective_path_ids are the ids of the derivation paths SynthWorld
                # minted internally. Those ids are not present in any public
                # artifact, so a public consumer cannot produce them. Submitted
                # empty; the corresponding metric is reported as not winnable.
                "effective_path_ids": [],
            }
        )
        abac_cells.append(
            {
                "cell_id": cid,
                "actual_outcome": d.get("abac", "allow"),
                "intended_outcome": d.get("abac", "allow"),
            }
        )
        # The evaluation profile is rbac_with_abac_guard for all 3209 cells, so ReBAC is not
        # on the decision path and was not projected into Topaz. Submitting a guess would be
        # fabrication; `not_applicable` is the honest mechanism outcome, and the ReBAC
        # scores are reported as not-exercised rather than as a result.
        rebac_cells.append(
            {
                "cell_id": cid,
                "actual_outcome": "not_applicable",
                "intended_outcome": "not_applicable",
                "actual_path_ids": [],
                "intended_path_ids": [],
            }
        )

    # Authorized role sets, as Topaz reported them from the directory graph
    # (closure-expanded over group membership, group nesting and role hierarchy).
    # Every access subject must appear, including those holding no role at all -
    # omitting them would silently shrink the denominator instead of being scored.
    universe = read_json(public / "identity-access/identity-access-universe.json")
    role_sets_path = Path(args.decisions).parent / "role-sets.json"
    topaz_role_sets = read_json(role_sets_path) if role_sets_path.exists() else {}
    authorized_role_sets = [
        {
            "subject_id": s["subject_id"],
            "role_ids": sorted(topaz_role_sets.get(s["subject_id"], [])),
        }
        for s in sorted(universe["access_subjects"], key=lambda s: s["subject_id"])
    ]

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    submissions = {
        "directory-rbac-prediction.json": {
            "schema_version": "1.0.0",
            "cells": rbac_cells,
            "authorized_role_sets": authorized_role_sets,
            "activations": [],
            "ssd_evaluations": [],
            "dsd_evaluations": [],
            "birthright_assignments": [],
        },
        "abac-prediction.json": {
            "schema_version": "1.0.0",
            "cells": abac_cells,
            "predicates": [],
        },
        "rebac-prediction.json": {"schema_version": "1.0.0", "cells": rebac_cells},
    }

    digests = {}
    for name, document in sorted(submissions.items()):
        data = canonical_bytes(document)
        (out / name).write_bytes(data + b"\n")
        digests[name] = hashlib.sha256(data).hexdigest()

    # The pre-scoring digest. Recorded here, before stage 60 opens anything under
    # 06-evaluator. Stage 60 re-computes these and refuses to score if they moved.
    manifest = {
        "submission_schema": "britannia-phase2-submission/1",
        "cells_in_public_corpus": len(cell_ids),
        "cells_answered_by_topaz": len(cell_ids) - len(missing),
        "cells_defaulted_to_deny": len(missing),
        "sha256": digests,
        "combined_sha256": hashlib.sha256(
            canonical_bytes({k: digests[k] for k in sorted(digests)})
        ).hexdigest(),
        "evaluator_artifacts_read": False,
        "note": (
            "Digests recorded before any evaluator artifact was opened. Stage 60 "
            "verifies them before scoring."
        ),
    }
    (out / "SUBMISSION-DIGEST.json").write_text(
        json.dumps(manifest, indent=1, sort_keys=True) + "\n", "utf-8"
    )
    print(json.dumps(manifest, indent=1, sort_keys=True))
    if missing:
        print(f"\nWARNING: {len(missing)} cells had no Topaz decision and were submitted as deny")
    return 0


if __name__ == "__main__":
    sys.exit(main())
