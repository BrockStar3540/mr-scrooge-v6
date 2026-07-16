# Technical Forex Direction Detector — Specification v2
## Evidence-Revised Edition (2026-07-03)

**Lineage:** v1 = Brock's original TechnicalForexDirectionDetector spec + the MAE/MFE
ExcursionEstimator addendum. v2 = the same theory, revised against everything measured
2026-06-18 → 2026-07-03: ~165 live broker trades, a validated per-bar MAE/MFE truth matrix
(8 pairs × 8 years, anchor-checked vs broker fills at r=0.84–0.90), a confirmed-and-repaired
look-ahead leak in the research corpus, and a 3-model analyst panel review.

**Implementation mapping (V5):** Direction Scorer = `direction_v2` · Movement Scorer =
`momentum_v3` · Trade Quality Gate = playmaker per-cell gates · Regime = profiles +
aggregator rules · ExcursionEstimator = the truth matrix (offline) → per-cell distance
calibration (live, pending) · Portfolio Layer = exposure caps (NEW, live).

---

## CHANGE LOG — what the evidence did to the theory

| # | v1 said | v2 says | Evidence |
|---|---------|---------|----------|
| 1 | One detector, default EURUSD, one weight table | **Everything is per-cell (pair × session × direction). No global weights, thresholds, buckets, or regime rules — ever.** | Per-cell sync rankings: every cell's persistent direction lean rides a DIFFERENT feature (vwap_dist AUD_USD/london, atr_h1_rel USD_JPY/london, daily levels USD_CHF/london, stochrsi EUR_USD/ny). A global weight table averages real cellular edges to ~zero. |
| 2 | Label = endpoint close ±threshold at t+12 (§13) | **Label = the forward excursion surface (MFE/MAE both directions), not the endpoint.** Direction target = excursion asymmetry; distance target = MFE magnitude; dead-entry target = low MFE. | The exit harvests paths, not closes (ratchet). Endpoint direction AUC on clean data ≈ 0.50 everywhere; excursion targets expose structure endpoints hide. Anchor check proved M5 H/L excursions ≈ broker fills (r=0.84–0.90). |
| 3 | Recommended static weights (trend 25%, structure 25%…) | **Weights are fit per cell against the truth matrix, drift-labeled, re-fit monthly.** The v1 table is a bootstrap for cells with no data, nothing more. | The 2026 profile re-audit on clean data: the three hand-built weight profiles are near-indistinguishable (mean AUC 0.4984, lift +0.011). Static weight sets don't carry the edge; per-cell fitted leans do. |
| 4 | Indicator interpretations from trading lore (§7) | **Indicator roles are assigned by measured sync with the truth matrix, per cell, with drift labels.** | See §7 sync table below. Lore casualties: aroon ±3.57 rule (dead on clean data), EFI (highest raw corr in dataset, pure FLICKER). Lore survivor: channel/Keltner distance — confirmed by THREE independent clean lineages. |
| 5 | Regime detector with fixed thresholds (§9) | Regime layer kept, but **every threshold must be (a) dimension-checked against the live feed's actual value range and (b) re-fit on the current year, monthly.** | The atr_conc bug: profiles gated on atr_conc ≥ 4.0 while the live ratio lives in (0,1) — 14 of 48 cells structurally dead for weeks. And regime rules fit on 8yr averages flip sign within 2026 (Feb ≠ May). |
| 6 | MAE/MFE proposed as an estimation layer (addendum) | **MAE/MFE is THE ground truth of the whole system** — the target every feature is judged against, the configuration tool, and the estimation layer. Built, validated, current. | Truth matrix: per-bar dual-direction 60m/240m excursions, 8 pairs × 8yr, seam-perfect to today, broker-anchored. "The verified MAE and MFE for each hour of ticks is the biggest ultimate truth we could have." |
| 7 | (absent) | **Portfolio exposure layer**: a correct UP call can still be an incorrect trade if the account already holds the same (currency, direction) bet. | 07-02: three simultaneous long-yen positions into a JPY crash = one macro bet at 3× size. Live fix: max_per_currency_direction=1 (121 candidate skips in first 8h, zero stacking since). |
| 8 | (absent) | **Data-integrity protocol** (§18): completed-bars-only joins, anchor checks vs broker, live-trade veto, drift labels. | The H1 look-ahead leak: open-time joins put up to 55min of future into every H1 feature; it inflated h1_ret_1bar's corpus corr from −0.01 to +0.41 and manufactured a fake +0.0802 profile finding that nearly shipped. |
| 9 | (absent) | **Governance layer**: sample-size constitution, flip/chop calibration, locks-as-attribution. | Six "validated winner" cells locked on n=2–14 went 3W/7L (−127p) immediately post-lock; P(under the claimed WR) = 2.8e-5. Tuning on n<10 is fitting luck. |
| 10 | d_cert / m_cert definitions (addendum §4) | **Confirmed with refinements** — kept as spec'd, plus: low m_cert ↔ large |MAE| (entry-quality reading confirmed); per-cell d_cert floors work (USD_JPY/asia 0.49 floor separated all winners from both losers). | Live: GBP_USD/ny d_cert gap (losses 0.49/0.50 vs winners ≥0.54); AUD_JPY m_cert 0.25–0.40 on all 6 deepest-MAE trades. |

---

## 1. Purpose — REVISED

The detector estimates, **per cell (pair × session × direction)**, the probable forward
excursion structure over the next 60 minutes: which way the path leans (direction), how far
it can run (projected distance / MFE), how much adverse movement precedes it (MAE), and
whether the entry is likely to get off the ground at all (dead-entry risk).

Technical inputs only (v1 §2 boundary unchanged — no news, macro, fundamentals).
**The strategy-free principle:** there are no named setups or plays. Direction + projected
distance per cell IS the entire strategy; everything in this spec is in service of those two
numbers and their certainties.

## 2. Module Boundary — UNCHANGED from v1
(Allowed: price/candles/bid/ask/spread/volatility/trend/momentum/structure/candle
anatomy/session structure/indicator state/MTF alignment. Excluded: all fundamentals.)

## 3. Prediction Objective — REVISED

Per evaluation timestamp AND per cell:

```text
excursion_forecast: expected MFE, expected MAE, both directions, 60m horizon
direction:          which side's (MFE − MAE) asymmetry is favorable → UP / DOWN / NO_EDGE
distance:           projected MFE for the favored side (replaces any fixed expected-pips)
dead_entry_risk:    P(MFE < 5 pips) for the favored side
certainties:        direction_certainty (d_cert), movement_certainty (m_cert)
```

FLAT is expressed as high dead-entry risk + low m_cert, not as a separate class — the live
system's equivalent of FLAT is "gates don't pass."

## 4. Data & Truth Labels — REVISED

Raw data requirements unchanged from v1 (§4), pip rules unchanged. NEW REQUIREMENTS:

- **Completed bars only, everywhere.** Any higher-timeframe feature joined to a lower
  timeframe must use the last bar whose CLOSE time ≤ t. Join on close-time, never open-time.
  (The leak. Non-negotiable. Test it empirically after every corpus rebuild.)
- **Truth labels are the excursion surface** (v1 addendum §3 formulas, adopted verbatim,
  now implemented): per bar t, forward 12-bar (60m) and 48-bar (240m) MFE/MAE for both
  hypothetical directions, from M5 highs/lows. MAE stored negative.
- **Anchor requirement:** the M5-derived surface must be re-validated against verified
  broker-fill excursions whenever the pipeline changes. Current anchor: r=0.84 (MFE), 0.84
  (MAE) raw; 0.86–0.90 convention-adjusted; MAD 2.5–3.1p; known bias: matrix understates
  MAE ~2.7p (entry-bar exclusion) — carry this bias in any MAE-based stop logic.

## 5. Timeframe Architecture — UNCHANGED from v1
(1m pressure / 5m primary / 15m confirm / 1h context; 60m horizon; 12 forward candles.
Tick data supplemental only.)

## 6–7. Features — REVISED: roles are measured, not assumed

Keep v1's seven buckets as the FEATURE TAXONOMY. Replace v1's interpretation rules with the
measured sync table (clean data, 2026-fit, drift-labeled — refresh monthly):

| Feature family | Direction sync | Distance (MFE) sync | Dead-entry sync | Drift | Verdict |
|---|---|---|---|---|---|
| Channel/Keltner/Donchian distance (kc_up_dist, dc_dist) | per-cell | medium | **AUC 0.53–0.65, best family** | PERSISTENT (most cells) | **Flagship. Three independent clean lineages agree.** |
| ATR family (atr_5m, atr_1h, yzv) | ~0 | **0.20–0.37, best family** | medium | REGIME/FLICKER monthly | Distance calibration input — monthly re-fit mandatory |
| bb_width | ~0 | medium | good (long cells) | PERSISTENT 24/24 | Clean ship candidate (movement energy) |
| bbwp | ~0 | medium | good (NY cells) | PERSISTENT 19/24 | Ship session-weighted (survived its own 44-trade false alarm AND the leak audit) |
| VWAP distance | **persistent per-cell lean** (AUD_USD/london r≈0.12) | low | low | PERSISTENT | Per-cell direction weight where it syncs |
| atr_h1_relative | **structural: helps longs, hurts shorts** (16/16/16 cells) | medium | low | pending 2026 confirm | Per-cell whitelist candidate — do NOT wire globally |
| Daily levels (PDH/PDL, d_high/d_low) | persistent per-cell (USD_CHF/london both timeframes) | low | medium | PERSISTENT | Strongest "sleeper"; session-structure bucket vindicated |
| willr / stochrsi | per-cell only (stochrsi: EUR_USD/ny) | low | medium | mixed | Gate material where a clean live split exists; NOT a universal weight |
| h1_ret_1bar | ~0 on corpus (clean) | ~0 | **live-trade AUC 0.658 (0.858 asia)** | FLICKER on corpus | Forward-tracked hypothesis only: don't fight the bar you enter on. Corpus dominance was 100% leak. |
| EFI | looks high, isn't | — | — | **FLICKER** | The cautionary tale: highest raw corr in the dataset, sign flips monthly. Never wire FLICKER. |
| aroon | dead as global rule (±3.57 = leak artifact) | low | per-cell gate only | mixed | Live per-cell gate where a clean broker-trade split exists (USD_CAD/london −85 wall) |
| RSI-lore, MACD-lore (v1 §7.3 bands) | unvalidated | unvalidated | unvalidated | — | v1 interpretations remain HYPOTHESES until they sync per-cell |

**Feature admission protocol:** corpus (clean, 2026-fit, per-cell) PROMOTES → live trades
VETO → drift label decides durability (PERSISTENT wire / REGIME wire+monthly-recheck /
FLICKER never). Small-N live findings are hypotheses with tracking plans, never gates,
until n≥20 same-engine.

## 8. Scoring — REVISED

v1's bucket structure and the "liquidity penalizes confidence, not direction" rule are kept
(the rule is confirmed: spread gate is now fail-closed on bad ticks and remains
non-directional). The static weight table is DELETED. Weights per cell come from the truth
matrix sync fit; v1's table may seed a NO_DATA cell's bootstrap only.

## 9. Regime — REVISED

Regime taxonomy kept. Two hard rules added:
1. **Dimension check**: every regime threshold must be validated against the live feed's
   empirical value range before deployment (the atr_conc ≥ 4.0 vs live <1.0 bug class).
2. **Regimes drift**: 2026 monthly sign-flips are the norm, not the exception. Regime
   thresholds are re-fit monthly with everything else. A regime rule that was fit once and
   trusted forever is a future bug.

## 10–11. Probability & Classification — KEPT (v1), with calibrated gate constants

v1's sigmoid conversion, conviction penalty, and minimum-edge classification stand. The
NO_EDGE discipline is confirmed as the single most important behavior (most cells' honest
state is NO_EDGE most of the time). Payoff-shape context for all gate tuning: with a −20p
stop and ratchet winners averaging +5–8p, breakeven WR ≈ 77% — gates exist to refuse
everything that can't plausibly clear that bar (or the stop/targets must become cellular —
see §13).

## 12. ExcursionEstimator — PROMOTED TO CORE (was addendum)

The addendum's design is adopted whole: MAE/MFE estimation per signal, risk buckets scaled
by current ATR (never fixed pips), reward_to_adverse_ratio, and the trade-quality gate
(direction alone never triggers a trade). Confirmed refinements:
- `m_cert` doubles as entry-quality: low m_cert ↔ deep MAE (live-confirmed). The
  addendum's suspicion is now doctrine.
- Cells where BOTH directions show MAE ≳ MFE (ratio ~1.5–2.5 both ways) are CHOP cells:
  disable, never invert (EUR_JPY/ny, AUD_JPY pair-wide).
- Cells where ONE direction shows MAE/MFE ≥ ~3× with n≥6 same-engine trades are
  wired-backwards: flip that direction only (per-direction inversion mechanism;
  USD_CAD/london at 12× is the type specimen). Below 3× is noise — do not flip.

## 13. Exits & Sizing — NEW (v1 was entry-only)

The detector's outputs must flow into cellular exit/size parameters:
- initial stop per cell (global −20p including JPY pairs is a known wrong; derive from the
  cell's winner-MAE distribution, respecting the matrix's −2.7p MAE understatement bias)
- ratchet bands per cell (cells whose winners run +5–8p never reach a +7.5p trigger)
- size risk-normalized: units = balance × risk% / (stop_pips × pip_value) — the margin-only
  model makes dollar risk vary by pair accidentally
These are pending implementation, sourced from the truth matrix, in the cellular-migration
queue (global-rule audit 2026-07-03).

## 14. Portfolio Layer — NEW

After the cell says UP and quality gates pass, the PORTFOLIO decides:
- max concurrent positions (global cap)
- **max 1 concurrent position per (currency, direction)** — a position is long BASE + short
  QUOTE; block candidates that would stack the same macro bet
- locked-cell throttles (max opens per session-instance)
A skipped correct signal costs opportunity; a stacked correct-looking macro bet costs 3×.

## 15. Output Schema — the addendum's JSON adopted, plus cell identity

Add to every output: `"cell": {"pair","session","direction"}`, `"drift_labels"` for the
features used, and `"lineage": "clean-corpus | live-fit | bootstrap"` per parameter, so
every number in production can be traced to its evidence class.

## 16. Naming — addendum §5 adopted for docs/logs
(direction_score / direction_certainty / movement_certainty / williams_r / keltner_upper_
distance / elder_force_index …; short names remain as model columns.)

## 17. Governance — NEW

- **n≥20 same-engine broker trades before any per-cell action** (invert / one-direction
  disable / lock / gate). Both-direction disables ("no edge here") may stand on less.
- **Locks are attribution snapshots, not validated-winner badges.** Snapshot + drift-log +
  explicit-override protocol (implemented as V5 lock_guard). Re-lock only at n≥25 with WR
  CI above breakeven.
- **Never evaluate a cell across engine eras** — cross-era contamination killed two "star"
  claims. Same-engine only.
- **Broker truth over journal; forward/excursion truth over realized P/L** for entry
  decisions (exit logic flips ~32% of outcomes off market direction).

## 18. Data-Integrity Protocol — NEW (the leak's legacy)

1. Close-time joins only; empirical overlap test after every rebuild.
2. Anchor check vs broker fills after every pipeline change (bar: r ≥ 0.8).
3. Fit windows are RECENT (current year); long history is drift context only
   (PERSISTENT/REGIME/FLICKER), never the fit.
4. Corpus promotes → live vetoes → monthly re-fit (lab-hardware cron).
5. When a number looks too good (r=+0.40 autocorrelation in FX), assume leak until proven
   otherwise. The reflex found the bug; keep the reflex.

## 19. Roadmap

```text
DONE:    truth matrix built + anchored + current · leak fixed · per-cell gate machinery
         (cert floors/ceilings, willr/kc/aroon ranges, per-direction inversion) ·
         portfolio caps · lock governance · profile shadow (live A/B of scoring stacks)
NEXT:    per-cell dead-entry penalties (channel-distance family) into momentum scoring ·
         per-cell projected distance replacing the global 0.30 multiplier ·
         cellular stops/ratchet bands/sizing · atr_h1_rel long/short whitelist (post
         2026-confirm) · monthly re-fit loop live end-to-end
V2 model: per-cell gradient boosting on truth-matrix targets once live samples earn it —
         same features, same labels, same protocol; ML is a better fitter, not a different
         truth.
```

**The v1 goal stands, sharpened:** a clean technical engine that produces structured,
traceable predictions per cell, refuses low-quality conditions, estimates its own risk and
reward in excursion terms, and — above all — never believes a number it can't trace to
verified excursion truth in the current regime.
