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
and was itself **falsified as-tested on 2026-07-16** by a pre-registered walk-forward with an honest
cost model (net test Sharpe 0.03 vs a 0.70 bar; gross 1.26 without slippage — the edge equals the
toll). The ledger closes with no surviving price-prediction hypothesis; what remains open is
execution-side, not prediction-side.

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
**H₀ was never rejected**: not for the direction-prediction family, and — as of the 2026-07-16
pre-registered walk-forward — not for the last candidate either (excursion-aware exit geometry on
cells with a persistent side, H6). Every family that showed a gross edge showed one the same size as
its execution cost.

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

**Documented.** [`papers/PAPER_ml_program.md`](papers/PAPER_ml_program.md) (the complete ML arc);
`RESEARCH_METHODOLOGY.md`, `BACKTEST_RESULTS.md` (archive `docs-harvest/v4-repo-docs/`);
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

### H6 — The wide-stop / rare-red thesis (falsified as-tested, 2026-07-16)

**Statement (as held now, Brock, Jul 14–15 2026).** Risk a book of many small greens plus the
occasional big green against a **wide, range-sized stop** (40 quiet / 50 mid / 60 loud, sized to the
per-(pair × session) session swing). Prove a trade green (ratchet trigger +7.5 → lock +5), let
runners express, and accept that reds are **rare and large** but carried by the green skew. Never
lock a stop within a spread of entry (a "flat" price is already −1 spread).

**Test method.** First the capstone portfolio sim (above) plus a range-sized variant, deployed to all
29 cells 2026-07-14 as a live forward experiment. Then the pre-committed decisive test, run
2026-07-16 with the design frozen before the run: **walk-forward cell selection** (train 2019–22 only
→ 3 of 29 cells survive; test 2023–26 untouched by selection) **plus a pre-registered tiered slippage
haircut** (~0.8–1.2p round-trip), on an engine validated by exact reproduction of the 07-14 capstone.
Pass bar stated first: net test Sharpe ≥ 0.70.

**Result.** In-sample (sim, 6-cell): Sharpe 1.00–1.05, the rare-red/runner skew confirmed — with the
inflators named and an honest guess of Sharpe 0.6–0.8 after correction. Decisive test (sim,
leak-clean corpus, n = 7,582): **net test Sharpe 0.03** vs the 0.70 bar (CAGR −2.1%, maxDD −50.9%).
The identical frozen book with zero slippage scores **Sharpe 1.26** (+32%/yr); the flat-slippage sweep
puts the knife-edge at **~0.4p round-trip** — half the defensible retail estimate. Every robustness
row (flat-SL, trigger-3.5, an exploratory 18-cell loose selection) fails in the same direction, and
the design's known impurities (candidate thresholds dialed on full history) could only have flattered
the result. The gross edge is also non-stationary (2023–24 strong, 2025–26 near-dead, frictionless).

**Verdict — FALSIFIED (as-tested, 2026-07-16).** The gross edge is real; it equals the execution
toll — the sixth structurally distinct family to die at the same wall. Nothing promoted to shadow;
live stops unchanged. The practice-account forward tape continues as an independent live check of the
same question (its main value now: measuring realized slippage against the sim's knife-edge), with
expectations reset accordingly.

**Documented.** [`papers/PAPER_h6_walkforward_2026-07-16.md`](papers/PAPER_h6_walkforward_2026-07-16.md)
(the decisive test); [`papers/PAPER_edge_hunt_falsifications_2026-07-14.md`](papers/PAPER_edge_hunt_falsifications_2026-07-14.md)
(CAPSTONE + range-sized deploy); [`SCROOGE_HISTORY.md`](SCROOGE_HISTORY.md) V5 Arcs 8–10.

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
| 2026-07-16 | Does wide-stop survive walk-forward + slippage? | pre-registered WF (train 2019–22 / test 2023–26), tiered slippage, engine reproduction-gated | 29→3 cells; 7,582 test trades | net Sharpe **0.03** vs 0.70 bar; no-slip twin 1.26; knife-edge ~0.4p RT (sim) | H6 walk-forward paper |

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

## 6. The verdict on the last open experiment — and what still runs

**The walk-forward verdict is in, and it is negative.** The decisive test the program owed itself —
pre-registered walk-forward cell selection (train 2019–22 / test 2023–26) plus a slippage haircut,
pass bar Sharpe ≥ 0.70 — was run on 2026-07-16 and returned **net test Sharpe 0.03**
([`papers/PAPER_h6_walkforward_2026-07-16.md`](papers/PAPER_h6_walkforward_2026-07-16.md)). The
identical book with zero slippage scores 1.26, locating the failure precisely at execution cost: the
gross wide-stop edge is real and is the same size as the toll (knife-edge ~0.4p round-trip vs a
defensible retail estimate of ~0.8–1.0p). H6 is falsified as-tested; no cell is promoted to a live
shadow seat. A same-day pre-registered follow-up (stale-exit of never-engaged trades after T hours,
T train-swept) also failed its material bar — every T that fires lowers Sharpe, because pre-engage
"drifters" and winners-in-waiting are the same population, and a 5-day extended-horizon probe refuted
the premise outright (all 1,374 test reds are fast stop-outs, median hold 2.2h; sim). A third
pre-registered test (the red-denominator hunt) found the reds DO share a real common denominator —
they are born in quiet tape (low ambient volatility, 22σ over a shuffled null at n=78k; NY-afternoon
13–18 UTC; and news days are *safer*, not riskier) — but the tradeable filter form failed both books
out-of-sample (sim): the regime is describable, not capturable. A fourth (joint SL x trigger grid)
closed wider stops with a clean physical law — widening the stop 3x cuts the pre-engage stop-out
rate only ~2.9x; rarity never outruns width — but produced **the ledger's first material positive**:
wider ENGAGE (trigger 7.5 → 20, SL unchanged) blind-tests at Sharpe ~0.57 in both sizing frames with
a zero overfit gap and a stable adjacent-arm plateau (sim) — material (≥0.30), not a revival (<0.70),
never yet traded live. All addenda in the H6 paper.

**What still runs.** The wide-stop book (range-sized SL 40/50/60, trigger +7.5 → lock +5, fixed trail
2.5 — B-090 fixed; no green-lock inside a spread of entry) remains deployed on the OANDA **practice**
account as an *independent live check of the same question*, with expectations reset by the sim
verdict. Its purpose is no longer to confirm a jackpot; it is to measure what the sim had to assume:
realized entry/stop slippage against the ~0.4p knife-edge, avg-red containment, and whether the
rare-red/green-skew shape appears in live fills at n ≥ 20 per cell. If the live tape were to beat the
sim's cost model decisively, that — and only that — would reopen H6.

---

## 7. Future work

With the wide-stop verdict in (§6), the ledger holds no open price-prediction hypothesis. The
surviving directions are the edge hunt's non-tuning forks — none of them "generate variant #7" of a
falsified family:

1. **Shadow the wider-engage arm** — the ledger's first material blind-test positive (3-cell book,
   trigger 20, SL 40–60; test Sharpe ~0.57 both frames, zero overfit gap — H6 paper, Addendum 3).
   Per the gauntlet: a live **shadow** seat only (no capital), to measure realized slippage and fill
   behavior against the sim's cost model; the 0.70 research bar and the live tape still gate any
   promotion.
   _Shadow DEPLOYED 2026-07-16 (commit 4ccf4db): additive `_t20s` SHADOW setups (the registered 3-cell book + 9 exploratory duplicates of live-ACTIVE setups) stamp on the dry-run shadow; a daily forward scorer replays the validated ratchet t20 vs t7.5 gears on practice M5 with the sim's realized-cost model. Never trades; promotion still gated by the 0.70 bar + live tape._
2. **Pivot from prediction to execution/structure** — carry, cost, liquidity, and rollover-timing
   edges are a different game with a different test. This is now the leading fork: the cost work (83%
   of a loss window was spread) and the H6 autopsy (gross Sharpe 1.26 eaten entirely by ~0.8–1.0p of
   slippage) both say the accessible edge lives in *paying less*, not *predicting better*.
3. **Different corpus, not different tuning** — the factor verdict's own prescription: the edge could
   not be expanded from this corpus, so any future prediction attempt belongs on a *different* one
   (pre-2019, other instruments) where AUD_JPY's 2023–26 trend does not dominate the OOS window — and
   must clear the same pre-registered cost-bearing bar H6 was held to.
4. **Accept trend as a low-Sharpe diversifier** — run it tiny and cheap alongside other ventures
   rather than as the main bet, consistent with the CTA finding.
5. **Measure the sim's one soft assumption** — the practice-account tape's remaining job: realized
   per-fill slippage vs the ~0.4p knife-edge (§6). Cheap, already running, and the only observation
   that could reopen H6.
6. **The honest option, now the default posture** — the program's own results say an automated retail
   price-edge is not this venture's advantage; engineering weight shifts toward the ventures that
   are. The willingness to conclude this is what makes the program's positive findings — the
   methodology, the falsifications, the cost accounting — trustworthy.

---

## 8. Provenance note

Every claim in this document is traceable. In-repo evidence is linked inline. Primary sources from the
pre-repo era are cited by archive location and date: the OANDA-agent genesis and the V1 runaway-re-entry
incident are from the operator's dated session archives (Dropbox `/LLM Sessions/…/Trading/`,
2026-02-14 and 2026-03-02); the Strategy E white paper and the retired-strategy catalog are imported
under [`papers/historical/`](papers/historical/) with their era clearly marked; the V4/V5 findings are
from the retired-repo docs (`/SCROOGE/SCROOGE ARCHIVE/docs-harvest/`) and the research session diaries
(`/SCROOGE/SCROOGE ARCHIVE/session-notes/`), both indexed in [`../research/README.md`](../research/README.md).
No number here is uncited, and no scope (sim/live/broker) is upgraded from its source.

**Data availability.** Every corpus and retired model behind these hypotheses is publicly downloadable
— the catalog, with the archive link and per-artifact leak status, is
[`DATA_AND_MODELS.md`](DATA_AND_MODELS.md). The machine-learning systems specifically (direction ML,
the pips brains, BUCKET21, the discovery engine, the sealed lab, the pattern loop) are documented
end-to-end in [`papers/PAPER_ml_program.md`](papers/PAPER_ml_program.md).

---

## Coda — the operator's doctrine

Written by the operator on the day the ledger closed (2026-07-16), after six falsifications
and the walk-forward verdict, as the distillation of what sixteen months and an −84% tape
actually taught:

> *"Indicators are useful — but more useful for momentum than direction. The wisdom found is
> in the trade management. That's where you win: you find the room for the pair to swing, and
> you lock in your green like a squirrel saving nuts for winter — at a lock-in point that
> floats above spread and slippage."*
> — Brock, 2026-07-16

Every clause is a measured result: momentum-not-direction is the 0-of-144 finding; the
management wisdom is where every surviving improvement in this program lived; the floating
lock is the breakeven-lock rejection ("never lock within a spread of entry") made doctrine.
The program adds one boundary the operator's doctrine runs into on this venue: management
redistributes the win/loss geometry but cannot manufacture expectancy — the doctrine is the
correct way to trade, and the execution toll decides whether trading is worth doing at all.
At a round-trip cost under ~0.4 pips, the system described above wins as already built.

## The Activation Bar (2026-07-22, post-storm doctrine)

The first live kill-week (B-091–B-095 era) exposed a governance gap: **ACTIVE had no
entry requirement** — it meant "survived some earlier era's validation and nobody demoted
it." The storm's entire realized red column came from one setup whose claimed edge
(+0.6p/trade in walk-forward) was smaller than our uncertainty about the execution toll,
carried live on legacy status and stale instruments.

**The bar:** a setup may be ACTIVE only with **current-era shadow evidence of n ≥ 20
episodes at avg ≥ +2.0 pips/episode** (net-240, stamp-forward — the Shadowboard metric).
The +2p margin exists because the toll knife-edge is ~0.4–0.5p and a sub-1p claimed edge
is indistinguishable from zero at any n the book reaches in weeks.

- The Shadowboard awards 🏆 only when the bar is met, and flags ACTIVE setups without
  current-era bar evidence (⚠️). The promote/demote buttons sit next to the evidence.
- Re-checked at every monthly refit; a setup that loses the bar reverts to SHADOW —
  where watching it costs nothing.
- The bar governs entry to ACTIVE. Exit from ACTIVE can (and should) be faster on
  broker-fill evidence — fills convict quicker than stamps (the storm needed two).
- Era boundaries matter: evidence must come from the current engine/config era. A
  cutover or gear change restarts the clock (see B-094 for what stale-era evidence does).

**SIDES ARE NEVER FLIPPED IN PLACE (2026-07-27, Brock).** A setup keeps its name-true
direction forever. When the mirror looks better (the MAE-flip signature), a COUNTERPART
setup with its own honest name fires the opposite direction at the same trigger
(classic_box_fade_long / classic_box_break_short is the template) and earns its own
evidence. Renamed history flows through config/setup_aliases.json so records survive
reorganization. Nobody reading the book should ever meet a long that trades short.

**AUTOMATED 2026-07-27 (the Bar Governor).** Promotion and demotion are no longer manual
dockets: `ops/governor.py` runs daily and flips statuses by the standard above (promote:
era n>=20, avg>=+2.0, LCB>0, 7d not negative; demote: bar lost on era stamps, or era
broker fills net-negative at n>=5). The humans define the numbers; the bot flips the
switches. Ledger: `data/governor_ledger.jsonl`. This is the loop the project was built
for — hundreds of candidates earning seats, incumbents losing them, autonomously.



## Open dockets (2026-07-24, from the outside-review triage)

An external review of the dashboard (2026-07-24) proposed ten changes; most were either
already doctrine (the bar IS confidence-gated promotion) or already falsified (regime
scoring and meta-allocators are price prediction re-skinned; graduation ladders assume
config stability we deliberately don't have). Two items survived triage and await a
Brock docket because they touch book governance:

- **D-1 — Wire exp_ev to current-era measured EV.** Most CELLSHADOW stamps carry
  `exp_ev=+0.000` (controls and un-scored setups stamp a placeholder), so the Setup
  Scoreboard's Δ (sim vs expected) only carries information on the few setups with an
  assigned ev_seq. Proposal: stamp exp_ev from the setup's current-era Shadowboard avg
  at stamp time, making Δ a real calibration signal across the whole board. Cost: the
  stamp path gains a dependency on the aggregate store; era boundaries must reset it.
- **D-2 — Evidence-tiered sizing.** Units tied to the activation bar: bar-met = full
  10%/trade, ACTIVE-without-bar (era too young) = half. Not prediction — capital
  geometry, consistent with the 2026-07-20 Kelly measurement (book runs ~quarter-Kelly).
  Reduces the cost of being wrong about young setups without claiming to know regimes.

- **D-3 — March-replay cross-pair shadow book (RUNNING since 2026-07-27).** The 2026-03-23..26
  winners (acct txns 209-324, V2 harvest era) carried exactly the shapes the cell era later
  validated on the majors — on pairs the book has never traded (CAD_JPY, AUD_CAD, EUR_CAD,
  GBP_CAD). Those 4 crosses now scan as SHADOW-only cells: ps_floor_fade_long (asia),
  trend_pullback_long (london/ny — the discovery engine's one robust entry, first time wired),
  ps_ceil_fade_short (ny). Conditions copied verbatim from the majors' validated blocks.
  Promotion: activation bar only. Prior: crosses pay 2-3x major spread toll — the bar may
  correctly say no; that is a result, not a failure. Generator:
  research/tools/build_march_replay_cells.py. EXTENDED 2026-07-27 with the April 1-7 tape
  (txns 435-522): +3 CHF crosses (EUR_CHF, CHF_JPY, AUD_CHF — 15 pairs scanning),
  ps_ceil_fade_short added to all cross asia sessions (April asia fades won: AUD_CHF +$815)
  and to USD_CHF london/ny SHADOW (txns 458/466 were this pair, this shape). April also
  supplied the floor-fade counter-example: USD_MXN 435 (-$1,197) longed a BROKEN floor in a
  4h downtrend — the ps_low_dist>=0 condition refuses exactly that trade. USD_MXN not added
  (exotic spread, and its tape is the cautionary example, not the edge). EXTENDED AGAIN
  2026-07-27 with the April 16-17 tape (txns 990-1344): +NZD_USD, NZD_JPY, GBP_JPY (18 pairs
  scanning, 54 cells). Star exhibit: NZD_USD 990/1014 — identical ceil-fade indicators 29
  minutes apart, -$746 then +$1,379; one trade proves nothing, the bar aggregates. That tape
  also ran a micro limit-chaser scalper whose ceil-fades LOST on a minutes-horizon while the
  big book's won at 240m — horizon is part of the edge.

- **D-4 — Strategy-Book cube on trial (RUNNING since 2026-07-27).** Five of the retired
  book strategies whose entries are pure feature thresholds (alpha_extended_fade both
  sides, echo_box_fade both sides, MR2 bb-reversion, RG1 range-scalp) run as SHADOW
  setups on the cube backtest universe (AUD/EUR/GBP_USD, USD_CAD; london+ny), thresholds
  verbatim from the book. Their cube EVs (+1.1..+4.5) are pre-leak upper bounds on the
  retired ladder — the current-era stamps are the re-measurement. TF2_pullback is already
  on trial as Strategy E; alpha_pullback skipped as duplicate. The six multi-bar pattern
  strategies (CP1/CP2/charlie/delta/bravo x2, BR-family) are NOT expressible in the cell
  condition schema — wiring them would need new feed features (BB_compress, ADX,
  bar-range ratios): a candidate follow-on if the threshold five earn anything.

- **D-5 — Execution truth (external review, finding 3; SHIPPED 2026-07-28 in four
  staged commits, each restart-verified against the live book).** Delivered: server-side
  SL as a fill-anchored DISTANCE (slippage can no longer resize the real stop); parents
  and poppers adopt orderFillTransaction.price as the true entry with per-fill
  quoted/filled/slippage/spread logging; parent and popper management (peak, engage,
  lock, trail, net) runs on executable bid/ask instead of mid; durable sv6-* order
  intent ids with broker reconciliation on transport errors (accepted-then-timeout is
  adopted, never orphaned; never-arrived raises safely). Grid marker crossing stays
  mid-based by design (level definition, documented inline). Residuals: bracket-mode TP
  remains quote-anchored (no distance form; unused by the live book). Original spec:** The engine builds Position, stop distance, and ratchet
  baseline from the pre-order quote and ignores the broker's returned fill price;
  management runs on mid rather than executable bid/ask. Work package: adopt
  orderFillTransaction.price as the entry everywhere; bid-for-long / ask-for-short
  liquidation and MFE in management and scoring; record spread+slippage per trade;
  durable client order ids + reconciliation so an accepted-order-then-timeout can never
  orphan or duplicate. At an 8.5p trigger these are not bookkeeping — they may decide
  whether the edge exists.
- **D-6 — The statistics program (external review, finding 6; SHIPPED 2026-07-28 — see docs/GOVERNOR.md §statistics).** Delivered: one net-of-cost utility for promotion AND demotion (stamped entry spread + slippage haircut; stamps now carry spread=X.X); overlap-aware effective n in the confidence bound; deflated z_promote (2.33 default) with the hypothesis registry (data/hypothesis_registry.json, M=146 at ship) reported every run; config-hash era resets on any mechanics change. Remaining as future work: grid-episode/currency clustering beyond time-overlap, and full DSR on a per-hypothesis trial count. Original spec:** The governor
  promotes on frictionless stamp-forward drift and demotes on broker P&L — different
  distributions; overlapping 240m labels on ~30min episodes make the LCB overconfident;
  ~150 setups examined daily is a multiple-testing machine with no deflation. Work
  package: cluster-aware scoring (grid episodes and same-currency trades as units), one
  cost-adjusted utility for promotion AND demotion, era resets on any config-hash change
  (not just governor flips), an explicit hypothesis registry, and PBO/Deflated-Sharpe-
  style controls on the promotion gate (Bailey & Lopez de Prado). SHIPPED from the same
  review, 2026-07-27: trial-fairness stamping (every setup, every cycle), validator
  sync + test enforcement, same-origin dashboard writes, fail-closed runtime controls.

- **D-7 — Statistics v2 + shadow execution truth (external review round 2; QUEUED —
  promotions gated off until it ships).** The full spec lives in docs/REVIEW_R2_PLAN.md
  (the reviewer's implementation plan, adopted). Work package: day/session-block
  bootstrap inference (gap-weighted n_eff demoted to a display diagnostic);
  Benjamini–Hochberg FDR across each run's candidate docket + sequential-peeking
  guards (re-test only on new independent blocks, weekly promotion cadence); ONE
  shared current-era evidence engine + promotion predicate for governor AND
  Shadowboard (trophy == predicate, current-era vs lifetime split); versioned
  structured TRIALSTAMPs carrying the stamped executable entry; bid/ask candle
  scoring from the stamped entry; setup-specific exit-geometry simulation with
  worst-case ambiguous-bar handling; metric-version isolation + METRIC-ERA-RESET
  migration. SHIPPED from the same review, 2026-07-28: path-keyed LKG + randomized
  CI (4/5 seeds failed before), live hot-loader schema enforcement with
  retain-last-valid, order-finality quarantine (HTTPError-order bug, PENDING/404
  never = absent, empty parent fills rejected), full dashboard security model
  (host allowlist, token auth, OANDA host allowlist token-exfil fix), per_test_z
  honesty + allow_promotions gate.

Adopted immediately (same triage, no governance impact): the Shadowboard now sorts by
**LCB = avg − 1.645·sd/√n** (95% one-sided lower bound on avg net/ep) instead of raw
avg — small-n glamour rows sink below proven ones, n<2 shows "—" and sorts last. The
Setup Scoreboard sim cap now takes the most recent 50 stamps (was oldest-50, which
blanked SimEV on exactly the highest-n setups).
