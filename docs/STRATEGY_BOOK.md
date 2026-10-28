# The Strategy Book

*Every strategy Mr. Scrooge V6 has put on trial: what it trades, which indicators it reads, what the backtesting said, and how it did with real money. Generated 2026-10-28 by [`research/tools/strategy_book.py`](../research/tools/strategy_book.py); rebuild it rather than editing it.*

**1,715 setups in 40 families**, across 18 pairs and 3 sessions (Asia, London, New York). Right now 14 are ACTIVE, 3 are PROBE, 1,621 are SHADOW and 77 are retired. 167 setups have held a live seat at some point. Since the live cutover on 2026-07-29 the account closed 1,040 trades attributed to a setup: -1,907 pips, $-1,290.52 realized.

## How to read this book

- **A setup** is one family's rules on one pair, session and side. Each family is a single idea, so it has dozens of setups: long and short, a *counter* twin that takes the opposite side, `_t20s` trials with a wider ratchet, and `_g_*` variants with an extra gate.
- **SHADOW** setups trade on paper: every time one fires, the bot stamps a simulated trade. **PROBE** setups trade real money at 0.20× size. **ACTIVE** setups trade full size. How a setup moves between them is in the [README](../README.md#how-a-setup-keeps-its-seat).
- **What the backtesting said** is the evidence each family was built on, quoted from the setup files. Many of those numbers came before fixes we found later (an H1 look-ahead bug fixed 2026-07-03, and simulator costs), so treat them as the reason a family was tried, not proof it worked.
- **Simulator** is the shadow forward test: completed family cycles stamped live and scored on the current exit. Its per-setup correlation with real fills was 0.07, so it is a weak guide.
- **Real money** is every live trade the family opened, parents and the poppers their grids fired, from the broker's own fills. Pips include the spread. Dollars depend on position size, which changed over the record; pips compare.

## The short version

| Family | What it does | Reads | Setups now (A / P / S / retired) | Simulator | Real money |
|---|---|---|---|---|---|
| [echo_box_fade](#echo_box_fade) | Fades a Bollinger Band tag | `bb_pos`, `ret_5m`, `bb_width` | 1 / 0 / 280 / 8 | 3127 cyc, 86%, +0.5p | 131 trades, -3p, 80% won |
| [orb_break](#orb_break) | Opening-range breakout | `orb_range_pips`, `orb_hi_dist`, `orb_lo_dist` | 2 / 1 / 31 / 0 | 369 cyc, 90%, +4.9p | 95 trades, +246p, 85% won |
| [timing_lean_30](#timing_lean_30) | Volatility timing | `atr_5m`, `atr_h1_relative`, `rvol_5bar` | 0 / 0 / 19 / 4 | 255 cyc, 84%, +2.2p | 90 trades, -992p, 67% won |
| [rg1_range_scalp](#rg1_range_scalp) | Range scalp at the band edge | `bb_pos`, `rsi14`, `ret_5m` | 2 / 1 / 194 / 9 | 1953 cyc, 85%, -3.1p | 85 trades, +144p, 85% won |
| [control_atr5m_60](#control_atr5m_60) | A control formula | `atr_5m` | 2 / 0 / 1 / 0 | 34 cyc, 82%, -2.5p | 76 trades, +300p, 91% won |
| [mr2_bb_reversion](#mr2_bb_reversion) | Mean reversion from a stretch | `zscore_5m`, `bb_pos`, `rsi14` | 0 / 0 / 224 / 4 | 2399 cyc, 86%, -2.1p | 66 trades, -421p, 64% won |
| [ps_floor_fade](#ps_floor_fade) | Buys the previous session's low | `ps_pos`, `ps_low_dist` | 2 / 0 / 104 / 2 | 1216 cyc, 78%, -0.8p | 65 trades, +67p, 83% won |
| [ps_ceil_fade](#ps_ceil_fade) | Fades the previous session's high | `ps_pos`, `ps_high_dist` | 0 / 0 / 144 / 2 | 1625 cyc, 81%, -1.5p | 61 trades, -187p, 75% won |
| [fvg_fill](#fvg_fill) | First revisit of an untouched fair-value gap, with the H1 trend | `ema20_1h_dist`, `fvg_bull_dist_pips`, `fvg_bear_dist_pips` | 0 / 0 / 60 / 1 | 613 cyc, 92%, +7.7p | 54 trades, -367p, 74% won |
| [impulse_ob](#impulse_ob) | Order-block continuation | `ema_trend_pips`, `ob_bear_dist_pips`, `ob_bull_dist_pips` | 0 / 0 / 31 / 0 | 286 cyc, 90%, +2.4p | 40 trades, -336p, 70% won |
| [liq_sweep_fade](#liq_sweep_fade) | Liquidity-sweep reversal | `liq_sweep_low`, `liq_sweep_high`, `rvol_5bar` | 0 / 0 / 38 / 1 | 394 cyc, 86%, -0.8p | 31 trades, +60p, 84% won |
| [control_rvol_60](#control_rvol_60) | A control formula | `rvol_5bar` | 1 / 0 / 4 / 0 | 49 cyc, 92%, -3.5p | 31 trades, +18p, 84% won |
| [es_trend](#es_trend) | Trend-regime entry | `adx14`, `trend_4h`, `ema20_dist_pct` | 0 / 0 / 10 / 0 | 97 cyc, 89%, +4.9p | 29 trades, -8p, 79% won |
| [classic_willr_fade](#classic_willr_fade) | Sells a Williams %R extreme | `willr_m5`, `ret_5m` | 1 / 0 / 0 / 0 | 9 cyc, 100%, +7.7p | 29 trades, +216p, 93% won |
| [shark_fade_mid](#shark_fade_mid) | Fades a prior-session extreme, but only on a normal-volatility day | `atr_h1_relative`, `adr_consumed`, `ps_pos` | 0 / 0 / 75 / 0 | 845 cyc, 86%, -0.1p | 28 trades, -76p, 79% won |
| [orb_fade](#orb_fade) | Fades back into the session's 15-minute opening range | `orb_pos`, `orb_range_pips` | 0 / 0 / 57 / 0 | 585 cyc, 87%, +1.8p | 26 trades, -35p, 81% won |
| [control_atrconc_60](#control_atrconc_60) | A control formula | `atr_conc` | 0 / 0 / 4 / 1 | 47 cyc, 96%, +12.2p | 19 trades, -135p, 63% won |
| [trend_pullback](#trend_pullback) | Buy the dip in an uptrend | `trend_4h`, `h1_ret_4bar`, `willr_m5` | 0 / 0 / 34 / 7 | 463 cyc, 85%, -3.9p | 15 trades, -364p, 47% won |
| [ps_floor_break](#ps_floor_break) | Session box break | `ps_low_dist` | 0 / 0 / 2 / 0 | 24 cyc, 96%, +5.7p | 15 trades, +17p, 87% won |
| [classic_extension_fade](#classic_extension_fade) | Buys an over-extension | `willr_m5`, `ema20_dist_pct` | 0 / 0 / 2 / 0 | 19 cyc, 100%, +14.6p | 10 trades, +42p, 70% won |
| [classic_box_break](#classic_box_break) | The box fade's opposite-direction twin from the flip era | `bb_pos` | 0 / 0 / 2 / 0 | 23 cyc, 100%, +12.7p | 10 trades, +9p, 90% won |
| [alpha_extended_fade](#alpha_extended_fade) | Buys a sharp oversold dip in an uptrend | `rsi14`, `ema20_1h_dist`, `ret_5m` | 1 / 0 / 28 / 12 | 403 cyc, 88%, +1.2p | 9 trades, -2p, 89% won |
| [shark_adr_late](#shark_adr_late) | Late-day continuation | `adr_consumed`, `d_ret`, `atr_h1_relative` | 0 / 0 / 23 / 0 | 261 cyc, 85%, -1.0p | 6 trades, -73p, 67% won |
| [es_breakout](#es_breakout) | Breakout above the previous day's high with ADX 20+ and RSI 50+ | `pdh_dist`, `adx14`, `rsi14` | 0 / 0 / 8 / 1 | 97 cyc, 82%, -9.3p | 6 trades, +30p, 83% won |
| [classic_box_fade](#classic_box_fade) | The original box fade | `bb_pos` | 1 / 0 / 1 / 0 | 20 cyc, 90%, -4.2p | 6 trades, -62p, 50% won |
| [ninja_flag](#ninja_flag) | Bull/bear flag | `ema_trend_pips`, `ema20_1h_dist`, `ret_1h` | 0 / 0 / 46 / 0 | 512 cyc, 85%, -1.8p | 4 trades, -1p, 75% won |
| [kc_up](#kc_up) | Leans long 4.6–15 pips under the upper Keltner Channel, with normal-or-better volume and a soft 60-day trend | `kc_up_dist_pips`, `rvol_5bar`, `htf_pct_60` | 1 / 0 / 3 / 0 | 39 cyc, 95%, +11.6p | 3 trades, +4p, 67% won |
| [shark_momo_run](#shark_momo_run) | Momentum on a hot day | `atr_h1_relative`, `adr_consumed`, `trend_4h` | 0 / 1 / 43 / 0 | 381 cyc, 81%, -8.7p | never traded |
| [ninja_stab_fade](#ninja_stab_fade) | Fades back off the prior-session low in a calm, choppy market | `atr_h1_relative`, `efficiency_10`, `ps_low_dist` | 0 / 0 / 40 / 0 | 368 cyc, 88%, +4.7p | never traded |
| [ninja_amp_break](#ninja_amp_break) | Breakout in a high-volatility regime | `atr_h1_relative`, `ema_trend_pips`, `ps_high_dist` | 0 / 0 / 38 / 0 | 166 cyc, 77%, -10.0p | never traded |
| [ninja_stack_break](#ninja_stack_break) | Breakout from compression | `ema_trend_pips`, `ema20_1h_dist`, `atr_h1_relative` | 0 / 0 / 37 / 0 | 216 cyc, 81%, -11.7p | never traded |
| [tc_vwapbb](#tc_vwapbb) | Trend pullback to the lower Bollinger Band while price holds above the session VWAP and the H1 EMA20 | `bb_pos`, `vwap_dist_pips`, `ema20_1h_dist` | 0 / 0 / 10 / 16 | 249 cyc, 85%, -4.8p | never traded |
| [pwh_fade](#pwh_fade) | Fades the previous week's high | `pwh_dist`, `rsi14` | 0 / 0 / 8 / 0 | 56 cyc, 89%, -8.3p | never traded |
| [pwl_fade](#pwl_fade) | Buys the previous week's low | `pwl_dist`, `rsi14` | 0 / 0 / 6 / 0 | 37 cyc, 84%, -0.5p | never traded |
| [box_pdl](#box_pdl) | Previous-day-low break | `pdl_dist` | 0 / 0 / 3 / 3 | 68 cyc, 94%, +10.6p | never traded |
| [es_meanrev](#es_meanrev) | Range-regime fade | `adx14`, `rsi14`, `bb_pos` | 0 / 0 / 2 / 4 | 13 cyc, 92%, +9.9p | never traded |
| [regime_short_240](#regime_short_240) | Short in quiet M5 volatility near the Keltner top while the 60-day trend is falling | `atr_5m`, `kc_up_dist_pips`, `willr_m5` | 0 / 0 / 2 / 1 | 35 cyc, 80%, +5.9p | never traded |
| [rvol_low_240](#rvol_low_240) | Long when relative volume is in its bottom quarter | `rvol_5bar`, `pdl_dist` | 0 / 0 / 3 / 0 | 28 cyc, 75%, -31.9p | never traded |
| [kc_breakout](#kc_breakout) | Long on a push above the upper Keltner Channel in calm H1 volatility, well above yesterday's low | `kc_up_dist_pips`, `atr_h1_relative`, `pdl_dist` | 0 / 0 / 2 / 1 | 35 cyc, 89%, +12.8p | never traded |
| [willr_recovery](#willr_recovery) | Short when Williams %R recovers above −50 in calm M5 volatility | `willr_m5`, `atr_5m` | 0 / 0 / 2 / 0 | 16 cyc, 94%, -4.9p | never traded |

## What it all says

- **Nothing yet beats the spread.** Across the live record, OANDA's own half-spread charges came to about three quarters of the realized loss. Families win often (most real-money families won 70–90% of trades) but their wins are small and their losses are large, so the win rate does not pay.
- **The indicators find distance, not direction.** The V1–V4 research found entry features predicted when and how far price would move, never which way (0 of 144 feature × cell combinations carried direction). The families here are different ways of asking the same question, and the real-money column is the answer so far.
- **Paper and real money disagree.** Families that looked best in the simulator were often not the ones that made money, which is why seats are now judged only on broker fills. For example: `control_atrconc_60` +12.2 pips a cycle in the simulator, -135 pips over 19 real trades; `fvg_fill` +7.7 pips a cycle in the simulator, -367 pips over 54 real trades; `es_trend` +4.9 pips a cycle in the simulator, -8 pips over 29 real trades.
- **The controls are the warning label.** `control_atr5m_60` was built as a control that history said should lose, and it holds one of the best real-money records in the book. A handful of trades can make any idea look good.

## The indicators

Every setup is a few conditions on these features, computed from OANDA M5, H1 and daily candles at each 5-minute bar ([`core/feed/oanda.py`](../core/feed/oanda.py), [`core/feed/structure.py`](../core/feed/structure.py)).

**Bollinger Bands (M5, 20)**

- `bb_pos`: where price sits inside the band: 0 = lower band, 1 = upper band
- `bb_width`: band width in pips (how wide the recent range is)
- `zscore_5m`: standard deviations from the 20-bar mean

**Momentum and oscillators**

- `rsi14`: RSI, 14 bars
- `willr_m5`: Williams %R on M5, 14 bars: −100 = oversold, 0 = overbought
- `adx14`: ADX, 14 bars: trend strength regardless of direction
- `ret_5m`: the last M5 bar's move in pips (positive = up bar)
- `ret_1h`: the last hour's move in pips
- `h1_ret_4bar`: net move over the last 4 H1 bars, in pips
- `d_ret`: move since today's open, in pips

**Trend**

- `ema_trend_pips`: fast EMA minus slow EMA on M5, in pips: sign = trend, size = separation
- `trend_4h`: +1 if the last 4 hours went up, −1 if down
- `ema20_1h_dist`: distance from the H1 EMA20, as a fraction of price
- `ema20_dist_pct`: distance from the M5 EMA20, as a fraction of price
- `htf_pct_60`: 60-day return
- `efficiency_10`: Kaufman efficiency over 10 bars: 1 = straight line, near 0 = chop

**Volatility and volume**

- `atr_5m`: ATR on M5, pips
- `atr_1h`: ATR on H1, pips
- `atr_h1_relative`: H1 ATR against its own recent average (1.0 = normal)
- `atr_conc`: M5 ATR ÷ H1 ATR
- `adr_consumed`: today's range ÷ the average daily range (1.0 = a full day's move)
- `rvol_5bar`: last 5 bars' tick volume ÷ the prior 20 bars'
- `spread_pips`: the live spread

**Session and day levels**

- `ps_pos`: where price sits in the previous session's range: 0 = its low, 1 = its high
- `ps_high_dist / ps_low_dist`: pips from the previous session's high / low
- `orb_pos, orb_hi_dist, orb_lo_dist, orb_range_pips`: the session's opening range (first 15 minutes): position, distance from its high/low, its size
- `pdh_dist / pdl_dist`: pips from the previous day's high / low
- `pwh_dist / pwl_dist`: pips from the previous week's high / low
- `vwap_dist_pips`: pips from the session VWAP
- `kc_up_dist_pips`: pips from the upper Keltner Channel (M5, 20, 2×ATR)

**Market structure**

- `fvg_bull_dist_pips / fvg_bear_dist_pips`: pips from the nearest untouched fair-value gap (three-candle imbalance)
- `ob_bull_dist_pips / ob_bear_dist_pips`: pips from the origin of the nearest unmitigated impulse move (an 'order block')
- `liq_sweep_low / liq_sweep_high`: how far price pierced a pool of stops below equal lows / above equal highs, then came back

## The families

### echo_box_fade

Fades a Bollinger Band tag. Long when an M5 bar closes at or below the lower band and the next bar turns up; short at the upper band. Brock's Strategy Book 'echo box' setup, replayed.

- **Rules, `echo_box_fade_long`:** `bb_pos` ≤ 0.03; `ret_5m` ≥ 0. Holds up to 240 minutes in the simulator.
- **Rules, `echo_box_fade_short`:** `bb_pos` ≥ 0.87; `ret_5m` ≤ 0.
- **Where it trades:** 289 setups on 18 pairs (AUD_CAD, AUD_CHF, AUD_JPY, AUD_USD, CAD_JPY, CHF_JPY, EUR_CAD, EUR_CHF, …), sessions: asia, london, ny.
- **Status now:** 1 ACTIVE, 0 PROBE, 280 SHADOW, 8 retired. 23 of its setups have held a live seat.
- **What the backtesting said:**
  - regime-map gap fill 2026-08-07 (operator): matrix of 5 fade families x 18 pairs x 3 sessions showed 125/675 wired; operator ordered the full fill as zero-authority shadows — the counting clocks decide. Neighborhood priors on the map artifact; hypothesis, not validation.
  - DIAL slate 2026-08-25: dial-in farm (4,250 eps w/ stamped gate values) + struck-cell autopsy (359 eps, reconstructed features). Sub-range structure was material and consistent; bands widened from raw terciles to blunt overfit. Zero prior authority; parents' strike records untouched.
- **Simulator:** 3127 completed cycles, 86% won, +0.5 pips per cycle.
- **Real money:** 131 trades (53 of them poppers), -3.2 pips (-0.02 per trade), 80% won, $-32.39.

### orb_break

Opening-range breakout: a fresh close 1–10 pips beyond the session's 15-minute opening range (range 5–40 pips).

- **Rules, `orb_break_long`:** `orb_hi_dist` 1 to 10; `orb_range_pips` 5 to 40. Holds up to 240 minutes in the simulator.
- **Rules, `orb_break_short`:** `orb_lo_dist` -10 to -1; `orb_range_pips` 5 to 40.
- **Where it trades:** 34 setups on 6 pairs (AUD_USD, EUR_USD, GBP_USD, USD_CAD, USD_CHF, USD_JPY), sessions: london, ny.
- **Status now:** 2 ACTIVE, 1 PROBE, 31 SHADOW, 0 retired. 8 of its setups have held a live seat.
- **What the backtesting said:**
  - Máximo NQ/MNQ 1-Minute Scalping Toolkit (open-source TradingView, pub 2026-08-13) — session ORB was the one concept the feed lacked; translated 2026-08-15 (v6.28.0). FX caveat: session opens are softer than NQ's cash open, prior deliberately weak — zero-authority trial, standard bar. Asia gets fades only (soft open + revert session); london/ny get breaks + fades.
  - MAE-flip counterpart audit 2026-07-27: orb_break_short (short) ran 5 eps @ -22.1p/ep with medMFE/MAE 3.1/13.5 — mirror is hypothesis, not validation
- **Simulator:** 369 completed cycles, 90% won, +4.9 pips per cycle.
- **Real money:** 95 trades (22 of them poppers), +246.0 pips (+2.59 per trade), 85% won, $+129.13.

### timing_lean_30

Volatility timing: enters when M5 ATR is in its top quarter for that cell, leaning the cell's historical direction, and holds about 30 minutes.

- **Rules, `timing_lean_30`:** `atr_5m` ≥ 6.61799. Holds up to 30 minutes in the simulator.
- **Rules, `timing_lean_30_short`:** `atr_5m` 5.91 to 8.13.
- **Where it trades:** 23 setups on 4 pairs (AUD_JPY, EUR_JPY, GBP_USD, USD_JPY), sessions: asia, london, ny.
- **Status now:** 0 ACTIVE, 0 PROBE, 19 SHADOW, 4 retired. 9 of its setups have held a live seat.
- **What the backtesting said:**
  - range-harvest-2026-07-04/top5_per_cell_per_horizon.csv h=30 atr_5m; cell-calibration-2026-07/direction_lean
  - DIAL slate 2026-08-25: dial-in farm (4,250 eps w/ stamped gate values) + struck-cell autopsy (359 eps, reconstructed features). Sub-range structure was material and consistent; bands widened from raw terciles to blunt overfit. Zero prior authority; parents' strike records untouched.
- **Simulator:** 255 completed cycles, 84% won, +2.2 pips per cycle.
- **Real money:** 90 trades (59 of them poppers), -992.0 pips (-11.02 per trade), 67% won, $-445.75.

### rg1_range_scalp

Range scalp at the band edge. Short near the top of the M5 band with RSI 62–80 and a down bar; long at the bottom. Variants add band-width and efficiency filters so it only trades quiet ranges.

- **Rules, `rg1_range_scalp_short`:** `bb_pos` ≥ 0.78; `rsi14` 62 to 80; `ret_5m` ≤ 0. Holds up to 240 minutes in the simulator.
- **Where it trades:** 206 setups on 18 pairs (AUD_CAD, AUD_CHF, AUD_JPY, AUD_USD, CAD_JPY, CHF_JPY, EUR_CAD, EUR_CHF, …), sessions: asia, london, ny.
- **Status now:** 2 ACTIVE, 1 PROBE, 194 SHADOW, 9 retired. 12 of its setups have held a live seat.
- **What the backtesting said:**
  - regime-map gap fill 2026-08-07 (operator): matrix of 5 fade families x 18 pairs x 3 sessions showed 125/675 wired; operator ordered the full fill as zero-authority shadows — the counting clocks decide. Neighborhood priors on the map artifact; hypothesis, not validation.
  - DIAL slate 2026-08-25: dial-in farm (4,250 eps w/ stamped gate values) + struck-cell autopsy (359 eps, reconstructed features). Sub-range structure was material and consistent; bands widened from raw terciles to blunt overfit. Zero prior authority; parents' strike records untouched.
- **Simulator:** 1953 completed cycles, 85% won, -3.1 pips per cycle.
- **Real money:** 85 trades (32 of them poppers), +144.2 pips (+1.70 per trade), 85% won, $+59.42.

### control_atr5m_60

A control formula: one M5 ATR band and the cell's side, held about an hour. History said it should lose; it stamps to test that.

- **Rules, `control_atr5m_60`:** `atr_5m` 2.70344 to 6.33182. Holds up to 60 minutes in the simulator.
- **Where it trades:** 3 setups on 1 pairs (USD_JPY), sessions: ny.
- **Status now:** 2 ACTIVE, 0 PROBE, 1 SHADOW, 0 retired. 3 of its setups have held a live seat.
- **What the backtesting said:**
  - formula-history-2026-07-04/verdict_table.csv
  - MAE-flip counterpart audit 2026-07-27: control_atr5m_60 (long) ran 31 eps @ -1.34p/ep with medMFE/MAE 3.7/5.7 — mirror is hypothesis, not validation
- **Simulator:** 34 completed cycles, 82% won, -2.5 pips per cycle.
- **Real money:** 76 trades (27 of them poppers), +299.9 pips (+3.95 per trade), 91% won, $+73.35.

### mr2_bb_reversion

Mean reversion from a stretch. Short when price is 1.2+ standard deviations above its M5 mean, in the top fifth of the band, RSI 58+, and the last bar turned down; the mirror for longs.

- **Rules, `mr2_bb_reversion_short`:** `zscore_5m` ≥ 1.2; `bb_pos` ≥ 0.78; `rsi14` ≥ 58; `ret_5m` ≤ 0. Holds up to 240 minutes in the simulator.
- **Where it trades:** 228 setups on 18 pairs (AUD_CAD, AUD_CHF, AUD_JPY, AUD_USD, CAD_JPY, CHF_JPY, EUR_CAD, EUR_CHF, …), sessions: asia, london, ny.
- **Status now:** 0 ACTIVE, 0 PROBE, 224 SHADOW, 4 retired. 17 of its setups have held a live seat.
- **What the backtesting said:**
  - regime-map gap fill 2026-08-07 (operator): matrix of 5 fade families x 18 pairs x 3 sessions showed 125/675 wired; operator ordered the full fill as zero-authority shadows — the counting clocks decide. Neighborhood priors on the map artifact; hypothesis, not validation.
  - DIAL slate 2026-08-25: dial-in farm (4,250 eps w/ stamped gate values) + struck-cell autopsy (359 eps, reconstructed features). Sub-range structure was material and consistent; bands widened from raw terciles to blunt overfit. Zero prior authority; parents' strike records untouched.
- **Simulator:** 2399 completed cycles, 86% won, -2.1 pips per cycle.
- **Real money:** 66 trades (44 of them poppers), -421.1 pips (-6.38 per trade), 64% won, $-233.69.

### ps_floor_fade

Buys the previous session's low: long in the bottom 15% of the prior session's range while that low holds.

- **Rules, `ps_floor_fade_long`:** `ps_pos` ≤ 0.15; `ps_low_dist` ≥ 0. Holds up to 240 minutes in the simulator.
- **Where it trades:** 108 setups on 18 pairs (AUD_CAD, AUD_CHF, AUD_JPY, AUD_USD, CAD_JPY, CHF_JPY, EUR_CAD, EUR_CHF, …), sessions: asia, london, ny.
- **Status now:** 2 ACTIVE, 0 PROBE, 104 SHADOW, 2 retired. 8 of its setups have held a live seat.
- **What the backtesting said:**
  - regime-map gap fill 2026-08-07 (operator): matrix of 5 fade families x 18 pairs x 3 sessions showed 125/675 wired; operator ordered the full fill as zero-authority shadows — the counting clocks decide. Neighborhood priors on the map artifact; hypothesis, not validation.
  - march-2026 replay (acct txns 209-324): fade/floor/pullback shapes on CAD crosses, 8 green / 1 red fills, descriptive n=9 — hypothesis, not validation
- **Simulator:** 1216 completed cycles, 78% won, -0.8 pips per cycle.
- **Real money:** 65 trades (4 of them poppers), +67.1 pips (+1.03 per trade), 83% won, $+72.67.

### ps_ceil_fade

Fades the previous session's high: short when price is in the top 15% of the prior session's range and has not broken its high.

- **Rules, `ps_ceil_fade_short`:** `ps_pos` ≥ 0.85; `ps_high_dist` ≤ 0. Holds up to 240 minutes in the simulator.
- **Where it trades:** 146 setups on 18 pairs (AUD_CAD, AUD_CHF, AUD_JPY, AUD_USD, CAD_JPY, CHF_JPY, EUR_CAD, EUR_CHF, …), sessions: asia, london, ny.
- **Status now:** 0 ACTIVE, 0 PROBE, 144 SHADOW, 2 retired. 14 of its setups have held a live seat.
- **What the backtesting said:**
  - regime-map gap fill 2026-08-07 (operator): matrix of 5 fade families x 18 pairs x 3 sessions showed 125/675 wired; operator ordered the full fill as zero-authority shadows — the counting clocks decide. Neighborhood priors on the map artifact; hypothesis, not validation.
  - DIAL slate 2026-08-25: dial-in farm (4,250 eps w/ stamped gate values) + struck-cell autopsy (359 eps, reconstructed features). Sub-range structure was material and consistent; bands widened from raw terciles to blunt overfit. Zero prior authority; parents' strike records untouched.
- **Simulator:** 1625 completed cycles, 81% won, -1.5 pips per cycle.
- **Real money:** 61 trades (24 of them poppers), -186.9 pips (-3.06 per trade), 75% won, $-94.30.

### fvg_fill

First revisit of an untouched fair-value gap, with the H1 trend: long at or just above a bullish gap while price is above the H1 EMA20.

- **Rules, `fvg_fill_long`:** `fvg_bull_dist_pips` -2 to 3; `ema20_1h_dist` ≥ 0. Holds up to 240 minutes in the simulator.
- **Rules, `fvg_fill_short`:** `fvg_bear_dist_pips` -2 to 3; `ema20_1h_dist` ≤ 0.
- **Where it trades:** 61 setups on 6 pairs (AUD_USD, EUR_USD, GBP_USD, USD_CAD, USD_CHF, USD_JPY), sessions: london, ny.
- **Status now:** 0 ACTIVE, 0 PROBE, 60 SHADOW, 1 retired. 11 of its setups have held a live seat.
- **What the backtesting said:**
  - Creedbentley Three-Candle S/D + FVGs (MPL-2.0, TradingView) translated 2026-08-16 (v6.29.0): first revisit of an untouched imbalance in H1 trend direction. Completes the SMC trio next to liq_sweep pools and impulse blocks.
  - DIAL slate 2026-08-25: dial-in farm (4,250 eps w/ stamped gate values) + struck-cell autopsy (359 eps, reconstructed features). Sub-range structure was material and consistent; bands widened from raw terciles to blunt overfit. Zero prior authority; parents' strike records untouched.
- **Simulator:** 613 completed cycles, 92% won, +7.7 pips per cycle.
- **Real money:** 54 trades (28 of them poppers), -367.4 pips (-6.80 per trade), 74% won, $-203.19.

### impulse_ob

Order-block continuation: price returns to within 3 pips of the origin of the last unmitigated impulse move, with the M5 trend agreeing.

- **Rules, `impulse_ob_long`:** `ob_bull_dist_pips` -3 to 3; `ema_trend_pips` ≥ 0.5. Holds up to 240 minutes in the simulator.
- **Rules, `impulse_ob_short`:** `ob_bear_dist_pips` -3 to 3; `ema_trend_pips` ≤ -0.5.
- **Where it trades:** 31 setups on 3 pairs (AUD_USD, EUR_USD, GBP_USD), sessions: london, ny.
- **Status now:** 0 ACTIVE, 0 PROBE, 31 SHADOW, 0 retired. 5 of its setups have held a live seat.
- **What the backtesting said:**
  - Independent implementation of public price-structure concepts (equal-high/low stop pools and their sweep; impulse-origin supply/demand zones with mitigation; fast/slow EMA regime). Built from core/feed/structure.py against our own M5 data — no third-party code, terminology or parameters. FX tick volume is not size, so these are PRICE structure only.
  - Paired VARIANT of the 2026-08-06 market-structure trials, wired on the SAME cell/session as its baseline so the comparison is not confounded by pair, session or market period. Independent implementation of public price-structure concepts; no third-party code, terminology or parameters.
- **Simulator:** 286 completed cycles, 90% won, +2.4 pips per cycle.
- **Real money:** 40 trades (24 of them poppers), -336.2 pips (-8.40 per trade), 70% won, $-195.93.

### liq_sweep_fade

Liquidity-sweep reversal: the stops under two or more equal lows get run and price comes back. Buy it; the mirror above equal highs.

- **Rules, `liq_sweep_fade_long`:** `liq_sweep_low` ≥ 1. Holds up to 240 minutes in the simulator.
- **Rules, `liq_sweep_fade_short`:** `liq_sweep_high` ≥ 1.
- **Where it trades:** 39 setups on 3 pairs (EUR_USD, GBP_USD, USD_CHF), sessions: asia, london.
- **Status now:** 0 ACTIVE, 0 PROBE, 38 SHADOW, 1 retired. 3 of its setups have held a live seat.
- **What the backtesting said:**
  - Paired VARIANT of the 2026-08-06 market-structure trials, on the SAME cell as its baseline so pair/session/period cannot confound the comparison. Independent implementation of public price-structure concepts.
  - Independent implementation of public price-structure concepts (equal-high/low stop pools and their sweep; impulse-origin supply/demand zones with mitigation; fast/slow EMA regime). Built from core/feed/structure.py against our own M5 data — no third-party code, terminology or parameters. FX tick volume is not size, so these are PRICE structure only.
- **Simulator:** 394 completed cycles, 86% won, -0.8 pips per cycle.
- **Real money:** 31 trades (6 of them poppers), +60.1 pips (+1.94 per trade), 84% won, $+41.17.

### control_rvol_60

A control formula: one relative-volume band and the cell's side, held about an hour. History said it should lose; it stamps to test that.

- **Rules, `control_rvol_60`:** `rvol_5bar` 0.371479 to 0.669169. Holds up to 60 minutes in the simulator.
- **Where it trades:** 5 setups on 1 pairs (GBP_USD), sessions: ny.
- **Status now:** 1 ACTIVE, 0 PROBE, 4 SHADOW, 0 retired. 3 of its setups have held a live seat.
- **What the backtesting said:**
  - formula-history-2026-07-04/verdict_table.csv
  - MAE-flip counterpart audit 2026-07-27: control_rvol_60 (short) ran 6 eps @ -6.53p/ep with medMFE/MAE 4.0/8.2 — mirror is hypothesis, not validation
- **Simulator:** 49 completed cycles, 92% won, -3.5 pips per cycle.
- **Real money:** 31 trades (22 of them poppers), +18.5 pips (+0.60 per trade), 84% won, $+2.09.

### es_trend

Trend-regime entry: ADX 25+, 4-hour trend up, price above the M5 EMA20 (open-source EuroScope rules).

- **Rules, `es_trend_long`:** `adx14` ≥ 25; `trend_4h` ≥ 0.5; `ema20_dist_pct` ≥ 0. Holds up to 240 minutes in the simulator.
- **Where it trades:** 10 setups on 2 pairs (EUR_USD, GBP_USD), sessions: asia, london, ny.
- **Status now:** 0 ACTIVE, 0 PROBE, 10 SHADOW, 0 retired. 3 of its setups have held a live seat.
- **What the backtesting said:**
  - external-repo trial 2026-07-31: EuroScope regime-routed rules (MIT). No performance evidence in source - zero prior
  - MAE-flip counterpart audit 2026-07-27: es_trend_long (long) ran 12 eps @ -5.5p/ep with medMFE/MAE 4.7/7.5 — mirror is hypothesis, not validation
- **Simulator:** 97 completed cycles, 89% won, +4.9 pips per cycle.
- **Real money:** 29 trades (14 of them poppers), -7.8 pips (-0.27 per trade), 79% won, $+59.44.

### classic_willr_fade

Sells a Williams %R extreme: overbought (−22 or higher) with a down bar.

- **Rules, `classic_willr_fade_short`:** `willr_m5` ≥ -22; `ret_5m` ≤ 0. Holds up to 240 minutes in the simulator.
- **Where it trades:** 1 setups on 1 pairs (USD_JPY), sessions: ny.
- **Status now:** 1 ACTIVE, 0 PROBE, 0 SHADOW, 0 retired. 1 of its setups have held a live seat.
- **What the backtesting said:**
  - classics-retrial 2026-07-09: YTD +2.6, edge +2.4
- **Simulator:** 9 completed cycles, 100% won, +7.7 pips per cycle.
- **Real money:** 29 trades (5 of them poppers), +216.0 pips (+7.45 per trade), 93% won, $+69.62.

### shark_fade_mid

Fades a prior-session extreme, but only on a normal-volatility day (H1 ATR 0.8–1.3× normal) that has already used a quarter of its average range.

- **Rules, `shark_fade_mid_long`:** `atr_h1_relative` 0.8 to 1.3; `adr_consumed` ≥ 0.25; `ps_pos` ≤ 0.1. Holds up to 240 minutes in the simulator.
- **Rules, `shark_fade_mid_short`:** `atr_h1_relative` 0.8 to 1.3; `adr_consumed` ≥ 0.25; `ps_pos` ≥ 0.9.
- **Where it trades:** 75 setups on 8 pairs (AUD_JPY, AUD_USD, EUR_JPY, EUR_USD, GBP_USD, USD_CAD, USD_CHF, USD_JPY), sessions: asia, london, ny.
- **Status now:** 0 ACTIVE, 0 PROBE, 75 SHADOW, 0 retired. 9 of its setups have held a live seat.
- **What the backtesting said:**
  - EATER slate 2026-08-19: churn-map session (P2.1 corpus walk-forward + P3a on 9,114 live episodes). Amplitude is predictable, count is not; dead-vol Q1 drags; fades peak mid-heat, momentum peaks max-heat; adr_consumed>0.9 continuation beat the exhaustion-fade heuristic. Correlational only, overlapping episodes, one era — zero prior, earns via family cycles or dies in shadow.
  - MAE-flip counterpart audit 2026-07-27: shark_fade_mid_long (long) ran 7 eps @ -42.36p/ep with medMFE/MAE 1.0/26.1 — mirror is hypothesis, not validation
- **Simulator:** 845 completed cycles, 86% won, -0.1 pips per cycle.
- **Real money:** 28 trades (1 of them poppers), -75.6 pips (-2.70 per trade), 79% won, $-9.65.

### orb_fade

Fades back into the session's 15-minute opening range: long at or just under its low (range 5–40 pips), short at its high.

- **Rules, `orb_fade_long`:** `orb_pos` -0.5 to 0.05; `orb_range_pips` 5 to 40. Holds up to 240 minutes in the simulator.
- **Rules, `orb_fade_short`:** `orb_pos` 0.95 to 1.5; `orb_range_pips` 5 to 40.
- **Where it trades:** 57 setups on 6 pairs (AUD_USD, EUR_USD, GBP_USD, USD_CAD, USD_CHF, USD_JPY), sessions: asia, london, ny.
- **Status now:** 0 ACTIVE, 0 PROBE, 57 SHADOW, 0 retired. 5 of its setups have held a live seat.
- **What the backtesting said:**
  - Máximo NQ/MNQ 1-Minute Scalping Toolkit (open-source TradingView, pub 2026-08-13) — session ORB was the one concept the feed lacked; translated 2026-08-15 (v6.28.0). FX caveat: session opens are softer than NQ's cash open, prior deliberately weak — zero-authority trial, standard bar. Asia gets fades only (soft open + revert session); london/ny get breaks + fades.
  - MAE-flip counterpart audit 2026-07-27: orb_fade_short (short) ran 6 eps @ -21.83p/ep with medMFE/MAE 4.1/7.6 — mirror is hypothesis, not validation
- **Simulator:** 585 completed cycles, 87% won, +1.8 pips per cycle.
- **Real money:** 26 trades (2 of them poppers), -35.5 pips (-1.37 per trade), 81% won, $-3.65.

### control_atrconc_60

A control formula: one volatility band (M5 ATR ÷ H1 ATR) and the cell's side, held about an hour. History said it should lose; it stamps to test that.

- **Rules, `control_atrconc_60`:** `atr_conc` 0.1776 to 0.241631. Holds up to 60 minutes in the simulator.
- **Where it trades:** 5 setups on 1 pairs (AUD_USD), sessions: ny.
- **Status now:** 0 ACTIVE, 0 PROBE, 4 SHADOW, 1 retired. 1 of its setups have held a live seat.
- **What the backtesting said:**
  - formula-history-2026-07-04/verdict_table.csv
  - MAE-flip counterpart audit 2026-07-27: control_atrconc_60 (short) ran 6 eps @ -1.5p/ep with medMFE/MAE 1.1/2.6 — mirror is hypothesis, not validation
- **Simulator:** 47 completed cycles, 96% won, +12.2 pips per cycle.
- **Real money:** 19 trades (12 of them poppers), -135.2 pips (-7.12 per trade), 63% won, $-220.46.

### trend_pullback

Buy the dip in an uptrend: 4-hour trend up with real H1 momentum (10+ pips over 4 bars) and M5 Williams %R washed out below −85; the mirror for shorts.

- **Rules, `trend_pullback_long`:** `trend_4h` ≥ 0.5; `h1_ret_4bar` ≥ 10; `willr_m5` ≤ -85. Holds up to 240 minutes in the simulator.
- **Rules, `trend_pullback_short`:** `trend_4h` ≤ -0.5; `ema20_1h_dist` -0.0015 to 0; `rsi14` 40 to 60; `ret_5m` ≤ 0.
- **Where it trades:** 41 setups on 11 pairs (AUD_CAD, AUD_CHF, CAD_JPY, CHF_JPY, EUR_CAD, EUR_CHF, EUR_USD, GBP_CAD, …), sessions: london, ny.
- **Status now:** 0 ACTIVE, 0 PROBE, 34 SHADOW, 7 retired. 2 of its setups have held a live seat.
- **What the backtesting said:**
  - march-2026 replay (acct txns 209-324): fade/floor/pullback shapes on CAD crosses, 8 green / 1 red fills, descriptive n=9 — hypothesis, not validation
  - april-2026 replay (acct txns 435-522): ceil-fade won on USD_CHF/AUD_CHF/CHF_JPY/GBP_USD incl. asia-session fades; descriptive n=11 — hypothesis
- **Simulator:** 463 completed cycles, 85% won, -3.9 pips per cycle.
- **Real money:** 15 trades (12 of them poppers), -363.9 pips (-24.26 per trade), 47% won, $-347.79.

### ps_floor_break

Session box break: short once price trades below the previous session's low.

- **Rules, `ps_floor_break_short`:** `ps_low_dist` ≤ 0. Holds up to 240 minutes in the simulator.
- **Where it trades:** 2 setups on 1 pairs (EUR_JPY), sessions: london.
- **Status now:** 0 ACTIVE, 0 PROBE, 2 SHADOW, 0 retired. 1 of its setups have held a live seat.
- **What the backtesting said:**
  - prev-session screen 2026-07-10: +9.71 YTD, Jul +28.4, 14d +24.7 (n=1651)
  - MAE-flip counterpart audit 2026-07-27: ps_floor_break_short (short) ran 18 eps @ -4.34p/ep with medMFE/MAE 9.8/16.0 — mirror is hypothesis, not validation
- **Simulator:** 24 completed cycles, 96% won, +5.7 pips per cycle.
- **Real money:** 15 trades (0 of them poppers), +17.3 pips (+1.15 per trade), 87% won, $-2.28.

### classic_extension_fade

Buys an over-extension: below the M5 EMA20 with Williams %R −65 or lower.

- **Rules, `classic_extension_fade_long`:** `willr_m5` ≤ -65; `ema20_dist_pct` ≤ 0. Holds up to 240 minutes in the simulator.
- **Where it trades:** 2 setups on 1 pairs (AUD_USD), sessions: london.
- **Status now:** 0 ACTIVE, 0 PROBE, 2 SHADOW, 0 retired. 1 of its setups have held a live seat.
- **What the backtesting said:**
  - classics-retrial 2026-07-09: YTD +2.9, edge +2.0
- **Simulator:** 19 completed cycles, 100% won, +14.6 pips per cycle.
- **Real money:** 10 trades (6 of them poppers), +41.7 pips (+4.17 per trade), 70% won, $+9.36.

### classic_box_break

The box fade's opposite-direction twin from the flip era: sell a close at or below the lower band (a breakdown).

- **Rules, `classic_box_break_short`:** `bb_pos` ≤ 0.03. Holds up to 240 minutes in the simulator.
- **Where it trades:** 2 setups on 1 pairs (GBP_USD), sessions: london.
- **Status now:** 0 ACTIVE, 0 PROBE, 2 SHADOW, 0 retired. 1 of its setups have held a live seat.
- **What the backtesting said:**
  - flip-era tape 2026-07-22..27: 12 eps +11.07/ep (aliased); governor owns the seat from here
  - DIAL slate 2026-08-25: dial-in farm (4,250 eps w/ stamped gate values) + struck-cell autopsy (359 eps, reconstructed features). Sub-range structure was material and consistent; bands widened from raw terciles to blunt overfit. Zero prior authority; parents' strike records untouched.
- **Simulator:** 23 completed cycles, 100% won, +12.7 pips per cycle.
- **Real money:** 10 trades (7 of them poppers), +9.4 pips (+0.94 per trade), 90% won, $+9.21.

### alpha_extended_fade

Buys a sharp oversold dip in an uptrend: RSI 35 or lower, below the H1 EMA20, last bar up, 4-hour trend up; the mirror for shorts.

- **Rules, `alpha_extended_fade_long`:** `rsi14` ≤ 35; `ema20_1h_dist` ≤ 0; `ret_5m` ≥ 0; `trend_4h` ≥ 0.5. Holds up to 240 minutes in the simulator.
- **Rules, `alpha_extended_fade_short`:** `rsi14` ≥ 65; `ema20_1h_dist` ≥ 0; `ret_5m` ≤ 0; `trend_4h` ≤ -0.5.
- **Where it trades:** 41 setups on 4 pairs (AUD_USD, EUR_USD, GBP_USD, USD_CAD), sessions: london, ny.
- **Status now:** 1 ACTIVE, 0 PROBE, 28 SHADOW, 12 retired. 4 of its setups have held a live seat.
- **What the backtesting said:**
  - Strategy-Book cube re-adjudication (Brock, 2026-07-27): 8yr align-factor table EVs — alpha_extended_fade align4 +2.7..+4.5 (n~20k), MR2 +1.4, RG1 +1.9, echo +1.1 — ALL pre-H1-leak-fix upper bounds on the retired ladder exit. Entry definitions from the book Strategy Setups sheet, verbatim thresholds. Current-era stamps re-adjudicate under the live ratchet.
  - align-cube slate 2026-07-31 (Brock) — 8yr factor-cube, pre-H1-leak upper bounds; gate bands translated at the cube 10p-stop context | row: alpha_extended_fade_v2 al2 A1_0
- **Simulator:** 403 completed cycles, 88% won, +1.2 pips per cycle.
- **Real money:** 9 trades (0 of them poppers), -1.6 pips (-0.18 per trade), 89% won, $-5.01.

### shark_adr_late

Late-day continuation: the day has used 90–250% of its average range and is 5+ pips from the open. Keep going the day's way.

- **Rules, `shark_adr_late_long`:** `adr_consumed` 0.9 to 2.5; `d_ret` ≥ 5; `atr_h1_relative` ≥ 0.8. Holds up to 240 minutes in the simulator.
- **Rules, `shark_adr_late_short`:** `adr_consumed` 0.9 to 2.5; `d_ret` ≤ -5; `atr_h1_relative` ≥ 0.8.
- **Where it trades:** 23 setups on 8 pairs (AUD_JPY, AUD_USD, EUR_JPY, EUR_USD, GBP_USD, USD_CAD, USD_CHF, USD_JPY), sessions: ny.
- **Status now:** 0 ACTIVE, 0 PROBE, 23 SHADOW, 0 retired. 3 of its setups have held a live seat.
- **What the backtesting said:**
  - EATER slate 2026-08-19: churn-map session (P2.1 corpus walk-forward + P3a on 9,114 live episodes). Amplitude is predictable, count is not; dead-vol Q1 drags; fades peak mid-heat, momentum peaks max-heat; adr_consumed>0.9 continuation beat the exhaustion-fade heuristic. Correlational only, overlapping episodes, one era — zero prior, earns via family cycles or dies in shadow.
  - MAE-flip counterpart audit 2026-07-27: shark_adr_late_long (long) ran 5 eps @ -27.9p/ep with medMFE/MAE 3.2/54.5 — mirror is hypothesis, not validation
- **Simulator:** 261 completed cycles, 85% won, -1.0 pips per cycle.
- **Real money:** 6 trades (0 of them poppers), -73.1 pips (-12.18 per trade), 67% won, $-12.20.

### es_breakout

Breakout above the previous day's high with ADX 20+ and RSI 50+ (EuroScope).

- **Rules, `es_breakout_long`:** `pdh_dist` ≥ 0; `adx14` ≥ 20; `rsi14` ≥ 50. Holds up to 240 minutes in the simulator.
- **Where it trades:** 9 setups on 2 pairs (EUR_USD, GBP_USD), sessions: asia, london, ny.
- **Status now:** 0 ACTIVE, 0 PROBE, 8 SHADOW, 1 retired. 1 of its setups have held a live seat.
- **What the backtesting said:**
  - external-repo trial 2026-07-31: EuroScope regime-routed rules (MIT). No performance evidence in source - zero prior
  - MAE-flip counterpart audit 2026-07-27: es_breakout_long (long) ran 6 eps @ -11.17p/ep with medMFE/MAE 7.1/11.6 — mirror is hypothesis, not validation
- **Simulator:** 97 completed cycles, 82% won, -9.3 pips per cycle.
- **Real money:** 6 trades (2 of them poppers), +30.1 pips (+5.02 per trade), 83% won, $+3.45.

### classic_box_fade

The original box fade: buy a close at or below the lower Bollinger Band.

- **Rules, `classic_box_fade_long`:** `bb_pos` ≤ 0.03. Holds up to 240 minutes in the simulator.
- **Rules, `classic_box_fade_short`:** `bb_pos` ≥ 0.87.
- **Where it trades:** 2 setups on 2 pairs (GBP_USD, USD_JPY), sessions: london, ny.
- **Status now:** 1 ACTIVE, 0 PROBE, 1 SHADOW, 0 retired. 2 of its setups have held a live seat.
- **What the backtesting said:**
  - classics-retrial 2026-07-09: YTD +5.0 drift, edge vs baseline +3.3 (strongest of batch)
  - classics-retrial 2026-07-09: YTD +2.9, edge +2.7
- **Simulator:** 20 completed cycles, 90% won, -4.2 pips per cycle.
- **Real money:** 6 trades (0 of them poppers), -61.6 pips (-10.27 per trade), 50% won, $-17.78.

### ninja_flag

Bull/bear flag: a big 1-hour move (the pole, at the pair's 85th percentile or more), M5 EMAs and the H1 trend aligned, then a quiet, tight pullback on low volume.

- **Rules, `ninja_flag_long`:** `ema_trend_pips` ≥ 3.73; `ema20_1h_dist` ≥ 0; `ret_1h` ≥ 9.4; `ret_5m` -3.8 to 0.95; `rvol_5bar` ≤ 1. Holds up to 240 minutes in the simulator.
- **Rules, `ninja_flag_short`:** `ema_trend_pips` ≤ -3.73; `ema20_1h_dist` ≤ 0; `ret_1h` ≤ -9.4; `ret_5m` -0.95 to 3.8; `rvol_5bar` ≤ 1.
- **Where it trades:** 46 setups on 8 pairs (AUD_JPY, AUD_USD, EUR_JPY, EUR_USD, GBP_USD, USD_CAD, USD_CHF, USD_JPY), sessions: london, ny.
- **Status now:** 0 ACTIVE, 0 PROBE, 46 SHADOW, 0 retired. 3 of its setups have held a live seat.
- **What the backtesting said:**
  - NINJA slate 2026-08-30: ninjagex.com 'Ninja GEX System' + A+ checklist (Brock-supplied PDFs), translated to FX. GEX dealer-gamma levels DO NOT EXIST in spot FX — the PDF's own claimed differentiator is the one part not replicated; level := prior-session ceiling/floor (price structure, not positioning) and gamma regime := volatility regime (behavioural analogue only). FX tick volume is a tick count…
  - MAE-flip counterpart audit 2026-07-27: ninja_flag_long (long) ran 5 eps @ -15.9p/ep with medMFE/MAE 6.6/13.6 — mirror is hypothesis, not validation
- **Simulator:** 512 completed cycles, 85% won, -1.8 pips per cycle.
- **Real money:** 4 trades (1 of them poppers), -0.6 pips (-0.15 per trade), 75% won, $-0.18.

### kc_up

Leans long 4.6–15 pips under the upper Keltner Channel, with normal-or-better volume and a soft 60-day trend.

- **Rules, `kc_up_long_lean`:** `kc_up_dist_pips` -15 to -4.62; `rvol_5bar` ≥ 0.8; `htf_pct_60` ≤ 0.013. Holds up to 240 minutes in the simulator.
- **Rules, `kc_up_short_lean`:** `kc_up_dist_pips` -15 to 0.
- **Where it trades:** 4 setups on 1 pairs (AUD_USD), sessions: london.
- **Status now:** 1 ACTIVE, 0 PROBE, 3 SHADOW, 0 retired. 2 of its setups have held a live seat.
- **What the backtesting said:**
  - side-audit 2026-07-06: corpus drift LONG in window (2026 +0.40, 60d +1.59, 14d +6.14 p/240m); twin installed to earn side via n>=20 shadow gauntlet
  - rederivation-2026-07-03/v5_rederivation_REPORT.md item-3b; phaseA_gate_rederivation 2026-07-04 (INSUFFICIENT DATA verdict; kc_up gate survives raw)
- **Simulator:** 39 completed cycles, 95% won, +11.6 pips per cycle.
- **Real money:** 3 trades (0 of them poppers), +4.5 pips (+1.50 per trade), 67% won, $+4.81.

### shark_momo_run

Momentum on a hot day: H1 ATR 1.3× normal or more, half to two days' range already used, and the 4-hour trend and M5 EMAs agreeing. Go with it.

- **Rules, `shark_momo_run_long`:** `atr_h1_relative` ≥ 1.3; `adr_consumed` 0.5 to 2; `trend_4h` ≥ 0.5; `ema_trend_pips` ≥ 1. Holds up to 240 minutes in the simulator.
- **Rules, `shark_momo_run_short`:** `atr_h1_relative` ≥ 1.3; `adr_consumed` 0.5 to 2; `trend_4h` ≤ -0.5; `ema_trend_pips` ≤ -1.
- **Where it trades:** 44 setups on 8 pairs (AUD_JPY, AUD_USD, EUR_JPY, EUR_USD, GBP_USD, USD_CAD, USD_CHF, USD_JPY), sessions: london, ny.
- **Status now:** 0 ACTIVE, 1 PROBE, 43 SHADOW, 0 retired. 5 of its setups have held a live seat.
- **What the backtesting said:**
  - EATER slate 2026-08-19: churn-map session (P2.1 corpus walk-forward + P3a on 9,114 live episodes). Amplitude is predictable, count is not; dead-vol Q1 drags; fades peak mid-heat, momentum peaks max-heat; adr_consumed>0.9 continuation beat the exhaustion-fade heuristic. Correlational only, overlapping episodes, one era — zero prior, earns via family cycles or dies in shadow.
  - MAE-flip counterpart audit 2026-07-27: shark_momo_run_long (long) ran 7 eps @ -9.5p/ep with medMFE/MAE 9.5/20.1 — mirror is hypothesis, not validation
- **Simulator:** 381 completed cycles, 81% won, -8.7 pips per cycle.
- **Real money:** never traded.

### ninja_stab_fade

Fades back off the prior-session low in a calm, choppy market (H1 ATR 0.85× normal or less, low efficiency).

- **Rules, `ninja_stab_fade_long`:** `atr_h1_relative` ≤ 0.85; `efficiency_10` ≤ 0.13; `ps_low_dist` -6 to 6. Holds up to 240 minutes in the simulator.
- **Rules, `ninja_stab_fade_short`:** `atr_h1_relative` ≤ 0.85; `efficiency_10` ≤ 0.13; `ps_high_dist` -6 to 6.
- **Where it trades:** 40 setups on 8 pairs (AUD_JPY, AUD_USD, EUR_JPY, EUR_USD, GBP_USD, USD_CAD, USD_CHF, USD_JPY), sessions: london, ny.
- **Status now:** 0 ACTIVE, 0 PROBE, 40 SHADOW, 0 retired. 0 of its setups have held a live seat.
- **What the backtesting said:**
  - NINJA slate 2026-08-30: ninjagex.com 'Ninja GEX System' + A+ checklist (Brock-supplied PDFs), translated to FX. GEX dealer-gamma levels DO NOT EXIST in spot FX — the PDF's own claimed differentiator is the one part not replicated; level := prior-session ceiling/floor (price structure, not positioning) and gamma regime := volatility regime (behavioural analogue only). FX tick volume is a tick count…
  - MAE-flip counterpart audit 2026-07-27: ninja_stab_fade_long (long) ran 9 eps @ -12.28p/ep with medMFE/MAE 7.7/15.0 — mirror is hypothesis, not validation
- **Simulator:** 368 completed cycles, 88% won, +4.7 pips per cycle.
- **Real money:** never traded.

### ninja_amp_break

Breakout in a high-volatility regime: H1 ATR 1.25× normal or more, M5 EMAs aligned, price at the prior-session high or low.

- **Rules, `ninja_amp_break_long`:** `atr_h1_relative` ≥ 1.25; `ema_trend_pips` ≥ 3.73; `ps_high_dist` -6 to 6. Holds up to 240 minutes in the simulator.
- **Rules, `ninja_amp_break_short`:** `atr_h1_relative` ≥ 1.25; `ema_trend_pips` ≤ -3.73; `ps_low_dist` -6 to 6.
- **Where it trades:** 38 setups on 8 pairs (AUD_JPY, AUD_USD, EUR_JPY, EUR_USD, GBP_USD, USD_CAD, USD_CHF, USD_JPY), sessions: london, ny.
- **Status now:** 0 ACTIVE, 0 PROBE, 38 SHADOW, 0 retired. 0 of its setups have held a live seat.
- **What the backtesting said:**
  - NINJA slate 2026-08-30: ninjagex.com 'Ninja GEX System' + A+ checklist (Brock-supplied PDFs), translated to FX. GEX dealer-gamma levels DO NOT EXIST in spot FX — the PDF's own claimed differentiator is the one part not replicated; level := prior-session ceiling/floor (price structure, not positioning) and gamma regime := volatility regime (behavioural analogue only). FX tick volume is a tick count…
  - MAE-flip counterpart audit 2026-07-27: ninja_amp_break_short (short) ran 5 eps @ -3.7p/ep with medMFE/MAE 7.5/13.5 — mirror is hypothesis, not validation
- **Simulator:** 166 completed cycles, 77% won, -10.0 pips per cycle.
- **Real money:** never traded.

### ninja_stack_break

Breakout from compression: EMAs stacked with the H1 trend, volatility near normal, a volume burst (1.35×+) at or through the prior-session high or low.

- **Rules, `ninja_stack_break_long`:** `ema_trend_pips` ≥ 3.73; `ema20_1h_dist` ≥ 0; `atr_h1_relative` 0.8 to 1.15; `rvol_5bar` ≥ 1.35; `ps_high_dist` ≥ -6. Holds up to 240 minutes in the simulator.
- **Rules, `ninja_stack_break_short`:** `ema_trend_pips` ≤ -3.73; `ema20_1h_dist` ≤ 0; `atr_h1_relative` 0.8 to 1.15; `rvol_5bar` ≥ 1.35; `ps_low_dist` ≤ 6.
- **Where it trades:** 37 setups on 8 pairs (AUD_JPY, AUD_USD, EUR_JPY, EUR_USD, GBP_USD, USD_CAD, USD_CHF, USD_JPY), sessions: london, ny.
- **Status now:** 0 ACTIVE, 0 PROBE, 37 SHADOW, 0 retired. 0 of its setups have held a live seat.
- **What the backtesting said:**
  - NINJA slate 2026-08-30: ninjagex.com 'Ninja GEX System' + A+ checklist (Brock-supplied PDFs), translated to FX. GEX dealer-gamma levels DO NOT EXIST in spot FX — the PDF's own claimed differentiator is the one part not replicated; level := prior-session ceiling/floor (price structure, not positioning) and gamma regime := volatility regime (behavioural analogue only). FX tick volume is a tick count…
  - MAE-flip counterpart audit 2026-07-27: ninja_stack_break_long (long) ran 8 eps @ -0.12p/ep with medMFE/MAE 6.2/10.8 — mirror is hypothesis, not validation
- **Simulator:** 216 completed cycles, 81% won, -11.7 pips per cycle.
- **Real money:** never traded.

### tc_vwapbb

Trend pullback to the lower Bollinger Band while price holds above the session VWAP and the H1 EMA20 (open-source TradeClaw rules).

- **Rules, `tc_vwapbb_long`:** `bb_pos` ≤ 0.08; `vwap_dist_pips` ≥ 0; `ema20_1h_dist` ≥ 0. Holds up to 240 minutes in the simulator.
- **Rules, `tc_vwapbb_short`:** `bb_pos` ≥ 0.92; `vwap_dist_pips` ≤ 0; `ema20_1h_dist` ≤ 0.
- **Where it trades:** 26 setups on 4 pairs (AUD_USD, EUR_USD, GBP_USD, USD_CAD), sessions: asia, london, ny.
- **Status now:** 0 ACTIVE, 0 PROBE, 10 SHADOW, 16 retired. 0 of its setups have held a live seat.
- **What the backtesting said:**
  - external-repo trial 2026-07-31: TradeClaw VWAP-EMA-BB pullback (MIT). Source's own costed test was NEGATIVE - zero prior, must earn the seat via family cycles
  - MAE-flip counterpart audit 2026-07-27: tc_vwapbb_short (short) ran 5 eps @ -4.3p/ep with medMFE/MAE 1.2/13.8 — mirror is hypothesis, not validation
- **Simulator:** 249 completed cycles, 85% won, -4.8 pips per cycle.
- **Real money:** never traded.

### pwh_fade

Fades the previous week's high: within 5 pips of it with RSI 60+.

- **Rules, `pwh_fade_short`:** `pwh_dist` -5 to 5; `rsi14` ≥ 60. Holds up to 240 minutes in the simulator.
- **Where it trades:** 8 setups on 6 pairs (AUD_USD, EUR_USD, GBP_USD, USD_CAD, USD_CHF, USD_JPY), sessions: asia.
- **Status now:** 0 ACTIVE, 0 PROBE, 8 SHADOW, 0 retired. 0 of its setups have held a live seat.
- **What the backtesting said:**
  - v6.29.0 weekly-level trial: the pdh/pdl idea one horizon up (box_pdl_short is the best asia short on the book). Concept surfaced via Liquidity Suite / AWR scripts.
  - MAE-flip counterpart audit 2026-07-27: pwh_fade_short (short) ran 12 eps @ -1.42p/ep with medMFE/MAE 3.9/6.2 — mirror is hypothesis, not validation
- **Simulator:** 56 completed cycles, 89% won, -8.3 pips per cycle.
- **Real money:** never traded.

### pwl_fade

Buys the previous week's low: within 5 pips of it with RSI 40 or less.

- **Rules, `pwl_fade_long`:** `pwl_dist` -5 to 5; `rsi14` ≤ 40. Holds up to 240 minutes in the simulator.
- **Where it trades:** 6 setups on 6 pairs (AUD_USD, EUR_USD, GBP_USD, USD_CAD, USD_CHF, USD_JPY), sessions: asia.
- **Status now:** 0 ACTIVE, 0 PROBE, 6 SHADOW, 0 retired. 0 of its setups have held a live seat.
- **What the backtesting said:**
  - v6.29.0 weekly-level trial: the pdh/pdl idea one horizon up (box_pdl_short is the best asia short on the book). Concept surfaced via Liquidity Suite / AWR scripts.
- **Simulator:** 37 completed cycles, 84% won, -0.5 pips per cycle.
- **Real money:** never traded.

### box_pdl

Previous-day-low break: short once price trades below yesterday's low.

- **Rules, `box_pdl_short`:** `pdl_dist` ≤ 0. Holds up to 240 minutes in the simulator.
- **Where it trades:** 6 setups on 3 pairs (EUR_JPY, GBP_USD, USD_JPY), sessions: asia, ny.
- **Status now:** 0 ACTIVE, 0 PROBE, 3 SHADOW, 3 retired. 1 of its setups have held a live seat.
- **What the backtesting said:**
  - box-screen 2026-07-09: drift +10.73p/240m YTD n=2465, positive ALL slices (May +58.6)
  - MAE-flip counterpart audit 2026-07-27: box_pdl_short (short) ran 5 eps @ -26.98p/ep with medMFE/MAE 1.6/34.4 — mirror is hypothesis, not validation
- **Simulator:** 68 completed cycles, 94% won, +10.6 pips per cycle.
- **Real money:** never traded.

### es_meanrev

Range-regime fade: ADX 20 or less, RSI 68+, price at the upper band. Sell it (EuroScope).

- **Rules, `es_meanrev_short`:** `adx14` ≤ 20; `rsi14` ≥ 68; `bb_pos` ≥ 0.9. Holds up to 240 minutes in the simulator.
- **Where it trades:** 6 setups on 2 pairs (EUR_USD, GBP_USD), sessions: asia, london, ny.
- **Status now:** 0 ACTIVE, 0 PROBE, 2 SHADOW, 4 retired. 0 of its setups have held a live seat.
- **What the backtesting said:**
  - external-repo trial 2026-07-31: EuroScope regime-routed rules (MIT). No performance evidence in source - zero prior
- **Simulator:** 13 completed cycles, 92% won, +9.9 pips per cycle.
- **Real money:** never traded.

### regime_short_240

Short in quiet M5 volatility near the Keltner top while the 60-day trend is falling.

- **Rules, `regime_short_240`:** `atr_5m` ≤ 2.81; `kc_up_dist_pips` ≥ -4.54; `willr_m5` ≥ -66.37; `htf_pct_60` ≤ -0.005. Holds up to 240 minutes in the simulator.
- **Where it trades:** 3 setups on 1 pairs (AUD_JPY), sessions: ny.
- **Status now:** 0 ACTIVE, 0 PROBE, 2 SHADOW, 1 retired. 1 of its setups have held a live seat.
- **What the backtesting said:**
  - ratchet-ev-cells-2026-07-03/ratchet_ev_cells.csv (ev_gross=-0.07 short)
  - MAE-flip counterpart audit 2026-07-27: regime_short_240 (short) ran 5 eps @ -11.3p/ep with medMFE/MAE 5.7/8.6 — mirror is hypothesis, not validation
- **Simulator:** 35 completed cycles, 80% won, +5.9 pips per cycle.
- **Real money:** never traded.

### rvol_low_240

Long when relative volume is in its bottom quarter (a quiet tape) and price is not far above yesterday's low.

- **Rules, `rvol_low_240`:** `rvol_5bar`; `pdl_dist` ≤ 57. Holds up to 240 minutes in the simulator.
- **Rules, `rvol_low_240_short`:** `rvol_5bar`; `pdl_dist` ≤ 57.
- **Where it trades:** 3 setups on 1 pairs (GBP_USD), sessions: london.
- **Status now:** 0 ACTIVE, 0 PROBE, 3 SHADOW, 0 retired. 3 of its setups have held a live seat.
- **What the backtesting said:**
  - formula-history-2026-07-04/verdict_table.csv
  - mirror of the storm-loser long tape — descriptive only, NOT validation
- **Simulator:** 28 completed cycles, 75% won, -31.9 pips per cycle.
- **Real money:** never traded.

### kc_breakout

Long on a push above the upper Keltner Channel in calm H1 volatility, well above yesterday's low.

- **Rules, `kc_breakout_long`:** `kc_up_dist_pips` ≥ 0; `atr_h1_relative` ≤ 1.05; `pdl_dist` ≥ 63. Holds up to 60 minutes in the simulator.
- **Where it trades:** 3 setups on 1 pairs (USD_JPY), sessions: asia.
- **Status now:** 0 ACTIVE, 0 PROBE, 2 SHADOW, 1 retired. 1 of its setups have held a live seat.
- **What the backtesting said:**
  - phaseA_gate_rederivation 2026-07-04 (RE-EXPRESSIBLE; beats old d_cert gate 80% vs 71.4% keep-WR, n=9)
  - MAE-flip counterpart audit 2026-07-27: kc_breakout_long (long) ran 11 eps @ -6.5p/ep with medMFE/MAE 3.7/7.5 — mirror is hypothesis, not validation
- **Simulator:** 35 completed cycles, 89% won, +12.8 pips per cycle.
- **Real money:** never traded.

### willr_recovery

Short when Williams %R recovers above −50 in calm M5 volatility.

- **Rules, `willr_recovery_short`:** `willr_m5` -50 to 0; `atr_5m` ≤ 6.349. Holds up to 60 minutes in the simulator.
- **Where it trades:** 2 setups on 1 pairs (GBP_USD), sessions: ny.
- **Status now:** 0 ACTIVE, 0 PROBE, 2 SHADOW, 0 retired. 1 of its setups have held a live seat.
- **What the backtesting said:**
  - phaseA_gate_rederivation 2026-07-04 (PARTIAL verdict; n=7 recoverable + 14 broker)
  - MAE-flip counterpart audit 2026-07-27: willr_recovery_short (short) ran 17 eps @ -1.82p/ep with medMFE/MAE 5.0/11.7 — mirror is hypothesis, not validation
- **Simulator:** 16 completed cycles, 94% won, -4.9 pips per cycle.
- **Real money:** never traded.

## Before V6

V1–V5 tested a different generation of strategies: the box bot, the Trade-Strategy library, bucket-keyed routing and the strategy-free cell era. They are written up in the archive's [Strategy Encyclopedia](https://github.com/BrockStar3540/mr-scrooge-archive/blob/main/docs-harvest/v4-repo-docs/STRATEGY_ENCYCLOPEDIA.md) and [dead-ends graveyard](https://github.com/BrockStar3540/mr-scrooge-archive/blob/main/docs-harvest/v3-repo-docs/history/dead-ends-graveyard.md), and the edge hunts that falsified them are in [`docs/papers/`](papers/).
