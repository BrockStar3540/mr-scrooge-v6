# Data & Models — the Public Availability Catalog

> **Availability (updated 2026-07-18):** the public [archive link](https://www.dropbox.com/scl/fo/uyjwoj274ndzqg98ol72p/AEB6zn4q-jFexhZxVmYFRyc?rlkey=a06ocaqxuyz4at1dfkjmww1i9&st=kup4s0x9&dl=0) now holds the **readable research record** — papers, session notes, backtest results, version history. The **raw corpora and trained-model binaries catalogued below are privately archived** (they are bulk data / code with no public-safe form) and are **available on request** — open a [Discussion](https://github.com/BrockStar3540/mr-scrooge-v6/discussions) if you want a specific corpus or model to re-run the analysis. The catalog below documents each one (schema, era, leak status) as the reference of record.

Everything the research rests on — every retired model and every corpus — is downloadable, testable,
and modifiable. This page is the catalog: what each artifact is, what it was trained/built on, its era,
and **its leak status**, so a public reader can re-run or challenge any result in
[`RESEARCH_PROGRAM.md`](RESEARCH_PROGRAM.md), [`papers/`](papers/), or [`SCROOGE_HISTORY.md`](SCROOGE_HISTORY.md).

> **Public archive (read-only Dropbox share):**
> https://www.dropbox.com/scl/fo/uyjwoj274ndzqg98ol72p/AEB6zn4q-jFexhZxVmYFRyc?rlkey=a06ocaqxuyz4at1dfkjmww1i9&st=kup4s0x9&dl=0
>
> Entry points inside the archive: `00_MASTER_INDEX.md` (updated 2026-07-29 — lists every private
> holding with size + content hash), `00_MANIFEST.json` (machine-readable listing of every file in
> both trees with Dropbox content hashes — verify downloads against it), `00_HISTORY_V1-V6.md`,
> `00_BOOK_OF_BUGS_V4-V5.md`.
>
> **WAVE-1 DATA RELEASE (2026-07-29): the seven core data corpora are now PUBLIC** in the
> archive's `research-corpora/` (~5.4 GB): `qtl-discovery-8yr` (clean 8yr OHLCV+feature
> parquets, per pair), `v5-truth-matrix` (8 pairs × 8yr simulated entries w/ forward
> MFE/MAE), `continuous_corpus` + `continuous_corpus_unbiased`, `allbars_corpus`,
> `factor_lift_v1`, and `forexsb_h1` (the raw H1 source). Each was hash-verified,
> content-listed, secret-swept (0 hits) and column-audited (0 account-linked fields)
> before publication; verify downloads against `00_MANIFEST.json`. Remaining holdings
> (model binaries, code mirrors) stay in the private annex — request by name in a
> [Discussion](https://github.com/BrockStar3540/mr-scrooge-v6/discussions).

**How to read leak status** (full rules: [`../research/README.md`](../research/README.md) truth
hierarchy): the dividing line is **2026-07-03**, when the H1 look-ahead leak (**B-078**) was found and
repaired — research parquets had joined H1 features on open-time, injecting up to 55 minutes of future
bar. Labels used here:

- **CLEAN** — raw market data, broker fills, M5-only features, or corpus rebuilt post-fix.
- **TAINTED-H1** — contains H1-derived features built before 2026-07-03. Research numbers computed from
  it are **upper bounds** (some historically inflated 8–15×). Fine for method replication and as a
  cautionary dataset; do not promote its magnitudes.
- **MIXED / UNKNOWN** — contains both, or contents not re-audited; treat H1-feature artifacts inside it
  dated before 2026-07-03 as tainted.

---

## Models — private annex, `research-corpora/` (by machine of origin)

All tree models are LightGBM unless noted; `model.txt` artifacts load with
`lightgbm.Booster(model_file="model.txt")`, with feature order/categorical levels in the accompanying
`feature_meta.json` (the V3-era "v0 format"). Context for every system:
[`papers/PAPER_ml_program.md`](papers/PAPER_ml_program.md).

| Tarball | What it is | Framework | Training data + objective | Era | Size |
|---|---|---|---|---|---|
| `pips_brain_v3_2026-06-13.tar.gz` | The pre-ratchet entry-brain package as of 2026-06-13 — the raw-continuous **net_ladder committee** era (`p7`/`pmom`/`pfast`/`pbig`/`eoffer` heads, floor 0.65) that gated V4 entries before the utility rebuild | LightGBM | strategy-fire corpus labeled with the capped `net_ladder` exit; raw continuous outcome targets | V3/V4 boundary (retired as live gate 2026-06-13; retained as harvest-mode fallback) | 31 MB |
| `pips_brain_v4.tar.gz` | The **pip-utility brain**: single regressor predicting `E[utility]` on `net_ratchet`; the "no bias in training" rebuild (all features, all trades, utility objective; floor = top-2%). Includes the golden set used to arm serving | LightGBM | 4M-trade relabeled corpus (8 pairs, 8yr, `net_ratchet` label, ~57 raw indicators); objective = Brock pip-utility curve (floor +6, 20+/30+ bonuses, losses ≥6p ×2) | V4 (live 2026-06-13 → 06-18) | 315 MB |
| `direction_ml.tar.gz` | The **direction-ML era** working tree: training runs and artifacts of the per-cell direction classifiers (the direct attack on hypothesis H1) | LightGBM (+ isotonic calibration) | per-(pair × session[, direction]) cells; Phase 1 `price_move > 0` labels, Phase 2 cost-aware labels | V4/V5 (Jun 2026) | 1.28 GB |
| `direction_artifacts_v2.tar.gz` | **Phase-2 direction detector** artifacts: 104 per-(pair × session × direction) calibrated boosters, walk-forward activation flags (57/92 activated; median OOF 68.9%), per-cell baseline ATR for the vol-amplifier `ev_pips` | LightGBM + isotonic | cost-aware label (`net > 0`), walk-forward gated | V4 Act XV (2026-06-15/16) | 18 MB |
| `factor_lift_v1.tar.gz` | The **factor-lift rig + verdicts**: `factor_lift_substrate.parquet` (885,698-row parity-locked corpus), `factor_lift_matrix_FULL.parquet` (4,736 cell×factor lift tests), `factor_value_bands.parquet` (48,421 value-band rows), `validated_value_bands.json` (49 adversarially-validated bands — all AUD_JPY shorts), `factor_veto.json`. The rig that proved the survivors collinear | rig: LightGBM two-head + permutation/BH-FDR scripts | walk-forward 2019-22 IN / 2023-26 OOS | V4 (2026-06-16) | 247 MB |
| `ml-observer-v3era.tar.gz` | The **V3-era live ML observer**: the per-pair win/loss rule modules + centroids (the frozen lookup-table "edge" the 2026-06-04 audit exposed), plus the observer scaffolding | pickle/CSV rule tables + LightGBM v0 gate lineage | V3 live scans + replay outcomes | V3 (≤ Jun 2026) | 190 MB |
| `v4-models-artifacts.tar.gz` | The **V4 `models/` tree**: the BUCKET21 brain series (v3 → v17 incl. pruned-map v12, direction-feature v15, amplifier v16/v17), `bucket_take_avoid_maps.json` (1,769 TAKE + 16,026 AVOID conjunctions, post-walk-forward-prune), golden sets, `strategies.json` plugin specs, the continuous exit brain (`exit_serving_cont`, holdout corr 0.87) | LightGBM + XGBoost (exit brain) | `util(net_real)` (realistic-cost utility, 3–4p slippage in the label) | V4 endgame (2026-06-15 → 18) | packaged from the V4 repo mirror during the consolidation |

**Quickstart (documented pattern).** The utility/BUCKET21 brains score a candidate row of raw
indicator values + categorical `pair`/`session`/`direction`(/`strategy`) in the exact order given by
`feature_meta.json`, then gate at the recorded floor: `take = booster.predict(row) >= floor`. The
serving wrappers (`models/pips_brain_util.py`, `models/exit_serving_cont.py`) with golden-set checks
ship inside `v4-models-artifacts.tar.gz` / the V4 repo mirror. **Parity warning from the era:** verify
your feature feed against `feature_meta.json` before trusting any output — two of this program's worst
bugs were models silently fed dead or truncated features (B-085; the 60-bar `OBV_z` NaN bug).

---

## Corpora — private annex, `research-corpora/` (by machine of origin)

| Tarball | Contents / schema | Granularity · window | Leak status | Size |
|---|---|---|---|---|
| `continuous_corpus.tar.gz` | The V4 **continuous-learning base corpus** (`labeled_ratchet_sample` lineage, ~907k rows at final backfill): strategy-fire rows with ~57–65 raw indicators, pair/session/direction/strategy identity, `net_ratchet` labels | M5 entries · 8 pairs · 2019-07 → 2026-06 | **TAINTED-H1** — built pre-2026-07-03 with H1-derived features (`trend_1h/4h`, `atr_1h`, …); treat derived research numbers as upper bounds | 825 MB |
| `continuous_corpus_unbiased.tar.gz` | The **unbiased variant** of the above (no threshold targets, no curated trades — the "no bias in training" rebuild input) | M5 entries · 8 pairs · 2019-07 → 2026-06 | **TAINTED-H1** (same basis) | 988 MB |
| `allbars_corpus.tar.gz` | The **all-bars discovery corpus**: ~674k rows, *every* bar sampled (~45k/pair), BOTH directions, `net_ratchet`-labeled — the input that de-biased strategy discovery from where-humans-fire | M5 · 8 pairs · 7yr (2019 → 2026) | **TAINTED-H1** (pre-fix build; H1 features present). The discovery *method* replicates on it; magnitudes are upper bounds | 133 MB |
| `qtl-discovery-8yr.tar.gz` | 8yr per-pair **M5/H1/D feature parquets rebuilt after the leak fix**, + the master-matrix archive | M5/H1/D · 8 pairs · 8yr | **CLEAN** (post-fix rebuild — this is the leak-safe replacement corpus) | 1.58 GB |
| `v5-truth-matrix.tar.gz` | **The primary reference corpus**: per-bar dual-direction forward MFE/MAE (60m/240m), 8 pairs × 8yr, broker-anchored r = 0.84–0.90 on ~155 V5 trades — the basis of the exit classes, fill probabilities, and the 0/144 direction result | per-M5-bar forward paths · 8 pairs · 8yr | **CLEAN** (leak-clean build, broker-anchored) | 1.65 GB |
| `forexsb_h1.tar.gz` | Third-party **raw H1 OHLC** history (ForexSB export) used for long-window cross-checks | H1 candles | **CLEAN** (raw candles; the leak is a feature-join artifact, not source data) | 13 MB |
| `factory_dukascopy_raw.tar.gz` | **Raw Dukascopy price data** downloaded for the V3 factory era (independent-broker cross-check of OANDA candles) | raw bars/ticks as downloaded (schema not re-audited; V3 factory era) | **CLEAN** as raw data; **UNKNOWN** internal layout — inspect before use | 454 MB |
| `v5-research-archive-2026-07.tar.gz` | The consolidated **V5 research working tree**: ratchet-EV sweeps, exit sweeps, the 48-cell calibration artifact, discovery-v2, atrrel-confirm, replay-gate | mixed artifacts · Jun–Jul 2026 | **MIXED** — spans the 2026-07-03 fix; anything H1-feature-based inside it dated pre-fix is tainted, post-fix and broker-anchored artifacts are clean. Check each artifact's date | 2.23 GB |

**Also in the archive (context, not part of this catalog's guarantee):** full V3/V4 repo mirrors
(`mr-scrooge-v3-full`, `MR-SCROOGE-V4-MIRROR`), the research/lab script bundles
(`scrooge_research_scripts.tar.gz` — build_allbars / discover_NxM / walkfwd / retrain scripts;
`scrooge_lab_code.tar.gz`), lab datasets, and git mirrors under the former `research-corpora/`
subtrees; the session diaries under `/SCROOGE/SCROOGE ARCHIVE/session-notes/`; and the retired repo docs under
`/SCROOGE/SCROOGE ARCHIVE/docs-harvest/`. Indexed in [`../research/README.md`](../research/README.md) §4.

---

## Using this catalog honestly

1. **Reproduce, then challenge.** Every paper's Data-availability section names the corpus its numbers
   came from. The highest-value external contribution is re-running a claim on the CLEAN corpora — or
   demonstrating that a CLEAN-labeled artifact isn't.
2. **Respect the scopes.** sim ≠ live ≠ broker. A corpus label (`net_ratchet`) is a *simulated exit*
   with ~1p assumed cost; the real trail slipped 3–5p (this gap killed a live deployment — see the ML
   paper §6).
3. **The validation protocol applies to you too.** Walk-forward split, trimmed means, full-population
   (not winners-only) stop statistics, n ≥ 20 per cell:
   [`../research/README.md`](../research/README.md) §3.
4. **No live-trading surface.** The archive contains no credentials, no account identifiers, and no
   execution paths; it is research material only.
