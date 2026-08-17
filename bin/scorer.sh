#!/usr/bin/env bash
set -Eeuo pipefail

python bin/55_seal_regression.py
python bin/60_score.py
python bin/75_negative_controls.py
python bin/80_validate.py
