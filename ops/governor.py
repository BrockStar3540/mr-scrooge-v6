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

REPO = Path(__file__).resolve().parents[1]
STORE = REPO / "data" / "shadowboard.json"
STATE_F = REPO / "data" / "governor_state.json"
LEDGER = REPO / "data" / "governor_ledger.jsonl"
CELLS = REPO / "config" / "cells"
CFG_F = REPO / "config" / "governor_config.json"
API = "http://127.0.0.1:8084/api/cell/status"

DEFAULT_CFG = {
    "enabled": True,
    "bar_n": 20, "bar_avg": 2.0, "lcb_min": 0.0,
    "recent_n": 5, "recent_min": 0.0,
    "fills_n": 5, "fills_avg_max": 0.0,
    "max_promotions": 2, "max_demotions": 4,
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
                out[(d.get("pair") or f.stem, sess, su.get("id"))] = {
                    "status": su.get("status", "?"), "side": su.get("side"),
                    "manual_only": bool(su.get("manual_only", False)),
                }
    return out


def era_stats(era_start_by_key, default_era, book_map):
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
        agg.setdefault(key, []).append((ep["t"], ep["scores"]["net240"]))
    out = {}
    cutoff7 = datetime.now(timezone.utc).timestamp() - 7 * 86400
    for key, rows in agg.items():
        nets = [n for _, n in rows]
        n = len(nets)
        avg = sum(nets) / n
        lcb = (avg - 1.645 * statistics.stdev(nets) / math.sqrt(n)) if n >= 2 else None
        r7 = [net for t, net in rows
              if datetime.fromisoformat(t).timestamp() >= cutoff7]
        out[key] = {"n": n, "avg": avg, "lcb": lcb,
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
    req = urllib.request.Request(API, method="POST",
        data=json.dumps({"pair": pair, "session": sess,
                         "setup_id": setup_id, "status": status}).encode(),
        headers={"Content-Type": "application/json"})
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
    bmap = book()
    stats = era_stats(eras, c["default_era_start"], bmap)
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

    if not promotions and not demotions:
        print(f"governor: no setups due ({len(stats)} era-scored, {len(bmap)} in book)")
        return

    with open(LEDGER, "a") as led:
        for kind, batch, new_status in (("PROMOTE", promotions, "ACTIVE"),
                                        ("DEMOTE", demotions, "SHADOW")):
            for (pair, sess, sid), s, f in batch:
                why = []
                if s:
                    why.append(f"era n={s['n']} avg={s['avg']:+.2f}p "
                               f"lcb={s['lcb']:+.2f} 7d={s['avg7'] if s['avg7'] is None else round(s['avg7'],2)}({s['n7']})")
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
