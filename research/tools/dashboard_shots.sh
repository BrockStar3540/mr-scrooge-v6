#!/usr/bin/env bash
# research/tools/dashboard_shots.sh — regenerate the README dashboard screenshots.
# Run from a machine with Chrome + an SSH tunnel to the live dashboard:
#   ssh -L 18084:127.0.0.1:8084 -N <ec2> &
#   bash research/tools/dashboard_shots.sh
# The panel supports #<tab> deep links (shadow, indicators, book, ...) — added
# 2026-07-27 exactly so these captures are one command.
set -euo pipefail
CHROME="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
BASE="${BASE:-http://localhost:18084}"
OUT="${OUT:-docs/images}"
for tab in shadow indicators; do
  "$CHROME" --headless --disable-gpu --hide-scrollbars \
    --window-size=1500,1900 --virtual-time-budget=12000 \
    --screenshot="$OUT/dashboard-$tab.png" "$BASE#$tab"
  echo "wrote $OUT/dashboard-$tab.png"
done
