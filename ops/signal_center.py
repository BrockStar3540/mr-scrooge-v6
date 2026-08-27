"""ops/signal_center.py — Signal Command Center data layer (2026-08-27).

A read-only observational layer for MANUAL trading. Every qualifying setup —
ACTIVE, PROBE and SHADOW alike — emits one TRIALSTAMP per 5-min scan cycle
while its entry conditions hold (modules/cells/cell.py). That gives on/off
signal state for free: a setup whose trigger window closes (conditions stop
passing, session ends, entry cutoff reached) simply stops stamping and ages
off the board. Nothing here touches the trading path; this module only READS
the journal + existing evidence stores.

Evidence joined per firing signal:
  - chamber form (data/chamber_scores.json, 15-min refresh): era_avg/era_n
    (current-gear era sample) + form7/n7 (7-day stamp form)
  - governor strikes (data/governor_state.json demotion_counts)
  - median realized hold time from the shadow-sim episode store
    (data/shadowboard.json: scored, non-censored executable-exit-v2 episodes;
    exit_bar × 5min), horizon_min fallback

Scoring (per pair, shown verbatim in the page legend):
  shrink(x, n)      = x · n/(n+SHRINK_N)          — small samples say little
  evidence_pips     = 0.5·broker + 0.3·shrink(era_avg) + 0.4·… see below
                      broker = governor trust (21d decayed mean cycle R, real
                      fills) × 60p, shrunk n_cycles/(n_cycles+4); sim parts =
                      0.3·shrink(era_avg, era_n) + 0.2·shrink(form7, n7).
                      Renormalized over available parts; 0 when no sample.
                      Real broker cycles outrank the simulator (truth layers).
  contribution      = status_weight × 0.6^strikes × evidence_pips
                      × (1 + 0.5·tilt·sign(evidence)), tilt = (MFE−MAE)/
                      (MFE+MAE) era-median path shape: own-side pushes are
                      boosted by MFE-heavy paths, CONTRA pushes by MAE-heavy
                      paths (the MAE-flip doctrine), neutral under 5 episodes
                      (ACTIVE 1.0 / PROBE 0.6 / SHADOW 0.25 / SUSPENDED 0.10;
                      each governor strike permanently discounts the setup's
                      say until redemption — mirrors three-strikes doctrine)
  signed            = +contribution for longs, −contribution for shorts, so a
                      firing setup with NEGATIVE evidence pushes the OPPOSITE
                      side (the MAE-flip doctrine: right signal, wrong wiring)
  net               = Σ signed        gross = Σ |contribution|
  agreement         = |net| / gross
  confidence (0-100)= 100 · tanh(|net|/CONF_SCALE) · (0.5 + 0.5·agreement)
  distance_pips     = Σ|c|·|evidence| / Σ|c| over net-aligned contributors
  hold estimate     = Σ|c|·hold_med  / Σ|c| over net-aligned contributors

Server integration mirrors ops/shadowboard.py: get_center() only ever returns
the cache and kicks a daemon refresh thread (leased latch, B-133 pattern) —
the dashboard server is single-threaded, so the 15MB episode-store parse must
never run inline in a request handler.
"""
from __future__ import annotations

import json
import math
import os
import statistics
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from core.trial_events import parse_stamp

_ROOT = Path(__file__).resolve().parent.parent
_SHADOW_STORE = _ROOT / "data" / "shadowboard.json"
_GOV_STATE = _ROOT / "data" / "governor_state.json"

# ── Tunables ─────────────────────────────────────────────────────────────────
JOURNAL_HOURS = 48        # journal lookback (bounds "on air since" runs)
SCAN_S = 300              # engine scan cadence (main.py)
LIVE_S = 450              # last stamp older than this ⇒ trigger window closed
RUN_GAP_S = 900           # stamp gap that splits an on-air run (>2 missed scans)
SHRINK_N = 8              # sample-size shrinkage constant
CONF_SCALE = 8.0          # shrunk-pips at which confidence saturates (~76)
W_STATUS = {"ACTIVE": 1.0, "PROBE": 0.6, "SHADOW": 0.25, "SUSPENDED": 0.10}
# Evidence blend (renormalized over available parts) — broker truth leads
BROKER_W, ERA_W, FORM_W = 0.5, 0.3, 0.2
BROKER_SHRINK_N = 4       # broker cycles are scarce: shrink by n/(n+4)
R_PIPS = 60.0             # governor cycle-R proxy → pips (the family stop)
STRIKE_DISCOUNT = 0.6     # per governor strike: weight × 0.6^strikes
EXC_TILT_W = 0.5          # excursion-tilt multiplier width (0.5 → ×0.5..×1.5)
EXC_MIN_N = 5             # episodes of path data before the tilt speaks
_REFRESH_S = 45           # cache TTL
_LATCH_TIMEOUT_S = 300    # presume a refresh thread dead after this lease

_CACHE: dict = {"ts": 0.0, "data": None}
_LATCH: dict = {"t": 0.0}
_LOCK = threading.Lock()

_HOLD_CACHE: dict = {"mtime": None, "holds": {}}


def _journal_unit() -> str:
    return os.environ.get("SCROOGE_JOURNAL_UNIT", "mr-scrooge-v6")


def _read_journal_lines(hours: int = JOURNAL_HOURS) -> list:
    """Raw TRIALSTAMP journal lines, oldest first. Empty on any failure."""
    try:
        out = subprocess.check_output(
            ["journalctl", "--user", "-u", _journal_unit(),
             "--since", "%d hours ago" % hours, "--no-pager", "-o", "short-iso"],
            text=True, timeout=20, stderr=subprocess.DEVNULL,
        )
        return [ln for ln in out.splitlines() if "TRIALSTAMP" in ln]
    except Exception:
        return []


def _parse_ts(s: str) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def build_registry(lines: list) -> dict:
    """(pair, session, setup_id, side) -> firing record with current-run info.

    Stamps arrive oldest-first; a gap > RUN_GAP_S starts a new on-air run.
    The LATEST stamp's fields (status, spread, exit geometry) win.
    """
    reg: dict = {}
    for ln in lines:
        st = parse_stamp(ln)
        if st is None:
            continue
        ts = _parse_ts(st.get("timestamp", ""))
        if ts is None:
            continue
        key = (st.get("pair"), st.get("session"), st.get("setup_id"),
               st.get("side"))
        if None in key:
            continue
        rec = reg.get(key)
        if rec is None or (ts - rec["last"]).total_seconds() > RUN_GAP_S:
            rec = {"run_start": ts, "n_run": 0}
        rec["last"] = ts
        rec["n_run"] = rec.get("n_run", 0) + 1
        ex = st.get("exit_config") or {}
        rec.update({
            "status": st.get("status", "SHADOW"),
            "spread": st.get("spread_pips"),
            "horizon_min": st.get("horizon_min"),
            "trigger_pips": ex.get("trigger_pips"),
            "sl_pips": ex.get("sl_pips"),
            "mech": st.get("mechanics_hash"),
        })
        reg[key] = rec
    return reg


def live_signals(reg: dict, now: datetime) -> dict:
    """Registry filtered to signals whose trigger window is still open."""
    return {k: v for k, v in reg.items()
            if (now - v["last"]).total_seconds() <= LIVE_S}


def hold_stats(store: Path = _SHADOW_STORE) -> dict:
    """'PAIR|sess|setup' -> {hold_med_min, hold_n, mfe_med, mae_med, exc_n}
    from the v2 episode store, mtime-cached (~15MB, rewritten every 15 min;
    parse at most once per rewrite, only ever from the refresh thread).
    Hold = exit_bar × 5 over resolved (non-censored, non-horizon) episodes.
    MFE/MAE medians use EVERY scored v2 episode incl. censored — the path up
    to the horizon is observed either way, and excursion is exactly the stat
    censoring can't bias the way it biased net (B-129)."""
    try:
        m = os.path.getmtime(store)
    except OSError:
        return _HOLD_CACHE["holds"] or {}
    if _HOLD_CACHE["mtime"] == m:
        return _HOLD_CACHE["holds"]
    holds: dict = {}
    try:
        eps = json.loads(store.read_text()).get("episodes", {})
        bars: dict = {}
        excs: dict = {}
        for ep in eps.values():
            if not isinstance(ep, dict) or ep.get("mv") != 2:
                continue
            sc = ep.get("scores") or {}
            if not sc:
                continue
            key = "%s|%s" % ((ep.get("cell") or "?/?").replace("/", "|"),
                             ep.get("setup"))
            mfe = sc.get("mfe240") if sc.get("mfe240") is not None else sc.get("mfe60")
            mae = sc.get("mae240") if sc.get("mae240") is not None else sc.get("mae60")
            if isinstance(mfe, (int, float)) and isinstance(mae, (int, float)):
                excs.setdefault(key, []).append((float(mfe), float(mae)))
            if sc.get("censored") or sc.get("exit_reason") in (None, "horizon"):
                continue
            xb = sc.get("exit_bar")
            if not isinstance(xb, (int, float)) or xb <= 0:
                continue
            bars.setdefault(key, []).append(float(xb) * 5.0)
        for key in set(bars) | set(excs):
            rec = {}
            if key in bars:
                rec["hold_med_min"] = round(statistics.median(bars[key]), 1)
                rec["hold_n"] = len(bars[key])
            if key in excs:
                rec["mfe_med"] = round(statistics.median(v[0] for v in excs[key]), 1)
                rec["mae_med"] = round(statistics.median(v[1] for v in excs[key]), 1)
                rec["exc_n"] = len(excs[key])
            holds[key] = rec
    except (OSError, ValueError, MemoryError):
        return _HOLD_CACHE["holds"] or {}
    _HOLD_CACHE["mtime"] = m
    _HOLD_CACHE["holds"] = holds
    return holds


def excursion_mult(ev: float, path: dict):
    """(multiplier, tilt) — path-quality scaling of a signal's contribution.
    tilt = (MFE−MAE)/(MFE+MAE) ∈ [−1,1] from era-median excursions. The
    multiplier 1 + EXC_TILT_W·tilt·sign(ev) boosts a contribution whose
    excursion profile AGREES with the direction it pushes: an own-side push
    (ev>0) wants MFE-heavy paths; a CONTRA push (ev<0) wants MAE-heavy paths
    — losing cell + MAE ≫ MFE = right signal, wrong wiring, so the flip gets
    STRONGER, never weaker (MAE-flip doctrine). Neutral (1.0) below
    EXC_MIN_N episodes of path data."""
    mfe, mae = path.get("mfe_med"), path.get("mae_med")
    n = path.get("exc_n", 0) or 0
    if (n < EXC_MIN_N or mfe is None or mae is None
            or (mfe + mae) <= 0 or not ev):
        return 1.0, None
    tilt = (float(mfe) - float(mae)) / (float(mfe) + float(mae))
    sign = 1.0 if ev > 0 else -1.0
    return 1.0 + EXC_TILT_W * tilt * sign, round(tilt, 3)


def _strikes() -> dict:
    try:
        g = json.loads(_GOV_STATE.read_text())
        return dict(g.get("demotion_counts") or {})
    except (OSError, ValueError):
        return {}


def formula_hash() -> str:
    """12-hex version stamp of the scoring formula. Consensus-accuracy samples
    are segmented by this hash — changing any weight starts a fresh sample
    (era discipline: never blend evidence across a formula change)."""
    import hashlib
    core = {"w_status": W_STATUS, "shrink_n": SHRINK_N,
            "conf_scale": CONF_SCALE,
            "blend": [BROKER_W, ERA_W, FORM_W],
            "broker_shrink_n": BROKER_SHRINK_N, "r_pips": R_PIPS,
            "strike_discount": STRIKE_DISCOUNT,
            "exc": [EXC_TILT_W, EXC_MIN_N],
            "live_s": LIVE_S}
    return hashlib.sha256(
        json.dumps(core, sort_keys=True).encode()).hexdigest()[:12]


def _shrink(x, n) -> Optional[float]:
    if x is None or not n:
        return None
    return float(x) * float(n) / (float(n) + SHRINK_N)


def evidence_pips(form: dict, broker: Optional[dict] = None) -> float:
    """Blend of broker truth (0.5), shrunk era mean (0.3) and shrunk 7d form
    (0.2), renormalized over whichever parts exist; 0.0 with no sample.
    Broker truth = the governor's 21d trust score — a decayed mean of REAL
    completed family cycles in R — × 60p, shrunk by cycle count. Real fills
    outrank the simulator (truth-layers doctrine), so a seat that has
    actually banked cycles (USD_JPY atr5m class) out-scores any sim-only
    record; era-clocked like everything else (fresh gear = fresh cycles)."""
    parts = []
    if broker and broker.get("n_cycles") and broker.get("trust") is not None:
        n = float(broker["n_cycles"])
        parts.append((BROKER_W, float(broker["trust"]) * R_PIPS
                      * n / (n + BROKER_SHRINK_N)))
    e = _shrink(form.get("era_avg"), form.get("era_n"))
    if e is not None:
        parts.append((ERA_W, e))
    f = _shrink(form.get("form7"), form.get("n7"))
    if f is not None:
        parts.append((FORM_W, f))
    if not parts:
        return 0.0
    wsum = sum(w for w, _ in parts)
    return sum(w * v for w, v in parts) / wsum


def _fmt_hold(minutes) -> Optional[str]:
    if minutes is None:
        return None
    m = float(minutes)
    if m < 90:
        return "~%dm" % round(m)
    return "~%.1fh" % (m / 60.0)


def aggregate(live: dict, forms: dict, holds: dict, strikes: dict,
              now: datetime, heats: Optional[dict] = None) -> list:
    """Per-pair groups, sorted by confidence desc then pair."""
    heats = heats or {}
    by_pair: dict = {}
    for (pair, sess, setup, side), rec in live.items():
        fkey = "%s|%s|%s" % (pair, sess, setup)
        form = forms.get(fkey) or {}
        ht = heats.get(fkey) or {}
        ev = evidence_pips(form, ht)
        n_strikes = int(strikes.get(fkey, 0) or 0)
        w = W_STATUS.get(rec.get("status"), 0.10) * (STRIKE_DISCOUNT ** n_strikes)
        hold = holds.get(fkey) or {}
        exc_mult, tilt = excursion_mult(ev, hold)
        c = w * ev * exc_mult
        signed = c if side == "long" else -c
        by_pair.setdefault(pair, []).append({
            "setup_id": setup,
            "session": sess,
            "side": side,
            "status": rec.get("status"),
            "age_min": round((now - rec["last"]).total_seconds() / 60.0, 1),
            "on_air_min": round((now - rec["run_start"]).total_seconds() / 60.0, 1),
            "n_run": rec.get("n_run", 0),
            "evidence_pips": round(ev, 2),
            "contribution": round(signed, 2),
            "era_avg": form.get("era_avg"), "era_n": form.get("era_n"),
            "form7": form.get("form7"), "n7": form.get("n7"),
            "strikes": n_strikes,
            "n_cycles": ht.get("n_cycles", 0),
            "trust": ht.get("trust"),
            "hold_med_min": hold.get("hold_med_min"),
            "hold_n": hold.get("hold_n", 0),
            "mfe_med": hold.get("mfe_med"),
            "mae_med": hold.get("mae_med"),
            "exc_n": hold.get("exc_n", 0),
            "exc_mult": round(exc_mult, 2),
            "tilt": tilt,
            "horizon_min": rec.get("horizon_min"),
            "trigger_pips": rec.get("trigger_pips"),
            "sl_pips": rec.get("sl_pips"),
            "spread": rec.get("spread"),
            "last_ts": rec["last"].isoformat(),
        })

    out = []
    for pair, sigs in by_pair.items():
        net = sum(s["contribution"] for s in sigs)
        gross = sum(abs(s["contribution"]) for s in sigs)
        direction = "LONG" if net > 0 else ("SHORT" if net < 0 else "FLAT")
        agreement = (abs(net) / gross) if gross > 0 else 0.0
        confidence = round(100.0 * math.tanh(abs(net) / CONF_SCALE)
                           * (0.5 + 0.5 * agreement))
        # aligned = contributors actually pushing the net direction
        aligned = [s for s in sigs if s["contribution"] * net > 0] if net else []
        wsum = sum(abs(s["contribution"]) for s in aligned)
        distance = (sum(abs(s["contribution"]) * abs(s["evidence_pips"])
                        for s in aligned) / wsum) if wsum > 0 else 0.0
        exc = [(abs(s["contribution"]),
                s["mfe_med"] if s["evidence_pips"] > 0 else s["mae_med"],
                s["mae_med"] if s["evidence_pips"] > 0 else s["mfe_med"])
               for s in aligned
               if s["mfe_med"] is not None and s["mae_med"] is not None]
        xw = sum(w for w, _, _ in exc)
        target = (sum(w * f for w, f, _ in exc) / xw) if xw > 0 else None
        heat_px = (sum(w * a for w, _, a in exc) / xw) if xw > 0 else None
        held = [(abs(s["contribution"]),
                 s["hold_med_min"] if s["hold_med_min"] is not None
                 else s["horizon_min"])
                for s in aligned
                if (s["hold_med_min"] is not None
                    or s["horizon_min"] is not None)]
        hw = sum(w for w, _ in held)
        hold_min = (sum(w * h for w, h in held) / hw) if hw > 0 else None
        counts: dict = {}
        for s in sigs:
            counts[s["status"]] = counts.get(s["status"], 0) + 1
        on_air = min((s["on_air_min"] for s in aligned), default=None) if aligned \
            else min((s["on_air_min"] for s in sigs), default=None)
        sigs.sort(key=lambda s: -abs(s["contribution"]))
        out.append({
            "pair": pair,
            "direction": direction,
            "confidence": confidence,
            "net": round(net, 2),
            "gross": round(gross, 2),
            "agreement": round(agreement, 2),
            "distance_pips": round(distance, 1),
            "target_pips": round(target, 1) if target is not None else None,
            "heat_pips": round(heat_px, 1) if heat_px is not None else None,
            "hold_min": round(hold_min, 1) if hold_min is not None else None,
            "hold_label": _fmt_hold(hold_min),
            "on_air_min": on_air,
            "counts": counts,
            "signals": sigs,
        })
    out.sort(key=lambda p: (-p["confidence"], -p["gross"], p["pair"]))
    return out


def build_center(now: Optional[datetime] = None,
                 lines: Optional[list] = None) -> dict:
    """Full rebuild — journal parse + evidence joins + aggregation."""
    now = now or datetime.now(timezone.utc)
    lines = _read_journal_lines() if lines is None else lines
    reg = build_registry(lines)
    live = live_signals(reg, now)
    from core.execution_score import load_chamber_form, load_heat_scores
    pairs = aggregate(live, load_chamber_form(), hold_stats(), _strikes(), now,
                      heats=load_heat_scores())
    return {
        "generated_at": now.isoformat(),
        "journal_hours": JOURNAL_HOURS,
        "scan_interval_s": SCAN_S,
        "live_window_s": LIVE_S,
        "totals": {
            "live_signals": sum(len(p["signals"]) for p in pairs),
            "pairs_live": len(pairs),
            "tracked_48h": len(reg),
        },
        "formula_hash": formula_hash(),
        "weights": {"status": W_STATUS, "shrink_n": SHRINK_N,
                    "conf_scale": CONF_SCALE,
                    "blend": {"broker": BROKER_W, "era": ERA_W, "form7": FORM_W},
                    "strike_discount": STRIKE_DISCOUNT,
                    "exc_tilt_w": EXC_TILT_W, "exc_min_n": EXC_MIN_N},
        "pairs": pairs,
    }


def _refresh_worker():
    try:
        data = build_center()
        with _LOCK:
            _CACHE["ts"] = time.time()
            _CACHE["data"] = data
    except Exception as exc:                      # noqa: BLE001
        import logging
        logging.getLogger("v5.signal_center").warning(
            "signal_center refresh failed: %s", exc)
    finally:
        with _LOCK:
            _LATCH["t"] = 0.0


def get_center() -> dict:
    """Cache-only accessor for the single-threaded dashboard server: returns
    the latest build immediately and kicks a background refresh when stale.
    First-ever call returns a 'building' placeholder."""
    with _LOCK:
        fresh = (time.time() - _CACHE["ts"]) < _REFRESH_S
        data = _CACHE["data"]
        latch_free = (time.time() - _LATCH["t"]) > _LATCH_TIMEOUT_S
        if (not fresh) and latch_free:
            _LATCH["t"] = time.time()
            threading.Thread(target=_refresh_worker, daemon=True,
                             name="signal-center-refresh").start()
    if data is not None:
        return data
    return {"building": True,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "totals": {"live_signals": 0, "pairs_live": 0, "tracked_48h": 0},
            "pairs": []}
