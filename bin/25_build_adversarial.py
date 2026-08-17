#!/usr/bin/env python3
"""Build the released SynthWorld 0.16 adversarial authorization pack.

This is a benchmark-owner stage. It writes separately typed public and evaluator
artifacts, copies only the public artifact into the SUT-visible tree, and records
deterministic digests. No product adapter imports this module or receives the
evaluator directory.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
from pathlib import Path

import yaml
from synthworld.enterprise.authorization.adversarial import (
    reference_enterprise_adversarial_authorization,
)
from synthworld.enterprise.consumer import canonical_enterprise_model_bytes

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "01-source/config/experiment.yaml"
PUBLIC_ROOT = ROOT / "02-synthworld-public"
EVALUATOR_ROOT = ROOT / "06-evaluator/artifacts/adversarial"
PUBLIC_NAME = "enterprise-adversarial-authorization.json"
EVALUATOR_NAME = "enterprise-adversarial-authorization-evaluator.json"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(document: object) -> bytes:
    return (
        json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode("utf-8")


def write_new(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as output:
        output.write(data)


def manifest(*, visibility: str, name: str, data: bytes, schema_version: str) -> bytes:
    return canonical_json(
        {
            "schema_version": "synthworld-enterprise-authorization-lab-manifest/1",
            "visibility": visibility,
            "synthworld_package_version": importlib.metadata.version("idcognito-synthworld"),
            "artifacts": [
                {
                    "path": name,
                    "schema_version": schema_version,
                    "byte_size": len(data),
                    "sha256": sha256(data),
                }
            ],
        }
    )


def main() -> int:
    config = yaml.safe_load(CONFIG.read_text("utf-8"))
    seed = int(config["determinism"]["seed"])
    benchmark = reference_enterprise_adversarial_authorization(seed=seed)
    public_data = canonical_enterprise_model_bytes(benchmark.public)
    evaluator_data = canonical_enterprise_model_bytes(benchmark.evaluator)

    evaluator_public = EVALUATOR_ROOT / "public"
    evaluator_truth = EVALUATOR_ROOT / "evaluator"
    write_new(evaluator_public / PUBLIC_NAME, public_data)
    write_new(
        evaluator_public / "manifest.json",
        manifest(
            visibility="public",
            name=PUBLIC_NAME,
            data=public_data,
            schema_version=benchmark.public.schema_version,
        ),
    )
    write_new(evaluator_truth / EVALUATOR_NAME, evaluator_data)
    write_new(
        evaluator_truth / "manifest.json",
        manifest(
            visibility="evaluator",
            name=EVALUATOR_NAME,
            data=evaluator_data,
            schema_version=benchmark.evaluator.schema_version,
        ),
    )

    sut_public = PUBLIC_ROOT / "adversarial"
    write_new(sut_public / PUBLIC_NAME, public_data)
    write_new(
        sut_public / "manifest.json",
        manifest(
            visibility="public",
            name=PUBLIC_NAME,
            data=public_data,
            schema_version=benchmark.public.schema_version,
        ),
    )

    index_path = PUBLIC_ROOT / "PUBLIC-INDEX.json"
    index = json.loads(index_path.read_text("utf-8"))
    index["sha256"][f"adversarial/{PUBLIC_NAME}"] = sha256(public_data)
    index["sha256"]["adversarial/manifest.json"] = sha256(
        (sut_public / "manifest.json").read_bytes()
    )
    index_path.write_bytes(canonical_json(index))

    canary = sha256(evaluator_data + b"synthworld-lab-isolation-canary").encode()
    write_new(ROOT / "06-evaluator/ISOLATION-CANARY", canary + b"\n")
    owner_receipt = {
        "schema_version": "synthworld-enterprise-authorization-owner-receipt/1",
        "seed": seed,
        "synthworld_package_version": importlib.metadata.version("idcognito-synthworld"),
        "topology_sha256": sha256(
            (ROOT / "01-source/topology/britannia_global_bank_topology.yaml").read_bytes()
        ),
        "public_index_sha256": sha256(index_path.read_bytes()),
        "adversarial_public_sha256": sha256(public_data),
        "adversarial_evaluator_sha256": sha256(evaluator_data),
    }
    write_new(ROOT / "06-evaluator/OWNER-RECEIPT.json", canonical_json(owner_receipt))
    print(json.dumps(owner_receipt, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
