# Papers

Formalized write-ups of the program's strongest research arcs. Each paper has a fixed structure —
**Abstract · Background · Method · Results · Limitations · Data availability** — and scopes every
number as **sim** (backtest), **live** (bot journal/intent), or **broker** (OANDA fills, the only
trade-truth). Start with [`../RESEARCH_PROGRAM.md`](../RESEARCH_PROGRAM.md) for the hypothesis ledger
that ties these together, and [`../SCROOGE_HISTORY.md`](../SCROOGE_HISTORY.md) for the chronological
narrative.

## Current papers

| Paper | Date | What it establishes |
|---|---|---|
| [`PAPER_edge_hunt_falsifications_2026-07-14.md`](PAPER_edge_hunt_falsifications_2026-07-14.md) | 2026-07-14 | **The flagship result.** Five structurally distinct price-edge families falsified at one wall (edge < cost); the survivorship-bias discovery in the stop-tuning doctrine; the wide-stop turn. |
| [`PAPER_h6_walkforward_2026-07-16.md`](PAPER_h6_walkforward_2026-07-16.md) | 2026-07-16 | **The capstone — recommended last read.** The pre-registered walk-forward + slippage test of the wide-stop thesis, the program's final open hypothesis: net test Sharpe 0.03 vs the 0.70 bar, gross 1.26 without slippage, knife-edge ~0.4p round-trip. H6 falsified as-tested; the ledger closes with no surviving price-prediction hypothesis. |
| [`PAPER_methodology_overhaul_2026-06-21.md`](PAPER_methodology_overhaul_2026-06-21.md) | 2026-06-21 | **The measurement standards.** Broker-truth over journal, forward-pip over realized P/L, walk-forward, per-cell resolution — and the NY-fade discovery that fell out of applying them. |
| [`PAPER_ml_program.md`](PAPER_ml_program.md) | 2026-07-16 (covers 2026-05 → 07) | **The machine-learning arc.** Direction ML, the pips_brain v3→v4 "no bias" rebuild, the exit-brain family, BUCKET21 + TAKE/AVOID maps, the strategy-discovery engine, the sealed ML Lab, the pattern loop — and why the cell-era bot runs no live ML (measurement beat modeling). |
| [`../PAPER_cost_aware_exit_classes_2026-07-05.md`](../PAPER_cost_aware_exit_classes_2026-07-05.md) | 2026-07-05 | **The live exit doctrine** (kept at its established path; linked from the top-level README). Per-cell transaction cost from 963 broker fills (~83% of the loss window was spread); the three-speed FAST/MEDIUM/LONG exit book; a third independent confirmation that features predict WHEN and HOW FAR but never WHICH WAY (0/144 signed-direction). |

## Historical papers ([`historical/`](historical/))

Primary sources preserved verbatim, each prefaced with a clearly-marked historical notice (what era, what
it believed, what later revised it, why it is kept). These are **artifacts of hypotheses the program
held and revised** — not current doctrine.

| Paper | Era | Preserved because |
|---|---|---|
| [`historical/StrategyE_EURUSD_whitepaper_2026-06.md`](historical/StrategyE_EURUSD_whitepaper_2026-06.md) | V3 (Jun 2026) | The cleanest written statement of the strategy-portfolio thesis (H2); the conditional-cell insight it isolates seeded the entire cell architecture even as its "strategy" framing was superseded. |
| [`historical/RETIRED_STRATEGIES.md`](historical/RETIRED_STRATEGIES.md) | V1–V4 | A condensed catalog (name · thesis · why retired) of the strategy families the program built and abolished, distilled from the 211-plugin V4 encyclopedia. |

## Data and models

Every corpus and retired model behind these papers is publicly downloadable — see
[`../DATA_AND_MODELS.md`](../DATA_AND_MODELS.md) for the full catalog (archive link, per-artifact
leak status, load hints).

## Reading the numbers

- **The dividing line is 2026-07-03** (the H1 look-ahead leak repair, B-078). Any headline number whose
  primary evidence came from H1-parquet features before that date is an **upper bound**, not ground
  truth. Papers say so where it applies.
- **A mechanism can stand while its magnitude is an upper bound** — the NY-fade *direction* survived the
  leak repair; its per-cell *magnitudes* did not.
- **Nothing promotes to live on a sim alone.** The validation protocol (walk-forward + broker veto +
  drift labels + n ≥ 20 per cell) lives in [`../../research/README.md`](../../research/README.md).
