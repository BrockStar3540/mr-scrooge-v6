"""config/cell_schema.py — THE canonical cell-config schema (review round 2).

One implementation, two consumers: the live hot-loader (modules/cells/cell.py
validates every (re)load and refuses structurally invalid configs) and the CLI
(research/tools/cell_config_validator.py, now a thin shim). A hot edit like
{"status": "ACTVE"} or {"exit": {"trail_pisp": 2.5}} can no longer reach the
trading process ahead of CI.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

VALID_SESSIONS = {"asia", "london", "ny"}
VALID_SIDES = {"long", "short"}
# Schema synced to live reality 2026-07-27 (external-review finding: the
# validator had drifted to the July-04 era and rejected all 18 live files while
# nothing enforced it — tests/test_cell_config_schema.py now makes schema drift
# a failing test instead of a silent gap).
VALID_CLASSES = {
    "FORMULA", "LEAN", "TIMING",              # generator-era classes
    "session_structure", "trend_pullback",    # ps-wall + discovery-engine shapes
    "book_replay",                            # D-4 strategy-book trials
    "classic", "box", "control",              # classic/control probe families
    "market_structure",                       # 2026-08-06: stop pools, impulse-
                                              # origin zones, EMA trend regime
}
VALID_STATUSES = {"ACTIVE", "PROBE", "SHADOW", "SUSPENDED", "DISABLED"}
# Pair universe: single source of truth is config/pairs.py — a list that exists
# in two files is two bugs (B-098 family; the dashboard server had the same
# defect until 2026-07-27).
from config.pairs import PAIRS as _PAIRS
VALID_PAIRS = set(_PAIRS)

# ── Error collector ────────────────────────────────────────────────────────────

class ValidationErrors:
    def __init__(self, path: str):
        self.path = path
        self.errors: list[str] = []

    def add(self, msg: str) -> None:
        self.errors.append(msg)

    def ok(self) -> bool:
        return len(self.errors) == 0

    def report(self) -> str:
        if self.ok():
            return f"OK  {self.path}"
        lines = [f"FAIL {self.path}  ({len(self.errors)} error(s)):"]
        for e in self.errors:
            lines.append(f"    • {e}")
        return "\n".join(lines)


# ── Field helpers ──────────────────────────────────────────────────────────────

def _require_str(obj: dict, key: str, ctx: str, errs: ValidationErrors,
                 choices: set | None = None) -> str | None:
    if key not in obj:
        errs.add(f"{ctx}: missing required field '{key}'")
        return None
    val = obj[key]
    if not isinstance(val, str):
        errs.add(f"{ctx}.{key}: must be a string, got {type(val).__name__}")
        return None
    if choices and val not in choices:
        errs.add(f"{ctx}.{key}: '{val}' not in allowed values {sorted(choices)}")
        return None
    return val


def _require_bool(obj: dict, key: str, ctx: str, errs: ValidationErrors) -> bool | None:
    if key not in obj:
        errs.add(f"{ctx}: missing required field '{key}'")
        return None
    val = obj[key]
    if not isinstance(val, bool):
        errs.add(f"{ctx}.{key}: must be a bool, got {type(val).__name__}")
        return None
    return val


def _require_number(obj: dict, key: str, ctx: str, errs: ValidationErrors,
                    allow_none: bool = False) -> float | None:
    if key not in obj:
        errs.add(f"{ctx}: missing required field '{key}'")
        return None
    val = obj[key]
    if val is None and allow_none:
        return None
    if not isinstance(val, (int, float)):
        errs.add(f"{ctx}.{key}: must be a number, got {type(val).__name__}")
        return None
    return float(val)


def _require_int(obj: dict, key: str, ctx: str, errs: ValidationErrors) -> int | None:
    if key not in obj:
        errs.add(f"{ctx}: missing required field '{key}'")
        return None
    val = obj[key]
    if not isinstance(val, int):
        errs.add(f"{ctx}.{key}: must be an int, got {type(val).__name__}")
        return None
    return val


def _no_unknown_fields(obj: dict, allowed: set, ctx: str, errs: ValidationErrors) -> None:
    extras = set(obj.keys()) - allowed
    if extras:
        errs.add(f"{ctx}: unknown fields {sorted(extras)}")


# ── Sub-validators ─────────────────────────────────────────────────────────────

def _validate_condition(cond: Any, idx: int, setup_id: str, sess: str,
                        errs: ValidationErrors) -> None:
    ctx = f"sessions.{sess}.setups[{setup_id}].conditions[{idx}]"
    if not isinstance(cond, dict):
        errs.add(f"{ctx}: must be a dict, got {type(cond).__name__}")
        return

    # feature is required
    if "feature" not in cond:
        errs.add(f"{ctx}: missing 'feature'")

    # Must be one of: absolute form (min/max) OR percentile form (pct_window_days etc.)
    has_abs = "min" in cond or "max" in cond
    has_pct = "pct_window_days" in cond or "pct_lo" in cond or "pct_hi" in cond

    if not has_abs and not has_pct:
        errs.add(f"{ctx}: must have either (min/max) or (pct_window_days/pct_lo/pct_hi)")

    if has_pct:
        # Percentile form requires resolved values (generator writes these)
        if "resolved" not in cond:
            errs.add(f"{ctx}: percentile-form condition missing 'resolved' array")
        else:
            res = cond["resolved"]
            if not isinstance(res, list) or len(res) != 2:
                errs.add(f"{ctx}: 'resolved' must be [lo, hi] array of length 2")
        if "resolved_at" not in cond:
            errs.add(f"{ctx}: percentile-form condition missing 'resolved_at'")
        _require_number(cond, "pct_window_days", ctx, errs)
        _require_number(cond, "pct_lo", ctx, errs)
        _require_number(cond, "pct_hi", ctx, errs)

    # Point-value trap: min == max for absolute form is a point value, not a range
    if has_abs and not has_pct:
        lo = cond.get("min")
        hi = cond.get("max")
        if lo is not None and hi is not None and lo == hi:
            errs.add(f"{ctx}: min==max ({lo}) is a point value, not a range — "
                     "use a range or percentile form")

    # Every condition must contribute to lineage somewhere (evidence block on setup)
    # (lineage at setup level, not per-condition — we just ensure it isn't totally missing)
    allowed = {
        "feature", "min", "max",
        "pct_window_days", "pct_lo", "pct_hi", "resolved", "resolved_at",
        "note", "lineage",
    }
    _no_unknown_fields(cond, allowed, ctx, errs)


def _validate_exit(exit_block: Any, ctx: str, errs: ValidationErrors) -> None:
    if not isinstance(exit_block, dict):
        errs.add(f"{ctx}.exit: must be a dict")
        return
    _require_number(exit_block, "sl_pips", ctx + ".exit", errs)
    _require_number(exit_block, "trigger_pips", ctx + ".exit", errs)
    _require_number(exit_block, "trail_pips", ctx + ".exit", errs)
    # Full live exit vocabulary (engine ExitParams, 2026-07-27 sync): ratchet
    # mode + ATR-scaled-trail bounds + display class + optional bracket fields.
    # v6.30.0 (operator 2026-08-18): two-phase ratchet — early engage lock
    # ahead of the step machine (engage 7.5 -> lock 6.0; step 9/2/2).
    allowed = {"sl_pips", "trigger_pips", "trail_pips",
               "mode", "trail_mult", "trail_min", "trail_max",
               "entry_cutoff_utc", "tp_pips", "timeout_min", "_class",
               "engage_pips", "engage_lock_pips"}
    _no_unknown_fields(exit_block, allowed, ctx + ".exit", errs)
    mode = exit_block.get("mode")
    if mode is not None and mode not in ("ratchet", "bracket"):
        errs.add(f"{ctx}.exit.mode: '{mode}' not in allowed values ['bracket', 'ratchet']")


def _validate_sizing(sizing: Any, ctx: str, errs: ValidationErrors) -> None:
    if not isinstance(sizing, dict):
        errs.add(f"{ctx}.sizing: must be a dict")
        return
    _require_number(sizing, "risk_pct", ctx + ".sizing", errs)
    mods = sizing.get("size_modulators")
    if mods is not None:
        if not isinstance(mods, list):
            errs.add(f"{ctx}.sizing.size_modulators: must be a list")
        else:
            for i, m in enumerate(mods):
                mctx = f"{ctx}.sizing.size_modulators[{i}]"
                if not isinstance(m, dict):
                    errs.add(f"{mctx}: must be a dict")
                    continue
                _require_str(m, "feature", mctx, errs)
                _require_number(m, "mult", mctx, errs)
                if "lineage" not in m:
                    errs.add(f"{mctx}: size_modulator missing 'lineage'")
                # gte or lte required
                if "gte" not in m and "lte" not in m:
                    errs.add(f"{mctx}: size_modulator must have 'gte' or 'lte'")
    allowed = {"risk_pct", "size_modulators"}
    _no_unknown_fields(sizing, allowed, ctx + ".sizing", errs)


def _validate_tripwires(tw: Any, ctx: str, errs: ValidationErrors) -> None:
    if not isinstance(tw, dict):
        errs.add(f"{ctx}.tripwires: must be a dict")
        return
    allowed_tw = {"monthly", "fast"}
    _no_unknown_fields(tw, allowed_tw, ctx + ".tripwires", errs)

    monthly = tw.get("monthly")
    if monthly is not None:
        if not isinstance(monthly, dict):
            errs.add(f"{ctx}.tripwires.monthly: must be a dict")
        else:
            _require_str(monthly, "metric", ctx + ".tripwires.monthly", errs)
            if "gte" not in monthly and "lte" not in monthly:
                errs.add(f"{ctx}.tripwires.monthly: must have 'gte' or 'lte' "
                         "(use null value for size-only mode)")
            _require_str(monthly, "action", ctx + ".tripwires.monthly", errs)

    fast = tw.get("fast")
    if fast is not None:
        if not isinstance(fast, dict):
            errs.add(f"{ctx}.tripwires.fast: must be a dict")
        else:
            _require_int(fast, "last_n", ctx + ".tripwires.fast", errs)
            _require_number(fast, "min_ev", ctx + ".tripwires.fast", errs)
            _require_str(fast, "action", ctx + ".tripwires.fast", errs)


def _validate_evidence(ev: Any, ctx: str, errs: ValidationErrors) -> None:
    if not isinstance(ev, dict):
        errs.add(f"{ctx}.evidence: must be a dict")
        return
    # ev_seq: number OR null (null = shadow-only, no OOS sequential EV yet)
    if "ev_seq" not in ev:
        errs.add(f"{ctx}.evidence: missing 'ev_seq'")
    elif ev["ev_seq"] is not None and not isinstance(ev["ev_seq"], (int, float)):
        errs.add(f"{ctx}.evidence.ev_seq: must be a number or null")
    if "source" not in ev:
        errs.add(f"{ctx}.evidence: missing 'source' (lineage requirement)")
    allowed = {"ev_seq", "wr", "oos_years_positive", "drift", "source",
               "n_floor_status", "holdout_months_positive"}
    _no_unknown_fields(ev, allowed, ctx + ".evidence", errs)


def _validate_setup(setup: Any, sess: str, errs: ValidationErrors) -> None:
    if not isinstance(setup, dict):
        errs.add(f"sessions.{sess}: setup must be a dict")
        return

    sid = setup.get("id", "<no-id>")
    ctx = f"sessions.{sess}.setups[{sid}]"

    _require_str(setup, "id", ctx, errs)
    _require_str(setup, "side", ctx, errs, choices=VALID_SIDES)
    _require_str(setup, "class", ctx, errs, choices=VALID_CLASSES)
    _require_str(setup, "status", ctx, errs, choices=VALID_STATUSES)
    _require_int(setup, "horizon_min", ctx, errs)

    # Conditions
    conds = setup.get("conditions")
    if conds is None:
        errs.add(f"{ctx}: missing 'conditions'")
    elif not isinstance(conds, list):
        errs.add(f"{ctx}: 'conditions' must be a list")
    else:
        if len(conds) == 0:
            errs.add(f"{ctx}: 'conditions' list is empty — "
                     "a setup with no conditions is invalid; use setups:[] for NO-SIDE")
        for i, c in enumerate(conds):
            _validate_condition(c, i, str(sid), sess, errs)

    # Exit block — required
    if "exit" not in setup:
        errs.add(f"{ctx}: missing 'exit' block")
    else:
        _validate_exit(setup["exit"], ctx, errs)

    # Sizing — required
    if "sizing" not in setup:
        errs.add(f"{ctx}: missing 'sizing' block")
    else:
        _validate_sizing(setup["sizing"], ctx, errs)

    # Tripwires — optional but if present must be valid
    if "tripwires" in setup:
        _validate_tripwires(setup["tripwires"], ctx, errs)

    # Evidence — required (every setup must carry lineage)
    if "evidence" not in setup:
        errs.add(f"{ctx}: missing 'evidence' block — every setup requires lineage")
    else:
        _validate_evidence(setup["evidence"], ctx, errs)

    allowed_setup = {
        "id", "side", "class", "status", "horizon_min",
        "conditions", "exit", "sizing", "tripwires", "evidence", "notes",
        "wired",   # date the setup entered the book (QUEUED-row age, 2026-07-31)
        "_note",         # operator margin notes (e.g. side-flip history)
        "manual_only",   # governor opt-out: this setup is hand-ruled only
        "watch",         # operator watch marker (emoji) — rendered on the board
                         # so a cohort can be followed at a glance. Display only:
                         # nothing in the governor, scorer or gates reads it.
    }
    _no_unknown_fields(setup, allowed_setup, ctx, errs)


def _validate_structure(struct: Any, sess: str, errs: ValidationErrors) -> None:
    ctx = f"sessions.{sess}.structure"
    if not isinstance(struct, dict):
        errs.add(f"{ctx}: must be a dict")
        return
    # tier/rates are nullable (2026-07-27): hand-authored new-pair hypothesis
    # cells carry null structure — "no truth-matrix evidence yet" is a valid,
    # explicit state, distinct from a missing field.
    tier = struct.get("tier")
    if "tier" not in struct:
        errs.add(f"{ctx}: missing 'tier' (use null for no-evidence cells)")
    elif tier is not None and tier not in (1, 2, 3):
        errs.add(f"{ctx}.tier: must be 1, 2, 3, or null")
    for k in ("rh_offer_rate_60m", "dead_rate_60m"):
        if k not in struct:
            errs.add(f"{ctx}: missing '{k}' (use null for no-evidence cells)")
        elif struct[k] is not None and not isinstance(struct[k], (int, float)):
            errs.add(f"{ctx}.{k}: must be a number or null")
    if "lineage" not in struct:
        errs.add(f"{ctx}: missing 'lineage' (lineage requirement for structure block)")
    allowed = {"tier", "rh_offer_rate_60m", "dead_rate_60m", "lineage", "ev_gross_long",
               "ev_gross_short"}
    _no_unknown_fields(struct, allowed, ctx, errs)


def _validate_cell_cfg(cfg: Any, sess: str, errs: ValidationErrors) -> None:
    if not isinstance(cfg, dict):
        errs.add(f"sessions.{sess}: must be a dict")
        return

    _require_bool(cfg, "enabled", f"sessions.{sess}", errs)

    # Structure block — required
    if "structure" not in cfg:
        errs.add(f"sessions.{sess}: missing 'structure' block")
    else:
        _validate_structure(cfg["structure"], sess, errs)

    # Setups — required, may be empty list (NO-SIDE)
    if "setups" not in cfg:
        errs.add(f"sessions.{sess}: missing 'setups' (use [] for NO-SIDE)")
    else:
        setups = cfg["setups"]
        if not isinstance(setups, list):
            errs.add(f"sessions.{sess}: 'setups' must be a list")
        else:
            # Check for duplicate IDs within session
            ids_seen: set[str] = set()
            for setup in setups:
                sid = setup.get("id") if isinstance(setup, dict) else None
                if sid is not None:
                    if sid in ids_seen:
                        errs.add(f"sessions.{sess}: duplicate setup id '{sid}'")
                    ids_seen.add(sid)
                _validate_setup(setup, sess, errs)

    allowed_cell = {"enabled", "structure", "setups", "notes"}
    _no_unknown_fields(cfg, allowed_cell, f"sessions.{sess}", errs)


# ── Top-level validator ────────────────────────────────────────────────────────

def _validate_document(data: dict, errs: "ValidationErrors") -> None:
    """The full document walk — shared by validate_file and the live loader."""
    _require_str(data, "pair", "top", errs, choices=VALID_PAIRS)
    _require_str(data, "generated", "top", errs)
    _require_str(data, "generator", "top", errs)

    if "sessions" not in data:
        errs.add("top: missing 'sessions' block")
        return
    sessions = data["sessions"]
    if not isinstance(sessions, dict):
        errs.add("top.sessions: must be a dict")
        return
    unknown_sess = set(sessions.keys()) - VALID_SESSIONS
    if unknown_sess:
        errs.add(f"top.sessions: unknown session keys {sorted(unknown_sess)}")
    for sess, cfg in sessions.items():
        if sess not in VALID_SESSIONS:
            continue  # already flagged above
        _validate_cell_cfg(cfg, sess, errs)
    allowed_top = {"pair", "generated", "generator", "sessions", "notes"}
    _no_unknown_fields(data, allowed_top, "top", errs)


def validate_file(path: Path) -> ValidationErrors:
    errs = ValidationErrors(str(path))
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        errs.add(f"JSON parse error: {exc}")
        return errs
    except OSError as exc:
        errs.add(f"Cannot read file: {exc}")
        return errs
    if not isinstance(data, dict):
        errs.add("Top-level must be a JSON object")
        return errs
    _validate_document(data, errs)
    return errs


# ── Programmatic API (live hot-loader) ───────────────────────────────────────
from dataclasses import dataclass as _dataclass


@_dataclass(frozen=True)
class SchemaResult:
    errors: tuple

    @property
    def ok(self) -> bool:
        return not self.errors


def validate_pair_config(data, source="<memory>") -> SchemaResult:
    """Validate an in-memory pair config dict. Same rules as validate_file."""
    errs = ValidationErrors(str(source))
    if not isinstance(data, dict):
        errs.add("top level: must be a JSON object")
        return SchemaResult(tuple(errs.errors))
    _validate_document(data, errs)
    return SchemaResult(tuple(errs.errors))
