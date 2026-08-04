"""ops/server.py — V6 control panel HTTP server.

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
  GET /api/credentials     → credential status (masked last4 + mode; NEVER values)
  POST /api/config/exit    → live edit exit_config.json (validated; RECOVERY FALLBACK only)
  POST /api/config/playmaker→ live edit playmaker_config.json (validated, merge-preserving)
  POST /api/cell/status    → flip one setup ACTIVE/SHADOW/DISABLED in config/cells (hot-reload)
  POST /api/cell/exit      → live edit one setup's per-cell exit geometry (hot-reload)
  POST /api/pp/retire      → retire one exact, flat grid before a governance era transition
  POST /api/credentials    → save+verify an OANDA credential set (writes credentials.local.json)
  POST /api/mode           → practice/live toggle (live-armed via SCROOGE_ALLOW_LIVE + confirm)
  POST /api/trading        → soft trading PAUSE switch (hot-reload; pause = no new entries)

Start via start_dashboard(engine, port=8084) from main.py — runs in daemon thread.

WRITE-endpoint safety: every writer validates input, merges (never replaces) so
unknown/other fields survive, writes atomically (tmp+replace), and touches only
config on disk — never the 3 open positions.  config/cells + config/*.json all
hot-reload on the next engine cycle; ONLY credential/mode changes need a restart
(broker creds load at engine init).
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

log = logging.getLogger("v6.dashboard")

_PANEL = Path(__file__).resolve().parent / "panel.html"

# Repo root derived from THIS file's location (ops/server.py → repo root), so the
# dashboard always reads its OWN config/journal — never a sibling checkout. Mirrors
# modules/cells/cell.py (_CELLS_DIR = Path(__file__)...parents[...]).
from pathlib import Path as _Path
_REPO_ROOT = Path(__file__).resolve().parents[1]

def _journal_unit() -> str:
    """journald unit for CELLSHADOW / journal reads — parameterized via
    SCROOGE_JOURNAL_UNIT (default = the live V6 unit). Matches the exact
    pattern in ops/shadowboard.py so both read the same unit's journal."""
    import os
    return os.environ.get("SCROOGE_JOURNAL_UNIT", "mr-scrooge-v6")

# ── Exit-tuning config (TUNE tab) ───────────────────────────────────────────
_EXIT_CONFIG_PATH = _REPO_ROOT / "config" / "exit_config.json"

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
# Single source of truth for the pair universe is config/pairs.py (B-098 family
# lesson: a list that exists in three files is three bugs) — sorted for display.
from config.pairs import PAIRS as _CFG_PAIRS
_PAIRS_ALL = sorted(_CFG_PAIRS)

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
_PM_CONFIG_PATH = _REPO_ROOT / "config" / "playmaker_config.json"

_PM_FIELDS = {
    "enabled":             {"kind": "bool",                 "label": "Enabled"},
    "min_direction_score": {"min": 0.0,  "max": 1.0,        "label": "Min |direction.score|"},
    "min_dir_certainty":   {"min": 0.0,  "max": 1.0,        "label": "Min direction.certainty"},
    "min_mom_certainty":   {"min": 0.0,  "max": 1.0,        "label": "Min momentum.certainty"},
    "cooldown_after_sl_min": {"min": 0.0, "max": 1440.0,    "label": "Cooldown after losing exit (min)"},
    # Governance toggles that live in the `defaults` block (playmaker._pm_load reads
    # them from defaults). Declared here so a save validates + round-trips them.
    "profile_shadow_enabled":  {"kind": "bool",             "label": "Profile shadow logging"},
    "calibration_log_enabled": {"kind": "bool",             "label": "Calibration logging"},
}
_PM_ACCT_FIELDS = {
    "margin_pct_per_trade":  {"min": 0.001, "max": 1.0,  "label": "Margin per trade (fraction of balance)"},
    "max_concurrent_trades": {"min": 1,     "max": 20,   "label": "Max concurrent trades", "int": True},
    # Live per-currency directional exposure cap. MUST round-trip: dropping it on a
    # save silently reverts the live cap to the code default (playmaker._PM_ACCT_DEFAULTS
    # = 1), changing risk behaviour without an operator edit.
    "max_per_currency_direction": {"min": 1, "max": 20, "label": "Max concurrent same (currency, sign) exposures", "int": True},
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
    """Validate a dashboard playmaker edit and MERGE it onto the on-disk config.

    Only the three editable blocks (account / defaults / per_pair) are taken from
    the incoming payload; every OTHER top-level key — disabled_cells, inverted_*
    cells, per_cell_* ranges, random_pick and all _note* annotations — is carried
    over verbatim from disk so a dashboard save can NEVER silently drop live
    governance or risk caps.  (Pre-fix regression: a save reduced the file to
    {schema,account,defaults,per_pair}, wiping account.max_per_currency_direction,
    12 disabled_cells, the inverted_live_cells set and every per_cell_* range.)

    Within each editable block KNOWN fields are range/type-validated; UNKNOWN
    sub-keys (e.g. a per-pair `_note`) are preserved untouched rather than stripped.
    """
    if not isinstance(cfg, dict):
        raise ValueError("playmaker config must be a JSON object")
    base = _read_playmaker_config()
    if not isinstance(base, dict) or "_error" in base:
        base = {"schema": "v1", "account": {}, "defaults": {}, "per_pair": {}}
    # Start from every on-disk key EXCEPT the three we're about to rebuild.
    out = {k: v for k, v in base.items() if k not in ("account", "defaults", "per_pair")}
    out["schema"] = "v1"

    acct = dict(base.get("account") or {})
    for k, v in (cfg.get("account") or {}).items():
        k = _PM_LEGACY_ACCT_KEYS.get(k, k)   # back-compat rename
        acct[k] = _validate_pm_field(_PM_ACCT_FIELDS, k, v) if k in _PM_ACCT_FIELDS else v
    out["account"] = acct

    defs = dict(base.get("defaults") or {})
    for k, v in (cfg.get("defaults") or {}).items():
        defs[k] = _validate_pm_field(_PM_FIELDS, k, v) if k in _PM_FIELDS else v
    out["defaults"] = defs

    per = dict(base.get("per_pair") or {})
    if isinstance(cfg.get("per_pair"), dict):
        for pair, ov in cfg["per_pair"].items():
            if pair not in _PAIRS_ALL:
                raise ValueError(f"unknown pair: {pair}")
            merged = dict(per.get(pair) or {})
            for k, v in (ov or {}).items():
                merged[k] = _validate_pm_field(_PM_FIELDS, k, v) if k in _PM_FIELDS else v
            per[pair] = merged
    out["per_pair"] = per
    return out

def _write_pp_toggle(payload: dict) -> dict:
    """Party Package on/off switches (V6.1). Merge-writes config/pp_config.json.

    Accepted payload keys:
      {"enabled": bool}                       — global kill switch
      {"cell": "PAIR|session|setup" (or "PAIR|session" or "PAIR"), "enabled": bool}
                                              — per-cell opt-out (most-specific wins)
      {"cell": "...", "enabled": null}        — remove the per-cell override (back to default ON)
    Every other pp_config key is carried over verbatim from disk.
    """
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")
    path = _REPO_ROOT / "config" / "pp_config.json"
    try:
        base = _j.loads(path.read_text())
    except (OSError, ValueError):
        base = {}
    if not isinstance(base, dict):
        base = {}
    if "cell" in payload:
        key = str(payload["cell"]).strip()
        parts = key.split("|")
        if not key or len(parts) > 3 or any(not p or "/" in p or ".." in p for p in parts):
            raise ValueError(f"bad cell key: {key!r}")
        pc = base.get("per_cell")
        if not isinstance(pc, dict):
            pc = {}
        if payload.get("enabled") is None:
            pc.pop(key, None)
        else:
            pc[key] = bool(payload["enabled"])
        base["per_cell"] = pc
    elif "enabled" in payload:
        base["enabled"] = bool(payload["enabled"])
    else:
        raise ValueError("payload needs 'enabled' (global) or 'cell' + 'enabled'")
    tmp = path.with_suffix(".tmp")
    tmp.write_text(_j.dumps(base, indent=2))
    tmp.replace(path)
    return base


_PP_BOOK_CACHE = {"ts": 0.0, "cells": []}

def _pp_book_cells() -> list:
    """Light list of the book's setups ("PAIR|session|setup_id" + status) for the
    per-cell popper toggles. Plain file reads, cached 30s."""
    import time as _t
    if _t.time() - _PP_BOOK_CACHE["ts"] < 30 and _PP_BOOK_CACHE["cells"]:
        return _PP_BOOK_CACHE["cells"]
    cells = []
    cdir = _REPO_ROOT / "config" / "cells"
    try:
        for f in sorted(cdir.glob("*.json")):
            try:
                data = _j.loads(f.read_text())
            except (OSError, ValueError):
                continue
            pair = data.get("pair") or f.stem
            for sess, sblock in (data.get("sessions") or {}).items():
                for su in (sblock.get("setups") or []):
                    sid = su.get("id") or su.get("setup_id") or "?"
                    cells.append({"key": f"{pair}|{sess}|{sid}",
                                  "status": su.get("status", "?")})
    except OSError:
        pass
    _PP_BOOK_CACHE.update(ts=_t.time(), cells=cells)
    return cells


def _write_playmaker_config(cfg: dict) -> None:
    clean = _validate_pm_cfg(cfg)
    # Record edit provenance WITHOUT clobbering the on-disk `_note` annotation
    # (which documents the disabled/inverted cell rationale).
    clean["_note_dashboard"] = ("Last edited via dashboard PLAYMAKER tab "
                                f"{datetime.now(timezone.utc).isoformat()} — "
                                "account/defaults/per_pair only; governance preserved.")
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


# ── Per-cell setup controls (status flip + live exit edit) ───────────────────
# These write the LIVE trading unit: config/cells/<PAIR>.json.  The engine
# hot-reloads that file on mtime change (modules/cells/cell.py _load_pair_config),
# so a status/exit write takes effect on the NEXT scan cycle — no restart.
_CELL_STATUSES = {"ACTIVE", "PROBE", "SHADOW", "DISABLED"}
# Per-cell exit ranges (dashboard TUNE tab).  Merge-not-replace: only these four
# geometry knobs are editable; mode/trail_min/trail_max/_class/tp_pips/timeout
# are preserved verbatim from disk.
_CELL_EXIT_FIELDS = {
    "sl_pips":      {"min": 5.0,  "max": 200.0, "label": "Range-sized initial SL (pips)"},
    "trigger_pips": {"min": 0.0,  "max": 50.0,  "label": "Ratchet engage / peak trigger (pips)"},
    "trail_pips":   {"min": 0.0,  "max": 30.0,  "label": "Trail behind peak (pips)"},
    "trail_mult":   {"min": 0.0,  "max": 3.0,   "label": "ATR-scaled trail multiplier (0=fixed)"},
}

def _cell_path(pair: str) -> Path:
    if pair not in _PAIRS_ALL:
        raise ValueError(f"unknown pair: {pair}")
    return _CELLS_DIR / f"{pair}.json"

def _load_cell_file(pair: str) -> dict:
    data = _j.loads(_cell_path(pair).read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{pair}.json is not a JSON object")
    return data

def _write_cell_file(pair: str, data: dict) -> None:
    """Atomic write preserving the file's 2-space indent style."""
    path = _cell_path(pair)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(_j.dumps(data, indent=2))
    tmp.replace(path)

def _find_setup(data: dict, session: str, setup_id: str) -> dict:
    """Return the mutable setup dict for (session, setup_id), or raise."""
    if session not in _SESSIONS_ALL:
        raise ValueError(f"unknown session: {session}")
    scfg = (data.get("sessions") or {}).get(session)
    if not isinstance(scfg, dict):
        raise ValueError(f"session {session} not present in config")
    for s in (scfg.get("setups") or []):
        if s.get("id") == setup_id:
            return s
    raise ValueError(f"setup '{setup_id}' not found in {session}")

_NOTES_COUNTS_RE = None    # compiled lazily (re import stays top-of-file scoped)


def _refresh_session_notes(scfg: dict) -> None:
    """Rewrite the leading "N ACTIVE, M SHADOW setups." sentence in a session's
    notes from the ACTUAL setup statuses. The sentence was written once at
    wiring time and never updated on flips — 10 cells were lying on the
    dashboard by the time this was caught (EUR_JPY/ny demotion, 2026-08-04)."""
    import re
    global _NOTES_COUNTS_RE
    if _NOTES_COUNTS_RE is None:
        _NOTES_COUNTS_RE = re.compile(r"^\s*(?:\d+\s+[A-Z-]+,?\s*)+setups\.\s*")
    notes = scfg.get("notes")
    if not isinstance(notes, str) or not _NOTES_COUNTS_RE.match(notes):
        return                      # hand-written notes: leave untouched
    counts = {}
    for st in (s.get("status") for s in scfg.get("setups") or []):
        counts[st or "?"] = counts.get(st or "?", 0) + 1
    parts = [f"{counts[k]} {k}" for k in ("ACTIVE", "PROBE", "SHADOW", "DISABLED")
             if counts.get(k)]
    sentence = (", ".join(parts) if parts else "0") + " setups. "
    scfg["notes"] = _NOTES_COUNTS_RE.sub(sentence, notes, count=1)


def _set_cell_status(pair: str, session: str, setup_id: str, status: str) -> dict:
    """Flip one setup's status in config/cells/<PAIR>.json (merge-preserving)."""
    if status not in _CELL_STATUSES:
        raise ValueError(f"status must be one of {sorted(_CELL_STATUSES)}, got {status!r}")
    data = _load_cell_file(pair)
    setup = _find_setup(data, session, setup_id)
    old = setup.get("status")
    setup["status"] = status
    _refresh_session_notes((data.get("sessions") or {}).get(session) or {})
    _write_cell_file(pair, data)
    return {"pair": pair, "session": session, "setup_id": setup_id,
            "old_status": old, "status": status}

def _validate_cell_exit(patch: dict) -> dict:
    if not isinstance(patch, dict):
        raise ValueError("exit must be a JSON object")
    clean = {}
    for k, v in patch.items():
        if k not in _CELL_EXIT_FIELDS:
            raise ValueError(f"unknown exit field: {k}")
        spec = _CELL_EXIT_FIELDS[k]
        f = float(v)
        if not (spec["min"] <= f <= spec["max"]):
            raise ValueError(f"{k}={f} out of bounds [{spec['min']}, {spec['max']}]")
        clean[k] = f
    if not clean:
        raise ValueError("no editable exit fields supplied")
    return clean

def _set_cell_exit(pair: str, session: str, setup_id: str, patch: dict) -> dict:
    """Merge exit-geometry edits into one setup's `exit` block (preserving
    mode/trail_min/trail_max/_class/tp_pips/timeout_min/entry_cutoff_utc)."""
    clean = _validate_cell_exit(patch)
    data = _load_cell_file(pair)
    setup = _find_setup(data, session, setup_id)
    ex = dict(setup.get("exit") or {})
    merged = {**ex, **clean}
    # Sanity: first lock = trigger - trail must stay positive when both are set.
    trig = merged.get("trigger_pips"); trail = merged.get("trail_pips")
    if trig is not None and trail is not None and float(trig) > 0 and float(trail) >= float(trig):
        raise ValueError(f"trail_pips ({trail}) must be < trigger_pips ({trig}) "
                         "(else the first ratchet lock is <= 0)")
    setup["exit"] = merged
    _write_cell_file(pair, data)
    return {"pair": pair, "session": session, "setup_id": setup_id, "exit": merged}


# ── Credentials + practice/live mode (CONNECTION tab) ────────────────────────
# All read/write/validate logic lives in config/credentials.py so the broker and
# the dashboard share one source of truth.  Tokens are NEVER logged or echoed.
def _credentials_status() -> dict:
    from config import credentials as _cred
    return _cred.status()

def _save_credentials(payload: dict) -> dict:
    """POST /api/credentials — verify a credential set READ-ONLY against OANDA,
    then merge it into credentials.local.json (preserving the other set + mode).
    Returns a masked confirmation; never the token."""
    from config import credentials as _cred
    if not isinstance(payload, dict):
        raise ValueError("body must be a JSON object")
    account = payload.get("account")
    if account not in _cred.MODES:
        raise ValueError(f"account must be one of {list(_cred.MODES)}")
    api_token = payload.get("api_token")
    account_id = payload.get("account_id")
    # Optional editable api_url. Blank/absent → OANDA default for the type.
    raw_url = payload.get("api_url")
    if raw_url is not None and str(raw_url).strip():
        if not _cred.valid_https_url(raw_url):
            raise ValueError("api_url must be a well-formed https:// URL")
        api_url = str(raw_url).strip().rstrip("/")
    else:
        api_url = _cred.default_url_for(account)
    # Verify against the chosen host — a non-OANDA URL fails here (deliberate guard).
    if not allowed_oanda_api_url(api_url, account):
        return 400, {"ok": False,
                     "error": "api_url rejected: dashboard credentials may only "
                              "be verified against the official OANDA host for "
                              "this account type (see SCROOGE_OANDA_HOST_ALLOWLIST "
                              "for lab overrides)"}
    ok, msg = _cred.verify_oanda_token(account, api_token, account_id, api_url=api_url)
    if not ok:
        raise ValueError(msg)
    local = _cred.load_local()
    local[account] = {"api_token": str(api_token).strip(),
                      "account_id": str(account_id).strip(),
                      "api_url": api_url}
    local.setdefault("mode", "practice")
    _cred.write_local(local)
    log.info("credentials saved for %s account (token %s, id %s, url %s) — verified",
             account, _cred.mask(api_token), account_id, api_url)
    return {"ok": True, "account": account, "verified": True,
            "masked": _cred.mask(api_token), "account_id": account_id, "api_url": api_url}

def _set_mode(payload: dict) -> tuple[int, dict]:
    """POST /api/mode — the practice/live toggle.  Returns (http_status, body).
    Guardrails: live requires SCROOGE_ALLOW_LIVE=1, verified live creds, and the
    exact confirm string.  Mode applies on the NEXT engine restart."""
    from config import credentials as _cred
    if not isinstance(payload, dict):
        return 400, {"ok": False, "error": "body must be a JSON object"}
    mode = payload.get("mode")
    if mode not in _cred.MODES:
        return 400, {"ok": False, "error": f"mode must be one of {list(_cred.MODES)}"}
    local = _cred.load_local()

    if mode == "live":
        if not _cred.allow_live():
            return 403, {"ok": False, "error": ("live trading disabled on this instance; "
                         "set SCROOGE_ALLOW_LIVE=1 in the environment to arm.")}
        cset = local.get("live") or {}
        if not (cset.get("api_token") and cset.get("account_id")):
            return 400, {"ok": False, "error": "no live credentials saved — add + verify them first"}
        if payload.get("confirm") != "TRADE REAL MONEY":
            return 400, {"ok": False, "error": 'confirmation required: send confirm="TRADE REAL MONEY"'}
        ok, msg = _cred.verify_oanda_token("live", cset["api_token"], cset["account_id"],
                                           api_url=_cred.url_for_set(cset, "live"))
        if not ok:
            return 400, {"ok": False, "error": f"live credentials failed re-verification: {msg}"}

    local["mode"] = mode
    _cred.write_local(local)
    log.warning("TRADING MODE set to %s via dashboard (applies on next restart)", mode.upper())
    return 200, {"ok": True, "mode": mode, "restart_required": True,
                 "note": "mode applies when the bot next restarts (broker creds load at engine init)"}


def _set_trading(payload: dict) -> tuple[int, dict]:
    """POST /api/trading — soft trading PAUSE switch. Returns (http_status, body).

    Turning OFF (pause) is unconfirmed — the safe direction. Turning ON while the
    box is in LIVE mode requires the same typed confirmation as other live
    actions. Hot-reloads (engine reads config/runtime.json each cycle) — no
    restart. Pause blocks NEW entries only; open positions keep being managed."""
    from config import runtime as _rt
    if not isinstance(payload, dict) or not isinstance(payload.get("enabled"), bool):
        return 400, {"ok": False, "error": "body must be {\"enabled\": true|false}"}
    enabled = payload["enabled"]
    if enabled:
        # Extra friction to RESUME trading while pointed at real money.
        try:
            from config import credentials as _cred
            mode = _cred.load_local().get("mode", "practice")
        except Exception:
            mode = "practice"
        if mode == "live" and payload.get("confirm") != "TRADE REAL MONEY":
            return 400, {"ok": False, "error": 'resuming LIVE trading requires confirm="TRADE REAL MONEY"'}
    _rt.set_trading_enabled(enabled)
    log.warning("TRADING %s via dashboard (hot-reload; new entries %s)",
                "ENABLED" if enabled else "PAUSED",
                "allowed" if enabled else "suppressed — open positions still managed")
    return 200, {"ok": True, "trading_enabled": enabled}



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

    # ── Poppers (V6.1): every open popper is its own row in Open Trades ──────
    try:
        for _tid, _pmgr in engine.pp.poppers.items():
            _ppair = _pmgr.position.ticket.pair
            _mid = _pmgr.position.entry_price
            for v in (engine.last_views or []):
                if v.pair == _ppair:
                    _mid = (v.bid + v.ask) / 2
                    break
            _lvl = engine.pp._popper_grid.get(_tid, (_ppair, 0))[1]
            _pt = oanda_trades.get(_tid, {})
            _pupl = float(_pt.get("unrealizedPL", 0)) if _pt else None
            _pep = getattr(_pmgr.position, "exit_params", None)
            _elapsed = (now - _pmgr.position.entry_time).total_seconds() / 60
            open_positions.append({
                "exit_mode":     "ratchet",
                "exit_class":    "POPPER",
                "popper_level":  _lvl,
                "popper_marker": f"-{float(_lvl):g}p",
                "engage_pips":   round(float(getattr(_pep, "trigger_pips", 0) or 0), 2),
                "trail_pips":    round(float(getattr(_pep, "trail_pips", 0) or 0), 2),
                "trail_mult":    None,
                "pair":          _ppair,
                "direction":     _pmgr.direction,
                "entry":         round(_pmgr.position.entry_price, 5),
                "entry_time":    _pmgr.position.entry_time.isoformat(),
                "elapsed_min":   round(_elapsed, 1),
                "oanda_trade_id": _tid,
                "sl_locked_pips": _pmgr.sl_locked_pips,
                "peak_price":    round(_pmgr.peak_price, 5),
                "peak_pips":     round(_pmgr._peak_pips(), 2),
                "sl_price":      round(_pmgr._sl_pips_to_price(_pmgr.sl_locked_pips), 5)
                                 if _pmgr.sl_locked_pips is not None else None,
                "net_pips_now":  round(_pmgr.net_pips(_mid), 2),
                "unrealized_pl": round(_pupl, 2) if _pupl is not None else None,
            })
    except Exception as _pperr:
        log.warning("popper rows for /api/state failed: %s", _pperr)

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
    try:
        from config.runtime import trading_enabled as _te
        _trading_enabled = _te()
    except Exception:
        _trading_enabled = True
    # ── Party Package (V6.1) — grids + poppers; defensive like everything else
    try:
        party_package = engine.pp.state()
        party_package["book_cells"] = _pp_book_cells()
    except Exception as exc:
        party_package = {"error": str(exc)}
    return {
        "account":         account,
        "rollover_freeze": _irf(now),
        "trading_enabled": _trading_enabled,
        "party_package":   party_package,
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
_CELLS_DIR = _REPO_ROOT / "config" / "cells"
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
    totals = {"ACTIVE": 0, "PROBE": 0, "SHADOW": 0, "NO-SIDE": 0, "DISABLED": 0}
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
            elif any(s.get("status") == "PROBE" for s in setups_cfg):
                rollup = "PROBE"      # live 0.33x audition seat — not a shadow
            else:
                rollup = "SHADOW"
            totals[rollup] = totals.get(rollup, 0) + 1

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
                ["journalctl", "--user", "-u", _journal_unit(),
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


# ── Dashboard security (external review round 2) ─────────────────────────────
import secrets as _secrets_mod

OFFICIAL_OANDA_HOSTS = {
    "practice": "https://api-fxpractice.oanda.com",
    "live":     "https://api-fxtrade.oanda.com",
}

def allowed_oanda_api_url(url: str, account_type: str) -> bool:
    """Dashboard-submitted credentials may only ever be sent to the official
    OANDA host for their account type (or a startup-time allowlisted host via
    SCROOGE_OANDA_HOST_ALLOWLIST). Review round 2: the old check accepted ANY
    https URL — an attacker-shaped host could harvest the bearer token."""
    import os as _os
    normalized = (url or "").strip().rstrip("/").lower()
    if normalized == OFFICIAL_OANDA_HOSTS.get(account_type, "").lower():
        return True
    extra = {u.strip().rstrip("/").lower()
             for u in _os.environ.get("SCROOGE_OANDA_HOST_ALLOWLIST", "").split(",")
             if u.strip()}
    return normalized in extra


def dashboard_allowed_hosts(bind_host: str, port: int) -> set:
    """Host-header allowlist — defeats DNS rebinding, where Origin==Host both
    carry the attacker's domain (equality checks pass; membership fails)."""
    import os as _os
    configured = {h.strip().lower()
                  for h in _os.environ.get("DASHBOARD_ALLOWED_HOSTS", "").split(",")
                  if h.strip()}
    if bind_host in ("127.0.0.1", "::1", "localhost"):
        return configured | {f"localhost:{port}", f"127.0.0.1:{port}", f"[::1]:{port}"}
    return configured


def _dashboard_token() -> str:
    import os as _os
    return _os.environ.get("DASHBOARD_TOKEN", "")


# ── Bar Governor (autonomous promote/demote) — status + ON/OFF ───────────────
_GOVERNOR_CFG = _REPO_ROOT / "config" / "governor_config.json"
_GOVERNOR_LEDGER = _REPO_ROOT / "data" / "governor_ledger.jsonl"

def _governor_get() -> dict:
    """GET /api/governor — config, enabled state, and the recent ledger tail."""
    try:
        cfg = _j.loads(_GOVERNOR_CFG.read_text())
    except Exception:
        cfg = {}
    ledger = []
    try:
        lines = _GOVERNOR_LEDGER.read_text().strip().splitlines()
        for ln in lines[-5:]:
            try:
                ledger.append(_j.loads(ln))
            except Exception:
                continue
    except Exception:
        pass
    return {"enabled": bool(cfg.get("enabled", False)), "config": cfg,
            "ledger_tail": list(reversed(ledger)),
            "generated_at": datetime.now(timezone.utc).isoformat()}

def _governor_post(payload: dict) -> tuple[int, dict]:
    """POST /api/governor {enabled: bool} and/or {cheater: bool} —
    merge-preserving atomic write. `cheater` toggles the opt-in CHEATER
    PROMOTION rule (era cum >= +100p promotes immediately, default OFF)."""
    if not isinstance(payload, dict) or (
            not isinstance(payload.get("enabled"), bool)
            and not isinstance(payload.get("cheater"), bool)):
        return 400, {"ok": False,
                     "error": "payload must set \"enabled\" and/or \"cheater\" (bool)"}
    try:
        cfg = _j.loads(_GOVERNOR_CFG.read_text())
    except Exception:
        cfg = {}
    if isinstance(payload.get("cheater"), bool):
        cfg["cheater_promotion_enabled"] = payload["cheater"]
        log.info("governor CHEATER PROMOTION %s via dashboard",
                 "ON" if payload["cheater"] else "OFF")
    if isinstance(payload.get("enabled"), bool):
        cfg["enabled"] = payload["enabled"]
    tmp = _GOVERNOR_CFG.with_suffix(".tmp")
    tmp.write_text(_j.dumps(cfg, indent=2) + "\n")
    tmp.replace(_GOVERNOR_CFG)
    log.info("governor state via dashboard: enabled=%s cheater=%s",
             cfg.get("enabled"), cfg.get("cheater_promotion_enabled", False))
    return 200, {"ok": True, "enabled": cfg.get("enabled", True),
                 "cheater": cfg.get("cheater_promotion_enabled", False)}


# ── Cell scoreboard (cell_setup_score.py --json, cached 300s) ────────────────
_CELLSCORE_CACHE = {"ts": 0, "data": None, "refreshing": False}
_CELLSCORE_SCRIPT = _REPO_ROOT / "research" / "tools" / "cell_setup_score.py"

def _cellscore_refresh():
    """Worker: run the Phase-C scorer subprocess and refill the cache.
    Runs ONLY in the daemon thread — the scorer takes minutes and the
    dashboard server is single-threaded (2026-07-09 lesson; a blocked
    /api/state here is what painted quick-status red)."""
    import time
    try:
        out = subprocess.check_output(
            ["python3", str(_CELLSCORE_SCRIPT), "--json"],
            text=True, timeout=600, stderr=subprocess.DEVNULL,
            cwd=str(_REPO_ROOT),
        )
        data = _j.loads(out)
        if not isinstance(data, dict):
            data = {"setups": [], "note": "scorer returned non-dict JSON"}
        if not data.get("setups"):
            data.setdefault("note", "no CELLSHADOW stamps scored yet — market opens Sunday 21:00 UTC")
    except subprocess.TimeoutExpired:
        data = {"setups": [], "note": "scorer timed out (>600s)"}
    except Exception as exc:
        data = {"setups": [], "note": f"scorer error: {exc}"}
    finally:
        _CELLSCORE_CACHE["refreshing"] = False
    data["generated_at"] = datetime.now(timezone.utc).isoformat()
    _CELLSCORE_CACHE["ts"] = time.time()
    _CELLSCORE_CACHE["data"] = data
    return data


def _cellscore() -> dict:
    """Serve the cached scoreboard instantly; kick a background refresh
    when stale. Never blocks the request thread."""
    import threading, time
    fresh = (time.time() - _CELLSCORE_CACHE["ts"] < 300
             and _CELLSCORE_CACHE["data"] is not None)
    if not fresh and not _CELLSCORE_CACHE["refreshing"]:
        _CELLSCORE_CACHE["refreshing"] = True
        threading.Thread(target=_cellscore_refresh,
                         name="cellscore-refresh", daemon=True).start()
    return _CELLSCORE_CACHE["data"] or {
        "setups": [], "note": "scoreboard building in background — refresh shortly",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


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

    _SHOW = {_journal_unit(), "openclaw-gateway", "claim-donkey", "mantis-crm"}
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
            ["journalctl", "--user", "-u", _journal_unit(), "-o", "cat",
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


def start_dashboard(engine: "Engine", port: int = 8084,
                    host: str | None = None) -> None:
    """Start the dashboard HTTP server in a background daemon thread.

    Bind address comes from the host arg, else DASHBOARD_HOST, else 127.0.0.1.
    SECURITY: the dashboard is UNAUTHENTICATED and has write endpoints
    (cell status, credentials, practice/live mode, trading pause). Bind a
    LAN address (e.g. 0.0.0.0 or the machine's IP) only on a network where
    every host is trusted — never on an internet-facing interface."""
    import os
    host = host or os.environ.get("DASHBOARD_HOST", "127.0.0.1")

    # Review round 2: a non-loopback bind REQUIRES the full secure config —
    # a token, an explicit host allowlist, and an explicit opt-in. Refusing
    # to serve remotely (downgrading to loopback) is chosen over refusing to
    # start: the dashboard runs inside the trading process, and a dashboard
    # misconfig must never kill the trader.
    loopback = host in ("127.0.0.1", "::1", "localhost")
    if not loopback:
        if not (_dashboard_token() and os.environ.get("DASHBOARD_ALLOWED_HOSTS")
                and os.environ.get("DASHBOARD_ALLOW_REMOTE") == "1"):
            log.critical("DASHBOARD_HOST=%s requires DASHBOARD_TOKEN + "
                         "DASHBOARD_ALLOWED_HOSTS + DASHBOARD_ALLOW_REMOTE=1 — "
                         "REFUSING remote bind, serving on 127.0.0.1 instead", host)
            host = "127.0.0.1"
            loopback = True

    def handler_factory(*args, **kwargs):
        return _Handler(engine, *args, **kwargs)

    srv = http.server.HTTPServer((host, port), handler_factory)
    srv.allowed_hosts = dashboard_allowed_hosts(host, port)
    t = threading.Thread(target=srv.serve_forever, daemon=True, name="dashboard")
    t.start()
    log.info("Dashboard started on %s:%d", host, port)


class _Handler(http.server.BaseHTTPRequestHandler):
    def __init__(self, engine: "Engine", *args, **kwargs):
        self._engine = engine
        super().__init__(*args, **kwargs)

    def do_GET(self):
        if not self._host_allowed():
            return self._deny(421, "host rejected")
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
            elif self.path.startswith("/api/commissioner"):
                # Edge Command cockpit: the Commissioner's stage + pass history
                try:
                    body = (_REPO_ROOT / "data" / "commissioner_state.json").read_bytes()
                    ctype, code = "application/json", 200
                except OSError:
                    body = _j.dumps({"stage": "VALIDATING", "passes": []}).encode()
                    ctype, code = "application/json", 200
            elif self.path.startswith("/api/governor/ledger"):
                # enhanced dashboard (2026-07-31): the decision ledger, no
                # METRIC-ERA-RESET noise, newest first, capped at 40. MUST sit
                # above the /api/governor prefix route.
                try:
                    _lp = _REPO_ROOT / "data" / "governor_ledger.jsonl"
                    _rows = []
                    for _ln in _lp.read_text().splitlines():
                        try:
                            _d = _j.loads(_ln)
                        except ValueError:
                            continue
                        if _d.get("action") != "METRIC-ERA-RESET":
                            _rows.append(_d)
                    body = _j.dumps({"entries": _rows[-40:][::-1]},
                                    default=str).encode()
                    ctype, code = "application/json", 200
                except OSError:
                    body = _j.dumps({"entries": []}).encode()
                    ctype, code = "application/json", 200
            elif self.path.startswith("/api/governor"):
                body = _j.dumps(_governor_get(), default=str).encode()
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
            elif self.path.startswith("/api/credentials"):
                body = _j.dumps(_credentials_status(), default=str).encode()
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
        # No CORS header on purpose (2026-07-27 external-review fix):
        # the old Access-Control-Allow-Origin:* invited any webpage the
        # operator visits to script this API cross-origin. The panel is
        # same-origin; nothing legitimate needs CORS here.
        # HTML/JS is versionless — stale cached panel JS against new state
        # renders garbage (2026-07-23: cached level*15 vs offset keys)
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length) if length else b""
        return _j.loads(raw.decode() or "{}")

    def _deny(self, code: int, why: str):
        body = _j.dumps({"ok": False, "error": why}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)
        log.warning("dashboard: %s (%d) %s from %s Origin=%s Host=%s",
                    why, code, self.path, self.client_address[0],
                    self.headers.get("Origin"), self.headers.get("Host"))

    def _host_allowed(self) -> bool:
        """Host-header ALLOWLIST membership (review round 2): Origin==Host
        equality does not defeat DNS rebinding — a rebinding domain matches
        itself. Membership in the configured set does."""
        allowed = getattr(self.server, "allowed_hosts", None)
        if not allowed:
            return True     # not configured (legacy start path) — other guards apply
        return self.headers.get("Host", "").strip().lower() in allowed

    def _origin_allowed(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            # non-browser tools; require a loopback peer
            return self.client_address[0] in ("127.0.0.1", "::1")
        from urllib.parse import urlsplit
        try:
            parsed = urlsplit(origin)
        except Exception:
            return False
        if parsed.scheme not in ("http", "https"):
            return False
        allowed = getattr(self.server, "allowed_hosts", None)
        if allowed:
            return parsed.netloc.lower() in allowed
        return parsed.netloc.lower() == self.headers.get("Host", "").strip().lower()

    def _authenticated(self) -> bool:
        """DASHBOARD_TOKEN auth (constant-time). Unset token = permitted ONLY
        because non-loopback binds refuse to start without one (see
        start_dashboard); on loopback an unset token preserves the local
        zero-friction workflow and same-machine automation."""
        expected = _dashboard_token()
        if not expected:
            return True
        supplied = self.headers.get("X-Scrooge-Token", "")
        return bool(supplied) and _secrets_mod.compare_digest(supplied, expected)

    def do_POST(self):
        if not self._host_allowed():
            return self._deny(421, "host rejected")
        if not self._origin_allowed():
            return self._deny(403, "origin rejected")
        if not self._authenticated():
            return self._deny(401, "authentication required")
        return self._do_post_inner()

    def _do_post_inner(self):
        try:
            if self.path.startswith("/api/pp/retire"):
                payload = self._read_json()
                try:
                    cell = str(payload.get("cell") or "")
                    result = self._engine.pp.retire_cell_grid(
                        cell, parent_pairs=set(self._engine.managers.keys()))
                    body = _j.dumps(result).encode()
                    ctype, code = "application/json", (200 if result.get("ok") else 409)
                    log.info("pp grid retirement requested cell=%s result=%s", cell, result)
                except Exception as exc:
                    body = _j.dumps({"ok": False, "error": str(exc)}).encode()
                    ctype, code = "application/json", 400
            elif self.path.startswith("/api/pp/toggle"):
                length = int(self.headers.get("Content-Length", "0") or 0)
                raw = self.rfile.read(length) if length else b""
                try:
                    payload = _j.loads(raw.decode() or "{}")
                    cfg = _write_pp_toggle(payload)
                    body = _j.dumps({"ok": True, "cfg": cfg}).encode()
                    ctype, code = "application/json", 200
                    log.info("pp_config updated via dashboard: %s", payload)
                except Exception as exc:
                    body = _j.dumps({"ok": False, "error": str(exc)}).encode()
                    ctype, code = "application/json", 400
            elif self.path.startswith("/api/config/exit"):
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
            elif self.path.startswith("/api/cell/status"):
                payload = self._read_json()
                try:
                    res = _set_cell_status(payload.get("pair"), payload.get("session"),
                                           payload.get("setup_id"), payload.get("status"))
                    body = _j.dumps({"ok": True, **res}).encode()
                    ctype, code = "application/json", 200
                    log.info("cell status %s/%s/%s: %s -> %s (dashboard)",
                             res["pair"], res["session"], res["setup_id"],
                             res["old_status"], res["status"])
                    try:                     # B-113: board must show it NOW
                        from ops import shadowboard as _sb
                        _sb.invalidate()
                    except Exception:
                        pass
                except Exception as exc:
                    body = _j.dumps({"ok": False, "error": str(exc)}).encode()
                    ctype, code = "application/json", 400
            elif self.path.startswith("/api/cell/exit"):
                payload = self._read_json()
                try:
                    res = _set_cell_exit(payload.get("pair"), payload.get("session"),
                                         payload.get("setup_id"), payload.get("exit") or {})
                    body = _j.dumps({"ok": True, **res}).encode()
                    ctype, code = "application/json", 200
                    log.info("cell exit %s/%s/%s updated (dashboard): %s",
                             res["pair"], res["session"], res["setup_id"], res["exit"])
                except Exception as exc:
                    body = _j.dumps({"ok": False, "error": str(exc)}).encode()
                    ctype, code = "application/json", 400
            elif self.path.startswith("/api/credentials"):
                payload = self._read_json()
                try:
                    body = _j.dumps(_save_credentials(payload)).encode()
                    ctype, code = "application/json", 200
                except Exception as exc:
                    body = _j.dumps({"ok": False, "error": str(exc)}).encode()
                    ctype, code = "application/json", 400
            elif self.path.startswith("/api/mode"):
                payload = self._read_json()
                code, obj = _set_mode(payload)
                body = _j.dumps(obj).encode()
                ctype = "application/json"
            elif self.path.startswith("/api/trading"):
                payload = self._read_json()
                code, obj = _set_trading(payload)
                body = _j.dumps(obj).encode()
                ctype = "application/json"
            elif self.path.startswith("/api/governor"):
                payload = self._read_json()
                code, obj = _governor_post(payload)
                body = _j.dumps(obj).encode()
                ctype = "application/json"
            else:
                body, ctype, code = b"not found", "text/plain", 404
        except Exception as exc:
            log.exception("dashboard POST handler error: %s", exc)
            body = _j.dumps({"ok": False, "error": str(exc)}).encode()
            ctype, code = "application/json", 500
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass
