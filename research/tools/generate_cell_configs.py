#!/usr/bin/env python3
"""research/tools/generate_cell_configs.py — Generate config/cells/<PAIR>.json for all 8 pairs.

Evidence sources:
  - Tier / EV gross:    research/sessions/2026-07-03_truth_matrix_envelope/ratchet_ev_cells.csv
  - RH rates (60m):     research/sessions/2026-07-04_range_harvest/cell_base_rates_multihorizon.csv
  - Lean features:      config/cell_calibration.json  (direction_lean block)
  - TIMING atr_5m (30m):research/sessions/2026-07-04_range_harvest/top5_per_cell_per_horizon.csv
  - Formula conditions: modules/signals/formula_shadow.py  (PRIMARY + CONTROL registry)
  - Rolling pct bounds: config/formula_rolling_pct.json
  - AUD_JPY/ny short-240 regime: top5_per_cell_per_horizon.csv (240m row)

Usage:
    python generate_cell_configs.py               # writes to config/cells/<PAIR>.json
    python generate_cell_configs.py --out-dir /tmp/cells
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

GENERATOR_LABEL = "generate_cell_configs.py-2026-07-04"
GENERATED_AT = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

PAIRS = ["AUD_JPY", "AUD_USD", "EUR_JPY", "EUR_USD", "GBP_USD", "USD_CAD", "USD_CHF", "USD_JPY"]
SESSIONS = ["asia", "london", "ny"]

# 4 cert-gate cells — phase-A re-derivation verdicts APPLIED 2026-07-04
# (source: /tmp/phaseA_gate_rederivation.md on EC2):
#   GBP_USD/ny      PARTIAL            -> willr_recovery_short SHADOW added
#   USD_JPY/asia    RE-EXPRESSIBLE     -> kc_breakout_long SHADOW added
#   AUD_JPY/asia    NOT-RE-EXPRESSIBLE -> stays NO-SIDE (final verdict)
#   AUD_USD/london  INSUFFICIENT DATA  -> kc_up short gate survives raw;
#                                         NO vwap long setup (feature not on live feed)
# These cells remain excluded from generic TIMING-setup generation — their
# setups come exclusively from the phase-A verdicts.
CERT_GATE_CELLS = {"GBP_USD/ny", "USD_JPY/asia", "AUD_JPY/asia", "AUD_USD/london"}

# ── Path resolution ────────────────────────────────────────────────────────────

def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _truth_matrix_csv() -> Path:
    return (_repo_root() / "research" / "sessions"
            / "2026-07-03_truth_matrix_envelope" / "ratchet_ev_cells.csv")


def _rh_rates_csv() -> Path:
    return (_repo_root() / "research" / "sessions"
            / "2026-07-04_range_harvest" / "cell_base_rates_multihorizon.csv")


def _top5_csv() -> Path:
    return (_repo_root() / "research" / "sessions"
            / "2026-07-04_range_harvest" / "top5_per_cell_per_horizon.csv")


def _calibration_json() -> Path:
    return _repo_root() / "config" / "cell_calibration.json"


def _rolling_pct_json() -> Path:
    return _repo_root() / "config" / "formula_rolling_pct.json"


# ── Data loaders ───────────────────────────────────────────────────────────────

def _load_ev_gross() -> dict[str, dict[str, float]]:
    """Returns {pair/session: {long: ev, short: ev}}"""
    result: dict[str, dict[str, float]] = {}
    with open(_truth_matrix_csv(), newline="") as f:
        for row in csv.DictReader(f):
            key = f"{row['pair']}/{row['session']}"
            result.setdefault(key, {})[row["direction"]] = float(row["ev_gross"])
    return result


def _load_rh_rates() -> dict[str, dict[str, float]]:
    """Returns {pair/session/direction: {rh_offer_rate_60m, dead_rate_60m}} using floor=6.0"""
    result: dict[str, dict[str, float]] = {}
    with open(_rh_rates_csv(), newline="") as f:
        for row in csv.DictReader(f):
            if row["horizon_min"] != "60" or row["floor"] != "6.0":
                continue
            key = f"{row['pair']}/{row['session']}/{row['direction']}"
            result[key] = {
                "rh_offer_rate_60m": float(row["pct_RANGE_HARVEST"]) / 100.0,
                "dead_rate_60m": float(row["pct_DEAD"]) / 100.0,
            }
    return result


def _load_top5() -> dict[tuple[str, str, str, str, str], dict]:
    """Returns {(pair, session, direction, horizon_min, feature): row}"""
    result = {}
    with open(_top5_csv(), newline="") as f:
        for row in csv.DictReader(f):
            key = (row["pair"], row["session"], row["direction"],
                   row["horizon_min"], row["feature"])
            result[key] = row
    return result


def _load_calibration() -> dict:
    with open(_calibration_json()) as f:
        return json.load(f)


def _load_rolling_pct() -> dict:
    path = _rolling_pct_json()
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


# ── Tier logic ─────────────────────────────────────────────────────────────────

def _assign_tier(long_ev: float | None, short_ev: float | None) -> int:
    """
    Tier 1: gross >= -1.3 BOTH directions (breakeven-capable under harvesting).
    Tier 3: both directions deeply negative (lose-even-gross set, < -3.0 both).
    Tier 2: everything else.
    """
    if long_ev is None or short_ev is None:
        return 2
    if long_ev >= -1.3 and short_ev >= -1.3:
        return 1
    if long_ev < -3.0 and short_ev < -3.0:
        return 3
    return 2


# ── Lean helpers ───────────────────────────────────────────────────────────────

def _lean_side(lean: dict) -> str:
    """Convert lean sign to favored side. sign='negative' → short-when-feature-high
    OR long-when-feature-low.  Spec: side = lean's favored side per its sign.
    sign 'negative' = feature correlates negatively with forward return → short.
    sign 'positive' = feature correlates positively → long.
    """
    # Lean feature corr: positive sign = higher feature → better outcome for LONG
    # negative sign = lower feature → better for SHORT
    # Per calibration.json: 'sign' directly encodes which direction benefits
    sign = lean.get("sign", "")
    # sign=positive → lean favors LONG (higher feature = more likely long wins)
    # sign=negative → lean favors SHORT
    return "long" if sign == "positive" else "short"


def _lean_condition(lean: dict, atr_boundary: float) -> dict:
    """Build the atr_5m band condition for a TIMING setup from lean."""
    lo = lean.get("live_feed_range", [None, None])
    return {
        "feature": "atr_5m",
        "min": atr_boundary,
        "max": None,
        "note": (f"atr_5m >= p75 boundary from top5_per_cell_per_horizon.csv h=30 "
                 f"(plateau_ok=True); raw boundary {atr_boundary}"),
        "lineage": "range-harvest-2026-07-04/top5_per_cell_per_horizon.csv h=30 atr_5m plateau_ok",
    }


def _lean_condition_feature(lean: dict) -> dict:
    """Build the lean-feature range condition for a TIMING/LEAN setup."""
    feature = lean["feature"]
    lo, hi = lean.get("live_feed_range", [None, None])
    sign = lean.get("sign", "positive")
    # side is 'long' when sign='positive', meaning feature > midpoint
    # side is 'short' when sign='negative', meaning feature < midpoint
    # For the condition: use the full live_feed_range as min/max (no point value)
    return {
        "feature": feature,
        "min": lo,
        "max": hi,
        "note": (f"Lean feature full live-feed range; sign={sign} confirms "
                 f"cell directional lean. Source: cell_calibration.json direction_lean."),
        "lineage": "cell-calibration-2026-07/direction_lean.live_feed_range",
    }


# ── Formula registry (from formula_shadow.py — inlined for independence) ──────

FORMULA_REGISTRY = [
    # PRIMARY
    {
        "cell": "GBP_USD/london/long",
        "id": "rvol_low_240",
        "side": "long",
        "class": "FORMULA",
        "status": "ACTIVE",
        "horizon_min": 240,
        "use_rolling_pct": True,
        "conditions_pct": [{"feature": "rvol_5bar", "pct_lo": 4.8, "pct_hi": 25.2,
                             "fallback_lo": 0.371479, "fallback_hi": 0.669169}],
        "exit": {"sl_pips": 12.0, "trigger_pips": 10.0, "trail_pips": 1.5},
        "sizing": {"risk_pct": 0.5},
        "tripwires": {
            "monthly": {"metric": "atr_h1_relative_monthly_mean", "gte": None, "action": "size_down"},
            "fast": {"last_n": 20, "min_ev": -0.5, "action": "suspend"},
        },
        "evidence": {
            "ev_seq": 0.35,
            "oos_years_positive": 7,
            "drift": "STABLE",
            "source": "formula-history-2026-07-04/verdict_table.csv",
            "n_floor_status": "deep-oos-passed",
            "holdout_months_positive": 2,
        },
        "notes": (
            "PRIMARY formula: rvol_5bar rolling-pct band [p4.8, p25.2]. "
            "Deep OOS: 7/7 years positive, sequential +0.35p, STABLE drift. "
            "Rolling pct bounds from config/formula_rolling_pct.json (updated monthly). "
            "2026 absolute fallback: [0.371479, 0.669169]. "
            "Geo: SL=12, trig=10, trail=1.5 (best_cell from convergence study). "
            "Source: research/sessions/2026-07-04_range_harvest + "
            "~/v5-formula-history/ on Mini (verdict_table.csv)."
        ),
    },
    # CONTROL formulas (SHADOW, negative expected EV — falsification stamps)
    {
        "cell": "USD_JPY/ny/long",
        "id": "control_atr5m_60",
        "side": "long",
        "class": "FORMULA",
        "status": "SHADOW",
        "horizon_min": 60,
        "use_rolling_pct": False,
        "conditions_abs": [{"feature": "atr_5m", "min": 2.703442, "max": 6.331820}],
        "exit": {"sl_pips": 20.0, "trigger_pips": 3.0, "trail_pips": 1.5},
        "sizing": {"risk_pct": 0.2},
        "tripwires": {
            "fast": {"last_n": 20, "min_ev": -0.5, "action": "suspend"},
        },
        "evidence": {
            "ev_seq": -1.0,
            "drift": "STABLE",
            "source": "formula-history-2026-07-04/verdict_table.csv",
            "holdout_months_positive": 2,
        },
        "notes": (
            "CONTROL formula: deep-OOS negative (2019-2025), sequential loss. "
            "2026 convergence ev=+1.199 is a 2026-pocket artifact. "
            "atr_5m in [p16.8, p70.4] abs=[2.703442, 6.331820]. "
            "Stamps emitted for live falsification. "
            "Source: formula_shadow.py REGISTRY + ~/v5-formula-history/ verdict_table.csv."
        ),
    },
    {
        "cell": "GBP_USD/ny/short",
        "id": "control_rvol_60",
        "side": "short",
        "class": "FORMULA",
        "status": "SHADOW",
        "horizon_min": 60,
        "use_rolling_pct": False,
        "conditions_abs": [{"feature": "rvol_5bar", "min": 0.371479, "max": 0.669169}],
        "exit": {"sl_pips": 12.0, "trigger_pips": 3.0, "trail_pips": 1.5},
        "sizing": {"risk_pct": 0.2},
        "tripwires": {
            "fast": {"last_n": 20, "min_ev": -0.5, "action": "suspend"},
        },
        "evidence": {
            "ev_seq": -1.0,
            "drift": "STABLE",
            "source": "formula-history-2026-07-04/verdict_table.csv",
            "holdout_months_positive": 2,
        },
        "notes": (
            "CONTROL formula: deep-OOS negative (2019-2025), sequential loss. "
            "2026 convergence ev=+0.914 is a 2026-pocket artifact. "
            "rvol_5bar in [p4.8, p25.2] abs=[0.371479, 0.669169]. "
            "Stamps emitted for live falsification. "
            "Source: formula_shadow.py REGISTRY + ~/v5-formula-history/ verdict_table.csv."
        ),
    },
    {
        "cell": "AUD_USD/ny/short",
        "id": "control_atrconc_60",
        "side": "short",
        "class": "FORMULA",
        "status": "SHADOW",
        "horizon_min": 60,
        "use_rolling_pct": False,
        "conditions_abs": [{"feature": "atr_conc", "min": 0.177600, "max": 0.241631}],
        "exit": {"sl_pips": 10.0, "trigger_pips": 3.0, "trail_pips": 1.5},
        "sizing": {"risk_pct": 0.2},
        "tripwires": {
            "fast": {"last_n": 20, "min_ev": -0.5, "action": "suspend"},
        },
        "evidence": {
            "ev_seq": -0.5,
            "drift": "STABLE",
            "source": "formula-history-2026-07-04/verdict_table.csv",
            "holdout_months_positive": 2,
        },
        "notes": (
            "CONTROL formula: deep-OOS failed validation. "
            "2026 convergence ev=+0.394 is a 2026-pocket artifact. "
            "atr_conc in [p13.9, p35.5] abs=[0.177600, 0.241631]. "
            "Stamps emitted for live falsification. "
            "Source: formula_shadow.py REGISTRY + ~/v5-formula-history/ verdict_table.csv."
        ),
    },
]

# Build fast lookup: (pair, session, direction) -> list[formula entries]
_FORMULA_INDEX: dict[tuple, list[dict]] = {}
for _fe in FORMULA_REGISTRY:
    _pair, _sess, _dir = _fe["cell"].split("/")
    _FORMULA_INDEX.setdefault((_pair, _sess, _dir), []).append(_fe)


def _formula_setups_for(pair: str, session: str) -> list[dict]:
    """Return all formula entries for this (pair, session) across both directions."""
    result = []
    for direction in ("long", "short"):
        result.extend(_FORMULA_INDEX.get((pair, session, direction), []))
    return result


# ── Condition builders ─────────────────────────────────────────────────────────

def _build_formula_conditions(fe: dict, rolling_pct: dict) -> list[dict]:
    """Build conditions list from a formula registry entry."""
    conditions = []
    cell_key = fe["cell"]

    if fe.get("use_rolling_pct"):
        for cpct in fe.get("conditions_pct", []):
            feat = cpct["feature"]
            pct_lo = cpct["pct_lo"]
            pct_hi = cpct["pct_hi"]
            fallback_lo = cpct["fallback_lo"]
            fallback_hi = cpct["fallback_hi"]

            # Try to get current rolling bounds
            cell_rolling = rolling_pct.get(cell_key, {})
            resolved = cell_rolling.get(feat)
            updated = cell_rolling.get("updated")
            resolved_at = updated if updated else "STALE-use-fallback"
            if resolved and len(resolved) == 2:
                resolved_vals = [float(resolved[0]), float(resolved[1])]
            else:
                resolved_vals = [fallback_lo, fallback_hi]
                resolved_at = "fallback-2026-absolute"

            conditions.append({
                "feature": feat,
                "pct_window_days": cell_rolling.get("window_days", 90),
                "pct_lo": pct_lo,
                "pct_hi": pct_hi,
                "resolved": resolved_vals,
                "resolved_at": resolved_at,
                "note": (
                    f"Rolling-pct band [p{pct_lo}, p{pct_hi}] of {feat} "
                    f"in GBP_USD london-session bars, trailing 90d. "
                    f"Engine reads 'resolved'; monthly refit updates resolved values. "
                    f"2026 absolute fallback: [{fallback_lo}, {fallback_hi}]."
                ),
                "lineage": (
                    "formula-rolling-pct-2026-07-04/config/formula_rolling_pct.json; "
                    "formula-history-2026-07-04 (verdict_table.csv, Mini)"
                ),
            })
    else:
        for cabs in fe.get("conditions_abs", []):
            feat = cabs["feature"]
            conditions.append({
                "feature": feat,
                "min": cabs.get("min"),
                "max": cabs.get("max"),
                "note": (
                    f"Absolute 2026 bounds — CONTROL formula, not rolling. "
                    f"Source: formula_shadow.py REGISTRY entry."
                ),
                "lineage": (
                    "formula-shadow-registry-2026-07-04/modules/signals/formula_shadow.py; "
                    "formula-history-2026-07-04 (verdict_table.csv, Mini)"
                ),
            })
    return conditions


# ── AUD_USD/london/short kc_up SHADOW setup ───────────────────────────────────

def _build_kc_up_shadow_setup() -> dict:
    """
    AUD_USD/london/short: kc_up_dist_pips in [-15, 0] — raw gate, broker-validated
    (6W1L). Emitted as SHADOW, class LEAN, side short.
    Phase-A verdict (2026-07-04): kc_up [-15,0] SURVIVES raw re-derivation unchanged;
    m_cert long gate dropped (both lock-era long wins would have passed — no regression).
    Sources: v5_rederivation_REPORT.md item-3b + /tmp/phaseA_gate_rederivation.md CELL 4.
    """
    return {
        "id": "kc_up_short_lean",
        "side": "short",
        "class": "LEAN",
        "status": "ACTIVE",  # promoted Phase D per Brock 2026-07-04
        "horizon_min": 240,
        "conditions": [
            {
                "feature": "kc_up_dist_pips",
                "min": -15.0,
                "max": 0.0,
                "note": (
                    "Price within [-15, 0] pips of KC upper band; near/below upper KC. "
                    "Clean-data re-derivation (2026-07-03): KEEP n=8391 -0.054p 49.2% WR "
                    "vs BLOCKED -1.110p 47.9% WR. Fresh stump: -13.6459 (gt) WR=49.6%. "
                    "Broker-validated: 6W 1L on live AUD_USD/london/short trades. "
                    "phaseA (2026-07-04): survives raw re-derivation unchanged."
                ),
                "lineage": (
                    "rederivation-2026-07-03/v5_rederivation_REPORT.md item-3b; "
                    "broker-validation-6W1L-2026-07; "
                    "phaseA_gate_rederivation-2026-07-04 CELL 4"
                ),
            }
        ],
        "exit": {"sl_pips": 20.0, "trigger_pips": 7.5, "trail_pips": 1.5},
        "sizing": {"risk_pct": 0.2},
        "tripwires": {
            "fast": {"last_n": 20, "min_ev": -0.5, "action": "suspend"},
        },
        "evidence": {
            "ev_seq": -0.054,
            "drift": "STABLE",
            "source": (
                "rederivation-2026-07-03/v5_rederivation_REPORT.md item-3b; "
                "phaseA_gate_rederivation 2026-07-04 (INSUFFICIENT DATA verdict; "
                "kc_up gate survives raw)"
            ),
            "n_floor_status": "broker-validated-6W1L",
        },
        "notes": (
            "phaseA: kc_up [-15,0] survives raw re-derivation; m_cert long gate dropped "
            "(both lock-era long wins would have passed — no regression). "
            "kc_up_dist_pips in [-15, 0] is broker-validated (6W1L) raw gate. "
            "Side: short. No vwap long setup emitted (q_vwap_dist_pips_m5 not on live feed). "
            "Log m_cert-equivalent stamps on every london long fire; re-derive after 10 longs."
        ),
    }


# ── Phase-A verdict setups (GBP_USD/ny, USD_JPY/asia) ─────────────────────────

def _build_willr_recovery_setup() -> dict:
    """
    GBP_USD/ny/short: phase-A PARTIAL verdict — willr >= -50 raw replacement for the
    d_cert/m_cert cert gate (m_cert dropped: never binding, zero discrimination).
    Blocks 1 of 2 recoverable losses (+11.9pp WR lift on n=7 journal window).
    Source: /tmp/phaseA_gate_rederivation.md CELL 1.
    """
    return {
        "id": "willr_recovery_short",
        "side": "short",
        "class": "LEAN",
        "status": "ACTIVE",  # promoted Phase D per Brock 2026-07-04
        "horizon_min": 60,
        "conditions": [
            {
                "feature": "willr_m5",
                "min": -50.0,
                "max": 0.0,
                "note": (
                    "willr_m5 >= -50 (willr bounded [-100, 0], so [-50, 0] IS a range). "
                    "Blocks extreme-oversold shorts (countertrend risk): loss tid 9640 "
                    "(willr=-73.1) blocked; keep 6 -> 5W/1L 83.3% WR vs base 71.4% "
                    "(+11.9pp) on n=7 recoverable. Equivalent alternative: kc_up >= -10."
                ),
                "lineage": "phaseA_gate_rederivation-2026-07-04 CELL 1 (raw feature search)",
            }
        ],
        "exit": {"sl_pips": 20.0, "trigger_pips": 7.5, "trail_pips": 1.5},
        "sizing": {"risk_pct": 0.2},
        "tripwires": {
            "fast": {"last_n": 20, "min_ev": -0.5, "action": "suspend"},
        },
        "evidence": {
            "ev_seq": None,
            "wr": 0.833,
            "drift": "STABLE",
            "source": (
                "phaseA_gate_rederivation 2026-07-04 (PARTIAL verdict; "
                "n=7 recoverable + 14 broker)"
            ),
            "n_floor_status": "small-n-hypothesis (n=7 journal; broker 12W/2L +42.4p)",
        },
        "notes": (
            "phaseA PARTIAL verdict: willr>=-50 replaces cert gate. m_cert>=0.40 DROPPED "
            "(never binding). Second loss (9636) not separable by any raw feature at n=7. "
            "Side short via inverted_live convention. was locked \U0001F512 -> priority_analysis."
        ),
    }


def _build_kc_breakout_long_setup() -> dict:
    """
    USD_JPY/asia/long: phase-A RE-EXPRESSIBLE verdict — kc_up >= 0 replaces d_cert>=0.49.
    keep=5, 4W/1L = 80% WR vs cert gate 5W/2L = 71.4% on same n=9; blocks 3/4 losses
    including tid 9692 which the cert gate incorrectly passed.
    Source: /tmp/phaseA_gate_rederivation.md CELL 2.
    """
    return {
        "id": "kc_breakout_long",
        "side": "long",
        "class": "LEAN",
        "status": "ACTIVE",  # promoted Phase D per Brock 2026-07-04
        "horizon_min": 60,
        "conditions": [
            {
                "feature": "kc_up_dist_pips",
                "min": 0.0,
                "max": None,
                "note": (
                    "kc_up_dist_pips >= 0 (open-top range): price at/above KC upper band "
                    "= breakout regime. Blocks 3/4 losses (9517=-0.5, 9539=-12.1, "
                    "9692=-19.4) incl 9692 which d_cert>=0.49 passed. Known "
                    "false-negative: 9813 (kc_up=-35, won +8.3p). "
                    "Alternative candidate: atr_5m >= 0.04 (blocks same 3 losses)."
                ),
                "lineage": "phaseA_gate_rederivation-2026-07-04 CELL 2 (raw feature search)",
            }
        ],
        "exit": {"sl_pips": 20.0, "trigger_pips": 7.5, "trail_pips": 1.5},
        "sizing": {"risk_pct": 0.2},
        "tripwires": {
            "fast": {"last_n": 20, "min_ev": -0.5, "action": "suspend"},
        },
        "evidence": {
            "ev_seq": None,
            "wr": 0.80,
            "drift": "STABLE",
            "source": (
                "phaseA_gate_rederivation 2026-07-04 (RE-EXPRESSIBLE; beats old d_cert "
                "gate 80% vs 71.4% keep-WR, n=9)"
            ),
            "n_floor_status": "small-n-hypothesis (keep-set n=5 of n=9 journal)",
        },
        "notes": (
            "phaseA RE-EXPRESSIBLE verdict: kc_up>=0 replaces d_cert>=0.49 "
            "(tighter: fewer fires, higher WR, catches the loss cert gate missed). "
            "Side long via inverted_live convention. was locked \U0001F512 -> priority_analysis."
        ),
    }


# ── AUD_JPY/ny/short regime SHADOW setup ──────────────────────────────────────

def _build_audjpy_ny_regime_setup(top5: dict) -> dict:
    """
    AUD_JPY/ny/short 240m regime setup (SHADOW, class LEAN, side short).
    Entry condition: per-bar atr_5m <= p25 boundary (sign_good='-', boundary=3.604874,
    top5 h=240 evidence).
    Monthly tripwire: MONTHLY-MEAN atr_5m regime switch at 2.836 from the regime-edges
    study (Mini ~/v5-regime-edges/) — a DIFFERENT quantity from the per-bar p25 boundary.
    Regime-edges finding: monthly mean atr_5m > 2.836 -> edge ON (+2.88/trade);
    below -> OFF (-1.06/trade).
    Note: session-not-enabled (AUD_JPY/ny was in disabled_cells).
    """
    # Get 240m row for AUD_JPY/ny/short, feature atr_5m
    row = top5.get(("AUD_JPY", "ny", "short", "240", "atr_5m"), {})
    boundary = float(row.get("boundary_abs", 3.604874))
    auc = float(row.get("auc_good_vs_bad", 0.634))
    # sign_good='-' means atr_5m BELOW boundary is good for shorts at 240m
    return {
        "id": "regime_short_240",
        "side": "short",
        "class": "LEAN",
        "status": "ACTIVE",  # promoted Phase D per Brock 2026-07-04
        "horizon_min": 240,
        "conditions": [
            {
                "feature": "atr_5m",
                "min": None,
                "max": boundary,
                "note": (
                    f"Per-bar entry condition: atr_5m <= p25 boundary ({boundary:.6f}) from "
                    f"top5_per_cell_per_horizon.csv h=240 (AUC={auc:.4f}, plateau_ok=True, "
                    "sign_good='-'). Low per-bar volatility favors short at 240m horizon. "
                    "Distinct from the monthly-mean regime tripwire (2.836)."
                ),
                "lineage": (
                    "range-harvest-2026-07-04/top5_per_cell_per_horizon.csv "
                    "h=240 atr_5m AUD_JPY/ny/short"
                ),
            },
        ],
        "exit": {"sl_pips": 20.0, "trigger_pips": 7.5, "trail_pips": 1.5},
        "sizing": {"risk_pct": 0.2},
        "tripwires": {
            "monthly": {
                # SUSPEND when the regime turns OFF: edge is ON above 2.836
                # (+2.88/trade) and OFF below (-1.06/trade) per v5-regime-edges.
                "metric": "atr_5m_monthly_mean",
                "lte": 2.836,
                "action": "suspend",
                "lineage": (
                    "v5-regime-edges 2026-07 (Mini ~/v5-regime-edges/, not in repo — "
                    "monthly refit re-derives)"
                ),
            },
            "fast": {"last_n": 20, "min_ev": -0.5, "action": "suspend"},
        },
        "evidence": {
            "ev_seq": -0.07,
            "drift": "STABLE",
            "source": "ratchet-ev-cells-2026-07-03/ratchet_ev_cells.csv (ev_gross=-0.07 short)",
            "n_floor_status": "shadow-only-session-disabled",
        },
        "notes": (
            "SHADOW regime setup for AUD_JPY/ny/short at 240m horizon. "
            "Session not currently enabled (AUD_JPY/ny was in disabled_cells). "
            "MONTHLY tripwire = regime-edges monthly-mean switch: monthly mean atr_5m "
            "> 2.836 -> edge ON (+2.88/trade), below -> OFF (-1.06/trade); metric "
            "atr_5m_monthly_mean, threshold 2.836 (v5-regime-edges study on Mini). "
            "Per-bar p25 boundary 3.604874 is the ENTRY condition only (top5 h=240) — "
            "these are different quantities, do not conflate. "
            "q_yzv_m5 secondary confirmer (p25 0.000231, AUC=0.632) NOT emitted: "
            "feature not on live feed (queued feed-extension); re-add when feed lands. "
            "Direction lean (q_yzv_m5 PERSISTENT) independently supports short."
        ),
    }


# ── Build a TIMING setup (atr_5m band) for a lean cell ────────────────────────
#
# LEAN-CONFIRMER RULE (config review 2026-07-04): a confirmer condition must be
# (a) readable on the LIVE feed today, (b) non-vacuous (not the feature's full
# range), (c) never an absolute price level. Confirmers that fail get DROPPED
# (side still comes from the calibration lean; first-live-stamps will judge) or
# converted to rolling-percentile form when the lean evidence supports a
# directional band.
LEAN_CONFIRMER_POLICY: dict[tuple[str, str], dict] = {
    ("GBP_USD", "london"): {
        "mode": "drop",
        "reason": "ema5 = price level, AUC at noise floor",
    },
    ("EUR_JPY", "ny"): {
        "mode": "drop",
        "reason": "pdh = absolute price band (182-188), setup-killer on drift",
    },
    ("GBP_USD", "asia"): {
        "mode": "drop",
        "reason": "trend_4h [-1,1] = full feature range, always-true no-op",
    },
    ("AUD_JPY", "ny"): {
        "mode": "drop",
        "reason": "q_yzv_m5 not on live feed (queued feed-extension)",
    },
    ("USD_JPY", "london"): {
        # atr_h1_relative HIGH is the lean evidence -> rolling-percentile >= p75.
        # Resolved from 2026 london-session bars (n=10870) on Mini
        # qtl-discovery-8yr/features/USD_JPY_features.parquet, computed 2026-07-04.
        "mode": "pct",
        "pct_window_days": 90,
        "pct_lo": 75.0,
        "pct_hi": 100.0,
        "resolved": [1.107572, 3.374999],
        "resolved_at": "2026-07-04",
        "note_extra": (
            "resolved lo = p75 of 2026 london-session bars (n=10870); "
            "resolved hi = observed 2026 max"
        ),
        "lineage": (
            "cell-calibration-2026-07/direction_lean (atr_h1_relative HIGH, PERSISTENT); "
            "regime-edges-2026-07; resolved 2026-07-04 from Mini "
            "qtl-discovery-8yr/features/USD_JPY_features.parquet"
        ),
    },
}


def _build_timing_setup(pair: str, session: str, direction: str,
                        lean: dict, atr_boundary: float) -> dict:
    """Build a 30m TIMING SHADOW setup from lean feature and atr_5m boundary.

    The lean-feature confirmer follows LEAN_CONFIRMER_POLICY: dropped when it is
    a price level / full-range no-op / not on live feed; percentile-form when the
    lean evidence supports a directional band. Default (unlisted cells) = drop,
    per the general rule: never full-range, never price levels.
    """
    side = _lean_side(lean)
    lean_feature = lean["feature"]
    lean_sign = lean["sign"]
    cell_str = f"{pair}/{session}/{direction}"

    policy = LEAN_CONFIRMER_POLICY.get((pair, session), {
        "mode": "drop",
        "reason": (
            "general rule: lean confirmer must be percentile-form or study-derived "
            "sub-range with plateau evidence — full live_feed_range is vacuous"
        ),
    })

    conditions = [
        {
            "feature": "atr_5m",
            "min": atr_boundary,
            "max": None,
            "note": (
                f"atr_5m >= p75 boundary ({atr_boundary:.6f}) from "
                f"top5_per_cell_per_horizon.csv h=30 (plateau_ok=True). "
                "Above p75 = sufficient vol for 30m range harvest."
            ),
            "lineage": (
                "range-harvest-2026-07-04/top5_per_cell_per_horizon.csv "
                f"h=30 atr_5m {cell_str}"
            ),
        },
    ]

    if policy["mode"] == "pct":
        conditions.append({
            "feature": lean_feature,
            "pct_window_days": policy["pct_window_days"],
            "pct_lo": policy["pct_lo"],
            "pct_hi": policy["pct_hi"],
            "resolved": policy["resolved"],
            "resolved_at": policy["resolved_at"],
            "note": (
                f"Direction lean confirmer (rolling-percentile form): {lean_feature} "
                f">= p{policy['pct_lo']:.0f} — lean evidence '{lean_feature} HIGH' "
                f"sign={lean_sign} drift={lean.get('drift', '')}. "
                f"{policy.get('note_extra', '')} "
                "Monthly refit re-resolves; engine reads 'resolved'."
            ),
            "lineage": policy["lineage"],
        })
        confirmer_note = (
            f"Lean confirmer: {lean_feature} >= p{policy['pct_lo']:.0f} "
            "(rolling-percentile form)."
        )
    else:
        confirmer_note = (
            f"lean confirmer dropped ({policy['reason']}); side={side} retained "
            "from calibration lean, first-live-stamps will judge."
        )

    # ── Brock direction-persistence override (2026-07-04) ───────────────────
    # Lock-era traded directions persist on trading cells until same-engine
    # n>=20 says otherwise (registry: config/locked_cells.json baselines).
    # USD_JPY/london: lock-era LONG 4W/0L +24.9p (06-22..07-01) overrides the
    # 30m calibration lean (short, AUC at noise floor).
    _override_note = ""
    if cell_str.startswith("USD_JPY/london") and side != "long":
        _override_note = (
            " | SIDE OVERRIDE: short -> long per Brock direction-persistence order "
            "2026-07-04 (lock-era 4W/0L +24.9p, config/locked_cells.json); the atr "
            "conditions stay as vol-energy gates; revisit at n>=20 same-engine trades."
        )
        side = "long"

    return {
        "id": "timing_lean_30",
        "side": side,
        "class": "TIMING",
        "status": "ACTIVE",  # promoted Phase D per Brock 2026-07-04
        "horizon_min": 30,
        "conditions": conditions,
        "exit": {"sl_pips": 20.0, "trigger_pips": 7.5, "trail_pips": 1.5},
        "sizing": {"risk_pct": 0.2},
        "tripwires": {
            "fast": {"last_n": 20, "min_ev": -0.5, "action": "suspend"},
        },
        "evidence": {
            "ev_seq": None,  # null = shadow-only; no OOS sequential EV measured yet
            "drift": lean.get("drift", "PERSISTENT"),
            "source": (
                "range-harvest-2026-07-04/top5_per_cell_per_horizon.csv h=30 atr_5m; "
                "cell-calibration-2026-07/direction_lean"
            ),
            "n_floor_status": "shadow-only-awaiting-live-stamps",
        },
        "notes": (
            f"SHADOW TIMING setup: 30m atr_5m band. "
            f"Side from persistent lean {lean_feature} sign={lean_sign} "
            f"(corr={lean.get('corr', 0):.4f}, AUC={lean.get('auc', 0):.4f}). "
            f"{confirmer_note} "
            f"atr_5m boundary p75={atr_boundary:.6f} (plateau_ok). "
            "Awaiting live CELLSHADOW stamps before promotion consideration."
        ) + _override_note,
    }


# ── Structure block builder ────────────────────────────────────────────────────

def _build_structure(pair: str, session: str, ev_gross: dict,
                     rh_rates: dict) -> dict:
    """Build the structure block for a session."""
    long_ev = ev_gross.get(f"{pair}/{session}", {}).get("long")
    short_ev = ev_gross.get(f"{pair}/{session}", {}).get("short")
    tier = _assign_tier(long_ev, short_ev)

    # RH rates — average of long and short for the session
    rh_l = rh_rates.get(f"{pair}/{session}/long", {})
    rh_s = rh_rates.get(f"{pair}/{session}/short", {})
    rh_offer = round(
        (rh_l.get("rh_offer_rate_60m", 0) + rh_s.get("rh_offer_rate_60m", 0)) / 2, 4
    ) if rh_l or rh_s else None
    dead_rate = round(
        (rh_l.get("dead_rate_60m", 0) + rh_s.get("dead_rate_60m", 0)) / 2, 4
    ) if rh_l or rh_s else None

    struct = {
        "tier": tier,
        "rh_offer_rate_60m": rh_offer,
        "dead_rate_60m": dead_rate,
        "ev_gross_long": long_ev,
        "ev_gross_short": short_ev,
        "lineage": (
            "truth-matrix-2026-07/ratchet_ev_cells.csv (ev_gross, tier); "
            "range-harvest-2026-07-04/cell_base_rates_multihorizon.csv (rh_offer_rate, dead_rate floor=6.0 h=60)"
        ),
    }
    return struct


# ── Main generator ─────────────────────────────────────────────────────────────

def _generate_pair(pair: str,
                   ev_gross: dict,
                   rh_rates: dict,
                   top5: dict,
                   calibration: dict,
                   rolling_pct: dict) -> dict:
    """Generate the full cell config for a pair."""
    now = GENERATED_AT

    sessions_cfg: dict[str, Any] = {}

    for session in SESSIONS:
        cell_long_key = f"{pair}/{session}/long"
        cell_short_key = f"{pair}/{session}/short"
        cell_session_key = f"{pair}/{session}"

        # USD_CHF: all sessions disabled
        if pair == "USD_CHF":
            struct = _build_structure(pair, session, ev_gross, rh_rates)
            killed_note = (
                "USD_CHF killed 2026-07-01 — pair-level disable; "
                "calibration data retained for reference only. "
                "ev_gross_long=" + str(ev_gross.get(cell_session_key, {}).get("long")) + " "
                "ev_gross_short=" + str(ev_gross.get(cell_session_key, {}).get("short")) + ". "
                "Source: config/cell_calibration.json metadata.killed_note."
            )
            sessions_cfg[session] = {
                "enabled": False,
                "structure": struct,
                "setups": [],
                "notes": killed_note,
            }
            continue

        # AUD_CHF/asia doesn't exist — skip non-existent sessions
        # (All 8 pairs have asia/london/ny per V5 spec)

        # Build structure
        struct = _build_structure(pair, session, ev_gross, rh_rates)
        tier = struct["tier"]

        # Collect setups for this session
        setups: list[dict] = []

        # ── FORMULA setups (ACTIVE / SHADOW) ─────────────────────────────────
        formula_entries = _formula_setups_for(pair, session)
        for fe in formula_entries:
            conds = _build_formula_conditions(fe, rolling_pct)
            setup = {
                "id": fe["id"],
                "side": fe["side"],
                "class": fe["class"],
                "status": fe["status"],
                "horizon_min": fe["horizon_min"],
                "conditions": conds,
                "exit": fe["exit"],
                "sizing": fe["sizing"],
                "evidence": fe["evidence"],
                "notes": fe.get("notes", ""),
            }
            if fe.get("tripwires"):
                setup["tripwires"] = fe["tripwires"]
            setups.append(setup)

        # ── CONTROL formulas ──────────────────────────────────────────────────
        # Already included via formula_entries (they are in FORMULA_REGISTRY)

        # ── AUD_JPY/ny/short 240m regime SHADOW ──────────────────────────────
        if pair == "AUD_JPY" and session == "ny":
            setups.append(_build_audjpy_ny_regime_setup(top5))

        # ── AUD_USD/london/short kc_up SHADOW (phase-A: survives raw) ────────
        if pair == "AUD_USD" and session == "london":
            setups.append(_build_kc_up_shadow_setup())

        # ── Phase-A verdict setups (applied 2026-07-04) ──────────────────────
        if pair == "GBP_USD" and session == "ny":
            setups.append(_build_willr_recovery_setup())
        if pair == "USD_JPY" and session == "asia":
            setups.append(_build_kc_breakout_long_setup())

        # ── TIMING setups for tier-1/2 lean cells ────────────────────────────
        # Only if the cell has a PERSISTENT lean
        # NOTE: we build ONE TIMING setup per session (combining both directions,
        # using the lean's favored side) — the lean determines which direction.
        # We look at BOTH directions in the calibration and pick the one with a lean.
        lean_long = None
        lean_short = None
        cal_long = calibration.get(cell_long_key) or {}
        cal_short = calibration.get(cell_short_key) or {}

        dl_long = cal_long.get("direction_lean") or {}
        dl_short = cal_short.get("direction_lean") or {}

        if dl_long and dl_long.get("drift") == "PERSISTENT" and dl_long.get("feature"):
            lean_long = dl_long
        if dl_short and dl_short.get("drift") == "PERSISTENT" and dl_short.get("feature"):
            lean_short = dl_short

        # Cert-gate cells are excluded from generic TIMING generation — their
        # setups come exclusively from the phase-A verdicts above.
        is_cert_gate_cell = cell_session_key in CERT_GATE_CELLS

        if not is_cert_gate_cell and tier in (1, 2):
            # Use one lean (both long and short calibration usually share the same feature
            # with opposite signs — just use long's lean for the setup)
            lean = lean_long or lean_short
            if lean and lean.get("drift") == "PERSISTENT":
                atr_key = (pair, session,
                           "long" if lean_long else "short",
                           "30", "atr_5m")
                atr_row = top5.get(atr_key, {})
                if atr_row.get("plateau_ok") == "True":
                    atr_boundary = float(atr_row["boundary_abs"])
                    side = _lean_side(lean)
                    # Don't duplicate if we already have a FORMULA setup on this side
                    existing_sides = {s["side"] for s in setups}
                    # Always add TIMING — it's SHADOW, different class/id
                    timing_setup = _build_timing_setup(
                        pair, session,
                        "long" if lean_long else "short",
                        lean, atr_boundary
                    )
                    # Avoid duplicate ids
                    existing_ids = {s["id"] for s in setups}
                    if timing_setup["id"] not in existing_ids:
                        setups.append(timing_setup)

        # ── Notes and NO-SIDE determination ──────────────────────────────────
        long_ev_val = ev_gross.get(cell_session_key, {}).get("long", None)
        short_ev_val = ev_gross.get(cell_session_key, {}).get("short", None)

        if cell_session_key == "AUD_JPY/asia":
            # Phase-A final verdict — stays NO-SIDE despite tier-1 + persistent lean.
            session_notes = (
                "was locked \U0001F512; phaseA verdict NOT-RE-EXPRESSIBLE (m_cert "
                "ceiling never binding in natural era; 1W/4L n=5, no raw separator); "
                "re-enters via monthly discovery only. Alternative flagged for Brock: "
                "short ungated + 15-trade requalification. "
                f"Structural: tier={tier} ev_gross_long={long_ev_val} "
                f"ev_gross_short={short_ev_val}."
            )
        elif not setups:
            reason_parts = []
            has_lean = bool(lean_long or lean_short)
            if not has_lean:
                reason_parts.append("no persistent lean (direction_lean.drift != PERSISTENT for both dirs)")
            if tier == 3:
                reason_parts.append(
                    f"tier-3 structural (ev_gross_long={long_ev_val} "
                    f"ev_gross_short={short_ev_val}, both < -3.0 — "
                    "lose-even-gross set, unharvestable at current geometry)"
                )
            session_notes = (
                "NO-SIDE: " + "; ".join(reason_parts) + ". "
                "Cell remains in monthly discovery loop. "
                "A discovered setup enters as SHADOW, earns ACTIVE via the gauntlet."
            )
        else:
            n_active = sum(1 for s in setups if s["status"] == "ACTIVE")
            n_shadow = sum(1 for s in setups if s["status"] == "SHADOW")
            session_notes = (
                f"{n_active} ACTIVE, {n_shadow} SHADOW setups. "
                f"Tier={tier} ev_gross_long={long_ev_val} ev_gross_short={short_ev_val}."
            )
            if cell_session_key in ("GBP_USD/ny", "USD_JPY/asia"):
                session_notes += " was locked \U0001F512 -> priority_analysis."

        sessions_cfg[session] = {
            "enabled": True,
            "structure": struct,
            "setups": setups,
            "notes": session_notes,
        }

    return {
        "pair": pair,
        "generated": now,
        "generator": GENERATOR_LABEL,
        "sessions": sessions_cfg,
    }


# ── Book summary ───────────────────────────────────────────────────────────────

def _print_book_summary(configs: dict[str, dict]) -> None:
    print("\n" + "=" * 72)
    print("BOOK SUMMARY — v1 Cell Configs")
    print("=" * 72)
    print(f"{'Pair/Session':<22} {'Tier':>4}  {'Setups':>8}  {'Status':>8}  {'Side':>6}  {'Class':>8}")
    print("-" * 72)

    total_active = total_shadow = total_noside = 0
    setup_lines = []

    for pair in PAIRS:
        cfg = configs.get(pair, {})
        for session in SESSIONS:
            scfg = cfg.get("sessions", {}).get(session, {})
            enabled = scfg.get("enabled", True)
            struct = scfg.get("structure", {})
            tier = struct.get("tier", "?")
            setups = scfg.get("setups", [])

            if not enabled:
                status_label = "DISABLED"
                print(f"{pair}/{session:<14} {str(tier):>4}  {'DISABLED':>8}")
                continue

            if not setups:
                total_noside += 1
                print(f"{pair}/{session:<14} {str(tier):>4}  {'NO-SIDE':>8}")
                continue

            for s in setups:
                sid = s.get("id", "?")
                side = s.get("side", "?")
                cls = s.get("class", "?")
                status = s.get("status", "?")
                print(f"{pair}/{session:<14} {str(tier):>4}  {sid:<20} {status:>8}  {side:>6}  {cls:>8}")
                if status == "ACTIVE":
                    total_active += 1
                elif status == "SHADOW":
                    total_shadow += 1
                setup_lines.append(f"  {pair}/{session} :: {sid} side={side} class={cls} status={status}")

    print("\n" + "-" * 72)
    print(f"  ACTIVE setups:  {total_active}")
    print(f"  SHADOW setups:  {total_shadow}")
    print(f"  NO-SIDE cells:  {total_noside}")
    print("=" * 72 + "\n")


# ── CLI ────────────────────────────────────────────────────────────────────────



# ── Exit classes (2026-07-05, Brock live order) ───────────────────────────────
# Cell-geometry classes from research/sessions/2026-07-05_ratchet_profiles
# (FAST = NY-fade quick-slice cells, LONG = asia/london extender cells) with
# per-pair cost floors from research/sessions/2026-07-04_cell_transaction_costs.
# Applied AFTER generation so monthly refits preserve the class geometry.
_CELL_KLASS = {('USD_CAD', 'ny'): 'FAST', ('USD_CHF', 'ny'): 'FAST', ('EUR_USD', 'ny'): 'FAST', ('GBP_USD', 'ny'): 'FAST', ('EUR_JPY', 'ny'): 'FAST', ('AUD_USD', 'ny'): 'FAST', ('EUR_JPY', 'london'): 'FAST', ('AUD_JPY', 'ny'): 'FAST', ('USD_JPY', 'london'): 'LONG', ('USD_JPY', 'asia'): 'LONG', ('AUD_USD', 'london'): 'LONG', ('EUR_JPY', 'asia'): 'LONG', ('EUR_USD', 'asia'): 'LONG', ('USD_CAD', 'london'): 'LONG', ('GBP_USD', 'asia'): 'LONG', ('USD_CHF', 'asia'): 'LONG', ('USD_JPY', 'ny'): 'MEDIUM', ('AUD_USD', 'asia'): 'MEDIUM', ('AUD_JPY', 'asia'): 'MEDIUM', ('USD_CAD', 'asia'): 'MEDIUM', ('USD_CHF', 'london'): 'MEDIUM', ('AUD_JPY', 'london'): 'MEDIUM', ('GBP_USD', 'london'): 'MEDIUM', ('EUR_USD', 'london'): 'MEDIUM'}
_TP_FLOOR = {'AUD_USD': 3.0, 'EUR_USD': 3.0, 'USD_JPY': 3.5, 'USD_CAD': 3.5, 'USD_CHF': 3.5, 'GBP_USD': 4.0, 'AUD_JPY': 5.0, 'EUR_JPY': 5.0}
_TRIGGER_MED = {'AUD_USD': 3.5, 'EUR_USD': 3.5, 'USD_JPY': 3.5, 'USD_CHF': 3.5, 'USD_CAD': 4.0, 'GBP_USD': 4.0, 'AUD_JPY': 4.5, 'EUR_JPY': 4.5}

def _apply_exit_classes(cfg: dict, pair: str) -> None:
    for sess, sc in cfg.get("sessions", {}).items():
        for st in sc.get("setups", []):
            k = _CELL_KLASS.get((pair, sess), "MEDIUM")
            if k == "FAST" and int(st.get("horizon_min") or 60) > 60:
                k = "MEDIUM"
            old = st.get("exit", {})
            if k == "FAST":
                tp = _TP_FLOOR[pair]
                st["exit"] = {"mode": "bracket", "tp_pips": tp, "sl_pips": tp + 1.0,
                              "timeout_min": 60.0, "entry_cutoff_utc": 20.0,
                              "trigger_pips": 7.5, "trail_pips": 1.5, "_class": "FAST"}
            elif k == "LONG":
                st["exit"] = {"mode": "ratchet", "sl_pips": float(old.get("sl_pips", 20.0)),
                              "trigger_pips": 8.0, "trail_pips": 4.0, "trail_mult": 1.0,
                              "trail_min": 4.0, "trail_max": 10.0, "_class": "LONG"}
            else:
                st["exit"] = {"mode": "ratchet", "sl_pips": float(old.get("sl_pips", 20.0)),
                              "trigger_pips": _TRIGGER_MED[pair], "trail_pips": 2.5,
                              "trail_mult": 0.6, "trail_min": 2.5, "trail_max": 6.0,
                              "_class": "MEDIUM"}



def _apply_brock_overrides_2026_07(configs: dict) -> None:
    """Live side/filter/exit overrides ordered by Brock 2026-07-06 (deep dives:
    AUD_USD, GBP_USD, USD_JPY). Applied post-generation so monthly refits
    preserve them. Each traces to research/sessions + activity log 2026-07-06."""
    import copy as _copy
    # AUD_USD/london: live flip short->long (corpus drift LONG all windows)
    lon = configs.get("AUD_USD", {}).get("sessions", {}).get("london", {})
    for st in lon.get("setups", []):
        if st.get("id") == "kc_up_short_lean":
            st["status"] = "SHADOW"
            if not any(x.get("id") == "kc_up_long_lean" for x in lon["setups"]):
                tw = _copy.deepcopy(st); tw["id"] = "kc_up_long_lean"; tw["side"] = "long"; tw["status"] = "ACTIVE"
                lon["setups"].append(tw)
    # GBP_USD/asia: live flip short->long; london timing: cemetery
    ga = configs.get("GBP_USD", {}).get("sessions", {}).get("asia", {})
    for st in ga.get("setups", []):
        if st.get("id") == "timing_lean_30":
            st["status"] = "SHADOW"
            if not any(x.get("id") == "timing_lean_30_long" for x in ga["setups"]):
                tw = _copy.deepcopy(st); tw["id"] = "timing_lean_30_long"; tw["side"] = "long"; tw["status"] = "ACTIVE"
                ga["setups"].append(tw)
    for st in configs.get("GBP_USD", {}).get("sessions", {}).get("london", {}).get("setups", []):
        if st.get("id") == "timing_lean_30":
            st["status"] = "DISABLED"
    # PREV-SESSION structure shadows 2026-07-10 (floor/ceiling consciousness)
    _PS_MED = lambda trig: {"mode":"ratchet","sl_pips":12.0,"trigger_pips":trig,"trail_pips":2.5,
                            "trail_mult":0.6,"trail_min":2.5,"trail_max":6.0,"_class":"MEDIUM"}
    _PS_WIRE = [
        ("EUR_JPY","london","ps_floor_break_short","short",[{"feature":"ps_low_dist","max":0.0}],_PS_MED(4.5)),
        ("GBP_USD","ny","ps_ceil_fade_short","short",[{"feature":"ps_pos","min":0.85},{"feature":"ps_high_dist","max":0.0}],_PS_MED(4.0)),
        ("EUR_USD","ny","ps_ceil_fade_short","short",[{"feature":"ps_pos","min":0.85},{"feature":"ps_high_dist","max":0.0}],_PS_MED(3.5)),
        ("EUR_USD","asia","ps_floor_fade_long","long",[{"feature":"ps_pos","max":0.15},{"feature":"ps_low_dist","min":0.0}],_PS_MED(3.5)),
        ("GBP_USD","asia","ps_floor_fade_long","long",[{"feature":"ps_pos","max":0.15},{"feature":"ps_low_dist","min":0.0}],_PS_MED(4.0)),
    ]
    for _pp, _ss, _sid, _side, _conds, _ex in _PS_WIRE:
        _sc = configs.get(_pp, {}).get("sessions", {}).get(_ss, {})
        if _sc and not any(x.get("id")==_sid for x in _sc.get("setups", [])):
            _sc.setdefault("setups", []).append({"id":_sid,"side":_side,"class":"session_structure",
                "status":"SHADOW","horizon_min":240,"conditions":_conds,"exit":_ex,
                "sizing":{"risk_pct":0.2},
                "tripwires":{"fast":{"last_n":20,"min_ev":-0.5,"action":"suspend"}},
                "evidence":{"ev_seq":0.0,"source":"prev-session screen 2026-07-10","drift":"STABLE"},
                "notes":"Session floor/ceiling consciousness; shadow earns via scoreboard."})
    # OG BOX THEORY shadows 2026-07-09 (resurrection docket item 3)
    import copy as _cbx
    _BOX = {"id":"box_pdl_short","side":"short","class":"box","status":"SHADOW","horizon_min":240,
            "conditions":[{"feature":"pdl_dist","max":0.0}],
            "sizing":{"risk_pct":0.2},
            "tripwires":{"fast":{"last_n":20,"min_ev":-0.5,"action":"suspend"}},
            "evidence":{"ev_seq":0.0,"source":"box-screen 2026-07-09","drift":"PERSISTENT"},
            "notes":"V1 box theory resurrected; SHADOW earns via scoreboard."}
    _BOX_EXITS = {
        ("EUR_JPY","asia"): {"mode":"ratchet","sl_pips":14.0,"trigger_pips":8.0,"trail_pips":4.0,"trail_mult":1.0,"trail_min":4.0,"trail_max":10.0,"_class":"LONG"},
        ("USD_JPY","asia"): {"mode":"ratchet","sl_pips":12.0,"trigger_pips":6.0,"trail_pips":3.5,"trail_mult":0.7,"trail_min":3.0,"trail_max":7.0,"_class":"HARVEST"},
        ("GBP_USD","ny"):   {"mode":"bracket","tp_pips":4.0,"sl_pips":5.0,"timeout_min":60.0,"entry_cutoff_utc":20.0,"trigger_pips":7.5,"trail_pips":1.5,"_class":"FAST"},
    }
    for (bp, bs), bx in _BOX_EXITS.items():
        sc = configs.get(bp, {}).get("sessions", {}).get(bs, {})
        if sc and not any(x.get("id")=="box_pdl_short" for x in sc.get("setups", [])):
            st = _cbx.deepcopy(_BOX); st["exit"] = bx
            sc.setdefault("setups", []).append(st)
    # MTF dial 2026-07-09: htf_pct_60 floor-of-range confirmation on AU london kc
    for st in configs.get("AUD_USD", {}).get("sessions", {}).get("london", {}).get("setups", []):
        if st.get("id") == "kc_up_long_lean":
            if not any(c.get("feature")=="htf_pct_60" for c in st.get("conditions", [])):
                st["conditions"].append({"feature": "htf_pct_60", "max": 0.013})
    # SHADOW SCOREBOARD 2026-07-09 (stamp-forward verdicts)
    for st in configs.get("AUD_USD", {}).get("sessions", {}).get("ny", {}).get("setups", []):
        if st.get("id") == "control_atrconc_60":
            st["status"] = "ACTIVE"
            st["exit"] = {"mode":"bracket","tp_pips":3.0,"sl_pips":4.0,"timeout_min":60.0,
                          "entry_cutoff_utc":20.0,"trigger_pips":7.5,"trail_pips":1.5,"_class":"FAST"}
    for st in configs.get("GBP_USD", {}).get("sessions", {}).get("london", {}).get("setups", []):
        if st.get("id") == "rvol_low_240":
            st["status"] = "ACTIVE"
            st["exit"] = {"mode":"ratchet","sl_pips":14.0,"trigger_pips":8.0,"trail_pips":4.0,
                          "trail_mult":1.0,"trail_min":4.0,"trail_max":10.0,"_class":"LONG"}
    for st in configs.get("GBP_USD", {}).get("sessions", {}).get("ny", {}).get("setups", []):
        if st.get("id") == "willr_recovery_short":
            st["status"] = "SHADOW"
    # BATCH DIAL-IN 2026-07-08 pt2 (Brock full-book order)
    for st in configs.get("GBP_USD", {}).get("sessions", {}).get("asia", {}).get("setups", []):
        if st.get("id") == "timing_lean_30_long":
            cds = st.setdefault("conditions", [])
            if not any(c.get("feature")=="rvol_5bar" for c in cds): cds.append({"feature":"rvol_5bar","max":1.321})
            if not any(c.get("feature")=="atr_conc" for c in cds): cds.append({"feature":"atr_conc","min":0.233})
    for st in configs.get("GBP_USD", {}).get("sessions", {}).get("ny", {}).get("setups", []):
        if st.get("id") == "willr_recovery_short":
            if not any(c.get("feature")=="atr_5m" for c in st.get("conditions", [])):
                st["conditions"].append({"feature":"atr_5m","max":6.349})
    for st in configs.get("GBP_USD", {}).get("sessions", {}).get("london", {}).get("setups", []):
        if st.get("id") == "rvol_low_240":
            st["status"] = "SHADOW"
    for st in configs.get("AUD_JPY", {}).get("sessions", {}).get("ny", {}).get("setups", []):
        if st.get("id") == "timing_lean_30_short":
            for cd in st.get("conditions", []):
                if cd.get("feature")=="atr_5m": cd["max"] = 7.947
    uj_lon = configs.get("USD_JPY", {}).get("sessions", {}).get("london", {})
    for st in uj_lon.get("setups", []):
        if st.get("id") == "timing_lean_30" and st.get("side") == "long":
            st["status"] = "SHADOW"
            if not any(x.get("id")=="timing_lean_30_short" for x in uj_lon["setups"]):
                import copy as _c
                tw = _c.deepcopy(st); tw["id"]="timing_lean_30_short"; tw["side"]="short"; tw["status"]="ACTIVE"
                tw["exit"] = {"mode":"ratchet","sl_pips":25.0,"trigger_pips":10.0,"trail_pips":5.0,
                              "trail_mult":1.0,"trail_min":5.0,"trail_max":12.0,"_class":"LONG"}
                uj_lon["setups"].append(tw)
    # DIAL-IN 2026-07-08 (quintile tables, combined-verified on 60d corpus)
    for st in configs.get("AUD_JPY", {}).get("sessions", {}).get("ny", {}).get("setups", []):
        if st.get("id") == "regime_short_240":
            for cd in st.get("conditions", []):
                if cd.get("feature") == "atr_5m": cd["max"] = 2.81
                if cd.get("feature") == "kc_up_dist_pips": cd["min"] = -4.54
    for st in configs.get("AUD_USD", {}).get("sessions", {}).get("london", {}).get("setups", []):
        if st.get("id") == "kc_up_long_lean":
            for cd in st.get("conditions", []):
                if cd.get("feature") == "kc_up_dist_pips": cd["min"] = -15.0; cd["max"] = -4.62
            if not any(c.get("feature") == "rvol_5bar" for c in st.get("conditions", [])):
                st["conditions"].append({"feature": "rvol_5bar", "min": 0.80})
    for st in configs.get("EUR_JPY", {}).get("sessions", {}).get("ny", {}).get("setups", []):
        if st.get("id") == "timing_lean_30":
            if not any(c.get("feature") == "atr_h1_relative" for c in st.get("conditions", [])):
                st.setdefault("conditions", []).append({"feature": "atr_h1_relative", "min": 1.09})
    for st in configs.get("GBP_USD", {}).get("sessions", {}).get("asia", {}).get("setups", []):
        if st.get("id") == "timing_lean_30_long":
            st["exit"] = dict(st.get("exit", {}), sl_pips=14.0)
    # AUD_JPY/ny timing_lean_30: live flip long->short (2026-07-08, window drift -2.95)
    aj_ny = configs.get("AUD_JPY", {}).get("sessions", {}).get("ny", {})
    for st in aj_ny.get("setups", []):
        if st.get("id") == "timing_lean_30" and st.get("side") == "long":
            st["status"] = "SHADOW"
            if not any(x.get("id") == "timing_lean_30_short" for x in aj_ny["setups"]):
                import copy as _c
                tw = _c.deepcopy(st); tw["id"] = "timing_lean_30_short"; tw["side"] = "short"; tw["status"] = "ACTIVE"
                aj_ny["setups"].append(tw)
    # AUD_JPY/ny regime_short_240: dual filter + SL12 (2026-07-08 deep dive)
    for st in configs.get("AUD_JPY", {}).get("sessions", {}).get("ny", {}).get("setups", []):
        if st.get("id") == "regime_short_240":
            cds = st.setdefault("conditions", [])
            if not any(c.get("feature") == "kc_up_dist_pips" for c in cds):
                cds.append({"feature": "kc_up_dist_pips", "min": -6.75})
            if not any(c.get("feature") == "willr_m5" for c in cds):
                cds.append({"feature": "willr_m5", "min": -66.37})
            st["exit"] = dict(st.get("exit", {}), sl_pips=12.0)
    # AUD_USD/london kc_up_long_lean: harvest regear (2026-07-08)
    for st in configs.get("AUD_USD", {}).get("sessions", {}).get("london", {}).get("setups", []):
        if st.get("id") == "kc_up_long_lean":
            st["exit"] = {"mode": "ratchet", "sl_pips": 12.0, "trigger_pips": 6.0, "trail_pips": 3.5,
                          "trail_mult": 0.7, "trail_min": 3.0, "trail_max": 7.0, "_class": "HARVEST"}
    # USD_JPY/asia kc_breakout_long: vol filter + harvest regear (window bleeds at 240m)
    for st in configs.get("USD_JPY", {}).get("sessions", {}).get("asia", {}).get("setups", []):
        if st.get("id") == "kc_breakout_long":
            if not any(c.get("feature") == "atr_h1_relative" for c in st.get("conditions", [])):
                st.setdefault("conditions", []).append({"feature": "atr_h1_relative", "max": 1.05})
            st["exit"] = {"mode": "ratchet", "sl_pips": 12.0, "trigger_pips": 6.0, "trail_pips": 3.5,
                          "trail_mult": 0.7, "trail_min": 3.0, "trail_max": 7.0, "_class": "HARVEST"}
    # ===== 2026-07-14 deep-dive dials (broker CSV + 235-episode corpus join; Brock order) =====
    # AJ/ny regime_short_240: DEMOTE + htf regime filter (qtl mono 1.0) + pre-rollover runway cutoff
    for st in configs.get("AUD_JPY", {}).get("sessions", {}).get("ny", {}).get("setups", []):
        if st.get("id") == "regime_short_240":
            st["status"] = "SHADOW"
            if not any(c.get("feature") == "htf_pct_60" for c in st.get("conditions", [])):
                st.setdefault("conditions", []).append({"feature": "htf_pct_60", "max": -0.005})
            st["exit"] = dict(st.get("exit", {}), entry_cutoff_utc=17.0)
    # GBP/lon rvol_low_240: DEMOTE + don't-chase filter (pdl_dist qtl mono 1.0, -1.20 -> +2.42/ep)
    for st in configs.get("GBP_USD", {}).get("sessions", {}).get("london", {}).get("setups", []):
        if st.get("id") == "rvol_low_240":
            st["status"] = "SHADOW"
            if not any(c.get("feature") == "pdl_dist" for c in st.get("conditions", [])):
                st.setdefault("conditions", []).append({"feature": "pdl_dist", "max": 57.0})
    # UJ/lon timing_lean_30_short: DEMOTE; SL 25->12 (winners' MAE p90 10.3; -25/attempt discovery)
    for st in configs.get("USD_JPY", {}).get("sessions", {}).get("london", {}).get("setups", []):
        if st.get("id") == "timing_lean_30_short":
            st["status"] = "SHADOW"
            st["exit"] = dict(st.get("exit", {}), sl_pips=12.0)
    # UJ/ny control_atr5m_60: PROMOTE with SL 20->5 (winners' MAE p90 4.2; +3.9/ep @60m, +8.6 @240m)
    for st in configs.get("USD_JPY", {}).get("sessions", {}).get("ny", {}).get("setups", []):
        if st.get("id") == "control_atr5m_60":
            st["status"] = "ACTIVE"
            st["exit"] = dict(st.get("exit", {}), sl_pips=5.0)
    # AU/lon kc_up_long_lean: SL 12->7 (max winner MAE 6.8 across 17 episodes)
    for st in configs.get("AUD_USD", {}).get("sessions", {}).get("london", {}).get("setups", []):
        if st.get("id") == "kc_up_long_lean":
            st["exit"] = dict(st.get("exit", {}), sl_pips=7.0)
    # GBP/asia timing_lean_30_long: SL 14->9 (max winner MAE 7.7; losers run to 24)
    for st in configs.get("GBP_USD", {}).get("sessions", {}).get("asia", {}).get("setups", []):
        if st.get("id") == "timing_lean_30_long":
            st["exit"] = dict(st.get("exit", {}), sl_pips=9.0)
    # UJ/asia kc_breakout_long: trend-day confirmation (pdl_dist mono 1.0; SL12 KEPT, max winner MAE 11.1)
    for st in configs.get("USD_JPY", {}).get("sessions", {}).get("asia", {}).get("setups", []):
        if st.get("id") == "kc_breakout_long":
            if not any(c.get("feature") == "pdl_dist" for c in st.get("conditions", [])):
                st.setdefault("conditions", []).append({"feature": "pdl_dist", "min": 63.0})
    # GBP/ny willr_recovery_short (shadow): willr floor — losers live below -61 (still-oversold shorts)
    for st in configs.get("GBP_USD", {}).get("sessions", {}).get("ny", {}).get("setups", []):
        if st.get("id") == "willr_recovery_short":
            if not any(c.get("feature") == "willr_m5" for c in st.get("conditions", [])):
                st.setdefault("conditions", []).append({"feature": "willr_m5", "min": -61.0})
    # ===== 2026-07-14 SL40 WIDE-STOP TEST — 6-cell shortlist (Brock order, portfolio sim proven) =====
    # All -> ratchet SL40 with own trigger/trail (bracket cells converted, matching the sim).
    # 4 shadow (scored forward = OOS validation), 2 active (kc_breakout_long, EJ/ny timing = live wide).
    _SL40 = [
        ("USD_JPY", "asia", "kc_breakout_long"),
        ("AUD_JPY", "ny", "regime_short_240"),
        ("GBP_USD", "london", "classic_box_fade_long"),
        ("GBP_USD", "ny", "ps_ceil_fade_short"),
        ("EUR_JPY", "ny", "timing_lean_30"),
        ("GBP_USD", "ny", "control_rvol_60"),
    ]
    for _p, _s, _id in _SL40:
        for st in configs.get(_p, {}).get("sessions", {}).get(_s, {}).get("setups", []):
            if st.get("id") == _id:
                _ex = dict(st.get("exit", {}))
                _trig = 7.5   # Brock 2026-07-15: engage at real +7.5 move (not +3.5 wiggles); tested Sharpe 0.70 vs 0.60
                _trail = 2.5  # trail stays TIGHT to lock the gain (loosening to 4 collapses to Sharpe 0.04)
                _new = {"mode": "ratchet", "sl_pips": 40.0, "trigger_pips": _trig, "trail_pips": _trail,
                        "trail_mult": 1.0, "trail_min": _trail, "trail_max": 12.0, "_class": "WIDE_TEST"}
                if _ex.get("entry_cutoff_utc"): _new["entry_cutoff_utc"] = _ex["entry_cutoff_utc"]
                st["exit"] = _new

    # AJ/ny timing_lean_30_short: DEAD CELL FIX (0.0% cond-pass since cutover — atr band [6.62,7.95]
    # stranded above current regime p90 5.75). Same-tail refresh (top 8.3%..1.7% of trailing 30d)
    # -> [5.91,8.13]; SHADOW until the board scores it (zero live/stamp evidence in current form).
    for st in configs.get("AUD_JPY", {}).get("sessions", {}).get("ny", {}).get("setups", []):
        if st.get("id") == "timing_lean_30_short":
            for cd in st.get("conditions", []):
                if cd.get("feature") == "atr_5m":
                    cd["min"] = 5.91; cd["max"] = 8.13
            st["status"] = "SHADOW"


    # ===== 2026-07-14 RANGE-SIZED SL — ALL CELLS (Brock order, PRACTICE account experiment) =====
    # Every cell -> ratchet, SL sized to its session's median swing (rare-red / runner-carried thesis).
    # SUPERSEDES the 6-cell SL40 block above. Brackets -> ratchet so wide stops + runners express.
    _RANGE_SL = {
        "USD_CHF/asia":40.0,"EUR_USD/asia":40.0,"USD_CAD/asia":40.0,"AUD_USD/london":40.0,"AUD_USD/asia":40.0,
        "USD_CHF/london":40.0,"GBP_USD/asia":40.0,"USD_CAD/london":40.0,
        "AUD_USD/ny":50.0,"USD_CHF/ny":50.0,"AUD_JPY/london":50.0,"EUR_USD/london":50.0,"EUR_USD/ny":50.0,
        "USD_JPY/london":50.0,"USD_JPY/asia":50.0,"AUD_JPY/ny":50.0,"AUD_JPY/asia":50.0,
        "EUR_JPY/asia":60.0,"USD_JPY/ny":60.0,"USD_CAD/ny":60.0,"EUR_JPY/ny":60.0,"EUR_JPY/london":60.0,
        "GBP_USD/london":60.0,"GBP_USD/ny":60.0,
    }
    for _pair, _pcfg in configs.items():
        for _sess, _scfg in _pcfg.get("sessions", {}).items():
            _sl = _RANGE_SL.get(_pair + "/" + _sess)
            if not _sl:
                continue
            for _st in _scfg.get("setups", []):
                _ex = dict(_st.get("exit", {}))
                _trig = 7.5   # Brock 2026-07-15: engage at real +7.5 move (not +3.5 wiggles); tested Sharpe 0.70 vs 0.60
                _trail = 2.5  # trail stays TIGHT to lock the gain (loosening to 4 collapses to Sharpe 0.04)
                _new = {"mode": "ratchet", "sl_pips": _sl, "trigger_pips": _trig, "trail_pips": _trail,
                        "trail_mult": 0.0, "trail_min": _trail, "trail_max": max(_trail * 3.0, 10.0),  # trail_mult=0 -> FIXED trail (Brock: no ATR-scaling; engage +7.5, lock +5)
                        "_class": "RANGE_SIZED"}
                if _ex.get("entry_cutoff_utc"):
                    _new["entry_cutoff_utc"] = _ex["entry_cutoff_utc"]
                _st["exit"] = _new




    # ===== 2026-07-15 PROMOTE control_rvol_60 GBP/ny SHADOW->ACTIVE (Brock; n=13, MFE/MAE 17.9/5.6, 7d +13.16) =====
    for _st in configs.get("GBP_USD", {}).get("sessions", {}).get("ny", {}).get("setups", []):
        if _st.get("id") == "control_rvol_60":
            _st["status"] = "ACTIVE"



    # ===== 2026-07-15 PROMOTE rvol_low_240 (GBP/lon) + classic_extension_fade_long (AUD/lon) (Brock) =====
    for _st in configs.get("GBP_USD", {}).get("sessions", {}).get("london", {}).get("setups", []):
        if _st.get("id") == "rvol_low_240":
            _st["status"] = "ACTIVE"
    for _st in configs.get("AUD_USD", {}).get("sessions", {}).get("london", {}).get("setups", []):
        if _st.get("id") == "classic_extension_fade_long":
            _st["status"] = "ACTIVE"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate config/cells/<PAIR>.json for all 8 pairs.")
    parser.add_argument("--out-dir", default=None,
                        help="Output directory (default: config/cells/ relative to repo root)")
    args = parser.parse_args()

    repo = _repo_root()
    out_dir = Path(args.out_dir) if args.out_dir else repo / "config" / "cells"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Load evidence
    print("Loading evidence files...")
    try:
        ev_gross = _load_ev_gross()
        print(f"  ev_gross: {len(ev_gross)} cells from {_truth_matrix_csv().name}")
    except Exception as exc:
        print(f"ERROR loading ev_gross: {exc}", file=sys.stderr)
        return 1

    try:
        rh_rates = _load_rh_rates()
        print(f"  rh_rates: {len(rh_rates)} cell-directions from {_rh_rates_csv().name}")
    except Exception as exc:
        print(f"ERROR loading rh_rates: {exc}", file=sys.stderr)
        return 1

    try:
        top5 = _load_top5()
        print(f"  top5: {len(top5)} entries from {_top5_csv().name}")
    except Exception as exc:
        print(f"ERROR loading top5: {exc}", file=sys.stderr)
        return 1

    try:
        calibration = _load_calibration()
        print(f"  calibration: {len(calibration)} cells from {_calibration_json().name}")
    except Exception as exc:
        print(f"ERROR loading calibration: {exc}", file=sys.stderr)
        return 1

    rolling_pct = _load_rolling_pct()
    print(f"  rolling_pct: {len(rolling_pct)} cells from formula_rolling_pct.json")

    # Generate configs
    configs: dict[str, dict] = {}
    for pair in PAIRS:
        print(f"  Generating {pair}...")
        cfg = _generate_pair(pair, ev_gross, rh_rates, top5, calibration, rolling_pct)
        _apply_exit_classes(cfg, pair)
        configs[pair] = cfg
        out_path = out_dir / f"{pair}.json"
        out_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        print(f"    -> {out_path}")

    _apply_brock_overrides_2026_07(configs)
    for pair, cfg in configs.items():
        (out_dir / f"{pair}.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    # Print book summary
    _print_book_summary(configs)

    print(f"Generated {len(configs)} pair configs in {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
