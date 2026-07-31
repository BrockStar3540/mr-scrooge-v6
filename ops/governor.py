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
  DEMOTE   ACTIVE -> SHADOW   FAMILY RULE (Brock, 2026-07-28 — "net loss is
                              the key"): a parent setup and the poppers its
                              grid fired are ONE unit tracked in broker
                              net pips. Family n >= 5 with era net pips <=
                              -60 (one popper SL) -> demoted, and the cell's
                              poppers are switched off with it. A family
                              net pips >= +60 DEFENDS its seat: real broker
                              green outranks the worst-case stamp simulator,
                              so bar_lost cannot demote it. JUDGE-WHEN-FLAT:
                              while any family trade is open, no verdict —
                              the episode is scored when it completes. Only
                              unfamilied actives fall back to bar_lost (era
                              v2 n >= 20, net avg < +2.0).
SEQUENTIAL-PEEKING GUARD: a setup that failed the bar is not re-tested until
it has at least one NEW independent block — daily re-rolls of the same
evidence cannot fish their way over the line.

RAILS: max 2 promotions + 4 demotions per run · DISABLED and "manual_only"
setups never touched · sides never flipped · flips go through the dashboard's
own /api/cell/status writer (validated, hot-reloaded, journaled) · every
decision appended to data/governor_ledger.jsonl · the era clock per setup is
owned by data/governor_state.json — any flip (or first sight) restarts the
evidence window, so a config-era change can never trade on stale proof.

Cron (EC2): 35 */6 * * *  — every SIX HOURS (Brock, 2026-07-30; was daily).
CHEATER PROMOTION: era-v2 cum net >= +100p promotes immediately, bar bypassed.
Manual: --dry-run first.
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
PP_API = "http://127.0.0.1:8084/api/pp/toggle"

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
    # FAMILY RULE (2026-07-28): parent + its poppers, broker net pips.
    # -60p = one full popper SL; +60p of realized family green = seat safe.
    # CHEATER PROMOTION (Brock, 2026-07-30): a shadow whose CURRENT-ERA v2
    # cumulative net reaches +100p promotes immediately, bar bypassed — a hot
    # hand gets a seat without waiting out the sample. Ledgered as
    # CHEATER-PROMOTE; era discipline still applies (legacy history can't cheat).
    "cheater_promotion_enabled": False,   # OPT-IN via the dashboard toggle
    # ── CHEATER v3 (family-cycle ticket, charter 2026-07-31) ─────────────────
    # The lane stays; the ticket changed: +100p of parent-horizon pips is
    # replaced by RISK-COVERED GAIN over resolved virtual family cycles under
    # the full live mechanics. A cheater seat is a PROBE (0.33x sizing).
    "cheater_metric_version": "family-cycle-v3",
    "cheater_min_cycles": 3,
    "cheater_min_days": 2,
    "cheater_min_positive_cycles": 2,
    "cheater_min_risk_covered_gain": 1.25,   # R units actually covered
    "cheater_min_harvest_coverage": 1.20,    # smoothed (+0.5/+0.5 prior)
    "cheater_max_single_cycle_share": 0.60,  # one freak episode can't buy it
    "cheater_require_flat": True,
    "cheater_max_seats": 2,
    "cheater_max_evals": 6,                  # replay budget per run
    "cheater_replay_days": 2.5,
    "cheater_replay_limit": 8,
    "cheater_live_demote_pips": -45.0,       # ~ -0.75R at the 60p family stop
    "cheater_graduate_cycles": 6,            # broker cycles to earn full ACTIVE
    # ── Heat/Trust adaptive layer (charter 2026-07-31) ───────────────────────
    "trusted_min_cycles": 8,                 # broker cycles to earn TRUSTED
    "trusted_demote_heat": -0.25,            # decay confirmation threshold
    "cluster_best_only": True,               # one seat per (pair, side) cluster
    # legacy v1 keys (retired 2026-07-31, kept for old config files)
    "cheater_cum_pips": 100.0,
    "cheater_min_n": 3,
    "family_min_trades": 5,          # legacy (B-117: superseded by cycles)
    "family_min_cycles": 2,          # completed grid cycles to convict on net
    "family_defend_cycles": 3,       # completed cycles to DEFEND a seat
    "family_catastrophic_pips": -90.0,  # ONE completed cycle this bad benches
    "family_demote_pips": -60.0,
    "family_defend_pips": 60.0,
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


def family_fills(default_era):
    """(pair, family_setup) -> family row from broker fills since default era:
    parents + their poppers as ONE unit (broker_setup_audit "families" block).
    Rows carry per-trade open times so callers can re-clock to a setup's era.
    B-117: keyed (instrument, SESSION, setup) — 47 setup ids repeat across
    sessions and the old pair+setup join merged their evidence."""
    try:
        out = subprocess.run(
            [sys.executable, str(REPO / "research" / "tools" / "broker_setup_audit.py"),
             "--since", default_era.replace("+00:00", "Z"), "--json"],
            capture_output=True, text=True, timeout=180)
        rows = json.loads(out.stdout).get("families", [])
    except Exception as exc:
        print(f"governor: fills audit unavailable ({exc}) — stamps-only run", file=sys.stderr)
        return {}
    return {(r["instrument"], r.get("session", "?"), r["setup"]): r
            for r in rows}


def cheater_v3_predicate(r: dict, c: dict, policy: str = "FAMILY_PP") -> tuple:
    """The family-cycle cheater ticket -> (passes, why). r = a
    family_cycle_replay.score_cell row (virtual cycles, live mechanics).
    POLICY FIRST (external review 2026-07-31): the predicate grades the
    CHOSEN policy's returns — a strong parent harmed by its grid is tested
    on PARENT_ONLY cycles, not condemned by PP_ON ones.
    Every gate exists to stop one freak episode buying a seat."""
    if policy == "PARENT_ONLY":
        r = dict(r, u_list=r.get("u_par_list") or [])
    n = len(r.get("u_list") or [])
    need = int(c.get("cheater_min_cycles", 3))
    if n < need:
        return False, f"cycles {n}<{need}"
    if int(r.get("days", 0)) < int(c.get("cheater_min_days", 2)):
        return False, f"days {r.get('days', 0)}<{c.get('cheater_min_days', 2)}"
    u = r.get("u_list") or []
    pos = [x for x in u if x > 0]
    if len(pos) < int(c.get("cheater_min_positive_cycles", 2)):
        return False, f"positive cycles {len(pos)}"
    cs = sum(u)
    if cs < float(c.get("cheater_min_risk_covered_gain", 1.25)):
        return False, f"CS {cs:+.2f}R < +{c.get('cheater_min_risk_covered_gain', 1.25)}R"
    if pos and max(pos) / sum(pos) > float(c.get("cheater_max_single_cycle_share", 0.60)):
        return False, "single cycle > 60% of gain"
    neg = sum(-x for x in u if x < 0)
    cov = (sum(pos) + 0.5) / (neg + 0.5)
    if cov < float(c.get("cheater_min_harvest_coverage", 1.20)):
        return False, f"coverage {cov:.2f}"
    if c.get("cheater_require_flat", True) and r.get("last_censored"):
        return False, "latest cycle still open"
    return True, (f"CS={cs:+.2f}R over {n} resolved virtual cycles / "
                  f"{r.get('days')}d, coverage {cov:.2f}")


def cheater_v3_policy(r: dict) -> str:
    """GridLift management-policy selector: FAMILY_PP | PARENT_ONLY | NONE.
    Strong parent + harmful grid -> seat WITHOUT poppers; weak parent +
    profitable family -> seat WITH poppers; both negative -> no seat."""
    upp = r.get("U_pp")
    upar = r.get("U_par")
    upp = float("-inf") if upp is None else upp
    upar = float("-inf") if upar is None else upar
    if upp <= 0 and upar <= 0:
        return "NONE"
    return "FAMILY_PP" if upp >= upar else "PARENT_ONLY"


R_PIPS = 60.0     # 1R = the 60p family stop (risk-unit proxy for broker cycles)


def heat_trust_for(f, now) -> dict:
    """Heat (2d) + Trust (21d) from a family view's completed cycles.
    R proxy = cycle pips / 60 (the family stop)."""
    from core.family_cycle import (two_speed_score, HEAT_HALF_LIFE_D,
                                   TRUST_HALF_LIFE_D)
    events = []
    for end, pips in (f.get("cycle_events") or []) if f else []:
        try:
            t = datetime.fromisoformat(end.replace("Z", "+00:00"))
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
            events.append((t, pips / R_PIPS))
        except (ValueError, TypeError):
            continue
    heat = two_speed_score(events, now, HEAT_HALF_LIFE_D)
    trust = two_speed_score(events, now, TRUST_HALF_LIFE_D)
    return {"heat": heat["score"], "trust": trust["score"],
            "heat_n_eff": heat["n_eff"], "n_cycles": len(events)}


def is_trusted(ht: dict, c: dict) -> bool:
    """TRUSTED (charter): repeated broker success earns evidence-based
    inertia — kept while economically positive, not while hottest."""
    return bool(ht and ht.get("n_cycles", 0) >= int(c.get("trusted_min_cycles", 8))
                and (ht.get("trust") or 0) > 0)


def active_verdict(e, f, c: dict, min_raw: int, ht: dict = None) -> tuple:
    """FAMILY RULE for one ACTIVE setup -> (demote: bool, reason: str).
    f = era-clocked family view {n, net_pips, net_usd, n_open} or None; e =
    stamp evidence (SetupEvidence) or None. Broker family net pips outranks
    the stamp simulator in BOTH directions: deep red convicts, solid green
    defends; bar_lost applies only when the family doesn't defend.

    JUDGE-WHEN-FLAT (Brock, 2026-07-28): while ANY family trade is open, NO
    verdict at all — a parent can stop −60 while its poppers ride toward +30;
    a mid-episode demotion judges half a scale-in AND switches the poppers
    off right before the harvest. The episode is scored when it completes."""
    if f and f.get("n_open"):
        return False, "episode_open"
    # B-117: convict/defend on completed GRID CYCLES, not closed legs — one
    # grid excursion producing six closed trades is ONE observation.
    # Asymmetric (charter): a single catastrophic completed cycle benches;
    # defending a seat needs MORE independent cycles than convicting.
    n_cyc = int(f.get("n_cycles", 0)) if f else 0
    cyc_nets = (f.get("cycle_nets") or []) if f else []
    min_cyc = int(c.get("family_min_cycles", 2))
    def_cyc = int(c.get("family_defend_cycles", 3))
    cata = float(c.get("family_catastrophic_pips", -90.0))
    family_red = bool(f and (
        (n_cyc >= min_cyc and f["net_pips"] <= float(c["family_demote_pips"]))
        or (n_cyc >= 1 and cyc_nets and min(cyc_nets) <= cata)))
    family_green = bool(f and n_cyc >= def_cyc
                        and f["net_pips"] >= float(c["family_defend_pips"]))
    bar_lost = bool((not family_green) and e and e.raw_n >= min_raw and (
        e.net_avg is None or e.net_avg < float(c["bar_avg"])))
    if family_red:
        # TRUSTED inertia (charter): a trusted seat is not churned on the
        # first red patch — demotion requires the decay CONFIRMED by Heat
        # (< -0.25R). The catastrophic single-cycle bench stands regardless
        # (risk suspension outranks inertia).
        _cata_hit = bool(cyc_nets and min(cyc_nets) <= cata)
        if (not _cata_hit) and ht and is_trusted(ht, c)                 and (ht.get("heat") or 0) >= float(c.get("trusted_demote_heat", -0.25)):
            return False, "trusted_inertia"
        return True, "family_red"
    if bar_lost:
        return True, "bar_lost"
    return False, "family_green" if family_green else "hold"


def family_era_view(fam: dict, era_start: str) -> dict:
    """A family row re-clocked to one setup's era: only trades opened at/after
    era_start count, so a mechanics change can't be convicted (or defended) on
    the old config's trades. Times compare as ISO strings (minute precision).
    n_open passes through un-clocked — an open trade defers the verdict
    regardless of when it was opened (it is current exposure either way)."""
    cut = (era_start or "")[:16]
    trades = [t for t in fam.get("trades", []) if (t.get("t") or "") >= cut]
    # B-117: the independent unit is the completed GRID CYCLE, not the leg
    from research.tools.broker_setup_audit import cycles_of
    cycles = cycles_of(trades, fam.get("open_ts", []))
    from core.family_cycle import edge_lcb
    return {"n": len(trades), "net_pips": round(sum(t["pips"] for t in trades), 1),
            "net_usd": round(sum(t["usd"] for t in trades), 2),
            "n_open": int(fam.get("n_open", 0)),
            "n_cycles": len(cycles),
            "cycle_nets": [c["pips"] for c in cycles],
            "cycle_events": [(c["end"], c["pips"]) for c in cycles],
            "worst_cycle": min((c["pips"] for c in cycles), default=None),
            # Geometry v3 vector (broker side)
            "edge_lcb": edge_lcb([c["pips"] for c in cycles]),
            "cycle_bps": fam.get("cycle_bps"),
            "open_floor_usd": fam.get("open_floor_usd")}


def _post(url, payload, dry):
    if dry:
        return {"ok": True, "dry_run": True}
    import os as _os
    headers = {"Content-Type": "application/json"}
    tok = _os.environ.get("DASHBOARD_TOKEN", "")
    if tok:
        headers["X-Scrooge-Token"] = tok
    req = urllib.request.Request(url, method="POST",
        data=json.dumps(payload).encode(), headers=headers)
    return json.loads(urllib.request.urlopen(req, timeout=15).read())


def pp_on(pair, sess, sid, dry):
    """Clear a setup-scoped popper override (external review 2026-07-31): a
    demotion writes per_cell=false with the seat; a promotion that WANTS the
    grid must explicitly clear it, or a rehabilitated family winner trades
    popperless — the exact stale-blanket shape that bit live on 2026-07-30."""
    return _post(PP_API, {"cell": f"{pair}|{sess}|{sid}", "enabled": None}, dry)


def _status_now(pair, sess, setup_id):
    """Re-read a setup's CURRENT status from config (not the run's snapshot)."""
    try:
        d = json.loads((CELLS / f"{pair}.json").read_text())
        for su in d.get("sessions", {}).get(sess, {}).get("setups", []):
            if su.get("id") == setup_id:
                return su.get("status", "?")
    except Exception:
        pass
    return "?"


def flip(pair, sess, setup_id, status, dry):
    # DISABLED IS SACRED (Brock, 2026-07-30): a manually disabled setup is
    # untouchable by every automation — promotion (bar OR cheater) and
    # demotion alike. Re-check the live status at flip time so a hand-flip
    # mid-run can never be overridden by this run's stale snapshot.
    cur = _status_now(pair, sess, setup_id)
    # PROBE (charter): a legal intermediate seat — promote from SHADOW or
    # PROBE; demote from ACTIVE or PROBE. DISABLED stays sacred.
    if status == "ACTIVE" and cur not in ("SHADOW", "PROBE"):
        return {"ok": False, "skipped": f"not SHADOW/PROBE at flip time (now {cur})"}
    if status == "PROBE" and cur != "SHADOW":
        return {"ok": False, "skipped": f"not SHADOW at flip time (now {cur})"}
    if status == "SHADOW" and cur not in ("ACTIVE", "PROBE"):
        return {"ok": False, "skipped": f"not ACTIVE/PROBE at flip time (now {cur})"}
    return _post(API, {"pair": pair, "session": sess,
                       "setup_id": setup_id, "status": status}, dry)


def pp_off(pair, sess, setup_id, dry):
    """Family demotion switches the cell's poppers off with the setup — the
    grid is the family's loss engine, so it never outlives the seat."""
    try:
        return _post(PP_API, {"cell": f"{pair}|{sess}|{setup_id}",
                              "enabled": False}, dry)
    except Exception as exc:            # advisory: the demotion itself stands
        return {"ok": False, "error": str(exc)}


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

    # Charter (2026-07-31): a FAMILY's evidence is void when its popper
    # machinery changes — global ladder/gear or that cell's per_cell switch.
    # First sighting initializes without resetting (no era wipe on deploy).
    pp_hashes = st.setdefault("pp_hash", {})
    try:
        import hashlib as _hl
        _ppc = json.load(open(REPO / "config" / "pp_config.json"))
        _gear = {k: _ppc.get(k) for k in ("enabled", "marker_pips", "sl_pips",
                                          "trigger_pips", "trail_pips",
                                          "max_levels", "max_total_trades")}
        _per = _ppc.get("per_cell") or {}
        pp_resets = []
        for key in bmap:
            k = "|".join(key)
            _cellsw = {ck: v for ck, v in _per.items()
                       if k.startswith(ck) or ck in ("|".join(key[:2]), key[0])
                       or ck == k}
            h = _hl.sha256(json.dumps({"g": _gear, "c": _cellsw},
                                      sort_keys=True).encode()).hexdigest()[:12]
            old_h = pp_hashes.get(k)
            if old_h is not None and old_h != h:
                eras[k] = now_iso
                pp_resets.append(k)
            pp_hashes[k] = h
        if pp_resets:
            with open(LEDGER, "a") as led:
                for k in pp_resets:
                    led.write(json.dumps({"t": now_iso, "action": "ERA-RESET",
                                          "key": k, "why": "popper config changed",
                                          "dry_run": args.dry_run}) + "\n")
            print(f"governor: era clocks reset for {len(pp_resets)} setup(s) — popper config changed")
    except Exception as _ppe:
        print(f"governor: pp-hash check skipped ({_ppe})", file=sys.stderr)
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
    fams = family_fills(c["default_era_start"])
    last_eval = st.setdefault("last_eval_blocks", {})
    now = datetime.now(timezone.utc).isoformat()

    min_raw = int(c.get("min_raw_episodes", c.get("bar_n", 20)))
    promotions, demotions, graduations, cheater_cands = [], [], [], []
    cheater_seats = st.setdefault("cheater_seats", {})
    heat_scores = {}
    _now_dt = datetime.now(timezone.utc)
    for key, meta in sorted(bmap.items()):
        pair, sess, sid = key
        if meta["manual_only"] or meta["status"] not in ("ACTIVE", "PROBE", "SHADOW"):
            continue
        e = ev_all.get(key)
        fam_row = fams.get((pair, sess, sid))
        f = (family_era_view(fam_row, eras.get("|".join(key),
                             c["default_era_start"])) if fam_row else None)
        ht = heat_trust_for(f, _now_dt) if f else None
        heat_scores["|".join(key)] = {
            "heat": (ht or {}).get("heat"), "trust": (ht or {}).get("trust"),
            "n_cycles": (ht or {}).get("n_cycles", 0),
            "status": meta["status"], "side": meta.get("side", "?"),
            "trusted": bool(ht and is_trusted(ht, c)),
            "decaying": bool(ht and is_trusted(ht, c)
                             and (ht.get("heat") or 0)
                             < float(c.get("trusted_demote_heat", -0.25)))}
        if meta["status"] == "SHADOW" and e:  # PROBE takes the ACTIVE branch
            k = "|".join(key)
            # CHEATER v3 candidacy (external review 2026-07-31): enough
            # episodes to replay — and NOTHING else. The old positive-parent-
            # EV gate let the discredited metric decide who reaches family
            # scoring; a family winner with a losing parent (the control_rvol
            # pattern) could never cheat in. Budget fairness comes from
            # least-recently-evaluated rotation, not parent-EV ranking.
            if (c.get("cheater_promotion_enabled", False)
                    and e.raw_n >= int(c.get("cheater_min_cycles", 3))):
                cheater_cands.append((key, e, meta))
            prev_blocks = last_eval.get(k)
            # SEQUENTIAL-PEEKING GUARD: no new independent block since the
            # last failed test => same evidence, no re-roll (statistical bar only).
            if prev_blocks is not None and e.independent_days <= prev_blocks:
                continue
            if e.promotable:
                promotions.append((key, e, None))    # -> PROBE (charter: full
                # capital requires completed broker family evidence)
            else:
                last_eval[k] = e.independent_days
        elif meta["status"] in ("ACTIVE", "PROBE"):
            # FAMILY RULE — broker cycles of parent + poppers, era-clocked.
            demote, _reason = active_verdict(e, f, c, min_raw, ht=ht)
            if meta["status"] == "PROBE" and f and not f.get("n_open"):
                k = "|".join(key)
                cyc = f.get("cycle_nets") or []
                if k in cheater_seats and cyc:
                    # CHEATER LEASH (charter): one bad live cycle benches;
                    # cum < 0 after 2; two consecutive negatives
                    if (min(cyc) <= float(c.get("cheater_live_demote_pips", -45.0))
                            or (len(cyc) >= 2 and sum(cyc) < 0)
                            or (len(cyc) >= 2 and cyc[-1] < 0 and cyc[-2] < 0)):
                        demote = True
                # GRADUATION: enough completed broker cycles + positive
                # conservative edge earns the full-size seat
                if (not demote
                        and len(cyc) >= int(c.get("cheater_graduate_cycles", 6))
                        and (f.get("edge_lcb") or 0) > 0):
                    graduations.append((key, e, f))
                    continue
            if demote:
                demotions.append((key, e, f))

    # CHEATER v3 evaluation: replay the top candidates through the full
    # family-cycle machine (both policies), gate on the risk-covered ticket,
    # rank by cumulative covered gain, cap by free seats.
    cheater_promos = []
    seats_used = sum(1 for k2 in list(cheater_seats)
                     if bmap.get(tuple(k2.split("|")), {}).get("status") == "PROBE")
    seats_free = max(0, int(c.get("cheater_max_seats", 2)) - seats_used)
    if cheater_cands and seats_free > 0:
        try:
            from research.tools.family_cycle_replay import (score_cell,
                                                            episode_records)
            db = json.load(open(REPO / "data" / "shadowboard.json"))
            eval_t = st.setdefault("cheater_eval_t", {})
            cheater_cands.sort(key=lambda x: eval_t.get("|".join(x[0]), ""))
            for key, e, meta in cheater_cands[:int(c.get("cheater_max_evals", 6))]:
                pair, sess, sid = key
                k = "|".join(key)
                era0 = str(eras.get(k, c["default_era_start"]))[:19]
                recs = episode_records(db, pair, sess, sid, era0)
                if len(recs) < int(c.get("cheater_min_cycles", 3)):
                    continue
                r = score_cell(pair, sess, sid, meta.get("side", "?"), recs,
                               float(c.get("cheater_replay_days", 2.5)),
                               int(c.get("cheater_replay_limit", 8)))
                eval_t[k] = now_iso
                pol = cheater_v3_policy(r)          # policy FIRST...
                ok, why = cheater_v3_predicate(r, c, policy=pol)  # ...then the test
                if ok and pol != "NONE":
                    cheater_promos.append((key, e, {
                        "cheater_v3": why, "policy": pol,
                        "cs": round(sum(r.get("u_list") or []), 2),
                        "grid_lift": r.get("grid_lift")}))
                else:
                    print(f"governor: cheater-v3 declined {k}: "
                          f"{why if not ok else 'policy=NONE'}")
        except Exception as exc:
            print(f"governor: cheater-v3 evaluation failed ({exc})", file=sys.stderr)
        cheater_promos.sort(key=lambda x: -x[2]["cs"])
        cheater_promos = cheater_promos[:seats_free]

    # RELATIVE HEAT / correlated peers (charter): one market move must not
    # seat twelve near-identical setups — only the BEST candidate per
    # (pair, side) cluster wins a seat this run.
    if c.get("cluster_best_only", True):
        def _cluster_filter(batch, rank):
            best, out = {}, []
            for item in batch:
                key = item[0]
                cl = (key[0], bmap.get(key, {}).get("side", "?"))
                if cl not in best or rank(item) > rank(best[cl]):
                    best[cl] = item
            kept = set(id(v) for v in best.values())
            dropped = [i for i in batch if id(i) not in kept]
            for d in dropped:
                print(f"governor: cluster-best dropped {'|'.join(d[0])} "
                      f"(better peer in {d[0][0]}/{bmap.get(d[0], {}).get('side')})")
            return list(best.values())
        promotions = _cluster_filter(promotions,
                                     lambda i: (i[1].block_lcb or 0))
        cheater_promos = _cluster_filter(cheater_promos,
                                         lambda i: i[2]["cs"])

    # persist the heat file for the execution selector (engine hot-reads it)
    try:
        with open(REPO / "data" / "heat_scores.json", "w") as hf:
            json.dump({"t": now_iso, "scores": heat_scores}, hf)
    except OSError as _he:
        print(f"governor: heat file write failed ({_he})", file=sys.stderr)

    # strongest evidence first; rails cap the day's changes
    promotions.sort(key=lambda x: -(x[1].block_lcb or 0))
    demotions.sort(key=lambda x: (x[2]["net_pips"] if x[2] else
                                  (x[1].net_avg if x[1] and x[1].net_avg
                                   is not None else 0)))
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

    if not promotions and not demotions and not cheater_promos and not graduations:
        print(f"governor: no setups due ({len(ev_all)} era-scored v2, "
              f"{len(bmap)} in book)")
        if not args.dry_run:
            save_state(st)   # peeking-guard block counts still advance
        return

    with open(LEDGER, "a") as led:
        # Charter: ALL promotions land on PROBE (0.33x audition); full-size
        # ACTIVE is earned by GRADUATION on completed broker family cycles.
        for kind, batch, new_status in (("PROMOTE", promotions, "PROBE"),
                                        ("CHEATER-PROBE", cheater_promos, "PROBE"),
                                        ("GRADUATE", graduations, "ACTIVE"),
                                        ("DEMOTE", demotions, "SHADOW")):
            for (pair, sess, sid), e, f in batch:
                why = []
                if e:
                    _l = "None" if e.block_lcb is None else f"{e.block_lcb:+.2f}"
                    _q = "None" if e.q_value is None else f"{e.q_value:.3f}"
                    why.append(f"v2 n={e.raw_n} days={e.independent_days} "
                               f"net_avg={e.net_avg:+.2f}p blcb={_l} q={_q} "
                               f"7d={e.recent_avg}({e.recent_n}) [{METRIC_V2}]")
                if isinstance(f, dict) and "cheater_v3" in f:
                    why.append(f"CHEATER-v3: {f['cheater_v3']} — policy "
                               f"{f['policy']} (grid lift {f.get('grid_lift')}) — "
                               f"risk-covered ticket, bar bypassed (charter 2026-07-31)")
                elif isinstance(f, dict) and "cheater" in f:
                    why.append(f"CHEATER-PROMOTE(v1, retired): era cum {f['cheater']:+.1f}p")
                elif f:
                    why.append(f"family n={f['n']} net={f['net_pips']:+.1f}p "
                               f"(${f['net_usd']:+.2f}) [broker]")
                res = flip(pair, sess, sid, new_status, args.dry_run)
                line = {"t": now, "action": kind, "pair": pair, "session": sess,
                        "setup": sid, "why": "; ".join(why),
                        "dry_run": bool(args.dry_run), "result": res}
                if kind == "DEMOTE" and res.get("ok"):
                    # seat lost -> the family's grid loses its fire permit too
                    line["pp_off"] = pp_off(pair, sess, sid, args.dry_run)
                k2 = "|".join((pair, sess, sid))
                if res.get("ok") and not args.dry_run:
                    if kind == "CHEATER-PROBE":
                        cheater_seats[k2] = {"t": now, "policy": f.get("policy"),
                                             "cs": f.get("cs")}
                        if f.get("policy") == "PARENT_ONLY":
                            # strong parent, harmful grid: seat WITHOUT poppers
                            line["pp_off_policy"] = pp_off(pair, sess, sid,
                                                           args.dry_run)
                        else:
                            # FAMILY_PP seat: clear any stale demotion-era
                            # popper switch-off (review finding #6)
                            line["pp_on_policy"] = pp_on(pair, sess, sid,
                                                         args.dry_run)
                    elif kind in ("PROMOTE", "GRADUATE"):
                        line["pp_on_policy"] = pp_on(pair, sess, sid,
                                                     args.dry_run)
                    elif kind in ("GRADUATE", "DEMOTE"):
                        cheater_seats.pop(k2, None)
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
