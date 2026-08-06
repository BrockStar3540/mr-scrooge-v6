#!/usr/bin/env python3
"""research/tools/ema_regime_gate.py — does trend alignment improve the book?

QUESTION (2026-08-06): the SpikePro manuals gate every setup on 69/200 EMA
alignment. Our port of that is `ema_trend_pips` (EMA14-EMA40 on M5 ~= 70 vs 200
minutes). Historical episodes predate the feature, so this tool RECONSTRUCTS it
from M5 candles at each episode's stamp time and asks whether requiring
alignment would have improved realized episode outcomes.

Method: for every resolved executable-exit-v2 episode, fetch the M5 closes
ending at the stamp, compute ema_trend_pips, then split episodes into
ALIGNED (long & trend > +band, short & trend < -band) vs COUNTER and compare
cost-adjusted net240. Read-only; touches no config and no live state.

Usage: python3 research/tools/ema_regime_gate.py [--band 0.5] [--json]
"""
from __future__ import annotations
import argparse, json, os, statistics as st, sys, urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from core.feed.structure import ema_trend_pips
from core.trial_stats import episode_net

PIP = lambda p: 0.01 if "JPY" in p else 0.0001
NEED = 60          # M5 closes needed before a stamp for a stable EMA40


def _secrets() -> dict:
    out = {}
    for ln in open(os.path.expanduser("~/.openclaw/secrets.env")):
        if "=" in ln and not ln.strip().startswith("#"):
            k, _, v = ln.strip().partition("=")
            out[k] = v
    return out


def _candles(pair: str, t0: datetime, t1: datetime, tok: str, base: str) -> list:
    out, cur = [], t0
    while cur < t1:
        nxt = min(cur + timedelta(minutes=5 * 4800), t1)
        url = (f"{base}/v3/instruments/{pair}/candles?granularity=M5&price=M"
               f"&from={cur.strftime('%Y-%m-%dT%H:%M:%SZ')}"
               f"&to={nxt.strftime('%Y-%m-%dT%H:%M:%SZ')}")
        req = urllib.request.Request(url, headers={"Authorization": "Bearer " + tok})
        try:
            cs = json.loads(urllib.request.urlopen(req, timeout=30).read())["candles"]
            out += [(c["time"], float(c["mid"]["c"])) for c in cs if c.get("complete")]
        except Exception as e:
            print(f"  WARN {pair} {cur:%m-%d}: {e}", file=sys.stderr)
        cur = nxt
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--band", type=float, default=0.5,
                    help="pips of EMA separation required to call a regime")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    S = _secrets()
    tok, base = S["OANDA_API_TOKEN"], S["OANDA_API_URL"].rstrip("/")
    db = json.load(open(REPO / "data" / "shadowboard.json"))
    eps = [e for e in db["episodes"].values()
           if (e.get("scores") or {}).get("mv") == 2
           and e["scores"].get("net240") is not None]
    by_pair = defaultdict(list)
    for e in eps:
        by_pair[e["cell"].split("/")[0]].append(e)

    rows = []
    for pair, group in sorted(by_pair.items()):
        ts = sorted(e["t"] for e in group)
        t0 = datetime.fromisoformat(ts[0]) - timedelta(minutes=5 * (NEED + 10))
        t1 = datetime.fromisoformat(ts[-1]) + timedelta(minutes=10)
        series = _candles(pair, t0.astimezone(timezone.utc),
                          t1.astimezone(timezone.utc), tok, base)
        if len(series) < NEED:
            continue
        times = [s[0] for s in series]
        closes = [s[1] for s in series]
        pip = PIP(pair)
        for e in group:
            t = e["t"]
            i = 0
            while i < len(times) and times[i] <= t:
                i += 1
            if i < NEED:
                continue
            trend = ema_trend_pips(closes[max(0, i - NEED):i], pip)
            net = episode_net(e["scores"]["net240"], e.get("spread"), pair,
                              slippage_pips=0.5, executable=True)
            if net is None:
                continue
            side = e.get("side")
            aligned = (trend > args.band) if side == "long" else (trend < -args.band)
            neutral = abs(trend) <= args.band
            rows.append({"cell": e["cell"], "setup": e["setup"], "side": side,
                         "trend": trend, "net": net,
                         "state": "neutral" if neutral else
                                  ("aligned" if aligned else "counter")})

    def agg(rs):
        if not rs:
            return None
        n = [r["net"] for r in rs]
        return {"n": len(n), "avg": round(sum(n) / len(n), 2),
                "wr": round(sum(1 for x in n if x > 0) / len(n), 3),
                "med": round(st.median(n), 2)}

    overall = {k: agg([r for r in rows if r["state"] == k])
               for k in ("aligned", "counter", "neutral")}
    if args.json:
        print(json.dumps({"band": args.band, "overall": overall,
                          "n_scored": len(rows)}, indent=1))
        return

    print(f"EMA REGIME GATE — reconstructed ema_trend_pips (EMA14-EMA40 M5), "
          f"band +/-{args.band}p")
    print(f"episodes scored: {len(rows)}\n")
    print(f"{'state':<10}{'n':>6}{'avg net':>10}{'median':>9}{'WR':>8}")
    for k in ("aligned", "counter", "neutral"):
        a = overall[k]
        if a:
            print(f"{k:<10}{a['n']:>6}{a['avg']:>10.2f}{a['med']:>9.2f}{a['wr']*100:>7.0f}%")
    al, co = overall["aligned"], overall["counter"]
    if al and co:
        print(f"\nedge from requiring alignment: {al['avg'] - co['avg']:+.2f}p per episode")

    print("\nper-setup (setups with >=8 aligned and >=8 counter):")
    by_setup = defaultdict(list)
    for r in rows:
        by_setup[(r["cell"], r["setup"])].append(r)
    hits = []
    for (cell, sid), rs in sorted(by_setup.items()):
        a = agg([r for r in rs if r["state"] == "aligned"])
        c = agg([r for r in rs if r["state"] == "counter"])
        if a and c and a["n"] >= 8 and c["n"] >= 8:
            hits.append((a["avg"] - c["avg"], cell, sid, a, c))
    for d, cell, sid, a, c in sorted(hits, reverse=True):
        print(f"  {cell}/{sid:<28} aligned {a['avg']:+7.2f}p({a['n']:>3})  "
              f"counter {c['avg']:+7.2f}p({c['n']:>3})  delta {d:+7.2f}p")
    if not hits:
        print("  (none have both arms at n>=8 yet)")


if __name__ == "__main__":
    main()
