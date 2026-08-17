#!/usr/bin/env python3
"""Stage 60 - score the blinded submission against SynthWorld evaluator truth.

This is the ONLY stage permitted to open anything under 06-evaluator, and it
refuses to run until it has re-verified the pre-scoring submission digest
recorded by stage 50. If the submission changed after that digest was taken, the
blinding claim is void and this stage aborts.

Scoring uses the released composed and per-mechanism scorers:
  evaluate_enterprise_authorization       composed effective/final decisions
  evaluate_enterprise_directory_rbac   RBAC family (B/I/E/F, roles, activation, SoD)
  evaluate_enterprise_abac             ABAC guard family
  evaluate_enterprise_rebac            relationship family

There is deliberately no aggregate. Every metric retains its own denominator.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import sys
from pathlib import Path

import yaml
from synthworld.enterprise.authorization.adversarial import (
    EnterpriseAdversarialAuthorizationEvaluatorV1,
    EnterpriseAdversarialAuthorizationPredictionV1,
    EnterpriseAdversarialAuthorizationPublicV1,
    evaluate_enterprise_adversarial_authorization,
)
from synthworld.enterprise.consumer import (
    EnterpriseAbacPredictionV1,
    EnterpriseAuthorizationPredictionV1,
    EnterpriseDirectoryRbacPredictionV1,
    EnterpriseRebacPredictionV1,
    evaluate_enterprise_abac,
    evaluate_enterprise_authorization,
    evaluate_enterprise_directory_rbac,
    evaluate_enterprise_rebac,
    load_evaluator_enterprise_authorization,
    load_evaluator_enterprise_case_inventory,
    load_evaluator_enterprise_directory_rbac_truth,
    load_public_enterprise_authorization,
)

REPO = Path(__file__).resolve().parent.parent

# Metrics that the released scorer computes from `truth` alone, ignoring the
# submission entirely. They describe the generated world, not the system under
# test, and must never be reported as scores. Verified empirically in the
# discovery probe by degrading a prediction and observing these stay fixed.
WORLD_PROPERTY_METRICS = {
    ("sprawl", "effective_outside_intent_rate"),
    ("sprawl", "missing_intended_access_rate"),
    ("birthright_breadth", "effective_outside_birthright_rate"),
    ("redundancy", "redundant_derivation_cell_rate"),
    ("accumulation", "privilege_accumulation_subject_rate"),
}

# Metrics a public-only consumer cannot win, with the reason. Reported separately
# so the headline numbers are not quietly inflated or quietly blamed.
NOT_PUBLICLY_WINNABLE = {
    ("intent", "intended_decision_accuracy"): (
        "The RBAC intent overlay is experiment-owned and is not published in any "
        "public artifact, so `intended_decision` cannot be derived by a consumer. "
        "The submission predicts intended == effective; this metric therefore "
        "measures declared-vs-intended drift in the world, not policy accuracy."
    ),
    ("rbac", "rbac_derivation_path_exact_match_rate"): (
        "`effective_path_ids` are internal SynthWorld derivation-path identifiers "
        "that appear in no public artifact. A public consumer cannot emit them. "
        "Submitted empty."
    ),
    ("abac", "predicate_outcome_accuracy"): (
        "Keyed by `truth_id`, which is minted inside the compiled ABAC truth - an "
        "evaluator-only artifact. The predicate outcomes themselves are derivable "
        "from the public facts, but the identifiers needed to submit them are not. "
        "Submitted empty."
    ),
    ("ssd", "ssd_violation_detection_rate"): (
        "Static separation-of-duty constraints live in the RBAC intent overlay, "
        "which is experiment-owned and exported to neither tree. A public consumer "
        "does not know which role pairs are segregated. Submitted empty."
    ),
    ("ssd", "ssd_violation_false_positive_rate"): (
        "Same as ssd_violation_detection_rate: the constraints are not public. "
        "The 0.0 here means no false alarms were raised, which is the trivial "
        "consequence of submitting nothing, not evidence of precision."
    ),
}

# Mechanisms this experiment did not exercise. Reported as not-exercised rather than as a
# poor score, because a low number here reflects an absent projection, not a wrong policy.
NOT_EXERCISED = {
    ("rebac", "rebac_decision_accuracy"): (
        "The evaluation profile is `rbac_with_abac_guard` for all 3209 cells, so the "
        "relationship mechanism is not on the decision path and was not projected into "
        "Topaz. Every cell was submitted as `not_applicable`; guessing an outcome would "
        "be fabrication."
    ),
    ("rebac", "relationship_path_exact_match_rate"): (
        "As above, and the path identifiers are evaluator-side in any case."
    ),
}


def canonical_bytes(document) -> bytes:
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_seal(submission_dir: Path) -> dict:
    seal_path = submission_dir / "SUBMISSION-SEAL.json"
    if not seal_path.is_file():
        raise SystemExit("SUBMISSION SEAL ABSENT - refusing to open evaluator truth")
    manifest = json.loads(seal_path.read_text("utf-8"))
    if manifest.get("seal_schema") != ("synthworld-enterprise-authorization-submission-seal/2"):
        raise SystemExit("unsupported submission seal schema; refusing to score")
    sealed = dict(manifest)
    recorded_seal = sealed.pop("seal_sha256", None)
    if hashlib.sha256(canonical_bytes(sealed)).hexdigest() != recorded_seal:
        raise SystemExit("submission seal document was modified; refusing to score")
    recomputed = {}
    for name in sorted(manifest["submission_sha256"]):
        raw = (submission_dir / name).read_bytes()
        recomputed[name] = hashlib.sha256(raw).hexdigest()
    drift = {
        n: (manifest["submission_sha256"][n], recomputed[n])
        for n in recomputed
        if manifest["submission_sha256"][n] != recomputed[n]
    }
    if drift:
        raise SystemExit(
            "SUBMISSION DIGEST MISMATCH - the submission changed after it was "
            f"sealed, so it is not blinded. Refusing to score.\n{json.dumps(drift, indent=1)}"
        )
    combined = hashlib.sha256(
        canonical_bytes({k: recomputed[k] for k in sorted(recomputed)})
    ).hexdigest()
    if combined != manifest["combined_sha256"]:
        raise SystemExit("combined submission digest mismatch; refusing to score")

    evidence_drift = {
        name: (expected, sha256_file(REPO / name))
        for name, expected in sorted(manifest["evidence_sha256"].items())
        if not (REPO / name).is_file() or sha256_file(REPO / name) != expected
    }
    if evidence_drift:
        raise SystemExit(
            "SEALED EVIDENCE MISMATCH - public input, raw result, policy, adapter, "
            f"or isolation evidence changed. Refusing to score.\n{json.dumps(evidence_drift, indent=1)}"
        )
    public_index = json.loads((REPO / "02-synthworld-public/PUBLIC-INDEX.json").read_text("utf-8"))
    if public_index.get("sha256") != manifest["public_artifact_sha256"]:
        raise SystemExit("public artifact inventory differs from the sealed run")
    for name, expected in sorted(public_index["sha256"].items()):
        path = REPO / "02-synthworld-public" / name
        if not path.is_file() or sha256_file(path) != expected:
            raise SystemExit(f"public artifact changed after sealing: {name}")

    config = yaml.safe_load((REPO / "01-source/config/experiment.yaml").read_text("utf-8"))
    installed = importlib.metadata.version("idcognito-synthworld")
    recorded = manifest["provenance"]["synthworld"]
    if installed != recorded["version"] or installed != config["synthworld"]["version"]:
        raise SystemExit("SynthWorld package version differs from sealed provenance")
    if any(
        recorded[field] != config["synthworld"][field] for field in ("wheel_sha256", "sdist_sha256")
    ):
        raise SystemExit("SynthWorld distribution digests differ from sealed provenance")
    if manifest["provenance"]["topaz"]["image"] != config["topaz"]["image"]:
        raise SystemExit("Topaz image differs from sealed provenance")
    topaz = manifest["provenance"]["topaz"]
    if (
        topaz["version"] != config["topaz"]["version"]
        or topaz["commit"] != config["topaz"]["commit"]
        or topaz["adversarial_version"] != topaz["version"]
        or topaz["adversarial_commit"] != topaz["commit"]
    ):
        raise SystemExit("Topaz runtime version differs from sealed provenance")
    adapter_sources = {
        name: digest
        for name, digest in manifest["evidence_sha256"].items()
        if name.startswith("bin/")
    }
    adapter_digest = hashlib.sha256(
        canonical_bytes(dict(sorted(adapter_sources.items())))
    ).hexdigest()
    if adapter_digest != manifest["provenance"]["adapter"]["source_sha256"]:
        raise SystemExit("adapter source digest differs from sealed provenance")
    if set(manifest["schema_versions"].values()) != {"1.0.0"}:
        raise SystemExit("unsupported prediction or public artifact schema version")
    return manifest


def metrics_to_rows(metrics) -> list[dict]:
    rows = []
    for m in metrics.metrics:
        rows.append(
            {
                "family": str(m.family),
                "name": m.name,
                "value": m.value,
                "numerator": m.numerator,
                "denominator": m.denominator,
                "support": m.support,
                "denominator_meaning": str(m.denominator_meaning),
                "empty_behaviour": str(m.empty_behaviour),
            }
        )
    return sorted(rows, key=lambda r: (r["family"], r["name"]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--submission", default=str(REPO / "05-submission"))
    ap.add_argument("--evaluator", default=str(REPO / "06-evaluator/artifacts/synthworld"))
    ap.add_argument("--out", default=str(REPO / "07-reports/scoring"))
    args = ap.parse_args()

    submission_dir = Path(args.submission)
    manifest = verify_seal(submission_dir)
    print("submission digest verified:", manifest["combined_sha256"])

    root = Path(args.evaluator)
    rbac_truth = load_evaluator_enterprise_directory_rbac_truth(root / "directory-rbac")
    authorization = load_evaluator_enterprise_authorization(root / "authorization")
    authorization_public = load_public_enterprise_authorization(root / "authorization")
    case_inventory = load_evaluator_enterprise_case_inventory(root / "evaluation-corpus")

    def load(model, name):
        return model.model_validate_json((submission_dir / name).read_text("utf-8"))

    rbac_pred = load(EnterpriseDirectoryRbacPredictionV1, "directory-rbac-prediction.json")
    abac_pred = load(EnterpriseAbacPredictionV1, "abac-prediction.json")
    rebac_pred = load(EnterpriseRebacPredictionV1, "rebac-prediction.json")
    composed_pred = load(
        EnterpriseAuthorizationPredictionV1,
        "enterprise-authorization-prediction.json",
    )
    adversarial_root = root.parent / "adversarial"
    adversarial_public = EnterpriseAdversarialAuthorizationPublicV1.model_validate_json(
        (adversarial_root / "public/enterprise-adversarial-authorization.json").read_bytes()
    )
    adversarial_evaluator = EnterpriseAdversarialAuthorizationEvaluatorV1.model_validate_json(
        (
            adversarial_root / "evaluator/enterprise-adversarial-authorization-evaluator.json"
        ).read_bytes()
    )
    adversarial_pred = load(
        EnterpriseAdversarialAuthorizationPredictionV1,
        "adversarial-authorization-prediction.json",
    )
    adversarial_metrics = evaluate_enterprise_adversarial_authorization(
        public=adversarial_public,
        evaluator=adversarial_evaluator,
        prediction=adversarial_pred,
    )

    families = {
        "adversarial": metrics_to_rows(adversarial_metrics),
        "composed": metrics_to_rows(
            evaluate_enterprise_authorization(
                scope=authorization_public.evaluation_scope,
                truth=authorization.access_state,
                predictions=composed_pred,
            )
        ),
        "directory_rbac": metrics_to_rows(
            evaluate_enterprise_directory_rbac(truth=rbac_truth, predictions=rbac_pred)
        ),
        "abac": metrics_to_rows(
            evaluate_enterprise_abac(truth=authorization.abac_truth, predictions=abac_pred)
        ),
        "rebac": metrics_to_rows(
            evaluate_enterprise_rebac(truth=authorization.rebac_truth, predictions=rebac_pred)
        ),
    }

    # Split every metric into how it should be read.
    scored, world_properties, not_winnable, not_exercised = [], [], [], []
    for family_name, rows in sorted(families.items()):
        for row in rows:
            key = (row["family"], row["name"])
            entry = dict(row, scorer=family_name)
            if key in WORLD_PROPERTY_METRICS:
                entry["note"] = (
                    "Computed from truth alone; the submission does not affect it. "
                    "This describes the generated world, not the system under test."
                )
                world_properties.append(entry)
            elif key in NOT_PUBLICLY_WINNABLE:
                entry["note"] = NOT_PUBLICLY_WINNABLE[key]
                not_winnable.append(entry)
            elif key in NOT_EXERCISED:
                entry["note"] = NOT_EXERCISED[key]
                not_exercised.append(entry)
            else:
                scored.append(entry)

    # Per-case-class breakdown, using the evaluator case inventory labels.
    #
    # RBAC-family final and composed final are intentionally kept separate: the
    # former applies binding/lifecycle gates, while the latter also includes the
    # selected ABAC guard.
    labels: dict[str, list[str]] = {}
    for case in case_inventory.cases:
        if str(case.target_kind) == "access_cell" or "access_cell" in str(case.target_kind):
            labels[case.target_id] = [str(x) for x in case.labels]
    truth_by_cell = {c.cell_id: c for c in rbac_truth.cells}
    pred_by_cell = {c.cell_id: c for c in rbac_pred.cells}
    composed_truth_by_cell = {c.cell_id: c for c in authorization.access_state.cells}
    composed_pred_by_cell = {c.cell_id: c for c in composed_pred.cells}
    per_class: dict[str, dict[str, int]] = {}
    for cell_id, labs in labels.items():
        t, p = truth_by_cell.get(cell_id), pred_by_cell.get(cell_id)
        if t is None or p is None:
            continue
        for lab in labs:
            if lab == "directory-rbac":
                continue
            b = per_class.setdefault(
                lab,
                {
                    "n": 0,
                    "effective_correct": 0,
                    "rbac_final_correct": 0,
                    "composed_final_correct": 0,
                    "rbac_truth_final_deny": 0,
                },
            )
            b["n"] += 1
            b["effective_correct"] += int(str(p.effective_decision) == str(t.effective_decision))
            b["rbac_final_correct"] += int(str(p.final_decision) == str(t.final_decision))
            b["composed_final_correct"] += int(
                composed_pred_by_cell[cell_id].final_decision
                is composed_truth_by_cell[cell_id].final_decision
            )
            b["rbac_truth_final_deny"] += int(str(t.final_decision) == "deny")
    for bucket in per_class.values():
        bucket["effective_accuracy"] = round(bucket["effective_correct"] / bucket["n"], 4)
        bucket["rbac_final_accuracy"] = round(bucket["rbac_final_correct"] / bucket["n"], 4)
        bucket["composed_final_accuracy"] = round(bucket["composed_final_correct"] / bucket["n"], 4)
        bucket["composed_decision_scored"] = True

    report = {
        "submission_digest": manifest["combined_sha256"],
        "submission_digest_verified_before_scoring": True,
        "cells_scored": len(rbac_pred.cells),
        "adversarial_attempts_scored": len(adversarial_pred.attempts),
        "adversarial_cohorts": [
            item.model_dump(mode="json") for item in adversarial_metrics.cohorts
        ],
        "scored_metrics": sorted(scored, key=lambda r: (r["scorer"], r["family"], r["name"])),
        "not_publicly_winnable": sorted(
            not_winnable, key=lambda r: (r["scorer"], r["family"], r["name"])
        ),
        "mechanisms_not_exercised": sorted(
            not_exercised, key=lambda r: (r["scorer"], r["family"], r["name"])
        ),
        "world_property_metrics_not_scores": sorted(
            world_properties, key=lambda r: (r["scorer"], r["family"], r["name"])
        ),
        "per_case_class": dict(sorted(per_class.items())),
        "per_case_class_note": (
            "RBAC-family final and composed final are reported independently. The "
            "composed column includes the public ABAC guard and is scored through "
            "the released SynthWorld 0.16.0 evaluation-scope contract."
        ),
        "aggregate": None,
        "aggregate_note": (
            "The released scorers deliberately emit no aggregate. Families carry "
            "different denominators and are not commensurable; "
            "no overall score is computed here."
        ),
    }

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "scoring-report.json").write_text(
        json.dumps(report, indent=1, sort_keys=True) + "\n", "utf-8"
    )

    print(f"\n=== SCORED METRICS ({len(scored)}) ===")
    for row in report["scored_metrics"]:
        print(
            f"  {row['scorer']:15s} {row['family']:20s} {row['name']:45s} "
            f"{row['value']}  (n={row['denominator']})"
        )
    print(f"\n=== NOT PUBLICLY WINNABLE ({len(not_winnable)}) ===")
    for row in report["not_publicly_winnable"]:
        print(f"  {row['family']}.{row['name']}: {row['value']}")
    print(f"\n=== MECHANISMS NOT EXERCISED ({len(not_exercised)}) ===")
    for row in report["mechanisms_not_exercised"]:
        print(f"  {row['family']}.{row['name']}: {row['value']}")
    print(f"\n=== WORLD PROPERTIES, NOT SCORES ({len(world_properties)}) ===")
    for row in report["world_property_metrics_not_scores"]:
        print(f"  {row['family']}.{row['name']}: {row['value']}")
    print("\n=== PER CASE CLASS ===")
    for lab, b in report["per_case_class"].items():
        print(
            f"  {lab:34s} n={b['n']:5d}  effective={b['effective_accuracy']:.4f}  "
            f"rbac_final={b['rbac_final_accuracy']:.4f}  "
            f"composed_final={b['composed_final_accuracy']:.4f}  "
            f"rbac_truth_final_deny={b['rbac_truth_final_deny']:5d}"
        )
    print(f"\nreport -> {out / 'scoring-report.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
