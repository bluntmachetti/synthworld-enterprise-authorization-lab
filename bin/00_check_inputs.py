#!/usr/bin/env python3
"""Validate explicit source/config provenance before generating artifacts."""

from __future__ import annotations

import hashlib
import importlib.metadata
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "01-source/config/experiment.yaml"
TOPOLOGY = ROOT / "01-source/topology/britannia_global_bank_topology.yaml"


def main() -> int:
    config = yaml.safe_load(CONFIG.read_text("utf-8"))
    actual_topology = hashlib.sha256(TOPOLOGY.read_bytes()).hexdigest()
    expected_topology = config["source"]["topology_sha256"]
    if actual_topology != expected_topology:
        raise SystemExit(
            "topology SHA-256 does not match experiment.yaml: "
            f"expected {expected_topology}, got {actual_topology}"
        )
    installed = importlib.metadata.version("idcognito-synthworld")
    if installed != config["synthworld"]["version"]:
        raise SystemExit(
            f"expected idcognito-synthworld {config['synthworld']['version']}, got {installed}"
        )
    if not isinstance(config["determinism"]["seed"], int):
        raise SystemExit("determinism.seed must be an explicit integer")
    print(f"inputs verified: topology {actual_topology}, seed {config['determinism']['seed']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
