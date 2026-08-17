#!/usr/bin/env bash
# Backward-compatible entry point from the Phase 2 experiment.
set -Eeuo pipefail
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/run_lab.sh" "$@"
