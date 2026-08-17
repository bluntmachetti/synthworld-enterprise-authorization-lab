#!/usr/bin/env bash
set -Eeuo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMP_DIR="$(mktemp -d -t synthworld-lab-repro.XXXXXX)"
trap 'rm -rf -- "$TEMP_DIR"' EXIT

"$REPO/bin/fingerprint_reproducible_outputs.py" >"$TEMP_DIR/first.sha256"
"$REPO/bin/run_lab.sh"
"$REPO/bin/fingerprint_reproducible_outputs.py" >"$TEMP_DIR/second.sha256"

diff -u "$TEMP_DIR/first.sha256" "$TEMP_DIR/second.sha256"
printf 'Reproducibility check passed: all scoped outputs are byte-identical.\n'
