#!/usr/bin/env python3
"""research/tools/view_at_time.py — MarketView indicators at a historical instant.

Replays the live feed's EXACT feature code (core/feed/oanda._compute_features)
on candle windows ending at --ts, so "what did the indicators say when this
trade was entered" uses the same formulas the bot trades with today — no
hand-rolled reimplementation (find-the-real-tool doctrine).

Caveats (both small, both stated so results are scoped honestly):
- The last candle of each window is the COMPLETED bar containing --ts; the live
  bot would have seen that bar still forming. Values that read the last bar
  (willr_m5, atr_5m tail, h1_ret_1bar on a boundary) can differ slightly from
  what a live scan at that second saw.
- bid/ask are both set to --price (or the last M5 close if omitted), so
  spread_pips is 0 and mid-derived features use the fill price as mid.

Works for any OANDA instrument, not just the book's 8 pairs (pip inferred for
unmapped pairs: 0.01 JPY-quoted, else 0.0001).

Usage:
  python3 research/tools/view_at_time.py --pair CAD_JPY --ts 2026-03-23T15:55:51Z [--price 115.706] [--json]
"""
from __future__ import annotations
import argparse, dataclasses, json, sys, urllib.parse
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import pandas as pd  # noqa: E402

from config.pairs import PIP                       # noqa: E402
from core.feed import oanda as feed                # noqa: E402


def _candles_to(client, instrument: str, granularity: str, count: int, to_iso: str) -> pd.DataFrame:
    """Historical version of _Client.candles: windows ENDING at to_iso."""
    raw = client.get(
        f"/v3/instruments/{instrument}/candles"
        f"?granularity={granularity}&count={count}&price=M&to={urllib.parse.quote(to_iso)}"
    )["candles"]
    rows = []
    for c in raw:
        m = c["mid"]
        rows.append({
            "time":   c["time"],
            "open":   float(m["o"]),
            "high":   float(m["h"]),
            "low":    float(m["l"]),
            "close":  float(m["c"]),
            "volume": float(c.get("volume", 1.0)),
        })
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pair", required=True, help="OANDA instrument, e.g. CAD_JPY")
    ap.add_argument("--ts", required=True, help="entry time, ISO8601 UTC (e.g. 2026-03-23T15:55:51Z)")
    ap.add_argument("--price", type=float, default=None,
                    help="fill price used as bid=ask=mid (default: last M5 close)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    pair = args.pair
    PIP.setdefault(pair, 0.01 if pair.endswith("JPY") else 0.0001)

    ts = datetime.fromisoformat(args.ts.replace("Z", "+00:00")).astimezone(timezone.utc)
    to_iso = ts.strftime("%Y-%m-%dT%H:%M:%SZ")

    client = feed._Client()
    m5 = _candles_to(client, pair, "M5", feed._M5_COUNT, to_iso)
    h1 = _candles_to(client, pair, "H1", feed._H1_COUNT, to_iso)
    d  = _candles_to(client, pair, "D",  feed._D_COUNT,  to_iso)
    if m5.empty or h1.empty or d.empty:
        print(f"no candle data for {pair} at {to_iso}", file=sys.stderr)
        sys.exit(1)

    px = args.price if args.price is not None else float(m5["close"].iloc[-1])
    view = feed._compute_features(pair, m5, h1, d, px, px, ts)

    out = dataclasses.asdict(view)
    out["_ts"] = to_iso
    out["_price_used"] = px
    if args.json:
        def _clean(v):
            try:
                if v != v: return None       # NaN
            except TypeError:
                pass
            return v
        print(json.dumps({k: _clean(v) for k, v in out.items()}, default=str))
    else:
        for k, v in out.items():
            print(f"{k:>22}: {v}")


if __name__ == "__main__":
    main()
