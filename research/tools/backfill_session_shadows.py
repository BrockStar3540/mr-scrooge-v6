#!/usr/bin/env python3
"""research/tools/backfill_session_shadows.py — retroactive SHADOW stamps for a
session block that was disabled while its siblings accrued evidence.

Born 2026-08-16: USD_CHF/asia sat at enabled:false while every other block
stamped; the operator enabled it and ordered a backfill. The engine can't
stamp the past, but the evidence can be reconstructed HONESTLY:

- Features come from the LIVE feed's exact code via the view_at_time path
  (core/feed/oanda._compute_features on candle windows ending at each bar) —
  no hand-rolled indicator math (find-the-real-tool doctrine).
- Conditions are evaluated with the same min/max semantics the CellModule
  uses, one evaluation per closed M5 bar (the live scan cadence), episodes on
  condition ONSET (pass after a non-pass), matching live episode folding.
- entry/bid/ask/spread come from bid-ask candles at the stamp bar, so the
  executable-exit-v2 scorer prices the same toll live stamps pay. The one
  divergence (stated): the view's own spread_pips is overridden with the BA
  spread so spread-gated setups are judged against real spreads.
- Episodes are inserted UNSCORED (scores=None) and flagged "backfill": true —
  the standard scorer resolves them through the identical _score_v2 replay,
  and provenance stays auditable forever.
- Each setup backfills only from its own `wired` date: no pre-wiring
  evidence, cohorts stay comparable.

Usage:
  python3 research/tools/backfill_session_shadows.py --pair USD_CHF --session asia \\
      --start 2026-08-07 [--end 2026-08-16] [--dry-run]

Run with the trader STOPPED (shares data/shadowboard.json with the refresh
daemon).
"""
from __future__ import annotations
import argparse, json, sys, time
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

SESS_HOURS = {"asia": set(list(range(22, 24)) + list(range(0, 7))),
              "london": set(range(7, 13)),
              "ny": set(range(13, 22))}


def _pip(pair):
    try:
        from config.pairs import PIP
        return PIP.get(pair, 0.01 if pair.endswith("JPY") else 0.0001)
    except Exception:
        return 0.01 if pair.endswith("JPY") else 0.0001


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pair", required=True)
    ap.add_argument("--session", required=True, choices=list(SESS_HOURS))
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", default=None)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    from research.tools.view_at_time import _candles_to           # noqa
    from core.feed import oanda as feed                           # noqa
    client = feed._Client()
    pip = _pip(a.pair)

    cells = json.loads((REPO / "config" / "cells" / f"{a.pair}.json").read_text())
    setups = (cells.get("sessions", {}).get(a.session, {}) or {}).get("setups", [])
    setups = [s for s in setups if s.get("status") == "SHADOW" and s.get("conditions")]
    print(f"{a.pair}/{a.session}: {len(setups)} SHADOW setups")

    # bid/ask candles across the window for entry pricing + real spreads
    end = a.end or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    t0 = datetime.fromisoformat(a.start).replace(tzinfo=timezone.utc)
    t1 = datetime.fromisoformat(end).replace(tzinfo=timezone.utc)
    ba = {}
    cur = t0
    while cur < t1:
        raw = client.get(
            f"/v3/instruments/{a.pair}/candles?granularity=M5&count=500"
            f"&from={cur.strftime('%Y-%m-%dT%H:%M:%SZ')}&price=BA")
        cs = raw.get("candles", [])
        if not cs:
            break
        for c in cs:
            if c.get("complete"):
                ba[c["time"][:16]] = (float(c["bid"]["c"]), float(c["ask"]["c"]))
        nxt = datetime.fromisoformat(cs[-1]["time"][:19] + "+00:00")
        if nxt <= cur:
            break
        cur = nxt
    print(f"bid/ask bars loaded: {len(ba)}")

    hours = SESS_HOURS[a.session]
    bars = sorted(k for k in ba if int(k[11:13]) in hours and a.start <= k[:10] < end)
    print(f"in-session bars to evaluate: {len(bars)}")

    store = REPO / "data" / "shadowboard.json"
    db = json.loads(store.read_text())
    eps = db["episodes"]
    prev_pass = {}
    made, evald = 0, 0
    for ts in bars:
        view = None
        for s in setups:
            wired = str(s.get("wired") or "2026-01-01")
            if ts[:10] < wired:
                continue
            if view is None:   # compute once per bar, real feature path
                try:
                    m5 = _candles_to(client, a.pair, "M5", feed._M5_COUNT, ts + ":00Z")
                    h1 = _candles_to(client, a.pair, "H1", feed._H1_COUNT, ts + ":00Z")
                    d = _candles_to(client, a.pair, "D", feed._D_COUNT, ts + ":00Z")
                    px = ba[ts]
                    view = feed._compute_features(
                        a.pair, m5, h1, d, px[0], px[1],
                        datetime.fromisoformat(ts + ":00+00:00"))
                    time.sleep(0.03)
                except Exception as e:
                    print(f"  view failed {ts}: {e}")
                    break
            ok = True
            for c in s.get("conditions", []):
                v = getattr(view, c.get("feature", ""), None)
                if v is None:
                    ok = False; break
                if c.get("min") is not None and float(v) < float(c["min"]):
                    ok = False; break
                if c.get("max") is not None and float(v) > float(c["max"]):
                    ok = False; break
            key = s["id"]
            onset = ok and not prev_pass.get(key, False)
            prev_pass[key] = ok
            evald += 1
            if not onset:
                continue
            bid, ask = ba[ts]
            side = s.get("side", "long")
            ek = f"{a.pair}/{a.session}|{s['id']}|{side}|{ts}"
            if ek in eps:
                continue
            eps[ek] = {"cell": f"{a.pair}/{a.session}", "setup": s["id"],
                       "side": side, "status": "SHADOW",
                       "t": ts + ":00+00:00", "mv": 2,
                       "horizon_min": int(s.get("horizon_min") or 240),
                       "exit_config": s.get("exit") or {},
                       "entry": ask if side == "long" else bid,
                       "bid": bid, "ask": ask,
                       "spread": round((ask - bid) / pip, 1),
                       "scores": None, "backfill": True}
            made += 1
    print(f"evaluations: {evald}, episodes created: {made}")
    if not a.dry_run and made:
        tmp = store.with_suffix(".tmp")
        tmp.write_text(json.dumps(db))
        tmp.replace(store)
        print("db written")


if __name__ == "__main__":
    main()
