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
