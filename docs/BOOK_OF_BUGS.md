# Mr. Scrooge — The Book of Bugs

**Living institutional memory of every documented defect across the bot family.** Format per entry: era · area · symptom · root cause · fix · lesson. When something odd surfaces, this book answers *"have we seen this before?"* before anyone re-derives it.

**V1–V3 (B-001 → B-074):** the full forensic catalog (74 entries: pre-deployment audit, box-geometry defects, regime-supervisor contamination windows, Echo discriminator postmortem, TP2 clamp, alt-box double-truth, …) is archived at Dropbox `/SCROOGE ARCHIVE/V3/scrooge-bug-catalog-V1-V3-export-2026-07-05.md`. Entries below continue the numbering into the V4/V5 eras.

---

## V4 era

### B-075 — HTF features frozen AND mis-defined (fixed 2026-06-09)
- **Area:** feature pipeline (H20/H60 / htf_pct)
- **Symptom:** higher-timeframe alignment features never updated; values also semantically wrong (1H position-in-range [0..1] where a signed daily return was intended).
- **Fix:** alignment definition corrected + freeze repaired; 8yr re-validation of the align lever.
- **Lesson:** a feature can be wrong twice at once — check *definition* and *liveness* separately.

### B-076 — The exit bottleneck (found 2026-06-13; design defect, not a code bug)
- **Symptom:** harvest scale-out + net_ladder capped winners <20p while MFE showed 70% of winners ran 20p+, 57% ran 30p+ (max 907p).
- **Fix:** full-position ratchet cutover (bake-off +3.28p vs +0.75p harvest).
- **Lesson:** measure what the exit *left on the table*, not just what it banked. "The strategies aren't losers — the exit was."

### B-083 — Silently corrupt archive tarball (ops, 2026-06-18)
- **Symptom:** V4-cutover Dropbox tarball had the correct size but held 342 of 3,924 files.
- **Fix/doctrine:** verify (`gzip -t` + content hash + file count) BEFORE deleting any source. Size match ≠ verification.

### B-085 — Factor weights dead ("x") live for months (V3/V4)
- **Symptom:** offline factor analysis kept informing decisions while the live wiring had the factors disabled.
- **Lesson/doctrine:** verify LIVE wiring before trusting any offline analysis of "the bot's" behavior.

## V5 era

### B-077 — atr_conc scale bug: 14 cells structurally unable to fire (fixed 2026-07-03, `2c7367a`)
- **Symptom:** feature lived in (0,1); profile gates required ≥4.0 → those cells could never fire, since V3-era activation.
- **Lesson:** every gate needs a fire-rate audit; a gate that never passes is indistinguishable from a bug-free filter unless you count.

### B-078 — H1 look-ahead leak in 8yr research parquets (found+fixed 2026-07-03)
- **Symptom:** all H1-feature research numbers pre-fix were optimistic upper bounds (some findings inflated 8–15× via overlap on top).
- **Fix:** parquets rebuilt leak-clean; affected findings quarantined + re-based (see research/README truth hierarchy).
- **Lesson:** leak-test the corpus BEFORE the discovery program, not after; label every artifact with its corpus generation.

### B-084 — Journal-derived trade analysis missed 70 of 120 real trades (2026-06-21)
- **Symptom:** bot journal logs INTENT (SIGNAL/ENTERED); fills, manual closes, spreads, realized P/L exist only at the broker.
- **Fix/doctrine:** broker API is the sole trade-truth source; journal is for wiring audits only.

### B-079 — Engine multi-open handling (fixed 2026-07-01)
- **Symptom:** concurrent-position bookkeeping defects when multiple pairs opened in one cycle.
- **Fix:** engine open-loop rework in the 07-01 throughput session.

### B-080 — ev_seq None crash (caught pre-flight, Phase D cutover 2026-07-04)
- **Symptom:** cell setups without ev_seq evidence crashed intent formatting at the cutover boundary.
- **Lesson:** schema-optional fields need explicit None paths the day a new config generation ships.

### B-081 — CAL scorer defect (fixed 2026-07-04)
- **Symptom:** calibration truth-matrix scorer mis-read live expected-pips stamps in its first cycle.

### B-082 — Aggregator rules inverted by regime drift (retired 2026-07-03)
- **Symptom:** `atr_h1_relative`-keyed amplification rules validated on the 8yr corpus had INVERTED sign in 2026 (297k-bar confirm study).
- **Fix:** all aggregator rules emptied; per-cell evidence replaced global rules.
- **Lesson:** a rule validated on an 8-year average is a bet that the current year is average.

### B-086 — Rollover stop-slippage wash class (measured 2026-07-04, fixed 2026-07-05)
- **Symptom:** ratchet locks filling ~0 despite +5p locked: at 21:00 UTC half-spreads blow out 4–10×, stops trigger on the widened side and slip (worst live specimen: +5.0p lock → +0.3p fill; slippage p90 8.8p in that hour vs 0.0p median otherwise).
- **Fix:** global 20:55–22:05 UTC stop-freeze (no tightening, no bot-side closes) + FAST cells exit via server-side limit TP (cannot slip) + no FAST entries ≥20:00 UTC.
- **Lesson:** the fee isn't charged twice — the wash mechanism is *slippage at spread blowout*; guard the clock, not the lock size.

### B-087 — Dashboard set-serialization crash (V3-era `/api/data`; pattern recurred in V5 dashboards)
- **Lesson:** every state endpoint needs a defensive serializer; one non-JSON type must degrade to a stub row, never a 500.

### B-088 — V4 wrapper alias direction mismatches (found 2026-07-09, read-only archaeology)
- **Area:** V4 `plugins/strategies/` wrappers vs `_v3_triggers/textbook.py` `_RENAME_MAP`
- **Symptom:** three wrappers' docstrings claim the trade direction was flipped at the 2026-06-17 rename (williams_extreme_fade "goes LONG", vol_coil_fade_long "goes SHORT", zscore_extreme_fade_l 'hi'->SHORT) but the alias map resolves each to the ORIGINAL probe — documentation and execution disagree on SIGN.
- **Impact:** any V4-era analysis that trusted wrapper docstrings for direction has sign-scrambled conclusions for these three families.
- **Lesson:** at every rename/flip, the alias map IS the behavior; docstrings are wishes. Test what the code does (the retrial did).

---

*Numbering note: B-075…B-087 assigned 2026-07-05 while porting the catalog into the repo; the vault copy remains the V1–V3 source of record.*


---

## B-090 — ATR-scaled trail parked the ratchet stop below breakeven (green given up as red)

- **Date:** 2026-07-15 (Brock caught it: "how does a 40-SL bot lose $8?")
- **Area:** `modules/cells/cell.py:292` exit_params build + `modules/management/ratchet.py` `_compute_step_sl`
- **Symptom:** wide-stop (SL40-60) trades closing for tiny reds (−$0.85, −$7). The ratchet locked stops BELOW entry even on green peaks. Trace: trade 10428 peak=3.7p → sl=−1.5p.
- **Root cause:** the range-sized deploy (2026-07-14) set `trail_mult=1.0` on every cell. cell.py then OVERRIDES the fixed `trail_pips` with `clamp(trail_mult*atr_5m, trail_min, trail_max)`. With atr_5m≈5, effective trail=5 (not the 2.5 in config). `_compute_step_sl` returns `level − trail`; with trigger 3.5 and trail 5, locked stop = 3.5−5 = −1.5. So engaging at a low peak parked the stop below breakeven → any reversal exited red. Silently defeated the ratchet whenever atr_5m > trail_pips (i.e. almost always).
- **Impact:** every wide-stop trade in >2.5p-vol conditions gave up its green; the trigger/trail tuning (incl. the trigger-7.5 fix) was neutered because the trail wasn't fixed. Explains the single-digit W/L.
- **Fix:** `trail_mult 1.0 → 0.0` in the RANGE_SIZED generator block → fixed `trail_pips=2.5` used directly. Now engage +7.5 locks +5 (7.5−2.5) and trails 2.5; once engaged, cannot exit red barring slippage/gap.
- **Lesson:** a config `trail_pips` value is a LIE if `trail_mult>0` — the ATR scaler silently overrides it. When setting a fixed trail, set trail_mult=0. And Brock's heuristic holds: a wide-SL bot that loses small amounts is a trail/engage bug, not the stop.
