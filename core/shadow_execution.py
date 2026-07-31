"""core/shadow_execution.py — setup-specific shadow exit simulation (D-7).

A fixed 240-minute mid close measures directional drift, not the strategy on
trial. This module replays the setup's ACTUAL exit geometry — the live
ratchet's floor-step lock (mirroring modules/management/ratchet.py:
lock = floor((peak - trigger) / step) * step + trigger - trail, cadence-gated)
or the bracket's TP/SL/timeout — over the EXECUTABLE candle path (bid for a
long's liquidation and MFE, ask for a short's), starting from the STAMPED
executable entry, never a later candle open.

INTRABAR AMBIGUITY: M5 candles hide event order inside a bar. Whenever both
the stop and a new favorable extreme are inside the same candle, the stop
fires FIRST at the stop price (worst case), and the outcome is flagged
`ambiguous_bar` — conservatism that prevents OHLC path assumptions from
manufacturing edge. Quote-stream replay can replace this later.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence

from core.trial_events import METRIC_V2

# Ratchet step knobs: read the LIVE defaults from config/exit_config.json.
# The old hardcoded 5p/20min simulated a ratchet 10x coarser than the live
# 2p/0.5min gear — "mechanics-matched" in name only (charter defect #2,
# 2026-07-31). Stamps now carry step_size_pips/step_cadence_min per stamp;
# these defaults cover legacy stamps.
def _live_step_defaults():
    import json as _j
    from pathlib import Path as _P
    try:
        d = _j.loads((_P(__file__).resolve().parents[1] / "config"
                      / "exit_config.json").read_text()).get("defaults", {})
        return (float(d.get("step_size_pips", 2.0)),
                float(d.get("step_cadence_min", 0.5)))
    except Exception:
        return 2.0, 0.5

DEFAULT_STEP_SIZE_PIPS, DEFAULT_CADENCE_MIN = _live_step_defaults()


@dataclass(frozen=True)
class ShadowOutcome:
    net_pips: float
    exit_reason: str          # "stop" | "initial_stop" | "tp" | "timeout" | "horizon"
    exit_bar: int             # index into the candle sequence
    mfe_pips: float
    mae_pips: float
    ambiguous_bar: bool
    metric_version: str = METRIC_V2


def executable_candle(candle: dict, side: str) -> Optional[dict]:
    """The liquidation-side OHLC: bid for longs, ask for shorts."""
    comp = candle.get("bid" if side == "long" else "ask")
    if not comp:
        return None
    try:
        return {"o": float(comp["o"]), "h": float(comp["h"]),
                "l": float(comp["l"]), "c": float(comp["c"])}
    except (KeyError, TypeError, ValueError):
        return None


def _fav(px: float, entry: float, side: str, pip: float) -> float:
    return (px - entry) / pip if side == "long" else (entry - px) / pip


def _ratchet_lock(peak_pips: float, trigger: float, step: float,
                  trail: float) -> Optional[float]:
    """Live ratchet's floor-step lock, in profit-direction pips from entry."""
    if peak_pips < trigger:
        return None
    level = math.floor((peak_pips - trigger) / step) * step + trigger
    return level - trail


def simulate_shadow_exit(stamp: dict, candles: Sequence[dict],
                         pip: float) -> Optional[ShadowOutcome]:
    """Replay the setup's exit over executable candles. `stamp` is a parsed
    TRIALSTAMP dict; `candles` are OANDA price=BA candles starting at/after
    the stamp. Returns None when the data is unusable (caller skips)."""
    side = stamp.get("side")
    entry = float(stamp.get("entry") or 0)
    exit_cfg = stamp.get("exit_config") or {}
    if side not in ("long", "short") or entry <= 0 or not candles:
        return None
    bars = []
    for c in candles:
        e = executable_candle(c, side)
        if e is not None:
            bars.append(e)
    if len(bars) < 2:
        return None
    horizon_bars = max(2, int(float(stamp.get("horizon_min", 240)) / 5.0))
    bars = bars[:horizon_bars]

    mode = str(exit_cfg.get("mode", "ratchet") or "ratchet")
    if mode == "bracket":
        return _simulate_bracket(bars, entry, side, exit_cfg, pip)
    return _simulate_ratchet(bars, entry, side, exit_cfg, pip)


def _extremes(bar: dict, entry: float, side: str, pip: float):
    """(favorable_extreme_pips, adverse_extreme_pips) for one bar."""
    if side == "long":
        return _fav(bar["h"], entry, side, pip), -_fav(bar["l"], entry, side, pip)
    return _fav(bar["l"], entry, side, pip), -_fav(bar["h"], entry, side, pip)


def _simulate_ratchet(bars, entry, side, cfg, pip) -> ShadowOutcome:
    sl = float(cfg.get("sl_pips", 50.0) or 50.0)
    trigger = float(cfg.get("trigger_pips", 8.5) or 8.5)
    trail = float(cfg.get("trail_pips", 2.5) or 2.5)
    step = float(cfg.get("step_size_pips", DEFAULT_STEP_SIZE_PIPS) or DEFAULT_STEP_SIZE_PIPS)
    cadence_min = float(cfg.get("step_cadence_min", DEFAULT_CADENCE_MIN)
                        or DEFAULT_CADENCE_MIN)
    # M5 bars are the floor of what the sim can resolve — the live 0.5-min
    # cadence maps to "every bar", the old 20-min default mapped to every 4th
    cadence_bars = max(1, int(cadence_min / 5.0))

    lock: Optional[float] = None      # profit-direction pips; None = initial SL
    peak = 0.0
    mfe = 0.0
    mae = 0.0
    ambiguous = False

    for i, bar in enumerate(bars):
        fav, adv = _extremes(bar, entry, side, pip)
        mfe = max(mfe, fav)
        mae = max(mae, adv)
        stop_level = lock if lock is not None else -sl

        # one rule for both regimes: the bar's worst favorable-direction
        # excursion reaching the stop level (negative = initial SL below
        # entry, positive = locked profit floor) is a hit
        stop_hit = _bar_low_pips(bar, entry, side, pip) <= stop_level
        new_peak_possible = fav > peak

        if stop_hit:
            # worst case: the stop fires before any favorable excursion in
            # the same bar counts toward a better lock
            if new_peak_possible:
                ambiguous = True
            reason = "stop" if lock is not None else "initial_stop"
            return ShadowOutcome(round(stop_level, 2), reason, i,
                                 round(mfe, 2), round(mae, 2), ambiguous)

        peak = max(peak, fav)
        # cadence-gated lock evaluation (per the stamped/live cadence)
        if (i + 1) % cadence_bars == 0:
            new_lock = _ratchet_lock(peak, trigger, step, trail)
            if new_lock is not None and (lock is None or new_lock > lock):
                lock = new_lock

    close = _fav(bars[-1]["c"], entry, side, pip)
    return ShadowOutcome(round(close, 2), "horizon", len(bars) - 1,
                         round(mfe, 2), round(mae, 2), ambiguous)


def _bar_low_pips(bar: dict, entry: float, side: str, pip: float) -> float:
    """Worst favorable-direction excursion of the bar (for in-profit stops)."""
    return _fav(bar["l"] if side == "long" else bar["h"], entry, side, pip)


def _simulate_bracket(bars, entry, side, cfg, pip) -> ShadowOutcome:
    sl = float(cfg.get("sl_pips", 50.0) or 50.0)
    tp = float(cfg.get("tp_pips", 0.0) or 0.0)
    timeout_bars = None
    to_min = float(cfg.get("timeout_min", 0.0) or 0.0)
    if to_min > 0:
        timeout_bars = max(1, int(to_min / 5.0))
    mfe = mae = 0.0
    ambiguous = False
    for i, bar in enumerate(bars):
        fav, adv = _extremes(bar, entry, side, pip)
        mfe = max(mfe, fav)
        mae = max(mae, adv)
        tp_hit = tp > 0 and fav >= tp
        sl_hit = adv >= sl
        if sl_hit:
            if tp_hit:
                ambiguous = True      # both in one bar: worst case = stop
            return ShadowOutcome(round(-sl, 2), "initial_stop", i,
                                 round(mfe, 2), round(mae, 2), ambiguous)
        if tp_hit:
            return ShadowOutcome(round(tp, 2), "tp", i,
                                 round(mfe, 2), round(mae, 2), ambiguous)
        if timeout_bars is not None and i + 1 >= timeout_bars:
            close = _fav(bar["c"], entry, side, pip)
            return ShadowOutcome(round(close, 2), "timeout", i,
                                 round(mfe, 2), round(mae, 2), ambiguous)
    close = _fav(bars[-1]["c"], entry, side, pip)
    return ShadowOutcome(round(close, 2), "horizon", len(bars) - 1,
                         round(mfe, 2), round(mae, 2), ambiguous)
