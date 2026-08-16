"""core/feed/oanda.py — OANDA REST v3 candles + pricing → MarketView for all V5 pairs.

Credentials: OANDA_API_URL, OANDA_API_TOKEN, OANDA_ACCOUNT_ID
Loaded from ~/.openclaw/secrets.env (never stored in code or repo).

Public API:
    feed = OandaFeed()
    views = feed.get_views(PAIRS)   # list[MarketView], one per pair per M5 cycle

Errors are isolated per pair — one pair's fetch failure never blocks others.
"""
from __future__ import annotations
import json, logging, os, urllib.request
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd

from config.pairs import PIP
from modules.signals.base import MarketView

log = logging.getLogger("v5.feed")

_SECRETS_CACHE: Optional[dict] = None

# Candle counts — enough lookback for every indicator
_M5_COUNT = 240   # covers 20h of M5 bars; prev-session H/L needs up to ~18h (ny after full asia)
_H1_COUNT = 200   # 200H; need 65 for RSI14+slope, 61 for htf_pct_60, ~100 for atr_h1_relative baseline
_D_COUNT  = 100   # 100 days; need 63 for htf_pct_60


# ── Credentials ─────────────────────────────────────────────────────────────

def _secrets() -> dict:
    """Resolve OANDA credentials for this instance — SAME path as the broker.

    Delegates to config.credentials.resolve_oanda_creds() so a fresh public-repo
    clone that supplied keys via the dashboard CONNECTION tab (config/
    credentials.local.json) gets a working FEED, not just a working broker.
    Precedence: env vars > ~/.openclaw/secrets.env > credentials.local.json[mode].
    Falls back to the legacy secrets.env-only reader if the module is absent.
    Cached; a credential/mode change takes effect on restart (documented)."""
    global _SECRETS_CACHE
    if _SECRETS_CACHE is not None:
        return _SECRETS_CACHE
    try:
        from config.credentials import resolve_oanda_creds
        out = resolve_oanda_creds()
    except Exception as exc:                          # never let creds import break the feed
        log.warning("credentials module unavailable (%s); using secrets.env only", exc)
        path = os.path.expanduser("~/.openclaw/secrets.env")
        out = {}
        if os.path.exists(path):
            for raw in open(path):
                line = raw.strip()
                if line and "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    k = k.replace("export ", "").strip()
                    out[k] = v.strip()
    _SECRETS_CACHE = out
    return out


# 3-session mapping is the canonical one in config.sessions (single source of
# truth, shared with the playmaker eligibility gate).
from config.sessions import coarse_session as _coarse_session


# ── HTTP helper ──────────────────────────────────────────────────────────────

class _Client:
    def __init__(self):
        s = _secrets()
        self.base  = s.get("OANDA_API_URL",   "").rstrip("/")
        self.token = s.get("OANDA_API_TOKEN",  "")
        self.acct  = s.get("OANDA_ACCOUNT_ID", "")

    def get(self, path: str) -> dict:
        req = urllib.request.Request(
            self.base + path,
            headers={"Authorization": f"Bearer {self.token}",
                     "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())

    def candles(self, instrument: str, granularity: str, count: int) -> pd.DataFrame:
        """Fetch completed + current forming candle; return OHLCV DataFrame."""
        raw = self.get(
            f"/v3/instruments/{instrument}/candles"
            f"?granularity={granularity}&count={count}&price=M"
        )["candles"]
        rows = []
        for i, c in enumerate(raw):
            if not c.get("complete", True) and i < len(raw) - 1:
                continue          # drop incomplete non-last bars
            m = c["mid"]
            rows.append({
                "time":   c["time"],
                "open":   float(m["o"]),
                "high":   float(m["h"]),
                "low":    float(m["l"]),
                "close":  float(m["c"]),
                "volume": float(c.get("volume", 1.0)),
            })
        return pd.DataFrame(rows)

    def pricing(self, instrument: str) -> tuple[float, float]:
        """Return (bid, ask) for instrument."""
        p = self.get(
            f"/v3/accounts/{self.acct}/pricing?instruments={instrument}"
        )["prices"][0]
        return float(p["bids"][0]["price"]), float(p["asks"][0]["price"])


# ── Indicator helpers (match V3/V4 exactly — dm_04 corpus was built with these) ─

from core.feed.structure import (ema_trend_pips as _ema_trend_pips,
                                 session_orb as _session_orb_calc,
                                 impulse_blocks as _impulse_blocks,
                                 liquidity_sweep as _liquidity_sweep)


def _adx14(df: pd.DataFrame, period: int = 14) -> float:
    """Wilder ADX(14) on the given frame (H1). 0 when insufficient bars."""
    if len(df) < period * 2 + 1:
        return 0.0
    h, l, c = df["high"].astype(float), df["low"].astype(float), df["close"].astype(float)
    up = h.diff()
    dn = -l.diff()
    plus_dm = ((up > dn) & (up > 0)) * up
    minus_dm = ((dn > up) & (dn > 0)) * dn
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()],
                   axis=1).max(axis=1)
    atr = tr.ewm(alpha=1.0 / period, adjust=False).mean()
    pdi = 100 * plus_dm.ewm(alpha=1.0 / period, adjust=False).mean() / atr
    mdi = 100 * minus_dm.ewm(alpha=1.0 / period, adjust=False).mean() / atr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, 1e-9)
    adx = dx.ewm(alpha=1.0 / period, adjust=False).mean()
    v = float(adx.iloc[-1])
    return round(v, 2) if v == v else 0.0


def _session_vwap_dist(m5: pd.DataFrame, mid: float, pip: float) -> float:
    """mid − VWAP anchored at the CURRENT coarse session's start, in pips.
    Typical price × tick volume over the current session run of M5 bars
    (session labels per config/sessions.py windows)."""
    try:
        if "time" in m5.columns:
            hours = [int(str(t)[11:13]) for t in m5["time"]]
        else:
            hours = list(m5.index.hour)
        lbl = [(0 if (h >= 22 or h < 7) else (1 if h < 13 else 2)) for h in hours]
        start = len(lbl) - 1
        while start > 0 and lbl[start - 1] == lbl[-1]:
            start -= 1
        seg = m5.iloc[start:]
        tp = (seg["high"].astype(float) + seg["low"].astype(float)
              + seg["close"].astype(float)) / 3.0
        vol = seg["volume"].astype(float).clip(lower=1e-9)
        vwap = float((tp * vol).sum() / vol.sum())
        return round((mid - vwap) / pip, 1)
    except Exception:
        return 0.0


def _session_orb(m5: pd.DataFrame, mid: float, pip: float) -> tuple:
    """(orb_hi_dist, orb_lo_dist, orb_pos, orb_range_pips) for the CURRENT
    coarse session — same session labeling as _session_vwap_dist; the range
    math lives in core.feed.structure.session_orb (pure, tested)."""
    try:
        if "time" in m5.columns:
            hours = [int(str(t)[11:13]) for t in m5["time"]]
        else:
            hours = list(m5.index.hour)
        lbl = [(0 if (h >= 22 or h < 7) else (1 if h < 13 else 2)) for h in hours]
        return _session_orb_calc(lbl, [float(x) for x in m5["high"]],
                                 [float(x) for x in m5["low"]], mid, pip)
    except Exception:
        return 0.0, 0.0, 0.5, 0.0


def _atr14(df: pd.DataFrame, pip: float) -> float:
    """Wilder ATR14 in pips. V3-exact: slice last 30 bars → TR → EWM(1/14)."""
    if df is None or len(df) < 15:
        return 0.0
    df2 = df.iloc[-30:]
    h  = df2["high"].astype(float)
    l  = df2["low"].astype(float)
    pc = df2["close"].astype(float).shift(1)
    tr = pd.concat([(h - l).abs(), (h - pc).abs(), (l - pc).abs()],
                   axis=1).max(axis=1).dropna()
    if len(tr) < 14:
        return 0.0
    return float(tr.ewm(alpha=1.0 / 14, adjust=False).mean().iloc[-1]) / pip


def _vortex_diff(df: pd.DataFrame, period: int = 14) -> float:
    """Vortex VI+ minus VI- on the last `period` bars. Directional indicator.

    VI+ = sum(|H[t] - L[t-1]|) / sum(TR) over last `period` bars
    VI- = sum(|L[t] - H[t-1]|) / sum(TR) over last `period` bars
    Returns (VI+ - VI-) as a float; >0 = up-pressure, <0 = down-pressure.
    """
    if df is None or len(df) < period + 2:
        return 0.0
    df2 = df.iloc[-(period+2):]
    h = df2["high"].astype(float)
    l = df2["low"].astype(float)
    c = df2["close"].astype(float)
    pc = c.shift(1)
    tr = pd.concat([(h - l).abs(), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1).dropna()
    if len(tr) < period:
        return 0.0
    vm_plus  = (h - l.shift(1)).abs().dropna()
    vm_minus = (l - h.shift(1)).abs().dropna()
    sum_tr   = float(tr.iloc[-period:].sum())
    if sum_tr <= 0:
        return 0.0
    vi_plus  = float(vm_plus.iloc[-period:].sum())  / sum_tr
    vi_minus = float(vm_minus.iloc[-period:].sum()) / sum_tr
    return vi_plus - vi_minus


# ── 2026-06-23 matrix shadow features (Williams %R, Aroon Osc, KC up dist, EFI) ──
def _willr(df: pd.DataFrame, period: int = 14) -> float:
    """Williams %R on the last bar. Range -100..0; -50 = midpoint, -100 = extreme oversold."""
    if df is None or len(df) < period + 1:
        return 0.0
    seg = df.iloc[-period:]
    hh = float(seg["high"].max())
    ll = float(seg["low"].min())
    c  = float(df["close"].iloc[-1])
    if hh == ll:
        return -50.0
    return -100.0 * (hh - c) / (hh - ll)


def _aroon_osc(df: pd.DataFrame, period: int = 14) -> float:
    """Aroon Oscillator = AroonUp − AroonDown over last `period` bars, on H1."""
    if df is None or len(df) < period + 1:
        return 0.0
    seg = df.iloc[-(period + 1):]
    highs = seg["high"].astype(float).reset_index(drop=True)
    lows  = seg["low"].astype(float).reset_index(drop=True)
    # Position of the highest-high / lowest-low within last `period+1` bars (0..period)
    idx_hh = int(highs.idxmax())
    idx_ll = int(lows.idxmin())
    aroon_up   = 100.0 * idx_hh / period
    aroon_down = 100.0 * idx_ll / period
    return aroon_up - aroon_down


def _kc_up_dist_pips(df: pd.DataFrame, pip: float, period: int = 20, mult: float = 2.0) -> float:
    """Distance from current close to upper Keltner Channel band, in pips. Signed.
    Upper KC = EMA(close, period) + mult × ATR(period). Positive = close above band."""
    if df is None or len(df) < period + 1:
        return 0.0
    c = df["close"].astype(float)
    h = df["high"].astype(float)
    l = df["low"].astype(float)
    pc = c.shift(1)
    tr = pd.concat([(h - l).abs(), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1.0 / period, adjust=False).mean()
    ema = c.ewm(span=period, adjust=False).mean()
    upper = ema + mult * atr
    return float((c.iloc[-1] - upper.iloc[-1]) / pip)


def _efi(df: pd.DataFrame, period: int = 13) -> float:
    """Elder Force Index: (close - prev_close) × volume, smoothed with EMA(period)."""
    if df is None or len(df) < period + 2:
        return 0.0
    c = df["close"].astype(float)
    v = df["volume"].astype(float)
    raw = (c - c.shift(1)) * v
    return float(raw.ewm(span=period, adjust=False).mean().iloc[-1])


def _rsi14_series(closes: pd.Series) -> pd.Series:
    """Wilder RSI14 series on the full close series."""
    delta = closes.astype(float).diff()
    gain  = delta.clip(lower=0).ewm(alpha=1.0 / 14, adjust=False).mean()
    loss  = (-delta.clip(upper=0)).ewm(alpha=1.0 / 14, adjust=False).mean()
    rs    = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(100)


def _ema(closes: pd.Series, span: int) -> pd.Series:
    return closes.astype(float).ewm(span=span, adjust=False).mean()


# ── Per-pair feature computation ─────────────────────────────────────────────

def _compute_features(
    pair: str,
    m5:   pd.DataFrame,
    h1:   pd.DataFrame,
    d:    pd.DataFrame,
    bid:  float,
    ask:  float,
    ts:   datetime,
) -> MarketView:
    pip  = PIP[pair]
    mid  = (bid + ask) / 2.0
    sess = _coarse_session(ts.hour)

    # ── Previous-session structure (2026-07-10) ──────────────────────────────
    # Prev session's H/L from the M5 history: label each bar's coarse session,
    # blocks = consecutive same-label runs, take the last COMPLETED block.
    ps_high_dist, ps_low_dist, ps_pos = 0.0, 0.0, 0.5
    try:
        if "time" in m5.columns:
            _tt = m5["time"]
            _hours = [t.hour if hasattr(t, "hour") else int(str(t)[11:13]) for t in _tt]
        else:
            _hours = list(m5.index.hour)
        _lbl = [(0 if (h >= 22 or h < 7) else (1 if h < 13 else 2)) for h in _hours]
        _blocks: list = []
        for _i, _l in enumerate(_lbl):
            if not _blocks or _l != _lbl[_blocks[-1][0]]:
                _blocks.append([_i, _i])
            else:
                _blocks[-1][1] = _i
        if len(_blocks) >= 2:
            _s, _e = _blocks[-2]
            _ps_h = float(m5["high"].iloc[_s:_e+1].max())
            _ps_l = float(m5["low"].iloc[_s:_e+1].min())
            ps_high_dist = (mid - _ps_h) / pip
            ps_low_dist  = (mid - _ps_l) / pip
            if _ps_h > _ps_l:
                ps_pos = max(0.0, min(1.0, (mid - _ps_l) / (_ps_h - _ps_l)))
    except Exception as _pse:
        log.warning("prev-session structure failed for %s: %s", pair, _pse)

    # ── H1 features ─────────────────────────────────────────────────────────
    h1c  = h1["close"].astype(float)
    h1h  = h1["high"].astype(float)
    h1l  = h1["low"].astype(float)

    # h1_ret_1bar: last completed H1 bar return
    h1_ret_1bar = (float(h1c.iloc[-1]) - float(h1c.iloc[-2])) / pip

    # h1_ret_4bar: sum of last 4 H1 bar returns
    h1_ret_4bar = (float(h1c.iloc[-1]) - float(h1c.iloc[-5])) / pip

    # RSI14 on H1 (Wilder EWM) + slope
    rsi_ser  = _rsi14_series(h1c)
    rsi14    = float(rsi_ser.iloc[-1])
    rsi_slope = float(rsi_ser.iloc[-1] - rsi_ser.iloc[-3])   # 2-bar delta

    # zscore_1h: H1 Z-score vs 20-bar SMA
    h1_sma20 = float(h1c.iloc[-20:].mean())
    h1_std20 = float(h1c.iloc[-20:].std(ddof=1))
    zscore_1h = (float(h1c.iloc[-1]) - h1_sma20) / h1_std20 if h1_std20 > 0 else 0.0

    # ema20_1h_dist: H1 EMA20 fractional distance
    ema20_h1 = float(_ema(h1c, 20).iloc[-1])
    ema20_1h_dist = (mid - ema20_h1) / mid if mid > 0 else 0.0

    # atr_1h (single Wilder ATR14 value)
    atr_1h = _atr14(h1, pip)

    # atr_h1_relative: current 1H ATR / its rolling-mean over recent window
    # Mirrors the canonical definition in scripts/v5_smoke_nightly.py compute_features_at()
    # Used by v2 direction aggregator rules (atr_h1_relative > 1.6 → boost reversion / suppress HTF)
    try:
        _h1h = h1["high"].astype(float); _h1l = h1["low"].astype(float)
        _h1pc = h1["close"].astype(float).shift(1)
        _h1_tr = pd.concat([(_h1h - _h1l).abs(), (_h1h - _h1pc).abs(), (_h1l - _h1pc).abs()],
                          axis=1).max(axis=1).dropna()
        _h1_atr_series = _h1_tr.ewm(alpha=1.0 / 14, adjust=False).mean()
        _baseline = _h1_atr_series.iloc[-100:] if len(_h1_atr_series) >= 100 else _h1_atr_series
        _bmean = float(_baseline.mean())
        atr_h1_relative = float(_h1_atr_series.iloc[-1]) / _bmean if _bmean > 0 else 1.0
    except Exception:
        atr_h1_relative = 1.0

    # trend_4h: sign of h1_ret_4bar (V3 candidate; v2 direction profiles weight it)
    if   h1_ret_4bar > 0: trend_4h = 1.0
    elif h1_ret_4bar < 0: trend_4h = -1.0
    else:                 trend_4h = 0.0

    # vortex_diff_h1: Vortex VI+ minus VI- on H1, period 14 (Master Matrix 2026-06-21)
    # Directional signal: >0 = up-pressure, <0 = down-pressure. SHADOW until 2026-07-04.
    try:
        vortex_diff_h1 = _vortex_diff(h1, period=14)
    except Exception:
        vortex_diff_h1 = 0.0

    # 2026-06-23 matrix shadow features (no scoring; CYCLE log only):
    #   willr_m5 (Williams %R, M5/14), aroonosc_h1 (Aroon Osc, H1/14),
    #   kc_up_dist_pips (Keltner upper band distance, M5/20),
    #   efi (Elder Force Index, M5/13).
    try:    willr_m5         = _willr(m5, period=14)
    except Exception: willr_m5 = 0.0
    try:    aroonosc_h1      = _aroon_osc(h1, period=14)
    except Exception: aroonosc_h1 = 0.0
    try:    kc_up_dist_pips  = _kc_up_dist_pips(m5, pip, period=20, mult=2.0)
    except Exception: kc_up_dist_pips = 0.0
    try:    efi              = _efi(m5, period=13)
    except Exception: efi    = 0.0

    # htf_pct (from daily closes — computed in D section below, placeholder for now)
    htf_pct_20 = 0.0
    htf_pct_60 = 0.0

    # ── Daily features ───────────────────────────────────────────────────────
    d_ret          = 0.0
    close_pos_daily = 0.0
    adr_consumed   = 0.0
    atr_d_pips     = 0.0
    pdh_dist       = 0.0
    pdl_dist       = 0.0
    pdh_dist_atr_pct = 0.0
    pdl_dist_atr_pct = 0.0
    d_range_pips   = 0.0

    if d is not None and len(d) >= 63:
        dc   = d["close"].astype(float)
        dh   = d["high"].astype(float)
        dl   = d["low"].astype(float)
        do_  = d["open"].astype(float)

        htf_pct_20 = float(dc.iloc[-1] / dc.iloc[-21] - 1.0)
        htf_pct_60 = float(dc.iloc[-1] / dc.iloc[-61] - 1.0)

        # Today's intraday data is in the last D bar (incomplete)
        today_high  = float(dh.iloc[-1])
        today_low   = float(dl.iloc[-1])
        today_open  = float(do_.iloc[-1])
        today_range = today_high - today_low

        d_ret = (mid - today_open) / pip
        close_pos_daily = (mid - today_low) / today_range if today_range > 0 else 0.5
        d_range_pips    = today_range / pip

        atr_d_val  = _atr14(d, pip)
        atr_d_pips = atr_d_val
        if atr_d_val > 0:
            adr_consumed = (today_range / pip) / atr_d_val

        # prev-day levels from the D[-2] bar (yesterday's completed bar)
        pdh = float(dh.iloc[-2])
        pdl = float(dl.iloc[-2])
        pdh_dist = (mid - pdh) / pip
        pdl_dist = (mid - pdl) / pip
        if atr_d_val > 0:
            pdh_dist_atr_pct = pdh_dist / atr_d_val
            pdl_dist_atr_pct = pdl_dist / atr_d_val

    # ── M5 features ──────────────────────────────────────────────────────────
    m5c  = m5["close"].astype(float)
    m5h  = m5["high"].astype(float)
    m5l  = m5["low"].astype(float)
    m5v  = m5["volume"].astype(float)

    atr_5m = _atr14(m5, pip)

    # BB on last 20 M5 bars (close prices)
    bb_sma = float(m5c.iloc[-20:].mean())
    bb_std = float(m5c.iloc[-20:].std(ddof=1))
    bb_upper = bb_sma + 2 * bb_std
    bb_lower = bb_sma - 2 * bb_std
    bb_range = bb_upper - bb_lower
    bb_pos   = (mid - bb_lower) / bb_range if bb_range > 0 else 0.5
    bb_width = bb_range / pip

    # zscore_5m
    zscore_5m = (mid - bb_sma) / bb_std if bb_std > 0 else 0.0

    # EMA distances (5m)
    ema5_m5  = float(_ema(m5c, 5).iloc[-1])
    ema20_m5 = float(_ema(m5c, 20).iloc[-1])
    ema50_m5 = float(_ema(m5c, 50).iloc[-1]) if len(m5c) >= 50 else mid

    ema20_dist_pct = (mid - ema20_m5) / mid if mid > 0 else 0.0
    ema5_dist_pips = (mid - ema5_m5) / pip
    ema50_dist_pct = (mid - ema50_m5) / mid if mid > 0 else 0.0
    ema_cross_pips = (ema5_m5 - ema20_m5) / pip

    # Lagged returns (pips) — cumulative over window
    ret_5m  = (float(m5c.iloc[-1]) - float(m5c.iloc[-2]))  / pip
    ret_15m = (float(m5c.iloc[-1]) - float(m5c.iloc[-4]))  / pip   # 3 bars = 15m
    ret_30m = (float(m5c.iloc[-1]) - float(m5c.iloc[-7]))  / pip   # 6 bars = 30m
    ret_1h  = (float(m5c.iloc[-1]) - float(m5c.iloc[-13])) / pip   # 12 bars = 1h

    # Relative volume (tick-count based)
    # rvol_5bar:  mean of last 5 bars / mean of prior 20-bar baseline
    # rvol_12bar: mean of last 12 bars / mean of prior 20-bar baseline
    baseline_vol = float(m5v.iloc[-32:-1].mean()) if len(m5v) >= 33 else float(m5v.mean())
    baseline_vol = max(baseline_vol, 1.0)
    rvol_5bar    = float(m5v.iloc[-5:].mean())  / baseline_vol
    rvol_12bar   = float(m5v.iloc[-12:].mean()) / baseline_vol

    # Range measures
    range_5bar  = (float(m5h.iloc[-5:].max())  - float(m5l.iloc[-5:].min()))  / pip
    range_12bar = (float(m5h.iloc[-12:].max()) - float(m5l.iloc[-12:].min())) / pip

    # ATR concentration (atr_5m / atr_1h — short-term vs hourly vol ratio)
    atr_conc = atr_5m / atr_1h if atr_1h > 0 else 0.0

    # ── Market structure (2026-08-06): stop pools, impulse-origin zones,
    # trend regime. Recomputed from the M5 window every cycle, no state.
    _m5h_l = [float(x) for x in m5h]
    _m5l_l = [float(x) for x in m5l]
    _m5c_l = [float(x) for x in m5c]
    liq_hi, liq_lo = _liquidity_sweep(_m5h_l, _m5l_l, _m5c_l, pip, atr_5m)
    ob_bull, ob_bear = _impulse_blocks(_m5h_l, _m5l_l, _m5c_l, mid, pip, atr_5m)
    ema_trend = _ema_trend_pips(_m5c_l, pip)
    _orb = _session_orb(m5, mid, pip)

    spread_pips = (ask - bid) / pip

    return MarketView(
        pair=pair, session=sess, timestamp=ts,
        # Required H1 fields
        h1_ret_1bar=round(h1_ret_1bar, 4),
        h1_ret_4bar=round(h1_ret_4bar, 4),
        rsi14=round(rsi14, 4),
        rsi_slope=round(rsi_slope, 4),
        zscore_1h=round(zscore_1h, 4),
        ema20_1h_dist=round(ema20_1h_dist, 6),
        # HTF
        htf_pct_20=round(htf_pct_20, 6),
        htf_pct_60=round(htf_pct_60, 6),
        # Level distances
        pdh_dist=round(pdh_dist, 4),
        pdl_dist=round(pdl_dist, 4),
        pdh_dist_atr_pct=round(pdh_dist_atr_pct, 4),
        pdl_dist_atr_pct=round(pdl_dist_atr_pct, 4),
        ps_high_dist=round(ps_high_dist, 4),
        ps_low_dist=round(ps_low_dist, 4),
        ps_pos=round(ps_pos, 4),
        # Daily context
        d_ret=round(d_ret, 4),
        close_pos_daily=round(close_pos_daily, 4),
        adr_consumed=round(adr_consumed, 4),
        vwap_dist_pips=_session_vwap_dist(m5, mid, pip),
        # Session opening range (v6.28.0, Máximo toolkit translation)
        orb_hi_dist=_orb[0], orb_lo_dist=_orb[1],
        orb_pos=_orb[2], orb_range_pips=_orb[3],
        adx14=_adx14(h1),
        # Mean-reversion (M5)
        bb_pos=round(bb_pos, 4),
        bb_width=round(bb_width, 4),
        zscore_5m=round(zscore_5m, 4),
        ema20_dist_pct=round(ema20_dist_pct, 6),
        ema5_dist_pips=round(ema5_dist_pips, 4),
        ema50_dist_pct=round(ema50_dist_pct, 6),
        ema_cross_pips=round(ema_cross_pips, 4),
        ret_5m=round(ret_5m, 4),
        ret_15m=round(ret_15m, 4),
        ret_30m=round(ret_30m, 4),
        ret_1h=round(ret_1h, 4),
        # Vol / magnitude
        atr_5m=round(atr_5m, 4),
        atr_1h=round(atr_1h, 4),
        atr_d_pips=round(atr_d_pips, 4),
        rvol_5bar=round(rvol_5bar, 4),
        rvol_12bar=round(rvol_12bar, 4),
        range_5bar=round(range_5bar, 4),
        range_12bar=round(range_12bar, 4),
        d_range_pips=round(d_range_pips, 4),
        atr_conc=round(atr_conc, 4),
        atr_h1_relative=round(atr_h1_relative, 4),
        trend_4h=trend_4h,
        vortex_diff_h1=round(vortex_diff_h1, 4),
        willr_m5=round(willr_m5, 2),
        aroonosc_h1=round(aroonosc_h1, 2),
        kc_up_dist_pips=round(kc_up_dist_pips, 2),
        efi=round(efi, 4),
        # Market structure (2026-08-06 trial features)
        liq_sweep_high=liq_hi,
        liq_sweep_low=liq_lo,
        ob_bull_dist_pips=ob_bull,
        ob_bear_dist_pips=ob_bear,
        ema_trend_pips=ema_trend,
        # Execution
        bid=bid, ask=ask, spread_pips=round(spread_pips, 4),
    )


# ── Feed class ───────────────────────────────────────────────────────────────

class OandaFeed:
    """OANDA REST feed — builds one MarketView per pair per M5 cycle."""

    def __init__(self):
        self._client = _Client()
        self._errors: list[str] = []

    def pricing(self, pair: str) -> tuple[float, float]:
        """Cheap (bid, ask) poll for one instrument -- no candle fetch. Used by the
        engine fast management loop to trail stops between 5-min scan cycles."""
        return self._client.pricing(pair)

    def get_views(self, pairs: list[str]) -> list[MarketView]:
        """Fetch candles + pricing for each pair; return completed MarketViews.

        Per-pair errors are logged and skipped — the other pairs still process.
        """
        self._errors = []
        views: list[MarketView] = []
        ts = datetime.now(timezone.utc)

        for pair in pairs:
            try:
                m5  = self._client.candles(pair, "M5", _M5_COUNT)
                h1  = self._client.candles(pair, "H1", _H1_COUNT)
                d   = self._client.candles(pair, "D",  _D_COUNT)
                bid, ask = self._client.pricing(pair)
                view = _compute_features(pair, m5, h1, d, bid, ask, ts)
                views.append(view)
                log.debug("feed ok %s  atr5m=%.2f  sess=%s  spread=%.2fp",
                          pair, view.atr_5m, view.session, view.spread_pips)
            except Exception as exc:
                msg = f"{pair}: {exc}"
                self._errors.append(msg)
                log.warning("feed error %s", msg)

        if self._errors:
            log.warning("feed: %d/%d pairs failed: %s",
                        len(self._errors), len(pairs), "; ".join(self._errors))
        return views

    @property
    def last_errors(self) -> list[str]:
        return list(self._errors)
