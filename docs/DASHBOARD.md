# The Enhanced Dashboard (2026-07-31)

Born from a six-repo external audit (see `docs/slates/external_repos_audit_2026-07-31.md`):
none of the audited bots had a demonstrated edge, but two had presentation ideas worth
stealing. Everything borrowed was re-based on Scrooge's own units — family cycles, risk
units, broker truth — never heuristic "confidence."

## SHADOW tab additions

- **Evidence accounting chips** (TradeClaw-inspired): era episodes with censored/open
  counts, completed family cycles, and data freshness (board age, heat-file age).
  Counted vs excluded is always visible — a number with no denominator is a lie.
- **Risk truth**: families with open legs and the total **open floor** — realized P/L if
  every open leg's current stop executed now. Judge-when-flat ≠ risk-invisible-while-open.
- **⚖️ Governor decision ledger** (collapsible): every flip, admission, veto, era reset
  and Commissioner transition, newest first, with its full reason. The operator contract:
  the machine flips its own switches and says why.

## Prospective snapshots + Δ_promotion

Every governor run appends decision-time scores (heat, trust, eligibility, promotion) to
`data/score_snapshots.jsonl` **before outcomes exist** — hindsight-proof by construction.
`research/tools/delta_promotion.py` joins each snapshot to the setup's next completed
broker family cycle and reports

    Δ_promotion = E[R_next | promoted] − E[R_next | eligible but not promoted]

— whether the selector adds value over its own eligibility pool. It withholds a verdict
below 5 joined outcomes per arm; an empty report today is the correct report.

## External-strategy trial docket

42 zero-authority shadows from the two audit survivors (both MIT):
- `tc_vwapbb_{long,short}` — TradeClaw's trend-conditioned VWAP–EMA–Bollinger pullback
  (24 cells; its own costed test was NEGATIVE — that fact is in each cell's evidence note).
- `es_trend_long` / `es_meanrev_short` / `es_breakout_long` — EuroScope's regime-routed
  split via the new `adx14` feed feature (18 cells).

New feed features for these trials: `vwap_dist_pips` (session-anchored VWAP distance),
`adx14` (H1 Wilder ADX). All 42 enter as SHADOW at ev_seq 0.0 and earn any seat
exclusively through family-cycle evidence — the same door as everyone else.

## The Signal Command Center (`/signals`, v6.34.0)

A read-only watch page for **manual trading**, linked from the nav (⚡ SIGNALS).
Every qualifying setup — ACTIVE, PROBE and SHADOW — stamps once per 5-min scan
while its entry conditions hold, so the page shows exactly which signals are
firing *right now*, grouped by pair and direction; a signal drops off ~7.5 min
after its trigger window closes (conditions fail, session ends, entry cutoff).

Each firing signal contributes `status_weight x 0.6^strikes x evidence` pips
toward its side (ACTIVE 1.0 / PROBE 0.6 / SHADOW 0.25; governor strikes
permanently discount a setup's say, mirroring three-strikes). Evidence
(v6.36.0) = 0.5*broker truth + 0.3*era avg + 0.2*7-day form, renormalized
over available parts: broker truth is the governor's 21-day trust score of
REAL completed family cycles (decayed mean R x 60p, shrunk n/(n+4)) — banked
fills outrank the simulator; sim parts are sample-size shrunk `x*n/(n+8)`.
v6.37.0 adds path shape: contributions scale by 1 + 0.5*tilt*sign(evidence),
tilt = (MFE-MAE)/(MFE+MAE) from era-median excursions (neutral under 5
episodes) — own-side pushes want MFE-heavy paths, CONTRA pushes want
MAE-heavy paths (the MAE-flip doctrine, wired in literally). Cards gain
tgt/heat: contribution-weighted typical favorable/adverse excursion of the
aligned signals, excursions swapped for contra contributors. A firing setup with **negative** evidence
pushes the **opposite** direction (the MAE-flip doctrine) and is tagged CONTRA.
Per pair: `confidence = 100*tanh(|net|/8)*(0.5+0.5*agreement)`, expected
distance = contribution-weighted pips of net-aligned signals, and **est. time
in trade** = contribution-weighted median realized hold from the shadow-sim
episode store (`exit_bar x 5m`, censored episodes excluded; horizon fallback).

Data layer: `ops/signal_center.py` (`GET /api/signal_center`, 45s cache,
leased-latch background refresh — journal parse + the 15MB episode store never
run inline in the single-threaded request handler). Strictly observational:
it reads the journal and existing evidence stores, never the trading path.

### Consensus track record (v6.35.0)

The command center grades itself. `ops/signal_snapshots.py` (cron `*/5`)
appends each pair's live consensus (direction, confidence, formula hash) to
`data/signal_calls.jsonl` — cron-driven, not pull-driven, so the record has no
viewer-shaped holes. `ops/signal_accuracy.py` (cron hourly) assembles
consecutive same-direction rows (gap <= 15m) into consensus episodes, scores
the FIRST snapshot of each run — the call — against forward executable M5
price (ask-entry long / bid-entry short, opposite-side exits, spread honestly
paid) at +30m/+1h/+2h/+4h/+8h checkpoints, and rebuilds aggregates into
`data/signal_accuracy.json`: overall, per confidence band (the calibration
table — does conf 70 actually beat conf 30?), and per pair x direction (each
card's `hist` badge). Checkpoints index trading bars, so weekend gaps do not
distort; unscoreable checkpoints wait rather than being discarded (the B-129
censoring lesson). Samples are segmented by the scoring-formula hash — any
weight change starts a fresh sample, never blending eras. Served by
`GET /api/signal_accuracy` (aggregates only; episode bulk stays on disk).
