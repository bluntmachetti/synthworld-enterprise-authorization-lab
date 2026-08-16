#!/usr/bin/env bash
#
# topaz_down.sh — tear down the Britannia Phase 2 Topaz stack AND destroy its
# named /db volume, guaranteeing the next `topaz_up.sh` starts from an empty
# directory database (topaz-reference.md §12.6, §12.10 — setting a manifest is
# destructive, so it must always be applied to a fresh store).
#
# Scoped to the `britannia-phase2` compose project only; it cannot touch any other
# stack's containers or volumes.

set -euo pipefail

PROJECT="${TOPAZ_PROJECT:-britannia-phase2}"
INFRA_DIR="${TOPAZ_INFRA_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../infra" && pwd)}"

echo "==> tearing down compose project '${PROJECT}' (with volumes)"
docker compose -p "${PROJECT}" -f "${INFRA_DIR}/docker-compose.yaml" down -v

if docker volume ls -q --filter "name=^${PROJECT}_topaz-db$" | grep -q .; then
	echo "!!! volume ${PROJECT}_topaz-db still exists" >&2
	exit 1
fi

echo "==> down. volume ${PROJECT}_topaz-db removed; next start is a clean slate."
