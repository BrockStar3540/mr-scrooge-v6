# The Mr. Scrooge Research Program

**A five-version investigation into whether a retail-accessible price edge exists net of cost.**

*Monograph front-matter and synthesis. Companion to [`SCROOGE_HISTORY.md`](SCROOGE_HISTORY.md)
(the narrative log), [`BOOK_OF_BUGS.md`](BOOK_OF_BUGS.md) (the defect record), the
[`papers/`](papers/) formalizations, and [`../research/README.md`](../research/README.md)
(the reading-order index and truth hierarchy). Where those tell the story chronologically, this
document organizes it as a research program: the question, the hypotheses it held, how each was
tested, and what the tests returned.*

---

## Abstract

Mr. Scrooge is a systematic intraday foreign-exchange bot, built and rebuilt across six versions
between February and July 2026, trading eight OANDA majors on a single **practice** account
(paper money — "the live trader" means the running program, never funded capital). Its purpose
was never a product; it was to answer one falsifiable question: **does a price-predictive edge a
retail trader can actually reach survive its own transaction cost?** Over five months the program
held and tested six major hypotheses — indicator-direction prediction, strategy portfolios, ML
strategy-authoring, cell-local timing edges, tight-stop MAE dial-in, and a wide-stop rare-red
thesis — across corpora up to sixteen years and 1.6 million trades. The direction-prediction
family was falsified repeatedly and independently: on the accessible venue (OANDA majors,
2010–2026, at the frequencies retail cost permits) **the market telegraphs WHEN a move comes and
HOW FAR it travels, but not WHICH WAY.** The single most consequential result of the program is
not a strategy but a **methodology**: the discovery, one measurement standard at a time, of how
much of an apparent edge is manufactured by the way it is measured — journal instead of broker
fills, realized P/L instead of forward price, in-sample instead of walk-forward, a look-ahead data
leak, and survivorship in the stop-tuning itself. Every headline number in this program is scoped
to how it was measured — **sim**, **live** (bot journal/intent), or **broker** (OANDA fills, the
only trade-truth) — and those scopes are never interchangeable. The one edge that appears to
survive honest scrutiny is thin, low-Sharpe, exit-geometry-shaped rather than direction-shaped,
and is at time of writing an **open forward experiment**, not a claimed result.

---

## 1. Motivation and research question

The program began not with a strategy but with skepticism. In mid-2025 the operator (Carl B.
Brock) was evaluating off-the-shelf "trading bots" that advertised guaranteed profits — including
one, Galileo FX, that the pre-project record shows him vetting and rejecting as a probable scam
(*OpenAI session, 2025-08-07, "Trading Bot Interface Design"*). The decision was to build an honest
one instead: fee-aware, disciplined, and above all **measured** — a machine that "counts every
pip," which is where the name comes from.

The scoping conversation that opened the trading line (*OpenAI session, 2026-02-14, "Building a
forex trading agent with OANDA API"*) already contains the program's spine, held as design intent
before a single trade:

- a **three-layer architecture** — market filters → signal engine → risk/execution;
- a **fee-aware minimum-move gate**: `MinMove = SpreadCost + Commission + SlippageBuffer`, skip any
  trade whose expected profit does not clear it ("that alone will eliminate most losing fake-edge
  trades");
- a **risk dial** (a single 0.1–1.0 aggression slider);
- and hard circuit breakers (max daily loss, max daily trades, consecutive-loss cooldown, news
  blackout).

The research question this apparatus was built to answer can be stated as a null hypothesis:

> **H₀:** On a retail-accessible venue (OANDA spot FX majors), there exists no entry rule, strategy,
> or model whose expected price move — net of spread, slippage, and financing — is reliably positive
> out-of-sample.

The five months that follow are the attempt to reject H₀. The honest summary of the program is that
**H₀ was not rejected for the direction-prediction family**, and that the one place it may fail —
excursion-aware exit geometry on cells with a persistent side — is still under test.

---

## 2. The hypothesis ledger

Each hypothesis is stated as it was actually held at the time, then given its test, data window,
result (scoped sim / live / broker), verdict, and where it is documented. Verdicts:
**FALSIFIED** (the evidence rejected it), **REVISED** (survived only in a narrower form),
**OPEN** (under test).

---

### H1 — Indicator-direction prediction

**Statement (as held, V3 matrix era → V4/V5 direction detector, Apr–Jul 2026).** A market
*signature* — a vector of indicators (RSI, ADX, Bollinger position, ATR, higher-timeframe
alignment, momentum) computed at the signal bar — predicts **which way** the next move goes, and
gating entries on the favorable region of that signature turns a coin-flip into an edge. The
strongest single form: the V5 direction engine used `h1_ret_1bar` (one-bar momentum) as its top
factor and trend-followed it.

**Test method.** (a) Factor-lift rig: 37 factors × 128 cells = 4,736 cell×factor lift tests plus a
48,421-row per-value-band decomposition, with adversarial validation (permutation null, BH-FDR at
5%, rolling 6-month OOS stability), walk-forward 2019-22 IN / 2023-26 OOS. (b) Direction detector:
per-(pair × session × direction) isotonic-calibrated boosters, walk-forward gated. (c) A
truth-matrix test of 24 cells × 6 features for signed-direction predictability, overlap-thinned.
(d) The edge-hunt single-pair trend test: 8 majors, 7.5yr, 32 regime gates.

**Data / window.** 8 pairs; 885k–290k-row corpora; 2019–2026; broker-anchored truth matrix
(r = 0.84–0.90).

**Result.**
- Factor verdict (sim, 2026-06-16): the surviving factors were **collinear** — 31 different factors
  "survived" in the *same* 2–3 cells (all AUD_JPY shorts), i.e. one phenomenon measured 31 ways, not
  31 edges. No new cells emerged; the library "cannot be expanded from this corpus."
- Signed direction from features (broker-anchored truth matrix, current truth, 2026-07-05):
  **0 of 144 robust relationships.** Nothing in the feature set predicted which way.
- Single-pair daily trend (sim, 16yr, 2026-07-14): ~0 gross edge at every 1h→4d horizon, hit rate
  pinned 49–50%; **0 of 32 regime gates** net-positive with year-consistency.

**Verdict — FALSIFIED (as a general edge).** The "how far / when" half of the signature is real and
load-bearing (see §3); the "which way" half is not. This became the program's one non-negotiable
law: **WHEN and HOW FAR, not WHICH WAY.**

**Documented.** [`papers/historical/RETIRED_STRATEGIES.md`](papers/historical/RETIRED_STRATEGIES.md);
`FACTOR_RESEARCH_VERDICT.md` (archive `docs-harvest/v4-repo-docs/`);
[`PAPER_cost_aware_exit_classes_2026-07-05.md`](PAPER_cost_aware_exit_classes_2026-07-05.md) §4;
[`papers/PAPER_edge_hunt_falsifications_2026-07-14.md`](papers/PAPER_edge_hunt_falsifications_2026-07-14.md)
Finding 2.

---

### H2 — Strategy portfolios

**Statement (as held, V1 box era → V3/V4, Feb–Jun 2026).** A **library of independent entry
strategies** — Darvas-box liquidity plays, trend-pullback fades, breakout-retests, compression
breakouts, mean-reversion snapbacks — is the product; each strategy carries its own edge and the
portfolio diversifies across them. The canonical worked example is **Strategy E**, a trend-pullback
short on EUR/USD (see [`papers/historical/StrategyE_EURUSD_whitepaper_2026-06.md`](papers/historical/StrategyE_EURUSD_whitepaper_2026-06.md)).

**Test method.** 8-year corpus scoring under the live exit; per-bucket K=2 refits of each textbook
trigger; the walk-forward gate applied to 23,211 AVOID conjunctions; SHAP attribution of
`strategy_id`; the Strategy E controlled comparison (hold alignment fixed, vary one factor).

**Data / window.** 1.6M-trade canonical corpus, 8 pairs, 2019–2026.

**Result.**
- **The strategy name does not matter; state does** (sim, "Session Findings," 2026-06-08): two
  independent models (XGBoost, LightGBM) agreed r = 0.96 that expected value is driven by
  alignment × volatility state, and SHAP gave `strategy_id` **zero weight**.
- Strategy E (sim, 8yr backtest): the raw strategy is only **+1.04 pips/trade**; holding alignment
  fixed and varying the RSI zone moves expectancy monotonically **−0.93 → +3.60 pips/trade**. The
  edge is in the *cell*, not the strategy.
- Per-bucket refit: of 7 textbook strategies, 3 had zero surviving buckets (genuinely dead); 4
  survived only inside specific (pair × session × direction) cells.

**Verdict — REVISED → the CELL replaced the strategy.** Strategies are not independent edges; they
are triggers whose expectancy is conditional on state. The unit of decision became the cell (H4).
Standalone, most strategies were marginal or survivorship-flattered.

**Documented.** [`papers/historical/StrategyE_EURUSD_whitepaper_2026-06.md`](papers/historical/StrategyE_EURUSD_whitepaper_2026-06.md);
[`papers/historical/RETIRED_STRATEGIES.md`](papers/historical/RETIRED_STRATEGIES.md);
[`SCROOGE_HISTORY.md`](SCROOGE_HISTORY.md) V1/V3.

---

### H3 — ML judging, then ML authoring

**Statement (as held, V4, Jun 2026).** First: an ML **judge** (the BUCKET21 utility brain) can
price the expected utility of a human strategy's firing and gate on it. Then, the franchise turn:
the ML can **author** its own strategies — mine an unbiased all-bars corpus, rank indicators and
value-levels, combine the strong ones into entry rules, and prove them out-of-sample before they
trade.

**Test method.** Discovery on 2019–2022 only; validation on **unseen 2023–2026**; re-run through the
live featurizer; then the walk-forward gate as the activation primitive.

**Data / window.** 674k-row unbiased all-bars corpus, 7 years, both directions.

**Result (all sim).**
- Discovery: 51 of 52 authored strategies stayed positive on unseen years — **23,095 fires · 66% win
  · +8.42 pips** vs a +1.4p all-bars base.
- Live-featurizer replay: 891 fires · 84% win · +14.85 pips; brain-gated cream +31.8p.
- But the factor verdict (H1) showed the discovered edge was **concentrated and collinear** (AUD_JPY
  shorts), not expandable; and the judge itself failed structurally — an asymmetric AVOID map ran a
  **$626/day bleed for 14 days** (sim/live) before the silence forced the diagnosis (see
  [`BOOK_OF_BUGS.md`](BOOK_OF_BUGS.md), the V4 asymmetric-map arc).

**Verdict — REVISED.** ML authoring works as a *method* and produced a real out-of-sample backtest
edge — but that edge was one narrow phenomenon, and the whole `ml_tp_*` family was retired at the
V5 cell-era cutover. What carried forward is the *discipline* (walk-forward gate as the activation
primitive), not the strategies.

**Documented.** `RESEARCH_METHODOLOGY.md`, `BACKTEST_RESULTS.md` (archive `docs-harvest/v4-repo-docs/`);
[`SCROOGE_HISTORY.md`](SCROOGE_HISTORY.md) V4.

---

### H4 — Cell-local timing edges

**Statement (as held, V5, Jun–Jul 2026).** The strategy is a fiction; the **cell** — a specific
(pair × session × direction) — is the real unit, and some cells have a **persistent tradeable
side**. The flagship claim: **NY is a momentum-FADE session** — where the V5 engine trend-followed
one-bar momentum, the next 60 minutes tends to reverse.

**Test method.** Broker forward-pip (OANDA API, not the journal); 8yr walk-forward momentum; ALIGN
resolution; four independent confirmations required before a cell claim.

**Data / window.** 120 broker trades + 8yr corpus; walk-forward train <2024 / test ≥2024.

**Result.**
- **NY-fade confirmed four ways** (broker P/L; broker 1H forward pip; 8yr walk-forward, 8/8 pairs
  both windows; ALIGN 14/16 cells) — direction VALID. Unification: momentum *without* higher-timeframe
  backing = exhaustion/fade; *with* backing = continuation.
- ~5 broker-confirmed winner cells out of 48 (e.g. USD_CAD/ny/long +6.61p, EUR_USD/london/short
  +6.31p; broker forward pip, n ≈ 7).

**Verdict — REVISED / OPEN.** The NY-fade *direction* stands on clean anchors. But (a) winner-cell
magnitudes were later found to sit on H1-leak parquets (upper bounds — see §3), (b) winner-cell N was
5–9 trades, and (c) the per-cell *tuning* built on top of this was itself survivorship-biased (H5).
The cell as a unit survives; the confidence in any single cell's magnitude does not.

**Documented.** [`papers/PAPER_methodology_overhaul_2026-06-21.md`](papers/PAPER_methodology_overhaul_2026-06-21.md);
[`../research/README.md`](../research/README.md) (VALID LEGACY tier).

---

### H5 — Tight-stop MAE dial-in

**Statement (as held, the "dial-in weeks," Jul 6–14 2026).** For a cell with a persistent side, set
the stop loss to the **75th percentile of the winners' Maximum Adverse Excursion** — tight enough to
cut losers early, loose enough to let winners breathe. Combined with quintile MAE/MFE separators,
this "dials in" each cell to peak expectancy.

**Test method.** The wide-SL sweep (SL never previously tried > 20p); a 29-cell scan at fixed SL40;
and a **head-to-head portfolio sim** on an identical 6-cell shortlist, current-tight vs SL40, both
runs on the same cells.

**Data / window.** 8yr/16yr leak-safe corpora; 6-cell risk-normalized portfolio (1%/trade, cap 3,
compounding).

**Result (sim, head-to-head).**
- **CURRENT (tight stops): −93%/yr, Sharpe −3.54 — account → zero every year.**
- **WIDE (SL40): +25.4%/yr, Sharpe 1.05, maxDD −40%, positive all 8 years.**
- **The methodological bombshell:** the winners'-MAE-p75 rule was **survivorship-biased** — MAE was
  measured only on trades that *survived to win*, blind to the trades a tight stop killed that would
  have recovered. The tell across 24 cells was `asym_train = 0.0`: per-trade MFE≫MAE is *realized
  direction*, not a selectable cell property.

**Verdict — FALSIFIED / REVERSED.** The dial-in doctrine was not merely unhelpful; it was actively
harmful — converting a thin-but-real edge into losses. This retroactively explains the constant
re-dialing and book-flips of the prior weeks: they were fitting realized-direction noise in-sample.

**Documented.** [`papers/PAPER_edge_hunt_falsifications_2026-07-14.md`](papers/PAPER_edge_hunt_falsifications_2026-07-14.md)
(THE TURN + CAPSTONE); [`../research/README.md`](../research/README.md) validation-protocol rule 7.

---

### H6 — The wide-stop / rare-red thesis (open)

**Statement (as held now, Brock, Jul 14–15 2026).** Risk a book of many small greens plus the
occasional big green against a **wide, range-sized stop** (40 quiet / 50 mid / 60 loud, sized to the
per-(pair × session) session swing). Prove a trade green (ratchet trigger +7.5 → lock +5), let
runners express, and accept that reds are **rare and large** but carried by the green skew. Never
lock a stop within a spread of entry (a "flat" price is already −1 spread).

**Test method.** The capstone portfolio sim (above) plus a range-sized variant; deployed to all 29
cells 2026-07-14 as a live forward experiment. **The decisive test is still owed:** walk-forward cell
selection (train 2019–22 / test 2023–26) + a slippage haircut.

**Result (sim, 6-cell portfolio).** Range-sized SL: Sharpe 1.00, maxDD −31%, rarest reds (14%), most
big runners (3% > 20p, 1% > 40p) — Brock's rare-red/runner skew confirmed in sim. **But** the
absolute level is inflated by cell selection (6 best), 2026 partially in-sample, and no
slippage/financing (wide stops slip); honest haircut ≈ **Sharpe 0.6–0.8** — a low-Sharpe grind, not a
jackpot.

**Verdict — OPEN.** This is the current live book on the practice account. What would falsify it: the
walk-forward + slippage test failing to clear ~0.7 Sharpe; or the forward tape showing avg-red not
contained, wide-stop slippage eating the runners, or the green skew not materializing at n ≥ 20 per
cell. **Live stops were not changed on the sim alone** beyond the deploy itself, and no cell is
promoted until the owed test passes.

**Documented.** [`papers/PAPER_edge_hunt_falsifications_2026-07-14.md`](papers/PAPER_edge_hunt_falsifications_2026-07-14.md)
(CAPSTONE + range-sized deploy); [`SCROOGE_HISTORY.md`](SCROOGE_HISTORY.md) V5 Arcs 8–10;
[`../research/README.md`](../research/README.md) §5 (active frontier).

---

### Ancillary hypotheses (tested and closed inside the edge hunt)

The 2026-07-14 edge hunt tested five structurally distinct price-edge families to a common wall;
H1 and H5 above are two of them. The remaining three, each falsified on 16yr OOS corpora (sim):

| # | Hypothesis (as held) | Result | Verdict |
|---|---|---|---|
| A | **M5 scalping** clears cost if picky + fee-aware (the V0/V1 genesis thesis) | edge +0.8–1.3p ≈ toll ~1.0–1.5p spread; cost is 19% of the 1h move, 1.8% at 4d | FALSIFIED (structural: edge = cost) |
| B | **Diversified retail TSM** (real CTA) is an edge on the OANDA universe | 47 instruments, vol-targeted: **gross Sharpe 0.08, net −0.22**; engine validated (2022 captures correct) | FALSIFIED (venue lacks breadth/cheap execution) |
| C | **Symmetric dual-ratchet straddle** (both sides, no direction) captures the winner | net −0.9 to −2.6p/straddle; **0/8 years positive, every pair** | FALSIFIED (a coin-flip pair guarantees you hold the −12 loser) |

The unifying mechanism across all five: **retail OANDA-majors spread > any price-predictable edge in
the data.** This is method-scoped — it does not say "no edge exists anywhere," it says "no
price-prediction edge clears retail cost for us on this venue, 2010–2026, at these frequencies."

---

## 3. Methodology evolution — the real finding of the program

The program's most durable output is not any strategy but the **succession of measurement standards**,
each installed after a specific way of fooling ourselves was caught. Stated as the program learned
them:

1. **Journal → broker truth (2026-06-20/21).** The bot's journal records its *intent* (SIGNAL /
   ENTERED markers); only the broker has actual fills, manual closes, spread cost, and realized P/L.
   The 44-trade journal matrix had **missed 70 of the real 120 trades** (B-084). Standing law: pull
   from the OANDA API, not the logs.

2. **Realized P/L → forward pip for entries (2026-06-21).** Exit logic changes constantly and had
   flipped ~32% of trades from their actual market direction. To judge an *entry*, measure the 1H
   forward price move, not the realized P/L (which conflates entry and exit). Include manual-closed
   trades (manual close affects realized P/L only, never the forward direction).

3. **In-sample → walk-forward (2026-06-15/16).** In-sample performance is not evidence. The
   walk-forward gate — anchored train-past / test-future — became the *activation primitive*: nothing
   wires live until it earns it on unseen forward data. Run against 23,211 AVOID conjunctions, **65%
   failed**; the dominant source (`K2_avoid_enumeration`) was 80% killed as in-sample-fitted overfit.

4. **The H1 look-ahead leak repair (2026-07-03, B-078).** Research parquets had joined H1 features on
   open-time, injecting up to **55 minutes of future bar** into every H1 feature. **Every headline
   number whose primary evidence came from pre-fix H1 parquets is an upper bound** (some inflated
   8–15×). The dividing line is 2026-07-03; clean anchors are broker measurements, M5 features, and
   post-fix corpus. This single bug re-based a large fraction of the prior research — and the fact
   that the *directions* (NY-fade, per-cell disagreement) survived while the *magnitudes* did not is
   itself the lesson: separate mechanism from magnitude.

5. **The survivorship-bias discovery (2026-07-14).** The winners'-MAE-p75 stop rule (H5) measured MAE
   only on trades that survived to win — structurally blind to trades a tight stop killed that would
   have recovered. This is survivorship bias inside the *tuning method itself*, and it had been
   quietly converting a thin edge into losses. Validate stop widths against the **full firing
   population**, not the winners.

6. **Scope every number: sim / live / broker.** These three are not interchangeable and are never
   silently upgraded. A sim head-to-head can be trusted for *direction* (wide beats tight on identical
   cells) while its *absolute level* is not (selection, in-sample, no-slippage inflators named). A
   config is judged only on its own trades since it deployed — never on a blended multi-config
   aggregate.

The throughline: **an apparent edge is, until proven otherwise, an artifact of how it was measured.**
Most of the program's "edges" dissolved not because the market changed but because the measurement
got honest.

---

## 4. Experiment ledger

Every major experiment, its question, method, sample, result, and where the evidence lives. Scope
tags: **sim** (backtest), **live** (bot journal/intent), **broker** (OANDA fills). Numbers before
2026-07-03 that rest on H1 features are upper bounds (§3.4).

| Date | Question | Method | n / window | Result (scope) | Where |
|---|---|---|---|---|---|
| 2026-03-01 | Does the V1 live scalper self-limit? | live incident review | 20 trades, 3h10m | 20 identical USD/JPY stop-outs, no loss-memory (live) | Book of Bugs legacy §; genesis note |
| 2026-06-08 | Does the strategy identity carry the edge? | XGB+LGBM SHAP on 1.6M corpus | 8yr, 8 pairs | strategy_id **zero weight**; EV = align×vol−spread (sim) | HISTORY V3 |
| 2026-06-11 | Which (strategy×align×factor×bucket) cells survive OOS? | train→OOS t-stats + direction-robust | ~9,000 combos | 127 cells → 157 direction-keyed sides (sim) | HISTORY V3 |
| 2026-06-13 | Are the strategies bad, or the exit? | forward-path MFE vs realized | 1.1M trades | 70% ran +20, 57% +30, max 907; exit capped <20 (sim) | Exit-bottleneck (B-076) |
| 2026-06-13 | Which exit captures the tail? | 3-way bake-off, same entries | 8yr M5 | ratchet **+3.28p** vs ladder ~+1–2 vs harvest +0.75 (sim) | HISTORY V4 |
| 2026-06-14 | Can the ML author strategies OOS? | discover 2019-22 / test 2023-26 | 674k rows | 51/52 survived, +8.42p unseen (sim) | `BACKTEST_RESULTS.md` |
| 2026-06-16 | Which old factors survive honest testing? | 4,736 cell×factor lift + adversarial | 885k rows | survivors all AUD_JPY shorts, 31 collinear (sim) | `FACTOR_RESEARCH_VERDICT.md` |
| 2026-06-21 | Is NY a fade session? | broker fwd-pip + 8yr walk-forward | 120 broker + 8yr | NY fades, 8/8 pairs, 4-way confirmed (broker+sim) | Methodology-overhaul paper |
| 2026-07-03 | How much of the loss is cost? | broker transaction export | 963 fills, 5wk | spread $18.6k vs −$22.5k net = **~83%** cost (broker) | Cost-classes paper |
| 2026-07-05 | Can features predict which way? | truth-matrix, 24 cells × 6 feats | ~290k bars | **0/144** signed-direction robust (broker-anchored) | Cost-classes paper §4 |
| 2026-07-14 | Is there any automatable price edge? | 5-family falsification, 16yr | 8 pairs, 16yr | 5 families fail at edge<cost wall (sim) | Edge-hunt paper |
| 2026-07-14 | Tight vs wide stops, same cells? | head-to-head portfolio sim | 6 cells, 8yr | tight −93%/yr Sharpe −3.54; wide +25.4%/yr Sharpe 1.05 (sim) | Edge-hunt paper CAPSTONE |

---

## 5. Threats to validity

Stated candidly; several are the reason a finding above is REVISED or OPEN rather than confirmed.

- **Selection bias.** The capstone portfolio (H5/H6) picked the 6 best cells; absolute returns are
  inflated. Only the *head-to-head direction* (same cells, both stop regimes) is selection-unbiased.
- **In-sample leakage.** Two distinct forms bit hard: the H1 look-ahead leak (B-078, up to 55min of
  future bar, some numbers 8–15× inflated) and 2026 being partially inside the tuning window for the
  wide-stop sim. Pre-2026-07-03 H1 numbers are upper bounds by default.
- **No-slippage simulation.** `net_ratchet` and the portfolio sims assume clean fills with ~1p cost.
  Real slippage is ~0 in calm hours but 4–10× at the 21:00 UTC rollover (B-086) and on news; wide
  stops slip more when hit. Every sim Sharpe owes a slippage haircut before promotion.
- **Small n.** Most live/broker cell claims rest on 5–50 trades. Winner-cell magnitudes (H4) were
  derived at n = 5–9. The governance floor (n ≥ 20 same-engine per cell before any action) exists
  precisely because early claims over-read small samples.
- **Config churn.** The book changed many times per session for months; a long aggregate blends
  incompatible configs into noise. Findings must be judged per-config, on trades since that config
  deployed.
- **Survivorship in the method.** Beyond data leakage, the stop-tuning method itself was
  survivorship-biased (H5) — the subtlest failure the program caught, and the reason "validate against
  the full firing population" is now doctrine.
- **Regime dependence.** The 2010–2026 CTA sample sits mostly in the documented post-2011 "trend
  drought"; AUD_JPY's 2023–26 risk-off crash inflates any cell that shorted it. A finding stable over
  one regime is not stable over all.
- **Ratchet-lottery magnitude inflation.** An uncapped ratchet in a trending cell produces
  fat-tailed magnitudes (+150p trimmed) that do not repeat; trimmed means, not raw, are the honest
  aggregator.
- **Practice-account pricing.** All fills are practice-account. Live spreads and fills must be
  re-measured after any switch to real capital.

---

## 6. The current open experiment

The live book (2026-07-14 → present) is the **wide-stop / range-sized-SL forward test** (H6): all 29
cells on range-sized stops (40/50/60 by session swing), ratchet trigger +7.5 → lock +5, fixed trail
2.5 (the `trail_mult=1.0` ATR-scaling bug that silently parked the ratchet below breakeven was B-090,
fixed), no green-lock inside a spread of entry. It runs on the OANDA **practice** account.

**What it would take to promote any cell to a live *shadow* seat:** the owed decisive test — anchored
walk-forward cell selection (train 2019–22 / test 2023–26) plus a slippage haircut — must return a
Sharpe that survives ~0.7. Until then the forward tape is the only verdict, and it is not in yet.

**What would falsify H6:** the walk-forward + haircut failing ~0.7; or the forward tape (at n ≥ 20 per
cell) showing avg-red not contained toward the wide stop, wide-stop slippage eating the runners the
thesis depends on, or the many-small-greens/rare-big-green skew simply not appearing.

---

## 7. Future work

Framed as the honest forks named at the close of the edge hunt — none of them "generate variant #6"
of a falsified family:

1. **Finish the wide-stop verdict** — the walk-forward + slippage gauntlet above. This is the single
   highest-value next step; the whole live book is staked on it.
2. **Different corpus, not different tuning** — the factor verdict's own prescription: the edge could
   not be expanded from this corpus, so test on a *different* one (pre-2019, other instruments) where
   AUD_JPY's 2023–26 trend does not dominate the OOS window.
3. **Pivot from prediction to execution/structure** — carry, cost, liquidity, and rollover-timing
   edges are a different game with a different test; the cost work (83% of the loss was spread)
   suggests the accessible edge may live in *paying less*, not *predicting better*.
4. **Accept trend as a low-Sharpe diversifier** — run it tiny and cheap alongside other ventures
   rather than as the main bet, consistent with the CTA finding.
5. **The honest option, kept on the table** — conclude that an automated retail price-edge is not this
   venture's advantage and weight engineering toward the ventures that are. The program's willingness
   to state this is part of what makes its positive findings trustworthy.

---

## 8. Provenance note

Every claim in this document is traceable. In-repo evidence is linked inline. Primary sources from the
pre-repo era are cited by archive location and date: the OANDA-agent genesis and the V1 runaway-re-entry
incident are from the operator's dated session archives (Dropbox `/LLM Sessions/…/Trading/`,
2026-02-14 and 2026-03-02); the Strategy E white paper and the retired-strategy catalog are imported
under [`papers/historical/`](papers/historical/) with their era clearly marked; the V4/V5 findings are
from the retired-repo docs (`/SCROOGE ARCHIVE/docs-harvest/`) and the research session diaries
(`/SCROOGE ARCHIVE/session-notes/`), both indexed in [`../research/README.md`](../research/README.md).
No number here is uncited, and no scope (sim/live/broker) is upgraded from its source.
