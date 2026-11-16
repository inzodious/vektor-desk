#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
OUT=${1:-${LONG_HISTORY_DATA:-$HOME/.cache/vektor-desk/long-history}/results}
mkdir -p "$OUT"
python3 fetch.py
python3 strategies.py "$OUT/strategies.json"
python3 grid.py "$OUT/grid.json"
python3 deep.py "$OUT/deep.json"
python3 sell_timing.py > "$OUT/sell-timing.txt"
echo "results in $OUT"
