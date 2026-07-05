#!/usr/bin/env python3
"""research/tools/cell_setup_score.py — Scorer for CELLSHADOW stamps (Phase C).

Greps CELLSHADOW lines from the systemd journal, then for each qualifying bar
simulates the setup's OWN exit geometry (sl / trigger / trail from the CELLSHADOW
conds snapshot if present, else from the cell config) over the setup's horizon_min
forward window using OANDA M5 candles.

Reports per setup_id:
  n_stamps   — qualifying bars seen in the journal
  sim_ev     — simulated EV/trade net of spread (adverse-first walk)
  win_rate   — fraction of sims that exit in profit
  exp_ev     — config's evidence.ev_seq (expected EV)
  delta      — sim_ev - exp_ev
  status     — ACTIVE-would-trade vs SHADOW (reported separately)

Ratchet simulation (adverse-first, matching formula_shadow_score.py pattern)
-----------------------------------------------------------------------------
  Entry at open of the bar FOLLOWING the qualifying M5 bar.
  For each M5 bar in [entry, entry + horizon_min]:
    - check SL first (low for long, high for short) — stop hit → exit at SL
    - update peak; if peak >= trigger, trail SL from peak
  If horizon reached without stop: exit at close of last bar.
  Net pips = exit_pips - spread_pips (half-spread on entry + half on exit).

Line format emitted by engine (core/engine.py _cycle via CellModule.evaluate):
  CELLSHADOW {pair}/{session} setup={id} side={side} conds={...} exp_ev={x} status={S}

Usage:
  cell_setup_score.py [--since YYYY-MM-DD] [--setup SETUP_ID]

Run on EC2 (has OANDA token + journalctl).
"""
import argparse
import bisect
import json
import math
import os
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

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

# ── Secrets ───────────────────────────────────────────────────────────────────
for ln in open(os.path.expanduser("~/.openclaw/secrets.env")):
    if "=" in ln and not ln.strip().startswith("#"):
        k, v = ln.strip().split("=", 1)
        os.environ[k.strip()] = v.strip().strip('"').strip("'")
TOKEN = os.environ["OANDA_API_TOKEN"]
BASE  = os.environ.get("OANDA_API_URL", "https://api-fxtrade.oanda.com")
ACCT  = os.environ["OANDA_ACCOUNT_ID"]

# ── CELLSHADOW regex ──────────────────────────────────────────────────────────
# CELLSHADOW GBP_USD/london setup=rvol_low_240 side=long conds={...} exp_ev=+0.350 status=ACTIVE
RX = re.compile(
    r"CELLSHADOW (\w+)/(\w+) setup=(\S+) side=(\w+) conds=(\{.*?\}) exp_ev=([+-]?[\d.]+) status=(\w+)"
)
TS_RX = re.compile(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})")


# ── OANDA candle fetch ────────────────────────────────────────────────────────
import urllib.request, urllib.parse

def _fetch_candles(pair: str, from_dt: datetime, to_dt: datetime, granularity: str = "M5") -> list:
    """Return list of {time, mid:{o,h,l,c}} dicts."""
    import urllib.error
    oanda_pair = pair  # already in OANDA format (underscore)
    from_s = from_dt.strftime("%Y-%m-%dT%H:%M:%S.000000000Z")
    to_s   = to_dt.strftime("%Y-%m-%dT%H:%M:%S.000000000Z")
    url = (f"{BASE}/v3/instruments/{oanda_pair}/candles"
           f"?granularity={granularity}&price=M"
           f"&from={urllib.parse.quote(from_s)}&to={urllib.parse.quote(to_s)}&count=500")
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {TOKEN}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read())
        return data.get("candles", [])
    except urllib.error.HTTPError as exc:
        print(f"  WARN candles {pair} {from_s[:16]}: HTTP {exc.code}", file=sys.stderr)
        return []
    except Exception as exc:
        print(f"  WARN candles {pair}: {exc}", file=sys.stderr)
        return []


def _candle_index(candles: list) -> dict:
    """ISO timestamp → candle dict."""
    return {c["time"][:16]: c for c in candles if c.get("complete", True)}


def _simulate_ratchet(
    pair: str, entry_time: datetime, side: str,
    sl_pips: float, trigger_pips: float, trail_pips: float,
    horizon_min: int,
) -> float:
    """Adverse-first ratchet simulation.  Returns net pips (signed, net of spread)."""
    pip = PIP[pair]
    spread = SPREAD_PIPS.get(pair, 1.0)

    to_dt   = entry_time + timedelta(minutes=horizon_min + 10)
    candles = _fetch_candles(pair, entry_time, to_dt)
    if not candles:
        return float("nan")

    # Find entry candle (first bar >= entry_time)
    bars = [c for c in candles if c.get("complete", True)]
    if not bars:
        return float("nan")

    # Entry price = open of first bar at or after entry_time
    entry_c  = bars[0]
    entry_px = float(entry_c["mid"]["o"])

    # Apply entry spread (half-spread against direction)
    if side == "long":
        entry_px += spread * pip / 2.0
    else:
        entry_px -= spread * pip / 2.0

    sl_price    = (entry_px - sl_pips * pip if side == "long"
                   else entry_px + sl_pips * pip)
    peak_price  = entry_px
    trail_sl    = None
    exit_px     = None

    deadline = entry_time + timedelta(minutes=horizon_min)

    for bar in bars:
        bar_time = datetime.fromisoformat(bar["time"].replace("Z", "+00:00"))
        if bar_time >= deadline:
            exit_px = float(bar["mid"]["c"])
            break

        lo = float(bar["mid"]["l"])
        hi = float(bar["mid"]["h"])
        cl = float(bar["mid"]["c"])

        # ── Adverse first ────────────────────────────────────────────────
        if side == "long":
            if lo <= sl_price:
                exit_px = sl_price
                break
        else:
            if hi >= sl_price:
                exit_px = sl_price
                break

        # ── Update peak ──────────────────────────────────────────────────
        if side == "long":
            if hi > peak_price:
                peak_price = hi
        else:
            if lo < peak_price:
                peak_price = lo

        # ── Trail SL ────────────────────────────────────────────────────
        if side == "long":
            mfe_pips = (peak_price - entry_px) / pip
        else:
            mfe_pips = (entry_px - peak_price) / pip

        if mfe_pips >= trigger_pips:
            new_trail = (peak_price - trail_pips * pip if side == "long"
                         else peak_price + trail_pips * pip)
            if trail_sl is None or (side == "long" and new_trail > trail_sl) or \
               (side == "short" and new_trail < trail_sl):
                trail_sl = new_trail

        if trail_sl is not None:
            if side == "long" and lo <= trail_sl:
                exit_px = trail_sl
                break
            if side == "short" and hi >= trail_sl:
                exit_px = trail_sl
                break

    if exit_px is None:
        # Horizon reached without stop
        exit_px = float(bars[-1]["mid"]["c"])

    # Exit spread (half-spread against direction)
    if side == "long":
        exit_px -= spread * pip / 2.0
    else:
        exit_px += spread * pip / 2.0

    if side == "long":
        return round((exit_px - entry_px) / pip, 2)
    else:
        return round((entry_px - exit_px) / pip, 2)


# ── Journal grep ─────────────────────────────────────────────────────────────
def _grep_journal(since: str) -> list[str]:
    """Return CELLSHADOW lines from journalctl.

    The bot runs as the USER unit mr-scrooge-v5 (see ops/server.py _sysinfo);
    the old system-unit name scrooge.service is kept as a fallback only."""
    cmds = [
        ["journalctl", "--user", "-u", "mr-scrooge-v5", "--no-pager",
         "--output=short-iso", f"--since={since}"],
        ["journalctl", "-u", "scrooge.service", "--no-pager",
         "--output=short-iso", f"--since={since}"],
    ]
    for cmd in cmds:
        try:
            out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, text=True)
        except (subprocess.CalledProcessError, FileNotFoundError, OSError):
            continue
        lines = [ln for ln in out.splitlines() if "CELLSHADOW" in ln]
        if lines:
            return lines
    return []


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-07-04", help="YYYY-MM-DD")
    ap.add_argument("--setup", default=None, help="Filter to one setup_id")
    ap.add_argument("--horizon", type=int, default=None, help="Override horizon (min)")
    ap.add_argument("--json", action="store_true",
                    help="Emit machine-readable JSON on stdout (for ops/server.py /api/cellscore); "
                         "human chatter goes to stderr. Default CLI table output is unchanged.")
    args = ap.parse_args()

    lines = _grep_journal(args.since)
    print(f"Found {len(lines)} CELLSHADOW lines since {args.since}",
          file=sys.stderr if args.json else sys.stdout)

    # Parse stamps
    # Group by (pair, session, setup_id, status)
    stamps: dict[tuple, list] = defaultdict(list)
    for ln in lines:
        m  = RX.search(ln)
        tm = TS_RX.search(ln)
        if not m or not tm:
            continue
        pair, sess, setup_id, side, conds_s, exp_ev_s, status = m.groups()
        if args.setup and setup_id != args.setup:
            continue
        key = (pair, sess, setup_id, side, status)
        try:
            ts = datetime.fromisoformat(tm.group(1)).replace(tzinfo=timezone.utc)
        except Exception:
            continue
        stamps[key].append((ts, float(exp_ev_s)))

    if not stamps:
        if args.json:
            print(json.dumps({"setups": [], "since": args.since,
                              "n_lines": len(lines),
                              "note": "no matching CELLSHADOW stamps found"}))
        else:
            print("No matching CELLSHADOW stamps found.")
        return

    # Load cell configs to get exit geometry and horizon
    configs: dict[str, dict] = {}
    cells_dir = REPO / "config" / "cells"

    def _get_setup_cfg(pair: str, sess: str, setup_id: str) -> dict:
        if pair not in configs:
            cfg_path = cells_dir / f"{pair}.json"
            try:
                configs[pair] = json.loads(cfg_path.read_text())
            except Exception:
                configs[pair] = {}
        pair_cfg = configs[pair]
        sess_cfg = pair_cfg.get("sessions", {}).get(sess, {})
        for s in sess_cfg.get("setups", []):
            if s.get("id") == setup_id:
                return s
        return {}

    if not args.json:
        print(f"\n{'Setup':<40} {'N':>5} {'SimEV':>8} {'WR%':>6} {'ExpEV':>8} {'Delta':>8} Status")
        print("-" * 90)

    json_rows = []
    for (pair, sess, setup_id, side, status), stamp_list in sorted(stamps.items()):
        n = len(stamp_list)
        exp_ev = stamp_list[0][1] if stamp_list else 0.0

        setup_cfg  = _get_setup_cfg(pair, sess, setup_id)
        exit_cfg   = setup_cfg.get("exit", {})
        sl_pips    = float(exit_cfg.get("sl_pips",      12.0))
        trig_pips  = float(exit_cfg.get("trigger_pips", 10.0))
        trail_pips = float(exit_cfg.get("trail_pips",   1.5))
        horizon    = args.horizon or int(setup_cfg.get("horizon_min", 60))

        evs = []
        wins = 0
        for ts, _ in stamp_list[:50]:  # cap at 50 to avoid rate-limiting
            ev = _simulate_ratchet(pair, ts, side, sl_pips, trig_pips, trail_pips, horizon)
            if not math.isnan(ev):
                evs.append(ev)
                if ev > 0:
                    wins += 1

        if not evs:
            sim_ev = float("nan")
            wr_pct = float("nan")
        else:
            sim_ev = round(sum(evs) / len(evs), 3)
            wr_pct = round(100.0 * wins / len(evs), 1)

        delta = round(sim_ev - exp_ev, 3) if not math.isnan(sim_ev) else float("nan")
        label = f"{pair}/{sess}/{setup_id}"
        if args.json:
            _num = lambda x: None if (isinstance(x, float) and math.isnan(x)) else x
            json_rows.append({
                "setup_id": setup_id,
                "pair":     pair,
                "session":  sess,
                "cell":     f"{pair}/{sess}",
                "side":     side,
                "n_stamps": n,
                "sim_ev":   _num(sim_ev),
                "win_rate": _num(wr_pct),
                "exp_ev":   exp_ev,
                "delta":    _num(delta),
                "status":   status,
            })
        else:
            print(f"{label:<40} {n:>5} {sim_ev:>8.3f} {wr_pct:>6.1f} {exp_ev:>8.3f} {delta:>8.3f} {status}")

    if args.json:
        print(json.dumps({"setups": json_rows, "since": args.since,
                          "n_lines": len(lines)}))


if __name__ == "__main__":
    main()
