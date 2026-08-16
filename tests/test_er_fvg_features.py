"""tests/test_er_fvg_features.py — v6.29.0 trial features.

Synthetic bars, pip=1.0 (structure-features convention).

efficiency_ratio: straight lines read ~1, round trips read ~0, dead tape
reads 0.0 (fail-closes trend `min` gates). fair_value_gaps: the three-candle
window [high[i-2] .. low[i]] per the translated source, TOUCH-mitigated,
spread-sized micro-gaps rejected, NO_LEVEL sentinel when nothing qualifies.
"""
from core.feed.structure import (NO_LEVEL_PIPS, efficiency_ratio,
                                 fair_value_gaps)

PIP = 1.0
ATR = 4.0   # min gap = max(0.5, 0.10*4.0) = 0.4... -> 0.5 price units


# ── efficiency_ratio ─────────────────────────────────────────────────────────

def test_straight_line_is_full_efficiency():
    assert efficiency_ratio([float(i) for i in range(20)]) == 1.0


def test_round_trip_is_zero_efficiency():
    c = [100.0, 105.0, 100.0, 105.0, 100.0, 105.0, 100.0, 105.0, 100.0,
         105.0, 100.0]
    assert efficiency_ratio(c) == 0.0


def test_dead_tape_fails_closed():
    assert efficiency_ratio([100.0] * 20) == 0.0


def test_partial_efficiency_arithmetic():
    # 10 bars: +2 x8 then -2 x2 -> net 12, path 20 -> 0.6
    c = [100.0]
    for step in [2.0] * 8 + [-2.0] * 2:
        c.append(c[-1] + step)
    assert efficiency_ratio(c) == 0.6


def test_short_input_neutral():
    assert efficiency_ratio([1.0, 2.0]) == 0.0


# ── fair_value_gaps ──────────────────────────────────────────────────────────

def _flat(n, h=101.0, lo=99.0):
    return [h] * n, [lo] * n


def _with_bull_gap(touched=False):
    """Bars 0-9 flat, impulse: bar 10 h=101 l=99, bar 11 rallies, bar 12
    low=106 -> bullish FVG [101 .. 106]. Optional later touch at bar 14."""
    hi, lo = _flat(10)
    hi += [101.0, 107.0, 112.0, 113.0, 113.0]
    lo += [99.0, 100.5, 106.0, 106.5, 105.0 if touched else 108.0]
    return hi, lo


def test_bullish_fvg_detected_with_distance():
    hi, lo = _with_bull_gap()
    bull, bear = fair_value_gaps(hi, lo, 110.0, PIP, ATR)
    assert bull == 4.0            # mid 110 - zone top 106
    assert bear == NO_LEVEL_PIPS


def test_touched_fvg_is_spent():
    hi, lo = _with_bull_gap(touched=True)   # bar 14 low 105 re-enters window
    bull, _ = fair_value_gaps(hi, lo, 110.0, PIP, ATR)
    assert bull == NO_LEVEL_PIPS


def test_bearish_mirror():
    hi, lo = _flat(10)
    # bar 10 l=99, drop: bar 12 high=94 -> bearish FVG [94 .. 99]
    hi += [101.0, 98.0, 94.0, 93.0, 93.5]
    lo += [99.0, 92.0, 88.0, 87.0, 88.0]
    bull, bear = fair_value_gaps(hi, lo, 90.0, PIP, ATR)
    assert bear == 4.0            # zone bottom 94 - mid 90
    assert bull == NO_LEVEL_PIPS


def test_micro_gap_rejected():
    hi, lo = _flat(10)
    hi += [101.0, 101.2, 101.6, 101.7, 101.7]
    lo += [99.0, 100.8, 101.3, 101.4, 101.4]   # gap 101.0->101.3 = 0.3 < 0.5
    bull, bear = fair_value_gaps(hi, lo, 101.5, PIP, ATR)
    assert bull == NO_LEVEL_PIPS and bear == NO_LEVEL_PIPS


def test_no_gap_no_level():
    hi, lo = _flat(20)
    assert fair_value_gaps(hi, lo, 100.0, PIP, ATR) == (NO_LEVEL_PIPS,
                                                        NO_LEVEL_PIPS)


def test_degenerate_inputs():
    assert fair_value_gaps([], [], 100.0, PIP, ATR) == (NO_LEVEL_PIPS,
                                                        NO_LEVEL_PIPS)
    hi, lo = _with_bull_gap()
    assert fair_value_gaps(hi, lo, 110.0, 0.0, ATR) == (NO_LEVEL_PIPS,
                                                        NO_LEVEL_PIPS)
