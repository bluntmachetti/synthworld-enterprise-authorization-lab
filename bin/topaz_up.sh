#!/usr/bin/env bash
#
# topaz_up.sh — bring up the pinned, hermetic Britannia Phase 2 Topaz stack.
#
# Idempotent: re-running against an already-healthy stack is a no-op that simply
# re-polls and re-prints the base URLs. `docker compose up -d` reconciles rather
# than recreates when nothing changed.
#
# Readiness is REST 200-polling from the host against BOTH gateways
# (topaz-reference.md §3): port 9494 speaks the gRPC health protocol, not HTTP, and
# the image ships no curl/grpcurl, so a container-internal healthcheck is not
# possible. The authorizer `needs: [reader]`, so the directory being up does NOT
# imply the policy engine is — hence both probes.
#
# Exits non-zero on readiness timeout, dumping the last container logs.

set -euo pipefail

PROJECT="${TOPAZ_PROJECT:-britannia-phase2}"
INFRA_DIR="${TOPAZ_INFRA_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../infra" && pwd)}"

# Host-side ports. Container side is fixed at the Topaz defaults by
# infra/config/config.yaml; only these host numbers may be remapped.
TOPAZ_AUTHZ_PORT="${TOPAZ_AUTHZ_PORT:-8383}"   # authorizer REST gateway  /api/v2
TOPAZ_DS_PORT="${TOPAZ_DS_PORT:-9393}"         # directory REST gateway   /api/v3

AUTHZ_URL="http://127.0.0.1:${TOPAZ_AUTHZ_PORT}"
DS_URL="http://127.0.0.1:${TOPAZ_DS_PORT}"

READY_ATTEMPTS="${TOPAZ_READY_ATTEMPTS:-60}"

echo "==> compose project : ${PROJECT}"
echo "==> infra dir       : ${INFRA_DIR}"

docker compose -p "${PROJECT}" -f "${INFRA_DIR}/docker-compose.yaml" up -d

echo "==> waiting for both gateways to return 200 ..."
ready=0
for i in $(seq 1 "${READY_ATTEMPTS}"); do
	d=$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 "${DS_URL}/api/v3/directory/manifest" || echo 000)
	a=$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 "${AUTHZ_URL}/api/v2/policies" || echo 000)
	if [ "$d" = "200" ] && [ "$a" = "200" ]; then
		echo "==> ready after ${i} attempt(s)  (directory=${d} authorizer=${a})"
		ready=1
		break
	fi
	sleep 1
done

if [ "$ready" -ne 1 ]; then
	echo "!!! TIMEOUT: gateways not ready after ${READY_ATTEMPTS}s (directory=${d} authorizer=${a})" >&2
	echo "--- last 30 log lines ---" >&2
	docker compose -p "${PROJECT}" -f "${INFRA_DIR}/docker-compose.yaml" logs --tail=30 >&2 || true
	exit 1
fi

cat <<EOF

Topaz is up.

  Authorizer REST gateway : ${AUTHZ_URL}      (/api/v2/authz/is, /api/v2/policies, /api/v2/info)
  Directory  REST gateway : ${DS_URL}      (/api/v3/directory/...)
  Authorizer gRPC         : 127.0.0.1:8282
  Directory  gRPC         : 127.0.0.1:9292
  Health (gRPC protocol)  : 127.0.0.1:9494
  Metrics                 : http://127.0.0.1:9696

  Policy path  : britannia.authz
  Decision     : allowed

  Tear down with: bin/topaz_down.sh   (destroys the ${PROJECT}_topaz-db volume)
EOF
