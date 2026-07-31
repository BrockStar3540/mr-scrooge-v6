# Align-cube slate — 2026-07-31 (Brock)

Source: the 8-year factor-cube research (pre-H1-leak upper bounds, ladder-exit
era; corpus at `~/v5-archives/loose-home-files-2026-07-05/scored_7yr.parquet`
on the ops box, gate definitions in `scrooge_lab_code/factor_buckets.py` on
the research machine). Columns: strategy · align(1-4) · gate family · gate
variant · n · wins · losses · WR% · avg win · avg loss · expectancy · score.

Wiring decision (v6.14.6): the top-scoring wireable (strategy, gate) combo per
family was wired as SHADOW variants on the cube pairs (AUD/EUR/GBP_USD,
USD_CAD london+ny), gate bands translated at the cube's 10p stop context.
NOT wired, with reasons:
- E20/E50-gated combos — the live view carries ema dist, not SLOPE (the gate's
  quantity); no faithful translation without a feed extension.
- T1-gated combos — no distinct 1h-trend feature on the view (trend_4h only).
- alpha_breakout_retest, delta_tag_and_go, bravo_*, charlie_*, CP1/2/3,
  BR2_vcb — multi-bar pattern strategies, not expressible in the condition
  schema (per the 2026-07-27 cube commit's doctrine).
- MR5_williams_extreme — expressible (willr_m5 exists) but entry thresholds
  must come from the book sheet verbatim, which this slate does not carry.

Top slate rows (score-ranked, as provided):

```
alpha_extended_fade_v2  2  A1  A1_0  4912  2763  2149  56.2  11.36  -10  2.016  9904.1
alpha_pullback_v2       3  T4  T4a   25870 12436 13434 48.1  11.59  -10  0.381  9852.8
alpha_pullback_v2       3  E20 E20c  9141  4681  4460  51.2  11.63  -10  1.074  9818.3
TF2_pullback_EMA20_short 1 E50 E50d  9886  5071  4815  51.3  11.43  -10  0.992  9803.3
RG1_range_bound_scalp_long 4 T1 T1a  7172  3748  3424  52.3  11.75  -10  1.367  9801.8
RG1_range_bound_scalp_long 4 SPR SPR1 7172 3748  3424  52.3  11.75  -10  1.367  9801.8
RG1_range_bound_scalp_long 4 T4 T4a  7172  3748  3424  52.3  11.75  -10  1.367  9801.8
(… full table retained in the operator's records; the wired subset and skip
reasons above are the actionable content …)
```
