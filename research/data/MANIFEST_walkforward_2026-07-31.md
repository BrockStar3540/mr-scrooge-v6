# Δ_hot walk-forward — published-run manifest (2026-07-31)

Dataset: `walkforward_cycles_2026-07-31_prefix.json` — the EXACT virtual-cycle
set behind the published first-run numbers (Δ_hot quartile −0.052 FAILED;
top-K=4 book +0.204 vs random +0.135 — exploratory, NOT validated).

Built by `research/tools/delta_hot_walkforward.py` at engine v6.14.3:
- 102 cells, era episodes since 2026-07-04, ≤12 cycles/cell, 2.5d windows
- FAMILY_PP variant, entries at first-bar open, CONFIG gear (not stamped),
  marker-price popper fills — all three superseded by the external-review
  fixes in v6.14.7 (stamped entries + stamped gear + gap-aware fills)
- censored cycles excluded by design (charter: an open cycle is not an outcome)

Status of the top-K result per the review: a NEW hypothesis. Requirements
before it can gate anything: an unseen forward period, block-bootstrap CIs,
reproduction of the live selector's simultaneous candidate set, and a fresh
dataset under the fixed engine (delete data/walkforward_cycles.json to
rebuild). The adaptive selector ships DIAGNOSTIC-ONLY meanwhile.
