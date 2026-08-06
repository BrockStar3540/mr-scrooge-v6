#!/usr/bin/env python3
"""research/tools/rescore_censored.py — recover censored episodes (2026-08-06).

The 2026-07-31 charter censored any stamp still open at horizon_min, dropping
its net from every aggregate. Measured on a 60-episode sample: 80% of those
resolve when followed to a real exit, and the recovered set has a NEGATIVE mean
(-4.5p) despite 75% winners — 1-in-4 ran to a full stop. Censoring was
therefore hiding losses and flattering every cell in the book.

This rescoring walks the episode DB and re-runs the (now follow-through) scorer
on every censored v2 episode, writing results back atomically. Read-heavy on the
OANDA candles endpoint; run it once after deploying the scorer change.
"""
from __future__ import annotations
import json, os, sys, tempfile, time
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
import ops.shadowboard as sb

DB = REPO / "data" / "shadowboard.json"


def main():
    db = json.loads(DB.read_text())
    eps = db["episodes"]
    todo = [k for k, e in eps.items()
            if (e.get("scores") or {}).get("mv") == 2
            and (e.get("scores") or {}).get("net240") is None]
    print(f"censored v2 episodes to rescore: {len(todo)}", flush=True)
    recovered = still = failed = 0
    t0 = time.time()
    for i, k in enumerate(todo, 1):
        e = eps[k]
        try:
            s = sb._score_v2(e, datetime.fromisoformat(e["t"]))
        except Exception as exc:
            failed += 1
            s = None
        if s is not None:
            eps[k]["scores"] = s
            if s.get("net240") is not None:
                recovered += 1
            else:
                still += 1
        if i % 25 == 0 or i == len(todo):
            el = time.time() - t0
            print(f"  {i}/{len(todo)}  recovered={recovered} still_open={still} "
                  f"failed={failed}  {el/60:.1f}min", flush=True)
            fd, tmp = tempfile.mkstemp(dir=str(DB.parent), suffix=".tmp")
            with os.fdopen(fd, "w") as f:
                json.dump(db, f)
            os.replace(tmp, DB)     # checkpoint so a crash cannot lose work
    print(f"\nDONE recovered={recovered} still_open={still} failed={failed} "
          f"in {(time.time()-t0)/60:.1f}min", flush=True)


if __name__ == "__main__":
    main()
