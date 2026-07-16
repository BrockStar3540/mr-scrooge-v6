# Roadmap

What's open and what's next, in rough priority order. Items move into [CHANGELOG.md](../CHANGELOG.md) when shipped.

## In-flight

### Decide on ratchet retune (commit `249f970`)

Live config currently has `step_trigger=7.5 / trail=2.5 / size=2.5`. Diagnosed 2026-06-19 as the cause of a -612 USD swing — ~50% of winners peak in +4.5-7.5p and now never arm. Three paths:

- **Revert** to OLD `4.5 / 1.5 / 5.0`.
- **Hybrid** `4.5 / 2.5 / 2.5` — keep the new step+trail shape, lower the trigger.
- **Keep current** — accept the new trade distribution.

The launch-week smoke data is archived under `/SCROOGE ARCHIVE/session-notes/2026-06-19_*` (indexed in [research/README.md](../research/README.md) §4).

### Activate direction_v2 + momentum_v3

Staged but not imported by engine.py. Activation: single import swap + add `direction` arg to `momentum.stamp()`. See [DEPLOYMENT.md](DEPLOYMENT.md). Recommended path = shadow-mode logging for 3-5 days first to compare v1 vs v2/v3 stamps on the same trades.

### Wire shadow-mode logging

Modify `engine.py` to import both v1 and v2/v3 each cycle and log both `DirectionStamp` and `MomentumStamp` results. Don't act on v2/v3 — let v1 still drive trades. After 3-5 days, compare:

- v3-rejected entries — did the trades v1 took but v3 would have blocked actually lose money?
- v2 dual-compute — does the long_score vs short_score split match what v1 picked?

If yes, swap to v3. If no, refine the cell assignments before activating.

## Near-term

### Per-(pair × session × direction) calibration anchors

The D1/D10 normalization anchors in `data/factor_sweep.json` are per-(pair × session) only. Adding a direction axis would require re-running the aggregator sweep on lab hardware with the long/short split. ~24h compute. Currently the per-direction modules use the same anchors for both directions, which is fine for now but limits per-direction precision.

### Per-direction `expected_pips` scaler

`momentum_profiles.PAIR_TUNING[pair]['expected_pips_scaler']` is per-pair only. The matrix work hints that asia/JPY shorts have a smaller typical pip distribution than asia/JPY longs (in cells where we have both). A per-(pair × direction) scaler would match.

### Direction-aware aggregator rules

The 3 aggregator amplifier rules in `direction_profiles.AGGREGATOR_RULES` are symmetric. With direction in the key now, some rules might be direction-specific. Need 100+ more trades before we have enough per-direction evidence to differentiate.

## Mid-term

### Self-evaluating ML — Path B

The nightly smoke cron writes `all_trades_per_feature.csv` (seed committed at `research/live-smoke/all_trades_per_feature_seed.csv`; the running series is archived). After 5-10 trading days (target: 200+ trades), we can train a per-cell ML that:

- Predicts pip_high MFE given the entry-time features
- Identifies cells where V5's expected_pips is over/under-estimating
- Refines the per-cell profile assignments

Path B = a lab-hardware job (never the live-trader host) that ingests the smoke CSV monthly + regenerates the profile assignments. Build deferred until N ≥ 200 trades accumulated.

### Reassess profile assignments

The current profile assignments are based on 44 trades + matrix-level inference. Many cells are NO_DATA. After 200+ more trades:

- Cells currently at WEAK / NO_DATA should be upgraded to MEDIUM / STRONG if evidence accrues.
- Cells currently at BAD should be re-evaluated — strict floors may need tuning down.
- New profile templates may emerge (e.g., London might split into "exhaustion" vs "fresh-breakout" depending on time-of-day within the session).

### Volume / liquidity features

OANDA M5 tick volume correlated +0.084 with peak_pips at N=44 — basically noise. Worth re-checking at N=200+. `rvol_5bar`/`rvol_12bar` (already on the view) correlated +0.67 in asia specifically — that's why asia_volume_rev uses them. Other sessions don't show the signal; revisit after more data.

## Long-term

### Per-pair direction modules with their own MarketView features

Currently every pair sees the same 24 direction features. Some pairs may have idiosyncratic predictors (e.g., USD_CAD vs oil price, AUD_JPY vs Nikkei). Adding per-pair feature sets is a substantial refactor of MarketView + engine, deferred unless evidence shows pair-specific predictors would help.

### Backtest harness

V5 doesn't have a proper backtest harness yet — all validation is live or via a lab-hardware aggregator sweep on the 7.5yr OANDA corpus. A walk-forward backtest harness that runs the full pipeline (Direction → Momentum → Playmaker → Ratchet) against historical candles would let us validate config changes before shipping.

### Cross-broker validation

The 2026-06-18 forexsb.com H1 cross-validation showed broker-portable methodology. Periodically re-run with fresh data from a second broker (forexsb, FXCM, or similar) to catch broker-specific biases.

## Off-roadmap (parked)

- Multi-account support. V5 trades a single OANDA practice account. Live + multiple accounts is a bigger refactor; not on the roadmap.
- Crypto support. Out of scope.
- Discretionary override UI. The dashboard is observation-only by design — no manual trade buttons.

## How items move on/off the roadmap

- A new research session (diaries archived under `/SCROOGE ARCHIVE/session-notes/`, indexed in [research/README.md](../research/README.md)) often surfaces new items.
- Items in flight have a session folder + a CHANGELOG entry when they land.
- "Off-roadmap" items stay here as a record of "considered, not pursuing."
