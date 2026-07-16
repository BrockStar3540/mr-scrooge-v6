# [HISTORICAL] Retired Strategies — A Condensed Catalog

> **Historical-document notice.** This is a **condensed** catalog of the strategy families the
> program built and retired during the strategy-portfolio and bucket-keyed eras (V1–V4, roughly
> Feb–Jun 2026), distilled from the V4-era *Strategy Encyclopedia* (211 live plugins across 9 families
> at its peak, 2026-06-16). It exists so a public reader can see **what was tried and why it was
> retired** without wading through the full plugin dump (archived at
> `/SCROOGE ARCHIVE/docs-harvest/v4-repo-docs/STRATEGY_ENCYCLOPEDIA.md`).
>
> **The whole roster is retired.** At the V5 cell-era cutover (2026-07-04) named strategies were
> abolished: the (pair × session) **cell** became the unit of decision, and no strategy trades under
> its own name any more. What follows is a graveyard tour, not a menu. All performance figures are
> **sim** (8-year backtest, `net_ratchet` label) and most predate the H1-leak repair (B-078), so their
> magnitudes are **upper bounds**. See [`../../RESEARCH_PROGRAM.md`](../../RESEARCH_PROGRAM.md) H2/H3 for
> why the strategy framing itself was superseded.

---

## The one structural lesson

Before the catalog: the encyclopedia's own headline finding was that **all 128 baseline buckets were
net-negative** — a strategy's edge, where it existed at all, lived only in *brain-filtered firings*, not
in the strategy standalone. Two independent models agreed (r = 0.96) that expected value is driven by
alignment × volatility state, and SHAP gave the strategy identity **zero weight**. Everything below is
therefore a catalog of *triggers* whose value was conditional on state — and most of whose apparent
edge did not survive honest per-bucket, walk-forward, and survivorship testing.

---

## Families that were built and retired

| Family | Thesis (as held) | Why retired |
|---|---|---|
| **Darvas / box-liquidity (V1)** | Daily PDH/PDL boxes, sucker-moves, "John Wick" / power-of-towers liquidity sweeps can be automated rule-for-rule | Box geometry was contaminated by its own bugs (inverted boxes, stale slices, midnight reset amnesia — B-068→B-074); any "edge" was inseparable from the defects. Superseded at V2/V3. |
| **Textbook alphas** (alpha_pullback, alpha_breakout_retest, alpha_extended_fade, bravo_expansion_continuation) | Classic pullback / breakout-retest / extended-fade / expansion-continuation setups each carry edge | Demoted to thin cells: their pooled "staircase" profiles were exposed as **selection leakage**. 4 of 7 survived only inside specific (pair × session × direction) buckets (as `bk_v4_*`); the rest were genuinely dead. |
| **Textbook — genuinely dead** (TF2_pullback_EMA20_short, delta_tag_and_go_v2, echo_box_fade_v2, charlie_compression_breakout) | Same premise, other setups | Zero surviving buckets under per-bucket K=2 refit. Falsified. |
| **Mean-reversion fades** (bb_reversion_fade, williams_extreme_fade, zscore_extreme_fade, vol_coil_fade) | Fade Bollinger / Williams / z-score / volatility-coil extremes back to the mean | Walk-forward audited as **bleeders** ("leakers"); the Bollinger-mean-reversion and RSI-fade theses do not survive honest per-bucket testing — they only "work" inside cells that already won. |
| **AEF — alpha_extended_fade_v2** | A Wilder-RSI + pin-bar fade (the 47-year-old Connors lineage) is the one flat-profile, leakage-free performer | The best-behaved textbook strategy (+2.46…+2.99p *every year* for 8 years, sim); traded the book solo in the AEF-only experiment. Retired with the whole roster at cell cutover, but its *profile* (flat, leak-free, direction-keyed) is the template the cell era chased. |
| **ML-discovered conjunctions** (bk_K=2, bk_disco_K2/K3/K4) | An ML can mine raw indicator-band conjunctions per bucket that beat human strategies | 28 of 60 disco candidates survived walk-forward; the rest disabled as in-sample overfit. The survivors' edge was later shown **collinear and concentrated** (AUD_JPY shorts) and did not clear cost live. |
| **ML-authored trend-pullback** (ml_tp_*) | The ML authors 30 new strategies from an unbiased all-bars corpus; trend-pullback generalizes | Strong OOS backtest (51/52 positive, +8.42p unseen) but the family was retired at cell cutover; the edge was one narrow phenomenon, not a portfolio (see [`../PAPER_edge_hunt_falsifications_2026-07-14.md`](../PAPER_edge_hunt_falsifications_2026-07-14.md)). |
| **Amplifier-rescue shorts** (bk_amp_*) | Some flat-baseline strategies rocket when filtered to high-volatility regime alone | 8 cells found — **every one a SHORT** (confirming shorts amplify more in high vol: 2.71× vs longs 2.49×). Retired with the roster; the vol-amplifier *finding* carried forward into exit geometry, the strategies did not. |
| **Box / double-Bollinger** (bk_box) | Pure box-theory / double-Bollinger-band structure | Only 2 of 284 walk-forward survivors — the family barely existed after honest testing. Retired. |

---

## The direction detector (also retired)

Alongside the strategies, V4/V5 ran a **direction detector** — per-(pair × session × direction)
isotonic-calibrated probability models (Phase 2: 104 cells on the cost-aware label, median OOF accuracy
68.9%, 57 of 92 cells walk-forward-activated). Its most surprising result — USD_JPY, a flagship pair,
had only 1 of 11 cells activate, while USD_CHF/asia/short came in as the single most predictable cell
(77.3% OOF) — is a good example of the aggregate hiding session-level structure. The `certainty`-era
detector (`direction_v2`/`momentum_v3`) was **archived at the cell-era cutover** (2026-07-04, rollback
tag `pre-cell-cutover-2026-07-04`): raw-indicator locks survived re-derivation verbatim, but the
composite "certainty" scores were proxies at best and were not carried into the cell era.

---

## What actually carried forward

Almost none of the strategies; several of the *findings*:
- **The cell** (pair × session × direction) as the unit of decision — the encyclopedia's own "edge
  lives in brain-filtered bucket firings" is the seed of the entire V5 architecture.
- **The volatility amplifier** (vol expands short magnitudes more than long) — carried into exit
  geometry, not entries.
- **Brock's pip-utility objective** and the **no-bias training** principle.
- **The walk-forward gate as the activation primitive** — nothing wires live until it earns it on
  unseen forward data.

Everything else is in the graveyard, referenced and reproducible, not carried. For the full plugin-level
detail (specs, conditions, per-bucket survival), see the archived encyclopedia and
`/SCROOGE ARCHIVE/docs-harvest/v4-repo-docs/`.
