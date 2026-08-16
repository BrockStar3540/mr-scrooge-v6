"""core/feed/structure.py — market-structure features (2026-08-06).

Three pure, deterministic feature builders, kept out of the feed so they can be
unit-tested against synthetic bars without a broker:

  liquidity_sweep()  — equal-high/low stop pools and the sweeps that take them
  impulse_blocks()   — impulse-origin (order-block) zones and freshness
  ema_trend_pips()   — fast/slow EMA separation as a trend-regime scalar

DESIGN NOTES (why these look the way they do)

* FX HAS NO REAL VOLUME. OANDA's `volume` is a tick count, not size, so none of
  these read "institutional participation" from volume the way a futures-based
  method would. They are pure PRICE-STRUCTURE features: where stops cluster,
  where an impulse originated, which way the trend leans. Any volume gating is
  left to the existing rvol_* features, which the caller can combine.

* TIME-CONSTANT PORT, not bar-count port. The source methodology used 69/200
  EMAs on 1-minute charts (~69 and ~200 MINUTES). Copying "69" and "200" onto
  M5 bars would silently produce 5.75h and 16.7h averages — a different animal,
  and EMA200 would be undercooked in a 240-bar window anyway. `ema_trend_pips`
  therefore defaults to 14/40 on M5 = ~70/200 minutes, preserving the intent.

* EVERYTHING IS RECOMPUTED PER CYCLE from the M5 window. No cross-cycle state,
  so a restart can never change a feature's value for the same input bars.

All functions take plain float sequences and return floats; they never raise.
"""
from __future__ import annotations

from typing import Sequence

# Sentinel for "no qualifying structure in range". Deliberately finite and
# large so absolute min/max conditions exclude it without special-casing.
NO_LEVEL_PIPS = 500.0


def _pivot_highs(highs: Sequence[float], k: int) -> list[int]:
    """Indices whose high is the max of the +/-k window (interior bars only)."""
    out = []
    n = len(highs)
    for i in range(k, n - k):
        h = highs[i]
        if all(h >= highs[j] for j in range(i - k, i + k + 1)) and \
           any(h > highs[j] for j in range(i - k, i + k + 1) if j != i):
            out.append(i)
    return out


def _pivot_lows(lows: Sequence[float], k: int) -> list[int]:
    out = []
    n = len(lows)
    for i in range(k, n - k):
        l = lows[i]
        if all(l <= lows[j] for j in range(i - k, i + k + 1)) and \
           any(l < lows[j] for j in range(i - k, i + k + 1) if j != i):
            out.append(i)
    return out


def _cluster(levels: list[float], tol: float, min_touches: int) -> list[float]:
    """Group levels within `tol` of each other; return the cluster EXTREME
    (max for highs, handled by caller sign) for clusters with enough touches."""
    if not levels:
        return []
    levels = sorted(levels)
    pools, cur = [], [levels[0]]
    for x in levels[1:]:
        if x - cur[0] <= tol:
            cur.append(x)
        else:
            if len(cur) >= min_touches:
                pools.append(cur)
            cur = [x]
    if len(cur) >= min_touches:
        pools.append(cur)
    return [max(c) for c in pools]


def liquidity_sweep(highs: Sequence[float], lows: Sequence[float],
                    closes: Sequence[float], pip: float, atr_pips: float, *,
                    pivot_k: int = 2, lookback: int = 120,
                    sweep_window: int = 6, min_touches: int = 2,
                    tol_atr_frac: float = 0.25) -> tuple[float, float]:
    """(high_sweep_pips, low_sweep_pips) — penetration of a stop pool that got
    rejected, 0.0 when no live sweep.

    A POOL is >= `min_touches` swing pivots resting within `tol` of each other
    — the classic equal-highs/equal-lows shape where stop orders accumulate.
    A SWEEP is a bar inside the last `sweep_window` whose EXTREME pierced the
    pool while its CLOSE came back inside: the level was taken and rejected,
    not broken. The returned value is that penetration in pips, so a condition
    can demand a minimum sweep size.

    Only pools formed BEFORE the sweep window are eligible, otherwise the
    sweep bar's own pivot could define the pool it is said to have swept.
    """
    try:
        n = len(highs)
        if n < pivot_k * 2 + 10 or pip <= 0:
            return 0.0, 0.0
        lo_i = max(0, n - lookback)
        h = list(highs)[lo_i:]
        l = list(lows)[lo_i:]
        c = list(closes)[lo_i:]
        m = len(h)
        w = min(sweep_window, m - 1)
        if w < 1:
            return 0.0, 0.0
        tol = max(pip, (atr_pips if atr_pips > 0 else 1.0) * tol_atr_frac * pip)

        # pools may only use pivots that closed before the sweep window opened
        edge = m - w
        ph = [h[i] for i in _pivot_highs(h[:edge], pivot_k)]
        pl = [l[i] for i in _pivot_lows(l[:edge], pivot_k)]
        pools_hi = _cluster(ph, tol, min_touches)
        pools_lo = [-x for x in _cluster([-x for x in pl], tol, min_touches)]

        hi_sweep = 0.0
        for lvl in pools_hi:
            for j in range(edge, m):
                if h[j] > lvl and c[j] < lvl:
                    hi_sweep = max(hi_sweep, (h[j] - lvl) / pip)
        lo_sweep = 0.0
        for lvl in pools_lo:
            for j in range(edge, m):
                if l[j] < lvl and c[j] > lvl:
                    lo_sweep = max(lo_sweep, (lvl - l[j]) / pip)
        return round(hi_sweep, 2), round(lo_sweep, 2)
    except Exception:
        return 0.0, 0.0


def impulse_blocks(highs: Sequence[float], lows: Sequence[float],
                   closes: Sequence[float],
                   mid: float, pip: float, atr_pips: float, *,
                   lookback: int = 120, impulse_bars: int = 3,
                   impulse_mult: float = 1.5) -> tuple[float, float]:
    """(bull_dist_pips, bear_dist_pips) — signed distance from `mid` to the
    nearest UNMITIGATED impulse-origin zone, NO_LEVEL_PIPS when none exists.

    An IMPULSE is a run of `impulse_bars` whose net close-to-close move exceeds
    `impulse_mult` x ATR. Its ORIGIN ZONE is the bar that launched it (the last
    bar before the move), taken as that bar's full high-low range — this is the
    standard order-block / supply-demand construction.

    UNMITIGATED means price has not yet traded fully back through the zone: a
    demand zone dies the moment a later bar's LOW prints below its bottom. Once
    mitigated a zone is spent and is not returned.

    bull_dist_pips = mid - zone_top  (>0 above the zone, <=0 inside it)
    bear_dist_pips = zone_bottom - mid (>0 below the zone, <=0 inside it)
    so "price is at the zone" is a band straddling zero in both cases.
    """
    try:
        n = len(closes)
        if n < impulse_bars + 5 or pip <= 0 or atr_pips <= 0:
            return NO_LEVEL_PIPS, NO_LEVEL_PIPS
        lo_i = max(0, n - lookback)
        h = list(highs)[lo_i:]
        l = list(lows)[lo_i:]
        c = list(closes)[lo_i:]
        m = len(c)
        thresh = impulse_mult * atr_pips * pip

        bull_top: float | None = None   # nearest fresh demand zone below mid
        bear_bot: float | None = None   # nearest fresh supply zone above mid

        for i in range(m - impulse_bars - 1):
            j = i + impulse_bars
            move = c[j] - c[i]
            if move >= thresh:                     # up-impulse -> demand zone
                z_top, z_bot = h[i], l[i]
                if any(l[k] < z_bot for k in range(j + 1, m)):
                    continue                        # mitigated
                # eligible when the zone sits at or below price INCLUDING the
                # case where price is inside it — being in the zone is the
                # entry condition, not a disqualifier.
                if z_bot <= mid and (bull_top is None or z_top > bull_top):
                    bull_top = z_top
            elif -move >= thresh:                   # down-impulse -> supply zone
                z_top, z_bot = h[i], l[i]
                if any(h[k] > z_top for k in range(j + 1, m)):
                    continue                        # mitigated
                if z_top >= mid and (bear_bot is None or z_bot < bear_bot):
                    bear_bot = z_bot

        bull = NO_LEVEL_PIPS if bull_top is None else (mid - bull_top) / pip
        bear = NO_LEVEL_PIPS if bear_bot is None else (bear_bot - mid) / pip
        return (round(min(bull, NO_LEVEL_PIPS), 2),
                round(min(bear, NO_LEVEL_PIPS), 2))
    except Exception:
        return NO_LEVEL_PIPS, NO_LEVEL_PIPS


def ema_trend_pips(closes: Sequence[float], pip: float, *,
                   fast: int = 14, slow: int = 40) -> float:
    """EMA(fast) - EMA(slow) in pips. Sign = regime, magnitude = separation.

    Defaults are the TIME-EQUIVALENT of the source method's 69/200 EMAs on a
    1-minute chart (~70 and ~200 minutes) expressed in M5 bars. See module
    docstring on why the raw bar counts were not copied.
    """
    try:
        c = list(closes)
        if len(c) < slow + 5 or pip <= 0:
            return 0.0

        def _ema(vals, span):
            a = 2.0 / (span + 1.0)
            e = vals[0]
            for v in vals[1:]:
                e = a * v + (1 - a) * e
            return e

        return round((_ema(c, fast) - _ema(c, slow)) / pip, 2)
    except Exception:
        return 0.0


def session_orb(labels: Sequence[int], highs: Sequence[float],
                lows: Sequence[float], mid: float, pip: float, *,
                orb_bars: int = 3) -> tuple:
    """Session OPENING RANGE (first `orb_bars` M5 bars = 15 min) of the
    CURRENT session run. Source: Máximo NQ/MNQ 1-Minute Scalping Toolkit
    (open-source TradingView, translated 2026-08-15) — the one concept in it
    the feed lacked. FX caveat logged at wiring: session opens are softer than
    a cash equity open, so the prior is deliberately weaker.

    labels: per-bar coarse-session ids (same walk `_session_vwap_dist` uses);
    the current run = trailing bars sharing the last label.

    Returns (orb_hi_dist, orb_lo_dist, orb_pos, orb_range_pips), all vs `mid`:
      orb_hi_dist  pips above (+) / below (−) the ORB high
      orb_lo_dist  pips above (+) / below (−) the ORB low
      orb_pos      0..1 inside the range (can exceed either side)
      orb_range_pips  ORB height — 0.0 while the range is STILL FORMING (or on
        any degenerate input), so a `min` condition on it fail-closes every
        ORB setup until 15 real minutes exist.
    """
    try:
        n = len(labels)
        if n == 0 or n != len(highs) or n != len(lows) or pip <= 0:
            return 0.0, 0.0, 0.5, 0.0
        start = n - 1
        while start > 0 and labels[start - 1] == labels[-1]:
            start -= 1
        run = n - start
        if run < orb_bars:                      # range still forming
            return 0.0, 0.0, 0.5, 0.0
        orb_hi = max(highs[start:start + orb_bars])
        orb_lo = min(lows[start:start + orb_bars])
        rng = orb_hi - orb_lo
        if rng <= 0:
            return 0.0, 0.0, 0.5, 0.0
        return (round((mid - orb_hi) / pip, 1),
                round((mid - orb_lo) / pip, 1),
                round((mid - orb_lo) / rng, 4),
                round(rng / pip, 1))
    except Exception:
        return 0.0, 0.0, 0.5, 0.0
