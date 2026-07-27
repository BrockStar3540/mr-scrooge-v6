# Cost-Aware Exit Classes: Per-Cell Transaction-Cost Measurement and the Three-Speed Exit Book

**Mr. Scrooge V5 · research paper · 2026-07-05**
**Author: Brock (hypothesis, doctrine) + Claude Code (measurement, wiring)**
**Status: DEPLOYED LIVE 2026-07-05 06:30Z (Brock order, no shadow) · rollback tag `pre-exit-classes-2026-07-05`**

---

## Abstract

We measured the full round-trip transaction cost of the live OANDA book at the (pair × session) cell level from 963 broker fills, decomposed it into spread, slippage, and currency-conversion components, and tested whether per-cell excursion geometry justifies per-cell exit tailoring. Cost is pair-dominant (1.35–2.8 pips round trip; session shifts it ≤0.2p), the only fee beyond spread is a ~1% conversion markup on non-USD-quote P/L, and stop-fill slippage is ~0 in calm hours but 4–10× at the 21:00 UTC rollover — which, not spread double-charging, is the mechanism behind "locked +5, cashed a wash" trades. On the 2026 truth-matrix corpus, entry-time features robustly predict how FAR price travels (113 walk-forward-robust relationships; atr_5m ρ 0.4–0.7 everywhere) but never WHICH WAY (0/144) — a third independent confirmation of the when-not-which-way law. Cells split cleanly into three exit-geometry classes, and the split aligns with the NY-fade discovery: 7 of 8 quick-slice cells are NY session. We deployed a three-speed exit book: FAST server-side TP brackets at per-pair cost floors, MEDIUM spread-aware ATR-scaled ratchets, LONG late-engage wide-trail runners, plus a global rollover stop-freeze. Success criteria and falsification thresholds for week-one broker data are stated in §8.

---

## 1. Hypotheses (Brock, 2026-07-04/05)

**H1 — Cellular cost structure.** Entry/exit cost (spread + fees + margin interaction) differs materially per (pair × session) cell, and a higher-frequency bot must price it per cell: "we have to make sure we are netting profit after the cost of the trade."

**H2 — Excursion asymmetry carries information.** In lopsided MAE/MFE trades, indicator variations that scale MAE or MFE imply direction; in balanced trades, indicator variations should instead scale the distance, justifying earlier / current / wider ratchet locks.

**H3 — Cells need tailored ratchet speeds.** Some cells suit quick 15–30 minute slice-and-exit (~+5p, "cheese slicer"); others justify wider ratchets, higher locks, and >1h holds.

**H4 — The tight-slice wash zone.** OANDA builds its fee into the spread on both entry and exit, so a tight lock (e.g. +3) may be a de-facto wash after true costs; "+5 is about the lowest we can go" — but the true math had never been run.

## 2. Data and methods

| source | what it gave us |
|---|---|
| OANDA transaction export (practice-account-id-redacted) (2026-05-31→07-03, 4,546 rows, 963 fills) | per-fill ESTIMATED SPREAD COST, conversion rate/fee, financing, balance arithmetic |
| OANDA v3 API (account instruments endpoint) | true per-pair margin rates (2/3/5%) and financing rates — measured, not assumed |
| Truth-matrix corpus (8 pairs × 8yr, per-bar dual-direction fwd MFE/MAE 60m/240m, leak-clean, broker-anchored r=0.84–0.90) | fill probabilities, travel/asymmetry scaling, cell geometry classes |
| 230 broker trades since 06-13 (M1-path MAE/MFE + 6 cell features at entry) | live anchor for classes and durations |

Rigor rules applied: broker fills over journal (use-broker-not-logs doctrine); 2026 window with walk-forward split (train Jan–Apr, confirm May–Jul); 30-minute-thinned correlation guard against overlapping-bar inflation (the 8–15× artifact class caught on 07-04); scope claims to method.

## 3. Results I — the true cost of a trade (H1: partially confirmed, refined)

**Round-trip spread cost per cell (median, pips):** AUD/USD 1.35 · USD/JPY ≈ EUR/USD ≈ USD/CHF 1.6 · USD/CAD 1.8 · GBP/USD 1.95 · AUD/JPY 2.35 · EUR/JPY 2.7. **The pair is the cost cell** — within a pair, sessions differ by ≤0.2p. H1's "per cell" resolves to "per pair, with hour-level danger zones."

**Scale of the toll:** $18,630 paid in spread over 5 weeks vs −$22,473 net P/L — at mid prices the book was ≈ −$3.9k; **~83% of the window's loss was transaction cost.** The cost thesis is not a refinement; it was the majority of the P/L story.

**Fee decomposition (fill-verified, §6 of the cost report):**
- Commission: **zero** on all 963 fills.
- Conversion markup: non-USD-quote P/L converted ~**1% against the client both directions** (= the CONVERSION FEE column; −$402.74/5wk; ≈0.03p on a +3p slice — real, cumulative, never the wash-maker).
- Financing: net **+$33.86 over 63 days** — irrelevant intraday (charged only past 21:00 UTC).
- Stop-fill slippage (375 matched stop→fill pairs): **med 0.0p / p75 0.2p / p90 0.8p** normal hours; **med 0.8p / p90 8.8p inside 21:00 UTC**; p97 3.2p (news tails).

**Mechanics correction (H4's premise):** the spread is charged inside the two fill prices, once per side, never again as a deduction — proven by balance arithmetic on the user's own rows (GBP/USD 9810→9835 nets price-diff × units to the penny). A +L lock that fills realizes L − slip. The spread's true tax on a tight slicer is **rarity**: the mid must travel **L + full spread** for a +L exit to fill.

**The wash mechanism (H4: confirmed, relocated).** Ticket 9790: EUR/JPY lock trailed to +5.0p at 17:30 ET, filled 4.7p below the stop → +0.3p cash. The wash class is **stop slippage at spread-blowout moments** (rollover 21:00 UTC, news), not a per-exit fee. A bigger lock does not fix it (9790 WAS a +5 lock); structural guards do.

**Margin (H1's margin clause):** measured rates split the book — EUR/USD & USD/CAD 2%, AUD/USD & USD/CHF 3%, GBP/USD & all JPY 5%. Equal-margin sizing (20% of balance/trade) therefore buys a **4.1× spread in $/pip** (AUD/USD $16.1 vs EUR/JPY $3.9 per pip at current NAV): the book's $ P/L is silently dominated by the low-margin-rate pairs regardless of cell quality. Flagged as an open sizing decision (equal-$/pip normalization) — **not** changed in this deployment.

## 4. Results II — what the features can and cannot say (H2: half falsified, half confirmed)

Walk-forward on ~290k 2026 corpus bars, 24 cells × 6 features (atr_5m, kc_up_dist_pips, atr_conc, rvol_5bar, willr_m5, atr_h1_relative), overlap-thinned:

- **Signed direction from lopsidedness: 0/144 robust.** Nothing in the feature set predicts which way — third independent confirmation (after direction-horizon 07-04 and discovery-v2 structure).
- **One-sidedness magnitude (unsigned trendiness): 0 robust.** Even "will this hour be one-sided at all" is not feature-predictable.
- **Total travel on balanced bars: 113 robust relationships.** atr_5m is the master distance knob (ρ 0.4–0.7, every cell, train/test/thinned agreeing); atr_conc and rvol_5bar secondary; kc_up_dist_pips is mostly an ATR echo.

**Verdict on H2:** the "implies direction" half is falsified; the "scales distance → ratchet knob" half is emphatically confirmed. The market telegraphs WHEN and HOW FAR, never WHICH WAY.

## 5. Results III — the three-speed cell book (H3: confirmed)

Growth ratio (median 240m travel ÷ median 60m travel) splits the 24 cells at terciles 2.09/2.27:

- **QUICK-SLICE (8): seven are NY session** (+ EUR/JPY london). Moves arrive fast (best 60m fill odds in the book) and don't extend — the NY-fade discovery expressed as exit geometry. Broker anchor: GBP/USD ny winners resolved in median 26.5 minutes.
- **RUNNER (8): all asia/london** (USD/JPY london & asia, AUD/USD london, GBP/USD asia, …). 240m travel ≥2.28× the 60m; live winners held 2.5–3.5h.
- **STANDARD (8):** current geometry fits.

**Slice EV ledger (H4's true math):** per slice, EV = P(fill) × L_cash − (1−P) × E[loss | no fill]. At per-pair floors, P(fill within 60m) runs 49–60% at +3 and 35–47% at +5; the profitability ceiling on the failure branch is **~3.5–4.5p average loss** in nearly every cell — the strategy lives or dies on the failed-slice exit, not the slice size. +3 is arithmetically sound on cheap pairs (nets +2.9p typical, ≥+2.2p at p90 slip); JPY crosses shouldn't slice below +5. The +5 instinct survives as EV-preference (slippage-tail dilution + toll amortization), not as a fee-wash boundary.

## 6. Changes deployed (2026-07-05, live, no shadow — Brock order)

| class | cells | exit mechanism |
|---|---|---|
| **FAST** | 8 slice cells; setups w/ horizon ≤60m (5 setups) | server-side **limit TP on fill** (cannot slip) at per-pair cost floor: AUD/USD & EUR/USD +3, USD/JPY & USD/CAD & USD/CHF +3.5, GBP/USD +4, AUD/JPY & EUR/JPY +5; SL = TP+1; **60m timeout** flat; no trail; no entries ≥20:00 UTC; force-flat 20:45 |
| **MEDIUM** | standard cells + 240m setups in slice cells (4 setups) | ratchet; lock cannot engage below **spread + 2p**; trail = **0.6 × atr_5m** at entry, clamp [2.5, 6]p |
| **LONG** | runner cells (4 setups) | ratchet; engage at **+8p**; trail = **1.0 × atr_5m**, clamp [4, 10]p; no partials (bake-off precedent) |

**Global guards:** 20:55–22:05 UTC full stop-freeze (no tightening, no bot-initiated closes — server SL stays armed); FAST entry cutoff removes the rollover exposure class entirely.

**Engineering:** new `BracketManager`; `takeProfitOnFill` in the broker client; `ExitParams` extended (mode/tp/timeout/cutoff/trail_mult); engine selects manager by mode; ATR trail resolved at qualification time; 13 setups reclassed in `config/cells/`; **generator patched so monthly refits preserve classes**; dashboard shows class chips + management detail + freeze indicator. Smoke-tested (timeout / rollover_flat / freeze / engage / ATR-trail / import chain), restarted clean.

## 7. Limitations — stated before the market states them

1. **No fired-trade sim preceded deployment** (explicit owner decision). The 07-03 exit sweep showed tighter *global* geometry lost −36.9p on real entries; per-cell class geometry is different in kind but was validated on arithmetic + corpus, not replay. This is the biggest open risk.
2. Corpus fill probabilities are unconditional-bar rates, not entry-conditioned; live entries are cell-gated and may fill better or worse.
3. FAST SL depth (TP+1) and 60m timeout are arithmetic-derived starting values, not swept optima.
4. Practice-account pricing; live-account spreads must be re-measured after the money switch (same script, one command).
5. Cost/slippage sample = 5 weeks, one export; hour-21 pattern is 8/8-pair consistent but the p97 tail estimate is thin.

## 8. Predictions and falsification criteria (week one, broker fills only, engine=cell_v1)

| # | prediction | falsified if |
|---|---|---|
| P1 | FAST slice fill rate within 60m ≈ 45–65% at the per-pair floors | <35% over n≥20 slices |
| P2 | Average loss on timed-out/SL'd slices ≤ 4p | >5p over n≥20 failed slices |
| P3 | Zero rollover-window bot exits; no stop fills with >2p slippage 20:55–22:05 | any |
| P4 | FAST winners' median hold <45m; LONG winners' >90m | inverted ordering |
| P5 | LONG cells' realized-vs-MFE capture improves vs the 2.5p-trail era (MFE study baseline: 57% of trades ran 30p+ while exits caught <20) | capture ratio unchanged |
| P6 | Net expectancy per FAST slice > 0 after all costs | negative over n≥30 slices |

Per the evaluation doctrine: judge ONLY trades tagged engine=cell_v1 with the new exit blocks, per class, n≥20 before any verdict; no aggregate blending with prior eras.

## 9. Artifact index

- Cost matrix, slippage, conversion, mechanics addendum + reusable `analyze_transaction_costs.py`: archived at `/SCROOGE/SCROOGE ARCHIVE/session-notes/2026-07-05 Ratchet Exit Research/` (indexed in [`../research/README.md`](../research/README.md) §4)
- Feature-scaling CSV, cell classes, `fill_probabilities.csv`: same archive folder
- 230-trade MAE/MFE excursion table: same archive folder, built on the truth-matrix corpus `/SCROOGE/SCROOGE ARCHIVE/research-corpora/mini/v5-truth-matrix.tar.gz`
- Code: tag `pre-exit-classes-2026-07-05`
