"""modules/signals/calibration.py — per-cell calibration lookups (log-only instrumentation).

Loads config/cell_calibration.json once at import time.  Fail-open: if the
file is missing or unparseable all lookups return None and a single warning is
emitted -- no crash, no retry.

Keyed "PAIR/session/direction" (e.g. "GBP_USD/ny/short").  Per-cell payload:
  distance_calibration  — MFE-60m quantiles (p25/p50/p75/p90, pips) +
                          ATR-1H regression (slope/intercept) + 240m p50.
  adverse_calibration   — winner-conditioned |MAE| p50/p75/p90 + anchor-bias note.
  dead_entry            — base_rate_dead + top-2 separators with feature/threshold.
  direction_lean        — feature/sign/corr/drift or None.
  metadata              — killed_pair flag, lineage, n_bars.

API
---
cal_for(pair, session, direction) -> dict | None
  Raw cell dict, or None if not found / killed / calibration disabled.

projected_mfe(pair, session, direction, atr_1h_pips) -> float | None
  Regression-based MFE-60m estimate, clipped to [p25, p90] in pips.
  Returns None if cell not found, killed, or calibration disabled.

dead_risk(pair, session, direction, view) -> dict | None
  Returns {base_rate, separator_states:[{...}]}
  separator_states has one entry per separator in the cell; separators
  whose feature is not on the MarketView are included with value=None
  and beyond_threshold=None (unreadable).  Readable separators supply
  {feature, value, beyond_threshold, conditional_rate}.
"""
from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger("v5.calibration")

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "cell_calibration.json"

# ── Load once at import ───────────────────────────────────────────────────────

def _load() -> Optional[dict]:
    """Return the parsed calibration dict, or None on any error (fail-open)."""
    try:
        data = json.loads(_CONFIG_PATH.read_text())
        if not isinstance(data, dict) or not data:
            log.warning("calibration DISABLED: %s is empty or not a dict", _CONFIG_PATH)
            return None
        log.info("calibration loaded: %d cells from %s", len(data), _CONFIG_PATH.name)
        return data
    except FileNotFoundError:
        log.warning("calibration DISABLED: %s not found", _CONFIG_PATH)
        return None
    except Exception as exc:
        log.warning("calibration DISABLED: cannot parse %s: %s", _CONFIG_PATH, exc)
        return None


_CAL: Optional[dict] = _load()


def is_enabled() -> bool:
    """True when the calibration artifact loaded successfully."""
    return _CAL is not None


# ── Public API ────────────────────────────────────────────────────────────────

def cal_for(pair: str, session: str, direction: str) -> Optional[dict]:
    """Raw cell dict for (pair, session, direction), or None.

    Returns None when:
      - calibration artifact failed to load
      - cell key not in the artifact
      - metadata.killed_pair is True for this cell's pair
    """
    if _CAL is None:
        return None
    key = f"{pair}/{session}/{direction}"
    cell = _CAL.get(key)
    if cell is None:
        return None
    if cell.get("metadata", {}).get("killed_pair", False):
        return None
    return cell


def projected_mfe(
    pair: str,
    session: str,
    direction: str,
    atr_1h_pips: float,
) -> Optional[float]:
    """Regression-predicted MFE-60m in pips, clipped to [p25, p90].

    Uses the ATR-1H linear regression stored in the artifact:
        raw = slope * atr_1h_pips + intercept
        result = clip(raw, mfe_60m_p25, mfe_60m_p90)

    Returns None if the cell is missing, killed, or calibration disabled.
    """
    cell = cal_for(pair, session, direction)
    if cell is None:
        return None
    dc = cell.get("distance_calibration", {})
    reg = dc.get("atr_regression", {})
    slope     = reg.get("slope")
    intercept = reg.get("intercept")
    p25       = dc.get("mfe_60m_p25")
    p90       = dc.get("mfe_60m_p90")
    if any(v is None for v in (slope, intercept, p25, p90)):
        return None
    raw = slope * atr_1h_pips + intercept
    return float(max(p25, min(p90, raw)))


def dead_risk(
    pair: str,
    session: str,
    direction: str,
    view,
) -> Optional[dict]:
    """Dead-entry risk assessment for a live bar.

    Returns:
      {
        "base_rate": float,                # base_rate_dead from artifact
        "separator_states": [
          {
            "feature":          str,
            "threshold":        float,
            "value":            float | None,   # None = feature not on view
            "beyond_threshold": bool | None,    # None = feature not on view
            "conditional_rate": float | None,   # None = feature not on view
          },
          ...  # one per separator in the cell (up to 2)
        ]
      }
    or None if cell missing / killed / calibration disabled.

    Separator direction convention (artifact):
      p_dead_above_threshold applies when value > threshold.
      p_dead_below_threshold applies when value <= threshold.
    """
    cell = cal_for(pair, session, direction)
    if cell is None:
        return None
    de = cell.get("dead_entry", {})
    base_rate = float(de.get("base_rate_dead", 0.0))
    separators = de.get("separators") or []

    states = []
    for sep in separators:
        feat      = sep.get("feature")
        threshold = sep.get("threshold")
        p_above   = sep.get("p_dead_above_threshold")
        p_below   = sep.get("p_dead_below_threshold")
        value     = getattr(view, feat, None) if feat else None
        if value is None or threshold is None:
            states.append({
                "feature":          feat,
                "threshold":        threshold,
                "value":            None,
                "beyond_threshold": None,
                "conditional_rate": None,
            })
        else:
            beyond = (value > threshold)
            cond_rate = float(p_above) if beyond else float(p_below)
            states.append({
                "feature":          feat,
                "threshold":        threshold,
                "value":            float(value),
                "beyond_threshold": beyond,
                "conditional_rate": cond_rate,
            })

    return {"base_rate": base_rate, "separator_states": states}
