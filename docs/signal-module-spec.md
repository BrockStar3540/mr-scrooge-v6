# V5 Signal Module Specification
## Direction Module · Momentum Module · Playmaker Gate

**Version:** dm_04 calibration, 2026-06-18  
**Pairs:** AUD/JPY, AUD/USD, EUR/JPY, EUR/USD, GBP/USD, USD/CAD, USD/CHF, USD/JPY  
**Sessions:** asia (00:00–08:00 UTC), london (08:00–16:00 UTC), ny (13:00–21:00 UTC)  
**Source corpus:** OANDA M5 bars, 2019–2026, ~555k bars per pair

---

## 1. Data Foundation: The dm_04 Factor Sweep

Every numeric constant in both signal modules — weights, calibration anchors, regime thresholds — comes from a single offline experiment called **dm_04**: a per-(pair × session × feature) decile EV sweep on raw 60-minute forward returns (`net_60m`) with no exit management applied.

For each of the 24 (pair × session) buckets and each candidate feature, bars are ranked by feature value and split into 10 equal-count deciles (D1 = lowest feature values, D10 = highest). The mean forward return is computed for each decile. The **span** is then:

```
span = D10_mean_pips − D1_mean_pips
```

A positive span means high feature values precede bullish outcomes (continuation signal).  
A negative span means high feature values precede bearish outcomes (mean-reversion signal).

The sweep tested 57 indicators. 24 passed the inclusion threshold of |span| ≥ 0.27 pips median across all 24 buckets. These 24 form the direction module. 10 additional indicators with near-zero direction span but significant volatility structure form the momentum module.

No ratchet, harvest, or other exit-management label was used. The spans reflect raw directional predictability of each indicator independent of how a trade is managed.

---

## 2. Direction Module

### 2.1 The 24 Indicators

Indicators are split into two classes based on the sign of their dm_04 span.

**Class A — Continuation (13 indicators):** high feature value → bullish forward return

| Rank | MarketView field | Sweep key | dm_04 span (p) | Description |
|------|-----------------|-----------|----------------|-------------|
| 1 | `h1_ret_1bar` | `h1_ret_1bar` | +17.61 | Last completed H1 bar return, pips |
| 2 | `rsi_slope` | `rsi_slope` | +10.41 | H1 RSI-14 two-bar delta |
| 3 | `zscore_1h` | `zscore_1h` | +8.73 | H1 price Z-score vs 20-bar SMA |
| 4 | `h1_ret_4bar` | `h1_ret_4bar` | +7.35 | Sum of last 4 H1 bar returns, pips |
| 5 | `d_ret` | `d_ret` | +7.09 | Running daily return, pips |
| 6 | `ema20_1h_dist` | `ema20_1h_dist_pct` | +6.37 | H1 EMA20 distance as fraction of price |
| 7 | `pdh_dist` | `pdh_dist_pips` | +5.95 | Current price minus prev-day high, pips |
| 8 | `pdl_dist` | `pdl_dist_pips` | +5.88 | Current price minus prev-day low, pips |
| 9 | `pdl_dist_atr_pct` | `pdl_dist_atr_pct` | +5.69 | pdl_dist normalized by ATR |
| 10 | `pdh_dist_atr_pct` | `pdh_dist_atr_pct` | +5.62 | pdh_dist normalized by ATR |
| 11 | `rsi14` | `rsi14` | +4.79 | H1 RSI-14 level (0–100) |
| 12 | `htf_pct_20` | `htf_pct_20` | +1.91 | Higher-TF percent signal (20-bar window) |
| 13 | `htf_pct_60` | `htf_pct_60` | +1.01 | Higher-TF percent signal (60-bar window) |

**Class B — Mean-reversion (11 indicators):** high feature value → bearish forward return

| Rank | MarketView field | Sweep key | dm_04 span (p) | Description |
|------|-----------------|-----------|----------------|-------------|
| 14 | `ema20_dist_pct` | `ema20_dist_pct` | −0.57 | 5m EMA20 distance as fraction of price |
| 15 | `bb_pos` | `bb_pos` | −0.55 | Bollinger Band position (0=low band, 1=high band) |
| 16 | `zscore_5m` | `zscore_5m` | −0.55 | 5m price Z-score vs 20-bar SMA |
| 17 | `ema5_dist_pips` | `ema5_dist_pips` | −0.53 | 5m EMA5 distance, pips |
| 18 | `ret_5m` | `ret_5m` | −0.50 | Last 5m bar return, pips |
| 19 | `ret_15m` | `ret_15m` | −0.45 | 15m lagged return, pips |
| 20 | `ret_1h` | `ret_1h` | −0.44 | 1h lagged return, pips |
| 21 | `ret_30m` | `ret_30m` | −0.41 | 30m lagged return, pips |
| 22 | `ema50_dist_pct` | `ema50_dist_pct` | −0.39 | 5m EMA50 distance as fraction of price |
| 23 | `close_pos_daily` | `close_pos_daily` | −0.30 | Close position in daily range (0=bottom, 1=top) |
| 24 | `ema_cross_pips` | `ema_cross_pips` | −0.27 | EMA cross signal, pips |

**Why mean-reversion signals have negative spans:** When price is extended above the EMA (high `ema20_dist_pct`), the 60-minute forward return tends to be negative — price reverts. The module exploits this by assigning a negative weight to these features. When `bb_pos` is high (price near upper band), the module reads that as bearish pressure, not bullish.

**adr_consumed (excluded from direction):** dm_07 direction-split analysis showed that `adr_consumed` has opposite spans depending on h1 context (−6.1p in downtrend context vs +5.3p in uptrend context). In the aggregate dm_04 sweep it measures −0.52p — the two effects cancel and the aggregate signal is misleading. It is kept in the momentum module as `adr_context` (qualitative read only, not a weight-bearing feature).

---

### 2.2 Per-Pair Calibration: Normalization Anchors

Each (pair × session) bucket has its own normalization range for every feature, loaded from `factor_sweep.json` at startup. The anchors are:

- **lo** = `D1.hi_val` — the D1/D2 boundary (top of the bottom decile, excluding the extreme D1 outliers themselves)
- **hi** = `D10.lo_val` — the D9/D10 boundary (bottom of the top decile, excluding the extreme D10 outliers)

These anchors were chosen over the absolute extremes (`D1.lo_val`, `D10.hi_val`) because the outer decile tails include genuine outliers (news spikes, data artifacts) that would compress all normal-day readings into a narrow range near zero.

The h1_ret_1bar calibration anchors across all 24 buckets illustrate the breadth of per-pair variation:

| Pair | Session | lo (p) | hi (p) | span (p) |
|------|---------|--------|--------|----------|
| AUD_JPY | asia | −13.000 | +13.400 | 26.4 |
| AUD_JPY | london | −14.300 | +14.400 | 28.7 |
| AUD_JPY | ny | −10.400 | +10.800 | 21.2 |
| AUD_USD | asia | −8.600 | +8.800 | 17.4 |
| AUD_USD | london | −11.200 | +11.200 | 22.4 |
| AUD_USD | ny | −8.200 | +8.000 | 16.2 |
| EUR_JPY | asia | −13.800 | +13.900 | 27.7 |
| EUR_JPY | london | −19.900 | +20.600 | 40.5 |
| EUR_JPY | ny | −11.900 | +12.600 | 24.5 |
| EUR_USD | asia | −6.900 | +7.000 | 13.9 |
| EUR_USD | london | −14.300 | +14.400 | 28.7 |
| EUR_USD | ny | −9.600 | +9.500 | 19.1 |
| GBP_USD | asia | −9.400 | +9.400 | 18.8 |
| GBP_USD | london | −20.400 | +20.200 | 40.6 |
| GBP_USD | ny | −13.000 | +12.900 | 25.9 |
| USD_CAD | asia | −8.000 | +7.900 | 15.9 |
| USD_CAD | london | −14.300 | +14.600 | 28.9 |
| USD_CAD | ny | −12.000 | +12.400 | 24.4 |
| USD_CHF | asia | −6.000 | +6.000 | 12.0 |
| USD_CHF | london | −12.800 | +12.500 | 25.3 |
| USD_CHF | ny | −8.200 | +8.300 | 16.5 |
| USD_JPY | asia | −13.100 | +13.200 | 26.3 |
| USD_JPY | london | −16.400 | +16.900 | 33.3 |
| USD_JPY | ny | −10.700 | +11.800 | 22.5 |

EUR/JPY and GBP/USD london sessions have roughly 3× the absolute range of EUR/USD asia — without per-pair calibration, the same absolute h1_ret_1bar value of +8.0p would score very differently (0.73 on EUR/USD london vs near the top range on EUR/USD asia). The per-pair normalization ensures a given decile rank produces the same normalized value regardless of the pair's volatility regime.

**Fallback anchors** (when calibration data is absent):

| Feature | lo_fallback | hi_fallback |
|---------|-------------|-------------|
| h1_ret_1bar | −12.0p | +12.0p |
| rsi_slope | −9.0 | +9.0 |
| zscore_1h | −2.0 | +2.0 |
| h1_ret_4bar | −20.0p | +20.0p |
| d_ret | −40.0p | +40.0p |
| ema20_1h_dist | −0.15 | +0.15 |
| pdh_dist | −20.0p | +20.0p |
| pdl_dist | −20.0p | +20.0p |
| pdh_dist_atr_pct | −3.0 | +3.0 |
| pdl_dist_atr_pct | −3.0 | +3.0 |
| rsi14 | 35.0 | 65.0 |
| htf_pct_20 | −3.0 | +3.0 |
| htf_pct_60 | −3.0 | +3.0 |
| ema20_dist_pct | −0.10 | +0.10 |
| bb_pos | 0.1 | 0.9 |
| zscore_5m | −2.0 | +2.0 |
| ema5_dist_pips | −5.0p | +5.0p |
| ret_5m | −3.0p | +3.0p |
| ret_15m | −5.0p | +5.0p |
| ret_30m | −8.0p | +8.0p |
| ret_1h | −12.0p | +12.0p |
| ema50_dist_pct | −0.20 | +0.20 |
| close_pos_daily | 0.1 | 0.9 |
| ema_cross_pips | −3.0p | +3.0p |

---

### 2.3 Feature Normalization

Each feature value is mapped to a signed range [−1, +1] relative to its per-bucket calibration anchors:

```
norm_i = clip( (v_i − lo_i) / (hi_i − lo_i) × 2 − 1,  −1,  +1 )
```

Where:
- `v_i` = raw feature value from MarketView
- `lo_i` = D1.hi_val for that (pair, session, feature)
- `hi_i` = D10.lo_val for that (pair, session, feature)

Interpretation of norm_i:
- `norm_i = −1.0` → feature is at or below the D1/D2 boundary (bottom 10% territory)
- `norm_i = 0.0` → feature is at the midpoint of the D1/D2 to D9/D10 range
- `norm_i = +1.0` → feature is at or above the D9/D10 boundary (top 10% territory)

Values below `lo_i` clip to −1 and values above `hi_i` clip to +1. The outlier extreme decile values (D1 lows and D10 highs) therefore all score ±1 and are not further distinguished — the module does not penalize or reward outlier extremes beyond the D9/D10 boundary.

**Example (EUR/USD london, h1_ret_1bar):**  
lo = −14.30p, hi = +14.40p

| Raw value | Calculation | norm |
|-----------|-------------|------|
| +14.40p | (14.40 − (−14.30)) / 28.70 × 2 − 1 | +1.00 |
| +8.50p | (8.50 − (−14.30)) / 28.70 × 2 − 1 | +0.59 |
| 0p | (0 − (−14.30)) / 28.70 × 2 − 1 | −0.003 ≈ 0.00 |
| −8.50p | (−8.50 − (−14.30)) / 28.70 × 2 − 1 | −0.60 |
| −14.30p | (−14.30 − (−14.30)) / 28.70 × 2 − 1 | −1.00 |

---

### 2.4 Signed Weight Derivation

The signed weight for each factor is its dm_04 raw span divided by the sum of absolute spans across all 24 included features:

```
Σ_abs = Σ |span_i|  for i = 1..24  =  93.37 pips
w_i   = span_i / Σ_abs
```

Continuation features (positive spans) get positive weights; mean-reversion features (negative spans) get negative weights. The absolute sum of all weights equals 1.0:

```
Σ |w_i| = 1.0
```

This means each feature's weight equals the fraction of total directional information it carries. The feature with the largest contribution to the direction outcome gets the largest weight.

Full weight table:

| # | Feature | span (p) | weight w_i | |w_i| | cumulative |w| |
|---|---------|----------|------------|------|----------------|
| 1 | h1_ret_1bar | +17.61 | +0.18862 | 0.18862 | 0.189 |
| 2 | rsi_slope | +10.41 | +0.11148 | 0.11148 | 0.300 |
| 3 | zscore_1h | +8.73 | +0.09349 | 0.09349 | 0.393 |
| 4 | h1_ret_4bar | +7.35 | +0.07872 | 0.07872 | 0.472 |
| 5 | d_ret | +7.09 | +0.07593 | 0.07593 | 0.548 |
| 6 | ema20_1h_dist | +6.37 | +0.06820 | 0.06820 | 0.616 |
| 7 | pdh_dist | +5.95 | +0.06373 | 0.06373 | 0.680 |
| 8 | pdl_dist | +5.88 | +0.06298 | 0.06298 | 0.743 |
| 9 | pdl_dist_atr_pct | +5.69 | +0.06094 | 0.06094 | 0.804 |
| 10 | pdh_dist_atr_pct | +5.62 | +0.06019 | 0.06019 | 0.864 |
| 11 | rsi14 | +4.79 | +0.05130 | 0.05130 | 0.915 |
| 12 | htf_pct_20 | +1.91 | +0.02045 | 0.02045 | 0.936 |
| 13 | htf_pct_60 | +1.01 | +0.01082 | 0.01082 | 0.946 |
| 14 | ema20_dist_pct | −0.57 | −0.00611 | 0.00611 | 0.953 |
| 15 | bb_pos | −0.55 | −0.00589 | 0.00589 | 0.958 |
| 16 | zscore_5m | −0.55 | −0.00589 | 0.00589 | 0.964 |
| 17 | ema5_dist_pips | −0.53 | −0.00568 | 0.00568 | 0.970 |
| 18 | ret_5m | −0.50 | −0.00536 | 0.00536 | 0.975 |
| 19 | ret_15m | −0.45 | −0.00482 | 0.00482 | 0.980 |
| 20 | ret_1h | −0.44 | −0.00471 | 0.00471 | 0.985 |
| 21 | ret_30m | −0.41 | −0.00439 | 0.00439 | 0.989 |
| 22 | ema50_dist_pct | −0.39 | −0.00418 | 0.00418 | 0.993 |
| 23 | close_pos_daily | −0.30 | −0.00321 | 0.00321 | 0.997 |
| 24 | ema_cross_pips | −0.27 | −0.00289 | 0.00289 | 1.000 |
| — | **TOTAL** | **93.37** | — | **1.00000** | |

The top 5 features (h1_ret_1bar through d_ret) account for 54.8% of total weight. The top 11 continuation features (ranks 1–11) account for 91.5%. The 11 mean-reversion features combined carry only 5.4% of total weight.

---

### 2.5 Composite Score

The raw composite is the weighted signed sum of all normalized features:

```
raw_score = Σ (w_i × norm_i)   for i = 1..24
```

Then clipped to [−1, +1]:

```
score = clip(raw_score, −1, +1)
```

**Sign semantics:**
- `score > 0` → net bullish reading (more continuation signal than mean-reversion)
- `score < 0` → net bearish reading
- `score ≈ 0` → conflicting or neutral indicators

**Absolute bounds:**
- Maximum possible score = +1.0 requires: all 13 continuation features at norm=+1.0 AND all 11 mean-reversion features at norm=−1.0 (i.e., all perfectly aligned bullish). This requires every indicator simultaneously at its historical D10 extreme.
- In practice, scores above ±0.60 are rare. Scores above ±0.80 occur only on extreme multi-factor setups (news-driven sessions, strong trend days).

**Example (strong long setup, EUR/USD london):**

| Feature | norm_i | w_i | contribution |
|---------|--------|-----|-------------|
| h1_ret_1bar = +10p | +0.67 | +0.189 | +0.127 |
| rsi_slope = +6.0 | +0.80 | +0.111 | +0.089 |
| zscore_1h = +1.5 | +0.50 | +0.093 | +0.047 |
| d_ret = +30p | +0.60 | +0.076 | +0.046 |
| ema20_1h_dist = +0.08 | +0.55 | +0.068 | +0.037 |
| bb_pos = 0.72 | +0.72 | −0.006 | −0.004 |
| zscore_5m = +0.80 | +0.80 | −0.006 | −0.005 |
| ret_5m = +1.5p | +0.50 | −0.005 | −0.003 |
| (remaining 16) | ~0 | — | ~0 |
| **raw_score** | | | **+0.334** |
| **clipped score** | | | **+0.334** |

---

### 2.6 Bias Classification

After clipping, score is classified into a directional bias:

```
if   score >  0.15 → bias = "long"
elif score < −0.15 → bias = "short"
else               → bias = "block"
```

The ±0.15 threshold is the "block zone" — weighted indicators are within 15% of the maximum possible score from neutral, which is not sufficient to commit to a direction. A trade will not be entered on a "block" ticket regardless of any other reading.

The ±0.15 boundary corresponds to the state where h1_ret_1bar alone is in strong D9 territory (norm=0.80) with no other support: contribution = 0.189 × 0.80 = 0.151 ≈ 0.15. In other words, a "non-block" signal requires at least the strength of having the primary momentum indicator clearly elevated, with some supporting signal to push past 0.15.

---

### 2.7 Factor Extremity

Factor extremity measures how far from zero (i.e., from the D5 center) the factors collectively are:

```
extremity = Σ |w_i × norm_i|   for i = 1..24
```

This is the sum of absolute contributions from all factors. Since |w_i| sums to 1.0 and |norm_i| ≤ 1.0:

```
0 ≤ extremity ≤ 1.0
```

Extremity is 0 when all features are exactly at their D5 midpoint (norm = 0 for all). Extremity is 1.0 when all features are at their maximum deviation from center in a consistent direction.

Note: extremity differs from |score|. When all continuation features are at norm=+1.0 and all mean-reversion at norm=+1.0 (not at −1.0 as a bearish signal would require), the extremity is still 1.0 but the score would be near zero because continuation and mean-reversion cancel. Extremity only reflects how extreme the readings are, not whether they agree.

---

### 2.8 Alignment Agreement

Agreement measures what fraction of active weighted signal points in the same direction as the composite score:

Only factors with |w_i × norm_i| > 0.002 are included in this calculation (the 0.002 threshold filters out contributions too small to be meaningful — at a weight of 0.003 and norm of 0.5, contribution is 0.0015, smaller than numerical noise).

Let **S** = sign(score). If |score| ≤ 0.05 or score = 0, agreement is set to 0.5 (neutral — no direction to align with).

Otherwise:

```
active_set  = { i : |w_i × norm_i| > 0.002 }
agree_weight  = Σ |w_i × norm_i|  for i ∈ active_set  where sign(w_i × norm_i) = S
total_weight  = Σ |w_i × norm_i|  for i ∈ active_set
agreement     = agree_weight / total_weight
```

Agreement ranges from 0.0 (all active factors oppose the composite direction) to 1.0 (all active factors align with it). In practice, values below 0.50 are unusual because the composite itself is a weighted majority vote — a composite of +0.20 already implies more weight aligned than opposed.

**Example:** If 80% of the active weighted signal points bullish but 20% of lower-weight mean-reversion factors are at extreme readings and pointing bearish, agreement = 0.80.

---

### 2.9 Direction Certainty

```
certainty = clip( extremity × (0.4 + 0.6 × agreement),  0,  1 )
```

This formula combines two orthogonal questions:
1. **Extremity:** Are the indicators actually saying something? (Are readings far from their midpoints?)
2. **Agreement:** Are they saying the same thing? (Do they all point the same direction?)

**The (0.4 + 0.6 × agreement) term:**
- At agreement = 0.0 → multiplier = 0.40 (even perfect disagreement gives 40% of the extremity value, because the extremity itself captured strong readings)
- At agreement = 0.5 → multiplier = 0.70
- At agreement = 1.0 → multiplier = 1.00

This weighting means agreement is important but can never collapse the certainty to zero when extremity is high. A setup where every factor is screaming strongly but half point each way still registers moderate certainty from the extremity alone.

**Calibration reference points (derived from dm_04):**

| Scenario | extremity | agreement | certainty |
|----------|-----------|-----------|-----------|
| h1_ret_1bar alone at D8 (norm=0.70), others neutral | 0.189×0.70 = 0.132 | 1.00 | 0.132 |
| h1 at D8 + 3 supporting at D7 (norm=0.45) | ~0.213 | 0.90 | 0.213 × 0.94 = 0.200 |
| h1 at D9 (norm=0.85) + 4 supporting at D7 (norm=0.45) | ~0.322 | 0.90 | 0.322 × 0.94 = 0.303 |
| h1 at D10 (norm=1.0) + all continuation at D8 (norm=0.65) | ~0.55 | 0.95 | 0.55 × 0.97 = 0.534 |
| Perfect alignment (all factors D10/D1) | 1.00 | 1.00 | 1.00 |

The practical range for tradeable setups is roughly 0.25–0.65. Values above 0.65 occur on high-conviction multi-factor alignment days and are not capped — they rank higher in the playmaker.

---

### 2.10 Label Translation

Each factor receives a human-readable label based on its normalized value:

```
if   norm >  0.70 → "strong_long"
elif norm >  0.30 → "mild_long"
elif norm > −0.30 → "neutral"
elif norm > −0.70 → "mild_short"
else              → "strong_short"
```

**For continuation features (w_i > 0):** the label reflects the feature's bullish/bearish implication directly. A high bb_pos... wait, bb_pos has w_i < 0 (mean-reversion), so:

**For mean-reversion features (w_i < 0):** the label is FLIPPED before display, because a high feature value is bearish (negative weight). The directional meaning of the label is preserved from the reader's perspective:

```
if w_i < 0:
    display_label = label_function(−norm_i)
else:
    display_label = label_function(norm_i)
```

Example: `bb_pos = 0.80` → norm = +0.75 → raw label would be "strong_long" (high on the band). But since bb_pos is a mean-reversion feature (w_i < 0), the flipped label = label(−0.75) = "strong_short". The reads dict will show `bb_pos: "strong_short"`, correctly conveying that price near the upper band is a bearish signal.

The reads dict also contains two summary fields:
- `reads["agreement"]`: a string like "78% weight aligned" showing the alignment fraction
- `reads["cal"]`: the pair/session and the h1_ret_1bar calibration range for sanity-checking the live feed

---

## 3. Momentum Module

### 3.1 The 10 Indicators

| Field | Role | Notes |
|-------|------|-------|
| `atr_5m` | Primary vol regime classification | Per-pair D2/D8/D9 thresholds |
| `atr_1h` | Expected-pips base | Hourly ATR as magnitude anchor |
| `rvol_5bar` | Short-window relative volume | vs 5-bar mean |
| `rvol_12bar` | Medium-window relative volume | vs 12-bar mean |
| `bb_width` | Band width (qualitative only) | Not a weight-bearing score |
| `range_5bar` | Recent high-low range | Ratio vs range_12bar |
| `range_12bar` | Medium-window high-low range | Used for range_trend read |
| `d_range_pips` | Today's full daily range | Carried in reads |
| `adr_consumed` | Fraction of avg daily range used | Qualitative context only |
| `atr_conc` | ATR concentration ratio | Carried in reads |

None of these 10 features carry a signed weight in the momentum module. They inform regime classification, certainty, and magnitude estimation — not a directional score.

---

### 3.2 Vol Regime Classification

ATR_5m is classified into four regimes using per-(pair × session) thresholds:

```
if   atr_5m ≥ thr_ext  → regime = "extreme"
elif atr_5m ≥ thr_high → regime = "high"
elif atr_5m ≥ thr_low  → regime = "normal"
else                    → regime = "low"
```

Where:
- `thr_low` = D2.hi_val of atr_5m in this bucket (D2/D3 boundary — top of bottom 20%)
- `thr_high` = D8.hi_val of atr_5m in this bucket (D8/D9 boundary — top of the 70th percentile)
- `thr_ext` = D9.hi_val of atr_5m in this bucket (D9/D10 boundary — top of the 90th percentile)

These thresholds divide the ATR_5m distribution into:

| Regime | ATR range | Historical frequency |
|--------|-----------|---------------------|
| low | below D2 | ~20% of bars |
| normal | D2–D8 | ~60% of bars |
| high | D8–D9 | ~10% of bars |
| extreme | above D9 | ~10% of bars |

---

### 3.3 Per-Pair ATR Thresholds

All values in pips. These numbers govern which vol regime applies to each bar.

| Pair | Session | thr_low (D2.hi) | thr_high (D8.hi) | thr_ext (D9.hi) | D5 mid |
|------|---------|-----------------|------------------|-----------------|--------|
| AUD_JPY | asia | 2.860 | 5.905 | 7.216 | 3.882 |
| AUD_JPY | london | 3.428 | 6.624 | 7.999 | 4.474 |
| AUD_JPY | ny | 2.646 | 6.143 | 7.709 | 3.762 |
| AUD_USD | asia | 1.829 | 3.721 | 4.447 | 2.475 |
| AUD_USD | london | 2.400 | 4.753 | 5.727 | 3.175 |
| AUD_USD | ny | 1.883 | 4.617 | 5.867 | 2.749 |
| EUR_JPY | asia | 2.755 | 6.699 | 8.381 | 3.966 |
| EUR_JPY | london | 4.300 | 9.173 | 11.186 | 5.814 |
| EUR_JPY | ny | 3.096 | 7.462 | 9.558 | 4.444 |
| EUR_USD | asia | 1.491 | 3.120 | 3.888 | 2.019 |
| EUR_USD | london | 3.139 | 6.078 | 7.363 | 4.088 |
| EUR_USD | ny | 2.308 | 5.691 | 7.105 | 3.409 |
| GBP_USD | asia | 2.123 | 4.135 | 5.101 | 2.767 |
| GBP_USD | london | 4.604 | 8.333 | 9.819 | 5.839 |
| GBP_USD | ny | 3.225 | 7.590 | 9.419 | 4.676 |
| USD_CAD | asia | 1.791 | 3.540 | 4.341 | 2.371 |
| USD_CAD | london | 2.866 | 5.850 | 7.263 | 3.853 |
| USD_CAD | ny | 3.026 | 6.612 | 8.185 | 4.195 |
| USD_CHF | asia | 1.353 | 2.679 | 3.365 | 1.763 |
| USD_CHF | london | 2.724 | 5.023 | 6.160 | 3.459 |
| USD_CHF | ny | 2.036 | 4.728 | 5.857 | 2.920 |
| USD_JPY | asia | 2.151 | 6.504 | 8.202 | 3.352 |
| USD_JPY | london | 2.874 | 8.104 | 10.159 | 4.475 |
| USD_JPY | ny | 2.410 | 7.000 | 9.274 | 3.750 |

Notable spread:
- USD_CHF asia has the lowest thr_high at 2.679p — a 3p ATR_5m already puts it in "high" regime.
- EUR_JPY london has the highest thr_ext at 11.186p — bars at 10p ATR are only "high" here.
- USD_JPY and EUR_JPY show the widest normal ranges, reflecting JPY cross volatility structure.

---

### 3.4 Expected Pips

The expected_pips estimate is the module's forward magnitude estimate — how large the move over the next hour is likely to be given current vol conditions:

```
rvol_combined = (rvol_5bar + rvol_12bar) / 2
rvol_factor   = clip(rvol_combined, 0.6, 1.6)
expected_pips = atr_1h × rvol_factor
```

`atr_1h` is the actual 1-hour ATR from the live feed — the historical average hourly move for this pair.

`rvol_factor` scales the expected move by current volume activity relative to the historical average. The clip prevents extreme volume readings from producing absurd pip estimates:
- Minimum factor = 0.6 (even very low volume produces at least 60% of the ATR estimate)
- Maximum factor = 1.6 (very high volume produces at most 160% of the ATR estimate)

This is a calibration-free formula — it does not use any dm_04 data because the momentum module does not attempt to predict direction-adjusted magnitude, only unconditional regime-aware magnitude.

---

### 3.5 Momentum Certainty: All Four Regime Cases

The certainty formula varies by which regime the bar is in. In all cases, the raw value is clipped to [0, 1] and then potentially boosted by rvol agreement.

**Case 1 — extreme regime (atr_5m ≥ thr_ext):**

```
raw = min(  (atr_5m − thr_ext) / thr_ext  +  0.5,  1.0  )
```

- At exactly thr_ext: raw = 0/thr_ext + 0.5 = 0.50 (moderate certainty just crossing into extreme)
- At 2 × thr_ext: raw = thr_ext/thr_ext + 0.5 = 1.50 → clipped to 1.0
- Certainty starts at 0.5 the instant the bar enters extreme territory and rises linearly to 1.0.

Rationale: entering the extreme regime is already an unusual and identifiable event (top 10%), so the base certainty is 0.5 even at the threshold. Deeper into extreme territory, the reading is unambiguous.

**Case 2 — high regime (thr_high ≤ atr_5m < thr_ext):**

```
span = thr_ext − thr_high
raw  = (atr_5m − thr_high) / span
```

- At thr_high: raw = 0.0 (just entered high, uncertain — it's the D8 boundary and could revert)
- At thr_ext: raw = 1.0 (at the top of high, just before extreme)
- Certainty rises linearly from 0 to 1 across the high vol range.

**Case 3 — low regime (atr_5m < thr_low):**

```
raw = 1.0 − (atr_5m / thr_low)
```

- At thr_low: raw = 1 − (thr_low/thr_low) = 0.0 (just entered low, uncertain)
- At 0: raw = 1.0 (definitively zero activity — maximum certainty in the low regime)
- Certainty rises as ATR moves further below the low threshold.

**Case 4 — normal regime (thr_low ≤ atr_5m < thr_high):**

```
dist = (atr_5m − thr_low) / (thr_high − thr_low)   ∈ [0, 1]
raw  = |dist − 0.5| × 2
```

- At thr_low (dist=0.0): raw = |0.0 − 0.5| × 2 = 1.0 (at the low/normal boundary — clear regime transition point)
- At D5 mid (dist=0.5): raw = |0.5 − 0.5| × 2 = 0.0 (ambiguous center of the normal zone)
- At thr_high (dist=1.0): raw = |1.0 − 0.5| × 2 = 1.0 (at the normal/high boundary)

The normal-regime certainty is therefore **highest at the boundaries and lowest at the center**. This reflects the informational content: a bar exactly in the middle of the normal ATR range tells us the least about vol conditions. A bar near the top of normal suggests we may be approaching high vol; a bar near the bottom suggests we may be approaching low vol.

---

### 3.6 Relative Volume Boost

After computing the raw certainty, a 20% boost is applied when the vol indicators corroborate each other:

```
if regime in ("high", "extreme") and rvol_combined > 1.25:
    certainty = min(certainty × 1.20,  1.0)

elif regime == "low" and rvol_combined < 0.75:
    certainty = min(certainty × 1.20,  1.0)
```

Logic: if ATR_5m says "high vol" AND rvol (transaction activity) is also elevated (>25% above normal), the two independent measures of vol agree → increase confidence. The same applies to low vol: if ATR is low AND rvol is subdued, both signals confirm a quiet market.

The boost is deliberately one-directional: if rvol contradicts the ATR regime, certainty is not reduced — only corroboration earns a boost. This is because rvol can be noisy in thin markets while ATR is the structural signal.

---

### 3.7 ADR Context (Qualitative Only)

`adr_consumed` is the fraction of the average daily range already used today:

```
if   adr_consumed < 0.25 → "fresh"      (early in the day's range)
elif adr_consumed < 0.55 → "midfield"   (typical mid-session position)
elif adr_consumed < 0.80 → "extended"   (significant portion of range used)
else                      → "exhausted" (range near or past average daily extent)
```

This label appears in the reads dict as `adr_context` but carries no weight in the momentum score or certainty. It is available to the human operator (dashboard) and to any downstream module that wants to reduce size or avoid entry when the daily range is exhausted.

The reason it is qualitative-only: dm_07 showed that the predictive direction of `adr_consumed` reverses between up-trend and down-trend bars (+5.3p in up-trend, −6.1p in down-trend). The aggregate dm_04 span of −0.52p is a near-cancellation. Including it in a direction-blind score would distort certainty.

---

### 3.8 Range Trend (Qualitative)

```
ratio = range_12bar / range_5bar
```

| Ratio | Label |
|-------|-------|
| > 2.0 | "expanding" |
| > 1.2 | "slightly_expanding" |
| > 0.8 | "stable" |
| ≤ 0.8 | "contracting" |

A contracting range (ratio < 1) means the last 5 bars are covering less ground than the broader 12-bar window — potential coiling or exhaustion. An expanding range means volatility is increasing.

---

## 4. The PairTicket

After both modules run, their stamps are combined into a PairTicket:

```
PairTicket.composite_score = direction.score
                           × direction.certainty
                           × momentum.certainty
```

The composite is signed: positive values indicate a long setup, negative values a short setup.

```
PairTicket.is_actionable =   direction.bias != "block"
                         AND direction.certainty > 0.25
                         AND momentum.vol_regime != "extreme"
```

`is_actionable` is the **low bar** — technically safe to consider. It does not mean the playmaker will fire. The playmaker adds its own stricter gates on top.

---

## 5. The Playmaker Gate

### 5.1 The Three Certainty Floors

These floors are the playmaker's independent gate layer, applied after `is_actionable`:

| Constant | Value | Derivation |
|----------|-------|------------|
| `MIN_DIRECTION_SCORE` | 0.25 | The block zone covers ±0.15. Score 0.15–0.25 is technically non-block but directionally weak — corresponds to only h1_ret_1bar in D7 territory with little support. 0.25+ requires meaningful commitment from multiple factors. |
| `MIN_DIR_CERTAINTY` | 0.30 | From dm_04: requires approximately h1_ret_1bar at D9 (norm≈0.85) plus 4 supporting factors in D7 territory (norm≈0.45). At this level, extremity ≈ 0.32, agreement ≈ 90%, certainty ≈ 0.30. Below this level the signal is not consistently above the noise floor established by the sweep. |
| `MIN_MOM_CERTAINTY` | 0.25 | ATR_5m must be at least 25% of the way from the center of the normal zone toward a regime boundary, or clearly in the low/high/extreme regime. Below 0.25 the vol regime is ambiguous and expected_pips estimates are unreliable. |

Note: `is_actionable` gates on `direction.certainty > 0.25`, which overlaps the `MIN_DIR_CERTAINTY = 0.30` gate. The two layers serve different purposes: `is_actionable` is the signal module's own sanity check, while the playmaker's floor is the trading threshold. They can be tuned independently.

### 5.2 Gate Sequence

The gates are applied in order. A ticket that fails any gate is dropped — no further gates are checked:

```
1. Session gate:    pair is active in current_session(hour_utc)
2. Position gate:   pair not in open_pairs
3. is_actionable:   direction.bias != "block"
                    AND direction.certainty > 0.25
                    AND momentum.vol_regime != "extreme"
4. Score floor:     abs(direction.score) >= MIN_DIRECTION_SCORE (0.25)
5. Dir cert floor:  direction.certainty >= MIN_DIR_CERTAINTY (0.30)
6. Mom cert floor:  momentum.certainty >= MIN_MOM_CERTAINTY (0.25)
7. Spread gate:     spread_pips <= MAX_SPREAD[pair]
                    (only if spread_pips > 0.0; skipped when feed is not live)
```

Maximum spread limits by pair:

| Pair | MAX_SPREAD (p) |
|------|----------------|
| EUR_USD | 2.5 |
| GBP_USD | 3.0 |
| USD_JPY | 2.0 |
| AUD_USD | 2.5 |
| USD_CAD | 3.0 |
| USD_CHF | 3.0 |
| EUR_JPY | 3.5 |
| AUD_JPY | 4.0 |
| (default) | 3.0 |

### 5.3 Best-Edge Ranking

When multiple tickets survive all gates in the same cycle (a "group arrival"), the playmaker selects the single best-edge setup using a two-level sort key:

```
edge_rank(ticket) = ( abs(composite_score),  expected_pips )
```

The ticket with the highest `abs(composite_score)` wins. If two tickets have identical composite scores, the one with higher `expected_pips` wins (prefer the pair with greater expected magnitude at the same quality of signal).

`composite_score = direction.score × direction.certainty × momentum.certainty`

This ranking correctly prices the joint quality of both modules. A moderately-strong direction signal with high certainties (0.45 score × 0.55 cert × 0.50 cert = 0.124) outranks a raw strong signal with poor certainties (0.80 × 0.32 × 0.26 = 0.067). The module is rewarding reliable signal, not just signal magnitude.

The fired `TradeTicket` records `rivals` — the count of other tickets that passed all gates in the same cycle. When `rivals > 0`, there were alternative setups the playmaker chose not to take.

---

## 6. Tuning the Playmaker Gate

### 6.1 How to Tighten (Trade Less, Higher Conviction Only)

Raise one or more of the three floor constants in `modules/playmaker/playmaker.py`. Each has a different effect:

**Raise `MIN_DIRECTION_SCORE` (currently 0.25):**

This requires more raw directional signal. At 0.30, the leading indicators must contribute ~20% more to the score.

| Value | Effect |
|-------|--------|
| 0.25 (current) | Above the weak-signal zone; blocks ~10% of non-block tickets |
| 0.30 | Requires clear multi-factor commitment; blocks ~25% of non-block tickets |
| 0.40 | High-conviction directional moves only; blocks ~40% |
| 0.50 | Major trending setups only; very infrequent |

Raise this when: you want to eliminate borderline directional setups — bars where the primary indicator is strong but secondary indicators are mixed.

**Raise `MIN_DIR_CERTAINTY` (currently 0.30):**

This requires better factor agreement and more extreme readings. Moving from 0.30 to 0.40 requires either the top factor to be in D10 territory or a wider coalition of D8-range factors.

| Value | Approximate requirement |
|-------|------------------------|
| 0.25 | h1 at D9 + 2 supporting at D7 |
| 0.30 (current) | h1 at D9 + 4 supporting at D7 (dm_04 verified) |
| 0.35 | h1 at D10 + 3 supporting at D7, or h1 at D9 + 6+ supporting at D7 |
| 0.45 | Near-perfect alignment; top 5 factors all at D8+; rare |

Raise this when: you are seeing too many "right direction but factors disagree" trades — setups where one indicator is extreme but most others are neutral.

**Raise `MIN_MOM_CERTAINTY` (currently 0.25):**

This requires a clearer vol regime. At 0.25, any regime boundary is sufficient. Raising to 0.40 means we must be well into the high/low regime or near the boundary from inside normal — not just barely past the center.

| Value | Meaning |
|-------|---------|
| 0.20 | Slightly away from center of normal; most hours pass |
| 0.25 (current) | Clearly positioned in a regime (25% of the way toward a boundary) |
| 0.40 | Well positioned — in high/low regime or clearly near normal/high transition |
| 0.60 | Deep in the high or low regime; only strong vol reads |

Raise this when: trades are entering in the ambiguous middle of the normal ATR range and expected_pips estimates are proving unreliable.

**Reduce `MAX_SPREAD`:**

This is pair-specific. Reducing EUR_USD's limit from 2.5p to 1.5p eliminates trades during widened spread conditions (news, thin sessions). Appropriate if the strategy is being entered at a meaningful spread cost relative to expected_pips.

---

### 6.2 How to Loosen (Trade More, Accept More Uncertainty)

**Lower `MIN_DIRECTION_SCORE` toward 0.20:**

This allows the "weak non-block" zone (scores 0.20–0.25) to pass. These are bars where h1 and one other indicator are in moderate D7-D8 territory but little else. The downside: more marginal-direction trades where the actual directional move may not materialize over the relevant exit window.

Minimum safe value: 0.15 is the block threshold — lowering to 0.15 would make the direction score gate redundant with `is_actionable`.

**Lower `MIN_DIR_CERTAINTY` toward 0.20:**

0.20 is the certainty achieved when h1_ret_1bar is in D8 territory with 3 supporting factors at D7. This represents "readable signal" but below the noise floor confirmed by the sweep. Acceptable if live data shows a meaningful positive hit rate in the 0.20–0.30 certainty band.

**Lower `MIN_MOM_CERTAINTY` toward 0.15:**

This allows trades in the flat middle of the normal ATR range. The risk is that `expected_pips` estimates become unreliable and the trade has no particular vol edge or magnitude clarity. Acceptable in a thin-markets session (asia) where vol is structurally lower and certainty rarely reaches 0.25 even on otherwise clean setups.

**Relax spread limits by pair:**

Raise the MAX_SPREAD values or remove the spread gate entirely while the feed is not live. After the OANDA feed is wired, tighten these to empirically observed session-average spreads + 1–2 pip headroom.

---

### 6.3 Deriving New Floor Values After a Corpus Update

If the factor sweep is re-run on updated data (e.g., after adding 2026 bars or running a dm_11 sweep with new features):

1. **Identify the new `Σ_abs`** — sum of absolute spans for all features that pass the inclusion threshold. This sets all weights.

2. **Recompute the certainty calibration points** using the new weights:
   - Compute: what is the certainty when h1_ret_1bar alone is at D8 (norm≈0.70)?
     `cert_D8_alone = h1_weight × 0.70 × 1.0` (agreement = 1 for single factor)
   - Compute: what is the certainty when h1 at D9 + top 4 supporting at D7?
     `cert_D9_with_support = (h1_w×0.85 + Σ4_support_w×0.45) × (0.4 + 0.6×0.90)`
   
3. **Set `MIN_DIR_CERTAINTY`** = the cert_D9_with_support value rounded up to the nearest 0.05. This ensures the floor requires at least D9-quality on the primary indicator with real supporting signal.

4. **Recheck the ATR thresholds** — if the corpus extends into different vol regimes, re-export from the new factor_sweep.json. The momentum floors do not need recalculation unless the distribution of ATR has shifted.

5. **Verify floors against smoke tests** — run the 10-case playmaker smoke test suite after any change to confirm gates behave correctly at boundary values.

---

## 7. Summary of Constants

| Location | Constant | Value | Derivation |
|----------|----------|-------|------------|
| `direction.py` | `_TOTAL_ABS` | 93.37p | Sum of |span| across 24 dm_04 features |
| `direction.py` | `w_i` (per feature) | see table § 2.4 | span_i / 93.37 |
| `direction.py` | bias block zone | ±0.15 | Score threshold for long/short vs block |
| `direction.py` | label thresholds | ±0.70, ±0.30 | Decile-relative quartile boundaries |
| `direction.py` | active contribution threshold | 0.002 | Filters negligible contributions from agreement calc |
| `momentum.py` | `thr_low` | per bucket | atr_5m D2.hi_val (D2/D3 boundary) |
| `momentum.py` | `thr_high` | per bucket | atr_5m D8.hi_val (D8/D9 boundary) |
| `momentum.py` | `thr_ext` | per bucket | atr_5m D9.hi_val (D9/D10 boundary) |
| `momentum.py` | rvol clip | [0.6, 1.6] | Prevents extreme rvol from blowing up expected_pips |
| `momentum.py` | rvol boost threshold | 1.25 / 0.75 | Corroboration requires >25% deviation from normal |
| `momentum.py` | rvol boost factor | 1.20 | 20% certainty increase on agreement |
| `base.py` | is_actionable cert floor | 0.25 | Signal module's own sanity gate |
| `playmaker.py` | `MIN_DIRECTION_SCORE` | 0.25 | Above weak-directional zone; dm_04 derived |
| `playmaker.py` | `MIN_DIR_CERTAINTY` | 0.30 | D9 + 4 supporting at D7; dm_04 derived |
| `playmaker.py` | `MIN_MOM_CERTAINTY` | 0.25 | Clear regime positioning; dm_04 derived |
| `playmaker.py` | `MAX_OPEN_POSITIONS` | 3 | Portfolio risk limit |
| `playmaker.py` | MAX_SPREAD (EUR_USD) | 2.5p | Spread cap for this pair |
| `playmaker.py` | MAX_SPREAD (GBP_USD) | 3.0p | Spread cap for this pair |
| `playmaker.py` | MAX_SPREAD (USD_JPY) | 2.0p | Spread cap for this pair |
| `playmaker.py` | MAX_SPREAD (AUD_USD) | 2.5p | Spread cap for this pair |
| `playmaker.py` | MAX_SPREAD (USD_CAD) | 3.0p | Spread cap for this pair |
| `playmaker.py` | MAX_SPREAD (USD_CHF) | 3.0p | Spread cap for this pair |
| `playmaker.py` | MAX_SPREAD (EUR_JPY) | 3.5p | Spread cap for this pair |
| `playmaker.py` | MAX_SPREAD (AUD_JPY) | 4.0p | Spread cap for this pair |
