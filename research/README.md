# Research

Every substantive research session that informed a V5 change. Cross-referenced so future sessions can be **circumspect of existing findings** and **rigorously cross-check** new ones against the corpus already in here.

---

## (a) CURRENT TRUTH — Post-2026-07-03 Foundation

**The dividing line is 2026-07-03.** On that date the H1 look-ahead leak was discovered and repaired: previous research corpus joins used open-time for H1 features, injecting up to 55 minutes of future bar data. All headline numbers from sessions whose primary evidence came from H1-parquet features before this fix are **upper bounds, not ground truth**. The clean anchors are: broker-trade measurements, M5-based features, and any corpus rebuilt post-fix.

### Authoritative session directories

| Session dir | What it contains | Status |
|---|---|---|
| `sessions/2026-07-05_ratchet_profiles/` | **Three-speed exit classes.** Walk-forward 2026 corpus: direction from features 0/144 robust (3rd falsification of WHICH-WAY), travel 113 robust (atr_5m rho 0.4-0.7 = the ratchet distance knob), 24 cells classed QUICK-SLICE(8, 7=NY)/STANDARD(8)/RUNNER(8, asia+london), lock fill probabilities at L=2/3/5/8. Basis of the 2026-07-05 live exit-class deployment. Paper: `docs/PAPER_cost_aware_exit_classes_2026-07-05.md`. | **CURRENT TRUTH** |
| `sessions/2026-07-04_trade_excursions_3wk/` | 230 broker trades since 06-13: M1-path MAE/MFE + duration + outcome + the 6 cell features at entry (corpus-exact formulas), grouped pair x session MAE-desc. Convergence check: MAE-dominant cells all NO-SIDE/killed in the cell book. Tool reusable on Mini ~/v5-trade-excursions/. | **CURRENT TRUTH** (broker-lineage) |
| `sessions/2026-07-04_cell_transaction_costs/` | **Cell-level transaction costs from broker fills** (OANDA export 05-31→07-03, 963 fills): RT spread cost per pair×session (AUD/USD 1.35p → EUR/JPY 2.8p; pair dominates, session ~flat), $18.6k spread tax vs −$22.5k net P/L (~83% of loss = cost), hour-21 UTC rollover 4–10× blowout, measured margin rates (2/3/5%) + $/pip asymmetry 4.1× under equal-margin sizing, per-cell cheese-slicer lock floors. Script reusable on any OANDA export. | **CURRENT TRUTH** (broker-lineage) |
| `sessions/2026-07-03_truth_matrix_envelope/` | **The Week's Truth Ledger.** Eight study reports embedded: TRUTH_MATRIX_REPORT (per-bar dual-direction fwd MFE/MAE 60m/240m, 8 pairs × 8yr, broker-anchored r=0.84–0.90), CALIBRATION_REPORT (48-cell artifact, MFE quantiles + ATR regression), LEAK_REPAIR_REPORT (H1 leak confirmed + fixed, parquets rebuilt), RATCHET_EV_REPORT (90-config geometry sweep), v5_mfe_study, v5_rederivation, v5_atrrel_confirm, NOTES (narrative + 07-03 trades). Raw Mini artifacts: ~/v5-truth-matrix/, ~/v5-ratchet-ev/, ~/v5-exit-sweep/, ~/v5-taint-rederivation/, ~/v5-cell-calibration/, ~/v5-discovery-v2/, ~/v5-atrrel-confirm/, ~/v5-mfe-study/ | **CURRENT TRUTH** |
| `sessions/2026-07-02_panel_and_5pair_sweep/` | 3-model panel (Opus/Sonnet/Haiku) + 7-pair broker-truth MAE/MFE sweep. Produced: two-layer-failure diagnosis (signal=wrong 2026 profiles, governance=winner-curse on n<10), constitution (n>=20 gate, inversion deprecated, locks provisional), shipped de-inversions + exposure cap + SHADOW_PROFILE. Mini replay gate: corrected profiles win 6/6 months 2026 +2.3-3.2p/call. All evidence: clean broker-trade lineage only. | **CURRENT TRUTH** |
| `sessions/2026-07-02_usdcad_deep_dive/` | USD_CAD per-trade MAE-flip analysis using broker fills. Produced aroon gate + per-direction inversion (MAE-flip doctrine first full wiring). | **CURRENT TRUTH** |
| `sessions/2026-07-01_cell_audit_throughput/` | USD_CHF/ny un-invert audit, USD_JPY/london LONG-ONLY wiring, engine multi-open fix, session widening; OANDA 72-trade broker audit (vs journal 56). All from OANDA API fills. | **CURRENT TRUTH** (broker-lineage) |
| `sessions/2026-07-01_full_audit_lock_guard/` | Lock guard enforcement design + USD_CHF kill + Mini cron defect fixes. | **CURRENT TRUTH** |

### Validation protocol (applies to all future research promoting to live config)

1. **Clean corpus only (2026-07-03+):** feature parquets rebuilt post-leak-fix (Mini `~/v5-parquets-clean/` or equivalent). Any H1-feature number from a pre-fix parquet is an upper bound; treat as directional, not precise.
2. **2026-fit promotes:** per-cell findings must show positive signal in the current 2026 window, not just 8yr average (regime shift: 2026 is mean-reverting vs trending 8yr average).
3. **Live vetoes:** broker-confirmed losing pattern (n>=5, consistent) overrides any backtest result. OANDA API is ground truth; bot journal is intent-only.
4. **Drift labels mandatory:** any per-cell lean must be tagged PERSISTENT (sign-stable across 6+ month window), REGIME (in-sample only), or FLICKER (EFI-class: highest corr, unstable). Only PERSISTENT ships to config.
5. **Plateau ranges:** for entry filter features, measure the width of the profitable plateau, not the peak. A narrow peak is an overfit relic.
6. **n >= 20 per cell, same-engine:** no per-cell governance action (disable/invert/gate) on fewer than 20 same-engine (v2/v3 module) trades from that cell. Thinner samples = watch only.

---

## (b) VALID LEGACY — Clean-Lineage Findings That Stand

These findings used M5 features, broker fills, or walk-forward methods not affected by the H1 look-ahead leak. They remain valid input to cell decisions.

| Finding | Session(s) | Summary | Caveat |
|---|---|---|---|
| **NY-fade (percell_exhaustion)** | `2026-06-21_percell_exhaustion/` | NY is a momentum-FADE session for ALL 8 pairs, walk-forward stable (train<2024, test>=2024). In NY, momentum signal direction tends to see the opposite 60m move. 8/8 pairs negative in both windows. | Per-cell magnitude varies; don't use NY-fade as a blanket INVERT rule — requires n>=20 per cell. The June inversion wave over-applied it. |
| **Broker validation forward-pip method** | `2026-06-21_broker_validation/`, `2026-06-21_real_oanda_trades/` | OANDA API (not journal) is the only ground truth. Use 1H forward pip (fresh candles) as entry-indicator evaluator, not realized P/L (which confounds exit choices). Manual closes must be included. Journal missed 70/120 trades. | Still valid; the OANDA API pull + forward-pip computation is the standard for any per-cell broker analysis (tool: `sessions/2026-06-23_aud_jpy_deep_dive/analyses/v5_pair_deep_dive.py`). |
| **Master matrix live/broker columns** | `2026-06-21_master_matrix/`, `2026-06-21_broker_validation/` | Per-(pair × session × direction) matrix with broker forward pip means; identified confirmed winner cells (USD_CAD/ny/long, EUR_USD/london/short) and disabled cells. | N was 5-9 trades per cell at time of derivation; those specific conclusions are early-era evidence. The METHOD (broker fwd pip per cell) is valid and is used in 07-02 and 07-03 work. |
| **Ratchet exit assessment** | `2026-06-23_ratchet_exit_assessment/` | Step-trail ratchet captures 73% of MFE on winners. Tighter bands (SL−4 @ MFE+4) would cost −36.9p across the live sample by converting 5 wobble-then-run winners to losers. Current ratchet bands validated on live filled trades (MFE/MAE reconstructed from OANDA M1). | n=14 inverted-live trades. Confirmed by 07-03 geometry sweep (90 configs, tighter exits +3.3p unconditional but population-mismatch on real fired entries). |
| **Entry-indicators vs MFE per-cell analysis** | `2026-06-23_entry_indicators_vs_mfe/` | Vortex_diff_h1 positive on 11/11 winners, negative on 3/3 losers in the 14-trade set. willr/aroonosc/kc_up_dist_pips identified as structural separators at per-cell level (shipped to live config). | n=14, all inverted-live trades. Direction of effect confirmed; magnitude and universality subject to per-cell re-measurement with larger n. |
| **Per-cell tightening LIVE-trade-derived gates** | `2026-06-23_per_cell_tightening/`, `2026-06-23_aud_jpy_deep_dive/`, `2026-06-30_usdjpy_audjpy_asia/` | Gates derived purely from broker fills: m_cert ceilings, d_cert floors/ceilings, willr_range, kc_up_range, aroon_range. Each derived from live per-trade MFE/MAE gap analysis (winners vs losers) without touching H1 parquets. | Individual gate thresholds were set on n=3-10 trades (Brock's intentional fast-feedback approach). Treat as provisional until n>=20 per cell confirms; monitor via locked_cell_monitor. |
| **MAE-flip doctrine / USD_CAD aroon gate** | `2026-07-02_usdcad_deep_dive/` | Losing cell with MAE >> MFE = right signal, wrong wiring → flip entry. USD_CAD: per-direction inversion + aroonosc_h1 range gate as separator. First clean MAE-flip implementation. | Doctrine validated on USD_CAD specifically; apply the method (n>=3x MAE:MFE asymmetry, n>=6 trades) to other cells, do not copy the USD_CAD thresholds. |

---

## (c) SUPERSEDED / TAINTED — Sessions Using Pre-Fix H1 Parquet Features

The following sessions used H1-feature parquets built with open-time joins (the pre-2026-07-03 leak). Their headline numbers are **upper bounds**; the leaky feature (especially `h1_ret_1bar`, `atr_h1_relative`, profile scores) was inflated relative to its true predictive power. Do NOT use their quantitative conclusions to set config thresholds. The sessions are retained for historical record and code reference.

| Session dir | Tainted claim | Why tainted | Clean anchor |
|---|---|---|---|
| `sessions/2026-06-18_aggregator_sweep/` | h1_ret_1bar #1 universal; atr_conc magnitude penalty | H1 features (atr_conc, h1_ret_1bar, atr_h1_rel) were primary sweep variables; all fed from leaked parquets | The atr_conc SCALE bug (fixed 07-03) also invalidated the absolute threshold; aroonosc result directionally correct, magnitude upper bound |
| `sessions/2026-06-20_qtl_8yr_per_cell/` | willr_m5 top-3 in 24/24 cells (mean ΔAUC +0.0052); aroon ±3.57 threshold magnitude | M5 willr result is clean (M5 features are tick-level, not H1); aroonosc_h1 threshold calibrated against leaked H1 rows | willr_m5 direction-of-effect confirmed by 07-03 discovery v2 (DIRECTION signals); aroon threshold must be re-derived on clean corpus |
| `sessions/2026-06-20_qtl_indicator_discovery/` | kurtosis_m5/bbwp_m5 looked strong (Δ+40.9pp WR) | 44-trade matrix used for the first cut was later shown (real_oanda_trades) to have missed 70 trades; small-N + combined with H1 sweep context | Refuted: at 8yr scale both fell to importance #20-21 (qtl_8yr_per_cell, which is itself H1-partial but the relative ranking of M5 features holds) |
| `sessions/2026-06-21_v5_2026_audit/` | 38/48 cells profile-mismatched (ΔAUC +0.0802); aggregator rule whitelist recommendations | The ΔAUC figures used the leaked H1 parquets; the +0.0802 headline was leak-fabricated (clean data shows the three weight profiles are near-indistinguishable, mean AUC lift ~0.011) | Panel session 07-02 confirmed direction of regime-shift finding (reversion > continuation in 2026) but magnitude is upper bound; the action (profile de-inversion + SHADOW_PROFILE) is grounded in 07-02 broker evidence |
| `sessions/2026-06-21_master_matrix/` | Per-cell broker_fwd_1h_mean_pip values; matrix column ΔAUC lifted cells | Broker columns are clean (derived from OANDA fills); ΔAUC columns used leaked parquets; master_matrix_monthly.sh cron output was also pre-leak | Broker-forward columns remain valid per-cell evidence; ΔAUC columns are upper bounds; matrix is superseded by 07-03 truth matrix and CAL artifact |
| `sessions/2026-06-21_percell_exhaustion/` | NY-fade magnitude figures (EUR_JPY/ny -1.31, USD_JPY/ny -0.96); session separation values | Walk-forward used per-cell M5 momentum separation (M5 features clean) but enriched with H1-feature-derived profile labels | Direction of finding (NY = fade, 8/8 pairs) is valid legacy (see §b above). Magnitude figures are H1-enriched upper bounds; re-derive from truth matrix if precise magnitude is needed |
| `sessions/2026-06-23_per_cell_tightening/` — BACKTEST THRESHOLDS only | 2026 backtest threshold values for willr, kc_up, m_cert, d_cert gates | Backtest corpus used H1 parquets; specific pip-uplift numbers (e.g., "willr filter +8.48p/70.2%") are upper bounds | The gates themselves (the mechanism, the which-cell choice, the direction of the separator) were live-trade-derived and stand. Only the quantitative backtest confidence is an upper bound. |
| `sessions/2026-06-21_cell_ruleset/` — PROFILE columns | Profile assignment recommendations (38 → reversion) | Profile scoring used leaked H1 feature AUC | Direction confirmed by panel; specific AUC deltas are upper bounds. Current live profiles are managed via SHADOW_PROFILE stamping and 07-02 de-inversion. |
| `sessions/2026-07-01_full_audit_lock_guard/` — EXIT SWEEP CONDITIONED TABLES | Conditioned ratchet EV tables from exit sweep v1 | Exit sweep v1 (pre 07-03) used leaked H1 features for conditioning variables | 07-03 re-ran the exit geometry sweep (90 configs) on clean corpus + broker-anchored truth matrix (see RATCHET_EV_REPORT in 2026-07-03 session). |

**See also:** `note_parquet_h1_leak_2026-07-03.md` in vault (memory key: `note_parquet_h1_leak`) — full technical details of the leak + fix + what it invalidates.

---

## (d) Mini Research Directories

All heavy compute runs on dedicated lab hardware (never the live-trader host). Key directories:

| Mini path | Contents | Notes |
|---|---|---|
| `~/v5-truth-matrix/` | Per-bar dual-direction fwd MFE/MAE excursion table, 8 pairs × 8yr, extended to 2026-07-03 | **Current ground truth.** Broker-anchored at r=0.84–0.90 on 155 V5 trades. |
| `~/v5-cell-calibration/` | Source for `config/cell_calibration.json` — MFE quantiles, ATR regression fits, winner-MAE, dead rates | Refreshed monthly by `v5_monthly_refit.sh` cron (0 5 1 * *) |
| `~/v5-ratchet-ev/` | 90-geometry exit sweep artifacts + ratchet_ev_cells.csv | 07-03 clean-corpus sweep; see RATCHET_EV_REPORT |
| `~/v5-exit-sweep/` | Raw exit config sweep output (per-config P&L tables) | Subset of ratchet-ev work |
| `~/v5-taint-rederivation/` | Rederivation of tainted sessions on clean corpus | See v5_rederivation_REPORT in 07-03 session dir |
| `~/v5-mfe-study/` | MFE distribution study — excursion patterns by cell/session | See v5_mfe_study_REPORT |
| `~/v5-atrrel-confirm/` | atr_h1_rel 2026-inversion confirmation (297k bars) | Confirmed aggregator rule retirement |
| `~/v5-discovery-v2/` | 288-formula discovery sweep artifacts; 130 validated signals; DIRECTION 32 at AUC 0.58-0.61 | **Active research frontier** — next: range distillation + plateau tests + formula-x-geometry EV sim |
| `~/v5-replay-gate/` | 07-02 corrected-profile replay (272K bars, 6/6 months 2026 positive) | Produced REPORT.md confirming profile de-inversion direction |
| `~/qtl-discovery-8yr/` | 8yr per-pair M5/H1/D feature parquets (post-leak-fix) + master_matrix_archive/ | **Use post-07-03 parquets only** (`~/v5-parquets-clean/` symlink if present) |
| `~/.venvs/quantalib/` | Python 3.12 venv: quantalib + xgboost + scipy (all research ML) | |
| `~/.local/bin/v5_monthly_refit.sh` | Monthly refit cron: bars → leak-test → truth rebuild → calibration → anchor check → ship to EC2 | Runs 0 5 1 * * (first run: 2026-08-01) |

---

## Methodology — Before Starting New Research

Read this section before running a new sweep, smoke test, or backtest. The same rules apply to humans and to agents.

### 1. Cross-check the corpus first

Search `sessions/*/NOTES.md` for the question you're investigating. Check `matrices/` for prior per-trade data. Check `reference/` for Brock-curated dm04-dm09 reports. Many questions have already been asked — confirm against §b (Valid Legacy) and §c (Tainted) before re-running.

### 2. Document what + why + outcome

Every session folder has a `NOTES.md` with three sections at minimum: **What** (files + commit hashes), **Why** (the question), **Findings + outcome** (conclusion + what shipped + next question). If a session changes the live trader, link the CHANGELOG.md entry.

### 3. Sample size honesty

Most sessions have small N (10-50 trades). State the cell sample size next to every claim. The governance constitution (07-02) requires n >= 20 same-engine trades for per-cell config action.

### 4. Scope claims to method + data

Note the corpus (live vs corpus vs broker-cross-validated), time window, and pair-session breakdown. Do not claim "universal" unless 8+ cells across 2+ sessions concur with walk-forward evidence. Use drift labels: PERSISTENT / REGIME / FLICKER.

### 5. Cross-broker / multi-source confirmation

Tier 1 findings (universal claims): confirm on 8yr OANDA corpus (post-fix), spot-check broker fills (>= 20 live trades), and walk-forward validate (train<2024, test>=2024). If only one of three confirms, it is Tier 2 (cell-conditional) — state the cell range.

---

## Folder Layout

```
research/
├── README.md            this file (master index + methodology + truth/tainted labeling)
├── reference/           Brock-curated reports (dm05-dm09 + factor_sweep)
├── sessions/            chronological — one folder per research session
│   ├── 2026-06-18_aggregator_sweep/     (TAINTED — H1 leak)
│   ├── 2026-06-19_live_smoke_v1-v5/
│   ├── 2026-06-19_matrix_compilation/
│   ├── 2026-06-19_per_direction_extension/
│   ├── 2026-06-20_qtl_8yr_per_cell/     (PARTIAL — willr M5 direction valid; thresholds tainted)
│   ├── 2026-06-20_qtl_indicator_discovery/  (SUPERSEDED by 8yr replication failure)
│   ├── 2026-06-20_quantalib_eval/       (clean — library validation)
│   ├── 2026-06-21_app_config_test/      (clean — MTF alignment has zero 1H edge)
│   ├── 2026-06-21_broker_validation/    (VALID LEGACY — broker fwd pip method)
│   ├── 2026-06-21_cell_ruleset/         (PARTIAL — profile columns tainted; gate directions valid)
│   ├── 2026-06-21_indicator_sweep/      (clean — standalone indicator structure)
│   ├── 2026-06-21_master_matrix/        (PARTIAL — broker cols valid; ΔAUC tainted)
│   ├── 2026-06-21_percell_exhaustion/   (VALID LEGACY — NY-fade direction; magnitudes tainted)
│   ├── 2026-06-21_real_oanda_trades/    (VALID LEGACY — broker truth methodology)
│   ├── 2026-06-21_v4_bucket_test/       (clean — ALIGN resolution, walk-forward)
│   ├── 2026-06-21_v5_2026_audit/        (TAINTED — ΔAUC +0.0802 was leak-fabricated)
│   ├── 2026-06-22_inverted_live_test/   (context only — inversions mostly reverted)
│   ├── 2026-06-23_aud_jpy_deep_dive/    (VALID LEGACY — broker per-trade method)
│   ├── 2026-06-23_entry_indicators_vs_mfe/  (VALID LEGACY — live trade separators)
│   ├── 2026-06-23_per_cell_tightening/  (PARTIAL — gates valid; backtest thresholds tainted)
│   ├── 2026-06-23_random_pick_cycle_log/
│   ├── 2026-06-23_ratchet_exit_assessment/  (VALID LEGACY — live MFE/MAE)
│   ├── 2026-06-30_usdjpy_audjpy_asia/   (VALID LEGACY — broker fills)
│   ├── 2026-07-01_cell_audit_throughput/  (CURRENT TRUTH — broker fills)
│   ├── 2026-07-01_full_audit_lock_guard/  (CURRENT TRUTH — exit sweep v1 partial)
│   ├── 2026-07-02_panel_and_5pair_sweep/  (CURRENT TRUTH)
│   ├── 2026-07-02_usdcad_deep_dive/     (CURRENT TRUTH)
│   └── 2026-07-03_truth_matrix_envelope/  (CURRENT TRUTH — the primary reference)
├── matrices/            live-trade matrices that drove decisions (pre-07-03; use CAL artifact now)
├── tools/               shared analysis tools (cell_audit.py, lock_snapshot.py, calibration_score.py, profile_shadow_score.py)
└── live-smoke/          nightly cron output (mirror of /data/v5-smoke-history/)
```

## Active Research Frontier (post 2026-07-03)

- **Discovery v2 → promotion:** 130 validated formula-signals incl. 32 DIRECTION (AUC 0.58–0.61). Next steps: range distillation, plateau tests, feed extension (q_yzv/q_dc/q_bbwp/q_vwap), formula × geometry EV simulation. Mini `~/v5-discovery-v2/`.
- **SHADOW_PROFILE stamping:** corrected-profile stack stamps live cycles alongside current profiles. When corrected > current on n>=20 same-engine per cell → promote (restart required). Scorer: `research/tools/profile_shadow_score.py`.
- **CAL instrumentation:** `config/cell_calibration.json` vs live `expected_pips` per cycle. First-cycle data shows artifact projecting ~2× the global 0.30 multiplier — need live comparison on n>=10 per cell to diagnose gap. Scorer: `research/tools/calibration_score.py`.
- **Monthly re-fit:** Mini cron `0 5 1 * *` (`v5_monthly_refit.sh`) — first autonomous run 2026-08-01. Output syncs calibration artifact + anchor check (r>=0.80) before shipping.
