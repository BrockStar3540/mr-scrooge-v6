# Changelog

Notable changes to Mr. Scrooge. Format loosely follows [Keep a Changelog](https://keepachangelog.com/).
The full narrative history lives in [docs/SCROOGE_HISTORY.md](docs/SCROOGE_HISTORY.md) and the
[Book of Bugs](docs/BOOK_OF_BUGS.md); this file tracks the public-repo era.

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
