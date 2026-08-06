"""tests/test_structure_features.py — market-structure feature builders.

Synthetic bars only; no broker, no feed. pip=1.0 throughout so a "pip" reads as
one price unit and the arithmetic in each assertion is checkable by eye.
"""
from core.feed.structure import (NO_LEVEL_PIPS, ema_trend_pips, impulse_blocks,
                                 liquidity_sweep)

PIP = 1.0
ATR = 4.0          # -> pool tolerance = max(pip, 4*0.25*1.0) = 1.0


def _pool_bars(sweep_close: float, sweep_high: float = 101.6):
    """40 bars with equal-high pivots at 101.0 (idx 10, 20) and a candidate
    sweep at idx 35 (inside the 6-bar sweep window, m=40 -> edge=34)."""
    highs, lows, closes = [], [], []
    for i in range(40):
        if i in (10, 20):
            highs.append(101.0); lows.append(99.0); closes.append(99.5)
        elif i == 35:
            highs.append(sweep_high); lows.append(99.0); closes.append(sweep_close)
        else:
            highs.append(99.5); lows.append(98.0); closes.append(99.0)
    return highs, lows, closes


def test_sweep_of_equal_highs_is_detected_with_penetration():
    hi, lo, cl = _pool_bars(sweep_close=100.0)
    high_sweep, low_sweep = liquidity_sweep(hi, lo, cl, PIP, ATR)
    assert high_sweep == 0.6      # 101.6 pierced 101.0, closed back inside
    assert low_sweep == 0.0


def test_clean_break_is_not_a_sweep():
    # same poke, but the close holds ABOVE the pool -> broken, not swept
    hi, lo, cl = _pool_bars(sweep_close=101.5)
    high_sweep, _ = liquidity_sweep(hi, lo, cl, PIP, ATR)
    assert high_sweep == 0.0


def test_single_touch_is_not_a_pool():
    hi, lo, cl = _pool_bars(sweep_close=100.0)
    hi[20] = 99.5                 # remove the second equal high
    high_sweep, _ = liquidity_sweep(hi, lo, cl, PIP, ATR)
    assert high_sweep == 0.0


def test_low_side_sweep_mirrors():
    highs, lows, closes = [], [], []
    for i in range(40):
        if i in (10, 20):
            highs.append(101.0); lows.append(99.0); closes.append(100.5)
        elif i == 35:
            highs.append(101.0); lows.append(98.4); closes.append(100.0)
        else:
            highs.append(102.0); lows.append(100.5); closes.append(101.0)
    high_sweep, low_sweep = liquidity_sweep(highs, lows, closes, PIP, ATR)
    assert low_sweep == 0.6       # 98.4 pierced the 99.0 pool, closed back above
    assert high_sweep == 0.0


def test_sweep_survives_short_or_degenerate_input():
    assert liquidity_sweep([], [], [], PIP, ATR) == (0.0, 0.0)
    assert liquidity_sweep([1.0] * 3, [1.0] * 3, [1.0] * 3, PIP, ATR) == (0.0, 0.0)
    assert liquidity_sweep([1.0] * 40, [1.0] * 40, [1.0] * 40, 0.0, ATR) == (0.0, 0.0)


def _impulse_bars(tail_low: float = 99.6, n: int = 30):
    """Origin bar at idx 5 (H 100.5 / L 99.5), then a +7 impulse over 3 bars.
    Threshold = 1.5 * ATR(4) * pip(1) = 6.0, so the move qualifies."""
    o, h, l, c = [], [], [], []
    for i in range(n):
        if i < 5:
            o.append(100.0); h.append(100.2); l.append(99.8); c.append(100.0)
        elif i == 5:
            o.append(100.0); h.append(100.5); l.append(99.5); c.append(100.0)
        elif i == 6:
            o.append(100.0); h.append(103.5); l.append(99.9); c.append(103.0)
        elif i == 7:
            o.append(103.0); h.append(106.5); l.append(102.5); c.append(106.0)
        elif i == 8:
            o.append(106.0); h.append(107.5); l.append(105.5); c.append(107.0)
        else:
            # gradual give-back: 0.5/bar means no 3-bar move ever reaches the
            # 6.0 impulse threshold, so no spurious supply zone is created
            px = max(101.0, 107.0 - 0.5 * (i - 8))
            o.append(px); h.append(px + 0.5); l.append(max(tail_low, px - 0.5))
            c.append(px)
    return o, h, l, c


def test_fresh_demand_zone_reports_distance_above_it():
    _, h, l, c = _impulse_bars()
    bull, bear = impulse_blocks(h, l, c, mid=101.0, pip=PIP, atr_pips=ATR)
    assert bull == 0.5            # mid 101.0 - zone top 100.5
    assert bear == NO_LEVEL_PIPS  # no down-impulse in this series


def test_price_inside_the_zone_goes_non_positive():
    _, h, l, c = _impulse_bars()
    bull, _ = impulse_blocks(h, l, c, mid=100.2, pip=PIP, atr_pips=ATR)
    assert bull == -0.3           # inside the 99.5-100.5 zone


def test_mitigated_zone_is_discarded():
    # a later bar trades BELOW the zone bottom -> the zone is spent
    _, h, l, c = _impulse_bars(tail_low=99.0, n=45)
    l[-1] = 99.0
    bull, _ = impulse_blocks(h, l, c, mid=101.0, pip=PIP, atr_pips=ATR)
    assert bull == NO_LEVEL_PIPS


def test_no_impulse_means_no_zone():
    flat = [100.0] * 30
    bull, bear = impulse_blocks([100.2] * 30, [99.8] * 30, flat,
                                mid=100.0, pip=PIP, atr_pips=ATR)
    assert bull == NO_LEVEL_PIPS and bear == NO_LEVEL_PIPS


def test_ema_trend_sign_tracks_direction():
    up = [100.0 + i * 0.1 for i in range(120)]
    down = [100.0 - i * 0.1 for i in range(120)]
    assert ema_trend_pips(up, PIP) > 0
    assert ema_trend_pips(down, PIP) < 0
    assert ema_trend_pips([100.0] * 120, PIP) == 0.0


def test_ema_trend_needs_history():
    assert ema_trend_pips([100.0] * 10, PIP) == 0.0
    assert ema_trend_pips([100.0] * 120, 0.0) == 0.0
