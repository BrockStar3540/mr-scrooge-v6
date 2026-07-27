# V6 Audit Ledger — ported-from-V5 cleanup items

Created at the 2026-07-05 port. Rule: anything that could change live behavior is **sim-gated** — removed only after a fired-trade replay shows parity (or improvement), per the exit-sweep lesson (B-076 doctrine: measure, don't assume).

## Done at port (2026-07-05)
- [x] Fresh git history; no private-era commits carried.
- [x] `modules/archive/signals_legacy/` left behind (V5 repo + graveyard keep it).
- [x] `research/sessions/` left behind (V5 repo + `/SCROOGE/SCROOGE ARCHIVE/session-notes/`); `research/` here keeps the index + live tools only.
- [x] lock_guard fingerprint check: graceful skip when legacy profile modules absent (was CRITICAL log spam every boot — locks retired at cell-era cutover).
- [x] `.env.example` + `.gitignore`; credentials environment-only.
- [x] v6 service unit; v5 unit not ported.

## Sim-gated removals (do with fired-trade parity replay)
- [x] **TP1/TP2 partial-close ladder** — REMOVED 2026-07-05 (ratchet.py, engine recovery kwargs, TUNE schema, exit_config keys). Gate: shadow-week parity (running).
- [ ] **dir_certainty / mom_certainty / vol_regime fields** on `TradeTicket` (legacy-V5 concepts; cell era stubs them). Prune fields + dashboard columns together.
- [ ] **lock_guard** beyond the session-instance throttle: locked_cells.json machinery is retired-era; decide keep-as-throttle-only vs full retirement once direction-persistence rules complete their n≥20 clocks.
- [ ] **exit_config.json per-pair schema**: superseded by per-setup `exit` blocks; keep as fallback for recovery-adopted trades or collapse.
- [ ] `playmaker.py` legacy ticket paths not exercised by cell intents.

## Open engineering debt
- [ ] **Generator-override sync discipline**: every V5 dial-in that touches research/tools/generate_cell_configs.py overrides or config/cells/*.json MUST be synced to V6 in the same session (2026-07-13 lesson: 07-08 dial-in never ported -> shadow traded retired sides for 3 days, gauntlet window invalidated). Candidate automation: nightly diff alert V5 vs V6 generator+configs.
- [x] Backport SHADOWBOARD from V5 (ops/shadowboard.py + route + SHADOW-tab section); parameterize the journal unit name (V5 hardcodes mr-scrooge-v5) and keep scoring in the background thread (single-threaded-server lesson, 2026-07-09). DONE 2026-07-15: `ops/shadowboard.py` ported. Route (`/api/shadowboard`) and SHADOW-tab UI already present in server.py/panel.html from the cell-era sync. (a) journal unit parameterized via `SCROOGE_JOURNAL_UNIT` env var, default `mr-scrooge-v6-dryrun` (→ `mr-scrooge-v6` once live). (b) scoring stays in the `shadowboard-refresh` daemon thread; `get_board()` only returns the cache + kicks the thread, never scores inline.
- [x] `tests/` is empty — port needs a real test suite (manager unit tests exist as smoke scripts in session history; formalize). DONE 2026-07-15: pytest suite added (31 tests, `mr_burns_env/bin/python3 -m pytest tests/`): `test_ratchet.py` (engage/trail/lock + B-090 fixed-trail / engaged-stop-above-breakeven regression), `test_cell_configs.py` (schema + range validation over every config/cells/*.json, incl. trail<trigger invariant), `test_exit_config.py` (deployed defaults engage 7.5 / trail 2.5 + structural sanity). Note: the ATR-scaled-trail path (trail_mult>0) lives in modules/cells/cell.py evaluate() and is covered indirectly (all cells ship trail_mult=0 + the ratchet fixed-trail invariant); driving cell.py's inline scaling directly would need a full CellModule/view fixture — deferred, not refactored.
- [ ] Recovery-adopted trades always get RatchetManager (bracket trades recovered after restart lose their timeout; server TP/SL still protect them). Fix: persist exit class in trade clientExtensions.
- [ ] Sizing: equal-margin vs equal-$/pip decision (4.1× asymmetry documented in the cost study) — Brock decision pending.
- [ ] License + contribution policy before public flip.
