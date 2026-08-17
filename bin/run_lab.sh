#!/usr/bin/env bash
set -Eeuo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

export LAB_UID="${LAB_UID:-$(id -u)}"
export LAB_GID="${LAB_GID:-$(id -g)}"
COMPOSE=(docker compose --project-directory "$REPO" -f "$REPO/compose.yaml")
TOPOLOGY_INPUT="$REPO/britannia_global_bank_topology.yaml"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --topology)
      [[ $# -ge 2 ]] || { printf 'missing path after --topology\n' >&2; exit 2; }
      TOPOLOGY_INPUT="$2"
      shift 2
      ;;
    -h|--help)
      printf 'usage: %s [--topology PATH]\n' "$0"
      exit 0
      ;;
    *)
      printf 'unknown argument: %s\n' "$1" >&2
      exit 2
      ;;
  esac
done

step() { printf '\n>> %s\n' "$*"; }
fail() { printf '\nFAILED: %s\n' "$*" >&2; exit 1; }

cleanup() {
  step "teardown: stop Topaz and remove the experiment database"
  "${COMPOSE[@]}" down --volumes --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT

[[ "$REPO" == "/home/"*"/Projects/agent-auth-lab" || -f "$REPO/compose.yaml" ]] \
  || fail "refusing to clean an unresolved repository path: $REPO"

step "clean generated experiment zones"
[[ -f "$TOPOLOGY_INPUT" ]] || fail "topology file not found: $TOPOLOGY_INPUT"
for target in \
  "$REPO/01-source/generated" "$REPO/01-source/topology" \
  "$REPO/02-synthworld-public" "$REPO/03-topaz-input" \
  "$REPO/04-topaz-results" "$REPO/05-submission" \
  "$REPO/06-evaluator" "$REPO/07-reports" "$REPO/viz"; do
  [[ "$target" == "$REPO/"* && "$target" != "$REPO" ]] \
    || fail "refusing unsafe generated-zone target: $target"
  rm -rf -- "$target"
  mkdir -p -- "$target"
done
cp -- "$TOPOLOGY_INPUT" \
  "$REPO/01-source/topology/britannia_global_bank_topology.yaml"

step "build the digest-locked lab image"
"${COMPOSE[@]}" build --pull=false owner

step "benchmark owner: generate public and evaluator artifacts"
"${COMPOSE[@]}" run --rm --no-deps owner

step "adapter: project public artifacts into Topaz inputs"
"${COMPOSE[@]}" run --rm --no-deps projector

step "start digest-pinned Topaz on the internal SUT network"
"${COMPOSE[@]}" up -d --no-build topaz

step "SUT runner: prove isolation, execute both lanes, and seal the submission"
"${COMPOSE[@]}" run --rm --no-deps runner

step "scorer: verify the seal before opening evaluator truth"
"${COMPOSE[@]}" run --rm --no-deps scorer

step "negative isolation regression: evaluator capability must be rejected"
if "${COMPOSE[@]}" --profile isolation-regression run --rm --no-deps \
  -e ISOLATION_REPORT=/tmp/isolation-regression.json isolation-regression; then
  fail "isolation regression unexpectedly accepted an evaluator mount"
fi

printf '\nComplete.\n'
printf '  machine report : 07-reports/validation-report.json\n'
printf '  scoring report : 07-reports/scoring/scoring-report.json\n'
printf '  public view    : viz/britannia-world.html\n'
