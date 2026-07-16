# [HISTORICAL] Strategy E — A Reproducible, Factor-Conditioned Intraday FX Strategy

> **Historical-document notice — read this first.**
>
> This is the **V3-era white paper, preserved verbatim** (June 7, 2026), imported into the public repo
> as a primary source. It represents a hypothesis the program **held at the time** and later **revised**;
> it is *not* current doctrine. Read it as an artifact of the strategy-portfolio era (**H2** in
> [`../../RESEARCH_PROGRAM.md`](../../RESEARCH_PROGRAM.md)), not as advice.
>
> - **What era:** V3, the "Matrix Era" — before the exit-bottleneck finding, before the cell-era
>   cutover, before the H1 look-ahead leak (B-078) was found, and before the five-family edge-hunt
>   falsifications. Its numbers are **sim** (an 8-year backtest) and predate the broker-truth /
>   forward-pip / leak-clean measurement standards.
> - **What it believed:** that a library of independent entry strategies, each gated by a
>   factor/alignment **cell** map, is the product — and that one strategy's conditional cell edge could
>   be isolated and independently reproduced. The paper is careful and honest for its era: it states a
>   *falsifiable, conditional* claim and publishes everything needed to check it.
> - **What later revised it:** the program subsequently found that **the strategy name carries no
>   weight — state does** (SHAP gave `strategy_id` zero weight, 2026-06-08), that most such "edges" are
>   survivorship-flattered or collinear (the 2026-06-16 factor verdict: survivors all AUD_JPY shorts,
>   31 factors measuring one phenomenon), and — decisively — that on this venue the market **does not
>   telegraph WHICH WAY** net of cost (0/144 signed-direction; the five edge-hunt falsifications). The
>   trend-pullback *family* the paper describes did survive out-of-sample in backtest, but did not clear
>   retail cost as a live, direction-predictive edge.
> - **Why it is preserved:** it is the cleanest written statement of the H2 thesis, it demonstrates the
>   program's early commitment to falsifiability and reproducibility, and it is honest primary-source
>   material for the historical record. The **cell-conditioning insight** it isolates (expectancy is not
>   uniform; it concentrates in particular alignment × factor states) *carried forward* — it is the seed
>   of the entire cell architecture — even though the "strategy" framing did not.
>
> One personal contact detail from the original has been replaced with `[contact redacted]` for the
> public repo. Everything else is the author's original text.

---

*The document below is the original, unaltered except for the redaction noted above.*

---

# A Reproducible, Factor-Conditioned Intraday FX Strategy
### Trend-Pullback Shorts on EUR/USD — one strategy, one pair, three cells, from an 8-year backtest

**By Carl B. Brock**
**June 07, 2026 · Version 1.0**

*For questions or partnership inquiries: [contact redacted]*

---

## Abstract

We operate a systematic intraday foreign-exchange system in which a library of independent entry strategies is filtered through a 14-factor *market signature* and a *trend-alignment score*. The unit of decision is not the strategy but the **cell** — a specific combination of alignment and factor state in which that strategy has historically been profitable.

This paper isolates **one** strategy (the 5th-ranked of our covered strategies by 8-year net contribution; the others are withheld), on **one** pair (EUR/USD), and examines **three** of its cells — out of 241 net-positive cells the strategy carries — over an ~8-year backtest (2019–2026; 21,648 trades for the base strategy). The central, reproducible finding: the raw strategy is only modestly profitable (+1.04 pips/trade), but its edge is strongly **conditional**. Holding the higher-timeframe alignment fixed, varying a single factor — the RSI zone at entry — moves expected value from **−0.93 to +3.60 pips per trade**, a 4.5-pip swing driven by one variable. The strong cell is profitable in 6 of 8 years and remains positive (+2.28 pips/trade) under a deliberately conservative volatility-scaled cost model. Every definition, parameter, and threshold required to replicate this independently is provided.

We make no claim of a large or risk-free edge. We make a falsifiable claim about a *conditional, reproducible structure*, and we provide everything needed to test it.

---

## 1. What this paper is — and is not

The production system runs many strategies across multiple currency pairs, each gated by a factor/alignment cell map that is tuned per strategy and per pair. **That larger apparatus is not the subject of this paper and is not disclosed here.**

This paper deliberately narrows to the smallest unit that is independently testable:

- **One strategy** (designated **"Strategy E"** in this paper — a trend-pullback short). Our other strategies are withheld.
- **One currency pair** (EUR/USD). The live universe is larger.
- **Three cells** of that strategy (it carries 241 net-positive cells over the backtest).

What is **not** described: the full strategy roster, the complete pair universe, the cell-selection/optimization layer, position sizing, portfolio construction, and the execution/risk machinery. Those are out of scope. The point of this paper is the **trading strategy and whether its conditional edge is real and reproducible** — nothing more.

**Where this sits.** By 8-year net contribution, Strategy E is the **5th-ranked** of our 21 covered strategies, and we examine **3 of its 241 net-positive cells**. We isolate it deliberately: strong enough to stand as a real, fully-specified worked example, while the leaders stay private. For scale — the four strategies ranked above it (undisclosed) reach **+25,000 to +56,000 net pips in their single strongest cell**, versus +20,300 for this one; this strategy's own dialed-in cells run at roughly a **62% win rate**. What we publish here is one strategy and three of its cells; the system behind it is materially larger.

---

## 2. System overview (high level)

```
   ┌──────────────────────────────────────────────────────────────┐
   │  SIGNAL GENERATORS                                            │
   │  A library of independent entry strategies (this paper        │
   │  examines ONE of them; the others are withheld).              │
   └───────────────┬──────────────────────────────────────────────┘
                   │  a candidate signal (pair, direction, time)
                   ▼
   ┌──────────────────────────────────────────────────────────────┐
   │  MARKET SIGNATURE                                             │
   │  At the signal bar, compute a 14-factor signature            │
   │  (volatility, momentum, band position, trend alignment, …)    │
   │  + a 0–4 higher-timeframe ALIGNMENT score.                    │
   └───────────────┬──────────────────────────────────────────────┘
                   │  signal + signature
                   ▼
   ┌──────────────────────────────────────────────────────────────┐
   │  CELL GATE                                                   │
   │  Trade only when the (alignment × factor) CELL has a          │
   │  historically positive expectancy. Otherwise, stand aside.    │
   └───────────────┬──────────────────────────────────────────────┘
                   │  approved trades
                   ▼
   ┌──────────────────────────────────────────────────────────────┐
   │  EXECUTION  →  MANAGED EXIT  (details withheld)              │
   └──────────────────────────────────────────────────────────────┘
```

*This diagram is intentionally high-level. The actual production architecture — its full mechanics, additional layers, and tuning — is **not released here and is not the point of this article.** The trading strategy itself is.*

For scale and honesty about context: the studied set contains **21 "covered" strategies**, complemented by an additional family of structure-based strategies (~30% of live signals) under separate study; this paper uses **4 major pairs** for the backtest, while the live universe is broader. We isolate one strategy on one pair precisely so that the result is small enough to be checked by hand.

---

## 3. The strategy: Strategy E — Trend-Pullback Short

**Concept.** In an established intraday downtrend (price trading below the 1-hour EMA-20), short *shallow* pullbacks that lift back toward the moving average and then turn down again. It is a "sell the bounce in a downtrend" strategy. It is deliberately a *calm-regime* strategy — it does not require, and in fact does not prefer, high volatility.

**Timeframe.** Signals are evaluated on **5-minute (M5)** bars. Two indicators are read from the **1-hour (H1)** series.

**Entry rules (short only).** On each completed M5 bar, enter a short at the bar's close if **all** of the following hold:

1. `close < EMA20` — price is below the 1-hour 20-period EMA (downtrend context).
2. `(EMA20 − close) / pip ≤ 0.4 × ATR_pips` — the pullback is **shallow**: price is within 0.4 ATR of the EMA (a bounce *into* resistance, not an extended drop).
3. `35 ≤ RSI ≤ 60` — the 1-hour 14-period RSI is in the lower/middle band (not oversold, not strong).
4. The current M5 bar is **bearish** (`close < open`) — the bounce is turning back down.

**Stop reference.** `struct_ref` = the highest high of the last 5 M5 bars (the local swing high the short is fading).

There is no long variant in this study.

### Indicator definitions (so the above is unambiguous)

| Symbol | Definition | Period | Series |
|---|---|---|---|
| `EMA20` | Exponential moving average of close | 20 | H1 |
| `RSI` | Relative Strength Index (Wilder smoothing) | 14 | H1 |
| `ATR_pips` | Average True Range, expressed in pips (= ATR_price ÷ pip size) | 14 | intraday |
| `pip` | 0.0001 for EUR/USD (0.01 for JPY pairs) | — | — |

---

## 4. Entry, stop and exit settings

- **Entry:** market order at the close of the signal M5 bar.
- **Initial stop distance (pips):**
  `stop = max( |entry − struct_ref| / pip + 0.25 × ATR_pips , max(3 × spread_pips, 3) )`
  i.e. the distance from entry to the swing high, plus a quarter-ATR buffer, floored at 3 pips (or 3× the spread, whichever is larger).
- **Initial stop price:** `entry + stop` (short).
- **Initial target:** `entry − R × stop`, with **R = 1.5**.
- **Realized exit (primary result):** stops/targets are then re-simulated bar-by-bar under a staged "ladder" exit (partial profit-taking with a break-even-plus lock and a time-based green-harvest). The ladder is our live exit model; for transparency we report results under three exit models in §6.4. **The ladder does not use future information** — every decision is made on completed bars.

---

## 5. The market signature and the "cell"

At the signal bar we compute a 14-factor signature. This paper uses two of those factors.

**Alignment score (0–4).** The count of how many of four higher-timeframe trend gauges agree with the trade direction:

```
align = [20-period HTF bias is down]
      + [60-period HTF bias is down]
      + [1-hour trend is down]
      + [4-hour trend is down]
```

(For a short, "agree" = down.) `align = 3` therefore means three of the four agree.

**RSI zone (the factor we vary).** The same H1 RSI(14), binned into classical zones:

| Code | RSI range | label |
|---|---|---|
| RSI2 | 30 ≤ RSI < 40 | weak |
| RSI3 | 40 ≤ RSI < 50 | lower-neutral |
| RSI4 | 50 ≤ RSI < 60 | upper-neutral |

**A cell** is the pair `(alignment level, factor bucket)`. Our claim is that the strategy's expectancy is not uniform — it is concentrated in particular cells. We test this with a controlled comparison: **hold alignment fixed at 3, and vary the RSI zone.**

---

## 6. Results (EUR/USD, M5, 2019-07-01 → 2026-05-25)

### 6.1 Base strategy

| metric | value |
|---|---|
| Trades | 21,648 |
| Win rate | 51.6% |
| Avg win / avg loss | +11.4 / −10.0 pips |
| **Expected value** | **+1.035 pips/trade** |
| Net (8 years) | +22,410 pips |
| Positive years | **8 of 8** (range +0.36 to +2.05 pips/trade) |

The raw strategy is positive but modest, and — importantly — positive in **every** calendar year of the sample, including 2020 and 2022.

### 6.2 The three cells (alignment = 3; RSI zone varied)

| Cell | RSI at entry | Trades | Win rate | EV / trade | Net pips (8 yr) |
|---|---|---|---|---|---|
| align=3, **RSI2** | 30–40 | 787 | 42.9% | **−0.93** | −728 |
| align=3, **RSI3** | 40–50 | 2,556 | 49.2% | **+0.59** | +1,515 |
| align=3, **RSI4** | 50–60 | 1,064 | 62.2% | **+3.60** | +3,833 |

A single factor, holding alignment constant, moves expectancy monotonically from **−0.93 to +3.60 pips/trade.**

**Mechanism (why this is sensible, not a fluke).** Strategy E shorts a bounce in a downtrend. When the H1 RSI has lifted into the *upper-neutral* zone (50–60, RSI4), the bounce has retraced higher and later — the short is sold into more meaningful resistance, and price more reliably resumes lower (62% win rate). When RSI is *weak* (30–40, RSI2), price is already depressed; the short chases a move that is more likely to mean-revert against it (43% win rate). The edge is in *where in the bounce* the short is taken — exactly the kind of structure a factor signature is meant to capture.

### 6.3 Year-by-year robustness of the strong cell (align=3, RSI4)

| 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|
| −3.5 (n50) | +3.7 | +3.1 | +5.4 | +4.7 | +2.8 | +4.2 | −0.1 (n46) |

Positive in **6 of 8 years**. The two non-positive years are the partial endpoints with the smallest samples (2019 begins mid-year; 2026 is truncated at May). The cell is not the product of a single regime.

**Supporting — alignment also amplifies.** Holding RSI4 fixed and varying alignment, EV rises monotonically: align0 +0.87 → align1 +3.15 → align2 +3.09 → align3 +3.60 → align4 +4.25 pips/trade. Alignment and RSI stack.

### 6.4 Cost-model sensitivity (strong cell)

A frequent failure mode for intraday FX backtests is under-charging for transaction costs. We re-priced the strong cell under three exit/cost models:

| Exit / cost model | EV / trade |
|---|---|
| Ladder, realistic spread + 0.5 pip slippage (primary) | +3.60 |
| Fixed stop/target, realistic spread | +3.23 |
| Ladder, **volatility-scaled spread** (deliberately harsh) | **+2.28** |

The cell remains clearly positive even when spreads are penalized for widening with volatility. (We note this cell is a *calm-regime, low-ATR* cell, which is precisely why it is robust to the volatility-cost penalty — a strategy whose edge concentrated in high-volatility states would be far more exposed here.)

---

## 7. Reproducibility checklist

To replicate independently, you need only the following, all specified above:

- **Data:** EUR/USD OHLC, 5-minute bars, 2019-07-01 → 2026-05-25, plus the 1-hour series for EMA20/RSI. Any reputable feed.
- **Indicators:** EMA-20 (H1 close), RSI-14 Wilder (H1 close), ATR-14 in pips. (§3)
- **Entry rule:** the four conditions in §3. **Short only.**
- **Stop/target:** §4 (structural stop + 0.25-ATR buffer, R = 1.5).
- **Costs:** realistic bid/ask spread + 0.5 pip slippage. (Results under three exit models in §6.4.)
- **Alignment score:** §5 (count of four HTF gauges agreeing with the short).
- **RSI bucket boundaries:** RSI2 = [30,40), RSI3 = [40,50), RSI4 = [50,60). (§5)
- **Cells:** align = 3, with the three RSI buckets. (§6.2)
- **No look-ahead:** all features and exit decisions use completed bars only.

A correct re-implementation should reproduce the base-strategy expectancy (≈ +1.0 pip/trade, ~21–22k trades) and the monotonic cell gradient (≈ −0.9 / +0.6 / +3.6 pips/trade) within sampling tolerance.

---

## 8. Limitations and honest disclosures

1. **The base edge is small, and the win rate is near a coin flip.** With ~1:1 reward/risk and ~52% hit rate, per-trade expectancy is a fraction of a pip to a few pips. This is not a high-Sharpe anomaly; it is a modest, conditional structure.
2. **The edge is in the cell, not the raw signal.** The strategy alone is marginal. The result is a statement about *conditioning*, not about the strategy in isolation.
3. **Backtest costs are modeled, not live fills.** We report three cost models, including a harsh one, but real slippage, fills, and spread dynamics can differ. Forward (live) validation is the only conclusive test.
4. **Multiple comparisons.** A 14-factor signature creates many candidate cells; some will look good by chance. We mitigate with (a) per-year robustness, (b) a single pre-specified controlled comparison, and (c) a mechanistically sensible explanation — but independent replication on out-of-sample data is the real arbiter, which is why this paper exists.
5. **This is one cell of a larger system.** Aggregate live performance depends on the full strategy/pair/cell portfolio, position sizing, and risk management — none of which is claimed or shown here.

---

## 9. Closing note

What we publish here is intentionally a sliver: one strategy, one pair, three cells. The broader program — many strategies, multiple pairs, each dialed in across numerous factors and alignment states — is substantially larger and is not the subject of this article. We share this slice because it is small enough to be checked, falsifiable, and fully specified: **a reader can take §3–§5, run their own backtest, and confirm or refute the numbers in §6.** That is the standard we hold it to.

*Numbers in this paper are from a single 8-year historical backtest and are not a representation of live trading results.*

---

## Appendix A — Reference implementation (entry logic)

A self-contained, platform-agnostic version of the Strategy E entry, using only the standard indicators defined in §3. It depends on no proprietary code. Evaluated once per completed 5-minute (M5) bar.

```python
# Inputs (all standard — see §3 for definitions):
#   ema20       : EMA(20) of the H1 close             (price)
#   rsi         : RSI(14, Wilder) of the H1 close      (0..100)
#   atr_pips    : ATR(14) expressed in pips
#   m5          : recent M5 bars; m5[-1] is the last COMPLETED bar
#   pip         : 0.0001 for EUR/USD
#   spread_pips : current bid/ask spread, in pips

def strategy_E_short_entry(ema20, rsi, atr_pips, m5, pip, spread_pips):
    close = m5[-1].close

    # (1) downtrend context — price below the H1 EMA20
    if close >= ema20:
        return None
    # (2) shallow pullback — price within 0.4 ATR of the EMA
    if (ema20 - close) / pip > 0.4 * atr_pips:
        return None
    # (3) RSI in the lower/middle band
    if rsi < 35 or rsi > 60:
        return None
    # (4) signal bar turning back down (bearish)
    if m5[-1].close >= m5[-1].open:
        return None

    # entry, stop, target
    entry      = close
    struct_ref = max(b.high for b in m5[-5:])             # local swing high
    stop_dist  = max(abs(entry - struct_ref) / pip + 0.25 * atr_pips,
                     max(3 * spread_pips, 3.0))           # pips
    return {
        "side":   "short",
        "entry":  entry,
        "stop":   entry + stop_dist * pip,
        "target": entry - 1.5 * stop_dist * pip,          # R = 1.5
    }
```

**Cell assignment (for §6).** Each generated signal is tagged with (a) its **alignment score** — the count of the four higher-timeframe gauges agreeing with the short (§5) — and (b) its **RSI bucket** — RSI2 = [30,40), RSI3 = [40,50), RSI4 = [50,60). The cells in §6.2 are the subsets `alignment == 3` for each RSI bucket.

**Realized P&L.** The function above returns the *initial* stop and target. The pip results reported in §6 re-simulate the exit bar-by-bar under the staged ladder described in §4; §6.4 also reports the simpler fixed stop/target model for comparison. No exit decision uses future bars.

---

## Editor's afterword (2026-07, added at import)

Three of this paper's own instincts were later *vindicated* by the program even as its framing was
revised: (1) the **cell** as the true unit of decision became the entire V5 architecture; (2) its
insistence on **cost-model sensitivity** and forward validation as "the only conclusive test"
anticipated the cost work that found ~83% of a later loss window was spread; and (3) its **honesty about
a near-coin-flip base edge** was exactly right — the program went on to prove, five falsifications
deep, that on this venue the base direction edge does *not* clear cost. Where the paper was wrong was in
implying the conditional cell edge would survive as a *live, direction-predictive* strategy; the
survivorship and collinearity audits (see [`RETIRED_STRATEGIES.md`](RETIRED_STRATEGIES.md) and
[`../PAPER_edge_hunt_falsifications_2026-07-14.md`](../PAPER_edge_hunt_falsifications_2026-07-14.md))
showed most such cell edges are flattered by the trades that survived to be measured. Preserved as an
honest, careful document that reached the right method and the wrong conclusion — which is most of what
research is.
