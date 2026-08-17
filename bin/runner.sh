#!/usr/bin/env bash
set -Eeuo pipefail

python bin/wait_topaz.py
python bin/05_check_isolation.py
python bin/40_run_topaz.py
python bin/45_run_adversarial.py
python bin/50_build_submission.py
python bin/70_visualize.py
