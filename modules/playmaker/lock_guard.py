"""modules/playmaker/lock_guard.py — Governance enforcement for LOCKED cells.

LOCKED cells are validated/dialed-in (pair, session) cells registered in
config/locked_cells.json. Once locked, their governance parameters (gates,
inversion, SL, etc.) are frozen at snapshot time. This module:

  1. Reads the lock file fresh each call (tiny file; matches _pm_load pattern).
  2. Serves frozen governance to pick_best() so locked cells always use their
     locked parameters regardless of live config drift.
  3. Rate-limited drift logging so operators know when live config diverges from
     the locked state without log flooding.
  4. Startup fingerprint check to detect when code/profile inputs have changed
     since the snapshot was taken.
  5. Per-session throttle to cap opens in a locked cell to a maximum per
     session-instance (protects against repeated re-entry in one session).

Fail-open design: any exception returns None / empty results. The bot must
NEVER crash because of the lock file.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("v5.lock_guard")

_LOCK_PATH = Path(__file__).resolve().parents[2] / "config" / "locked_cells.json"

# ── Rate-limit state ─────────────────────────────────────────────────────────
# Module-level dicts so they persist across calls within a process.
# Each key is (pair, session) or (pair, session, field); value is last-log epoch.
_warn_rate: dict = {}           # warn-once-per-hour for load errors: key = "load"
_drift_rate: dict = {}          # once per 3600s per (pair, session, field)


def _load() -> Optional[dict]:
    """Fresh json.load of locked_cells.json. Fail-open: returns None on any error."""
    try:
        return json.loads(_LOCK_PATH.read_text())
    except Exception as exc:
        now = time.time()
        if now - _warn_rate.get("load", 0) >= 3600:
            _warn_rate["load"] = now
            log.warning("lock_guard: failed to load %s: %s (lock inert)", _LOCK_PATH, exc)
        return None


def locked_governance(pair: str, session: str) -> Optional[dict]:
    """Return the frozen governance dict for (pair, session), or None if not locked
    or snapshot not yet generated.  Overrides from the 'overrides' list are applied
    on top before returning."""
    data = _load()
    if data is None:
        return None
    for cell in data.get("cells", []):
        if cell.get("pair") == pair and cell.get("session") == session:
            snap = cell.get("snapshot")
            if snap is None:
                return None          # lock registered but not snapshotted yet — inert
            gov = dict(snap.get("governance", {}))
            # Apply overrides that match this (pair, session)
            for ov in data.get("overrides", []):
                if ov.get("pair") == pair and ov.get("session") == session:
                    field = ov.get("field")
                    if field and field in gov:
                        gov[field] = ov["value"]
            return gov
    return None


def locked_traded_directions(pair: str, session: str) -> set:
    """Traded directions locked for (pair, session)."""
    data = _load()
    if data is None:
        return set()
    dirs = set()
    for cell in data.get("cells", []):
        if cell.get("pair") == pair and cell.get("session") == session:
            dirs.add(cell.get("dir"))
    return dirs


def throttle_cap(pair: str, session: str) -> Optional[int]:
    """Return max_opens_per_session for this locked (pair, session), or None if not locked."""
    data = _load()
    if data is None:
        return None
    for cell in data.get("cells", []):
        if cell.get("pair") == pair and cell.get("session") == session:
            snap = cell.get("snapshot")
            if snap and "throttle" in snap:
                return snap["throttle"].get("max_opens_per_session")
    return None


def session_instance_key(session: str, now_utc: datetime) -> str:
    """Return "<session>@<YYYY-MM-DD>" where asia uses the date of the session START.

    Asia runs 22:00–07:00 UTC crossing midnight.  If hour >= 22, the session
    started today; if hour < 22 (i.e. we're in the early-morning half), the
    session started yesterday.  London/NY use the current UTC date.
    """
    if session == "asia":
        if now_utc.hour >= 22:
            date_str = now_utc.strftime("%Y-%m-%d")
        else:
            from datetime import timedelta
            date_str = (now_utc - timedelta(days=1)).strftime("%Y-%m-%d")
    else:
        date_str = now_utc.strftime("%Y-%m-%d")
    return f"{session}@{date_str}"


def log_drift(pair: str, session: str, field: str, live_val, locked_val) -> None:
    """Log a drift warning once per (pair, session, field) per 3600s."""
    key = (pair, session, field)
    now = time.time()
    if now - _drift_rate.get(key, 0) >= 3600:
        _drift_rate[key] = now
        log.warning(
            "LOCK_GUARD drift %s/%s %s live=%s locked=%s (using locked)",
            pair, session, field, live_val, locked_val
        )


# ── Code fingerprint ─────────────────────────────────────────────────────────

def compute_code_fingerprint(pair: str, session: str) -> str:
    """SHA-256 of canonical JSON of code inputs that affect locked cell behavior.

    Covers:
      - direction_profiles PROFILE_ASSIGNMENT entries for (pair, session, *)
      - resolved profile template weights for those entries
      - AGGREGATOR_RULES (serialisable representation)
      - momentum_profiles PROFILE_ASSIGNMENT/PAIR_TUNING/EVIDENCE_STRICTNESS
        for the pair/session
      - factor_sweep.json (pair, session) bucket
      - sessions.py SESSIONS dict
      - PAIR_SESSIONS[pair]
      - exit_config resolved step params for the pair
    """
    # Legacy profile modules were archived at the 2026-07-04 cell-era cutover
    # (V5 repo modules/archive/signals_legacy/). Locks are RETIRED; if the
    # modules are absent the fingerprint is meaningless — skip cleanly.
    try:
        import importlib.util
        if importlib.util.find_spec("modules.signals.direction_profiles") is None:
            return None
        # -- direction profiles --
        from modules.signals.direction_profiles import (
            PROFILE_ASSIGNMENT as DIR_ASSIGN,
            AGGREGATOR_RULES,
            get_factor_defs,
        )
        from modules.signals.momentum_profiles import (
            PROFILE_ASSIGNMENT as MOM_ASSIGN,
            PAIR_TUNING,
            EVIDENCE_STRICTNESS,
        )
        from config.pairs import PAIR_SESSIONS
        from config.sessions import SESSIONS
        from modules.management.ratchet import _load_config as _exit_load

        # Direction profile entries for (pair, session, long) and (pair, session, short)
        dir_entries = {}
        for direction in ("long", "short"):
            cell = DIR_ASSIGN.get(pair, {}).get(session, {}).get(direction)
            if cell is not None:
                profile_name, evidence = cell
                dir_entries[direction] = {
                    "profile": profile_name,
                    "evidence": evidence,
                    "weights": get_factor_defs(pair, session, direction),
                }
            else:
                dir_entries[direction] = None

        # AGGREGATOR_RULES — strip lambdas, keep name/amplify/multiplier/evidence/confidence
        agg_rules_serialisable = []
        for rule in AGGREGATOR_RULES:
            agg_rules_serialisable.append({
                "name":       rule.get("name"),
                "amplify":    rule.get("amplify"),
                "multiplier": rule.get("multiplier"),
                "evidence":   rule.get("evidence"),
                "confidence": rule.get("confidence"),
            })

        # Momentum profile entries for this pair/session
        mom_entries = {}
        for direction in ("long", "short"):
            key = (pair, session, direction)
            if key in MOM_ASSIGN:
                mom_entries[str(key)] = list(MOM_ASSIGN[key])
        mom_pair_tuning = PAIR_TUNING.get(pair, {})

        # factor_sweep.json bucket for (pair, session)
        _sweep_path = Path(__file__).resolve().parents[2] / "modules" / "signals" / "factor_sweep.json"
        try:
            _sweep = json.loads(_sweep_path.read_text())
            sweep_bucket = _sweep.get(pair, {}).get(session, None)
            # Trim to essential ranked keys only (full bucket is huge)
            if sweep_bucket and "ranked" in sweep_bucket:
                sweep_bucket = {
                    "n_rows":     sweep_bucket.get("n_rows"),
                    "n_features": sweep_bucket.get("n_features"),
                    "top_ranked": [r[0] for r in sweep_bucket["ranked"][:10]],
                }
        except Exception:
            sweep_bucket = None

        # exit_config resolved step params for the pair
        exit_cfg = _exit_load(pair)
        exit_step_params = {
            "initial_sl_pips":   exit_cfg.get("initial_sl_pips"),
            "step_trigger_pips": exit_cfg.get("step_trigger_pips"),
            "step_trail_pips":   exit_cfg.get("step_trail_pips"),
            "step_size_pips":    exit_cfg.get("step_size_pips"),
            "step_engage_min":   exit_cfg.get("step_engage_min"),
            "step_cadence_min":  exit_cfg.get("step_cadence_min"),
            "tp1_enabled":       exit_cfg.get("tp1_enabled"),
            "tp2_enabled":       exit_cfg.get("tp2_enabled"),
        }

        payload = {
            "pair":            pair,
            "session":         session,
            "dir_profiles":    dir_entries,
            "aggregator_rules": agg_rules_serialisable,
            "mom_profiles":    mom_entries,
            "mom_pair_tuning": mom_pair_tuning,
            "evidence_strictness": dict(EVIDENCE_STRICTNESS),
            "sweep_bucket":    sweep_bucket,
            "sessions":        {k: list(v) for k, v in SESSIONS.items()},
            "pair_sessions":   PAIR_SESSIONS.get(pair, []),
            "exit_step_params": exit_step_params,
        }
        canonical = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode()).hexdigest()
    except Exception as exc:
        log.warning("lock_guard: fingerprint computation failed for %s/%s: %s", pair, session, exc)
        return "error:" + str(exc)[:64]


def _fingerprint_skipped_note(logger):
    logger.info("lock_guard: legacy profile modules not present (archived at cell-era "
                "cutover) — code fingerprints skipped; locks are retired, cells govern.")


# ── Startup check ─────────────────────────────────────────────────────────────

def startup_check(logger) -> dict:
    """For each locked cell with a snapshot, recompute fingerprint and compare.

    On mismatch (with no override entry for field=="code_fingerprint"), logs
    CRITICAL. A recomputed fingerprint of None means the legacy modules are
    archived (cell era) — check is skipped quietly, not treated as drift.  Returns dict of {(pair, session): bool_ok} for the dashboard.
    """
    results: dict = {}
    data = _load()
    if data is None:
        return results

    for cell in data.get("cells", []):
        pair    = cell.get("pair")
        session = cell.get("session")
        snap    = cell.get("snapshot")
        if not snap:
            continue                        # no snapshot yet — skip

        stored_fp  = snap.get("code_fingerprint")
        live_fp    = compute_code_fingerprint(pair, session)
        if live_fp is None:
            # Legacy profile modules archived at cell-era cutover — locks are
            # retired; fingerprint comparison is meaningless. Skip quietly.
            _fingerprint_skipped_note(logger)
            results[(pair, session)] = True
            continue
        ok         = (stored_fp == live_fp)

        # Check if there's an explicit override approving the fingerprint mismatch
        override_present = any(
            ov.get("pair") == pair and ov.get("session") == session
            and ov.get("field") == "code_fingerprint"
            for ov in data.get("overrides", [])
        )

        if not ok and not override_present:
            logger.critical(
                "LOCK_GUARD CODE-DRIFT %s/%s: profile/code inputs changed since lock"
                " — locked cell behavior may differ; explicit override required",
                pair, session
            )

        results[(pair, session)] = ok

    return results
