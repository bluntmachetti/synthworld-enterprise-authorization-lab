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
import importlib.metadata
import json
import sys
from pathlib import Path

import yaml
from synthworld.enterprise.authorization.adversarial import (
    EnterpriseAdversarialAuthorizationPredictionV1,
    EnterpriseAdversarialAuthorizationPublicV1,
)
from synthworld.enterprise.consumer import (
    EnterpriseAuthorizationCompositionV1,
    EnterpriseAuthorizationEvaluationScopeV1,
    EnterpriseAuthorizationKernelV1,
    EnterpriseAuthorizationPredictionV1,
    EnterpriseDirectoryRbacKernelV1,
    EnterpriseEvaluationCorpusV1,
    EnterpriseIdentityAccessUniverseV1,
    canonical_enterprise_model_bytes,
    digest_enterprise_model,
)

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
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def sha256_file(path: Path) -> str:
    return hashlib.sha256(guard(path).read_bytes()).hexdigest()


def read_model(model, path: Path):
    return model.model_validate_json(guard(path).read_bytes())


def lifecycle_status(observation, tick: int) -> str:
    if observation is None:
        return "inactive"
    if tick < observation.valid_from_tick:
        return "not_yet_valid"
    if observation.valid_until_tick is not None and tick >= observation.valid_until_tick:
        return "expired"
    if str(observation.administrative_state) != "active":
        return "inactive"
    return "active"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--public", default=str(REPO / "02-synthworld-public"))
    ap.add_argument("--decisions", default=str(REPO / "04-topaz-results/normalized/decisions.json"))
    ap.add_argument(
        "--adversarial-decisions",
        default=str(REPO / "04-topaz-results/adversarial/decisions.json"),
    )
    ap.add_argument("--out", default=str(REPO / "05-submission"))
    args = ap.parse_args()

    public = Path(args.public)
    universe_model = read_model(
        EnterpriseIdentityAccessUniverseV1,
        public / "identity-access/identity-access-universe.json",
    )
    corpus_model = read_model(
        EnterpriseEvaluationCorpusV1,
        public / "evaluation-corpus/evaluation-corpus.json",
    )
    directory_kernel = read_model(
        EnterpriseDirectoryRbacKernelV1,
        public / "directory-rbac/directory-rbac-kernel.json",
    )
    composition = read_model(
        EnterpriseAuthorizationCompositionV1,
        public / "authorization/authorization-composition.json",
    )
    authorization_kernel = read_model(
        EnterpriseAuthorizationKernelV1,
        public / "authorization/authorization-kernel.json",
    )
    evaluation_scope = read_model(
        EnterpriseAuthorizationEvaluationScopeV1,
        public / "authorization/authorization-evaluation-scope.json",
    )
    cell_ids = [c.cell_id for c in corpus_model.evaluation_cells]
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
    universe = universe_model.model_dump(mode="json")
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

    submission_documents = {
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

    atom_by_id = {item.access_atom_id: item for item in universe_model.access_atoms}
    subject_by_id = {item.subject_id: item for item in universe_model.access_subjects}
    observation_by_account = {
        item.account_id: item for item in directory_kernel.account_observations
    }
    corpus_cell_by_id = {item.cell_id: item for item in corpus_model.evaluation_cells}
    scope_by_cell = {
        item.cell_id: {str(dimension) for dimension in item.scored_dimensions}
        for item in evaluation_scope.cells
    }
    composed_cells = []
    for cid in cell_ids:
        observed = decisions.get(cid) or {
            "effective": False,
            "final": False,
            "abac": "deny",
        }
        rbac = verdict(observed["effective"])
        abac = observed.get("abac", "deny")
        dimensions = scope_by_cell[cid]
        row = {
            "cell_id": cid,
            "mechanism_outcomes": {"rbac": rbac, "abac": abac},
            "effective_decision": (
                verdict(observed["effective"] and abac == "allow")
                if "effective_decision" in dimensions
                else None
            ),
            "final_decision": (
                verdict(observed["final"]) if "final_decision" in dimensions else None
            ),
            "policy_conflict": (
                bool(
                    (observed["effective"] and abac == "deny")
                    or (not observed["effective"] and abac == "allow")
                )
                if "policy_conflict" in dimensions
                else None
            ),
        }
        if "lifecycle_status" in dimensions:
            corpus_cell = corpus_cell_by_id[cid]
            atom = atom_by_id[corpus_cell.access_atom_id]
            subject = subject_by_id[atom.subject_id]
            if str(subject.subject_kind) != "account":
                raise SystemExit(f"public scope selected lifecycle_status for principal cell {cid}")
            row["lifecycle_status"] = lifecycle_status(
                observation_by_account.get(subject.subject_id), corpus_cell.tick
            )
        composed_cells.append(row)

    run_report = read_json(Path(args.decisions).parents[1] / "run-report.json")
    adversarial_run_report = read_json(Path(args.adversarial_decisions).parent / "run-report.json")
    config = yaml.safe_load(guard(REPO / "01-source/config/experiment.yaml").read_text("utf-8"))
    policy_path = REPO / "03-topaz-input/policy/britannia/authz.rego"
    composed_prediction = EnterpriseAuthorizationPredictionV1.model_validate_json(
        json.dumps(
            {
                "identity_access_universe_digest": digest_enterprise_model(
                    universe_model
                ).model_dump(mode="json"),
                "evaluation_corpus_digest": digest_enterprise_model(corpus_model).model_dump(
                    mode="json"
                ),
                "composition_digest": digest_enterprise_model(composition).model_dump(mode="json"),
                "authorization_kernel_digest": digest_enterprise_model(
                    authorization_kernel
                ).model_dump(mode="json"),
                "evaluation_scope_digest": digest_enterprise_model(evaluation_scope).model_dump(
                    mode="json"
                ),
                "execution": {
                    "synthworld_package_version": importlib.metadata.version(
                        "idcognito-synthworld"
                    ),
                    "adapter_name": "synthworld-enterprise-authorization-lab-topaz",
                    "adapter_version": "1.0.0",
                    "system_name": "Aserto Topaz",
                    "system_version": run_report["topaz"]["version"],
                    "policy_name": "britannia-composed-authorization",
                    "policy_version": "1.0.0",
                    "policy_sha256": hashlib.sha256(policy_path.read_bytes()).hexdigest(),
                },
                "cells": composed_cells,
            }
        )
    )

    submissions = {
        name: canonical_bytes(document) + b"\n" for name, document in submission_documents.items()
    }
    submissions["enterprise-authorization-prediction.json"] = canonical_enterprise_model_bytes(
        composed_prediction
    )

    adversarial_public = read_model(
        EnterpriseAdversarialAuthorizationPublicV1,
        public / "adversarial/enterprise-adversarial-authorization.json",
    )
    adversarial_decisions = read_json(Path(args.adversarial_decisions))
    attempt_by_id = {item.attempt_id: item for item in adversarial_public.attempts}
    if set(adversarial_decisions) != set(attempt_by_id):
        raise SystemExit("adversarial Topaz result inventory differs from public attempts")
    adversarial_prediction = EnterpriseAdversarialAuthorizationPredictionV1.model_validate_json(
        json.dumps(
            {
                "public_digest": digest_enterprise_model(adversarial_public).model_dump(
                    mode="json"
                ),
                "attempts": [
                    {
                        "attempt_id": attempt_id,
                        "resolved_principal_id": result["resolved_principal_id"],
                        "binding_status": (
                            "missing"
                            if result["resolved_principal_id"] is None
                            else (
                                "matches_canonical"
                                if result["resolved_principal_id"]
                                == attempt_by_id[attempt_id].presented_principal_id
                                else "mismatch"
                            )
                        ),
                        "decision": "allow" if result["allow"] else "deny",
                    }
                    for attempt_id, result in sorted(adversarial_decisions.items())
                ],
            }
        )
    )
    submissions["adversarial-authorization-prediction.json"] = canonical_enterprise_model_bytes(
        adversarial_prediction
    )

    digests = {}
    for name, data in sorted(submissions.items()):
        (out / name).write_bytes(data)
        digests[name] = hashlib.sha256(data).hexdigest()

    evidence_paths = [
        "02-synthworld-public/PUBLIC-INDEX.json",
        "03-topaz-input/policy/.manifest",
        "03-topaz-input/policy/adversarial/authz.rego",
        "03-topaz-input/policy/britannia/authz.rego",
        "04-topaz-results/isolation-report.json",
        "04-topaz-results/run-report.json",
        "04-topaz-results/raw/decisions.jsonl",
        "04-topaz-results/normalized/decisions.json",
        "04-topaz-results/normalized/role-sets.json",
        "04-topaz-results/adversarial/run-report.json",
        "04-topaz-results/adversarial/raw-decisions.jsonl",
        "04-topaz-results/adversarial/decisions.json",
        "bin/05_check_isolation.py",
        "bin/30_project_topaz.py",
        "bin/35_project_adversarial.py",
        "bin/40_run_topaz.py",
        "bin/45_run_adversarial.py",
        "bin/50_build_submission.py",
    ]
    evidence = {name: sha256_file(REPO / name) for name in sorted(evidence_paths)}
    public_index = read_json(REPO / "02-synthworld-public/PUBLIC-INDEX.json")
    isolation_report = read_json(REPO / "04-topaz-results/isolation-report.json")
    if not isolation_report.get("passed"):
        raise SystemExit("refusing to seal a submission that failed isolation checks")
    if not isolation_report.get("public_input_read_only"):
        raise SystemExit("refusing to seal without a read-only public input mount")

    # The pre-scoring seal. It binds the predictions to their public inputs, raw
    # system responses, policy, adapter source, runtime, and isolation proof.
    # Stage 60 verifies every byte before it opens evaluator truth.
    manifest = {
        "seal_schema": "synthworld-enterprise-authorization-submission-seal/2",
        "cells_in_public_corpus": len(cell_ids),
        "cells_answered_by_topaz": len(cell_ids) - len(missing),
        "cells_defaulted_to_deny": len(missing),
        "submission_sha256": digests,
        "combined_sha256": hashlib.sha256(
            canonical_bytes({k: digests[k] for k in sorted(digests)})
        ).hexdigest(),
        "evidence_sha256": evidence,
        "public_artifact_sha256": public_index["sha256"],
        "provenance": {
            "synthworld": {
                "distribution": config["synthworld"]["package"],
                "version": importlib.metadata.version("idcognito-synthworld"),
                "wheel_sha256": config["synthworld"]["wheel_sha256"],
                "sdist_sha256": config["synthworld"]["sdist_sha256"],
            },
            "topaz": {
                "image": config["topaz"]["image"],
                "version": run_report["topaz"]["version"],
                "commit": run_report["topaz"]["commit"],
                "adversarial_version": adversarial_run_report["topaz"]["version"],
                "adversarial_commit": adversarial_run_report["topaz"]["commit"],
            },
            "adapter": {
                "name": "synthworld-enterprise-authorization-lab-topaz",
                "version": "1.0.0",
                "source_sha256": hashlib.sha256(
                    canonical_bytes(
                        {
                            name: evidence[name]
                            for name in sorted(evidence)
                            if name.startswith("bin/")
                        }
                    )
                ).hexdigest(),
            },
        },
        "schema_versions": {
            "enterprise_authorization_prediction": composed_prediction.schema_version,
            "enterprise_adversarial_public": adversarial_public.schema_version,
            "enterprise_adversarial_prediction": adversarial_prediction.schema_version,
        },
        "evaluator_artifacts_read": False,
        "note": (
            "Seal recorded inside the evaluator-free SUT container. Stage 60 "
            "verifies all bound evidence before opening evaluator truth."
        ),
    }
    manifest["seal_sha256"] = hashlib.sha256(canonical_bytes(manifest)).hexdigest()
    (out / "SUBMISSION-SEAL.json").write_text(
        json.dumps(manifest, indent=1, sort_keys=True) + "\n", "utf-8"
    )
    print(json.dumps(manifest, indent=1, sort_keys=True))
    if missing:
        print(f"\nWARNING: {len(missing)} cells had no Topaz decision and were submitted as deny")
    return 0


if __name__ == "__main__":
    sys.exit(main())
