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
  evidence_pips     = 0.6·shrink(era_avg, era_n) + 0.4·shrink(form7, n7)
                      (renormalized when a part is missing; 0 when no sample)
  contribution      = status_weight × evidence_pips  (ACTIVE 1.0 / PROBE 0.6 /
                      SHADOW 0.25 / SUSPENDED 0.10)
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
    """'PAIR|sess|setup' -> {hold_med_min, hold_n} from scored, non-censored
    v2 episodes (exit_bar × 5). mtime-cached — the store is ~15MB and rewritten
    every 15 min; parse at most once per rewrite, and only ever from the
    refresh thread."""
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
        for ep in eps.values():
            if not isinstance(ep, dict) or ep.get("mv") != 2:
                continue
            sc = ep.get("scores") or {}
            if sc.get("censored") or sc.get("exit_reason") in (None, "horizon"):
                continue
            xb = sc.get("exit_bar")
            if not isinstance(xb, (int, float)) or xb <= 0:
                continue
            key = "%s|%s" % ((ep.get("cell") or "?/?").replace("/", "|"),
                             ep.get("setup"))
            bars.setdefault(key, []).append(float(xb) * 5.0)
        for key, mins in bars.items():
            holds[key] = {"hold_med_min": round(statistics.median(mins), 1),
                          "hold_n": len(mins)}
    except (OSError, ValueError, MemoryError):
        return _HOLD_CACHE["holds"] or {}
    _HOLD_CACHE["mtime"] = m
    _HOLD_CACHE["holds"] = holds
    return holds


def _strikes() -> dict:
    try:
        g = json.loads(_GOV_STATE.read_text())
        return dict(g.get("demotion_counts") or {})
    except (OSError, ValueError):
        return {}


def _shrink(x, n) -> Optional[float]:
    if x is None or not n:
        return None
    return float(x) * float(n) / (float(n) + SHRINK_N)


def evidence_pips(form: dict) -> float:
    """Blend of shrunk era mean (0.6) and shrunk 7d form (0.4), renormalized
    over whichever parts exist. 0.0 when the setup has no sample at all."""
    parts = []
    e = _shrink(form.get("era_avg"), form.get("era_n"))
    if e is not None:
        parts.append((0.6, e))
    f = _shrink(form.get("form7"), form.get("n7"))
    if f is not None:
        parts.append((0.4, f))
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
              now: datetime) -> list:
    """Per-pair groups, sorted by confidence desc then pair."""
    by_pair: dict = {}
    for (pair, sess, setup, side), rec in live.items():
        fkey = "%s|%s|%s" % (pair, sess, setup)
        form = forms.get(fkey) or {}
        ev = evidence_pips(form)
        w = W_STATUS.get(rec.get("status"), 0.10)
        c = w * ev
        signed = c if side == "long" else -c
        hold = holds.get(fkey) or {}
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
            "strikes": strikes.get(fkey, 0),
            "hold_med_min": hold.get("hold_med_min"),
            "hold_n": hold.get("hold_n", 0),
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
    from core.execution_score import load_chamber_form
    pairs = aggregate(live, load_chamber_form(), hold_stats(), _strikes(), now)
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
        "weights": {"status": W_STATUS, "shrink_n": SHRINK_N,
                    "conf_scale": CONF_SCALE, "era_w": 0.6, "form7_w": 0.4},
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
