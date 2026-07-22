# Changelog

Notable changes to Mr. Scrooge. Format loosely follows [Keep a Changelog](https://keepachangelog.com/).
The full narrative history lives in [docs/SCROOGE_HISTORY.md](docs/SCROOGE_HISTORY.md) and the
[Book of Bugs](docs/BOOK_OF_BUGS.md); this file tracks the public-repo era.

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
