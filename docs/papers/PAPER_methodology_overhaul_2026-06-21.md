# The Measurement Overhaul: Broker Truth, Forward Pip, and the NY-Fade Discovery

**Mr. Scrooge V5 · research paper · 2026-06-20/21 weekend**
**Author: Brock (research direction) + Claude Code (measurement, wiring)**
**Status: standing methodology. The measurement rules below are program law; the NY-fade *direction*
is VALID LEGACY (clean anchors); several per-cell *magnitudes* were later found to sit on H1-leak
parquets (B-078) and are upper bounds.**

---

## Abstract

Over one weekend (23 commits, 12 research sessions) the project changed *how it measures itself*, and
in doing so found the reason V5 had been losing money. Four measurement standards were installed as
standing law: measure from **broker fills, not the bot journal** (the journal matrix had missed 70 of
the real 120 trades); judge *entries* by **1H forward pip, not realized P/L** (exit logic had flipped
~32% of trades from their market direction); **walk-forward everything** (train <2024, test ≥2024); and
resolve **per-(pair × session × direction), never globally**. Applying them surfaced the weekend's
headline: **the New York session is a momentum-FADE regime for all eight majors**, confirmed four
independent ways. V5's direction engine used one-bar momentum as its top factor and *trend-followed* it
— so it systematically fought the NY fade. The unification that resolves it: short-term momentum
*without* higher-timeframe backing is exhaustion (fade); *with* backing it is continuation. Roughly five
of forty-eight cells showed a broker-confirmed edge; ten were disabled. All broker figures are tagged
broker; all backtest figures are sim; and the paper flags in advance that its H1-enriched magnitudes are
upper bounds pending the leak repair that came two weeks later.

---

## 1. Background

By 2026-06-18 V5 (the strategy-free rebuild) was live but losing: broker tape read **−$6,114 over 120
trades** (V4+V5 combined), **−$2,234 over 36 V5-era trades**, and the V5_v1 brain was *anti-calibrated*
— its confidence score (`m_cert`) was **negatively** correlated with wins. The prior analysis had been
built from the bot's own journal and from realized P/L. This weekend's premise was that both of those
inputs were lying, and that fixing the *measurement* would explain the loss before any new strategy
could.

---

## 2. Method — the four rules installed as law

1. **OANDA API, not the journal.** The journal records V5's *intent* (SIGNAL / ENTERED markers); the
   broker has the actual fills, manual closes, spread cost, and realized P/L. A 44-trade journal matrix
   had **missed 70 of the real 120 trades** (later catalogued B-084). Every subsequent trade analysis
   pulls from the broker.
2. **1H forward pip, not realized P/L, for entry decisions.** Exit logic changes constantly and had
   flipped ~32% of trades from their actual market direction — so realized P/L conflates a good entry
   with a bad exit. To judge an *entry*, measure the 1H forward price move. Manual-closed trades are
   *included* (manual close affects realized P/L only, never the forward direction).
3. **Walk-forward everything** (train <2024, test ≥2024). A prior "overlap trends" claim flipped sign
   out-of-sample; nothing is trusted that has not survived a train-past / test-future split.
4. **Per-(pair × session × direction), never global.** The cells genuinely disagree — validated four
   ways — so a global verdict averages away the signal. App-confluence visuals are not forward-price
   edges.

Corpus: 120 broker trades (V4+V5 era) + 8-year OANDA M5/H1/D corpus, 8 pairs. Heavy compute on lab
hardware.

---

## 3. Results — NY is a momentum-fade session

V5's direction engine ranked `h1_ret_1bar` (one-bar momentum) as its #1 factor and **trend-followed**
it. Measured honestly, that is backwards in the NY session: when momentum points a direction, the next
60 minutes tends to **reverse**. Confirmed four independent ways:

| Confirmation | Evidence |
|---|---|
| Broker realized P/L | NY cells lost money (broker) |
| Broker 1H forward pip | NY cells negative (broker) |
| 8yr walk-forward momentum | NY fades, **8/8 pairs**, both train and test windows (sim) |
| ALIGN resolution | HTF alignment fades in NY/london (14/16 cells), confirms in overlap (16/16) (sim) |

**Why V5 lost in NY: it trend-followed a fade regime.** The unification across sessions:
short-term momentum **without** higher-timeframe backing (unaligned) = exhaustion / fade; **with**
backing (aligned) = continuation. This single frame reconciles the session disagreement.

**Confirmed winner cells (V5's real edge — ~5 of 48):**

| Cell | profile | broker forward pip | n |
|---|---|---:|---:|
| USD_CAD/ny/long | reversion | +6.61p | 7 |
| EUR_USD/london/short | reversion | +6.31p | 7 |
| AUD_JPY/asia/long | default (trend) | +6.70p | — |
| AUD_JPY/asia/short | continuation_strong (trend) | +1.80p | 6 |

**The per-cell architecture, proven by its conflicts.** The consolidated 48-cell ruleset contains 8
cells where the ML profile says `continuation_strong` but momentum + broker say fade (worst:
USD_JPY/ny/short, profile = continuation but broker −17.8p). *Only per-cell resolution catches this* — a
global model would trust the profile and keep losing. The MAE-flip doctrine was formalized here: a
losing cell with MAE ≫ MFE is the right signal wired backwards → flip the entry.

**Live actions taken:** 10 cells disabled in the playmaker config (AUD_USD/ny L+S, USD_CHF/london/short,
USD_CAD/ny/short, EUR_USD/ny/long, EUR_JPY/london/short, EUR_JPY/ny/long, USD_CHF/ny/long,
AUD_JPY/london/short, AUD_JPY/ny/long); 2 cells set to shadow-log inverted (GBP_USD/ny + EUR_JPY/ny,
looked +2.5–3.0p net of spread at n = 4–10); a shadow Vortex feature began logging; a monthly
master-matrix refit was scheduled on lab hardware.

---

## 4. Limitations (stated at the time, sharpened by hindsight)

1. **Small n.** Winner-cell and inverted-cell claims rest on n = 4–10 broker trades. The *direction* is
   what stands; the magnitudes are early-era evidence.
2. **H1-enriched magnitudes are upper bounds.** Two weeks later the H1 look-ahead leak (B-078) was found:
   research parquets had joined H1 features on open-time, injecting up to 55 minutes of future bar. Many
   per-cell magnitudes from this weekend sit on those parquets and are inflated. **The NY-fade
   *direction* survived on clean anchors (broker + M5 + walk-forward); the per-cell magnitudes did not.**
3. **v2/v3 modules had zero live trades** through the launch weekend (market windows), so the first real
   test came the following week.
4. **Session lumping.** V5's `ny` session lumped the trend-y 13–14 UTC overlap with the fade-y 15–21 —
   flagged as an open split, not resolved here.

---

## 5. Significance

This weekend is why the whole program's numbers are scoped **sim / live / broker** and why the reading
order leads with a truth hierarchy. The lesson generalizes past forex: **the apparent performance of a
system is dominated by the fidelity of its measurement.** Broker-over-journal and forward-pip-over-P/L
each moved the verdict on dozens of cells; walk-forward flipped a headline claim's sign; and the
subsequent leak repair (B-078) showed that even a clean-looking corpus can carry a look-ahead that
inflates results 8–15×. The overhaul did not find a new edge — it found that the *old* edges were
measurement artifacts, which is the more valuable and more transferable result.

---

## 6. Data availability

- Session diaries: `/SCROOGE/SCROOGE ARCHIVE/session-notes/2026-06-21_full_weekend/` and
  `.../2026-06-21_master_matrix_broker_validation/`; 48-cell ruleset at
  `research/sessions/2026-06-21_cell_ruleset/data/cell_ruleset.csv` (archived).
- Early V5 live-trade matrices: [`../../research/matrices/`](../../research/matrices/)
  (`v5_full_matrix_44trades.csv`, etc.) — **historical**, predating broker-truth and leak-clean anchors.
- Broker-truth doctrine and the forward-pip method are program law; see
  [`../../research/README.md`](../../research/README.md) truth hierarchy (VALID LEGACY tier) and
  [`../RESEARCH_PROGRAM.md`](../RESEARCH_PROGRAM.md) §3.
- Related defects: B-084 (journal missed 70 trades), B-078 (H1 leak). See [`../BOOK_OF_BUGS.md`](../BOOK_OF_BUGS.md).
