# V6 Audit Ledger — ported-from-V5 cleanup items

Created at the 2026-07-05 port. Rule: anything that could change live behavior is **sim-gated** — removed only after a fired-trade replay shows parity (or improvement), per the exit-sweep lesson (B-076 doctrine: measure, don't assume).

## Done at port (2026-07-05)
- [x] Fresh git history; no private-era commits carried.
- [x] `modules/archive/signals_legacy/` left behind (V5 repo + graveyard keep it).
- [x] `research/sessions/` left behind (V5 repo + `/SCROOGE ARCHIVE/session-notes/`); `research/` here keeps the index + live tools only.
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
- [ ] `tests/` is empty — port needs a real test suite (manager unit tests exist as smoke scripts in session history; formalize).
- [ ] Recovery-adopted trades always get RatchetManager (bracket trades recovered after restart lose their timeout; server TP/SL still protect them). Fix: persist exit class in trade clientExtensions.
- [ ] Sizing: equal-margin vs equal-$/pip decision (4.1× asymmetry documented in the cost study) — Brock decision pending.
- [ ] License + contribution policy before public flip.
