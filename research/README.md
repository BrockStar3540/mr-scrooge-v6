# Research

This is the reading-order index for the Mr. Scrooge research corpus. It is written for a
**public reader who has only this repo** — everything referenced here is either in-repo or in
the Dropbox `/SCROOGE ARCHIVE/` research library (folder paths given; a shareable link is added
at public launch). Nothing points at a private machine or a private repo.

The project's one non-negotiable methodological claim: **the market telegraphs WHEN a move
comes and HOW FAR it travels, but not WHICH WAY.** Five structurally distinct price-direction
edges were falsified on 8yr/16yr corpora (see the edge hunt, below); what survives is
excursion-aware *exit* geometry on cells with a persistent side. Read in that spirit — be
circumspect of any new "direction" finding and cross-check it against what is already here.

---

## 1. Reading order (in-repo)

Start here; each links to a file that lives in this repo.

1. **[`../docs/SCROOGE_HISTORY.md`](../docs/SCROOGE_HISTORY.md)** — the whole story V1→V6, each
   era's thesis / method / measured numbers / what falsified it. The map for everything else.
2. **[`../docs/PAPER_cost_aware_exit_classes_2026-07-05.md`](../docs/PAPER_cost_aware_exit_classes_2026-07-05.md)**
   — the flagship paper: transaction costs from broker fills, the three-speed exit book
   (FAST/MEDIUM/LONG), the rollover wash, and the fill-probability tables. This is the current
   live exit doctrine.
3. **[`../docs/CELL_ARCHITECTURE_SPEC.md`](../docs/CELL_ARCHITECTURE_SPEC.md)** — what a "cell"
   is and how a validated setup becomes a trade (the strategy-free execution model).
4. **[`../docs/DIRECTION_DETECTOR_SPEC_v2.md`](../docs/DIRECTION_DETECTOR_SPEC_v2.md)** and
   **[`../docs/RATCHET.md`](../docs/RATCHET.md)** — the two mechanisms (entry side, exit trail).
5. **[`../docs/BOOK_OF_BUGS.md`](../docs/BOOK_OF_BUGS.md)** — every documented defect B-001→B-090,
   including B-078 (the H1 look-ahead leak that re-bases much of the pre-2026-07-03 research).
6. **[`../docs/ROADMAP.md`](../docs/ROADMAP.md)** and **[`../docs/AUDIT_TODO.md`](../docs/AUDIT_TODO.md)**
   — open questions and the sim-gated removal ledger.

## 2. In-repo research assets

| Path | Contents |
|---|---|
| `reference/` | Brock-curated reports carried into the repo: `dm05_ratchet_corr.txt`, `dm06_validation.txt`, `dm07_direction_split.txt`, `dm08_combo_sweep.txt`, `dm09_ratchet_sweep.txt`, `factor_sweep.txt`, `direction_ml_report.txt`. Compact summaries of the corpora whose raw form is archived. |
| `matrices/` | The early V5 live-trade matrices that drove the first cell decisions: `v5_full_matrix_44trades.csv`, `v5_full_matrix_v2_36cols.csv`, `v5_trade_matrix_44trades_base.csv`. **Historical** — these predate the broker-truth and leak-clean anchors (see truth hierarchy); use the calibration artifact / broker fills for live decisions. |
| `tools/` | Shared analysis + governance scripts, still current: `cell_audit.py`, `cell_config_validator.py`, `generate_cell_configs.py` (the live book's source of truth, incl. the dial-in override block), `cell_setup_score.py`, `calibration_score.py`, `profile_shadow_score.py`, `formula_shadow_score.py`, `center_probe_score.py`, `lock_snapshot.py`, `parity_check.py` (the V6-vs-shadow gauntlet). |
| `live-smoke/` | Seed + first-run nightly-smoke output (`2026-06-19_first_run.txt`, `all_trades_per_feature_seed.csv`). The running series is archived. |

## 3. The truth hierarchy (durable methodology)

Read this before promoting any finding to live config. It survives independent of where the
data lives; the same rules apply to humans and to agents.

**The dividing line is 2026-07-03.** On that date the H1 look-ahead leak (B-078) was found and
repaired: research corpus joins had used open-time for H1 features, injecting up to 55 minutes
of future bar. **Every headline number whose primary evidence came from H1-parquet features
before this fix is an upper bound, not ground truth.** The clean anchors are: broker-trade
measurements, M5-based features, and any corpus rebuilt post-fix.

Findings therefore sort into three tiers:

- **CURRENT TRUTH** — broker-fill lineage or post-fix corpus. The primary references are the
  truth-matrix envelope (per-bar dual-direction forward MFE/MAE, 8 pairs × 8yr, broker-anchored
  r=0.84–0.90), the cell transaction-cost accounting (963 broker fills: ~83% of the loss window
  was spread cost), the ratchet-profile exit classes, and the 3-week trade-excursion table.
- **VALID LEGACY** — used M5 features, broker fills, or walk-forward methods untouched by the
  leak. Chief among these: the **NY-fade** result (NY is a momentum-fade session, 8/8 pairs,
  walk-forward stable — direction valid; per-cell magnitudes are H1-enriched upper bounds), the
  **broker forward-pip method** (OANDA API not the journal; 1H forward pip not realized P/L),
  and the **MAE-flip doctrine** (a losing cell with MAE≫MFE is the right signal wired backwards).
- **SUPERSEDED / TAINTED** — headline numbers built on pre-fix H1 parquets (the 06-18 aggregator
  sweep, the "38/48 profile-mismatch ΔAUC +0.0802" figure which was leak-fabricated, the qtl
  indicator-discovery magnitudes). Retained for the record and code reference; do **not** use
  their quantitative thresholds. Note that a *mechanism* can stand while its *magnitude* is an
  upper bound — the per-cell gates were live-trade-derived and hold; only the backtest confidence
  numbers are inflated.

### Validation protocol (applies to anything promoting to live config)
1. **Clean corpus only (2026-07-03+):** any H1-feature number from a pre-fix parquet is an
   upper bound; treat as directional, not precise.
2. **2026-fit promotes:** a per-cell finding must show positive signal in the current 2026
   window, not just an 8yr average (2026 has been mean-reverting vs a trending 8yr average).
3. **Live vetoes:** a broker-confirmed losing pattern (n≥5, consistent) overrides any backtest.
   OANDA fills are ground truth; the bot journal is intent-only.
4. **Drift labels mandatory:** tag each per-cell lean PERSISTENT (sign-stable across 6+ months),
   REGIME (in-sample only), or FLICKER (unstable); only PERSISTENT ships.
5. **Plateau ranges:** measure the width of the profitable plateau, not the peak — a narrow peak
   is an overfit relic.
6. **n ≥ 20 per cell, same-engine:** no per-cell governance action on fewer than 20 same-engine
   trades from that cell.
7. **Survivorship check (added 2026-07-14):** an MAE-based stop rule measured only on trades that
   *survived to win* is survivorship-biased — it is blind to the trades a tight stop killed that
   would have recovered. Validate stop widths against the full firing population, not the winners.

### Before starting new research
- **Cross-check first.** Search the archived session diaries for your question; many have been
  asked. Confirm against VALID LEGACY and TAINTED before re-running.
- **Document what + why + outcome** in a session note (files + the question + the conclusion and
  what shipped). If a session changes the live trader, link the `CHANGELOG.md` entry.
- **Sample-size honesty.** Most sessions have small N (10–50 trades). State the cell sample size
  next to every claim.
- **Scope claims to method + data.** Note corpus (live / backtest / broker-cross-validated), time
  window, and pair-session breakdown. Do not claim "universal" unless 8+ cells across 2+ sessions
  concur with walk-forward evidence.
- **Heavy compute never runs on the live-trader host** (the origin of B-067) — it belongs on
  separate lab hardware; the outputs are what get archived.

---

## 4. The archive (`/SCROOGE ARCHIVE/` on Dropbox)

The full research library — every corpus, session diary, and retired module — lives here.
Entry points inside the archive: `00_MASTER_INDEX.md`, `00_HISTORY_V1-V6.md`,
`00_BOOK_OF_BUGS_V4-V5.md`.

### Session diaries — `/SCROOGE ARCHIVE/session-notes/`
The working record behind every CHANGELOG entry, dated 2026-03 (V1 daily notes) → present. The
arcs a researcher will most want:

| Folder | Covers |
|---|---|
| `2026-03-*` (dated .md files) | V1/V2 daily notes — the box-bug forensics behind B-025→B-074 |
| `2026-06-11_v4-cutover-night.md`, `2026-06-11_AEF-only-era-launch.md` | the V4 bucket-keyed launch |
| `scrooge_handoff_2026-06-13_exit-bottleneck.md` | **the exit-bottleneck finding** (B-076) — read this for the ratchet rationale |
| `2026-06-18_v5-buildout-day`, `2026-06-19_*` | the V5 ground-up rebuild |
| `2026-06-21_full_weekend`, `2026-06-21_master_matrix_broker_validation` | **the methodology overhaul** (broker truth, forward pip, NY-fade) |
| `2026-06-23_*`, `2026-06-25_per_cell_tightening_trio`, `2026-06-30_usdjpy_audjpy_asia_deepdive` | per-cell tightening, broker-fill deep dives |
| `2026-07-01_cell_audit_throughput`, `2026-07-04_cell_era_cutover` | the cell-era cutover |
| `2026-07-05 Ratchet Exit Research` | **the cost-aware exit classes** — source for the in-repo paper |
| `2026-07-08 Book Dial-In` | the dial-in method (side-check, winners'-MAE SL, quintile separators) |
| `2026-07-09 Resurrection Day` | shadow-scoreboard retrials + the classics/box-theory shadows |
| `2026-07-13 V6 Gauntlet Fix` | the parity-gauntlet config-drift postmortem |
| `2026-07-14 Edge Hunt`, `2026-07-14 Deep-Dive Dial-In` | **the five falsifications + the wide-stop turn + the survivorship-bias discovery** |

Loose top-level files in `session-notes/` also hold the miner/prospector/discovery outputs
(`miner_v3_gen1*.csv`, `discovery_hierarchical.json`, `ml_strategies*.json`,
`bucket_survivors_K2_K3.*`, `combo_atoms_by_bucket.*`), the pattern-loop artifacts
(`cellular_knowledge.json`, `pattern_loop.py`), the exit-model / ratchet builders
(`build_ratchet_8pair.py`, `build_exit_cont.py`, `exit_model.txt`, `model_util.txt`), and the
reading note on the 2024 Warsaw ML-FX paper.

### Research corpora — `/SCROOGE ARCHIVE/research-corpora/`
The heavy data needed to reproduce or challenge the research (all generated on lab hardware,
archived as tarballs):

| Tarball | Contents |
|---|---|
| `mini/v5-truth-matrix.tar.gz` | **the primary reference** — per-bar dual-direction forward MFE/MAE, 8 pairs × 8yr, broker-anchored |
| `mini/qtl-discovery-8yr.tar.gz` | 8yr per-pair M5/H1/D feature parquets (post-leak-fix) + the master-matrix archive |
| `mini/v5-research-archive-2026-07.tar.gz` | the consolidated V5 research working tree (ratchet-EV, exit-sweep, calibration, discovery-v2, atrrel-confirm, replay-gate) |
| `mini/continuous_corpus.tar.gz`, `mini/continuous_corpus_unbiased.tar.gz`, `mini/allbars_corpus.tar.gz` | the V4-era continuous + unbiased + all-bars corpora (the exit-bottleneck evidence) |
| `mini/pips_brain_v4.tar.gz`, `mini/direction_artifacts_v2.tar.gz`, `mini/factor_lift_v1.tar.gz` | ML brain + direction + factor-lift artifacts |
| `mini/scrooge_research_scripts.tar.gz`, `mini/scrooge_lab_code.tar.gz` | the durable research scripts (build_unbiased, cell extractors, etc.) |
| `alien/*.tar.gz` | full V3/V4 repo mirrors, direction-ML, lab datasets, forexsb H1 data, git mirrors |
| `ec2/ml-observer-v3era.tar.gz` | the V3-era live ML observer |

### Retired modules & docs
- **Retired signal stack (V5 legacy):** the `direction_v2`/`momentum_v3` "certainty" era was
  archived in-repo at cutover as `modules/archive/signals_legacy/` and is reachable in git
  history at tag `pre-cell-cutover-2026-07-04`. Full V5 tree: `/SCROOGE ARCHIVE/V5/archives/`.
- **Retired V3/V4 repo docs:** `/SCROOGE ARCHIVE/docs-harvest/v3-repo-docs/` and
  `.../v4-repo-docs/` — ADRs, evolution timeline, the **strategy encyclopedia** (every strategy
  the strategy era tested and why it's retired), execution physics, research methodology, and the
  fix postmortems that ground the box-bug family.
- **Version indexes:** `/SCROOGE ARCHIVE/V3|V4|V5/SCROOGE_*_INDEX.md`.

---

## 5. Active research frontier

- **Wide-stop verdict (the decisive open test):** walk-forward cell selection (train 2019–22 /
  test 2023–26) + a slippage haircut on the range-sized book. If Sharpe survives ~0.7 there, a
  cell earns a live *shadow* seat. Until then the practice-account forward tape is the only
  verdict, and it is not in yet.
- **Direction hunt (honest):** the center-box discovery probe logs a full feature vector at the
  prev-session box center with no direction commitment, mining signed-travel (which wall) vs each
  indicator for a which-way filter — needs n≥100 before any read. Prior attempts at pre-committed
  direction were regime-only.
- **Monthly re-fit:** the calibration artifact + truth matrix are rebuilt monthly on lab hardware
  (bars → leak-test → truth rebuild → calibration → anchor check r≥0.80 → ship). Any promotion
  must pass the anchor check.
