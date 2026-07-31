#!/usr/bin/env python3
"""research/tools/family_cycle_replay.py — family-cycle-v3 virtual scoring.

Feeds real era episodes (shadowboard stamp DB, episode-collapsed) through
core/family_cycle.py under BOTH management policies and reports per cell:

  cycles     completed virtual family cycles (censored excluded, counted)
  U_pp       mean risk-normalized return, FAMILY_PP:  net / peak liability
  U_par      same, PARENT_ONLY
  GridLift   U_pp − U_par  (the management-policy selector's input)
  cov        smoothed harvest coverage (Σ+R + 0.5) / (Σ|−R| + 0.5)
  worst      worst completed cycle (R units)

This is the cheater-v3 ticket's evidence source and Geometry v3's engine.

SAMPLING CAVEAT (charter defect #6, observed live 2026-07-31): virtual
cycles replay from SHADOW STAMP times — every episode the setup fired on
paper. The live engine executes only the first qualifying ACTIVE setup per
pair, so an ACTIVE cell's real fills are a SELECTED SUBSET of its stamps
(control_rvol_60_t20s: 6 virtual cycles net −101p vs its ONE selected live
cycle +85.8p). For SHADOW cells this all-episodes view is the right cheater
evidence; for ACTIVE cells, judge the live seat by BROKER cycles and read
this table as entry-signal quality across all firings. Closing the gap
needs the selector model (ExecutionScore program item).
Candles: M5 bid/ask, fetched forward in 5000-minute chunks until the cycle
resolves or grid_max_age caps it. Run on EC2. Read-only.
"""
import argparse, json, math, os, sys, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from core.family_cycle import replay_family_cycle
import research.tools.cell_setup_score as css
from research.tools.cell_setup_score import collapse_episodes

PIP = lambda pair: 0.01 if "JPY" in pair else 0.0001


def _ba_candles(pair, t0, t1):
    """M5 bid/ask candles t0..t1 (chunked; OANDA caps 5000/request)."""
    out, cur = [], t0
    while cur < t1:
        nxt = min(cur + timedelta(minutes=5 * 4900), t1)
        url = (f"{css.BASE}/v3/instruments/{pair}/candles?granularity=M5"
               f"&from={cur.strftime('%Y-%m-%dT%H:%M:%SZ')}"
               f"&to={nxt.strftime('%Y-%m-%dT%H:%M:%SZ')}&price=BA")
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {css.TOKEN}"})
        try:
            cs = json.loads(urllib.request.urlopen(req, timeout=30).read()).get("candles", [])
        except Exception as e:
            print(f"  WARN candles {pair} {cur:%m-%dT%H:%M}: {e}", file=sys.stderr)
            break
        out += [c for c in cs if c.get("complete", True)]
        cur = nxt
    return out


def _setup_exit(pair, sess, sid):
    try:
        d = json.load(open(REPO / "config" / "cells" / f"{pair}.json"))
        for su in d["sessions"][sess]["setups"]:
            if su.get("id") == sid:
                ex = dict(su.get("exit") or {})
                ex.setdefault("step_size_pips", 2.0)
                ex.setdefault("step_cadence_min", 0.5)
                return ex
    except (OSError, KeyError):
        pass
    return {"sl_pips": 60.0, "trigger_pips": 8.5, "trail_pips": 2.5,
            "step_size_pips": 2.0, "step_cadence_min": 0.5}


def _pp():
    try:
        d = json.load(open(REPO / "config" / "pp_config.json"))
    except OSError:
        d = {}
    return {"marker_pips": d.get("marker_pips", [10, 15, 20, 30, 40, 60]),
            "sl_pips": d.get("sl_pips", 60.0),
            "trigger_pips": d.get("trigger_pips", 8.5),
            "trail_pips": d.get("trail_pips", 2.5),
            "step_size_pips": 2.0,
            "grid_max_age_days": d.get("grid_max_age_days", 7.0)}


def score_cell(pair, sess, sid, side, ep_times, max_days, limit):
    gear, pp = _setup_exit(pair, sess, sid), _pp()
    rows = []
    now = datetime.now(timezone.utc)
    for t in ep_times[-limit:]:
        t1 = min(t + timedelta(days=max_days), now)
        bars = _ba_candles(pair, t, t1)
        if len(bars) < 3:
            continue
        fam = replay_family_cycle(bars, side, PIP(pair), gear, pp, "FAMILY_PP")
        par = replay_family_cycle(bars, side, PIP(pair), gear, pp, "PARENT_ONLY")
        if fam is None or par is None:
            continue
        rows.append((fam, par))
    comp = [(f, p) for f, p in rows if not f.censored]
    cens = len(rows) - len(comp)
    if not comp:
        return {"cycles": 0, "censored": cens}
    def U(c):
        liab = max(c.peak_liability_pips, 1.0)
        return c.net_pips / liab
    u_pp = [U(f) for f, _ in comp]
    u_par = [U(p) for _, p in comp if not p.censored]
    pos = sum(u for u in u_pp if u > 0)
    neg = sum(-u for u in u_pp if u < 0)
    return {"cycles": len(comp), "censored": cens,
            "U_pp": round(sum(u_pp) / len(u_pp), 3),
            "U_par": round(sum(u_par) / len(u_par), 3) if u_par else None,
            "grid_lift": (round(sum(u_pp) / len(u_pp) - sum(u_par) / len(u_par), 3)
                          if u_par else None),
            "coverage": round((pos + 0.5) / (neg + 0.5), 2),
            "worst": round(min(u_pp), 3),
            "net_pips_mean": round(sum(f.net_pips for f, _ in comp) / len(comp), 1),
            "harvest_mean": round(sum(f.harvest for f, _ in comp) / len(comp), 1)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-07-28T00:00:00")
    ap.add_argument("--setups", default="", help="pair/sess/id,... (default: ACTIVE+SHADOW with era episodes)")
    ap.add_argument("--limit", type=int, default=12, help="max cycles per cell")
    ap.add_argument("--max-days", type=float, default=3.0, help="candle window per cycle")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    since = datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc)

    db = json.load(open(REPO / "data" / "shadowboard.json"))
    eps = {}
    targets = ({tuple(s.split("/")) for s in args.setups.split(",")}
               if args.setups else None)
    for e in db["episodes"].values():
        t = datetime.fromisoformat(e["t"])
        if t < since:
            continue
        pair, _, sess = e["cell"].partition("/")
        if targets and (pair, sess, e["setup"]) not in targets:
            continue
        eps.setdefault((pair, sess, e["setup"], e["side"]), []).append(t)

    out = []
    print(f"FAMILY-CYCLE-v3 replay — era since {args.since}, "
          f"window {args.max_days}d/cycle, live gear + full grid mechanics")
    print(f"{'cell':15s} {'setup':26s} {'cyc':>3s} {'cen':>3s} {'U_pp':>6s} "
          f"{'U_par':>6s} {'lift':>6s} {'cov':>5s} {'worst':>6s} {'net':>7s} {'harv':>6s}")
    for (pair, sess, sid, side), ts in sorted(eps.items()):
        ts.sort()
        firsts = collapse_episodes(ts)
        r = score_cell(pair, sess, sid, side, firsts, args.max_days, args.limit)
        r.update(cell=f"{pair}/{sess}", setup=sid, side=side)
        out.append(r)
        if r["cycles"]:
            print(f"{r['cell']:15s} {sid[:26]:26s} {r['cycles']:3d} {r['censored']:3d} "
                  f"{r['U_pp']:6.2f} "
                  f"{r['U_par'] if r['U_par'] is not None else float('nan'):6.2f} "
                  f"{r['grid_lift'] if r['grid_lift'] is not None else float('nan'):6.2f} "
                  f"{r['coverage']:5.2f} {r['worst']:6.2f} "
                  f"{r['net_pips_mean']:7.1f} {r['harvest_mean']:6.1f}")
    if args.json:
        print(json.dumps({"since": args.since, "rows": out}))


if __name__ == "__main__":
    main()
