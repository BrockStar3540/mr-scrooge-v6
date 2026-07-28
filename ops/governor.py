#!/usr/bin/env python3
"""ops/governor.py — the Bar Governor: autonomous promote/demote by evidence.

The trial system's closing loop (Brock, 2026-07-27): the bot flips its own
switches. Shadows that clear the activation bar on CURRENT-ERA evidence go
ACTIVE; actives that lose the bar — or go net-negative on broker fills — go
back to SHADOW, where stamping costs nothing and a seat can be re-earned.

THE STANDARD (all evidence is current-era, config-side only):
  PROMOTE  SHADOW -> ACTIVE   when  n >= 20  AND  avg net240 >= +2.0 p/ep
                              AND  LCB(95%) > 0
                              AND  (last-7d avg >= 0 when it has >= 5 episodes)
  DEMOTE   ACTIVE -> SHADOW   when  n >= 20  AND  avg net240 < +2.0   (bar lost)
                              OR   era broker fills n >= 5 with avg pips < 0

RAILS: max 2 promotions + 4 demotions per run · DISABLED and "manual_only"
setups never touched · sides never flipped · flips go through the dashboard's
own /api/cell/status writer (validated, hot-reloaded, journaled) · every
decision appended to data/governor_ledger.jsonl · the era clock per setup is
owned by data/governor_state.json — any flip (or first sight) restarts the
evidence window, so a config-era change can never trade on stale proof.

Cron (EC2): 35 6 * * *  — after the nightly scorers. Manual: --dry-run first.
"""
from __future__ import annotations
import argparse, json, math, statistics, subprocess, sys, urllib.request
from datetime import datetime, timezone
from pathlib import Path

import hashlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.trial_stats import cost_adjusted_nets, effective_n, lcb as _lcb

REPO = Path(__file__).resolve().parents[1]
STORE = REPO / "data" / "shadowboard.json"
STATE_F = REPO / "data" / "governor_state.json"
LEDGER = REPO / "data" / "governor_ledger.jsonl"
REGISTRY = REPO / "data" / "hypothesis_registry.json"
CELLS = REPO / "config" / "cells"
CFG_F = REPO / "config" / "governor_config.json"
API = "http://127.0.0.1:8084/api/cell/status"

DEFAULT_CFG = {
    "enabled": True,
    # Promotions ON by operator ruling (Brock, 2026-07-28), overriding the
    # review's interim gate: the bar is already strict (net-of-cost, n>=20,
    # per_test_z=2.33 LCB on overlap-adjusted n_eff, 7d guard, 2/day rail),
    # and the autonomy loop is the project's thesis. D-7 (block bootstrap,
    # BH-FDR, shared evidence engine, exit simulation) upgrades the math
    # when it ships; the switch remains one edit away.
    "allow_promotions": True,
    "allow_demotions": True,
    "bar_n": 20, "bar_avg": 2.0, "lcb_min": 0.0,
    "recent_n": 5, "recent_min": 0.0,
    "fills_n": 5, "fills_avg_max": 0.0,
    "max_promotions": 2, "max_demotions": 4,
    # per_test_z: a PER-TEST 99% one-sided bound. It is NOT a multiple-testing
    # correction and NOT the Deflated Sharpe Ratio (we mislabeled it for a
    # day; review round 2 called it out). Real FDR control lands with D-7.
    "per_test_z": 2.33,
    "slippage_pips": 0.5,
    "default_era_start": "2026-07-19T00:00:00+00:00",
}


def cfg():
    """FAIL-CLOSED (2026-07-27): a corrupted governor config must not run the
    governor on defaults — a missing file uses defaults (never configured),
    but an unreadable/malformed one disables the run until a human looks."""
    c = dict(DEFAULT_CFG)
    try:
        c.update(json.loads(CFG_F.read_text()))
    except FileNotFoundError:
        pass
    except Exception as exc:
        print(f"governor: config unreadable ({exc}) — FAILING CLOSED (disabled)",
              file=sys.stderr)
        c["enabled"] = False
    return c


def load_state():
    try:
        return json.loads(STATE_F.read_text())
    except Exception:
        return {}


def save_state(st):
    STATE_F.write_text(json.dumps(st, indent=1))


def book():
    """(pair, session, setup_id) -> {status, side, manual_only}."""
    out = {}
    for f in CELLS.glob("*.json"):
        try:
            d = json.loads(f.read_text())
        except Exception:
            continue
        for sess, b in (d.get("sessions") or {}).items():
            for su in (b.get("setups") or []):
                # Era identity = the setup's MECHANICS (conditions/exit/side/
                # sizing), not its prose — notes and evidence edits must not
                # reset anyone's clock.
                core = {k: su.get(k) for k in
                        ("side", "conditions", "exit", "sizing", "horizon_min")}
                h = hashlib.sha256(json.dumps(core, sort_keys=True,
                                              default=str).encode()).hexdigest()[:16]
                out[(d.get("pair") or f.stem, sess, su.get("id"))] = {
                    "status": su.get("status", "?"), "side": su.get("side"),
                    "manual_only": bool(su.get("manual_only", False)),
                    "cfg_hash": h,
                }
    return out


def era_stats(era_start_by_key, default_era, book_map, gov_cfg):
    """Aggregate scored episodes per (pair, sess, setup) — CONFIG side only,
    episodes at/after that setup's era start."""
    try:
        eps = json.loads(STORE.read_text())["episodes"]
    except Exception:
        return {}
    try:
        aliases = {(r["cell"], r["setup"], r["side"]): r["as"]
                   for r in json.loads((REPO / "config" / "setup_aliases.json").read_text())}
    except Exception:
        aliases = {}
    now = datetime.now(timezone.utc).isoformat()
    agg = {}
    for ep in eps.values():
        if not ep.get("scores"):
            continue
        pair, sess = (ep["cell"].split("/") + ["?"])[:2]
        sid = aliases.get((ep["cell"], ep["setup"], ep["side"]), ep["setup"])
        key = (pair, sess, sid)
        meta = book_map.get(key)
        if meta is None or ep.get("side") != meta["side"]:
            continue
        era = era_start_by_key.get("|".join(key), default_era)
        if ep["t"] < era:
            continue
        agg.setdefault(key, []).append((ep["t"], ep["scores"]["net240"],
                                        ep.get("spread")))
    out = {}
    z = float(gov_cfg.get("per_test_z", gov_cfg.get("z_promote", 2.33)))
    slip = float(gov_cfg.get("slippage_pips", 0.5))
    cutoff7 = datetime.now(timezone.utc).timestamp() - 7 * 86400
    for key, rows in agg.items():
        pair = key[0]
        times = [t for t, _, _ in rows]
        gross = [n for _, n, _ in rows]
        spreads = [sp for _, _, sp in rows]
        # D-6: ONE cost-adjusted utility for every verdict — stamps pay the
        # stamped (or default) spread + slippage before being judged.
        nets = cost_adjusted_nets(gross, spreads, pair, slippage_pips=slip)
        n = len(nets)
        n_eff = effective_n(times)
        avg = sum(nets) / n
        lcb = _lcb(nets, n_eff, z)
        r7 = [net for (t, _, _), net in zip(rows, nets)
              if datetime.fromisoformat(t).timestamp() >= cutoff7]
        out[key] = {"n": n, "n_eff": n_eff, "avg": avg, "lcb": lcb,
                    "n7": len(r7), "avg7": (sum(r7) / len(r7)) if r7 else None}
    return out


def era_fills(default_era):
    """(pair, setup_id) -> {n, avg_pips} from broker fills since default era.
    (Fills carry setup id but not session; the rule convicts per pair+setup.)"""
    try:
        out = subprocess.run(
            [sys.executable, str(REPO / "research" / "tools" / "broker_setup_audit.py"),
             "--since", default_era.replace("+00:00", "Z"), "--json"],
            capture_output=True, text=True, timeout=180)
        rows = json.loads(out.stdout)["rows"]
    except Exception as exc:
        print(f"governor: fills audit unavailable ({exc}) — stamps-only run", file=sys.stderr)
        return {}
    return {(r["instrument"], r["setup"]): {"n": r["n"], "avg": r["avg_pips"]}
            for r in rows if r.get("tag") == "cell_v1"}


def flip(pair, sess, setup_id, status, dry):
    if dry:
        return {"ok": True, "dry_run": True}
    import os as _os
    headers = {"Content-Type": "application/json"}
    tok = _os.environ.get("DASHBOARD_TOKEN", "")
    if tok:
        headers["X-Scrooge-Token"] = tok
    req = urllib.request.Request(API, method="POST",
        data=json.dumps({"pair": pair, "session": sess,
                         "setup_id": setup_id, "status": status}).encode(),
        headers=headers)
    return json.loads(urllib.request.urlopen(req, timeout=15).read())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    c = cfg()
    if not c["enabled"]:
        print("governor disabled (config/governor_config.json)")
        return
    st = load_state()
    eras = st.setdefault("era_start", {})
    hashes = st.setdefault("cfg_hash", {})
    bmap = book()
    now_iso = datetime.now(timezone.utc).isoformat()

    # D-6: ANY change to a setup's mechanics restarts its evidence clock —
    # not just governor flips. Manual dashboard exit-tuning counts.
    resets = []
    for key, meta in bmap.items():
        k = "|".join(key)
        old_h = hashes.get(k)
        if old_h is not None and old_h != meta["cfg_hash"]:
            eras[k] = now_iso
            resets.append(k)
        hashes[k] = meta["cfg_hash"]
    if resets:
        with open(LEDGER, "a") as led:
            for k in resets:
                led.write(json.dumps({"t": now_iso, "action": "ERA-RESET",
                                      "key": k, "why": "setup mechanics changed",
                                      "dry_run": args.dry_run}) + "\n")
        print(f"governor: era clocks reset for {len(resets)} changed setup(s)")
    if not args.dry_run:
        save_state(st)

    # D-6: hypothesis registry — every (cell, setup) ever examined, so the
    # deflation denominator is explicit and public.
    try:
        reg = json.loads(REGISTRY.read_text())
    except Exception:
        reg = {}
    for key, meta in bmap.items():
        k = "|".join(key)
        e = reg.setdefault(k, {"first_seen": now_iso, "hashes": []})
        if meta["cfg_hash"] not in e["hashes"]:
            e["hashes"].append(meta["cfg_hash"])
    if not args.dry_run:
        REGISTRY.write_text(json.dumps(reg, indent=1))
    m_live = sum(1 for m in bmap.values() if m["status"] in ("ACTIVE", "SHADOW"))
    print(f"governor: hypothesis registry M_ever={len(reg)} M_live={m_live} "
          f"per_test_z={c.get('per_test_z', 2.33)} "
          f"promotions={'ON' if c.get('allow_promotions', True) else 'GATED-OFF (D-7)'}")
    stats = era_stats(eras, c["default_era_start"], bmap, c)
    fills = era_fills(c["default_era_start"])
    now = datetime.now(timezone.utc).isoformat()

    promotions, demotions = [], []
    for key, meta in sorted(bmap.items()):
        pair, sess, sid = key
        if meta["manual_only"] or meta["status"] not in ("ACTIVE", "SHADOW"):
            continue
        s = stats.get(key)
        f = fills.get((pair, sid))
        if meta["status"] == "SHADOW" and s:
            ok = (s["n"] >= c["bar_n"] and s["avg"] >= c["bar_avg"]
                  and s["lcb"] is not None and s["lcb"] > c["lcb_min"]
                  and not (s["n7"] >= c["recent_n"] and s["avg7"] is not None
                           and s["avg7"] < c["recent_min"]))
            if ok:
                promotions.append((key, s, None))
        elif meta["status"] == "ACTIVE":
            bar_lost = s and s["n"] >= c["bar_n"] and s["avg"] < c["bar_avg"]
            fills_red = f and f["n"] >= c["fills_n"] and f["avg"] < c["fills_avg_max"]
            if bar_lost or fills_red:
                demotions.append((key, s, f))

    # strongest evidence first; rails cap the day's changes
    promotions.sort(key=lambda x: -(x[1]["lcb"] or 0))
    demotions.sort(key=lambda x: (x[1]["avg"] if x[1] else 0))
    promotions = promotions[:c["max_promotions"]]
    demotions = demotions[:c["max_demotions"]]
    if not c.get("allow_promotions", True) and promotions:
        print(f"governor: {len(promotions)} setup(s) meet the bar but promotions "
              f"are GATED OFF pending D-7 (shared evidence engine + shadow-exit "
              f"simulation) — logged, not flipped")
        with open(LEDGER, "a") as led:
            for (pair, sess, sid), st_, f_ in promotions:
                led.write(json.dumps({"t": now, "action": "PROMOTE-GATED",
                                      "pair": pair, "session": sess, "setup": sid,
                                      "why": "allow_promotions=false (D-7 pending)",
                                      "dry_run": args.dry_run}) + "\n")
        promotions = []
    if not c.get("allow_demotions", True):
        demotions = []

    if not promotions and not demotions:
        print(f"governor: no setups due ({len(stats)} era-scored, {len(bmap)} in book)")
        return

    with open(LEDGER, "a") as led:
        for kind, batch, new_status in (("PROMOTE", promotions, "ACTIVE"),
                                        ("DEMOTE", demotions, "SHADOW")):
            for (pair, sess, sid), s, f in batch:
                why = []
                if s:
                    _l = "None" if s["lcb"] is None else f"{s['lcb']:+.2f}"
                    why.append(f"era n={s['n']} n_eff={s['n_eff']} "
                               f"net_avg={s['avg']:+.2f}p lcb={_l} "
                               f"7d={s['avg7'] if s['avg7'] is None else round(s['avg7'], 2)}({s['n7']}) "
                               f"[net-of-cost]")
                if f:
                    why.append(f"fills n={f['n']} avg={f['avg']:+.2f}p")
                res = flip(pair, sess, sid, new_status, args.dry_run)
                line = {"t": now, "action": kind, "pair": pair, "session": sess,
                        "setup": sid, "why": "; ".join(why),
                        "dry_run": bool(args.dry_run), "result": res}
                led.write(json.dumps(line) + "\n")
                print(f"GOVERNOR {kind} {pair}/{sess}/{sid}  [{'; '.join(why)}]"
                      f"{'  (dry-run)' if args.dry_run else ''}")
                if not args.dry_run and res.get("ok"):
                    eras["|".join((pair, sess, sid))] = now   # evidence clock restarts
    if not args.dry_run:
        save_state(st)


if __name__ == "__main__":
    main()
