"""modules/signals/formula_shadow.py — Formula-condition shadow stamps (log-only).

Mirrors the SHADOW_PROFILE / CAL instrumentation pattern in core/engine.py.
Once per pair per scan cycle the engine calls formula_shadow.get_entries_for()
and formula_shadow.evaluate() for each registry entry matching the pair's current
session.  When ALL conditions pass, the engine emits a FORMULA log line —
execution unchanged.

Registry statuses
-----------------
  PRIMARY  — passed full deep out-of-sample validation (8yr sequential, 7/7 OOS
             years positive).  These are live-confirmation candidates.
  CONTROL  — positive in 2026 convergence study but failed deep OOS (negative
             every year 2019-2025 or sequential loss).  Stamps continue to emit
             so live data can falsify or confirm the deep-history verdict.
  INACTIVE — required features absent from live MarketView; emit nothing until
             feed extended.

Rolling-percentile thresholds (PRIMARY formulas)
-------------------------------------------------
Hardcoded absolute 2026 values are regime-specific and fail prior years.
PRIMARY formulas use ROLLING percentile bounds recomputed from a trailing
90-day window of session bars.  The bounds live in a JSON file:
  config/formula_rolling_pct.json
Schema:
  { "GBP_USD/london/long": { "rvol_5bar": [lo_abs, hi_abs], "updated": "ISO" } }
If the file is absent or a cell's entry is stale (>48h), the formula falls
back to the 2026 hardcoded values and logs FORMULA_WARN once per day.
The JSON is updated monthly by the same process that regenerates the registry
(or more frequently by a cron job on the Mini).

# TO-BE-GENERATED-MONTHLY via research/tools/formula_convergence.py
# (formula_wire_ready.csv + convergence_results.csv produced 2026-07-04;
# deep-OOS validation results in ~/v5-formula-history/ on Mini, verdict_table.csv).

Kill-switch: defaults.formula_shadow_enabled in config/playmaker_config.json
(hot-reload, same pattern as calibration_log_enabled / profile_shadow_enabled).
Accessor: pm_formula_shadow_enabled() in modules/playmaker/playmaker.py.

Scorer: research/tools/formula_shadow_score.py --since YYYY-MM-DD
(greps FORMULA lines, simulates ratchet at each formula's target geometry,
reports PRIMARY vs CONTROL separately).
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from typing import NamedTuple, Optional

from .base import MarketView

log = logging.getLogger("v5.formula_shadow")

_ROLLING_PCT_PATH = (Path(__file__).resolve().parents[2]
                     / "config" / "formula_rolling_pct.json")
_ROLLING_STALE_H = 48   # hours before rolling bounds are considered stale


# ── Registry entry ────────────────────────────────────────────────────────────

class FormulaEntry(NamedTuple):
    """One formula from the convergence + deep-OOS validation study."""
    cell: str                           # "PAIR/session/direction"
    pair: str
    session: str
    direction: str
    horizon: int                        # minutes (60 or 240)
    conditions: list                    # [(feature_name, lo_abs, hi_abs), ...]
    # percentile labels for the 2026-calibration window; parallel to conditions
    conditions_pct: list                # [(feature_name, lo_pct, hi_pct), ...]
    use_rolling_pct: bool               # True = look up bounds in formula_rolling_pct.json
    target_sl: float                    # pips
    target_trigger: float               # pips
    target_trail: float                 # pips
    expected_ev: float                  # net-of-spread pips (SEQUENTIAL for CONTROL)
    holdout_months_positive: int        # months where ev_positive=True in convergence
    status: str                         # "PRIMARY" | "CONTROL" | "INACTIVE"
    inactive_reason: str                # empty when status != INACTIVE


# ── Rolling-percentile cache ──────────────────────────────────────────────────

def _load_rolling_pct() -> dict:
    """Load formula_rolling_pct.json.  Returns {} if file missing or unreadable."""
    try:
        return json.loads(_ROLLING_PCT_PATH.read_text())
    except Exception:
        return {}


def _rolling_bounds(cell: str, feature: str,
                    fallback_lo: float, fallback_hi: float) -> tuple[float, float]:
    """Return (lo, hi) for feature from rolling JSON, or fallback if absent/stale."""
    cache = _load_rolling_pct()
    entry = cache.get(cell, {})
    feat_vals = entry.get(feature)
    updated_str = entry.get("updated")
    if feat_vals and updated_str:
        try:
            updated = datetime.fromisoformat(updated_str)
            age_h = (datetime.now(timezone.utc) - updated).total_seconds() / 3600
            if age_h <= _ROLLING_STALE_H:
                return float(feat_vals[0]), float(feat_vals[1])
        except Exception:
            pass
    return fallback_lo, fallback_hi


# ── Registry  (TO-BE-GENERATED-MONTHLY) ──────────────────────────────────────
# Source: convergence_results.csv (formula_wire_ready.csv + convergence_results.csv,
# 2026-07-04) + deep-OOS validation in ~/v5-formula-history/ on Mini.
#
# Excluded (not tradeable):
#   - USD_CHF: pair killed 2026-07-01 (enabled=false in playmaker_config.json)
#   - AUD_JPY/ny: AUD_JPY/ny/long + short both in disabled_cells
#
# Deep-OOS validation verdict (verdict_table.csv, Mini):
#   PRIMARY (pass 7/7 OOS years + sequential positive):
#     GBP_USD/london/long 240m — rvol_5bar low-quartile band
#       ev_sequential=+0.35p, all years 2019-2025 positive, STABLE drift
#       NOTE: conditions use ROLLING PERCENTILE (not 2026 absolute) — see above.
#   CONTROL (positive in 2026 convergence but failed deep OOS):
#     USD_JPY/ny/long 60m  — negative 2019-2025, sequential loss
#     GBP_USD/ny/short 60m — negative 2019-2025, sequential loss
#     AUD_USD/ny/short 60m — failed deep OOS
#     (stamps continue to emit as falsification data)
#   INACTIVE (feed gap — features not on MarketView):
#     GBP_USD/london/long using pdl/low/d_high (original convergence conditions)
#     USD_JPY/ny/long 240m using q_atrn_m5

_REGISTRY: list[FormulaEntry] = [

    # ════════════════════════════════════════════════════════════════════════
    # PRIMARY — passed deep out-of-sample validation
    # ════════════════════════════════════════════════════════════════════════

    # ── GBP_USD / london / long — horizon 240m ─────────────────────────────
    # Deep-OOS: 7/7 years positive, sequential +0.35p, STABLE drift.
    # Feature: rvol_5bar in rolling-percentile band [p4.8, p25.2].
    # 2026 absolute fallback: [0.371479, 0.669169] (p4.8–p25.2 in 2026 data).
    # ROLLING bounds preferred: look up config/formula_rolling_pct.json.
    # Best geo from convergence: SL=12, trig=10, trail=1.5 (best_cell row).
    # expected_ev from SEQUENTIAL validation (+0.35p, conservative).
    FormulaEntry(
        cell="GBP_USD/london/long",
        pair="GBP_USD", session="london", direction="long",
        horizon=240,
        conditions=[
            ("rvol_5bar", 0.371479, 0.669169),  # 2026 fallback; see use_rolling_pct
        ],
        conditions_pct=[
            ("rvol_5bar", 4.8, 25.2),
        ],
        use_rolling_pct=True,
        target_sl=12.0, target_trigger=10.0, target_trail=1.5,
        expected_ev=+0.35,       # sequential OOS, conservative
        holdout_months_positive=2,
        status="PRIMARY",
        inactive_reason="",
    ),

    # ════════════════════════════════════════════════════════════════════════
    # CONTROL — 2026 convergence positive but failed deep OOS
    # Stamps emitted for live falsification; expected_ev from sequential results
    # ════════════════════════════════════════════════════════════════════════

    # ── USD_JPY / ny / long — horizon 60m ──────────────────────────────────
    # Deep-OOS: negative 2019-2025, sequential loss.
    # 2026 convergence best_cell ev=+1.199 is a 2026-pocket artifact.
    # Expected sequential EV: negative (mark as negative to flag falsification).
    # atr_5m in [p16.8, p70.4] abs=[2.703442, 6.331820]
    FormulaEntry(
        cell="USD_JPY/ny/long",
        pair="USD_JPY", session="ny", direction="long",
        horizon=60,
        conditions=[
            ("atr_5m", 2.703442, 6.331820),
        ],
        conditions_pct=[
            ("atr_5m", 16.8, 70.4),
        ],
        use_rolling_pct=False,
        target_sl=20.0, target_trigger=3.0, target_trail=1.5,
        expected_ev=-1.0,        # sequential OOS: negative; convergence +1.199 was 2026 artifact
        holdout_months_positive=2,
        status="CONTROL",
        inactive_reason="",
    ),

    # ── GBP_USD / ny / short — horizon 60m ─────────────────────────────────
    # Deep-OOS: negative 2019-2025, sequential loss.
    # 2026 convergence best_cell ev=+0.914 is a 2026-pocket artifact.
    # rvol_5bar in [p4.8, p25.2] abs=[0.371479, 0.669169]
    FormulaEntry(
        cell="GBP_USD/ny/short",
        pair="GBP_USD", session="ny", direction="short",
        horizon=60,
        conditions=[
            ("rvol_5bar", 0.371479, 0.669169),
        ],
        conditions_pct=[
            ("rvol_5bar", 4.8, 25.2),
        ],
        use_rolling_pct=False,
        target_sl=12.0, target_trigger=3.0, target_trail=1.5,
        expected_ev=-1.0,        # sequential OOS: negative; convergence +0.914 was 2026 artifact
        holdout_months_positive=2,
        status="CONTROL",
        inactive_reason="",
    ),

    # ── AUD_USD / ny / short — horizon 60m ─────────────────────────────────
    # Deep-OOS: failed validation.
    # 2026 convergence best_cell ev=+0.394.
    # atr_conc in [p13.9, p35.5] abs=[0.177600, 0.241631]
    FormulaEntry(
        cell="AUD_USD/ny/short",
        pair="AUD_USD", session="ny", direction="short",
        horizon=60,
        conditions=[
            ("atr_conc", 0.177600, 0.241631),
        ],
        conditions_pct=[
            ("atr_conc", 13.9, 35.5),
        ],
        use_rolling_pct=False,
        target_sl=10.0, target_trigger=3.0, target_trail=1.5,
        expected_ev=-0.5,        # sequential OOS: negative; convergence +0.394 was 2026 artifact
        holdout_months_positive=2,
        status="CONTROL",
        inactive_reason="",
    ),

    # ════════════════════════════════════════════════════════════════════════
    # INACTIVE — required features absent from live MarketView
    # These entries exist for documentation; evaluate() will warn and skip.
    # ════════════════════════════════════════════════════════════════════════

    # ── GBP_USD / london / long 240m — original convergence conditions ──────
    # pdl, low, d_high not present on MarketView.
    # Superseded by PRIMARY formula above (rvol_5bar rolling-pct).
    # Kept for reference; INACTIVE.
    FormulaEntry(
        cell="GBP_USD/london/long",
        pair="GBP_USD", session="london", direction="long",
        horizon=240,
        conditions=[
            ("pdl",    1.220220, 1.353820),
            ("low",    1.272920, 1.343980),
            ("d_high", 1.209540, 1.415820),
        ],
        conditions_pct=[
            ("pdl",    0.0,  85.4),
            ("low",    0.0,  50.1),
            ("d_high", 0.0, 100.0),
        ],
        use_rolling_pct=False,
        target_sl=12.0, target_trigger=10.0, target_trail=1.5,
        expected_ev=+0.154,
        holdout_months_positive=1,
        status="INACTIVE",
        inactive_reason="INACTIVE-pending-feed-extension: pdl, low, d_high not on MarketView",
    ),

    # ── USD_JPY / ny / long 240m — q_atrn_m5 condition ─────────────────────
    # q_atrn_m5 not present on MarketView.
    FormulaEntry(
        cell="USD_JPY/ny/long",
        pair="USD_JPY", session="ny", direction="long",
        horizon=240,
        conditions=[
            ("q_atrn_m5", 0.019818, 0.420425),
        ],
        conditions_pct=[
            ("q_atrn_m5", 16.6, 55.0),
        ],
        use_rolling_pct=False,
        target_sl=20.0, target_trigger=3.0, target_trail=1.5,
        expected_ev=-0.593,
        holdout_months_positive=0,
        status="INACTIVE",
        inactive_reason="INACTIVE-pending-feed-extension: q_atrn_m5 not on MarketView",
    ),
]

# ── Index: (pair, session) -> list of registry entries ───────────────────────
_INDEX: dict[tuple[str, str], list[FormulaEntry]] = {}
for _e in _REGISTRY:
    _k = (_e.pair, _e.session)
    _INDEX.setdefault(_k, []).append(_e)

# ── Per-day warn-once tracker for missing features ────────────────────────────
_warned_feature: dict[tuple[str, str], date] = {}   # (cell, feature) -> last warn date
_warned_rolling:  dict[str, date] = {}               # cell -> last rolling-stale warn date


def formula_shadow_enabled() -> bool:
    """True unless the module itself is broken — external kill-switch is in playmaker."""
    return True


def get_entries_for(pair: str, session: str) -> list[FormulaEntry]:
    """Return all registry entries for this (pair, session)."""
    return _INDEX.get((pair, session), [])


# Sentinel for missing attributes (avoids shadowing None)
_MISSING = object()


def evaluate(entry: FormulaEntry, view: MarketView) -> tuple[int, int]:
    """Check entry's conditions against view.

    For PRIMARY entries with use_rolling_pct=True, looks up rolling bounds
    from config/formula_rolling_pct.json (falls back to 2026 absolute values
    with a once-per-day warning when stale or absent).

    Returns (n_met, n_total).  Missing features are logged once per day as
    FORMULA_WARN and counted as not-met (never crash).
    """
    if entry.status == "INACTIVE":
        # Still call through so missing-feature warnings fire for tracking purposes
        pass

    today = date.today()
    n_met = 0
    n_total = len(entry.conditions)

    # Check rolling-pct staleness once per day for PRIMARY entries
    if entry.use_rolling_pct and entry.status == "PRIMARY":
        cache = _load_rolling_pct()
        cell_cache = cache.get(entry.cell, {})
        updated_str = cell_cache.get("updated")
        stale = True
        if updated_str:
            try:
                updated = datetime.fromisoformat(updated_str)
                age_h = (datetime.now(timezone.utc) - updated).total_seconds() / 3600
                stale = age_h > _ROLLING_STALE_H
            except Exception:
                pass
        if stale and _warned_rolling.get(entry.cell) != today:
            _warned_rolling[entry.cell] = today
            log.warning(
                "FORMULA_WARN %s rolling-pct bounds absent or stale (>%dh) — "
                "using 2026 absolute fallback; update config/formula_rolling_pct.json",
                entry.cell, _ROLLING_STALE_H,
            )

    for feat, lo_fallback, hi_fallback in entry.conditions:
        val = getattr(view, feat, _MISSING)
        if val is _MISSING:
            warn_key = (entry.cell, feat)
            if _warned_feature.get(warn_key) != today:
                _warned_feature[warn_key] = today
                log.warning(
                    "FORMULA_WARN %s condition unreadable: feature '%s' missing "
                    "from MarketView — formula marked %s in registry",
                    entry.cell, feat, entry.status,
                )
            continue  # count as not met; do not crash

        # Resolve bounds (rolling for PRIMARY, absolute for others)
        if entry.use_rolling_pct:
            lo, hi = _rolling_bounds(entry.cell, feat, lo_fallback, hi_fallback)
        else:
            lo, hi = lo_fallback, hi_fallback

        if lo <= val <= hi:
            n_met += 1

    return n_met, n_total
