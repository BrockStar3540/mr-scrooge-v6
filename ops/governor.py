#!/usr/bin/env python3
"""ops/governor.py — the Bar Governor: autonomous promote/demote by evidence.

The trial system's closing loop (Brock, 2026-07-27): the bot flips its own
switches. Shadows that clear the activation bar on CURRENT-ERA evidence go
ACTIVE; actives that lose the bar — or go net-negative on broker fills — go
back to SHADOW, where stamping costs nothing and a seat can be re-earned.

THE STANDARD (D-7: evidence comes from core/trial_evidence — the SAME engine
behind the dashboard trophy — and counts executable-exit-v2 episodes only):
  PROMOTE  SHADOW -> ACTIVE   when promotion_predicate passes ALL of:
                              raw n >= 20 · independent day/session blocks
                              >= 10 · net avg >= +2.0p · block-bootstrap
                              LCB > 0 · 7d recent guard · BH-FDR q <= 0.05
  DEMOTE   ACTIVE -> SHADOW   when era v2 n >= 20 with net avg < +2.0 (bar
                              lost)  OR  era broker fills n >= 5, avg < 0
SEQUENTIAL-PEEKING GUARD: a setup that failed the bar is not re-tested until
it has at least one NEW independent block — daily re-rolls of the same
evidence cannot fish their way over the line.

RAILS: max 2 promotions + 4 demotions per run · DISABLED and "manual_only"
setups never touched · sides never flipped · flips go through the dashboard's
own /api/cell/status writer (validated, hot-reloaded, journaled) · every
decision appended to data/governor_ledger.jsonl · the era clock per setup is
owned by data/governor_state.json — any flip (or first sight) restarts the
evidence window, so a config-era change can never trade on stale proof.

Cron (EC2): 35 6 * * *  — after the nightly scorers. Manual: --dry-run first.
"""
from __future__ import annotations
import argparse, json, subprocess, sys, urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.trial_events import METRIC_V2, mechanics_hash
from core.trial_evidence import current_era_evidence

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
    # D-7 evidence bar (core/trial_evidence.promotion_predicate):
    "min_raw_episodes": 20,        # bar_n honored as a deprecated alias
    "min_independent_days": 10,
    "bar_avg": 2.0, "lcb_min": 0.0,
    "recent_n": 5, "recent_min": 0.0,
    "bootstrap_reps": 10000, "bootstrap_confidence": 0.95,
    "fdr_q": 0.05,
    "fills_n": 5, "fills_avg_max": 0.0,
    "max_promotions": 2, "max_demotions": 4,
    # per_test_z survives for the board's legacy-display LCB only; the
    # PROMOTION denominator is the day/session block bootstrap + BH-FDR (D-7).
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
                # reset anyone's clock. ONE implementation everywhere:
                # core.trial_events.mechanics_hash also signs every TRIALSTAMP.
                out[(d.get("pair") or f.stem, sess, su.get("id"))] = {
                    "status": su.get("status", "?"), "side": su.get("side"),
                    "manual_only": bool(su.get("manual_only", False)),
                    "cfg_hash": mechanics_hash(su),
                }
    return out


def _aliases():
    try:
        return {(r["cell"], r["setup"], r["side"]): r["as"]
                for r in json.loads((REPO / "config" / "setup_aliases.json").read_text())}
    except Exception:
        return {}


def evidence(book_map, gov_state, gov_cfg):
    """All promote/demote statistics via the ONE shared engine (D-7):
    executable-exit-v2 episodes, current era, mechanics-matched, block
    bootstrap + BH-FDR. The dashboard trophy reads the same function."""
    try:
        eps = json.loads(STORE.read_text())["episodes"]
    except Exception:
        return {}
    return current_era_evidence(eps, book_map, gov_state, gov_cfg,
                                aliases=_aliases())


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
          f"fdr_q={c.get('fdr_q', 0.05)} "
          f"promotions={'ON' if c.get('allow_promotions', True) else 'OFF'}")

    # METRIC-ERA-RESET (D-7, one-time): the promotion metric moved from
    # legacy-mid-v1 to executable-exit-v2. Old-metric evidence measured a
    # different (frictionless, mid-anchored) quantity, so every setup's
    # evidence restarts under the new metric — recorded per setup, once.
    if st.get("metric_version") != METRIC_V2:
        live = [k for k, m in sorted(bmap.items())
                if m["status"] in ("ACTIVE", "SHADOW")]
        with open(LEDGER, "a") as led:
            for key in live:
                led.write(json.dumps({
                    "t": now_iso, "action": "METRIC-ERA-RESET",
                    "key": "|".join(key),
                    "why": f"promotion metric -> {METRIC_V2}; evidence "
                           f"restarts under the executable-exit metric",
                    "dry_run": args.dry_run}) + "\n")
        st["metric_version"] = METRIC_V2
        print(f"governor: METRIC-ERA-RESET recorded for {len(live)} setups "
              f"(promotion metric -> {METRIC_V2})")
        if not args.dry_run:
            save_state(st)

    ev_all = evidence(bmap, st, c)
    fills = era_fills(c["default_era_start"])
    last_eval = st.setdefault("last_eval_blocks", {})
    now = datetime.now(timezone.utc).isoformat()

    min_raw = int(c.get("min_raw_episodes", c.get("bar_n", 20)))
    promotions, demotions = [], []
    for key, meta in sorted(bmap.items()):
        pair, sess, sid = key
        if meta["manual_only"] or meta["status"] not in ("ACTIVE", "SHADOW"):
            continue
        e = ev_all.get(key)
        f = fills.get((pair, sid))
        if meta["status"] == "SHADOW" and e:
            k = "|".join(key)
            prev_blocks = last_eval.get(k)
            # SEQUENTIAL-PEEKING GUARD: no new independent block since the
            # last failed test => same evidence, no re-roll.
            if prev_blocks is not None and e.independent_days <= prev_blocks:
                continue
            if e.promotable:
                promotions.append((key, e, None))
            else:
                last_eval[k] = e.independent_days
        elif meta["status"] == "ACTIVE":
            bar_lost = e and e.raw_n >= min_raw and (
                e.net_avg is None or e.net_avg < float(c["bar_avg"]))
            fills_red = f and f["n"] >= c["fills_n"] and f["avg"] < c["fills_avg_max"]
            if bar_lost or fills_red:
                demotions.append((key, e, f))

    # strongest evidence first; rails cap the day's changes
    promotions.sort(key=lambda x: -(x[1].block_lcb or 0))
    demotions.sort(key=lambda x: (x[1].net_avg if x[1] and x[1].net_avg
                                  is not None else 0))
    promotions = promotions[:c["max_promotions"]]
    demotions = demotions[:c["max_demotions"]]
    if not c.get("allow_promotions", True) and promotions:
        print(f"governor: {len(promotions)} setup(s) meet the bar but promotions "
              f"are switched OFF — logged, not flipped")
        with open(LEDGER, "a") as led:
            for (pair, sess, sid), e_, f_ in promotions:
                led.write(json.dumps({"t": now, "action": "PROMOTE-GATED",
                                      "pair": pair, "session": sess, "setup": sid,
                                      "why": "allow_promotions=false",
                                      "dry_run": args.dry_run}) + "\n")
        promotions = []
    if not c.get("allow_demotions", True):
        demotions = []

    if not promotions and not demotions:
        print(f"governor: no setups due ({len(ev_all)} era-scored v2, "
              f"{len(bmap)} in book)")
        if not args.dry_run:
            save_state(st)   # peeking-guard block counts still advance
        return

    with open(LEDGER, "a") as led:
        for kind, batch, new_status in (("PROMOTE", promotions, "ACTIVE"),
                                        ("DEMOTE", demotions, "SHADOW")):
            for (pair, sess, sid), e, f in batch:
                why = []
                if e:
                    _l = "None" if e.block_lcb is None else f"{e.block_lcb:+.2f}"
                    _q = "None" if e.q_value is None else f"{e.q_value:.3f}"
                    why.append(f"v2 n={e.raw_n} days={e.independent_days} "
                               f"net_avg={e.net_avg:+.2f}p blcb={_l} q={_q} "
                               f"7d={e.recent_avg}({e.recent_n}) [{METRIC_V2}]")
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
                    k = "|".join((pair, sess, sid))
                    eras[k] = now                # evidence clock restarts
                    last_eval.pop(k, None)       # fresh era, fresh peeking count
    if not args.dry_run:
        save_state(st)


if __name__ == "__main__":
    main()
