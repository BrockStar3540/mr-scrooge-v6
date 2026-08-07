# Changelog

Notable changes to Mr. Scrooge. Format loosely follows [Keep a Changelog](https://keepachangelog.com/).
The full narrative history lives in [docs/SCROOGE_HISTORY.md](docs/SCROOGE_HISTORY.md) and the
[Book of Bugs](docs/BOOK_OF_BUGS.md); this file tracks the public-repo era.

## [6.25.1] — 2026-08-07 — B-124: the max-spread entry veto is gone

### Removed
- **The max-spread entry veto, at all three sites** (cell portfolio `select_intent`,
  playmaker candidate gate, party-package popper fire gate) and the `_MAX_SPREAD`
  table behind it. The table listed 8 pairs; anything else fell to a 3.0p default —
  below CAD_JPY's floor spread (3.4p over 14 days of stamps), so that ACTIVE cell
  was structurally vetoed for 11 days with zero trace. Operator decision: the
  ratchet exit and broker-truth net-of-cost cycle scoring already price the spread
  toll; a hard entry veto from the pre-ratchet era double-filtered on a stale table.

### Changed
- `spread <= 0` bad-tick guards remain (fail-closed) and now LOG: `CELLSKIP
  reason=bad_tick` / `PP SKIP ... reason=bad_tick`. The post-loss-cooldown veto
  logs `CELLSKIP reason=post_loss_cooldown`. No veto is silent anymore.

See [Book of Bugs B-124](docs/BOOK_OF_BUGS.md).

## [6.25.0] — 2026-08-07 — 🍀 market-structure variant matrix

### Added
- **30 paired variants** of the 2026-08-06 market-structure trials, each wired on
  the SAME cell/session as its baseline so pair, session and market period cannot
  confound the comparison. All tagged 🍀; cohort is now 42 setups across 6 cells.

  | suffix | change vs baseline | question it answers |
  |---|---|---|
  | `_v` | sweep + `rvol_5bar ≥ 1.15` | does elevated activity separate real stop runs from drift? |
  | `_t` | sweep + EMA regime agreement | does trend alignment help a REVERSAL setup? |
  | `_m` | sweep + `willr_m5` stretched into the swept side | does exhaustion confirm the fade? |
  | `_nt` | impulse zone MINUS the trend gate | does the trend gate the manuals demand earn its keep? |
  | `_adx` | impulse zone + `adx14 ≥ 20` | does trend STRENGTH (not just direction) matter? |

### Notes
- `_t` is wired **against** existing evidence, at operator request: the 2026-08-06
  gate test on 836 episodes produced a trimmed gap of only +1.28p with a bootstrap
  CI straddling zero, and trend agreement narrows a reversal setup into a
  continuation one. Forward evidence will settle it better than argument.
- `_nt` fires MORE often than its baseline (a gate removed), so it accrues
  evidence faster; every other variant fires LESS often and will be slower to the
  bar. That is the accepted cost of a conjunction.
- All gating features were verified to read non-default on live views before
  wiring — an unreadable feature makes a setup skip silently forever, which is
  how the audit's "never fired" cells were created.
- FX tick volume is a COUNT, not size. `_v` does not claim an institutional
  footprint; it claims a stop cascade is many orders firing, which tick count
  does capture.

## [6.24.0] — 2026-08-06 — censoring was hiding losses (evidence recovery)

### Fixed
- **27% of all episodes were being silently discarded, and the discard was
  biased toward losses.** The 2026-07-31 charter censored any stamp still open
  at `horizon_min` (correct reasoning: the live ratchet has no timeout, so an
  unresolved trade is not an outcome) — but the replay was TRUNCATED at the
  horizon, so "unresolved" really meant "we stopped watching". Measured:
  616 of 2240 episodes older than 8h, some 9 days old.

  `simulate_shadow_exit()` gains `max_bars`, and `_score_v2` now FOLLOWS a
  still-open stamp to its real exit (paged M5 fetch, capped at
  `FOLLOW_MAX_DAYS`=5, inside the bot's own `grid_max_age_days`=7). MFE/MAE
  stay scoped to the horizon window so `hit≥trig` / `hitSL` keep their meaning;
  full-window extremes are carried as `mfe_full`/`mae_full`. A stamp still open
  after 5 days remains genuinely censored.

- **`research/tools/rescore_censored.py`** recovered the backlog: **503 of 657
  censored episodes resolved (77%)**, 154 genuinely still open, 0 failures.

### Why this mattered
The recovered episodes are **75% winners but average −4.5p** — one in four ran
to a full stop. Censoring was therefore removing losers preferentially and
flattering every cell in the book. Post-rescore: cells with era evidence
171 → 193, and **61 of 131 cells with grown samples got WORSE** (mean −1.15p).
Two live seats were revealed as flattered — `CAD_JPY/asia/ps_ceil_fade_short`
(ACTIVE) +13.50 → **−22.50p**, `USD_CHF/london/ps_ceil_fade_short` (PROBE)
+6.83 → **−12.50p**. The governor's next tick promotes two genuinely strong
candidates (LCB +5.9 and +5.7, q=0.001) and demotes `GBP_USD/ny/control_rvol_60`
(now −3.58p, LCB −8.23) with its first strike.

Episode DB backed up to `data/shadowboard.json.pre-rescore-20260806` first.

## [6.23.1] — 2026-08-06 — operator raises FDR tolerance to 0.10

### Changed
- **`fdr_q` 0.05 → 0.10** (operator decision): accept roughly one in ten
  admissions being a fluke in exchange for testing marginal ideas faster.
  What justifies it is what sits BEHIND admission — every promotion lands on a
  0.33× PROBE, must earn completed broker family cycles to graduate, and a
  demotion costs a permanent strike. The audition is the second filter.
- **`max_probe_seats_total` 4 → 6.** The ceiling added earlier the same day
  immediately became the binding constraint at the looser threshold and blocked
  the very cells the change was meant to give a chance. Sized as 3 occupied +
  1 reserved for the commissioned lane + room for 2 ordinary admissions. Note
  the ordinary lane had NO standing ceiling at all before today, so 6 remains
  far tighter than prior behaviour; concurrent RISK is bounded separately by
  the party-package caps, not by this number.
- **The commissioned lane's seat is now RESERVED, not first-come.** At
  fdr_q=0.10 the ordinary lane can fill every free seat in one run, which would
  have re-created the starvation bug fixed hours earlier.
- One-time `last_eval_blocks` reset (160 entries) — a threshold change is a bar
  change, and the sequential-peeking guard caches the day-count of failed tests.

### Note on effect
Nothing promotes at the new threshold today, for reasons unrelated to it:
`USD_JPY/ny/classic_box_fade_short` deteriorated on its own between measurements
(n 21→23, avg +9.99→+6.90, **LCB +1.46→−4.47**) and now fails on LCB, not FDR;
`GBP_USD/london/rvol_low_240`'s q rose 0.091→0.228 because the docket's
strongest member (`rvol_low_240_short`, p=0.0002) promoted at 18:35Z and its era
clock reset, removing it from the family — the same rank/m mechanic documented
in 6.23.0. The looser threshold stands for future candidates.

## [6.23.0] — 2026-08-06 — seat pools + BH family scope

### Fixed
- **Ordinary promotions structurally starved the cheater lane.** The cheater
  cap was `cheater_max_seats − probe_seat_count`, and `probe_seat_count` counts
  EVERY PROBE regardless of origin. Two ordinary-lane PROBEs therefore zeroed
  the single seat the Commissioner had just spent five days earning — the lane
  did not merely fail to seat, it skipped candidate evaluation entirely.
  Seats are now two pools: `cheater_seat_count()` (per-lane policy, from the
  cheater seat book) and a new **`max_probe_seats_total`** (default 4) — a
  durable, status-derived ceiling across BOTH lanes, which is the real risk
  control and survives loss of governor state.
- **The ordinary lane had no standing seat ceiling at all.** `max_promotions`
  bounded promotions *per run*; nothing bounded the total number of live
  PROBEs across runs. It now respects `max_probe_seats_total`, with cheater
  admissions reserved first (that lane already paid the validation cost).

### Changed
- **BH-FDR family scoped to the candidate docket** (`fdr_family: "docket"`,
  `"all"` restores legacy). The module contract always said "across the run's
  whole candidate docket"; the implementation had drifted to every scored row.
  Family membership is decided by SAMPLE SIZE only, which is independent of the
  effect estimate. Measured: family 128 → 10, so newly-wired shadows no longer
  tax cells already in the queue.

  **Honest result: this did NOT rescue the marginal candidates and slightly
  tightened them** (USD_JPY/ny/classic_box_fade_short q 0.071 → 0.091). BH
  normalises by rank/m and the rows removed were disproportionately strong
  cells short of their counting gates; dropping low-p members raises everyone
  else's rank-normalised position. Promotable count is unchanged (1 in both
  modes) — this is not a loosening. The real constraint on those two cells is
  their raw evidence (p ≈ 0.023 and 0.027) against `fdr_q = 0.05` in a family
  of 10, which is a policy threshold, deliberately left alone.

## [6.22.0] — 2026-08-06 — market-structure trial features

### Added
- **`core/feed/structure.py`** — three pure, unit-tested feature builders on the
  M5 window, no cross-cycle state: `liquidity_sweep()` (equal-high/low stop
  pools + the sweeps that pierce and get REJECTED), `impulse_blocks()`
  (impulse-origin supply/demand zones with mitigation tracking) and
  `ema_trend_pips()` (fast/slow EMA separation as a regime scalar).
  New MarketView fields: `liq_sweep_high`, `liq_sweep_low`,
  `ob_bull_dist_pips`, `ob_bear_dist_pips`, `ema_trend_pips`.
  Live-verified across 8 pairs: sweeps fire on ~2/8 at any moment (correctly
  rare), fresh impulse zones exist on 8/8.
- **12 zero-authority SHADOW setups** (`market_structure` class, registered in
  `config/cell_schema.py`): `liq_sweep_fade_{long,short}` on EUR_USD/asia,
  GBP_USD/london, USD_CHF/london (cells where fades already have broker
  evidence) and `impulse_ob_{long,short}` on EUR_USD/london, GBP_USD/ny,
  AUD_USD/london. Impulse setups require trend agreement; sweep setups do not.
- **`research/tools/ema_regime_gate.py`** — reconstructs `ema_trend_pips` from
  historical candles at each episode's stamp time so the gate hypothesis can be
  tested on 836 existing episodes instead of waiting for forward data.

### Notes
- FX tick "volume" is not size, so these are PRICE-structure features only; no
  claim of reading participation. EMA periods are the TIME-equivalent of the
  source method's 1-minute 69/200 (~70/200 min = 14/40 on M5), not a bar-count
  copy — a literal copy would silently mean 5.75h/16.7h and EMA200 would be
  undercooked in a 240-bar window.
- Implemented independently from public price-structure concepts against our own
  M5 data; no third-party code, terminology, or parameters.

### Fixed
- `test_review_r4` config lock asserted `cheater_promotion_enabled is False`
  forever — i.e. asserted that autonomy never works. The Commissioner
  legitimately flipped it on reaching COMMISSIONED_1 (2026-08-06T12:56Z, first
  time possible after the B-120 fix). Now pins the blast radius (one seat, v4
  ticket, replay window, truth gate) and the fail-closed code default instead.

## [6.21.1] — 2026-08-05 — mid-cycle losses visible in BROKER TRUTH

### Fixed
- **A leg closed mid-cycle was invisible in the cycle columns** (operator
  report: AUD_USD closed −$86.37 at 19:07Z; the row still read cycle WR 100%,
  "last close" Aug 3 — the loss only netted silently into realized $). Cycle
  stats correctly book only COMPLETED cycles (judge-when-flat), so the open
  column now carries the missing signal: unrealized on open legs **plus
  ⏳ realized-so-far inside the current uncompleted cycle**
  (`open_cycle_usd` = family total − completed cycles), and "last close"
  became **"last fill"** (completed-cycle end moved to the tooltip). A
  family having a bad day now looks like one at a glance.

## [6.21.0] — 2026-08-04 — truth-check promotion gate

### Added
- **TRUTH-CHECK GATE** (`truth_check_gate: true`): the governor blocks any
  promotion whose virtual family-cycle sign contradicts the cell's own broker
  fills (full window — era resets never erase real fills). Ledger action
  `PROMOTE-GATED-TRUTH` with the contradiction spelled out; the board mirrors
  the gate as a **TRUTH BLOCKED** verdict so the trophy and the governor can
  never disagree. Cells with no broker record or no virtual cycles pass — the
  gate fires only on a proven contradiction (5 cells at ship).

## [6.20.0] — 2026-08-04 — "V-Cycles" (family-aware shadow scoring + truth checks)

### Added
- **VIRTUAL FAMILY CYCLES on the shadowboard** (V-CYC column): every era stamp
  replayed as a full family — parent + popper grid over real M5 bid/ask
  candles (core/family_cycle.py) — batch-scored by `ops/virtual_scores.py`
  (cron 6h, atomic data/virtual_cycles.json, 170 cells first run). Shown as
  net pips per completed cycle × cycles (cycle WR), with U_pp/U_par/GridLift/
  coverage/worst in the tooltip.
- **TRUTH CHECK badges**: any cell with real broker fills gets its virtual sim
  sign-checked against the FULL broker window (not the era view — demotions
  reset era clocks but real fills stay real). Sim contradicting broker = ❌
  with a "trust BROKER TRUTH" tooltip; agreement = small ✓. At ship: 5 ✓ / 5 ❌.

### Validated (operator: "the shadowboard is way off")
- Parent/horizon stamp sim vs broker sign across all 10 filled families:
  **3/10** — anti-informative (flipped all four biggest losers AND the
  second-biggest winner). Virtual family cycles: **5/10** — sees the grid
  (harvest), but the live-selection effect (charter defect #6: the engine
  executes only the first qualifying ACTIVE setup per pair, so real fills are
  a selected subset of stamps) still separates all-firings metrics from the
  live seat. Hence the layered board: BROKER TRUTH for anything that traded,
  V-CYC for shadow economics, parent-era columns only as the bar's entry-
  signal input — with contradictions flagged, never averaged away.

## [6.19.0] — 2026-08-04 — "Broker Truth" (the real-stats scoreboard)

### Added
- **💰 BROKER TRUTH scoreboard** leading the EDGE LAB tab (operator: "I need
  functional data — this made up shit is useless"): one row per family that has
  ever filled on the broker, every number a real OANDA transaction — realized $
  and pips, completed grid-family cycles, cycle win rate, avg/worst/best cycle,
  open exposure, last close. Served by `/api/broker/truth` from the
  daemon-warmed cache (`ops.shadowboard.broker_truth()`); the audit subprocess
  never runs in a request handler.
- **Account reconciliation line**, the proof of completeness: window realized $
  = attributed + pre-era + unattributed, with an explicit ⚠ if any dollar is
  unattributed. At ship time: −$155.64 window realized, 100% attributed, $0
  unattributed.
- `research/tools/broker_setup_audit.py --json` now emits the `account`
  reconciliation block.
- **SIM badges** on the stamp-forward scoreboard and setup scoreboard cards —
  paper is now labeled paper wherever it appears.

## [6.18.0] — 2026-08-04 — "Functional Data" (governor-grade stat columns)

### Changed
- **EDGE LAB stat columns (avg net/ep, cum net, WR, hit≥trig, hitSL, medMFE/MAE,
  7d, LCB) now compute on the GOVERNOR-GRADE sample**: current era,
  executable-exit-v2 only, mechanics matching the setup's current config, net
  of costs — the exact sample the promotion predicate uses (`governor_sample()`
  in ops/shadowboard.py, mirroring core.trial_evidence filtering).
  Operator audit that forced this: of 174 scored rows the old lifetime blend
  (legacy-mid-v1 frictionless metric + dead config eras + censored stamps) had
  59 rows contaminated with v1 episodes and put the WRONG SIGN on 15 —
  e.g. GBP_USD/london/classic_box_fade_long showed −7.5p (16 of 22 eps were
  frictionless-v1) vs +7.2p on real current-era evidence, while
  EUR_USD/asia/ps_floor_fade_long showed +5.6p (15/17 v1) vs −6.2p real.
  Paper-vs-broker divergence stays visible in the family column
  (EUR_JPY/ny/timing_lean_30: +288p lifetime paper vs −174p broker family).
- **Lifetime blend demoted to context**: a `life` object (n, stamps, avg, cum,
  wr, v1 count) rendered only as a muted `life:` chip + tooltip in the eps
  column, explicitly labeled non-decision data. Rows whose governor sample is
  empty (fresh era after promote/demote) show — instead of dead-era numbers.

## [6.17.1] — 2026-08-04 — stale dashboard cell notes + PROBE display

### Fixed
- **Stale "N ACTIVE, M SHADOW setups." cell notes** (operator report: EUR_JPY/ny
  showed ACTIVE after its strike-2 demotion): the sentence was written once at
  wiring time and never updated by status flips — 10 of the cells were lying.
  `_set_cell_status` now regenerates the counts sentence on every flip
  (hand-written notes untouched); one-time repair applied to all 10.
- **PROBE was invisible in pair rollups**: `/api/cells` status_rollup and totals
  now rank PROBE between ACTIVE and SHADOW (a live 0.33× audition seat is not a
  shadow); panel gets a PROBE color. `tests/test_cell_configs.py` `_STATUSES`
  also predated PROBE-on-disk — tripped by the first real PROBE landing
  (USD_CHF/london/ps_ceil_fade_short, 18:35Z tick).

## [6.17.0] — 2026-08-03 — "Three Strikes" (operator promotion policy)

### Added
- **STRIKE RULE (operator decision)**: every executed demotion is a permanent
  strike, persisted in `governor_state.demotion_counts` and backfilled from the
  full governor ledger (4 cells carried historical strikes at ship time).
  Ever-demoted cells promote only over the stricter **redemption bar**
  (`redemption_min_raw_episodes` 20 / `redemption_min_independent_days` 10);
  first offenders use the relaxed operator bar (10/5, set earlier today with
  `allow_promotions: true`). The strike that reaches `strike_disable_count` (3)
  retires the cell to **DISABLED** — untouchable by automation, manual
  re-enable only. Implemented in the shared evidence engine
  (`required_bar()` + strike-aware `promotion_predicate`), so the governor's
  decision and the dashboard trophy stay one predicate.
- **Dashboard**: 🔻 strike badges (one per demotion, forever) next to the setup
  name with a full-rule tooltip; DISABLED rows in red; THE BAR gate chips now
  read the per-cell required bar (`n…/req` `d…/req`) instead of a hardcoded
  20/10 — they had gone stale the moment the bar became configurable.
- Ledger `DEMOTE` lines now carry `strikes` and `new_status`; a third-strike
  demotion logs `-> DISABLED (three strikes, cell retired)` in `why`.

### Changed
- `config/governor_config.json`: promotion bar relaxed to 10/5 and the
  parent-metric lane switched ON (operator decision, commit 8ac6e1e), with a
  one-time `last_eval_blocks` reset — the sequential-peeking guard caches the
  day-count of failed tests against the OLD bar and would otherwise hold
  every shadow until it earned a new independent day.

## [6.16.0 – 6.16.2] — 2026-07-31/08-01 — "The Edge Lab" (external trials, cockpit, B-119)

### Added
- **External-strategy trial docket** (from a six-repo source audit,
  docs/slates/external_repos_audit_2026-07-31.md — verdict: no repo had a demonstrated
  edge): 42 zero-authority SHADOW cells — TradeClaw's VWAP–EMA–BB pullback ×24 (wired
  WITH its own negative costed test in each evidence note) and EuroScope's regime-routed
  trend/mean-reversion/breakout ×18. New feed features: `vwap_dist_pips`
  (session-anchored VWAP), `adx14` (H1 Wilder ADX). Promotion only via family cycles.
- **Enhanced dashboard**: ⚡ EDGE COMMAND cockpit on the LIVE page (promotion pipeline
  with live counts, admission status, trusted/decay tiles, open-floor hero number, hot
  queue); SHADOW → **EDGE LAB** (purple/cyan identity, NEW badge); governance card grid
  (evidence accounting, risk truth, autonomy lanes, trial docket, decision ledger with
  full reasons); `/api/governor/ledger` + `/api/commissioner` endpoints; prospective
  score snapshots (`data/score_snapshots.jsonl`, hindsight-proof) and
  `research/tools/delta_promotion.py` (E[R_next | promoted] − E[R_next | eligible-not]).
  Structure tests pin the conspicuous pieces AND per-pane div balance (a stray `</div>`
  briefly broke tab switching for every pane after EDGE LAB — caught by the operator,
  now a permanent red test).

### Fixed
- **B-119 (CRITICAL, caught by the Commissioner's reconcile guard)**: OANDA answers a
  close request with HTTP 200 even when the close order is created-and-CANCELLED
  (`orderCancelTransaction`; observed `MARKET_HALTED` over the weekend halt —
  `FIFO_VIOLATION` is the same shape). `close_position` logged CLOSED on any 200, so the
  popper manager booked phantom +8p exits for a still-open trade and the reconciler
  re-adopted it in a churn loop. Fixed at all three layers: typed `CloseRejected` on
  cancel-without-fill; popper stays tracked with 30-min backoff; parent keeps its
  manager. A 200 is transport, not truth — read the transaction inside. Suite 391.

## [6.15.2] — 2026-07-31 — "Health Is Not Edge" (review round 5)

The Commissioner's doctrine, corrected before its first commissioning tick:
**health permits evaluation; evidence permits one PROBE; broker validation
permits expansion.** Commissioning requires ≥2 spaced clean health batteries
AND a current qualifying candidate (a real CHEATER-PROBE admission in that
invocation's dry-run); healthy-with-zero-qualifiers holds indefinitely.
Expansion to 2 seats requires the post-commission graduation + zero
reconciler orphan-adoptions during the audition + a second current
qualifier. First live run under the corrected logic: health=PASS,
evidence=no → holding (correct). Suite 384.

## [6.15.1] — 2026-07-31 — "Full Autonomy" (the Reconciler + the Commissioner)

- **Engine Reconciler**: every 5 minutes the broker's open trades are compared
  against the tracked set — including when the engine tracks nothing (the old
  early-return made the fully-orphaned state the one never checked) — and any
  orphan is adopted on the spot via the now-idempotent recovery path. The
  B-112/B-114 orphan class is closed by standing code.
- **The Commissioner** (`ops/commissioner.py`, cron :55 after each governor
  run): staged fail-closed autonomous commissioning of the cheater-v4 lane.
  Health battery = full suite (unpiped) + governor dry-run + broker/engine
  reconcile + journal CRITICAL scan. Guard failure while commissioned =
  immediate autonomous DECOMMISSION. `allow_promotions` is never touched.
  Every transition ledgered. Suite 380.

## [6.14.9] — 2026-07-31 — "Cheater v4: Earn the Policy"

### Fixed
- **Independent policy qualification:** PARENT_ONLY and FAMILY_PP must each pass the
  risk-covered ticket on their own completed cycles. PP_ON additionally requires a
  positive LCB90 over paired per-episode GridLift; unpaired completed-only means cannot
  choose the grid.
- **Censor/missingness veto:** any unresolved selected-policy cycle or missing replay
  path blocks admission instead of silently shrinking the denominator. Replay covers at
  least the live seven-day grid lifetime plus one resolution day.
- **Era-safe grid transitions:** every promotion, graduation and demotion now quiesces
  new popper fires, retires the exact flat grid, establishes PP_ON/PARENT_ONLY, then
  changes status. Quiescence persists across restart; unknown legacy ownership fails
  closed while open risk is managed out.
- **Status-truth cap and leash:** every current PROBE consumes the one-seat cap and gets
  the fast loss leash. A crash or lost governor-state registry can no longer create a
  second audition or remove its early-stop rule.
- **Crash-safe era ordering:** the fresh evidence era is persisted after grid retirement
  but before the status flip. A crash can discard evidence conservatively; it cannot put
  new capital under an old clock.
- **Production-path coverage:** candidacy, policy selection, seat bookkeeping, grid
  retirement/restart reconciliation and transition ordering are pinned in the round-4
  suite. Both admission switches remain OFF for commissioning; Cheater is explicitly
  capped at one 0.33× whole-family PROBE seat.
- **Honest commissioning command:** `--dry-run --cheater-diagnostic` evaluates the raw
  candidate docket while admission stays OFF and can never queue a flip.

## [6.13.0] — 2026-07-31 — "The Unit of Evidence" (B-117 + interim safety)

Start of the Family-Cycle program: an external design review (docs: see repo discussions
and the Book of Bugs) demonstrated the shadow scorer grades a materially different system
than the live one, and its recommendations are being implemented in V6, item by item.

### Fixed
- **B-117 — family attribution**: families now keyed (instrument, SESSION, setup) — the
  old join merged same-named setups across sessions; poppers inherit their parent's
  session. Family evidence now counts **completed GRID CYCLES** (legs chained by
  open-interval overlap; flat = boundary; open-extended cycles censored), not closed legs.
- **Governor verdicts on cycles, asymmetric** (charter): convict at ≥2 completed cycles on
  net ≤ −60p **or ONE catastrophic cycle ≤ −90p**; defend requires ≥3 completed cycles at
  net ≥ +60p. Judge-when-flat unchanged.

### Changed (interim safety, pending family-cycle-v3)
- **🎲 Cheater promotions OFF** — the +100p cumulative parent-horizon ticket was shown
  structurally divergent from broker family results (sign agreement 2/7). Existing cheater
  seats remain, governed by the family leash. The lane returns with a risk-covered v3 ticket.
- **Era/stamp columns relabeled as PARENT/HORIZON DIAGNOSTICS** on the dashboard — they
  simulate the parent only, force-closed at horizon, with coarser ratchet steps than live;
  they are not projected live performance.

Suite 312 (7 new: cycle chaining, censoring, session split, catastrophic-cycle bench,
defend-needs-more-cycles).

## [6.12.7] — 2026-07-31 — "Plot Time on the Time Axis"

### Fixed
- **B-116 — the README live-equity card froze between closes**: it plotted only the
  realized curve on a per-trade index axis, so a morning with six open trades and a
  $160 NAV swing rendered as a stale flat line (operator read it as a dead updater —
  correctly, since the two are indistinguishable). The card now draws on a TIME axis:
  bold realized steps at each close + a thin hourly NAV line (incl. open trades) from
  equity.csv, with legend and end-dots. Suite 305.

## [6.12.6] — 2026-07-31 — "One Move, One Vote"

### Fixed
- **B-115 — the Setup Scoreboard counted stamps as trades**: the engine re-stamps a
  setup every scan cycle while conditions hold, so one runaway afternoon read as
  "78 trades, 100% WR, +67.9p" (true record: 15 episodes, 8W/7L) — and the
  recent-50-stamps sim cap meant that single clustered day WAS the sample. The scorer
  now collapses stamps into episodes (≤30 min apart = one entry decision, same rule as
  the shadowboard) and sims one entry per episode; the table shows `N eps (stamps)`.
  Poster child: `kc_up_short_lean` "503 trades / 100% WR / +7.2p" → **10 episodes /
  62.5% / −5.2p**. No restart needed (scorer is a subprocess; panel served from disk).
  Suite 305.

## [6.12.5] — 2026-07-31 — "Three Different Programs" — CRITICAL for LIVE accounts

### Fixed
- **B-114 — recovery orphaned live poppers after restart (regression introduced BY the
  B-112 fix)**: 6.11.1's critical-fields-first comment reorder pushed `sl`/`tr` past the
  live account's ~32-char clientExtensions truncation, so the recovery classifier's
  `sl`+`tr` test misclassified every truncated popper as a parent — and the
  one-parent-per-pair rule silently swallowed the rest of that pair's trades. Found live:
  a 4-trade GBP grid unmanaged for ~9 hours, stops still at −60p while +30p in profit.
  The classifier now recognizes both comment formats by whatever survives truncation, is
  extracted to `_looks_like_popper()` with regression tests pinning the exact mangled
  live copies, and the parent-collision skip logs a WARNING naming the unadopted trade.
  **If you run a LIVE (not practice) account on 6.11.1–6.12.4: any bot restart with open
  poppers orphaned them — pull this release and restart once while flat, or verify your
  open trades on the dashboard after restarting.** Suite 301.

## [6.12.4] — 2026-07-30 — "The Death Rate"

### Added
- **`hitSL` column (operator rule, Brock)**: share of episodes whose MAE reached the
  setup's **config SL − 0.5p** (mid understates adverse excursion — the executable side
  hits the stop first). The mirror of `hit≥trig`: engage locks +6 and cannot lose, death
  eats the full stop, and at lock 6 / SL 60 **one death costs ten engages** — the two
  columns together are the breakeven math. Strongest single-stat predictor tested so far
  (ρ −0.47 with per-cell net, 33 cells n≥8); the trap-cell autopsy completes: GBP/ny
  `ps_ceil_fade_short` engages 75% but dies 25% — 3 engages per death against the 10
  required. Every top live family reads 0%.

### Changed
- **Both hit columns now read per-setup geometry from `config/cells`** (trigger_pips /
  sl_pips, incl. range-sized stops 40/50/60) instead of constants — a re-tuned gear
  re-scores the columns on the next board build.

## [6.12.3] — 2026-07-30 — "The Engage Rate"

### Changed
- **`hit≥6p` → `hit≥trig` (operator rule, Brock)**: the SHADOW board's hit column now
  measures the share of episodes whose MFE reached the setup's **ratchet trigger + 0.5p
  mid-price buffer** (book gear 8.5 → 9p, `_t20s` gear 20 → 20.5p) instead of the 6p
  lock level. Engagement is the causal event — an engaged trade locks +6 and cannot
  lose — while the old stat flattered "almost-winners": measured on 100-trade-era
  episodes, `rvol_low_240_t20s` (the forward test's −$858 family) touched +6p in 61%
  of episodes but reached its actual 20p trigger only 17% of the time. Rank
  correlation with per-cell net improves (+0.35 → +0.42, 34 cells n≥8); WR/family
  net remain the scoreboard — the new column's job is diagnosis, and a wide
  hit6-vs-engage gap was the almost-winner signature all along.

## [6.12.2] — 2026-07-30 — "Trust the Switch"

### Fixed
- **B-113 — manual status flips were invisible for up to 15 minutes**: the SHADOW
  board's payload is cached (rebuilt at most every 15 min) and each row's status was
  baked in at build time, so flipping a cell ACTIVE from the dashboard changed what the
  engine trades immediately but the board kept showing the pre-flip snapshot. Now
  (1) `get_board()` re-joins `config/cells` at serve time — live status always wins,
  rows re-tier and re-sort in place; (2) `POST /api/cell/status` invalidates the board
  cache so the next load kicks a full rebuild. Aggregates may be cached; **state never
  is**. Five regression tests; suite 296.

## [6.12.1] — 2026-07-30 — "Guardrails on the Dice"

Same-day hardening of the cheater rule, plus a status-semantics guarantee.

### Changed
- **Cheater floor: `cheater_min_n` = 3** — one lucky episode can't buy a seat. The +100p
  cumulative must span at least 3 era episodes.
- **Cheater check now precedes the sequential-peeking guard** — the guard exists to stop
  re-rolling unchanged evidence against the *statistical* bar; a fixed threshold has no
  p to hack, so it evaluates every run. (Found live: the first cheater candidate was
  silently skipped until this reorder.)
- **First CHEATER-PROMOTE executed**: `CAD_JPY/asia ps_ceil_fade_short` — the March-replay
  resurrection cross — promoted on era cum +116.8p (5/5 green episodes). Same run: second
  autonomous family-red demotion (`USD_JPY/london timing_lean_30`, −175.4p family).

### Added
- **DISABLED IS SACRED**: a manually disabled setup is untouchable by every automation —
  the bar, the cheater rule, the counterpart audit, all of it. Beyond the existing loop
  filters, `flip()` now re-reads the LIVE status at flip time (promote requires
  currently-SHADOW, demote requires currently-ACTIVE), so disabling a cell by hand
  mid-run can never be overridden by a stale snapshot. Regression-tested; documented in
  GOVERNOR.md. Suite 291.

## [6.12.0] — 2026-07-30 — "The Operator's Amendments"

Three operator-ruled changes. Two are amendments to the published freeze, disclosed as
such: the governor's cadence and the opt-in cheater rule change *trading governance*, by
Brock's explicit decision, after two days of live observation. The FIFO fix is an
environmental defect repair.

### Fixed
- **Two-step FIFO dodge (B-097 escalation)**: US live accounts were rejecting attached-SL
  popper orders whenever older same-instrument trades were open — thinning grids to about
  half the tested density. On a FIFO no-fill, the fire now retries ONCE as a naked market
  order and attaches the stop immediately after the fill; if the stop cannot be attached,
  the position is closed on the spot — **a popper is never left naked**. Two regression
  tests cover both paths.

### Changed (operator amendments to the freeze)
- **The governor runs every SIX HOURS** (00:35/06:35/12:35/18:35 UTC; was daily 06:35Z).
  Seats are won and lost four times a day; the sequential-peeking guard already prevents
  re-rolling unchanged evidence between runs.
- **🎲 CHEATER PROMOTION — opt-in, default OFF**: a dashboard toggle (Bar Governor card)
  that, when enabled, promotes any shadow whose current-era v2 **cumulative net reaches
  +100 pips** immediately — no 20-trade bar, no day-block minimum, no bootstrap/FDR. A
  hot hand gets its seat without waiting out the sample; the family rule demotes it if it
  cools. Era discipline still applies (legacy v1 history can never trigger it). Every use
  is ledgered as CHEATER-PROMOTE; the toggle carries its own instruction and confirm.

Suite 290 green.

## [6.11.1] — 2026-07-30 — "The Two Endpoints" — CRITICAL fix for LIVE accounts

**If you trade this bot on a real-money account, update now.** B-112: OANDA **live**
accounts return mangled `clientExtensions` on the *trades* endpoint — `tag` comes back
`"0"` and `comment` truncates to ~32 characters — while the *transaction* stream carries
them pristine. Practice accounts don't do this, so nothing in the practice era could have
caught it. Consequences on our live box (day two): after a process restart, **two open
poppers were not re-adopted** — unmanaged for ~16 hours (server-side stops held; no
ratchet locking profits) and invisible to the dashboard — and the same blindness made
their family read "flat," so it was **demoted mid-episode** (a judge-when-flat bypass;
the verdict happened to survive full-data review).

### Fixed
- **Recovery is tag-agnostic**: poppers vs parents classified by comment *shape* (tag is
  a hint only); both decoders regex-extract whatever fields survive truncation. Verified
  live: both orphans adopted on restart, the ratchet locked +24p and +16p within seconds,
  one banked green minutes later.
- **Comment encoding is truncation-resilient**: critical fields lead the string — `su`
  first in parent gear comments, `anc`/`lvl` first in popper comments — so even a 32-char
  surviving prefix carries what recovery and family attribution need.
- **Family/open-trade attribution reads the pristine source**: open trades attribute from
  their opening *transaction* record, falling back to the trades-endpoint copy only when
  necessary — judge-when-flat can no longer be blinded by the endpoint mangling.

Full write-up: Book of Bugs **B-112**. Suite 287 green.

## [6.11.0] — 2026-07-29 — "Day One, Live" — the first-day patch series

Everything the first hours of real money exposed, fixed the same day. The freeze holds:
every change below is a defect fix or a truth-of-reporting fix — no new trading behavior.

### Fixed
- **B-107 — the first live fill sized at 10%, not 15%**: the cutover wrote the live gearing
  as dead top-level JSON keys while the sizing readers pull from the `account` block.
  Caught on trade #1 within minutes, fixed through the actual readers, hot-reloaded.
- **B-108 — Setup Scoreboard crashed on the replay crosses** (`KeyError: AUD_CAD`, a fourth
  private 8-pair map) — plus the follow-through: **all research tools now import the
  canonical 18-pair map** (four more private copies retired).
- **The dashboard said PRACTICE while trading real money** — credentials mode flipped to
  live (red "LIVE — REAL MONEY" header), `SCROOGE_ALLOW_LIVE` armed, stale July-5
  shadow-week banner replaced with the live-era status line, governor-ledger
  `undefined/undefined` render fixed.
- **Deposit-aware livelog**: `TRANSFER_FUNDS` backed out of the reconstructed start
  balance; headline % is simple-Dietz time-weighted; `net_deposits` column; the README
  discloses added capital automatically. External money can never read as trading P/L.
- **Popper fire tests isolated from the live runtime pause** (the cutover freeze turned
  10 tests red — fixtures were reading production `config/runtime.json`).

### Changed (reporting truth, operator-ruled)
- **The 100-trade record finalized per the protocol as written**: the window is the first
  100 closed trades — **90W/10L, 90.0%**, realized +$1,793.50 — trade #100 (an operator
  close) daggered in-window, #101 asterisked post-window; broker-diff verified the tape
  complete. The record moved to its own top-level **`forward-test-100/`** (out of
  `livelog/`, which now holds only the real-money log), with a folder README, a
  normalized one-schema equity CSV, and the **forward-test stat card** leading the README
  (`research/tools/forward_test_card.py` — computed from the tape, never typed).
- **Shadowboard truth pass**: 🔻 DEMOTE DUE now tops the board (most actionable, worst
  first); **AWAITING V2** verdict distinguishes legacy-history rows from never-scored
  QUEUED rows (v1 history never counts toward the bar — the era reset, stated in-place);
  both long explainers collapse to one-line summaries.
- **Research release pointers**: waves 1+2 of the archive data/tools release
  (7 corpora + 3 tool bundles public, deep-swept; one backup bundle private permanently
  after the sweep located an embedded credential) — see `docs/DATA_AND_MODELS.md`.

## [6.10.0] — 2026-07-29 — "Real Money" — THE LIVE CUTOVER + VERSION FREEZE

The pre-registered protocol executed end to end. The practice window closed at
$16,665.12 → $18,421.85 (+10.54%; the 100-trade window went 90W/10L = 90.0% WR vs 82.2%
breakeven; the single post-window operator close asterisked). The same code, same book, same governor now trades
$2,500 of real money.

### Changed
- **Live account wired** per protocol: gearing 15%/trade · 6 concurrent (was 10%/8),
  popper total-margin cap 0.9. Book continuity verified: config/cells untouched, every
  ACTIVE stayed ACTIVE, every SHADOW stayed SHADOW, era clocks intact.
- **Livelog re-anchored to the live account** (anchor 2026-07-29): same hourly pipeline,
  trades + equity + README chart, numbers only. Practice record archived immutable at
  forward-test-100/; full raw broker export (11,564 transactions,
  account creation → close) public in the archive under proof-of-tape/.
- **README finalized**: real-money badges and track-record block, final account tape,
  the patience-game section (red-for-days is the design), concluded-test framing,
  Book of Bugs B-099→B-106.

### FEATURE FREEZE
This repository now changes only to **fix reported bugs**. Significant future
development ships as **Mr. Scrooge V7**, separately. The live record publishes hourly
regardless.

## [6.9.0] — 2026-07-28 — "The Hundred-Trade Protocol"

The forward test gets a pre-registered endpoint and a declared consequence — before the
result is known.

### Added
- **docs/FORWARD_TEST_PROTOCOL.md**: the current-config window ends at its **100th closed
  trade** (anchor 2026-07-16 01:11Z, starting balance **$16,665.12** broker-verified).
  At n=100: freeze practice entries, manage open positions to natural exits (the record
  ends flat), publish the write-up, close the practice account, and go **live with $2,500
  real money** — `margin_pct_per_trade` 0.10→0.15, `max_concurrent_trades` 8→6, popper
  `max_margin_pct_total` 0.8→0.9 (so the total-margin cap can't bind below 6×15%),
  everything else exactly as tested. The live account publishes the same hourly livelog
  (trades + equity graph, numbers only) so the record continues in public.
- **research/tools/forward_test_100.py**: the write-up generator — start/end balance,
  tape geometry, breakeven-WR vs delivered, per-family attribution, mid-window changes
  disclosed. One command on the day.
- **livelog trigger**: the hourly cron raises a one-time flag + operator alert the hour
  trade #100 closes.

## [6.8.1] — 2026-07-28 — "The Bar, Visible"

### Added
- **era v2 bar column** on the Shadowboard: the five promotion conditions with their live
  values — n/20 episodes · d/10 day-blocks · avg vs +2.0p · block LCB vs 0 · q vs 0.05 —
  each element turns green as it is met; all green = PROMOTE READY. The deciding numbers
  for promotion now sit in a visible column beside the verdict, mirroring how the family
  column already shows the deciding numbers for demotion. Replaces the lifetime-LCB
  column (the old sort key, which decided nothing).

## [6.8.0] — 2026-07-28 — "The Board Explains Itself"

The SHADOW tab now states the whole standard and sorts the whole docket exactly as the
governor acts — the dashboard and the 06:35Z run can never tell different stories.

### Added
- **Governor verdicts on every Shadowboard row** (`ops/shadowboard.py`): each ACTIVE/SHADOW
  row carries the verdict the governor's own code would reach today — DEFENDED / HOLDING /
  DEFERRED (episode open) / PROMOTE READY / BUILDING (with the bar conditions still
  failing) / QUEUED / DEMOTE DUE — plus its broker **family** view (era net pips, closed
  trades, open-trade count). Family data comes from the same `broker_setup_audit` families
  block the governor reads, cached 10 min, fetched only in the board's daemon thread.
- **Governor-ordered board**: rows sort by verdict tier — defended seats first, then
  holding/deferred, promote-ready, building (ranked by conditions passed), queued, and
  demote-due at the bottom — with tier group headers in the SHADOW tab. The old lifetime-LCB
  order remains only as the fallback for rows outside the governor's view (EX-SIDE).
- **SHADOW tab explains the rules**: the Bar Governor card now states the full promotion
  bar, the FAMILY RULE with thresholds (−60p demote + poppers off / +60p defends), and
  judge-when-flat; the Shadowboard legend explains the sort, the verdict column, and the
  family column. New columns: **verdict**, **family (broker)** with ⏳ open-trade badges.

### Fixed
- Governor ledger card rendered `undefined/undefined/undefined` for ERA-RESET entries
  (they carry `key`, not pair/session/setup).

## [6.7.1] — 2026-07-28 — "Judge When Flat"

Brock's boundary case: a parent stops −60p while its poppers are still riding toward +30 —
convicting (or defending) mid-episode judges half a scale-in, and a mid-episode demotion
would switch the poppers off right before the harvest.

### Changed
- **No family verdict while any family trade is open.** `broker_setup_audit.py` now
  family-attributes OPEN trades too (`n_open`/`open_upl` per family; open-only families
  emitted); `active_verdict` returns `episode_open` and defers ALL demote/defend judgment
  until the family is flat. Closes are era-clocked; open exposure never is. Natural
  backstop: grids age out at 7 days, so "never flat" isn't a path. Tests 283 → 287.

## [6.7.0] — 2026-07-28 — "The Family Rule"

Demotion re-grounded in broker truth at the FAMILY level (Brock: "net loss is the key").
The 7/16→7/28 forward test showed per-leg views mislead both ways: kc_up_long_lean's
parents were red (−$74) inside a +$718 family, while rvol_low_240's 2-trade parent leg hid
a −$858 family — the book's single loss driver, invisible to the old cell_v1-only fills
rule (poppers were excluded from demotion evidence entirely).

### Added
- **Popper self-attribution**: every popper order's client-extension comment now carries
  `psu` — the parent setup id that armed its grid (`modules/management/party_package.py`).
  Recovery adopts it; comments stay within OANDA's 128-char cap.
- **Families view** in `research/tools/broker_setup_audit.py` (`"families"` in `--json`,
  FAMILIES table in text): parent + its poppers as one economic unit, per (instrument,
  parent setup) — pre-psu fills join via grid anchor ≈ parent entry (≤30p, direction-matched).
- **THE FAMILY RULE** in `ops/governor.py` (`active_verdict`, unit-tested): family era
  net pips ≤ **−60p** with n ≥ 5 → DEMOTE **and the cell's popper switch goes off with the
  seat** (`/api/pp/toggle`; the fire gate re-checks per-cell state, so armed grids stop);
  family ≥ **+60p** → the seat is DEFENDED — bar_lost (worst-case stamp simulation) cannot
  demote a family that is paying rent on the broker. Family evidence is era-clocked per
  setup via per-trade open times, so a mechanics change is never convicted on old trades.
- Config: `family_min_trades` (5), `family_demote_pips` (−60), `family_defend_pips` (+60);
  `fills_n`/`fills_avg_max` retired with the parents-only rule.
- 15 regression tests (`tests/test_family_ledger.py`): psu stamping/truncation/recovery,
  family attribution (psu + anchor join, direction + distance guards), era re-clocking,
  and the demote/defend verdict matrix. Suite 268 → 283.

## [6.6.1] — 2026-07-28 — "Honest to the Pip"

D-7 shipped whole: the statistics-v2 + shadow-execution-truth program from external review
round 2 (spec: docs/REVIEW_R2_PLAN.md). Shadow trials are now measured the way live trades
are paid, and a dashboard trophy is *computed by* the governor's promotion predicate — the
two can never disagree.

### Added
- **TRIALSTAMP v2 events** (`core/trial_events.py`): one structured JSON stamp per
  qualifying setup carrying bid/ask, the EXECUTABLE entry (ask long / bid short), spread,
  horizon, the setup's exit geometry, and a mechanics hash. Legacy CELLSHADOW lines still
  emit for old consumers.
- **Shadow exit simulation** (`core/shadow_execution.py`): each shadow episode is scored by
  replaying the setup's OWN exit — the live ratchet's floor-step lock (cadence-gated) or
  bracket TP/SL/timeout — over executable bid/ask candles from the stamped entry.
  Intrabar ambiguity resolves worst-case (stop first) and is flagged.
- **One shared evidence engine** (`core/trial_evidence.py`): day/session **block
  bootstrap** (deterministic seeds — identical evidence yields identical bounds),
  **Benjamini–Hochberg FDR** across the whole candidate docket, and a single
  `promotion_predicate` with explicit failure codes (RAW_N / INDEPENDENT_DAYS / AVG /
  LCB / RECENT / FDR), consumed by the governor AND the Shadowboard trophy.
- **Sequential-peeking guard**: a setup that failed the bar is re-tested only after at
  least one NEW independent day-block — daily re-rolls of unchanged evidence can't fish
  over the line.
- Board rows expose per-row `era` evidence, `n_v2`, and ambiguous-bar counts; trophy/warn
  chips carry the full evidence tooltip.

### Changed
- **Promotion standard** (governor + trophy, identically): raw n ≥ 20 executable-exit-v2
  episodes · ≥ 10 independent day/session blocks · avg ≥ +2.0p net · block-bootstrap
  LCB > 0 · 7-day guard · BH-FDR q ≤ 0.05. New knobs in `config/governor_config.json`
  (`min_raw_episodes`, `min_independent_days`, `bootstrap_reps`, `bootstrap_confidence`,
  `fdr_q`).
- **Version-aware costs** (`core.trial_stats.episode_net`): v2 episodes pay slippage only —
  the spread is already inside their executable geometry; legacy episodes keep paying
  stamped-spread + slippage. No double-charging, no free rides.
- **METRIC-ERA-RESET**: ledgered for all 146 live setups — legacy-mid-v1 evidence measured
  a different (frictionless) quantity and does not carry over. Every trophy restarts from
  zero under the honest metric; broker-fills demotion keeps guarding the ACTIVE book daily.
- README, GOVERNOR.md, and RESEARCH_PROGRAM.md (D-7 → SHIPPED) track the new standard.

### Fixed
- **Remote dashboard access after the R2-4 hardening**: the Host allowlist knew only
  loopback names, so Tailscale-serve / SSH-tunnel hostnames got 421s. Documented
  `DASHBOARD_ALLOWED_HOSTS` (docs/DASHBOARD.md) and allowlisted the operator's access
  names via a systemd drop-in; rebinding protection unchanged (unknown hosts still 421).

### Tests
- Suite 223 → **268** across randomized orders: simulator geometry (trail-out at the exact
  lock, worst-case ambiguity, short symmetry, brackets), stamp fold semantics
  (no double-count, no late re-anchor, idempotence), version-aware costs, bootstrap
  determinism, BH known values, every predicate failure code, era clocks end-to-end.

## [6.6.0] — 2026-07-28 — "The Review"

An external code review found six real defects — and every one is now closed. This release
is the project's doctrine applied to itself: outside scrutiny treated as evidence, verified
against the code, fixed with regression tests, and credited. The bot now measures itself in
the same units it trades in.

### Fixed (review findings 1–4)
- **Trial fairness**: cell evaluation returned on the first qualifying ACTIVE setup,
  silently starving every later setup of evaluation and stamps that cycle — config-order
  bias aimed straight at the newest hypotheses (always appended last). Every setup now
  evaluates and stamps every cycle; selection semantics unchanged.
- **The canonical config validator** had drifted to the July-04 schema (rejecting all 18
  live files) while nothing enforced it. Schema synced (incl. the pair universe now
  imported from config/pairs.py) and enforced in the test suite with anti-vacuity
  corruption tests — schema drift is a failing test, in CI, forever.
- **Dashboard writes reject cross-origin**: the Access-Control-Allow-Origin:* wildcard is
  gone and every POST passes a same-origin guard (Origin must equal Host — DNS-rebinding
  safe; curl/same-machine tools unaffected).
- **Runtime controls fail CLOSED with last-known-good**: a corrupted pause file can never
  restart trading, a corrupted popper config can never re-arm grids or erase per-cell
  opt-outs, a corrupted governor config disables the run. The legacy fail-open test was
  doctrine-reversed to pin the new contract.

### Added (review findings 5–6, shipped as D-5 and D-6)
- **D-5 — Execution truth** (staged, each restart-verified): the server-side SL is sent as
  a fill-anchored DISTANCE (slippage can no longer resize the real stop); parents and
  poppers adopt the broker's orderFillTransaction price as the true entry, with per-fill
  quoted/filled/slippage/spread logging; parent and popper management (peak, engage, lock,
  trail, net) runs on executable bid/ask instead of mid; every order carries a durable
  sv6-* intent id with broker reconciliation on transport errors — an accepted-then-timeout
  order is adopted, never orphaned; a never-arrived order raises with safe-to-retry
  semantics.
- **D-6 — The statistics program**: one net-of-cost utility for promotion AND demotion
  (stamps carry their live entry spread; scoring pays spread + slippage before any
  verdict — the +2p bar now means +2 after the toll, literally); overlap-aware effective
  sample size (240m labels on 30m-spaced episodes are not independent); deflated promotion
  confidence (z 1.645 → 2.33) with an explicit hypothesis registry (M=146 at ship) so the
  multiple-testing denominator is public; era clocks reset on ANY change to a setup's
  mechanics via config hash. The Shadowboard displays the exact metric the governor judges.

### Changed
- README overhauled: regenerating account tape (from broker balances, all eras marked),
  trial-loop pipeline diagram, live dashboard screenshots (headless capture pipeline +
  panel #tab deep links), text current through the governor era.

Credit: the six findings came from an external reviewer's unsolicited audit. This is what
CONTRIBUTING.md means by "external ideas welcome" — the gauntlet works in both directions.

## [6.5.0] — 2026-07-27 — "The Governor"

The autonomy release. The project's thesis was always an autonomous trading bot; this is
the version where the loop actually closes — hundreds of strategies earn or lose their own
seats, by a published standard, with the switch and the spec on the dashboard for any
operator.

### Added
- **The Bar Governor — autonomous promote/demote** (Brock, 2026-07-27): `ops/governor.py`
  (daily 06:35Z) closes the trial loop. SHADOW -> ACTIVE when current-era evidence clears
  the bar (n>=20, avg>=+2.0p/ep, LCB>0, non-negative 7d); ACTIVE -> SHADOW when the bar is
  lost on era stamps or era broker fills go net-negative (n>=5). Rails: 2 promotions +
  4 demotions/day max, config-side evidence only, sides never flipped, manual_only
  respected, all flips via the dashboard's own validated writer, every decision in
  data/governor_ledger.jsonl, per-setup era clocks in governor state (a flip restarts the
  evidence window). Tunables in config/governor_config.json. The bot now grants and
  revokes its own seats; the humans set the standard.

- **Governor dashboard card** (SHADOW tab): AUTO-PROMOTE/DEMOTE ON/OFF toggle for any
  operator (GET/POST `/api/governor`, atomic merge-preserving write, confirm dialogs both
  ways), the standard inline, the ledger tail, and a How-it-works link to the new
  **[docs/GOVERNOR.md](docs/GOVERNOR.md)** — the loop, the numbers, why they are what they
  are, the rails, the era clocks, every tuning knob.
- **MAE-flip counterpart audit — standing daily rule**: if a losing setup's median adverse
  excursion outsizes its favorable by >=1.5x (n>=5), it needs a counterpart firing the
  opposite direction at the same trigger — `research/tools/counterpart_audit.py` wires them
  automatically (daily 06:30Z, before the governor), SHADOW, fresh era, honest
  `_counter_<side>` names. First sweep: 3 signatures, 1 new counterpart
  (`timing_lean_30_counter_long` GBP/asia); harvest-problem losers (MFE >= MAE) correctly
  excluded.
- **Counterpart policy replaces in-place side flips**: setups keep their name-true
  direction forever; promising mirrors get their own setup, name, and record
  (`classic_box_fade_long` restored LONG/SHADOW; `classic_box_break_short` carries the
  winning direction with its 12-ep history via the new `config/setup_aliases.json`;
  `rvol_low_240_short` wired). The Shadowboard and governor are alias-aware, and the
  status join is side-aware — a retired side can never wear the live side's badge.

### Changed
- **All DISABLED setups -> SHADOW** (nothing is beyond the reach of evidence; under the
  governor, a seat can only be re-earned through the bar). Also enabled the USD_CHF
  london/ny session blocks that had been silently muting their april-replay setups.

## [6.4.0] — 2026-07-27 — "The trial docket"

The release where the old research record was formally arraigned: errata published on the
pre-V5 era's public documents, and every salvageable claim from them re-filed as a live
shadow trial. Plus the contest that invites the world to join the docket.

### Added
- **The $10,000 Strategy Contest** ([CONTEST.md](CONTEST.md)): sponsor-funded standing
  challenge — submit a fully mechanical, evidenced, novel strategy; it runs 30 days in the
  forward-test harness. Path A: >=90% WR and profitable with avg winner >= half the avg
  loser; Path B: net +500 pips; both >=20 trades, no >3-market-day gap. First qualifier
  wins $10k ($10k/$5k on simultaneous qualifiers); maintainer is sole judge; measurements
  final. Submission via issue template; badge graphic; README section.
- **Strategy E on trial**: the June white paper's trend-pullback short (EUR/USD), wired as
  a SHADOW setup with the paper's gates in MarketView terms. Errata prepended to the
  archived paper (its numbers predate the 2026-07-03 H1 look-ahead fix and rode the
  falsified ladder/tight-stop exits; the method graduated, the numbers must re-earn).
- **D-4 — the Strategy-Book cube on trial**: five threshold-translatable book strategies
  (alpha_extended_fade both sides, echo_box_fade both sides, MR2 bb-reversion, RG1
  range-scalp) wired verbatim as 48 SHADOW setups on the cube backtest universe
  (AUD/EUR/GBP_USD, USD_CAD x london/ny). Six multi-bar pattern strategies are not
  expressible in the condition schema without new feed features — documented in
  RESEARCH_PROGRAM section D-4. Errata sheets added to all archived Strategy Book
  workbooks.

## [6.3.1] — 2026-07-27

### Added
- **Shadowboard queued rows**: every wired ACTIVE/SHADOW setup with zero scored episodes now
  shows as a dimmed ⏳ row (sorted below all scored rows) — the trial docket is visible;
  waiting is a state, not an absence. Board went 41 → 94 rows across 17 pairs.
- **Automated live-bot backup** (infrastructure, off-repo): daily verified tarball of the full
  bot + dashboard working tree to two destinations (cloud + cold drive), change-gated,
  secrets excluded, 14-generation retention.

### Changed
- Docs: Dropbox archive paths updated to the consolidated `/SCROOGE/` folder structure
  (the public share link is unchanged and survived the move).

## [6.3.0] — 2026-07-27 — "Strategies on trial"

The release where the README stopped underselling the system: Scrooge is not "a bot with no
strategy" — it is a bot that **puts strategies and entry/exit indicators on trial**, promotes
the ones that prove themselves as shadows, and demotes the ones that degrade. This release
ships the trial machinery upgrades (LCB ranking, honest chips, broker-truth audit) and the
biggest expansion of the trial docket since the cell cutover: 10 replay pairs, 18 scanning.

### Added
- **The replay shadow book — 10 never-traded pairs on trial (D-3)** (Brock, 2026-07-27):
  CAD_JPY, AUD_CAD, EUR_CAD, GBP_CAD (March tape), EUR_CHF, CHF_JPY, AUD_CHF (April 1–7 tape),
  NZD_USD, NZD_JPY, GBP_JPY (April 16–17 tape) — resurrected from this account's own pre-V5
  transaction history, where session-extreme fades and trend-pullback entries recurred as
  winners. All SHADOW-only: `ps_floor_fade_long` (asia), `ps_ceil_fade_short` (asia + ny, and
  USD_CHF london/ny), `trend_pullback_long` (london/ny — the 2026-06-14 discovery-engine entry,
  first time wired). Promotion strictly via the activation bar (n≥20 eps @ ≥+2p/ep); the
  standing prior is that cross spread toll kills most of them — that verdict is the point.
  Evidence and counter-examples (the USD_MXN broken-floor knife; the NZD_USD 990/1014
  identical-entry loss/win pair) are written into the cell files and RESEARCH_PROGRAM §D-3.
- **`research/tools/view_at_time.py`**: replay the live feed's exact `_compute_features` on
  candle windows ending at any historical instant — "what did the indicators say when this
  trade was entered," for any OANDA instrument, using the same formulas the bot trades with.
- **INDICATORS tab: why-is/isn't-it-firing** (Brock, 2026-07-26): each pair card leads with the
  current session's ACTIVE setups and their live condition bars (range zone + marker, server-
  computed pass/fail), a READY badge + green card glow when all conditions pass, an "n/m OUT"
  badge naming what's blocking, and an explicit "no ACTIVE setups this session — this pair
  cannot fire" note. Legacy V4 furniture (mcert/dcert/dir.sc gauges, direction/vol pills)
  removed; sparklines fixed (ring buffer was keyed on always-empty legacy tickets — willr/rsi/
  vortex/kc_up/cpos sparks had never drawn in the cell era).
- **Shadowboard LCB column + sort** (2026-07-24): `LCB = avg − 1.645·sd/√n` (95% one-sided
  lower bound on avg net/ep) per row, now the board's sort key — small-n glamour rows rank
  below proven ones; n<2 shows "—" and sorts last.
- **`research/tools/broker_setup_audit.py`** (2026-07-24): per-setup broker-truth scoreboard —
  joins `tradeOpened` client-extension setup ids to closed fills over an era window. Fills
  convict faster than stamps; this is the tool for that doctrine.
- **`DASHBOARD_HOST` env var** ([#2](https://github.com/BrockStar3540/mr-scrooge-v6/issues/2),
  2026-07-26): configurable dashboard bind address (first community feature request). Default
  stays `127.0.0.1`; the panel is unauthenticated with write endpoints, so wider binds are
  opt-in — security note in `docs/DASHBOARD.md`.

### Fixed
- **Setup Scoreboard + stamp feed dead since the 07-22 overhaul** (B-098, 2026-07-24): a
  status-join edit pasted a helper into the middle of the scorer's `main()`, silently
  truncating it (exit 0, empty stdout); the server's journal-unit default still pointed at the
  retired dry-run unit; and the scoreboard cache's refresh flag reset sat after a `return`, so
  one failure wedged the error until restart. All three fixed; scorer sim cap now takes the
  most recent 50 stamps (was oldest-50, which blanked SimEV on the highest-n setups).
- **Broker-cancelled fire treated as a fill** (B-097, 2026-07-24): OANDA's FIFO safeguard
  rejected a popper's on-fill SL and `_fire` registered the fill-less response as success —
  82 re-fires on one marker in ~9h (no fills, no fees). Fires now verify a real fill; rejected
  fires cool the marker 30 min; 3 straight rejections suspend the grid 2h.
- **Shadowboard trophy was still beat-the-median** (2026-07-27): the 07-22 doctrine says 🏆 =
  activation bar met; the panel never wired `bar_met` (a 3-episode row edging the ACTIVE median
  by 0.07p wore a trophy) and the ⚠️ ACTIVE-without-bar-evidence chip was never rendered. Both
  now live; first honest census: zero shadows hold the bar, 2 of 10 ACTIVE setups do.
- **The pair universe existed in three files** (2026-07-27, B-098 family): the dashboard
  server carried its own hardcoded 8-pair list, so new pairs scanned and stamped but never
  appeared on the book endpoint. `config/pairs.py` is now the single source of truth.

### Changed
- **Popper marker ladder** (Brock, 2026-07-22): grid markers are now an explicit offsets list
  `pp_config.marker_pips` — default **−10, −15, −20, −30, −40, −60** — replacing the uniform
  −15 step. Sim on the live era's real parents/candles: ladder +115.0p popper P&L vs +21.2p
  current scheme (complex +46.3 vs −47.5); the dense top double-harvests shallow chop, the
  skipped −50 rung cost nothing. Warning label attached: denser ladders roughly double storm-grid
  bleed (−334 vs −153 on the rvol slide) — mitigated by the Activation Bar and per-cell popper
  switches. Level state, client extensions (`lvl` = offset pips), persistence, and recovery all
  migrated; pre-ladder state/comments auto-migrate (index × 15p).

## [6.2.0] — 2026-07-22

### Fixed
- **The shadow instrumentation stack was reading retired journals** (B-094): the Setup
  Scoreboard + five research tools polled the retired `mr-scrooge-v5` unit; the stamp feed,
  Shadowboard and t20 scorer defaulted to the retired dry-run unit. All consumers now read the
  live `mr-scrooge-v6` journal (env-overridable).
- **Scoreboards labeled/keyed rows by status-at-stamp-time** (B-095): promoted setups showed
  stale SHADOW rows with split stats. Rows now group by setup identity; status joins live from
  `config/cells` at render time.
- **Public trade log: directions were inverted and poppers unattributed** (B-091): one row per
  closed trade, direction from the trade's own units, new `source` column (parent/popper).
- **README live-config blurb hourly-reverted by the livelog template** (B-092).

### Changed
- **Storm response (first live kill-week, Jul 20–21):** GBP_USD/london `rvol_low_240`
  DISABLED and poppers switched off for GBP/london (its grid outlived its parent and kept
  re-arm-firing into the decline — 3 popper knives, the era's only realized losses).
  `classic_box_fade_long` GBP/london flipped long→short (MAE-flip doctrine). Promotions on
  current-era evidence: USD_JPY/london `timing_lean_30`, and `control_rvol_60_t20s` (GBP/ny) —
  **the t20 wider-engage gear trading live for the first time**. Book: 12 ACTIVE.
- Book of Bugs gains the V6.1-era section (B-091 → B-095) and two new recurring-pattern rows.

### Fixed
- **Poppers were invisible while being managed.** The first live popper engaged its ratchet
  (+8.5 -> lock +6, stepped to +10) but nothing on the dashboard showed it — poppers weren't in
  the positions table and the Party Package card had no manager state. Now: the card shows
  per-popper peak / engaged / locked-SL, and every popper is a first-class row in the positions
  table with full ratchet columns and a `POPPER` chip carrying its grid marker.

### Changed
- Dashboard "Open Positions" card renamed **"Open Trades"** — with popper grids live, multiple
  independent trades can share one pair; the table now lists trades, not net positions. (The
  broker layer always polled `/openTrades` and per-trade stop orders; verified live with a
  parent and popper both long AUD_USD under independent stops.)
- **Setup Scoreboard sim column was silently dead (B-class bug).** `research/tools/cell_setup_score.py` requested OANDA candles with `from` + `to` + `count` together, which the v20 API rejects (HTTP 400) — so the dashboard's "simulated EV vs expected" card showed stamp counts but never a simulated EV. Dropped `count`; the card now scores stamps again.
- **Credential resolver parity (broker ↔ feed).** The OANDA feed client now resolves credentials
  through the same `config.credentials.resolve_oanda_creds()` path as the broker
  (precedence: env vars → `~/.openclaw/secrets.env` → `config/credentials.local.json[mode]`).
  Previously the feed read `secrets.env` **only**, so a fresh clone that supplied keys via the
  dashboard CONNECTION tab / `credentials.local.json` ended up with a working broker but a **blank
  feed** (no price data). Found by an external reviewer. Added
  `tests/test_feed_broker_creds_parity.py` so the two resolvers can't silently drift again.

### Added
- **Continuous integration.** GitHub Actions runs the full test suite (`pytest`) on every push
  and pull request.

### Changed
- README shows a live CI status badge instead of a hardcoded test count (the count is now 102 and
  will keep moving; the badge stays current).

## [6.1.0] — 2026-07-19

### Added
- **Party Package (popper grids).** New additive management module
  (`modules/management/party_package.py`): every parent (cell) trade hangs a re-arming grid of
  levels every 15 pips on its adverse side. An armed level fires a **popper** — an independent
  same-direction trade with its own server-side SL (60p from its own fill) and its own ratchet
  (engage +8.5 → lock +6, trail 2.5). One popper per level at a time; a level re-arms after its
  popper closes and price re-crosses the level, so oscillating tape harvests repeatedly without
  stacking duplicates at the same mile marker. Fires are gated on the trading
  pause, the rollover freeze, spread fail-closed, and the book-wide trade/margin caps; poppers are
  stamped `engine=pp_v1` and carry `pp_v1` OANDA client extensions for exact broker-truth
  attribution and restart recovery. Kill switch: `config/pp_config.json {"enabled": false}`
  (hot-reloaded). Dashboard: new *Party Package* card (grid ladders, armed/spent levels, popper
  ledger greens vs knives). State persists to `data/pp_state.json`.
  Research context: `research/` 2026-07-19 scale-in ledger — on simulated costs the grid
  gross-harvests ~+100–150p/parent but pays more in toll; this deployment is the forward
  practice-tape test of that cost model.
- Tests for the grid mechanics (`tests/test_party_package.py`), including Brock's
  one-popper-per-mile-marker scenario as a regression test.
- **Per-cell popper opt-out + global switch.** Dashboard Party Package card gains a clickable
  ARMED/OFF global toggle and per-cell chips (one per ACTIVE setup); `POST /api/pp/toggle`
  merge-writes `config/pp_config.json` (`per_cell` map, most-specific key wins:
  `PAIR|session|setup` > `PAIR|session` > `PAIR`). Disabled cells never arm a grid; a grid whose
  cell is disabled mid-flight keeps managing open poppers but fires no new ones.
- **Research paper:** [docs/papers/PAPER_party_package_scale_in_2026-07-19.md](docs/papers/PAPER_party_package_scale_in_2026-07-19.md)
  — the full hypothesis → ten falsification rounds → first-passage-fairness finding → why the
  live deployment is the right next test anyway.

### Changed
- **Parent-book ratchet: engage +7.5 → +8.5 (lock +5 → +6), trail 2.5 unchanged.** Applied to
  all 29 ratchet setups in `config/cells/`, the recovery fallback (`exit_config.json`), and the
  calibration generator's final override block (so monthly refits preserve it). The t20s
  wider-engage shadow rows are untouched. Open positions keep the gear persisted at their entry.
- **Sizing:** `margin_pct_per_trade` 0.2 → **0.1**, `max_concurrent_trades` 4 → **8** (total
  exposure cap unchanged at ~80% of balance; poppers count toward the cap, and a pair with an
  active grid can't open a second parent).

## [6.0.0] — 2026-07-16
First public release. A strategy-free, cell-first OANDA forex trading bot (Python) with a live
control-panel dashboard, a full backtesting research program, formal falsification papers, and an
honest, auto-updated track record. See the
[release notes](https://github.com/BrockStar3540/mr-scrooge-v6/releases/tag/v6.0.0).
