#!/usr/bin/env bash
#
# Complete reproduction, from an empty working directory containing only
# britannia_global_bank_topology.yaml and this repository's scripts.
#
#   bin/run_all.sh              full run
#   bin/run_all.sh --keep-up    full run, leave Topaz running
#
# Requires: docker + docker compose v2, uv (or python3.12+ with pip), curl.
# Touches nothing outside this directory except the pinned container image it
# pulls and a compose project named britannia-phase2.

set -Eeuo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

KEEP_UP=0
[[ "${1:-}" == "--keep-up" ]] && KEEP_UP=1

VENV="$REPO/.venv"
PY="$VENV/bin/python"

step() { printf '\n\033[1m>> %s\033[0m\n' "$*"; }
fail() { printf '\n\033[31mFAILED: %s\033[0m\n' "$*" >&2; exit 1; }

cleanup() {
  if [[ $KEEP_UP -eq 0 ]]; then
    step "[teardown] stopping Topaz and destroying its volume"
    bash "$REPO/bin/topaz_down.sh" || true
  else
    echo "(leaving Topaz running as requested)"
  fi
}
trap cleanup EXIT

# --------------------------------------------------------------- 0. clean setup
step "[0/9] clean setup: pinned virtualenv from requirements.lock"
rm -rf "$REPO/02-synthworld-public" \
       "$REPO/03-topaz-input/model" "$REPO/03-topaz-input/policy" \
       "$REPO/03-topaz-input/directory" "$REPO/03-topaz-input/requests" \
       "$REPO/04-topaz-results" "$REPO/05-submission" \
       "$REPO/06-evaluator" "$REPO/reports" "$REPO/viz"
mkdir -p "$REPO/03-topaz-input" "$REPO/04-topaz-results" "$REPO/05-submission" \
         "$REPO/06-evaluator" "$REPO/reports" "$REPO/viz" "$REPO/01-source/topology" \
         "$REPO/01-source/generated"

# The supplied topology is the only external input. Stage it into zone 1 unchanged.
cp -f "$REPO/britannia_global_bank_topology.yaml" \
      "$REPO/01-source/topology/britannia_global_bank_topology.yaml"

if [[ ! -x "$PY" ]]; then
  if command -v uv >/dev/null 2>&1; then
    uv venv --python 3.13 "$VENV"
    uv pip install --python "$PY" --require-hashes -r "$REPO/requirements.lock"
  else
    python3 -m venv "$VENV"
    "$VENV/bin/pip" install --require-hashes -r "$REPO/requirements.lock"
  fi
fi
"$PY" -c "import synthworld" || fail "synthworld import failed"
"$PY" - <<'EOF'
import importlib.metadata as md
v = md.version("idcognito-synthworld")
assert v == "0.15.0", f"expected idcognito-synthworld 0.15.0, got {v}"
print(f"idcognito-synthworld {v}")
EOF

# ------------------------------------------------- 1. deterministic generation
step "[1/9] map topology -> SynthWorld enterprise identity/access import"
"$PY" bin/10_map_topology.py

step "[2/9] validate the import with the released CLI"
"$VENV/bin/synthworld" validate-enterprise-access \
  --input 01-source/generated/britannia-identity-access-import.yaml --json \
  | "$PY" -c 'import json,sys; d=json.load(sys.stdin); print("valid:",d["valid"],"diagnostics:",len(d["diagnostics"])); sys.exit(0 if d["valid"] else 1)' \
  || fail "generated import did not validate"

step "[3/9] compile the world, corpus, overlays and evaluator truth"
"$PY" bin/20_build_world.py

# --------------------------------------------- 2. public artifact validation
step "[4/9] project public artifacts into Topaz model, policy, directory, requests"
"$PY" bin/30_project_topaz.py

# ------------------------------------------------- 3. topaz startup + execution
step "[5/9] start Topaz (pinned by digest) and wait for readiness"
bash bin/topaz_up.sh

step "[6/9] install model + policy, load directory, verify, run decisions"
"$PY" bin/40_run_topaz.py

# ------------------------------------------------- 4. blinded submission
step "[7/9] build the blinded submission and seal its digest"
"$PY" bin/50_build_submission.py

# ------------------------------------------------- 5. isolated scoring
step "[8/9] score against evaluator truth (verifies the seal first)"
"$PY" bin/60_score.py

# ------------------------------------------------- 6. visualization + validation
step "[9/9] render the public-only HTML view and run the validation report"
"$PY" bin/70_visualize.py
"$PY" bin/80_validate.py || fail "validation report has failing checks"

printf '\n\033[32mComplete.\033[0m\n'
printf '  scoring report : 06-evaluator/scoring/scoring-report.json\n'
printf '  validation     : reports/validation-report.json\n'
printf '  visualization  : viz/britannia-world.html\n'
