# CHANGELOG

Every substantive change to Mr. Scrooge V5 — what changed, why, and what the outcome was. Grouped by era. Trivial formatting and comment-only commits are omitted. For full commit detail: `git log --format='%ad %h %s' --date=short`.

---

## Summary: V5 Eras

**V5 Launch (2026-06-18):** Bot deployed from scratch as a strategy-free framework. V4 and V3 retired. Core pipeline: direction_v2 + momentum_v3 → playmaker → ratchet exit. Eight pairs on OANDA.

**v2/v3 Activation (2026-06-20):** Per-(pair × session × direction) modules wired live. Feed gaps fixed (atr_h1_relative, trend_4h). Nightly smoke cron installed.

**Matrix + Broker Methodology (2026-06-21):** The weekend that changed how V5 is measured. Pulled real OANDA trades (journal missed 70/120), established forward-pip ground truth, disabled 10 cells, confirmed 2 winner cells, proved NY is a fade session.

**Inversion Era (2026-06-22 through 2026-06-30):** Per-cell inversion mechanisms wired. Multiple cells inverted, then un-inverted, then re-inverted. Dashboard rebuilt with 8 tabs + streaming pack. Per-cell gates (m_cert, d_cert, willr_range, kc_up_range) shipped. USD_JPY + AUD_JPY deep-dives. Lessons: inversions fit to n<10 are winner's curse; backtest thresholds from H1 parquets are upper bounds.

**Throughput + Locks (2026-07-01):** Engine multi-open per cycle (was 1/300s, now all actionable up to max_concurrent). Session widening. Locked-cell security registry + enforcement. USD_CHF killed.

**MAE-flip + Lock Guard (2026-07-02):** 3-model panel diagnosis. Governance constitution (n>=20). USD_CAD MAE-flip with aroon gate. Per-currency exposure cap. SHADOW_PROFILE instrumentation. De-inversions.

**Cellular Architecture Phase B+C (2026-07-04):** The cell becomes the first-class unit. 48 evidence-generated cell configs (1 ACTIVE / 12 SHADOW / 11 NO-SIDE / 3 DISABLED), CellModule/PairModule engine wired shadow-only (CELL_EXECUTION_ENABLED=False), per-trade exit params prepared. Direction/momentum modules unchanged and still driving execution until Phase D cutover.

**Truth-Matrix Era + Leak Repair + Strategy Ledger (2026-07-03):** H1 look-ahead leak discovered and fixed. atr_conc scale bug fixed (14 dead cells revived). All aggregator rules retired. Truth matrix built (8yr broker-anchored). Per-cell calibration artifact wired. Monthly re-fit pipeline armed. Direction detector spec v2. Discovery v2 (130 validated signals).

---

## 2026-06-18 — V5 Launch

- `3b8a0b0` **Initial V5 scaffold** — per-pair signal → playmaker → ratchet. Strategy-free from day one.
- `4f42043` **Wire 35 dm_04 features**; weights = span / total_abs_span.
- `20a80db` **Playmaker certainty floors** + best-edge priority logic.
- `d251652` **Margin-based sizing (V1 model)** — rename risk_pct → margin_pct; SL no longer in sizing math. `units = (balance × margin_pct) / (base_price_usd × OANDA_marginRate)`.
- `b31caac` **TP1/TP2 partial-close ladder** ported from V4 harvest_ladder, defaults OFF.
- `e55d403` **TUNE tab** — live-edit SL + ratchet, defaults + per-pair overrides.
- `d5c4f94` **PLAYMAKER tab** — per-pair gates + account-level risk and max concurrent.
- `6757075` **Default SL: -12 → -20 pips** (config + README). Widened for V5 larger range cells.
- `9e31c28` **SETUP.md** + systemd service file.
- `e26dba7` **Fix session-label mismatch** that silently disabled NY-session trading.
- `72e33fc` **Phase 2: 30s management poll** — manage separate from 300s scan cycle.
- `249f970` **Retune ratchet: engage +7.5p lock +5p, step +2.5p trail +2.5p** (retuned from launch settings).

## 2026-06-19 — Per-direction extension + smoke infra

- `87ffe08` **Add v2 direction + momentum modules + nightly smoke cron** — infrastructure for per-(pair × session × direction) cells.
- `c1925d3` **Add momentum_v3** — per-pair module with per-session profiles (30 default / 7 london_exhaustion / 4 asia_volume_rev / 4 ny_volatility / 3 ny_volatility_strict).
- `969eefc` **Extend direction_v2 + momentum_v3 to per-(pair × session × direction)** — 48 cells each.

## 2026-06-20 — QuanTAlib eval + 8yr ML sweep

- `715d1b4` **QuanTAlib validated** — 53 candidate indicators curated; EMA/SMA/BB bit-exact; installed on Mini (~/.venvs/quantalib/).
- `4d02917` **QuanTAlib discovery sweep on 44-trade matrix** — kurtosis_m5/bbwp_m5 looked strong (later refuted at 8yr scale).
- `d144219` **QuanTAlib 8yr per-cell ML sweep** — 4.4M bars, 24/24 cells improved; willr_m5 top-3 in 24/24 cells; aroonosc_h1 dominant aggregator candidate (threshold later shown H1-leaked).
- `a8f3889` **v2/v3 observability + aggregator-inputs fix** — feed populates atr_h1_relative + trend_4h (were dead/missing); smoke cron gains 6 new columns; dashboard PAIRS tab shows dir/mom profile names.
- `5a29000` **v2/v3 LIVE** — direction_v2 + momentum_v3 wired in modules/signals/__init__.py. v1 modules retained as rollback.

## 2026-06-21 — Master Matrix + broker methodology weekend

- `1d3afa4` **V5 2026 re-audit** — profiles + aggregators + qtl candidates vs 2026 data only. Headline: 38/48 cells profile-mismatched. *Note: ΔAUC headline +0.0802 was H1-leak-fabricated; direction of regime-shift finding valid.*
- `bd6790d` **V5 Master Matrix** — 48 cells × 55 columns; live replay KILLED qtl-as-binary-rules (blocked all 5 AUD_JPY/asia/short winners); 5 disable candidates flagged.
- `f8df78b` **CORRECTED Master Matrix** — real OANDA trade data (89,251 candles pulled fresh); broker fwd pip per cell. USD_CAD/ny/long confirmed star (+6.61p); EUR_USD/london/short confirmed (+6.31p).
- `51c10dd` **Disable EUR_JPY/london/short** — broker -5.73p fwd + matrix agrees → 10 disabled cells total.
- `0c35a5d` **Fix: broker validation MUST include manual-closed trades** — forward analysis is unaffected by how the trade closed; filtering manual closes discards valid evidence.
- `e5caa77` **Master Matrix ACTIONS** — (A) Shadow Vortex VI+/VI− wired on H1 (weight=0, observation); (B) 5 cells disabled via disabled_cells; (C) monthly Mini cron installed (1st of month 04:00 local).
- `e1ac26a` **NY is a momentum-FADE session** — per-(pair × session) walk-forward; 8/8 pairs negative NY momentum separation in both train AND test; explains broker NY losses.
- `89d953a` **Disable 4 more cells per broker validation** — 10 disabled total.
- `bd08cb1` **Wire shadow-inverted logging for GBP_USD/ny + EUR_JPY/ny** — shadow-log opposite signals for observation.
- `0c526f2` **Research: ALIGN sign flips by session** — align climbs in ny_open; sign-flipped in some sessions; validated four ways.
- `b1cfb0c` **Consolidated per-cell ruleset** — 48 cell modules, validated 4 ways.
- `2a62122` **research/README.md** — original index (superseded by this file, 2026-07-03).

## 2026-06-22 — Inversion mechanisms wired

- `200629f` **Wire inverted_live_cells** — flip live trade direction at execution; first cell: AUD_JPY/asia. Signal still selected normally; trade direction flipped at broker order.
- `9cdb2ea` **USD_JPY/asia added to inverted_live_cells.**
- `d663991` **Inversion test mode** — flip 7 more cells (4 pairs, all sessions) for comparative analysis.
- `8954e43` **Disable 4 more cells** (inversion analysis; 14 disabled total): EUR_USD/london/long, USD_JPY/ny/short, AUD_USD/asia/short, AUD_USD/asia/long.

## 2026-06-23 — Per-cell tightening + dashboard + random pick

- `bac4d69` **Manage-cycle polling 30s → 5s** — catches MFE peak crossings missed at 30s. Filed ratchet exit assessment session.
- `c43c38c` **Random pick_best + per-cycle CYCLE log** — cut from max-composite to random.choice among actionable; paired with per-cycle pipe-delimited log for ranking backtest.
- `8f7d9ba` **CYCLE log analyzer** — research tool for ranking evaluation.
- `ff64a09` **Wire 4 matrix shadow features** — willr_m5, aroonosc_h1, kc_up_dist_pips, efi as feed features (MarketView).
- `cfc95fc` **Wire willr_m5 as SOFT direction feature** — added to all profiles.
- `4721015` **Per-cell m_cert FLOOR mechanism + first use** (GBP_USD/ny=0.40, USD_JPY/london=0.50).
- `325d687` **USD_JPY/london: flip + m_cert floor 0.50** (Brock explicit).
- `472dd96` **Per-cell willr_m5 range gate** + EUR_JPY/ny/short=[-85,-7].
- `8ab0709` **AUD_JPY/asia revert + per-cell m_cert CEILING** (AUD_JPY/asia=0.50 max; reverted from inverted_live after 5 trades -46p).
- `7d7ca9f` **Per-cell kc_up_dist_pips range gate** + AUD_USD/london/short [-15,0].
- `01d066b`→`c4076fc` **Dashboard rebuild** — modern dark design with 8 tabs (LIVE / PAIRS / CELLS / INDICATORS / HEALTH / SYSTEM / TUNE / PLAYMAKER); CELLS governance grid; INDICATORS sparklines; streaming pack (GIGA P/L ticker, equity curve, cell mosaic, decision ticker, confetti, sound); URL modes `?stream=1` + `?mode=overlay`.

## 2026-06-24 — Dashboard passes + more inversions

- `01d066b`..`a16b62c` **Dashboard passes 1-3** — sparklines, Today's Trades, CELLS filter/sort, per-pair P/L, gauge bars.
- `a786198`..`c4076fc` **Streaming pack** — trade event overlay + giga P/L ticker + equity curve + streaming modes.
- `0f3f085` **EUR_JPY/ny inverted_live added** (10 cells total).
- `b571c2e` **per_cell_mom_cert_max[AUD_USD/london] = 0.50.**
- `8464dc9` **Per-pair deep-dive utility** — parameterized analysis script (works for any pair).

## 2026-06-25 — d_cert mechanisms + dashboard block reasons

- `d91b643` **NEW per_cell_dir_cert_min mechanism** + GBP_USD/ny=0.52.
- `8aa8c54` **USD_CHF un-invert** + per_cell_dir_cert_max + d_cert range [0.35, 0.55] for USD_CHF/ny+london.
- `0b5a6ef`..`06bab73` **Dashboard: block reasons** — GLOBAL / CELL / SPREAD tags with color coding; fix 'ready' check to match playmaker gate logic.
- `60b8ad2` **Revert fb6d90b** — re-add 4 disable entries.

## 2026-06-26 — USD_CHF re-invert

- `4609f0e` **Re-invert USD_CHF/ny + london** + keep d_cert ceiling 0.55, drop floor.
- `265e4e8` **AUD_JPY/asia: flip to inverted_live** + per_cell_dir_cert_max=0.65.
- `2d1ade3` **Clean up stale inverted_shadow_cells.**

## 2026-06-30 — USD_JPY + AUD_JPY asia deep-dives

- `af0afa7` **USD_JPY/asia: per_cell_dir_cert_min=0.49** — separates both losers (d_cert 0.37/0.46) from all 3 winners (>=0.49).
- `1e7b24a` **AUD_JPY/asia UN-INVERTED** + dropped d_cert ceiling — inversion was forcing longs (6 deepest MAE trades all longs that should have been short); native short signal now fires short.
- `5f36685` **Session note** + README governance counts.

## 2026-07-01 — Throughput + locks

- `acdefe7` **USD_CHF/ny UN-INVERTED to short** (Brock override; broker confirms cell loses both ways → disable candidate).
- `c6479e1` **USD_JPY/london LONG-ONLY** — kept inverted + disabled native long; broker london/long 4W/0L vs short 0W/2L.
- `0312522` **Engine multi-open per cycle** — was 1 trade/300s scan → now fires ALL actionable up to max_concurrent=4 per _cycle. Root cause of chronic 1-2 concurrent positions fixed.
- `e6b0b30` **Widen sessions** — asia enabled for EUR_USD/EUR_JPY/GBP_USD; USD_CAD ny-only→all-3; AUD_USD asia re-enabled. Only USD_CHF lacks asia.
- `f0b3323` **Session note** (cell audit + throughput + session widening).
- `a2c96c5` **Add LOCKED-cell registry + safety-monitor audit tool** (`config/locked_cells.json` + `research/tools/cell_audit.py`). Six broker-validated cells dialed-in + locked.
- `f605d4c` **LOCKED-cell security lock enforcement** (`modules/playmaker/lock_guard.py` wired into pick_best). Locked cells resolve ALL gates from lock-time snapshot; drift logged; throttle 2 opens/session; code-input fingerprint on startup; `/api/state.lock_guard` block; overrides require explicit config entry.
- `7998bce` **USD_CHF KILLED** — `per_pair enabled=false`; broker -$1,071 both directions.

## 2026-07-02 — Panel verdict + MAE-flip + governance constitution

- `5c9ac55` **Panel-consensus de-inversion** (non-locked cells) — EUR_USD london+ny, GBP_USD london, EUR_JPY ny un-inverted; EUR_JPY/ny/short + AUD_JPY/asia/long disabled (chop veto).
- `5ddd0d2` **Per-currency directional exposure cap** — `max_per_currency_direction=1` in pick_best Step 6; /api/state exposes exposure map. 121 candidate skips in first 8h.
- `bade16b` **SHADOW_PROFILE dual-stamp** — corrected-profile stack stamps same views alongside live profiles, logs separately; inert until restart promotes. Scorer: `research/tools/profile_shadow_score.py`.
- `cc939ae` **USD_CAD MAE-flip: per-direction inversion + aroon gate** — first full MAE-flip doctrine wiring. dir-cert floor 0.25. Both new mechanisms: per-direction inversion (inverted_live_directions) + per_cell_aroon_range.
- `d6d9f81` **EUR_JPY/ny/short willr window re-fit** [-85,-7] → [-100,-75] (exhaustion-only for inverted regime).
- `b8422e8` **README: V5 is strategy-free** — direction + momentum/distance IS the strategy (Brock framing directive).
- `e5367ad` **USD_JPY/london natural direction restored** (explicit Brock lock override).

## 2026-07-04 — PHASE D CUTOVER: the cell engine IS the bot (Brock order)

Brock: "i told you to archive the old shit that is obsolete now" + explicit three-step
authorization. The shadow-week plan was superseded — cutover same night.

- **CELL_EXECUTION_ENABLED = True.** core/engine.py rewritten: cells are the sole
  strategy source (evaluate -> CellIntent -> modules/cells/portfolio.select_intent ->
  order). SIGNAL/ENTERED lines carry engine=cell_v1 setup=<id>. Each trade ships its
  setup's own exit block via Position.exit_params (GBP formula trades 12/10/1.5).
- **Legacy stack ARCHIVED**: direction_v2, momentum_v3, both profile files,
  profile_shadow, factor_sweep.json + pre-v2 versions -> modules/archive/signals_legacy/
  (importable; rollback = tag pre-cell-cutover-2026-07-04 + restart). SHADOW_INVERT /
  SHADOW_PROFILE / CAL instrumentation retired with it; FORMULA stamps retained.
- **Portfolio layer** (modules/cells/portfolio.py): risk arithmetic only — one-per-pair,
  max_concurrent, per-currency-direction, spread fail-closed, 60m post-loss cooldown;
  ranks by measured ev_seq. Sizing stays on the margin model (per-setup risk_pct
  normalization = flagged follow-up, not silently invented).
- **Book promoted per Brock**: 9 SHADOW setups -> ACTIVE (4 LEAN/regime evidence-backed +
  5 TIMING first-live-trades). The 3 CONTROL formulas stay SHADOW — they are negative-
  expectation falsification instruments and are not tradeable by design.
  Book: 10 ACTIVE / 3 SHADOW / 11 NO-SIDE / 3 DISABLED.
- **ev_seq-null crash fixed** in cell.py (float(None) TypeError killed stamping AND
  intent generation for every ev_seq:null setup — found by the dashboard build agent).
- **Dashboard overhauled** (ops/): BOOK tab (8x3 cell grid, condition-proximity bars,
  click-to-expand evidence), SHADOW tab (scoreboard + stamp feed), /api/cells +
  /api/cellshadow + /api/cellscore, /api/state serializer hardened for cell-era tickets,
  legacy exec-stack view behind a retirement toggle. cell_setup_score.py gains --json.
- Cutover sanity: 8/8 (evaluate geometry, portfolio caps x4, ticket build, exit_params).

## 2026-07-04 — Cellular architecture Phase B+C (shadow-only)

The migration approved in `docs/CELL_ARCHITECTURE_PLAN.md`: invert the hierarchy so the (pair × session) CELL owns its complete configuration. All of tonight's changes are shadow-only — live execution still flows through direction_v2 + momentum_v3 + playmaker, byte-identical, until Phase D cutover.

- **Phase B — evidence-generated cell configs.** `research/tools/generate_cell_configs.py` (1.1k lines) emits `config/cells/<PAIR>.json` for all 8 pairs from the clean-corpus evidence CSVs; `research/tools/cell_config_validator.py` enforces the schema (lineage mandatory on every threshold, ranges never point values, percentile-form conditions carry resolved values). Book v1: **1 ACTIVE** (GBP_USD/london `rvol_low_240` — the sole deep-OOS-validated formula, rolling-percentile form, per-setup exit 12/10/1.5), **12 SHADOW** (LEAN + TIMING + CONTROL setups, stamps only), **11 NO-SIDE** (no validated setup = no trade — the honest consequence of the direction falsification), **3 DISABLED** (USD_CHF). Phase-A cert-gate re-derivations folded in: GBP_USD/ny willr [-50,0] short, USD_JPY/asia kc_up>=0 long (beats the old d_cert gate), AUD_JPY/asia NOT-RE-EXPRESSIBLE -> NO-SIDE, AUD_USD/london kc gate survives raw with m_cert dropped.
- **Phase C — cell engine, shadow-wired.** `modules/cells/` (CellModule, PairModule, CellIntent, ExitParams). Engine evaluates every active cell each scan cycle and stamps `CELLSHADOW`; `CELL_EXECUTION_ENABLED=False` forces evaluate() to return None regardless of setup status. Kill-switch `defaults.cell_shadow_enabled` (hot-reload). `Position.exit_params` + RatchetManager override path prepared but dead code until cutover (verified byte-identical when None). Scorer: `research/tools/cell_setup_score.py`.
- **Review catches (coordinator):** pair_module session table had drifted from `config/sessions.py` (london 07-16 vs canonical 07-13 — would have cross-stamped london cells into NY; now imports `coarse_session`, single source of truth); AUD_JPY/ny monthly tripwire direction inverted in spec (suspend fires when monthly-mean atr_5m <= 2.836 = regime OFF, not >=); 5 TIMING lean-confirmers were vacuous/price-level/feed-unreadable — dropped or converted to percentile form, rule codified in the generator (`LEAN_CONFIRMER_POLICY`).
- Locked cells -> `priority_analysis` notes inside cell configs (lock semantics retire at Phase D per Brock's directive).

## 2026-07-03 — Truth matrix + leak repair + strategy ledger

- `2c7367a` **Fix atr_conc scale bug (14 dead cells revived)** + 6 audit bugs. atr_conc lived in (0,1) but profiles gated on >=4.0 → 14 cells structurally unable to fire since v3 activation. Also: spread gate fail-closed, is_actionable bootstrap, dead rules/constants cleaned.
- `82e0fa2` **Re-enable AUD_USD/ny both directions** — disable evidence was leak-fabricated (clean dAUC -0.002 vs tainted -0.032).
- `7eb47ec` **Remove stale USD_CHF/london inversion** — pair killed; dead entry flagged by conformance sweep.
- `948291f` **Direction detector spec v2** (`docs/DIRECTION_DETECTOR_SPEC_v2.md`) — 10-item evidence-revised change log; per-cell fitted leans replace static weight tables; truth matrix is ground truth.
- `fabdf52` **Remove last two aggregator rules** — atr_h1_rel asymmetry INVERTED in 2026 (297k-bar confirmation study); AGGREGATOR_RULES now empty.
- `de8934d` **Per-cell calibration instrumentation (LOG-ONLY)** — `config/cell_calibration.json` (48 cells: MFE quantiles + ATR regression, winner-MAE, dead rates + separators, direction leans) wired as CAL log-lines per cycle vs live expected_pips.
- `7d6708f` **Monthly re-fit pipeline test run** — refreshed calibration artifact through 2026-07-03 08:00Z; anchored vs 155 V5 broker trades r=0.86/0.84.
- `c4cc09d` **Session notes 2026-07-03: truth-matrix era** — full ledger: leak repair, envelope falsifications, discovery v2 (130 validated formula-signals, 32 DIRECTION with AUC 0.58-0.61), structural tiering, geometry sweep (90 configs, 0/44 holdout-positive unconditionally). H1 look-ahead leak note added to MEMORY.md.
