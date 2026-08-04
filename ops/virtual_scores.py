#!/usr/bin/env python3
"""ops/virtual_scores.py — batch VIRTUAL FAMILY-CYCLE scoring for the board.

WHY (2026-08-04, operator): the parent/horizon stamp sim agreed with broker
sign on only 3/10 families — anti-informative where it mattered (flipped all
four big losers and a big winner). The accurate shadow metric is the virtual
FAMILY cycle: parent + popper grid replayed over real M5 bid/ask candles
(core/family_cycle.py), the same economics the live book trades.

Runs research/tools/family_cycle_replay.py over every ACTIVE/PROBE/SHADOW
cell with era episodes and atomically writes data/virtual_cycles.json for
the shadowboard. Network-bound (candle fetches), tiny CPU — cron every 6h.
"""
from __future__ import annotations
import json, subprocess, sys, tempfile, os
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "data" / "virtual_cycles.json"


def transform(d: dict) -> dict:
    """Replay-tool JSON -> the board's keyed document."""
    rows = {}
    for row in d.get("rows", []):
        u = row.get("u_list") or []
        rows["|".join((row["cell"], row["setup"], row.get("side", "?")))] = {
            "cycles": row.get("cycles", 0),
            "censored": row.get("censored", 0),
            "net_mean": row.get("net_pips_mean"),      # pips / completed cycle
            "harvest_mean": row.get("harvest_mean"),   # popper share of that
            "wr": (round(sum(1 for x in u if x > 0) / len(u), 3) if u else None),
            "U_pp": row.get("U_pp"), "U_par": row.get("U_par"),
            "grid_lift": row.get("grid_lift"),
            "grid_lift_lcb": row.get("grid_lift_lcb"),
            "coverage": row.get("coverage"), "worst": row.get("worst"),
            "days": row.get("days"),
            "scored": row.get("episodes_scored"),
        }
    return {"t": datetime.now(timezone.utc).isoformat(),
            "since": d.get("since"), "rows": rows}


def main():
    r = subprocess.run(
        [sys.executable, str(REPO / "research" / "tools" / "family_cycle_replay.py"),
         "--json"], capture_output=True, text=True, timeout=3600, cwd=REPO)
    if r.returncode != 0:
        print(f"replay failed rc={r.returncode}: {r.stderr[-500:]}", file=sys.stderr)
        sys.exit(1)
    # the tool prints a human banner first; the JSON document is the last line
    last = [l for l in r.stdout.splitlines() if l.startswith("{")]
    if not last:
        print("no JSON in replay output", file=sys.stderr)
        sys.exit(1)
    d = json.loads(last[-1])
    doc = transform(d)
    fd, tmp = tempfile.mkstemp(dir=str(OUT.parent), suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(doc, f)
    os.replace(tmp, OUT)
    print(f"virtual_cycles.json: {len(rows)} cells scored")


if __name__ == "__main__":
    main()
