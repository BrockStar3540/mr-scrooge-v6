#!/usr/bin/env python3
"""research/tools/mark_closed_market_2026-10-21.py — retro-mark executable-exit-v2
episodes that were stamped while FX was closed.

The scan loop keeps running on the frozen Friday quote all weekend, so the
board held ~2,651 resolved v2 episodes whose "entry" was a price no broker
would fill (MARKET_HALTED) and whose forward path started at the Sunday
reopen — the weekend gap was booked as P&L. ops/shadowboard._score_v2 now
scores such stamps market_closed going forward; this tool applies the SAME
test (ops.shadowboard._market_closed_at: no M5 bar within 30 min after the
stamp, or none within 30 min before it)
to the episodes already scored.

Two phases so the trader is down for seconds, not minutes:
  --plan PLAN.json   read-only; fetches candles per unique (pair, stamp minute)
                     for weekend-window candidates and writes the keys to mark.
                     Safe with the trader running.
  --apply PLAN.json  RUN WITH THE TRADER STOPPED (shares data/shadowboard.json
                     with the refresh daemon). Backs up the store, then sets
                     each planned episode's scores to _market_closed_score(),
                     flagged "market_closed_mark": "2026-10-21". Original scores
                     stay in the backup.

Candidates are v2 episodes with scores, stamped Fri >= 20:00 to Sun 23:59 UTC
(a superset of the close in both DST regimes); the candle test decides.
"""
from __future__ import annotations
import argparse, json, os, sys, tempfile, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
import ops.shadowboard as sb

DB = REPO / "data" / "shadowboard.json"
BAK = DB.with_name("shadowboard.json.pre-closed-market-20261021")
MARK = "2026-10-21"


def atomic_write(path, obj):
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(obj, f)
    os.replace(tmp, path)


def weekend_window(t: datetime) -> bool:
    d = t.weekday()
    return (d == 4 and t.hour >= 20) or d == 5 or d == 6


def plan(out: Path):
    eps = json.loads(DB.read_text())["episodes"]
    cands = {}
    for k, e in eps.items():
        if e.get("mv") != 2 or not e.get("scores") or e["scores"].get("market_closed"):
            continue
        t0 = datetime.fromisoformat(e["t"]).astimezone(timezone.utc)
        if weekend_window(t0):
            cands.setdefault((e["cell"].split("/")[0], e["t"]), []).append(k)
    print(f"candidate episodes: {sum(map(len, cands.values()))} "
          f"across {len(cands)} (pair, stamp) fetches", flush=True)
    url, tok = sb._creds()
    keys, failed = [], 0
    for i, ((pair, t), ks) in enumerate(sorted(cands.items()), 1):
        t0 = datetime.fromisoformat(t)
        u = (f"{url}/v3/instruments/{pair}/candles?granularity=M5"
             f"&from={t0.strftime('%Y-%m-%dT%H:%M:%SZ')}&count=3&price=BA")
        try:
            cs = json.load(urllib.request.urlopen(urllib.request.Request(
                u, headers={"Authorization": f"Bearer {tok}"}), timeout=20))["candles"]
            prev = sb._bars_before(pair, t0, url, tok)
        except Exception:
            failed += 1
            continue
        cs = [c for c in cs if c.get("complete", True)]
        if sb._market_closed_at(t0, cs, prev):
            keys += ks
        time.sleep(0.05)
        if i % 200 == 0:
            print(f"  {i}/{len(cands)} marked={len(keys)} failed={failed}", flush=True)
    resolved = sum(1 for k in keys if eps[k]["scores"].get("net240") is not None)
    print(f"to mark: {len(keys)} ({resolved} resolved), fetch failures: {failed}",
          flush=True)
    out.write_text(json.dumps({"made": datetime.now(timezone.utc).isoformat(),
                               "keys": sorted(keys), "fetch_failures": failed}))


def apply(src: Path):
    keys = json.loads(src.read_text())["keys"]
    raw = DB.read_text()
    if not BAK.exists():
        BAK.write_text(raw)
        print(f"backup written: {BAK.name}", flush=True)
    db = json.loads(raw)
    eps = db["episodes"]
    n = 0
    for k in keys:
        e = eps.get(k)
        if e is None or (e.get("scores") or {}).get("market_closed"):
            continue
        e["scores"] = sb._market_closed_score()
        e["market_closed_mark"] = MARK
        n += 1
    atomic_write(DB, db)
    print(f"marked {n} of {len(keys)} planned episodes", flush=True)


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--plan", type=Path)
    g.add_argument("--apply", type=Path)
    a = ap.parse_args()
    plan(a.plan) if a.plan else apply(a.apply)


if __name__ == "__main__":
    main()
