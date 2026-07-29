#!/usr/bin/env python3
"""research/tools/calibration_score.py — Score the per-cell calibration artifact.

Greps CAL lines from the systemd journal, fetches the 60-minute (12×M5)
forward MFE from OANDA, and reports per-cell and aggregate:
  - artifact proj_mfe  vs  realized forward-MFE (correlation, MAD)
  - live exp_pips_live vs  realized forward-MFE (correlation, MAD)
  - dead_now calibration: predicted dead rate vs realized dead rate
    in buckets (dead_now < 0.30 / 0.30-0.45 / >0.45)

Which estimator is closer to realized MFE truth: the artifact regression
or the current global-multiplier expected_pips?

Line format (engine _cycle):
  CAL GBP_USD/ny/short proj_mfe=8.2p exp_pips_live=4.1p dead_base=0.39 dead_now=0.31 lean=ema5:+2.345

Usage:
  calibration_score.py [--since YYYY-MM-DD]

Run on EC2 (has OANDA token + journalctl).  Needs ~2 weeks of CAL lines to be
informative; settle_seconds ensures the 60-min window has passed before scoring.
"""
import argparse
import bisect
import json
import math
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.join(_os.path.dirname(__file__), "..", ".."))
from config.pairs import PIP  # canonical 18-pair map (B-108: no more private copies)
FWD_BARS   = 12       # 12 × M5 = 60 minutes forward
SETTLE_S   = 3900     # need 60 min + 5 min buffer before scoring
DEAD_THRESH = 5.0     # pips; trade is "dead" if forward MFE < DEAD_THRESH

# ── Load secrets ──────────────────────────────────────────────────────────────
for ln in open(os.path.expanduser("~/.openclaw/secrets.env")):
    if "=" in ln and not ln.strip().startswith("#"):
        k, v = ln.strip().split("=", 1)
        os.environ[k.strip()] = v.strip().strip('"').strip("'")
TOKEN = os.environ["OANDA_API_TOKEN"]
BASE  = os.environ.get("OANDA_API_URL", "https://api-fxtrade.oanda.com")

# ── Regex ─────────────────────────────────────────────────────────────────────
RX = re.compile(
    r"CAL (\w+)/(\w+)/(\w+) "
    r"proj_mfe=([\d.]+)p exp_pips_live=([\d.]+)p "
    r"dead_base=([\d.]+) dead_now=([\d.]+) lean=(\S+)"
)


def parse_journal(since: str) -> list[dict]:
    raw = subprocess.run(
        ["journalctl", "--user", "-u", "mr-scrooge-v6",
         "--since", since, "--no-pager", "-o", "cat"],
        env={**os.environ,
             "XDG_RUNTIME_DIR": f"/run/user/{os.getuid()}",
             "SYSTEMD_PAGER": ""},
        capture_output=True, text=True,
    ).stdout
    sigs = []
    for line in raw.splitlines():
        m = RX.search(line)
        if m:
            pair, sess, dirn, proj, exp_live, dbase, dnow, lean = m.groups()
            # extract timestamp from journalctl cat output prefix: not present in cat
            # mode -- use file mtime won't work; use 'short-iso' output format instead.
            # Actually for 'cat' mode there's no ts, so re-run with short-iso to get ts.
            pass
    # Re-run with short-iso to get timestamps
    raw2 = subprocess.run(
        ["journalctl", "--user", "-u", "mr-scrooge-v6",
         "--since", since, "--no-pager", "-o", "short-iso"],
        env={**os.environ,
             "XDG_RUNTIME_DIR": f"/run/user/{os.getuid()}",
             "SYSTEMD_PAGER": ""},
        capture_output=True, text=True,
    ).stdout
    TS_RX = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:?\d{2})")
    cur_ts = None
    sigs = []
    for line in raw2.splitlines():
        tm = TS_RX.match(line)
        if tm:
            ts_str = tm.group(1)
            try:
                cur_ts = datetime.fromisoformat(ts_str)
            except ValueError:
                cur_ts = None
        cx = RX.search(line)
        if cx and cur_ts:
            pair, sess, dirn, proj, exp_live, dbase, dnow, lean = cx.groups()
            sigs.append({
                "pair": pair, "session": sess, "direction": dirn,
                "proj_mfe":      float(proj),
                "exp_pips_live": float(exp_live),
                "dead_base":     float(dbase),
                "dead_now":      float(dnow),
                "lean":          lean,
                "ts":            cur_ts,
            })
    return sigs


def fetch_m5_series(pair: str, start: datetime, end: datetime):
    """Return (times, closes) for M5 mid-close candles covering [start, end]."""
    times: list[datetime] = []
    closes: list[float]   = []
    cur = start
    while cur < end:
        url = (f"{BASE}/v3/instruments/{pair}/candles?"
               + urllib.parse.urlencode({
                   "from": cur.isoformat().replace("+00:00", "Z"),
                   "granularity": "M5", "price": "M", "count": 5000,
               }))
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {TOKEN}"})
        data = json.loads(urllib.request.urlopen(req, timeout=30).read())
        cs = [c for c in data.get("candles", []) if c.get("complete")]
        if not cs:
            break
        for c in cs:
            t = datetime.fromisoformat(c["time"].replace("Z", "+00:00"))
            if not times or t > times[-1]:
                times.append(t)
                closes.append(float(c["mid"]["c"]))
        cur = times[-1] + timedelta(seconds=1)
    return times, closes


def fwd_mfe_pips(pair: str, ts: datetime, dirn: str,
                 series_cache: dict) -> float | None:
    """60-min forward MFE in pips from OANDA M5 series.

    MFE = max favorable excursion over the next FWD_BARS M5 bars.
    For 'long': max(close[1..FWD_BARS]) - close[0].
    For 'short': close[0] - min(close[1..FWD_BARS]).
    Returns None if not enough bars.
    """
    if pair not in series_cache:
        return None
    times, closes = series_cache[pair]
    pip = PIP.get(pair, 0.0001)
    idx = bisect.bisect_left(times, ts)
    if idx >= len(times):
        return None
    window = closes[idx : idx + FWD_BARS + 1]
    if len(window) < 2:
        return None
    entry = window[0]
    if dirn == "long":
        mfe = max(window[1:]) - entry
    else:
        mfe = entry - min(window[1:])
    return mfe / pip


def _corr(xs: list[float], ys: list[float]) -> float:
    """Pearson correlation coefficient, or NaN if undefined."""
    n = len(xs)
    if n < 2:
        return float("nan")
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dxs = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dys = math.sqrt(sum((y - my) ** 2 for y in ys))
    if dxs == 0 or dys == 0:
        return float("nan")
    return num / (dxs * dys)


def _mad(predicted: list[float], actual: list[float]) -> float:
    """Mean absolute deviation of predicted vs actual."""
    if not predicted:
        return float("nan")
    return sum(abs(p - a) for p, a in zip(predicted, actual)) / len(predicted)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--since", default="7 days ago",
                    help="journalctl --since value (default: '7 days ago')")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    settle_cutoff = now - timedelta(seconds=SETTLE_S)

    print(f"Parsing journal since '{args.since}' ...", flush=True)
    sigs = parse_journal(args.since)
    print(f"  {len(sigs)} CAL lines found", flush=True)

    sigs = [s for s in sigs if s["ts"] <= settle_cutoff]
    print(f"  {len(sigs)} settled (>{SETTLE_S}s ago)", flush=True)

    if not sigs:
        print("Nothing to score yet — run again after more data accumulates.")
        return

    # Determine date range for OANDA fetch
    pairs_needed = sorted({s["pair"] for s in sigs})
    t_min = min(s["ts"] for s in sigs)
    t_max = max(s["ts"] for s in sigs) + timedelta(hours=2)

    print(f"Fetching M5 series for {pairs_needed} ...", flush=True)
    series_cache: dict[str, tuple] = {}
    for pair in pairs_needed:
        times, closes = fetch_m5_series(pair, t_min, t_max)
        series_cache[pair] = (times, closes)
        print(f"  {pair}: {len(times)} M5 bars", flush=True)

    # Score each signal
    per_cell: dict[str, dict] = defaultdict(lambda: {
        "proj": [], "exp_live": [], "real_mfe": [],
        "dead_now": [], "dead_real": [],
    })
    skipped = 0
    for s in sigs:
        real = fwd_mfe_pips(s["pair"], s["ts"], s["direction"], series_cache)
        if real is None:
            skipped += 1
            continue
        cell = f"{s['pair']}/{s['session']}/{s['direction']}"
        per_cell[cell]["proj"].append(s["proj_mfe"])
        per_cell[cell]["exp_live"].append(s["exp_pips_live"])
        per_cell[cell]["real_mfe"].append(real)
        per_cell[cell]["dead_now"].append(s["dead_now"])
        per_cell[cell]["dead_real"].append(1.0 if real < DEAD_THRESH else 0.0)

    print(f"\n  {skipped} signals skipped (OANDA series gap)")

    # ── Per-cell report ───────────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print(f"PER-CELL CALIBRATION SCORE  (dead threshold = {DEAD_THRESH}p)")
    print("=" * 80)
    print(f"{'CELL':<26}  {'n':>4}  "
          f"{'proj_MAD':>8}  {'exp_MAD':>8}  "
          f"{'proj_corr':>9}  {'exp_corr':>9}  "
          f"{'dead_MAD':>8}  {'winner'}  ")
    print("-" * 80)

    agg = {"proj": [], "exp_live": [], "real_mfe": [],
           "dead_now": [], "dead_real": []}
    for cell in sorted(per_cell):
        d = per_cell[cell]
        n = len(d["real_mfe"])
        if n == 0:
            continue
        proj_mad   = _mad(d["proj"],     d["real_mfe"])
        exp_mad    = _mad(d["exp_live"], d["real_mfe"])
        proj_corr  = _corr(d["proj"],    d["real_mfe"])
        exp_corr   = _corr(d["exp_live"], d["real_mfe"])
        dead_mad   = _mad(d["dead_now"], d["dead_real"])
        winner = "proj" if proj_mad < exp_mad else "exp "
        print(f"{cell:<26}  {n:>4}  "
              f"{proj_mad:>8.2f}  {exp_mad:>8.2f}  "
              f"{proj_corr:>+9.3f}  {exp_corr:>+9.3f}  "
              f"{dead_mad:>8.3f}  {winner}")
        for k in agg:
            agg[k].extend(d[k])

    # ── Aggregate ─────────────────────────────────────────────────────────────
    print("-" * 80)
    n_agg = len(agg["real_mfe"])
    if n_agg:
        proj_mad_agg  = _mad(agg["proj"],     agg["real_mfe"])
        exp_mad_agg   = _mad(agg["exp_live"], agg["real_mfe"])
        proj_corr_agg = _corr(agg["proj"],    agg["real_mfe"])
        exp_corr_agg  = _corr(agg["exp_live"], agg["real_mfe"])
        dead_mad_agg  = _mad(agg["dead_now"], agg["dead_real"])
        winner_agg    = "proj" if proj_mad_agg < exp_mad_agg else "exp "
        print(f"{'AGGREGATE':<26}  {n_agg:>4}  "
              f"{proj_mad_agg:>8.2f}  {exp_mad_agg:>8.2f}  "
              f"{proj_corr_agg:>+9.3f}  {exp_corr_agg:>+9.3f}  "
              f"{dead_mad_agg:>8.3f}  {winner_agg}")

    # ── Dead-risk bucket calibration ──────────────────────────────────────────
    print("\n" + "=" * 80)
    print("DEAD-RISK BUCKET CALIBRATION  (dead_now vs realized dead rate)")
    print("=" * 80)
    print(f"{'BUCKET':<15}  {'n':>5}  {'pred_dead':>10}  {'real_dead':>10}  {'diff':>8}")
    print("-" * 80)
    buckets = [("low  (<0.30)",    0.00, 0.30),
               ("mid  (0.30-0.45)", 0.30, 0.45),
               ("high (>0.45)",    0.45, 1.01)]
    for label, lo, hi in buckets:
        rows = [(dn, dr) for dn, dr in zip(agg["dead_now"], agg["dead_real"])
                if lo <= dn < hi]
        if not rows:
            continue
        bk_n      = len(rows)
        pred_mean = sum(r[0] for r in rows) / bk_n
        real_mean = sum(r[1] for r in rows) / bk_n
        print(f"{label:<15}  {bk_n:>5}  {pred_mean:>10.3f}  {real_mean:>10.3f}  "
              f"{real_mean - pred_mean:>+8.3f}")

    print("\nDone.")


if __name__ == "__main__":
    main()
