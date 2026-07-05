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

---

*Numbering note: B-075…B-087 assigned 2026-07-05 while porting the catalog into the repo; the vault copy remains the V1–V3 source of record.*
