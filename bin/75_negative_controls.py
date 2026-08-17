#!/usr/bin/env python3
"""Prove the benchmark metrics reject deliberately faulty implementations."""

from __future__ import annotations

import json
from pathlib import Path

from synthworld.enterprise.authorization.adversarial import (
    ENTERPRISE_ADVERSARIAL_AUTHORIZATION_BASELINES,
    EnterpriseAdversarialAuthorizationEvaluatorV1,
    EnterpriseAdversarialAuthorizationPublicV1,
    evaluate_enterprise_adversarial_authorization,
)
from synthworld.enterprise.consumer import (
    EnterpriseAuthorizationPredictionV1,
    evaluate_enterprise_authorization,
    load_evaluator_enterprise_authorization,
    load_public_enterprise_authorization,
)

ROOT = Path(__file__).resolve().parent.parent
EVALUATOR = ROOT / "06-evaluator/artifacts"
SUBMISSION = ROOT / "05-submission"
OUTPUT = ROOT / "07-reports/negative-controls.json"


def canonical_json(document: object) -> bytes:
    return (
        json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode("utf-8")


def metric_map(metrics) -> dict[str, float | None]:
    return {f"{item.family}.{item.name}": item.value for item in metrics.metrics}


def flip(value: str) -> str:
    return "deny" if value == "allow" else "allow"


def main() -> int:
    adversarial_root = EVALUATOR / "adversarial"
    public = EnterpriseAdversarialAuthorizationPublicV1.model_validate_json(
        (adversarial_root / "public/enterprise-adversarial-authorization.json").read_bytes()
    )
    evaluator = EnterpriseAdversarialAuthorizationEvaluatorV1.model_validate_json(
        (
            adversarial_root / "evaluator/enterprise-adversarial-authorization-evaluator.json"
        ).read_bytes()
    )
    required_degradation = {
        "Tenant blind": "mechanism.tenant_decision_accuracy",
        "Scope blind": "mechanism.scope_decision_accuracy",
        "Binding blind": "mechanism.binding_decision_accuracy",
        "Time blind": "mechanism.time_decision_accuracy",
        "Clearance blind": "mechanism.clearance_decision_accuracy",
        "RBAC only": "mechanism.composition_decision_accuracy",
        "Identifier/order memorization": ("robustness.identifier_independent_decision_accuracy"),
    }
    adversarial_controls = []
    for name, baseline in ENTERPRISE_ADVERSARIAL_AUTHORIZATION_BASELINES:
        metrics = metric_map(
            evaluate_enterprise_adversarial_authorization(
                public=public,
                evaluator=evaluator,
                prediction=baseline(public),
            )
        )
        target = required_degradation[name]
        value = metrics[target]
        passed = value is not None and value < 1.0
        adversarial_controls.append(
            {
                "control": name,
                "target_metric": target,
                "target_value": value,
                "passed": passed,
            }
        )

    authorization_root = EVALUATOR / "synthworld/authorization"
    authorization = load_evaluator_enterprise_authorization(authorization_root)
    authorization_public = load_public_enterprise_authorization(authorization_root)
    prediction = EnterpriseAuthorizationPredictionV1.model_validate_json(
        (SUBMISSION / "enterprise-authorization-prediction.json").read_bytes()
    )
    baseline_metrics = metric_map(
        evaluate_enterprise_authorization(
            scope=authorization_public.evaluation_scope,
            truth=authorization.access_state,
            predictions=prediction,
        )
    )

    mechanism_document = prediction.model_dump(mode="json")
    mechanism_cell = mechanism_document["cells"][0]
    mechanism_cell["mechanism_outcomes"]["rbac"] = flip(
        mechanism_cell["mechanism_outcomes"]["rbac"]
    )
    mechanism_metrics = metric_map(
        evaluate_enterprise_authorization(
            scope=authorization_public.evaluation_scope,
            truth=authorization.access_state,
            predictions=EnterpriseAuthorizationPredictionV1.model_validate_json(
                json.dumps(mechanism_document)
            ),
        )
    )

    composed_document = prediction.model_dump(mode="json")
    composed_cell = next(
        item for item in composed_document["cells"] if item["final_decision"] is not None
    )
    composed_cell["final_decision"] = flip(composed_cell["final_decision"])
    composed_metrics = metric_map(
        evaluate_enterprise_authorization(
            scope=authorization_public.evaluation_scope,
            truth=authorization.access_state,
            predictions=EnterpriseAuthorizationPredictionV1.model_validate_json(
                json.dumps(composed_document)
            ),
        )
    )
    independence_controls = [
        {
            "control": "wrong RBAC mechanism outcome",
            "target_metric": "mechanism.mechanism_outcome_exact_match_rate",
            "target_value": mechanism_metrics["mechanism.mechanism_outcome_exact_match_rate"],
            "unaffected_metric": "composed.final_decision_accuracy",
            "unaffected_value": mechanism_metrics["composed.final_decision_accuracy"],
            "passed": (
                mechanism_metrics["mechanism.mechanism_outcome_exact_match_rate"]
                < baseline_metrics["mechanism.mechanism_outcome_exact_match_rate"]
                and mechanism_metrics["composed.final_decision_accuracy"]
                == baseline_metrics["composed.final_decision_accuracy"]
            ),
        },
        {
            "control": "wrong composed final decision",
            "target_metric": "composed.final_decision_accuracy",
            "target_value": composed_metrics["composed.final_decision_accuracy"],
            "unaffected_metric": "mechanism.mechanism_outcome_exact_match_rate",
            "unaffected_value": composed_metrics["mechanism.mechanism_outcome_exact_match_rate"],
            "passed": (
                composed_metrics["composed.final_decision_accuracy"]
                < baseline_metrics["composed.final_decision_accuracy"]
                and composed_metrics["mechanism.mechanism_outcome_exact_match_rate"]
                == baseline_metrics["mechanism.mechanism_outcome_exact_match_rate"]
            ),
        },
    ]

    controls = adversarial_controls + independence_controls
    report = {
        "schema_version": "synthworld-enterprise-authorization-negative-controls/1",
        "controls": controls,
        "controls_total": len(controls),
        "controls_passed": sum(item["passed"] for item in controls),
        "passed": all(item["passed"] for item in controls),
        "note": (
            "Each control deliberately removes one authorization capability or "
            "corrupts one prediction dimension. No aggregate score is computed."
        ),
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(canonical_json(report))
    print(json.dumps(report, indent=1, sort_keys=True))
    if not report["passed"]:
        raise SystemExit("one or more faulty controls escaped its target metric")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
