#!/usr/bin/env python3
"""ops/governor.py — the Bar Governor: autonomous promote/demote by evidence.

The trial system's closing loop (Brock, 2026-07-27): the bot flips its own
switches. Shadows that clear an enabled admission lane go to a reduced-risk
PROBE; broker family cycles decide graduation to ACTIVE or return to SHADOW.

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
CHEATER v4: independently qualify PARENT_ONLY and FAMILY_PP on resolved,
risk-normalized virtual cycles. FAMILY_PP also needs a positive paired
GridLift LCB. Every admission is a one-seat, 0.33x family PROBE.
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
PP_RETIRE_API = "http://127.0.0.1:8084/api/pp/retire"

DEFAULT_CFG = {
    "enabled": True,
    # Entry lanes fail closed. Ordinary promotions still use the parent-only
    # horizon metric and remain disabled; cheater is commissioned separately.
    "allow_promotions": False,
    "allow_demotions": True,
    # D-7 evidence bar (core/trial_evidence.promotion_predicate):
    "min_raw_episodes": 20,        # bar_n honored as a deprecated alias
    "min_independent_days": 10,
    # ── STRIKE RULE (2026-08-03, operator) ──────────────────────────────────
    # Every executed demotion is a permanent strike. Ever-demoted cells must
    # clear the stricter redemption bar to promote again; the strike that
    # reaches the limit retires the cell to DISABLED (manual re-enable only).
    "redemption_min_raw_episodes": 20,
    "redemption_min_independent_days": 10,
    "strike_disable_count": 3,
    # ── TRUTH-CHECK GATE (2026-08-04, operator) ─────────────────────────────
    # A shadow whose virtual family-cycle sign CONTRADICTS its own broker
    # fills (full window — era resets never erase real fills) cannot promote:
    # the sim is proven wrong for that cell, so it does not get to spend money.
    "truth_check_gate": True,
    # ── SEAT POOLS (2026-08-06) ─────────────────────────────────────────────
    # Durable, status-derived ceiling on TOTAL audition seats across BOTH
    # lanes — the actual risk control. `cheater_max_seats` is a per-lane
    # POLICY cap counted from governor state; if that state is ever lost the
    # global ceiling still holds the line, which is why the risk control is
    # the one derived from cell status.
    "max_probe_seats_total": 4,
    "bar_avg": 2.0, "lcb_min": 0.0,
    "recent_n": 5, "recent_min": 0.0,
    "bootstrap_reps": 10000, "bootstrap_confidence": 0.95,
    "fdr_q": 0.05,
    # FAMILY RULE (2026-07-28): parent + its poppers, broker net pips.
    # -60p = one full popper SL; +60p of realized family green = seat safe.
    "cheater_promotion_enabled": False,   # OPT-IN via the dashboard toggle
    # ── CHEATER v4 (censor-aware paired-policy ticket) ───────────────────────
    # Risk-covered gain over resolved virtual family cycles. Both policies
    # qualify independently; the grid also has to prove positive paired lift.
    "cheater_metric_version": "family-cycle-v4",
    "cheater_min_cycles": 3,
    "cheater_min_days": 2,
    "cheater_min_positive_cycles": 2,
    "cheater_min_risk_covered_gain": 1.25,   # R units actually covered
    "cheater_min_harvest_coverage": 1.20,    # smoothed (+0.5/+0.5 prior)
    "cheater_max_single_cycle_share": 0.60,  # one freak episode can't buy it
    "cheater_require_flat": True,
    "cheater_max_seats": 1,                  # commissioning cap; explicit in config
    "cheater_max_evals": 6,                  # replay budget per run
    "cheater_replay_days": 8.0,              # >= 7d live grid age + resolution day
    "cheater_replay_limit": 8,
    "cheater_min_paired_cycles": 3,
    "cheater_min_grid_lift_lcb": 0.0,        # PP_ON must add proven paired value
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


def cheater_policy_view(r: dict, policy: str) -> dict:
    """Return one policy's internally consistent evidence view."""
    if policy == "PARENT_ONLY":
        return dict(r, u_list=r.get("u_par_list") or [],
                    days=r.get("days_par", r.get("days", 0)),
                    censored=r.get("censored_par", r.get("censored", 0)),
                    last_censored=r.get("last_censored_par",
                                        r.get("last_censored", False)))
    return dict(r, u_list=r.get("u_list") or [],
                censored=r.get("censored", 0))


def selected_policy_cs(r: dict, policy: str) -> float:
    """Cumulative covered gain for the exact policy being ranked."""
    return round(sum(cheater_policy_view(r, policy).get("u_list") or []), 2)


def cheater_v3_predicate(r: dict, c: dict, policy: str = "FAMILY_PP") -> tuple:
    """The family-cycle cheater ticket -> (passes, why). r = a
    family_cycle_replay.score_cell row (virtual cycles, live mechanics).
    Each policy is graded independently before selection — a strong parent
    harmed by its grid is tested on PARENT_ONLY cycles, not condemned by
    PP_ON ones.
    Every gate exists to stop one freak episode buying a seat."""
    r = cheater_policy_view(r, policy)
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
    if c.get("cheater_require_flat", True):
        missing = int(r.get("missing_cycles", 0) or 0)
        if missing:
            return False, f"{missing} replay cycle(s) missing data"
        unresolved = int(r.get("censored", 0) or 0)
        if unresolved:
            return False, f"{unresolved} selected-policy cycle(s) unresolved"
        if r.get("last_censored"):
            return False, "latest cycle still open"
    return True, (f"CS={cs:+.2f}R over {n} resolved virtual cycles / "
                  f"{r.get('days')}d, coverage {cov:.2f}")


def cheater_v3_decision(r: dict, c: dict) -> tuple:
    """Qualify BOTH policies, then select only among policies that pass.

    PP_ON additionally needs a positive lower confidence bound on paired
    GridLift.  Completed-only, unpaired means can never select the grid.
    Returns ``(policy, why, diagnostics)``; policy is NONE when neither mode
    has earned a seat.
    """
    pp_ok, pp_why = cheater_v3_predicate(r, c, "FAMILY_PP")
    par_ok, par_why = cheater_v3_predicate(r, c, "PARENT_ONLY")
    paired_n = int(r.get("grid_lift_n", 0) or 0)
    lift_lcb = r.get("grid_lift_lcb")
    pp_lift_ok = (paired_n >= int(c.get("cheater_min_paired_cycles", 3))
                  and lift_lcb is not None
                  and float(lift_lcb) > float(c.get("cheater_min_grid_lift_lcb", 0.0)))
    diag = {"FAMILY_PP": {"passes": pp_ok, "why": pp_why},
            "PARENT_ONLY": {"passes": par_ok, "why": par_why},
            "paired_n": paired_n, "grid_lift_lcb": lift_lcb,
            "pp_lift_proven": pp_lift_ok}
    if pp_ok and pp_lift_ok:
        return "FAMILY_PP", pp_why, diag
    if par_ok:
        return "PARENT_ONLY", par_why, diag
    if pp_ok and not pp_lift_ok:
        return "NONE", (f"PP ticket passed but paired GridLift unproven "
                        f"(n={paired_n}, LCB={lift_lcb})"), diag
    return "NONE", f"PP[{pp_why}] PARENT[{par_why}]", diag


def cheater_v3_policy(r: dict) -> str:
    """Conservative display helper; governance uses cheater_v3_decision()."""
    lift_lcb = r.get("grid_lift_lcb")
    if lift_lcb is not None and lift_lcb > 0 and (r.get("U_pp") or 0) > 0:
        return "FAMILY_PP"
    if (r.get("U_par") or 0) > 0:
        return "PARENT_ONLY"
    return "NONE"


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
    try:
        return _post(PP_API, {"cell": f"{pair}|{sess}|{sid}", "enabled": None}, dry)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def pp_retire(pair, sess, sid, dry):
    """Retire the exact flat grid before a seat/policy era transition."""
    try:
        return _post(PP_RETIRE_API, {"cell": f"{pair}|{sess}|{sid}"}, dry)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


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


def truth_gate(vc_row, fam_row) -> tuple:
    """(ok, detail). Blocks promotion ONLY on a proven contradiction: the cell
    has resolved virtual family cycles AND real broker fills, and their signs
    disagree. No broker record or no virtual cycles => nothing to contradict."""
    if not vc_row or not vc_row.get("cycles"):
        return True, "no virtual cycles"
    if not fam_row or not (fam_row.get("n") or 0):
        return True, "no broker fills"
    vm = vc_row.get("net_mean") or 0
    bu = fam_row.get("usd") or 0
    if (vm > 0) == (bu > 0):
        return True, f"vc {vm:+.1f}p/cyc agrees with broker ${bu:+.2f}"
    return False, (f"vc {vm:+.1f}p/cyc CONTRADICTS broker ${bu:+.2f} "
                   f"over {fam_row.get('n')} fill(s) — sim proven wrong here")


def demote_target(prior_strikes: int, cfg: dict) -> tuple:
    """(new_status, strike_number) for one executed demotion. THREE-STRIKES
    RULE (2026-08-03, operator): the strike that reaches strike_disable_count
    retires the cell to DISABLED — untouchable by every automation."""
    strike = prior_strikes + 1
    limit = int(cfg.get("strike_disable_count", 3))
    return ("DISABLED" if strike >= limit else "SHADOW", strike)


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
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def prepare_grid_transition(kind, pair, sess, sid, dry, policy=None,
                            pp_off_fn=pp_off, pp_retire_fn=pp_retire,
                            pp_on_fn=pp_on):
    """Quiesce -> retire -> establish the new policy before a status flip.

    The status writer is intentionally last: every partial failure leaves the
    old seat with poppers disabled, never a new seat attached to an old anchor,
    gid, sizing flag or evidence era.
    """
    off = pp_off_fn(pair, sess, sid, dry)
    if not isinstance(off, dict) or not off.get("ok"):
        return {"ok": False, "stage": "quiesce", "result": off}
    retired = pp_retire_fn(pair, sess, sid, dry)
    if not isinstance(retired, dict) or not retired.get("ok"):
        return {"ok": False, "stage": "retire", "quiesce": off,
                "result": retired}
    wants_grid = (kind in ("PROMOTE", "GRADUATE")
                  or (kind == "CHEATER-PROBE" and policy == "FAMILY_PP"))
    desired = pp_on_fn(pair, sess, sid, dry) if wants_grid else off
    if not isinstance(desired, dict) or not desired.get("ok"):
        return {"ok": False, "stage": "policy", "quiesce": off,
                "retire": retired, "result": desired}
    return {"ok": True, "quiesce": off, "retire": retired,
            "policy": "FAMILY_PP" if wants_grid else "PARENT_ONLY",
            "policy_result": desired}


def update_cheater_seat_book(kind, seats, key, now, metadata=None):
    """Production seat bookkeeping, extracted so tests exercise real logic."""
    if kind == "CHEATER-PROBE":
        metadata = metadata or {}
        seats[key] = {"t": now, "policy": metadata.get("policy"),
                      "cs": metadata.get("cs")}
    if kind in ("GRADUATE", "DEMOTE"):
        seats.pop(key, None)


def stage_era_reset(st, key, now):
    """Persist the conservative side of a transition before the status flip.

    If the process dies after this write but before the dashboard status write,
    the cell merely rebuilds evidence. The unsafe inverse—new capital trading
    under an old evidence clock—cannot occur.
    """
    st.setdefault("era_start", {})[key] = now
    st.setdefault("last_eval_blocks", {}).pop(key, None)


def probe_seat_count(book_map) -> int:
    """All current PROBEs consume the commissioning cap.

    Cell status is the durable trading truth. Auxiliary governor state can be
    lost between the status write and save_state(), so it must never enforce a
    risk cap.
    """
    return sum(1 for meta in book_map.values() if meta.get("status") == "PROBE")


def cheater_seat_count(seats) -> int:
    """PROBEs THIS LANE opened, from the cheater seat book.

    Deliberately NOT derived from cell status: status cannot say which lane
    seated a cell, and mis-attributing an ordinary PROBE to the cheater lane
    is what starved it. This is a policy cap only — the durable risk ceiling
    is `max_probe_seats_total`, enforced from status in probe_seat_count().
    """
    return len(seats or {})


def probe_leash_breached(cycle_nets, c: dict) -> bool:
    """Fast broker loss leash for every reduced-risk audition seat."""
    cyc = list(cycle_nets or [])
    return bool(cyc and (
        min(cyc) <= float(c.get("cheater_live_demote_pips", -45.0))
        or (len(cyc) >= 2 and sum(cyc) < 0)
        or (len(cyc) >= 2 and cyc[-1] < 0 and cyc[-2] < 0)))


def build_cheater_candidates(book_map, eras, default_era, db, min_cycles,
                             record_fn=None):
    """Candidate scan sourced only from raw, era-clocked episode records."""
    if record_fn is None:
        from research.tools.family_cycle_replay import episode_records
        record_fn = episode_records
    out = []
    for key, meta in sorted(book_map.items()):
        if meta.get("manual_only") or meta.get("status") != "SHADOW":
            continue
        era0 = str(eras.get("|".join(key), default_era))[:19]
        if len(record_fn(db, key[0], key[1], key[2], era0)) >= min_cycles:
            out.append((key, None, meta))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--cheater-diagnostic", action="store_true",
                    help="evaluate Cheater v4 candidates while admission stays OFF; "
                         "requires --dry-run and never queues a flip")
    ap.add_argument("--cheater-diagnostic-limit", type=int, default=0,
                    help="candidate count in diagnostic mode (0 = entire docket)")
    args = ap.parse_args()
    if args.cheater_diagnostic and not args.dry_run:
        ap.error("--cheater-diagnostic requires --dry-run")
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
            # (cheater candidacy moved OUT of this branch — review r3
            # defect 1: this branch requires `e`, which exists only when the
            # parent scorer produced completed net240s. Candidacy now comes
            # from episode_records() directly, after the loop.)
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
                cyc = f.get("cycle_nets") or []
                # Every PROBE is an audition and gets the fast leash. Safety
                # cannot depend on cheater_seats metadata surviving a crash.
                if probe_leash_breached(cyc, c):
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

    # CHEATER v4 evaluation: replay candidates through both policies,
    # family-cycle machine (both policies), gate on the risk-covered ticket,
    # rank by cumulative covered gain, cap by free seats.
    cheater_promos = []
    cheater_diagnostic_error = None
    cheater_scan_ok = False
    # SEAT POOLS: ordinary promotions no longer consume the cheater lane's
    # allowance. Before this, two ordinary PROBEs zeroed out the single
    # cheater seat and the lane the Commissioner spent five days earning
    # could never seat anything.
    probes_now  = probe_seat_count(bmap)                    # durable, all lanes
    global_free = max(0, int(c.get("max_probe_seats_total", 4)) - probes_now)
    cheater_used = cheater_seat_count(cheater_seats)        # policy, this lane
    seats_free = max(0, min(int(c.get("cheater_max_seats", 1)) - cheater_used,
                            global_free))
    # CANDIDACY (review r3 defect 1): straight from the episode DB — a shadow
    # whose parent episodes are all CENSORED (still open under the parent
    # horizon) can still resolve under the multi-day family replay; the
    # parent evidence object must have no say in who reaches the ticket.
    if c.get("cheater_promotion_enabled", False) or args.cheater_diagnostic:
        try:
            _db0 = json.load(open(REPO / "data" / "shadowboard.json"))
            _minc = int(c.get("cheater_min_cycles", 3))
            cheater_cands.extend(build_cheater_candidates(
                bmap, eras, c["default_era_start"], _db0, _minc))
            cheater_scan_ok = True
        except Exception as _cde:
            print(f"governor: cheater candidacy scan failed ({_cde})",
                  file=sys.stderr)
            if args.cheater_diagnostic:
                cheater_diagnostic_error = f"candidacy scan failed: {_cde}"
    cheater_diagnostics = []
    if cheater_cands and (seats_free > 0 or args.cheater_diagnostic):
        try:
            from research.tools.family_cycle_replay import (score_cell,
                                                            episode_records)
            db = json.load(open(REPO / "data" / "shadowboard.json"))
            eval_t = st.setdefault("cheater_eval_t", {})
            cheater_cands.sort(key=lambda x: eval_t.get("|".join(x[0]), ""))
            diag_limit = int(args.cheater_diagnostic_limit)
            eval_limit = (len(cheater_cands) if args.cheater_diagnostic and diag_limit <= 0
                          else diag_limit if args.cheater_diagnostic
                          else int(c.get("cheater_max_evals", 6)))
            for key, e, meta in cheater_cands[:eval_limit]:
                pair, sess, sid = key
                k = "|".join(key)
                era0 = str(eras.get(k, c["default_era_start"]))[:19]
                recs = episode_records(db, pair, sess, sid, era0)
                if len(recs) < int(c.get("cheater_min_cycles", 3)):
                    continue
                r = score_cell(pair, sess, sid, meta.get("side", "?"), recs,
                               float(c.get("cheater_replay_days", 8.0)),
                               int(c.get("cheater_replay_limit", 8)))
                eval_t[k] = now_iso
                pol, why, policy_diag = cheater_v3_decision(r, c)
                if pol != "NONE":
                    decision = {
                        "cheater_v4": why, "policy": pol,
                        "cs": selected_policy_cs(r, pol),
                        "grid_lift": r.get("grid_lift"),
                        "grid_lift_lcb": r.get("grid_lift_lcb"),
                        "policy_diagnostics": policy_diag}
                    if args.cheater_diagnostic:
                        cheater_diagnostics.append((key, "QUALIFIED", decision))
                        print(f"governor: cheater-v4 diagnostic QUALIFIED {k}: "
                              f"{pol} {why}; lift_lcb={r.get('grid_lift_lcb')}")
                    else:
                        cheater_promos.append((key, e, decision))
                else:
                    if args.cheater_diagnostic:
                        cheater_diagnostics.append((key, "DECLINED", {
                            "why": why, "policy_diagnostics": policy_diag}))
                    print(f"governor: cheater-v4 declined {k}: {why}")
        except Exception as exc:
            print(f"governor: cheater-v4 evaluation failed ({exc})", file=sys.stderr)
            if args.cheater_diagnostic:
                cheater_diagnostic_error = f"evaluation failed: {exc}"
        cheater_promos.sort(key=lambda x: -x[2]["cs"])
        cheater_promos = cheater_promos[:seats_free]
        if args.cheater_diagnostic:
            qualified = sum(1 for _, verdict, _ in cheater_diagnostics
                            if verdict == "QUALIFIED")
            print(f"governor: cheater-v4 diagnostic complete — "
                  f"{qualified}/{len(cheater_diagnostics)} qualified; "
                  "admission switch unchanged, no flips queued")
    elif args.cheater_diagnostic and cheater_scan_ok:
        print("governor: cheater-v4 diagnostic complete — 0/0 qualified; "
              "no raw candidates met the episode floor, admission switch unchanged")

    if args.cheater_diagnostic and cheater_diagnostic_error:
        print(f"governor: cheater-v4 diagnostic FAIL-CLOSED — "
              f"{cheater_diagnostic_error}", file=sys.stderr)
        raise SystemExit(1)

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
        # TRUTH-CHECK GATE: sim proven wrong by this cell's own broker fills
        # never spends money, no matter how good the stamp evidence looks.
        if c.get("truth_check_gate", True) and promotions:
            try:
                _vcd = json.loads((REPO / "data" / "virtual_cycles.json")
                                  .read_text()).get("rows", {})
            except (OSError, ValueError):
                _vcd = {}
            _tkept = []
            for item in promotions:
                (pair, sess, sid), e_, f_ = item
                _side = bmap.get((pair, sess, sid), {}).get("side", "?")
                _vc = _vcd.get("|".join((f"{pair}/{sess}", sid, _side)))
                ok_, det_ = truth_gate(_vc, fams.get((pair, sess, sid)))
                if ok_:
                    _tkept.append(item)
                else:
                    print(f"governor: TRUTH GATE blocked {pair}/{sess}/{sid} — {det_}")
                    with open(LEDGER, "a") as led:
                        led.write(json.dumps({
                            "t": now, "action": "PROMOTE-GATED-TRUTH",
                            "pair": pair, "session": sess, "setup": sid,
                            "why": det_, "dry_run": bool(args.dry_run)}) + "\n")
            promotions = _tkept
        promotions = _cluster_filter(promotions,
                                     lambda i: (i[1].block_lcb or 0))
        # TRUTH-CHECK GATE applies a fortiori to the cheater lane — it
        # qualifies ON the virtual metric, so a broker contradiction is a
        # direct falsification of its own admission ticket.
        if c.get("truth_check_gate", True) and cheater_promos:
            try:
                _vcd2 = json.loads((REPO / "data" / "virtual_cycles.json")
                                   .read_text()).get("rows", {})
            except (OSError, ValueError):
                _vcd2 = {}
            _ckept = []
            for item in cheater_promos:
                (pair, sess, sid) = item[0]
                _side = bmap.get((pair, sess, sid), {}).get("side", "?")
                _vc = _vcd2.get("|".join((f"{pair}/{sess}", sid, _side)))
                ok_, det_ = truth_gate(_vc, fams.get((pair, sess, sid)))
                if ok_:
                    _ckept.append(item)
                else:
                    print(f"governor: TRUTH GATE blocked cheater {pair}/{sess}/{sid} — {det_}")
                    with open(LEDGER, "a") as led:
                        led.write(json.dumps({
                            "t": now, "action": "CHEATER-GATED-TRUTH",
                            "pair": pair, "session": sess, "setup": sid,
                            "why": det_, "dry_run": bool(args.dry_run)}) + "\n")
            cheater_promos = _ckept
        cheater_promos = _cluster_filter(cheater_promos,
                                         lambda i: i[2]["cs"])

    # persist the heat file for the execution selector (engine hot-reads it)
    try:
        with open(REPO / "data" / "heat_scores.json", "w") as hf:
            json.dump({"t": now_iso, "scores": heat_scores}, hf)
    except OSError as _he:
        print(f"governor: heat file write failed ({_he})", file=sys.stderr)

    # PROSPECTIVE SNAPSHOTS (enhanced dashboard, 2026-07-31): one compact
    # line per run per scored key, written BEFORE outcomes are known — the
    # substrate for the Δ_promotion metric (does admission actually predict
    # the next broker family cycle, promoted vs eligible-but-not?). Append-
    # only; hindsight-proof by construction.
    try:
        _promoted = {"|".join(k) for k, _, _ in cheater_promos}
        _eligible = {"|".join(k) for k, _, _ in cheater_cands}
        with open(REPO / "data" / "score_snapshots.jsonl", "a") as sf:
            for k2, hs in heat_scores.items():
                sf.write(json.dumps({
                    "t": now_iso, "key": k2, "status": hs.get("status"),
                    "heat": hs.get("heat"), "trust": hs.get("trust"),
                    "n_cycles": hs.get("n_cycles"),
                    "eligible": k2 in _eligible,
                    "promoted": k2 in _promoted}) + "\n")
    except OSError as _se2:
        print(f"governor: snapshot write failed ({_se2})", file=sys.stderr)

    # strongest evidence first; rails cap the day's changes
    promotions.sort(key=lambda x: -(x[1].block_lcb or 0))
    demotions.sort(key=lambda x: (x[2]["net_pips"] if x[2] else
                                  (x[1].net_avg if x[1] and x[1].net_avg
                                   is not None else 0)))
    promotions = promotions[:c["max_promotions"]]
    # Global seat ceiling applies to the ordinary lane too — max_promotions
    # only ever bounded promotions PER RUN, so standing PROBE count could
    # grow without limit across runs. Cheater admissions are reserved first
    # because that lane already paid the Commissioner's validation cost.
    # RESERVE the commissioned lane's seats. Sharing a ceiling first-come
    # would re-create the starvation bug we just fixed: with fdr_q at 0.10 the
    # ordinary lane can fill every free seat in a single run, and the cheater
    # lane would again find nothing left on the next one.
    _cheat_reserve = 0
    if c.get("cheater_promotion_enabled", False):
        _cheat_reserve = max(0, int(c.get("cheater_max_seats", 1))
                             - cheater_used - len(cheater_promos))
    _ord_room = max(0, global_free - len(cheater_promos) - _cheat_reserve)
    if len(promotions) > _ord_room:
        for (pair, sess, sid), _e, _f in promotions[_ord_room:]:
            print(f"governor: seat ceiling — {pair}/{sess}/{sid} deferred "
                  f"({probes_now} PROBE(s) open, cap "
                  f"{c.get('max_probe_seats_total', 4)})")
        promotions = promotions[:_ord_room]
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
                if isinstance(f, dict) and "cheater_v4" in f:
                    why.append(f"CHEATER-v4: {f['cheater_v4']} — policy "
                               f"{f['policy']} (grid lift {f.get('grid_lift')}) — "
                               f"censor-aware paired-policy ticket")
                elif isinstance(f, dict) and "cheater_v3" in f:
                    why.append(f"CHEATER-v3 (legacy): {f['cheater_v3']} — policy "
                               f"{f.get('policy')}")
                elif isinstance(f, dict) and "cheater" in f:
                    why.append(f"CHEATER-PROMOTE(v1, retired): era cum {f['cheater']:+.1f}p")
                elif f:
                    why.append(f"family n={f['n']} net={f['net_pips']:+.1f}p "
                               f"(${f['net_usd']:+.2f}) [broker]")
                target_status, strike = new_status, None
                if kind == "DEMOTE":
                    _sc = st.setdefault("demotion_counts", {})
                    target_status, strike = demote_target(
                        int(_sc.get("|".join((pair, sess, sid)), 0)), c)
                    _lim = int(c.get("strike_disable_count", 3))
                    why.append(f"strike {strike}/{_lim}"
                               + (" -> DISABLED (three strikes, cell retired)"
                                  if target_status == "DISABLED" else ""))
                _policy = (f.get("policy") if isinstance(f, dict) else None)
                grid_transition = prepare_grid_transition(
                    kind, pair, sess, sid, args.dry_run, policy=_policy)
                if not grid_transition.get("ok"):
                    line = {"t": now, "action": f"{kind}-GRID-PREP-FAILED",
                            "pair": pair, "session": sess, "setup": sid,
                            "why": "; ".join(why), "dry_run": bool(args.dry_run),
                            "grid_transition": grid_transition}
                    led.write(json.dumps(line) + "\n")
                    print(f"GOVERNOR {kind} BLOCKED {pair}/{sess}/{sid}  "
                          f"[grid transition {grid_transition.get('stage')} failed]")
                    continue
                k2 = "|".join((pair, sess, sid))
                if not args.dry_run:
                    # Safe cross-file ordering: retire/quiesce first, then make
                    # the fresh era durable, then expose the new cell status.
                    stage_era_reset(st, k2, now)
                    save_state(st)
                res = flip(pair, sess, sid, target_status, args.dry_run)
                line = {"t": now, "action": kind, "pair": pair, "session": sess,
                        "setup": sid, "why": "; ".join(why),
                        "dry_run": bool(args.dry_run), "result": res,
                        "grid_transition": grid_transition}
                if strike is not None:
                    line["strikes"] = strike
                    line["new_status"] = target_status
                if res.get("ok") and not args.dry_run:
                    if strike is not None:
                        st["demotion_counts"][k2] = strike
                    update_cheater_seat_book(kind, cheater_seats, k2, now,
                                             f if isinstance(f, dict) else None)
                    save_state(st)
                led.write(json.dumps(line) + "\n")
                print(f"GOVERNOR {kind} {pair}/{sess}/{sid}  [{'; '.join(why)}]"
                      f"{'  (dry-run)' if args.dry_run else ''}")
    if not args.dry_run:
        save_state(st)


if __name__ == "__main__":
    main()
