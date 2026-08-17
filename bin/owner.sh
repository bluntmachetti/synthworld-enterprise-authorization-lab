#!/usr/bin/env bash
set -Eeuo pipefail

python bin/00_check_inputs.py
python bin/10_map_topology.py
synthworld validate-enterprise-access \
  --input 01-source/generated/britannia-identity-access-import.yaml --json \
  >01-source/generated/import-validation.json
python bin/20_build_world.py
python bin/25_build_adversarial.py
