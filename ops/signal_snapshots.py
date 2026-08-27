"""ops/signal_snapshots.py — record the Signal Command Center's consensus
calls for forward-truth scoring (cron */5, 2026-08-27).

Appends one JSONL row per pair with a live LONG/SHORT consensus to
data/signal_calls.jsonl. ops/signal_accuracy.py later assembles consecutive
rows into consensus episodes and grades them against forward executable price.

Cron-driven, not pull-driven, on purpose: the dashboard's own refresh only
runs while someone is looking (the 2026-08-25 chamber-freshness lesson), and
an accuracy record with viewer-shaped holes would bias toward hours Brock
watches. Rows carry the scoring-formula hash so samples never blend across a
formula change (era discipline).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

CALLS = _ROOT / "data" / "signal_calls.jsonl"


def snapshot(center: dict = None) -> int:
    """Append one call row per pair with a directional consensus. Returns the
    number of rows written. FLAT pairs (no evidence either way) are skipped —
    a no-call is not a call."""
    from ops.signal_center import build_center, formula_hash
    if center is None:
        center = build_center()
    fh = center.get("formula_hash") or formula_hash()
    rows = []
    for p in center.get("pairs", []):
        if p.get("direction") not in ("LONG", "SHORT"):
            continue
        rows.append(json.dumps({
            "ts": center["generated_at"],
            "pair": p["pair"],
            "dir": p["direction"],
            "conf": p["confidence"],
            "net": p["net"],
            "gross": p["gross"],
            "agree": p["agreement"],
            "dist": p["distance_pips"],
            "hold_min": p["hold_min"],
            "n_sig": len(p.get("signals", [])),
            "counts": p.get("counts", {}),
            "fhash": fh,
        }, separators=(",", ":")))
    if rows:
        with CALLS.open("a") as f:
            f.write("\n".join(rows) + "\n")
    return len(rows)


if __name__ == "__main__":
    print("signal_snapshots: wrote %d call row(s)" % snapshot())
