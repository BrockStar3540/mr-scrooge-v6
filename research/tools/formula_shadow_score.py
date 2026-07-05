#!/usr/bin/env python3
"""research/tools/formula_shadow_score.py — Live-confirmation scorer for FORMULA stamps.

Greps FORMULA lines from the systemd journal, then for each qualifying bar
simulates the ratchet at the formula's TARGET geometry (sl/trigger/trail from
the registry's best_cell geo) over a 60-min or 240-min forward window using
OANDA M5 candles.  Reports PRIMARY and CONTROL formulas separately.

  PRIMARY  — deep-OOS validated; live sim should approach expected_ev
  CONTROL  — 2026-pocket artifact; live falsification (expected to be negative)

Per formula report:
  - n_stamps  : qualifying bars seen in the journal
  - sim_ev    : simulated EV/trade net of spread
  - win_rate  : fraction of trades where ratchet exits in profit
  - exp_ev    : registry expected EV (sequential OOS for CONTROL = negative)
  - delta     : sim_ev - exp_ev

Ratchet simulation:
  Entry at close of the qualifying M5 bar.
  SL at entry ± sl pips against direction.
  Once price moves trigger pips in favor, trail = trail pips from peak/trough.
  Exit: trailing SL crossed, or horizon close (neutral).

Line format emitted by engine (core/engine.py _cycle):
  FORMULA {cell} qualifies side={dir} conds_met={k}/{n}
    geo={sl}/{trig}/{trail} exp_ev={x:+.2f} ts={iso}

Usage:
  formula_shadow_score.py [--since YYYY-MM-DD]

Run on EC2 (has OANDA token + journalctl).
"""
import argparse
import bisect
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
import urllib.parse
import urllib.request

REPO = Path(__file__).resolve().parents[2]
PIP = {
    "AUD_JPY": 0.01,  "EUR_JPY": 0.01, "USD_JPY": 0.01,
    "AUD_USD": 0.0001, "EUR_USD": 0.0001, "GBP_USD": 0.0001,
    "USD_CAD": 0.0001, "USD_CHF": 0.0001,
}
SPREAD_PIPS = {
    "AUD_JPY": 1.0, "EUR_JPY": 1.0, "USD_JPY": 0.8,
    "AUD_USD": 0.7, "EUR_USD": 0.6, "GBP_USD": 0.8,
    "USD_CAD": 0.9, "USD_CHF": 0.8,
}
SETTLE_S     = 3900    # 60 min + 5 min buffer
SETTLE_S_4H  = 14700   # 240 min + 5 min buffer

# ── Load secrets ──────────────────────────────────────────────────────────────
for ln in open(os.path.expanduser("~/.openclaw/secrets.env")):
    if "=" in ln and not ln.strip().startswith("#"):
        k, v = ln.strip().split("=", 1)
        os.environ[k.strip()] = v.strip().strip('"').strip("'")
TOKEN = os.environ["OANDA_API_TOKEN"]
BASE  = os.environ.get("OANDA_API_URL", "https://api-fxtrade.oanda.com")

# ── Regex for FORMULA lines ───────────────────────────────────────────────────
# FORMULA USD_JPY/ny/long qualifies side=long conds_met=1/1 geo=20.0/3.0/1.5 exp_ev=+1.20 ts=...
RX = re.compile(
    r"FORMULA (\w+/\w+/\w+) qualifies side=(\w+) "
    r"conds_met=(\d+)/(\d+) "
    r"geo=([\d.]+)/([\d.]+)/([\d.]+) "
    r"exp_ev=([+-]?[\d.]+) "
    r"(?:status=(\w+) )?"
    r"ts=(\S+)"
)
TS_RX = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:?\d{2})")

# ── Load registry status map ──────────────────────────────────────────────────
def _load_registry_status() -> dict[str, str]:
    """Return {cell: status} from formula_shadow module."""
    try:
        sys.path.insert(0, str(REPO))
        from modules.signals.formula_shadow import _REGISTRY
        return {e.cell + "/" + str(e.horizon): e.status for e in _REGISTRY}
    except Exception:
        return {}

# Build a cell->status map keyed by cell string (pair/session/direction).
# If a cell appears with multiple horizons, prefer PRIMARY.
def _build_status_map() -> dict[str, str]:
    try:
        sys.path.insert(0, str(REPO))
        from modules.signals.formula_shadow import _REGISTRY
        out: dict[str, str] = {}
        priority = {"PRIMARY": 3, "CONTROL": 2, "INACTIVE": 1}
        for e in _REGISTRY:
            cur = out.get(e.cell)
            if cur is None or priority.get(e.status, 0) > priority.get(cur, 0):
                out[e.cell] = e.status
        return out
    except Exception:
        return {}


def parse_journal(since: str) -> list[dict]:
    raw = subprocess.run(
        ["journalctl", "--user", "-u", "mr-scrooge-v5",
         "--since", since, "--no-pager", "-o", "short-iso"],
        env={**os.environ,
             "XDG_RUNTIME_DIR": f"/run/user/{os.getuid()}",
             "SYSTEMD_PAGER": ""},
        capture_output=True, text=True,
    ).stdout
    cur_ts = None
    stamps = []
    for line in raw.splitlines():
        tm = TS_RX.match(line)
        if tm:
            try:
                cur_ts = datetime.fromisoformat(tm.group(1))
            except ValueError:
                cur_ts = None
        m = RX.search(line)
        if m and cur_ts:
            cell, side, n_met, n_total, sl, trig, trail, exp_ev, log_status, ts_field = m.groups()
            pair = cell.split("/")[0]
            stamps.append({
                "cell":       cell,
                "pair":       pair,
                "side":       side,
                "n_met":      int(n_met),
                "n_total":    int(n_total),
                "sl":         float(sl),
                "trig":       float(trig),
                "trail":      float(trail),
                "exp_ev":     float(exp_ev),
                "log_status": log_status or "UNKNOWN",
                "ts":         cur_ts,
            })
    return stamps


def fetch_m5_series(pair: str, start: datetime, end: datetime):
    times, highs, lows, closes = [], [], [], []
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
                highs.append(float(c["mid"]["h"]))
                lows.append(float(c["mid"]["l"]))
                closes.append(float(c["mid"]["c"]))
        cur = times[-1] + timedelta(seconds=1)
    return times, highs, lows, closes


def simulate_ratchet(pair: str, ts: datetime, side: str,
                     sl_p: float, trig_p: float, trail_p: float,
                     horizon_bars: int, series_cache: dict) -> float | None:
    """Simulate ratchet exit.  Returns net pips or None if data missing."""
    if pair not in series_cache:
        return None
    times, highs, lows, closes = series_cache[pair]
    pip = PIP.get(pair, 0.0001)
    sl_price   = sl_p    * pip
    trig_price = trig_p  * pip
    trail_price = trail_p * pip

    idx = bisect.bisect_left(times, ts)
    if idx >= len(times):
        return None
    entry = closes[idx]
    end_idx = min(idx + horizon_bars + 1, len(times))
    window_h = highs[idx:end_idx]
    window_l = lows[idx:end_idx]
    window_c = closes[idx:end_idx]
    if len(window_c) < 2:
        return None

    if side == "long":
        sl_level   = entry - sl_price
        trail_lock = None
        peak       = entry
        for h, l, c in zip(window_h[1:], window_l[1:], window_c[1:]):
            if l <= sl_level:
                return (sl_level - entry) / pip
            if h > peak:
                peak = h
            if peak - entry >= trig_price:
                ts2 = peak - trail_price
                if trail_lock is None or ts2 > trail_lock:
                    trail_lock = ts2
            if trail_lock is not None and l <= trail_lock:
                return (trail_lock - entry) / pip
        return (window_c[-1] - entry) / pip
    else:
        sl_level   = entry + sl_price
        trail_lock = None
        trough     = entry
        for h, l, c in zip(window_h[1:], window_l[1:], window_c[1:]):
            if h >= sl_level:
                return (entry - sl_level) / pip
            if l < trough:
                trough = l
            if entry - trough >= trig_price:
                ts2 = trough + trail_price
                if trail_lock is None or ts2 < trail_lock:
                    trail_lock = ts2
            if trail_lock is not None and h >= trail_lock:
                return (entry - trail_lock) / pip
        return (entry - window_c[-1]) / pip


def _print_table(label: str, rows: list[dict]):
    print(f"\n{'=' * 90}")
    print(f"FORMULA SHADOW SCORE — {label}")
    print(f"{'=' * 90}")
    hdr = (f"{'FORMULA':<28}  {'n':>4}  {'sim_ev':>8}  {'WR':>6}  "
           f"{'exp_ev':>8}  {'delta':>8}  geo(sl/trig/trail)")
    print(hdr)
    print("-" * 90)
    for r in sorted(rows, key=lambda x: x["cell"]):
        pips = r["sim_pips"]
        n = len(pips)
        if n == 0:
            continue
        sim_ev = sum(pips) / n
        wr = sum(1 for p in pips if p > 0) / n
        exp = r["exp_ev"]
        delta = sim_ev - exp
        geo = f"{r['sl']}/{r['trig']}/{r['trail']}"
        print(f"{r['cell']:<28}  {n:>4}  {sim_ev:>+8.2f}  {wr:>6.1%}  "
              f"{exp:>+8.2f}  {delta:>+8.2f}  {geo}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--since", default="7 days ago",
                    help="journalctl --since value (default: '7 days ago')")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    status_map = _build_status_map()

    print(f"Parsing journal since '{args.since}' ...", flush=True)
    stamps = parse_journal(args.since)
    print(f"  {len(stamps)} FORMULA stamps found", flush=True)

    if not stamps:
        print("No FORMULA stamps found yet — bot may not have emitted any, or "
              "formula_shadow_enabled=false.")
        return

    # Filter settled (use 240m settle for large SL formulas)
    settled = []
    for s in stamps:
        use_4h = s["sl"] >= 15.0 and s["trig"] >= 8.0
        settle_needed = SETTLE_S_4H if use_4h else SETTLE_S
        if s["ts"] <= now - timedelta(seconds=settle_needed):
            settled.append(s)
    print(f"  {len(settled)} settled", flush=True)

    if not settled:
        print("Nothing to score yet — wait for horizon to elapse.")
        return

    pairs_needed = sorted({s["pair"] for s in settled})
    t_min = min(s["ts"] for s in settled)
    t_max = max(s["ts"] for s in settled) + timedelta(hours=5)

    print(f"Fetching M5 series for {pairs_needed} ...", flush=True)
    series_cache: dict = {}
    for pair in pairs_needed:
        t, h, l, c = fetch_m5_series(pair, t_min, t_max)
        series_cache[pair] = (t, h, l, c)
        print(f"  {pair}: {len(t)} M5 bars", flush=True)

    per_formula: dict[str, dict] = defaultdict(lambda: {
        "sim_pips": [], "exp_ev": None, "sl": None, "trig": None, "trail": None,
        "status": "UNKNOWN",
    })
    skipped = 0
    for s in settled:
        use_4h = s["sl"] >= 15.0 and s["trig"] >= 8.0
        horizon_bars = 48 if use_4h else 12
        result = simulate_ratchet(
            s["pair"], s["ts"], s["side"],
            s["sl"], s["trig"], s["trail"],
            horizon_bars, series_cache,
        )
        if result is None:
            skipped += 1
            continue
        spread_cost = SPREAD_PIPS.get(s["pair"], 1.0)
        net = result - spread_cost
        key = s["cell"]
        per_formula[key]["sim_pips"].append(net)
        per_formula[key]["exp_ev"]  = s["exp_ev"]
        per_formula[key]["sl"]      = s["sl"]
        per_formula[key]["trig"]    = s["trig"]
        per_formula[key]["trail"]   = s["trail"]
        per_formula[key]["status"]  = s.get("log_status") or status_map.get(key, "UNKNOWN")

    print(f"  {skipped} stamps skipped (OANDA series gap)\n")

    primary_rows = [{"cell": k, **v} for k, v in per_formula.items()
                    if v["status"] == "PRIMARY"]
    control_rows = [{"cell": k, **v} for k, v in per_formula.items()
                    if v["status"] in ("CONTROL", "UNKNOWN")]

    if primary_rows:
        _print_table("PRIMARY (deep-OOS validated — expect positive)", primary_rows)
    else:
        print("\nNo PRIMARY formula stamps settled yet.")

    if control_rows:
        _print_table("CONTROL (2026-pocket artifacts — expect negative, falsification data)", control_rows)
    else:
        print("\nNo CONTROL formula stamps settled yet.")

    print("=" * 90)
    print("Done.")


if __name__ == "__main__":
    main()
