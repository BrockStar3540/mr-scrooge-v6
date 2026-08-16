"""modules/signals/base.py — Data structures for the V5 signal pipeline."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class MarketView:
    """Snapshot of one pair at one M5 bar — raw feed values.

    Fields that have = 0.0 defaults are wired in the module design but not yet
    populated by the feed; they contribute zero until the feed is implemented.
    """
    pair:          str
    session:       str
    timestamp:     datetime

    # ── H1 timeframe: momentum & structure ──────────────────────────────────
    h1_ret_1bar:   float           # last completed H1 bar return, pips  [+17.6p dir span]
    h1_ret_4bar:   float           # sum of last 4 H1 bar returns, pips  [+7.4p]
    rsi14:         float           # H1 RSI-14 level (0..100)            [+4.8p]
    rsi_slope:     float           # H1 RSI 2-bar delta                  [+10.4p]
    zscore_1h:     float           # H1 Z-score vs 20-bar SMA            [+8.7p]
    ema20_1h_dist: float           # H1 EMA20 distance, frac of price    [+6.4p]
    htf_pct_20:    float = 0.0     # H20 higher-TF percent signal        [+1.9p]
    htf_pct_60:    float = 0.0     # H60 higher-TF percent signal        [+1.0p]

    # ── Distance-to-level signals ────────────────────────────────────────────
    pdh_dist:          float = 0.0  # current price - prev-day high, pips   [+6.0p]
    pdl_dist:          float = 0.0  # current price - prev-day low, pips    [+5.9p]
    pdh_dist_atr_pct:  float = 0.0  # pdh_dist normalized by ATR            [+5.6p]
    pdl_dist_atr_pct:  float = 0.0  # pdl_dist normalized by ATR            [+5.7p]
    # Previous-SESSION structure (2026-07-10, Brock: floor/ceiling consciousness)
    ps_high_dist:      float = 0.0  # mid - prev session HIGH, pips (>0 = broke ceiling)
    ps_low_dist:       float = 0.0  # mid - prev session LOW, pips (<0 = broke floor)
    ps_pos:            float = 0.5  # position of mid within prev session range [0..1]

    # ── Daily context ─────────────────────────────────────────────────────────
    d_ret:          float = 0.0     # today's running daily return, pips     [+7.1p]
    close_pos_daily: float = 0.0    # close position in daily range (0..1)   [-0.3p]
    adr_consumed:   float = 0.0     # fraction of avg daily range used (0..1) [in momentum]

    # ── Mean-reversion signals (5m timeframe) ────────────────────────────────
    bb_pos:         float = 0.0     # Bollinger Band position (0=low, 1=high)  [-0.55p]
    bb_width:       float = 0.0     # Bollinger Band width, pips (in momentum) [+0.12p]
    zscore_5m:      float = 0.0     # 5m Z-score vs 20-bar SMA                [-0.55p]
    # external-strategy trial features (2026-07-31: TradeClaw/EuroScope shadows)
    vwap_dist_pips: float = 0.0     # mid − session-anchored VWAP, pips
    adx14:          float = 0.0     # H1 ADX-14 (trend-strength regime gate)
    ema20_dist_pct: float = 0.0     # 5m EMA20 distance, frac of price        [-0.57p]
    ema5_dist_pips: float = 0.0     # 5m EMA5 distance, pips                  [-0.53p]
    ema50_dist_pct: float = 0.0     # 5m EMA50 distance, frac of price        [-0.39p]
    ema_cross_pips: float = 0.0     # EMA cross signal, pips                  [-0.27p]
    ret_5m:         float = 0.0     # last 5m bar return, pips                [-0.50p]
    ret_15m:        float = 0.0     # last 15m lagged return, pips            [-0.45p]
    ret_30m:        float = 0.0     # last 30m lagged return, pips            [-0.41p]
    ret_1h:         float = 0.0     # last 1h lagged return, pips             [-0.44p]

    # ── Volatility / magnitude ────────────────────────────────────────────────
    atr_5m:         float = 0.0     # 5-min ATR, pips
    atr_1h:         float = 0.0     # 1H ATR, pips
    atr_d_pips:     float = 0.0     # daily ATR, pips
    rvol_5bar:      float = 1.0     # relative volume vs 5-bar mean (1.0=normal)
    rvol_12bar:     float = 1.0     # relative volume vs 12-bar mean
    range_5bar:     float = 0.0     # high-low range over last 5 bars, pips
    range_12bar:    float = 0.0     # high-low range over last 12 bars, pips
    d_range_pips:   float = 0.0     # today's high-low range, pips
    atr_conc:       float = 0.0     # ATR concentration ratio
    atr_h1_relative: float = 1.0    # current 1H ATR / its rolling-mean (1.0=normal; v2/v3 aggregator: >1.6 = elevated)
    vortex_diff_h1: float = 0.0     # Vortex VI+ minus VI- on H1 — directional signal (Master Matrix 2026-06-21; shadow only until 2026-07-04)
    trend_4h:       float = 0.0     # sign of last-4 H1 bars net return (+1 up, 0 flat, -1 down)
    # ── 2026-06-23 matrix features (SHADOW logging only, no scoring effect) ──
    # Per Master Matrix 2026-06-21 + per-session analysis 2026-06-23.
    # CYCLE log emits per pair per cycle for backtest of alternative rankers.
    willr_m5:        float = 0.0    # Williams %R on M5, period 14 (range -100..0; top-3 in 24/24 cells)
    aroonosc_h1:     float = 0.0    # Aroon Oscillator on H1, period 14 (range -100..+100; asia+NY top-3)
    kc_up_dist_pips: float = 0.0    # Distance close→upper Keltner band, M5 period 20 (pips signed; +=close above)
    efi:             float = 0.0    # Elder Force Index on M5, period 13 (asia+london top binary rule, 22/32 cells)

    # ── Market structure (2026-08-06 trial features) ─────────────────────────
    # PRICE-structure only: FX tick "volume" is not size, so none of these
    # claim to read participation. Combine with rvol_* if volume gating is
    # wanted. NO_LEVEL_PIPS (500.0) = "no qualifying structure in range".
    liq_sweep_high:    float = 0.0    # pips a rejected sweep pierced an equal-HIGH pool
    liq_sweep_low:     float = 0.0    # pips a rejected sweep pierced an equal-LOW pool
    ob_bull_dist_pips: float = 500.0  # mid − top of nearest UNMITIGATED demand zone
    ob_bear_dist_pips: float = 500.0  # bottom of nearest UNMITIGATED supply zone − mid
    ema_trend_pips:    float = 0.0    # EMA14−EMA40 on M5 (~70min vs ~200min), pips

    # ── Session opening range (v6.28.0 trial features) ───────────────────────
    # First 15 min of the CURRENT coarse session. orb_range_pips is 0.0 while
    # the range is forming, so a `min` gate on it fail-closes every ORB setup.
    orb_hi_dist:    float = 0.0     # mid − ORB high, pips
    orb_lo_dist:    float = 0.0     # mid − ORB low, pips
    orb_pos:        float = 0.5     # position within ORB (0=low, 1=high, unclamped)
    orb_range_pips: float = 0.0     # ORB height, pips; 0.0 = forming/absent

    # ── Execution ────────────────────────────────────────────────────────────
    bid:            float = 0.0
    ask:            float = 0.0
    spread_pips:    float = 0.0

    # ── v2/v3 module field-name aliases (read-only) ─────────────────────
    @property
    def pdh_dist_pips(self) -> float: return self.pdh_dist
    @property
    def pdl_dist_pips(self) -> float: return self.pdl_dist
    @property
    def ema20_1h_dist_pct(self) -> float: return self.ema20_1h_dist


@dataclass
class DirectionStamp:
    """Translation of raw direction indicators for one pair/session bar."""
    pair:      str
    session:   str
    timestamp: datetime
    bias:      str     # "long" | "short" | "block"
    score:     float   # -1.0 (strong short) .. +1.0 (strong long), weighted composite
    certainty: float   # 0.0..1.0 — factor agreement × factor extremity
    reads:     dict    # per-factor translation + agreement summary


@dataclass
class MomentumStamp:
    """Translation of raw volatility / magnitude indicators for one pair/session bar."""
    pair:          str
    session:       str
    timestamp:     datetime
    vol_regime:    str     # "low" | "normal" | "high" | "extreme"
    expected_pips: float   # calibrated 1-hour expected move estimate in pips
    certainty:     float   # 0.0..1.0 — how definitively in a regime
    reads:         dict    # per-factor translation


@dataclass
class PairTicket:
    """Direction + momentum stamps combined — what the playmaker consumes."""
    pair:      str
    session:   str
    timestamp: datetime
    direction:   DirectionStamp
    momentum:    MomentumStamp
    spread_pips: float = 0.0      # live spread at stamp time — playmaker spread gate
    # 2026-06-23: raw view features piped through for per-cell gates in playmaker
    # (e.g. per_cell_willr_range, per_cell_close_pos_range).
    willr_m5:        float = 0.0
    close_pos_daily: float = 0.0
    vortex_diff_h1:  float = 0.0
    kc_up_dist_pips: float = 0.0

    @property
    def composite_score(self) -> float:
        return self.direction.score * self.direction.certainty * self.momentum.certainty

    @property
    def is_actionable(self) -> bool:
        # dir certainty > 0.10: bootstrap sanity floor only — eliminates pure-noise
        # signals before playmaker. Real floors live in playmaker config (global
        # min_dir_certainty=0.30 + per-pair overrides). This was 0.25 which was
        # redundant with playmaker floors and created a boundary conflict for
        # USD_CAD whose per-pair floor is exactly 0.25 (equality excluded it).
        # Lowered to 0.10 (2026-07-03). Note: act=T counts in CYCLE logs will
        # rise cosmetically — playmaker floors remain the effective gate.
        return (
            self.direction.bias != "block"
            and self.direction.certainty > 0.10
            and self.momentum.vol_regime != "extreme"
        )
