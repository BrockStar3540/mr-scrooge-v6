"""ops/server.py — V5 control panel HTTP server.

Routes:
  GET /                    → ops/panel.html
  GET /api/state           → live engine state JSON (positions, tickets, views, governance, last_trade_ticket, engine_info)
  GET /api/sysinfo         → system metrics JSON (CPU, RAM, services, logs)
  GET /api/daily_pl        → today's realized P/L from OANDA (cached 30s)
  GET /api/cells           → cell book: config/cells/*.json + live condition values (fresh each call)
  GET /api/cellshadow?n=200→ recent CELLSHADOW journal stamps, newest first (cached 30s)
  GET /api/cellscore       → cell_setup_score.py --json scoreboard (cached 300s)
  GET /api/config/exit     → exit-tuning config + field schema
  GET /api/config/playmaker→ playmaker config + field schema
  POST /api/config/exit    → live edit exit_config.json (validated)
  POST /api/config/playmaker→ live edit playmaker_config.json (validated)

Start via start_dashboard(engine, port=8084) from main.py — runs in daemon thread.
"""
from __future__ import annotations
import http.server
import json as _j
import logging
import re
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.engine import Engine

log = logging.getLogger("v5.dashboard")

_PANEL = Path(__file__).resolve().parent / "panel.html"

# ── Exit-tuning config (TUNE tab) ───────────────────────────────────────────
from pathlib import Path as _Path
_EXIT_CONFIG_PATH = _Path("/home/ubuntu/mr-scrooge-v5/config/exit_config.json")

_EXIT_FIELDS = {
    "initial_sl_pips":   {"min": 1.0,  "max": 100.0, "label": "Initial SL (pips)"},
    "step_engage_min":   {"min": 0.0,  "max": 240.0, "label": "Engage delay (min)"},
    "step_cadence_min":  {"min": 0.1,  "max": 60.0,  "label": "Cadence (min)"},
    "step_trigger_pips": {"min": 0.5,  "max": 100.0, "label": "TP1 trigger (peak pips)"},
    "step_trail_pips":   {"min": 0.1,  "max": 100.0, "label": "Trail behind level (pips)"},
    "step_size_pips":    {"min": 0.5,  "max": 50.0,  "label": "Rung spacing (pips)"},
}
# TP1/TP2 fields. bools use kind=bool; percentages 0..1.
_EXIT_FIELDS_TP = {
    "tp1_enabled":   {"kind": "bool",                "label": "TP1 on"},
    "tp1_at_pips":   {"min": 0.5,  "max": 200.0,     "label": "TP1 peak (pips)"},
    "tp1_close_pct": {"min": 0.0,  "max": 0.95,      "label": "TP1 close %"},
    "tp1_lock_pips": {"min": 0.0,  "max": 100.0,     "label": "TP1 SL lock (pips)"},
    "tp2_enabled":   {"kind": "bool",                "label": "TP2 on"},
    "tp2_at_pips":   {"min": 0.5,  "max": 300.0,     "label": "TP2 peak (pips)"},
    "tp2_close_pct": {"min": 0.0,  "max": 0.95,      "label": "TP2 close %"},
}
_EXIT_FIELDS.update(_EXIT_FIELDS_TP)
_PAIRS_ALL = ["AUD_JPY","AUD_USD","EUR_JPY","EUR_USD","GBP_USD","USD_CAD","USD_CHF","USD_JPY"]

def _read_exit_config() -> dict:
    try:
        return _j.loads(_EXIT_CONFIG_PATH.read_text())
    except Exception as exc:
        return {"schema": "v2", "defaults": {}, "per_pair": {}, "_error": str(exc)}

def _validate_exit_field(k: str, v):
    if k not in _EXIT_FIELDS:
        raise ValueError(f"unknown field: {k}")
    spec = _EXIT_FIELDS[k]
    if spec.get("kind") == "bool":
        if isinstance(v, bool): return v
        if isinstance(v, (int, float)): return bool(v)
        if isinstance(v, str): return v.strip().lower() in ("1","true","yes","on")
        raise ValueError(f"{k}: expected bool, got {type(v).__name__}")
    f = float(v)
    if not (spec["min"] <= f <= spec["max"]):
        raise ValueError(f"{k}={f} out of bounds [{spec['min']}, {spec['max']}]")
    return f

def _check_tp_cross_rules(merged: dict) -> None:
    """Cross-field validation for TP1/TP2 on the merged effective view."""
    t1e = bool(merged.get("tp1_enabled", False))
    t2e = bool(merged.get("tp2_enabled", False))
    if t2e and not t1e:
        raise ValueError("tp2_enabled requires tp1_enabled (TP2 only fires after TP1)")
    t1p = merged.get("tp1_close_pct"); t2p = merged.get("tp2_close_pct")
    if t1p is not None and t2p is not None and (t1p + t2p) >= 1.0:
        raise ValueError(f"tp1_close_pct + tp2_close_pct = {t1p+t2p:.2f} >= 1.0 (runner must remain)")
    t1at = merged.get("tp1_at_pips"); t2at = merged.get("tp2_at_pips")
    if t1at is not None and t2at is not None and t2at <= t1at:
        raise ValueError(f"tp2_at_pips ({t2at}) must be > tp1_at_pips ({t1at})")

def _validate_exit_cfg(cfg: dict) -> dict:
    out = {"schema": "v2", "defaults": {}, "per_pair": {}}
    defaults = cfg.get("defaults") or {}
    for k in _EXIT_FIELDS:
        if k in defaults:
            out["defaults"][k] = _validate_exit_field(k, defaults[k])
    if "step_trail_pips" in out["defaults"] and "step_trigger_pips" in out["defaults"]:
        if out["defaults"]["step_trail_pips"] >= out["defaults"]["step_trigger_pips"]:
            raise ValueError("defaults: step_trail_pips must be < step_trigger_pips (else first lock <= 0)")
    _check_tp_cross_rules(out["defaults"])
    per = cfg.get("per_pair") or {}
    for pair, ov in per.items():
        if pair not in _PAIRS_ALL:
            raise ValueError(f"unknown pair: {pair}")
        clean = {}
        for k, v in (ov or {}).items():
            clean[k] = _validate_exit_field(k, v)
        merged_trig  = clean.get("step_trigger_pips", out["defaults"].get("step_trigger_pips"))
        merged_trail = clean.get("step_trail_pips",   out["defaults"].get("step_trail_pips"))
        if merged_trig is not None and merged_trail is not None and merged_trail >= merged_trig:
            raise ValueError(f"{pair}: step_trail_pips must be < step_trigger_pips")
        merged_eff = {**out["defaults"], **clean}
        try:
            _check_tp_cross_rules(merged_eff)
        except ValueError as exc:
            raise ValueError(f"{pair}: {exc}") from None
        if clean:
            out["per_pair"][pair] = clean
    return out



# ── Playmaker config (PLAYMAKER tab) ────────────────────────────────────────
_PM_CONFIG_PATH = _Path("/home/ubuntu/mr-scrooge-v5/config/playmaker_config.json")

_PM_FIELDS = {
    "enabled":             {"kind": "bool",                 "label": "Enabled"},
    "min_direction_score": {"min": 0.0,  "max": 1.0,        "label": "Min |direction.score|"},
    "min_dir_certainty":   {"min": 0.0,  "max": 1.0,        "label": "Min direction.certainty"},
    "min_mom_certainty":   {"min": 0.0,  "max": 1.0,        "label": "Min momentum.certainty"},
    "cooldown_after_sl_min": {"min": 0.0, "max": 1440.0,    "label": "Cooldown after losing exit (min)"},
}
_PM_ACCT_FIELDS = {
    "margin_pct_per_trade":  {"min": 0.001, "max": 1.0,  "label": "Margin per trade (fraction of balance)"},
    "max_concurrent_trades": {"min": 1,     "max": 20,   "label": "Max concurrent trades", "int": True},
}
_PM_LEGACY_ACCT_KEYS = {"risk_pct_per_trade": "margin_pct_per_trade"}

def _read_playmaker_config() -> dict:
    try:
        return _j.loads(_PM_CONFIG_PATH.read_text())
    except Exception as exc:
        return {"schema": "v1", "account": {}, "defaults": {}, "per_pair": {}, "_error": str(exc)}

def _validate_pm_field(table: dict, k: str, v):
    if k not in table:
        raise ValueError(f"unknown field: {k}")
    spec = table[k]
    if spec.get("kind") == "bool":
        if isinstance(v, bool): return v
        if isinstance(v, (int, float)): return bool(v)
        if isinstance(v, str): return v.strip().lower() in ("1","true","yes","on")
        raise ValueError(f"{k}: expected bool")
    f = float(v)
    if not (spec["min"] <= f <= spec["max"]):
        raise ValueError(f"{k}={f} out of bounds [{spec['min']}, {spec['max']}]")
    return int(f) if spec.get("int") else f

def _validate_pm_cfg(cfg: dict) -> dict:
    out = {"schema": "v1", "account": {}, "defaults": {}, "per_pair": {}}
    for k, v in (cfg.get("account") or {}).items():
        k = _PM_LEGACY_ACCT_KEYS.get(k, k)   # back-compat rename
        out["account"][k] = _validate_pm_field(_PM_ACCT_FIELDS, k, v)
    for k, v in (cfg.get("defaults") or {}).items():
        out["defaults"][k] = _validate_pm_field(_PM_FIELDS, k, v)
    for pair, ov in (cfg.get("per_pair") or {}).items():
        if pair not in _PAIRS_ALL:
            raise ValueError(f"unknown pair: {pair}")
        clean = {}
        for k, v in (ov or {}).items():
            clean[k] = _validate_pm_field(_PM_FIELDS, k, v)
        if clean:
            out["per_pair"][pair] = clean
    return out

def _write_playmaker_config(cfg: dict) -> None:
    clean = _validate_pm_cfg(cfg)
    clean["_note"] = "Edited via dashboard PLAYMAKER tab."
    tmp = _PM_CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(_j.dumps(clean, indent=2))
    tmp.replace(_PM_CONFIG_PATH)

def _write_exit_config(cfg: dict) -> None:
    clean = _validate_exit_cfg(cfg)
    clean["_note"] = ("Nested schema v2. Edited via dashboard TUNE tab. "
                      "Per-pair fields override defaults for that pair only.")
    tmp = _EXIT_CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(_j.dumps(clean, indent=2))
    tmp.replace(_EXIT_CONFIG_PATH)



def _state(engine: "Engine") -> dict:
    now = datetime.now(timezone.utc)

    # ── Account ──────────────────────────────────────────────────────────────
    account: dict = {}
    try:
        account = engine.broker.account_summary()
    except Exception as exc:
        account = {"error": str(exc)}

    # ── Open positions + ratchet state ───────────────────────────────────────
    open_positions = []
    try:
        oanda_trades = {t["id"]: t for t in engine.broker.open_positions()}
    except Exception:
        oanda_trades = {}

    for pair, mgr in engine.managers.items():
        mid = mgr.position.entry_price  # fallback
        for t in oanda_trades.values():
            if t.get("instrument") == pair:
                mid = (float(t.get("currentUnits", 0)) and
                       float(t.get("unrealizedPL", 0)) / abs(float(t.get("currentUnits", 1)))
                       / (0.0001 if "JPY" not in pair else 0.01))
                break

        elapsed = (now - mgr.position.entry_time).total_seconds() / 60
        # current mid from last views
        for v in (engine.last_views or []):
            if v.pair == pair:
                mid = (v.bid + v.ask) / 2
                break

        oanda_t = oanda_trades.get(mgr.position.oanda_trade_id, {})
        upl = float(oanda_t.get("unrealizedPL", 0)) if oanda_t else None

        # Exit-class info (2026-07-05): how this trade is being managed
        _ep    = getattr(mgr.position, "exit_params", None)
        _mode  = mgr.name() if hasattr(mgr, "name") else "ratchet"
        _tmult = float(getattr(_ep, "trail_mult", 0) or 0) if _ep is not None else 0.0
        _klass = ("FAST" if _mode == "bracket"
                  else "RECOVERED" if _ep is None
                  else "ATR-TRAIL" if _tmult > 0
                  else "FIXED")
        _exit_info = {"exit_mode": _mode, "exit_class": _klass}
        if _mode == "bracket":
            _tp  = float(getattr(mgr, "tp_pips", 0) or 0)
            _tmo = float(getattr(mgr, "timeout_min", 0) or 0)
            _tp_price = None
            if _tp:
                _tp_price = (mgr.position.entry_price + _tp * mgr.position.pip_size
                             if mgr.direction == "long"
                             else mgr.position.entry_price - _tp * mgr.position.pip_size)
            _exit_info.update({
                "tp_pips":          _tp or None,
                "tp_price":         round(_tp_price, 5) if _tp_price else None,
                "timeout_min":      _tmo or None,
                "timeout_left_min": round(max(0.0, _tmo - elapsed), 1) if _tmo else None,
            })
        else:
            if _ep is not None:
                _eng, _trl, _tm = float(getattr(_ep, "trigger_pips", 0) or 0), float(getattr(_ep, "trail_pips", 0) or 0), _tmult
            else:
                # recovered position: no per-cell exit_params -> runs exit_config.json effective gear
                _ec = _read_exit_config()
                _base = _ec.get("defaults", _ec)
                _pp = (_ec.get("per_pair") or {}).get(pair) or {}
                _dfl = {**_base, **_pp}
                _eng, _trl, _tm = float(_dfl.get("step_trigger_pips", 7.5)), float(_dfl.get("step_trail_pips", 2.5)), 0.0
            _exit_info.update({
                "engage_pips": round(_eng, 2),
                "trail_pips":  round(_trl, 2),
                "trail_mult":  _tm or None,
            })

        open_positions.append({
            **_exit_info,
            "pair":          pair,
            "direction":     mgr.direction,
            "entry":         round(mgr.position.entry_price, 5),
            "entry_time":    mgr.position.entry_time.isoformat(),
            "elapsed_min":   round(elapsed, 1),
            "oanda_trade_id": mgr.position.oanda_trade_id,
            "sl_locked_pips": mgr.sl_locked_pips,
            "peak_price":    round(mgr.peak_price, 5),
            "peak_pips":     round(mgr._peak_pips(), 2),
            "sl_price":      round(mgr._sl_pips_to_price(mgr.sl_locked_pips), 5)
                             if mgr.sl_locked_pips is not None else None,
            "net_pips_now":  round(mgr.net_pips(mid), 2),
            "unrealized_pl": round(upl, 2) if upl is not None else None,
        })

    # ── Last tickets (from last engine cycle) ─────────────────────────────────
    # Phase-D hardening (2026-07-04): last_tickets may hold legacy PairTickets
    # (direction/momentum OBJECTS with .bias/.score/.certainty/.reads) OR
    # cell-era TradeTickets built from CellIntents (direction is a plain str,
    # reads={"cell": {...}, "direction": {}, "momentum": {}}, .cell attribute).
    # Every access is defensive so /api/state survives the cutover restart in
    # either world; one malformed ticket degrades to a stub row, never a 500.
    last_tickets = []
    _firstword = lambda s: (s or "?").split()[0]
    def _rnd(v, nd=3, default=None):
        try:
            return round(float(v), nd)
        except (TypeError, ValueError):
            return default
    for t in (engine.last_tickets or []):
        try:
            _dir = getattr(t, "direction", None)
            _mom = getattr(t, "momentum", None)
            _dir_is_obj = _dir is not None and not isinstance(_dir, str)
            _dr = (getattr(_dir, "reads", None) or {}) if _dir_is_obj else {}
            _mr = (getattr(_mom, "reads", None) or {}) if _mom is not None else {}
            if not isinstance(_dr, dict): _dr = {}
            if not isinstance(_mr, dict): _mr = {}
            _treads = getattr(t, "reads", None)
            _treads = _treads if isinstance(_treads, dict) else {}
            _cell_read = _treads.get("cell") if isinstance(_treads.get("cell"), dict) else None
            if not _dr and isinstance(_treads.get("direction"), dict):
                _dr = _treads["direction"]
            if not _mr and isinstance(_treads.get("momentum"), dict):
                _mr = _treads["momentum"]
            _ts = getattr(t, "timestamp", None)
            _bias = (getattr(_dir, "bias", None) if _dir_is_obj else _dir) or "block"
            last_tickets.append({
                "pair":          getattr(t, "pair", "?"),
                "session":       getattr(t, "session", "?"),
                "timestamp":     _ts.isoformat() if hasattr(_ts, "isoformat") else str(_ts),
                "dir_bias":      _bias,
                "dir_score":     _rnd(getattr(_dir, "score", None) if _dir_is_obj
                                      else getattr(t, "score", None), 3, 0.0),
                "dir_certainty": _rnd(getattr(_dir, "certainty", None) if _dir_is_obj
                                      else None, 3, 0.0),
                "vol_regime":    getattr(_mom, "vol_regime", None),
                "expected_pips": _rnd(getattr(_mom, "expected_pips", None) if _mom is not None
                                      else getattr(t, "expected_pips", None), 1, 0.0),
                "mom_certainty": _rnd(getattr(_mom, "certainty", None), 3, 0.0),
                "spread_pips":   _rnd(getattr(t, "spread_pips", None), 2, 0.0),
                "composite":     _rnd(getattr(t, "composite_score", None), 3, 0.0),
                "actionable":    bool(getattr(t, "is_actionable", False)),
                # ── v2/v3 profile fields (None-safe on cell-era tickets) ────
                "active_side":    _dr.get("active_side"),
                "long_profile":   _firstword(_dr.get("long_profile")),
                "short_profile":  _firstword(_dr.get("short_profile")),
                "long_score":     _dr.get("long_score"),
                "short_score":    _dr.get("short_score"),
                "agreement":      _dr.get("agreement"),
                "mom_profile":    _firstword(_mr.get("profile")),
                "gates_passed":   _mr.get("gates_passed"),
                "cert_boost":     _mr.get("cert_boost"),
                "profile_reasons":_mr.get("profile_reasons"),
                # ── Phase-D cell fields (None on legacy tickets) ────────────
                "cell":          _cell_read,
                "setup_id":      ((_cell_read or {}).get("setup_id")
                                  or getattr(getattr(t, "cell", None), "setup_id", None)),
            })
        except Exception as _texc:
            last_tickets.append({"pair": getattr(t, "pair", "?"),
                                 "session": getattr(t, "session", "?"),
                                 "dir_bias": "block", "dir_score": 0.0,
                                 "dir_certainty": 0.0, "mom_certainty": 0.0,
                                 "actionable": False,
                                 "error": str(_texc)})

    # ── Last market views (for market-feature chips) ─────────────────────────
    last_views = []
    for v in (engine.last_views or []):
        last_views.append({
            "pair":        v.pair,
            "session":     v.session,
            "bid":         round(v.bid, 5) if hasattr(v, "bid") else None,
            "ask":         round(v.ask, 5) if hasattr(v, "ask") else None,
            "spread_pips": round(v.spread_pips, 2) if hasattr(v, "spread_pips") else None,
            "rsi14":       round(v.rsi14, 1) if hasattr(v, "rsi14") else None,
            "rsi_slope":   round(v.rsi_slope, 2) if hasattr(v, "rsi_slope") else None,
            "h1_ret_1bar": round(v.h1_ret_1bar, 1) if hasattr(v, "h1_ret_1bar") else None,
            "h1_ret_4bar": round(v.h1_ret_4bar, 1) if hasattr(v, "h1_ret_4bar") else None,
            "adr_consumed":round(v.adr_consumed, 2) if hasattr(v, "adr_consumed") else None,
            "htf_pct_20":  round(v.htf_pct_20, 3) if hasattr(v, "htf_pct_20") else None,
            "htf_pct_60":  round(v.htf_pct_60, 3) if hasattr(v, "htf_pct_60") else None,
            "pdh_dist":    round(v.pdh_dist, 1) if hasattr(v, "pdh_dist") else None,
            "pdl_dist":    round(v.pdl_dist, 1) if hasattr(v, "pdl_dist") else None,
            "atr_h1_relative": round(v.atr_h1_relative, 3) if hasattr(v, "atr_h1_relative") else None,
            "trend_4h":    int(v.trend_4h) if hasattr(v, "trend_4h") else None,
            "vortex_diff_h1": round(v.vortex_diff_h1, 4) if hasattr(v, "vortex_diff_h1") else None,
            "atr_conc":    round(v.atr_conc, 3) if hasattr(v, "atr_conc") else None,
            # 2026-06-23: 4 matrix shadow features + close_pos_daily
            "close_pos_daily": round(v.close_pos_daily, 3) if hasattr(v, "close_pos_daily") else None,
            "willr_m5":        round(v.willr_m5, 1) if hasattr(v, "willr_m5") else None,
            "aroonosc_h1":     round(v.aroonosc_h1, 1) if hasattr(v, "aroonosc_h1") else None,
            "kc_up_dist_pips": round(v.kc_up_dist_pips, 2) if hasattr(v, "kc_up_dist_pips") else None,
            "efi":             round(v.efi, 4) if hasattr(v, "efi") else None,
            "atr_5m":          round(v.atr_5m, 2) if hasattr(v, "atr_5m") else None,
            "atr_1h":          round(v.atr_1h, 1) if hasattr(v, "atr_1h") else None,
            "rvol_5bar":       round(v.rvol_5bar, 2) if hasattr(v, "rvol_5bar") else None,
        })

    # ── Per-cell governance (NEW 2026-06-23: visibility for disabled/inverted/per-cell rules) ──
    governance = {}
    try:
        from modules.playmaker.playmaker import _pm_load
        _pm = _pm_load()
        governance = {
            "disabled_cells":          sorted([list(x) for x in _pm.get("disabled_cells", set())]),
            "inverted_live_cells":     sorted([list(x) for x in _pm.get("inverted_live_cells", set())]),
            "inverted_shadow_cells":   sorted([list(x) for x in _pm.get("inverted_shadow_cells", set())]),
            "per_cell_mom_cert_max":   {"/".join(k): v for k, v in _pm.get("per_cell_mom_cert_max", {}).items()},
            "per_cell_mom_cert_min":   {"/".join(k): v for k, v in _pm.get("per_cell_mom_cert_min", {}).items()},
            "per_cell_dir_cert_min":   {"/".join(k): v for k, v in _pm.get("per_cell_dir_cert_min", {}).items()},
            "per_cell_dir_cert_max":   {"/".join(k): v for k, v in _pm.get("per_cell_dir_cert_max", {}).items()},
            "per_cell_willr_range":    {"/".join(k): list(v) for k, v in _pm.get("per_cell_willr_range", {}).items()},
            "per_cell_kc_up_range":    {"/".join(k): list(v) for k, v in _pm.get("per_cell_kc_up_range", {}).items()},
            "random_pick":             bool(_pm.get("random_pick", False)),
            "defaults":                _pm.get("defaults", {}),
            "account":                 _pm.get("account", {}),
        }
    except Exception as exc:
        governance = {"error": str(exc)}

    # ── Last trade ticket (with new fields) ──
    last_trade_ticket = None
    if engine.last_trade_ticket is not None:
        ltt = engine.last_trade_ticket
        _ltt_reads = getattr(ltt, "reads", None)
        _ltt_reads = _ltt_reads if isinstance(_ltt_reads, dict) else {}
        _ltt_ts = getattr(ltt, "timestamp", None)
        _ltt_dir = getattr(ltt, "direction", None)
        _ltt_cell = _ltt_reads.get("cell") if isinstance(_ltt_reads.get("cell"), dict) else None
        last_trade_ticket = {
            "pair":           getattr(ltt, "pair", "?"),
            "session":        getattr(ltt, "session", "?"),
            "direction":      _ltt_dir or "?",
            "score":          getattr(ltt, "score", None),
            "expected_pips":  getattr(ltt, "expected_pips", None),
            "timestamp":      _ltt_ts.isoformat() if hasattr(_ltt_ts, "isoformat") else str(_ltt_ts),
            "inverted_live":  getattr(ltt, "inverted_live", False),
            "pick_method":    _ltt_reads.get("pick_method", "edge_rank"),
            "signal_direction": _ltt_reads.get("signal_direction", _ltt_dir),
            "cell":           _ltt_cell,
            "setup_id":       ((_ltt_cell or {}).get("setup_id")
                               or getattr(getattr(ltt, "cell", None), "setup_id", None)),
        }

    # ── Engine cycle intervals (V5 main.py: scan=300s, manage=5s as of 2026-06-23) ──
    # NOTE: engine doesn't store these as attributes; reading from main.py would
    # be brittle. Surfaced as info-only; if changed in main.py, update here.
    engine_info = {
        "scan_interval_seconds":   300,
        "manage_interval_seconds": 5,
    }

    # ── Per-currency directional exposure (RISK_CAP inputs, cheap) ────────────
    # 2026-07-02 panel-unanimous cap: pick_best blocks a candidate when any single
    # (currency, sign) exposure would exceed max_per_currency_direction. Surface
    # the live map so the dashboard shows what the cap is counting.
    try:
        from modules.playmaker.playmaker import (currency_exposure as _ccy_exp_fn,
                                                 pm_max_per_currency_direction as _ccy_cap_fn)
        _ccy_exp = _ccy_exp_fn([(p, m.direction) for p, m in engine.managers.items()])
        engine_info["currency_exposure"] = {f"{_c}/{_s}": _n
                                            for (_c, _s), _n in sorted(_ccy_exp.items())}
        engine_info["max_per_currency_direction"] = _ccy_cap_fn()
    except Exception as _exc:
        engine_info["currency_exposure"] = {"error": str(_exc)}

    # ── Lock guard status (read-only, cheap) ────────────────────────────────────
    lock_guard_status = []
    try:
        from modules.playmaker import lock_guard as _lg
        _lg_data = _lg._load()
        if _lg_data:
            for _lc in _lg_data.get("cells", []):
                _pair    = _lc.get("pair")
                _session = _lc.get("session")
                _dir     = _lc.get("dir")
                _snap    = _lc.get("snapshot")
                _has_snap = _snap is not None
                # code_fingerprint_ok: True if stored fp matches live fp, else False; None if no snapshot
                _fp_ok = None
                if _has_snap:
                    _lg_status = getattr(engine, "_lock_guard_status", {})
                    _fp_ok = _lg_status.get((_pair, _session), None)
                # opens this session for this locked traded direction
                _opens = 0
                if now is not None and _pair and _session:
                    _inst = _lg.session_instance_key(_session, now)
                    _opens = getattr(engine, "_cell_opens", {}).get(
                        f"{_pair}|{_session}|{_dir}|{_inst}", 0
                    )
                _cap = _lg.throttle_cap(_pair, _session) if (_pair and _session) else None
                lock_guard_status.append({
                    "cell":                 f"{_pair}/{_session}/{_dir}",
                    "has_snapshot":         _has_snap,
                    "code_fingerprint_ok":  _fp_ok,
                    "opens_this_session":   _opens,
                    "throttle_cap":         _cap,
                })
    except Exception as _exc:
        lock_guard_status = [{"error": str(_exc)}]

    from modules.management.base import in_rollover_freeze as _irf
    return {
        "account":         account,
        "rollover_freeze": _irf(now),
        "open_positions":  open_positions,
        "last_tickets":    last_tickets,
        "last_views":      last_views,
        "last_trade_ticket": last_trade_ticket,
        "recent_events":   list(engine.recent_events),
        "cycle_count":     engine.cycle_count,
        "last_cycle_time": engine.last_cycle_time.isoformat() if engine.last_cycle_time else None,
        "dry_run":         engine.dry_run,
        "server_time":     now.isoformat(),
        "governance":      governance,
        "engine":          engine_info,
        "lock_guard":      lock_guard_status,
    }


# ── Daily P/L (NEW 2026-06-23) ────────────────────────────────────────────────
_DAILY_PL_CACHE = {"ts": 0, "data": None}

def _daily_pl(engine: "Engine") -> dict:
    """Query OANDA for today's closed-trade realized P/L (UTC day boundary).
    Cached for 30s to avoid hammering the API on dashboard polls."""
    import time, urllib.parse
    if time.time() - _DAILY_PL_CACHE["ts"] < 30 and _DAILY_PL_CACHE["data"]:
        return _DAILY_PL_CACHE["data"]
    try:
        broker = engine.broker
        token = getattr(broker, "_token", None) or getattr(broker, "token", None)
        base  = getattr(broker, "_base", None) or getattr(broker, "base", None)
        acct  = (getattr(broker, "_acct", None) or getattr(broker, "_account_id", None)
                 or getattr(broker, "account_id", None))
        if not (token and base and acct):
            return {"error": "broker creds not exposed (looked for _token/_base/_acct)"}
        import urllib.request
        from_ts = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat().replace("+00:00","Z")
        url = (f"{base}/v3/accounts/{acct}/transactions?"
               + urllib.parse.urlencode({"from": from_ts, "type": "ORDER_FILL"}))
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=10) as r:
            page = _j.loads(r.read())
        pages = page.get("pages", [])
        # Walk pages; each page is a URL we GET to fetch transactions
        all_tx = []
        for p_url in pages:
            req = urllib.request.Request(p_url, headers={"Authorization": f"Bearer {token}"})
            with urllib.request.urlopen(req, timeout=10) as r:
                d = _j.loads(r.read())
            all_tx.extend(d.get("transactions", []))
        # If pages empty, transactions may be in page['lastTransactionID'] flow — fallback: sinceID
        if not all_tx and page.get("transactions"):
            all_tx = page["transactions"]
        realized = 0.0; n_wins = 0; n_losses = 0; n_trades = 0
        per_pair = {}
        per_cell = {}     # NEW: keyed by "PAIR/session/dir"
        finance = 0.0
        trades = []       # NEW: detailed list for the Today's Trades table
        def _sess_of(h):
            if 7 <= h < 13: return "london"
            if 13 <= h < 22: return "ny"
            return "asia"
        for tx in all_tx:
            if tx.get("type") != "ORDER_FILL":  continue
            pl = float(tx.get("pl", 0) or 0)
            fin = float(tx.get("financing", 0) or 0)
            instr = tx.get("instrument", "?")
            if pl == 0 and fin == 0:  continue
            realized += pl; finance += fin
            if pl > 0:   n_wins += 1
            elif pl < 0: n_losses += 1
            if pl != 0: n_trades += 1
            per_pair.setdefault(instr, {"pl": 0.0, "n": 0, "wins": 0})
            per_pair[instr]["pl"] += pl
            per_pair[instr]["n"]  += 1
            if pl > 0: per_pair[instr]["wins"] += 1
            # Per-cell aggregation: derive (session, direction) from transaction
            ts_raw = tx.get("time", "")
            try:
                _t = datetime.fromisoformat(ts_raw.replace("Z","+00:00"))
                _sess = _sess_of(_t.hour)
            except Exception:
                _t = None; _sess = "?"
            units = float(tx.get("units", 0) or 0)
            _dir = "short" if units < 0 else "long"   # close transaction has opposite-signed units of the trade direction... but ORDER_FILL with pl > 0 is the close. We need open units.
            # OANDA: ORDER_FILL with tradesClosed has the close. tradeOpened is the open.
            # Heuristic: use the sign of 'units' field on the fill. For market-order trades, the close-fill 'units' sign is OPPOSITE to the open. We want the OPEN direction.
            # Simpler: check tradesClosed[].units (the trade's original units sign) if present.
            tc = tx.get("tradesClosed", [])
            if tc and isinstance(tc, list):
                try:
                    open_units = float(tc[0].get("units", 0) or 0)
                    # tradesClosed units is the units BEING closed (signed same as original trade direction)
                    _dir = "long" if open_units > 0 else "short"
                except Exception:
                    pass
            cell_key = f"{instr}/{_sess}/{_dir}"
            per_cell.setdefault(cell_key, {"pl": 0.0, "n": 0, "wins": 0})
            per_cell[cell_key]["pl"] += pl
            per_cell[cell_key]["n"]  += 1
            if pl > 0: per_cell[cell_key]["wins"] += 1
            trades.append({
                "time":     ts_raw,
                "pair":     instr,
                "session":  _sess,
                "dir":      _dir,
                "units":    int(units),
                "price":    float(tx.get("price", 0) or 0),
                "pl_usd":   round(pl, 2),
                "fin_usd":  round(fin, 4),
                "trade_id": tx.get("orderID") or tx.get("tradeID") or "?",
            })
        result = {
            "realized_usd":   round(realized, 2),
            "financing_usd":  round(finance, 4),
            "net_usd":        round(realized + finance, 2),
            "n_trades":       n_trades,
            "n_wins":         n_wins,
            "n_losses":       n_losses,
            "wr_pct":         round(100 * n_wins / n_trades, 1) if n_trades else None,
            "per_pair":       {k: {"pl": round(v["pl"], 2), "n": v["n"], "wins": v["wins"]} for k, v in per_pair.items()},
            "per_cell":       {k: {"pl": round(v["pl"], 2), "n": v["n"], "wins": v["wins"]} for k, v in per_cell.items()},
            "trades":         sorted(trades, key=lambda t: t["time"], reverse=True),
            "since":          from_ts,
            "fetched_at":     datetime.now(timezone.utc).isoformat(),
        }
        _DAILY_PL_CACHE["ts"] = time.time()
        _DAILY_PL_CACHE["data"] = result
        return result
    except Exception as exc:
        return {"error": str(exc)}


# ── Cell book (Phase C, 2026-07-04) ──────────────────────────────────────────
_CELLS_DIR = _Path("/home/ubuntu/mr-scrooge-v5/config/cells")
_SESSIONS_ALL = ["asia", "london", "ny"]

def _cell_condition_view(cond: dict, view) -> dict:
    """One condition + its live MarketView value + pass verdict.

    Pass logic mirrors modules/cells/cell.py _eval_condition exactly:
    percentile-form uses cond['resolved']=[lo,hi]; absolute form uses min/max
    (None = unbounded).  Unreadable feature → pass=None."""
    feature = cond.get("feature")
    live = getattr(view, feature, None) if (view is not None and feature) else None
    verdict = None
    if live is not None:
        try:
            v = float(live)
            resolved = cond.get("resolved")
            if resolved is not None:
                verdict = float(resolved[0]) <= v <= float(resolved[1])
            else:
                verdict = True
                if cond.get("min") is not None and v < float(cond["min"]):
                    verdict = False
                if cond.get("max") is not None and v > float(cond["max"]):
                    verdict = False
        except (TypeError, ValueError, IndexError):
            verdict = None
    return {
        "feature":         feature,
        "min":             cond.get("min"),
        "max":             cond.get("max"),
        "resolved":        cond.get("resolved"),
        "pct_window_days": cond.get("pct_window_days"),
        "pct_lo":          cond.get("pct_lo"),
        "pct_hi":          cond.get("pct_hi"),
        "resolved_at":     cond.get("resolved_at"),
        "note":            cond.get("note"),
        "lineage":         cond.get("lineage"),
        "live_value":      round(float(live), 6) if isinstance(live, (int, float)) else None,
        "pass":            verdict,
    }

def _cells(engine: "Engine") -> dict:
    """Full cell book: config/cells/*.json (read fresh — files hot-reload, cheap)
    joined with live feature values from the engine's last_views."""
    from config.sessions import coarse_session
    now = datetime.now(timezone.utc)
    cur_sess = coarse_session(now.hour)

    exec_enabled = None
    try:
        from modules.cells import CELL_EXECUTION_ENABLED as _cee
        exec_enabled = bool(_cee)
    except Exception as exc:
        log.warning("cells api: cannot import CELL_EXECUTION_ENABLED: %s", exc)
    shadow_enabled = None
    try:
        from modules.playmaker.playmaker import pm_cell_shadow_enabled
        shadow_enabled = bool(pm_cell_shadow_enabled())
    except Exception as exc:
        log.warning("cells api: pm_cell_shadow_enabled failed: %s", exc)

    views = {v.pair: v for v in (engine.last_views or [])}

    cells = []
    totals = {"ACTIVE": 0, "SHADOW": 0, "NO-SIDE": 0, "DISABLED": 0}
    for pair in _PAIRS_ALL:
        try:
            cfg = _j.loads((_CELLS_DIR / f"{pair}.json").read_text())
        except Exception:
            cfg = {}
        sessions_cfg = cfg.get("sessions", {}) if isinstance(cfg, dict) else {}
        view = views.get(pair)
        for sess in _SESSIONS_ALL:
            scfg = sessions_cfg.get(sess)
            if not isinstance(scfg, dict):
                scfg = {}
            enabled    = bool(scfg.get("enabled", False))
            setups_cfg = scfg.get("setups", []) or []
            if not enabled:
                rollup = "DISABLED"
            elif not setups_cfg:
                rollup = "NO-SIDE"
            elif any(s.get("status") == "ACTIVE" for s in setups_cfg):
                rollup = "ACTIVE"
            else:
                rollup = "SHADOW"
            totals[rollup] += 1

            setups = []
            for s in setups_cfg:
                evidence = s.get("evidence") or {}
                setups.append({
                    "id":          s.get("id"),
                    "side":        s.get("side"),
                    "class":       s.get("class"),
                    "status":      s.get("status"),
                    "horizon_min": s.get("horizon_min"),
                    "exit":        s.get("exit"),
                    "sizing":      s.get("sizing"),
                    "tripwires":   s.get("tripwires"),
                    "ev_seq":      evidence.get("ev_seq"),
                    "lineage":     evidence.get("source"),
                    "evidence":    evidence,
                    "notes":       s.get("notes"),
                    "conditions":  [_cell_condition_view(c, view)
                                    for c in (s.get("conditions") or [])],
                })

            cells.append({
                "pair":           pair,
                "session":        sess,
                "tier":           (scfg.get("structure") or {}).get("tier"),
                "structure":      scfg.get("structure"),
                "enabled":        enabled,
                "in_session_now": sess == cur_sess,
                "status_rollup":  rollup,
                "notes":          scfg.get("notes"),
                "setups":         setups,
            })

    return {
        "exec_enabled":    exec_enabled,
        "shadow_enabled":  shadow_enabled,
        "generated_at":    now.isoformat(),
        "current_session": cur_sess,
        "totals":          totals,
        "cells":           cells,
    }


# ── CELLSHADOW stamp feed (cached 30s, same pattern as daily_pl) ─────────────
_CELLSHADOW_CACHE = {"ts": 0, "data": None}
# CELLSHADOW GBP_USD/london setup=rvol_low_240 side=long conds={...} exp_ev=+0.350 status=ACTIVE
_CELLSHADOW_RX = re.compile(
    r"CELLSHADOW (\w+)/(\w+) setup=(\S+) side=(\w+) conds=(\{.*?\}) "
    r"exp_ev=([+-]?[\d.]+|nan) status=(\w+)"
)
_CELLSHADOW_TS_RX = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:[+-]\d{2}:?\d{2})?)")

def _cellshadow(n: int = 200) -> dict:
    """Recent CELLSHADOW stamps from the user journal, newest first."""
    import time
    if time.time() - _CELLSHADOW_CACHE["ts"] < 30 and _CELLSHADOW_CACHE["data"] is not None:
        data = _CELLSHADOW_CACHE["data"]
    else:
        raw_lines: list[str] = []
        try:
            out = subprocess.check_output(
                ["journalctl", "--user", "-u", "mr-scrooge-v5",
                 "--since", "48 hours ago", "--no-pager", "-o", "short-iso"],
                text=True, timeout=15, stderr=subprocess.DEVNULL,
            )
            raw_lines = [ln for ln in out.splitlines() if "CELLSHADOW" in ln]
        except Exception:
            raw_lines = []   # journalctl absent / no journal → empty feed, no crash
        stamps = []
        for ln in raw_lines:
            m = _CELLSHADOW_RX.search(ln)
            if not m:
                continue
            pair, sess, setup_id, side, conds_s, exp_ev_s, status = m.groups()
            try:
                exp_ev = float(exp_ev_s)
            except ValueError:
                exp_ev = None
            tsm = _CELLSHADOW_TS_RX.match(ln)
            stamps.append({
                "ts":       tsm.group(1) if tsm else None,
                "pair":     pair,
                "session":  sess,
                "setup_id": setup_id,
                "side":     side,
                "exp_ev":   exp_ev,
                "status":   status,
                "conds":    conds_s,
            })
        stamps.reverse()   # journal is oldest-first → newest first
        data = {"stamps": stamps, "n_total": len(stamps),
                "generated_at": datetime.now(timezone.utc).isoformat()}
        _CELLSHADOW_CACHE["ts"] = time.time()
        _CELLSHADOW_CACHE["data"] = data
    return {"stamps": data["stamps"][:n], "n_total": data["n_total"],
            "generated_at": data["generated_at"]}


# ── Cell scoreboard (cell_setup_score.py --json, cached 300s) ────────────────
_CELLSCORE_CACHE = {"ts": 0, "data": None}
_CELLSCORE_SCRIPT = _Path("/home/ubuntu/mr-scrooge-v5/research/tools/cell_setup_score.py")

def _cellscore() -> dict:
    """Run the Phase-C scorer as a subprocess (it needs OANDA candles + journal).
    Cached 300s; scorer errors/timeouts degrade to an empty scoreboard."""
    import time
    if time.time() - _CELLSCORE_CACHE["ts"] < 300 and _CELLSCORE_CACHE["data"] is not None:
        return _CELLSCORE_CACHE["data"]
    try:
        out = subprocess.check_output(
            ["python3", str(_CELLSCORE_SCRIPT), "--json"],
            text=True, timeout=120, stderr=subprocess.DEVNULL,
            cwd="/home/ubuntu/mr-scrooge-v5",
        )
        data = _j.loads(out)
        if not isinstance(data, dict):
            data = {"setups": [], "note": "scorer returned non-dict JSON"}
        if not data.get("setups"):
            data.setdefault("note", "no CELLSHADOW stamps scored yet — market opens Sunday 21:00 UTC")
    except subprocess.TimeoutExpired:
        data = {"setups": [], "note": "scorer timed out (>120s)"}
    except Exception as exc:
        data = {"setups": [], "note": f"scorer error: {exc}"}
    data["generated_at"] = datetime.now(timezone.utc).isoformat()
    _CELLSCORE_CACHE["ts"] = time.time()
    _CELLSCORE_CACHE["data"] = data
    return data


def _sysinfo() -> dict:
    import multiprocessing as _mp, os as _os
    try:
        with open("/proc/loadavg") as f:
            parts = f.read().split()
            load_1, load_5 = parts[0], parts[1]
        with open("/proc/meminfo") as f:
            mem: dict = {}
            for line in f:
                k, v = line.split(":", 1)
                mem[k.strip()] = int(v.split()[0])
        ram_total = mem["MemTotal"]; ram_avail = mem["MemAvailable"]
        ram_used = ram_total - ram_avail; ram_pct = round(ram_used / ram_total * 100)
        cpu_count = _mp.cpu_count()
        cpu_pct = min(round(float(load_1) / cpu_count * 100), 100)
        st = _os.statvfs("/home")
        disk_total = st.f_frsize * st.f_blocks; disk_free = st.f_frsize * st.f_bavail
        disk_pct = round((disk_total - disk_free) / disk_total * 100)
        with open("/proc/uptime") as f:
            secs = int(float(f.read().split()[0]))
        days, rem = divmod(secs, 86400); hrs, rem2 = divmod(rem, 3600); mins = rem2 // 60
        uptime = (f"{days}d " if days else "") + f"{hrs}h {mins}m"
        hostname = _os.uname().nodename
    except Exception as exc:
        return {"error": str(exc)}

    _SHOW = {"mr-scrooge-v5", "openclaw-gateway", "claim-donkey", "mantis-crm"}
    services = []
    try:
        out = subprocess.check_output(
            ["systemctl", "--user", "list-units", "--type=service",
             "--all", "--no-pager", "--no-legend", "--plain"],
            text=True, timeout=5,
        )
        for line in out.strip().splitlines():
            cols = line.split(None, 4)
            if len(cols) < 4:
                continue
            name = cols[0].removesuffix(".service")
            if name not in _SHOW:
                continue
            pid = ""
            try:
                p = subprocess.check_output(
                    ["systemctl", "--user", "show", cols[0], "--property=MainPID"],
                    text=True, timeout=2,
                ).strip()
                pv = p.split("=", 1)[1] if "=" in p else ""
                pid = "" if pv in ("", "0") else pv
            except Exception:
                pass
            services.append({"name": name, "active": cols[2], "sub": cols[3],
                              "desc": cols[4] if len(cols) > 4 else "", "pid": pid})
    except Exception as exc:
        services = [{"name": "error", "active": "unknown", "desc": str(exc), "pid": ""}]

    logs: list[str] = []
    try:
        logs = subprocess.check_output(
            ["journalctl", "--user", "-u", "mr-scrooge-v5", "-o", "cat",
             "-n", "40", "--no-pager"],
            text=True, timeout=5, stderr=subprocess.DEVNULL,
        ).splitlines()
    except Exception:
        logs = ["(journal unavailable)"]

    return {
        "system": {
            "cpu_pct": cpu_pct, "cpu_count": cpu_count,
            "load_1": load_1, "load_5": load_5,
            "ram_pct": ram_pct,
            "ram_used_gb": round(ram_used / 1024 ** 3, 1),
            "ram_total_gb": round(ram_total / 1024 ** 3, 1),
            "disk_pct": disk_pct,
            "uptime": uptime, "hostname": hostname,
        },
        "services": services,
        "logs":     logs,
    }


def start_dashboard(engine: "Engine", port: int = 8084) -> None:
    """Start the dashboard HTTP server in a background daemon thread."""

    def handler_factory(*args, **kwargs):
        return _Handler(engine, *args, **kwargs)

    srv = http.server.HTTPServer(("127.0.0.1", port), handler_factory)
    t = threading.Thread(target=srv.serve_forever, daemon=True, name="v5-dashboard")
    t.start()
    log.info("Dashboard started on port %d — https://[internal-host-redacted]:%d/", port, port)


class _Handler(http.server.BaseHTTPRequestHandler):
    def __init__(self, engine: "Engine", *args, **kwargs):
        self._engine = engine
        super().__init__(*args, **kwargs)

    def do_GET(self):
        try:
            if self.path in ("/", ""):
                if _PANEL.exists():
                    body = _PANEL.read_bytes()
                    ctype = "text/html; charset=utf-8"
                else:
                    body = b"<h1>Panel not found</h1>"
                    ctype = "text/html"
                code = 200
            elif self.path.startswith("/api/state"):
                body = _j.dumps(_state(self._engine), default=str).encode()
                ctype = "application/json"
                code = 200
            elif self.path.startswith("/api/shadowboard"):
                from ops import shadowboard as _sb
                body = _j.dumps(_sb.get_board(), default=str).encode()
                ctype = "application/json"
                code = 200
            elif self.path.startswith("/api/sysinfo"):
                body = _j.dumps(_sysinfo(), default=str).encode()
                ctype = "application/json"
                code = 200
            elif self.path.startswith("/api/daily_pl"):
                body = _j.dumps(_daily_pl(self._engine), default=str).encode()
                ctype = "application/json"
                code = 200
            # NOTE: cellshadow/cellscore BEFORE cells — "/api/cells" is a prefix of both
            elif self.path.startswith("/api/cellshadow"):
                from urllib.parse import urlparse, parse_qs
                q = parse_qs(urlparse(self.path).query)
                try:
                    n = int(q.get("n", ["200"])[0])
                except (ValueError, IndexError):
                    n = 200
                n = max(1, min(n, 2000))
                body = _j.dumps(_cellshadow(n), default=str).encode()
                ctype = "application/json"
                code = 200
            elif self.path.startswith("/api/cellscore"):
                body = _j.dumps(_cellscore(), default=str).encode()
                ctype = "application/json"
                code = 200
            elif self.path.startswith("/api/cells"):
                body = _j.dumps(_cells(self._engine), default=str).encode()
                ctype = "application/json"
                code = 200
            elif self.path.startswith("/api/config/exit"):
                body = _j.dumps({
                    "cfg": _read_exit_config(),
                    "fields": _EXIT_FIELDS,
                    "pairs": _PAIRS_ALL,
                }, default=str).encode()
                ctype = "application/json"
                code = 200
            elif self.path.startswith("/api/config/playmaker"):
                body = _j.dumps({
                    "cfg": _read_playmaker_config(),
                    "fields": _PM_FIELDS,
                    "acct_fields": _PM_ACCT_FIELDS,
                    "pairs": _PAIRS_ALL,
                }, default=str).encode()
                ctype = "application/json"
                code = 200
            else:
                body, ctype, code = b"not found", "text/plain", 404
        except Exception as exc:
            log.exception("dashboard handler error: %s", exc)
            body = _j.dumps({"error": str(exc)}).encode()
            ctype, code = "application/json", 500

        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        try:
            if self.path.startswith("/api/config/exit"):
                length = int(self.headers.get("Content-Length", "0") or 0)
                raw = self.rfile.read(length) if length else b""
                try:
                    payload = _j.loads(raw.decode() or "{}")
                    _write_exit_config(payload)
                    body = _j.dumps({"ok": True, "cfg": _read_exit_config()}).encode()
                    ctype, code = "application/json", 200
                    log.info("exit_config updated via dashboard (defaults=%s per_pair=%s)",
                             list(payload.get("defaults", {}).keys()),
                             list(payload.get("per_pair", {}).keys()))
                except Exception as exc:
                    body = _j.dumps({"ok": False, "error": str(exc)}).encode()
                    ctype, code = "application/json", 400
            elif self.path.startswith("/api/config/playmaker"):
                length = int(self.headers.get("Content-Length", "0") or 0)
                raw = self.rfile.read(length) if length else b""
                try:
                    payload = _j.loads(raw.decode() or "{}")
                    _write_playmaker_config(payload)
                    body = _j.dumps({"ok": True, "cfg": _read_playmaker_config()}).encode()
                    ctype, code = "application/json", 200
                    log.info("playmaker_config updated (account=%s defaults=%s per_pair=%s)",
                             list(payload.get("account", {}).keys()),
                             list(payload.get("defaults", {}).keys()),
                             list(payload.get("per_pair", {}).keys()))
                except Exception as exc:
                    body = _j.dumps({"ok": False, "error": str(exc)}).encode()
                    ctype, code = "application/json", 400
            else:
                body, ctype, code = b"not found", "text/plain", 404
        except Exception as exc:
            log.exception("dashboard POST handler error: %s", exc)
            body = _j.dumps({"ok": False, "error": str(exc)}).encode()
            ctype, code = "application/json", 500
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass
