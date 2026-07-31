#!/usr/bin/env python3
"""research/tools/family_sim_grade.py — grade cells by what the BOT actually does.

Every standard metric (WR, parent sim EV, hit rates) grades the PARENT trade;
this bot's economic unit is the FAMILY: parent + the popper grid that fires
into adverse excursion and harvests the recovery. The parent-only era metric
had the SIGN wrong on control_rvol_60_t20s (sim −38.5p vs broker family
+85.8p, 6/0) because deep-but-recovering MAE is fuel here, not damage.

For each era episode this tool replays the WHOLE family machine over M5 mids:
  - parent: entry at next bar open, its own config gear (sl/trigger/trail)
  - poppers: fire when the adverse excursion crosses each pp marker
    (10/15/20/30/40/60p from parent entry), each with pp gear (SL 60 own-fill,
    ratchet 8.5 → lock 6 → trail 2.5)
  - adverse-first bar walk for every open unit; spread charged per unit
  - horizon: 24h (families outlive the 4h parent window — the rescued GBP
    grid ran 44h; 24h is a compromise, flagged)

v1 simplifications (all conservative): one fire per marker (no re-arm on
re-cross), popper entry exactly at marker price, no FIFO blocking.

Grade per cell (era window, episode-collapsed):
  fam_ev      — mean family net pips per episode
  fam_exp_r   — expectancy ratio: fam_ev / |avg losing episode| (the
                scoreboard doctrine number; >0 profitable, sign-stable)
  death%      — episodes where the PARENT ate its full stop
  harvest     — mean popper contribution (pips) per episode

Usage: family_sim_grade.py [--since ISO] [--setups pair/sess/id,...] [--limit N]
Run on EC2 (OANDA token + shadowboard.json). Read-only; touches nothing live.
"""
import argparse, json, math, os, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
# reuse candle fetch + secrets + episode collapse from the scorer module
import research.tools.cell_setup_score as css

PIP = lambda pair: 0.01 if "JPY" in pair else 0.0001
SPREAD = {"USD_JPY": 0.8, "EUR_USD": 0.6, "GBP_USD": 0.8, "AUD_USD": 0.7,
          "EUR_JPY": 1.0, "AUD_JPY": 1.0, "USD_CAD": 0.9, "USD_CHF": 0.8}

def _pp_cfg():
    try:
        d = json.load(open(REPO / "config" / "pp_config.json"))
        return (sorted(float(m) for m in d.get("marker_pips", [10, 15, 20, 30, 40, 60])),
                float(d.get("sl_pips", 60.0)), float(d.get("trigger_pips", 8.5)),
                float(d.get("trail_pips", 2.5)))
    except OSError:
        return [10.0, 15.0, 20.0, 30.0, 40.0, 60.0], 60.0, 8.5, 2.5

def _setup_exit(pair, sess, sid):
    try:
        d = json.load(open(REPO / "config" / "cells" / f"{pair}.json"))
        for su in d["sessions"][sess]["setups"]:
            if su.get("id") == sid:
                ex = su.get("exit") or {}
                return (float(ex.get("sl_pips", 60)), float(ex.get("trigger_pips", 8.5)),
                        float(ex.get("trail_pips", 2.5)))
    except (OSError, KeyError):
        pass
    return 60.0, 8.5, 2.5

class Unit:
    __slots__ = ("entry", "sl_px", "trig", "trail", "peak", "locked", "done", "net")
    def __init__(self, entry, sl_pips, trig, trail, sgn, pip):
        self.entry = entry
        self.sl_px = entry - sgn * sl_pips * pip
        self.trig, self.trail = trig, trail
        self.peak = 0.0; self.locked = False; self.done = False; self.net = 0.0

def family_walk(candles, side, pair, parent_gear, markers, pp_sl, pp_trig, pp_trail):
    """Replay one episode's path through parent + popper grid. Adverse-first."""
    pip = PIP(pair); sgn = 1 if side == "long" else -1
    spread = SPREAD.get(pair, 1.0)
    o0 = float(candles[0]["mid"]["o"])
    parent = Unit(o0, parent_gear[0], parent_gear[1], parent_gear[2], sgn, pip)
    units = [parent]; fired = set()
    deaths_parent = False
    for c in candles:
        m = c["mid"]
        hi, lo = float(m["h"]), float(m["l"])
        adverse = lo if sgn > 0 else hi          # worst price for our side
        favor   = hi if sgn > 0 else lo
        adv_pips_from_parent = sgn * (o0 - adverse) / pip
        # 1) fire poppers whose marker the adverse excursion crossed this bar
        for mk in markers:
            if mk not in fired and adv_pips_from_parent >= mk:
                fired.add(mk)
                units.append(Unit(o0 - sgn * mk * pip, pp_sl, pp_trig, pp_trail, sgn, pip))
        # 2) walk every open unit, adverse first
        for u in units:
            if u.done: continue
            hit_sl = (adverse <= u.sl_px) if sgn > 0 else (adverse >= u.sl_px)
            if hit_sl:
                u.net = sgn * (u.sl_px - u.entry) / pip - spread
                u.done = True
                if u is parent and not u.locked: deaths_parent = True
                continue
            fav_pips = sgn * (favor - u.entry) / pip
            if fav_pips > u.peak:
                u.peak = fav_pips
                if u.peak >= u.trig:
                    u.locked = True
                    lock_px = u.entry + sgn * max(6.0, u.peak - u.trail) * pip
                    if (sgn > 0 and lock_px > u.sl_px) or (sgn < 0 and lock_px < u.sl_px):
                        u.sl_px = lock_px
    last = float(candles[-1]["mid"]["c"])
    for u in units:
        if not u.done:
            u.net = sgn * (last - u.entry) / pip - spread
    fam = sum(u.net for u in units)
    harvest = sum(u.net for u in units if u is not parent)
    return fam, parent.net, harvest, len(units) - 1, deaths_parent

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-07-28T00:00:00")
    ap.add_argument("--setups", default="", help="pair/sess/id,... (default: every ACTIVE)")
    ap.add_argument("--limit", type=int, default=20, help="max episodes simmed per cell")
    ap.add_argument("--horizon-h", type=int, default=24)
    args = ap.parse_args()
    since = datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc)

    db = json.load(open(REPO / "data" / "shadowboard.json"))
    targets = set()
    if args.setups:
        targets = {tuple(s.split("/")) for s in args.setups.split(",")}
    from research.tools.cell_setup_score import collapse_episodes
    eps_by = {}
    for e in db["episodes"].values():
        t = datetime.fromisoformat(e["t"])
        if t < since: continue
        pair, _, sess = e["cell"].partition("/")
        key = (pair, sess, e["setup"], e["side"])
        if targets and (pair, sess, e["setup"]) not in targets: continue
        eps_by.setdefault(key, []).append(t)

    markers, pp_sl, pp_trig, pp_trail = _pp_cfg()
    print(f"FAMILY-SIM GRADE — era since {args.since}, horizon {args.horizon_h}h, "
          f"markers {markers}")
    print(f"{'cell':15s} {'setup':26s} {'n':>3s} {'famEV':>7s} {'expR':>6s} "
          f"{'death%':>6s} {'harvest':>7s} {'parEV':>7s}")
    rows_out = []
    for (pair, sess, sid, side), ts_list in sorted(eps_by.items()):
        ts_list.sort()
        firsts = collapse_episodes(ts_list)[-args.limit:]
        gear = _setup_exit(pair, sess, sid)
        fams, harvs, pars, deaths = [], [], [], 0
        now_utc = datetime.now(timezone.utc)
        for t in firsts:
            try:
                _to = min(t + timedelta(hours=args.horizon_h), now_utc)
                candles = css._fetch_candles(pair, t, _to)
            except Exception:
                continue
            if len(candles) < 3: continue
            f, p, h, npop, died = family_walk(candles, side, pair, gear,
                                              markers, pp_sl, pp_trig, pp_trail)
            fams.append(f); harvs.append(h); pars.append(p); deaths += died
        if not fams: continue
        fam_ev = sum(fams) / len(fams)
        losses = [f for f in fams if f < 0]
        avg_loss = abs(sum(losses) / len(losses)) if losses else 0.0
        exp_r = fam_ev / avg_loss if avg_loss else float("inf")
        row = {"cell": f"{pair}/{sess}", "setup": sid, "n": len(fams),
               "fam_ev": round(fam_ev, 1),
               "exp_r": round(exp_r, 2) if math.isfinite(exp_r) else None,
               "death_pct": round(100 * deaths / len(fams)),
               "harvest": round(sum(harvs) / len(harvs), 1),
               "parent_ev": round(sum(pars) / len(pars), 1)}
        rows_out.append(row)
        er = "∞" if row["exp_r"] is None else f"{row['exp_r']:.2f}"
        print(f"{row['cell']:15s} {sid[:26]:26s} {row['n']:3d} {row['fam_ev']:7.1f} "
              f"{er:>6s} {row['death_pct']:5d}% {row['harvest']:7.1f} {row['parent_ev']:7.1f}")
    return rows_out

if __name__ == "__main__":
    main()
