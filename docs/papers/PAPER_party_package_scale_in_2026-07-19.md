# The Party Package: Scale-In Grids, First-Passage Fairness, and a Live Forward Test

**Date:** 2026-07-19 (one research day, ten simulation rounds, then a live deployment)
**Status:** Sim-falsified on our cost model at every tested configuration → deployed to the
practice account anyway, deliberately, as V6.1's forward experiment — because the one thing the
sims cannot settle is whether the *cost model itself* matches real fills.
**Authoring convention:** Brock hypothesis + iterations; implementation/measurement by the
research harness. Same corpus discipline as [PAPER_h6_walkforward_2026-07-16.md](PAPER_h6_walkforward_2026-07-16.md)
(leak-clean truth matrices, H6 tiered slippage, per-pair spread, train ≤2022 / test ≥2023).

---

## 1. The hypothesis (Brock, 2026-07-19)

> Buy the parent trade. Every additional −10 to −15 pips of adverse movement, add an independent
> tranche ("popper") with its own wide SL and its own ratchet. Oscillating tape ("the waves")
> lets poppers repeatedly lock green while the parent rides its wide stop. Rare deep runs are
> survivable because our entries rarely swing 60 pips against us.

This is a **management** hypothesis, not a direction-prediction hypothesis — so it is not
covered by the six falsified families in
[PAPER_edge_hunt_falsifications_2026-07-14.md](PAPER_edge_hunt_falsifications_2026-07-14.md),
and it earned a full test program. Ten rounds followed, each round driven by a specific
objection Brock raised to the previous result. Every round used bar-by-bar replay on the
leak-clean M5 corpus (223,642 episodes across the 29-cell gear book, 2018–2026) with the exact
H6 cost model (per-pair spread + 0.4p entry slip + 0.8p stop-exit / 0.4p trail-exit slip).

## 2. What the ten rounds found

**Round 1 — one-shot poppers, 12h horizon (t7.5/lock5, adds every −10p).** Gross, the idea
works: +3.94p/signal vs +0.40 baseline no-slip. Net, it's a wash vs baseline (−0.71 vs −0.76)
with a 17× worse tail (p99 −308p, worst −1,094p). Avg 4.05 tranches ⇒ ~4× the toll, which
consumes almost exactly the extra gross.

**Round 2 — t12.5/lock10, 8-tranche cap, 10%-balance sizing, "quiet" momentum entries.**
All worse or equal. The 8-cap *hurts* (deep adds were the profitable ones). No 8-major
"rarely swings 60p/week" instrument exists (P(week≤60p) = 0.0–1.8% on every pair). Quiet-regime
momentum bursts are negative *even gross* (−3.8p/signal no-slip): on majors, a burst inside a
quiet regime fades. Account sim of the full spec: $10k → $9,182 on the test window.

**Round 3 — adverse-swing census from the real gear entries.** Brock half-right, and the
half matters: within the ~12h trade window, the best cells swing −60 only **3–7%** of the time
(AUD_JPY/ny regime_short 3.0%). But over a 1-week no-timeout horizon: 39–79%, median week-MAE
43–146p. The popper stack needs the long horizon; the long horizon dissolves the premise.

**Round 4 — order-aware race census (Brock's correction: MAE census can't order events).**
Correct, and it flips the read: **87.5–94.4% of entries touch +7.5 before ever touching −60**
(true kill rate 5.6–12.4%). The strategy's kills are rare — but the arithmetic
`E = P(engage)·avgGreen − P(kill)·63p` needs ~7.8p average green net at t7.5 and the book
delivers ~6–8p. Knife-edge, toll decides.

**Round 5 — lock sweep (Brock: "lock 20+, longer holds").** The deepest result of the day.
Week horizon, locks 10 → 47.5:

| trigger | avg green (net) | kill % | greens **needed**/kill | greens **supplied**/kill |
|---|---|---|---|---|
| 12.5 | +12.7 | 17.4% | 5.0 | 4.7 |
| 20 | +20.5 | 24.8% | 3.1 | 3.0 |
| 25 | +25.8 | 29.1% | 2.4 | 2.4 |
| 30 | +31.0 | 32.8% | 2.0 | 2.0 |
| 40 | +41.0 | 39.4% | 1.5 | 1.5 |
| 50 | +50.7 | 44.1% | 1.2 | 1.3 |

Supplied ≈ needed **at every rung, to the decimal**. Average green lands on the trigger +~0.5p
of runner juice; the kill rate rises in exact compensation. The majors are **first-passage
fair**: whatever race you set between "+X locked" and "−60 dead," the market prices the odds to
zero gross. Only the toll is asymmetric — and it's against you. (Test-window mean net peaks at
a noise-level +0.02p/trade at t30; train is negative everywhere.)

**Round 6 — per-cell, single tranche.** Real structure exists at cell level: a small family is
positive in *both* train and test at multiple lock rungs (EUR_JPY/asia box_pdl_short +3–5p at
locks 10–27.5; USD_JPY kc_breakout_long and london timing_lean_30 improve *with* lock height,
+2.5–3.6p at locks 22.5–37.5). Fade cells want low locks; trend cells want high locks.

**Round 7 — per-cell, poppers on.** Spectacular test numbers (+40–52p/signal on USD_JPY longs)
that are **directional regime in disguise**: long-side dip-stacking during the 2023–26
dollar/yen trend. Same cells' short side: −10 to −46. Train-only-selected popper book:
+9.6/+21.9p in 2023/24, **−9.0/−9.8 in 2025/26** — all profit in the first half, bleeding since.

**Round 8 — honest walk-forward, singles vs poppers (selection on train only).**
Singles book (14 cells, mostly lock 37.5, week horizon): test +0.70p/signal, pip-Sharpe 0.80,
worst −63p, 3 of 4 years green. Poppers book: +4.79p/signal but Sharpe 0.35, maxDD −52k pips,
worst signal −1,912p, and negative in 2025 *and* 2026. Poppers lose to plain high-lock singles
on every risk metric.

**Round 9 — re-arming grid (Brock's true spec: levels re-fire after re-cross), audited ledger.**
The waves are real: **44.6 green poppers per signal averaging +8.9p net** (step −15, test) =
+395p banked per signal. The knives are realer: 7.28 × −57.2 = −416p. Poppers face their own
first-passage race (6.1 greens supplied per knife vs 6.4 needed) — the fairness result is
**fractal**. On kill-weeks the claw-back thesis inverts: median kill-week depth is **−143p**
(p75 −225, max −1,338), so poppers *add* −178p on top of the parent's −63 (net −244/kill).
Spacing sweep: −10 → −39.8p/signal, −15 → −21.6, −20 → −14.4, −30 → −6.2 — monotonic toward
the no-popper limit; no interior optimum. Decomposed: the re-arming grid **gross-harvests
~+100–150p per signal and pays ~130–190p per signal in spread+slippage.** It is a fee machine —
the largest gross edge and the largest toll measured in this program, in the same trade.

**Round 10 — H6-grade portfolio validation of the round-8 singles lead** (1-per-pair dedup,
cap 3, 1% risk, compounding): **net Sharpe 0.34** (bar: 0.70) — WEAKENED. No-slip twin 1.02.
Clears the bar only if total slippage ≤ ~0.5p. Selection-free variant −0.18; jackknife 0.06–0.56.
The tenth measurement of the same wall.

## 3. The verdict, and why it shipped anyway

On the simulated cost model, **no configuration of the scale-in family is net-positive**, and
every improvement Brock proposed moved the number in the direction he predicted while leaving
the sign unchanged — because gross harvest and toll rise together. The doctrine holds:
*management redistributes geometry; the toll decides.*

But Brock's closing objection is legitimate and unfalsifiable offline:

> "This idea is so difficult to actually quantify that it requires real testing. I see so many
> mathematical variables that can't truly be accounted for."

He's pointing at the model's real seams: fill quality inside spreads, M5 bar-path ambiguity
(intrabar ordering of stop vs trigger), spread dynamics around the fires, the tick-level wave
structure that 5-minute bars cannot see. The sim's knife-edges are all within the width of
those seams (~0.4–0.5p). So V6.1 deploys the Party Package **live on the practice account** as
a pre-registered forward experiment:

- **Spec:** levels every −15p from parent entry; one popper per level at a time; level re-arms
  after its popper clears and price re-crosses it; each popper independent — 60p server-side SL
  from its own fill, ratchet **+8.5 → lock +6 → trail 2.5**; sizing 10% of balance per trade,
  8-trade cap (~80% exposure ceiling), parents + poppers both counted.
- **Attribution:** every popper carries `pp_v1` OANDA client extensions and `engine=pp_v1` log
  stamps, so broker-fill scoring can separate parent vs popper P&L exactly — no journal truth.
- **The falsifiable claim:** the sim says popper P&L net of real costs will be negative
  (≈ −15 to −40p per parent at this spacing). If the real tape's popper ledger disagrees at
  n ≥ 30 parents, the cost model — not the doctrine — is what's wrong, and everything above
  gets re-scored.
- **Controls:** per-cell popper opt-out switches + a global kill switch (dashboard / 
  `config/pp_config.json`, hot-reloaded), and the standing trading pause. The parent book is
  decision-identical to v6.0.

## 4. Artifacts

- Simulation scripts + full results ledger: Mini `~/scrooge-research-tools/2026-07-19-scale-in/`
  (`RESULTS.md`, per-round CSVs/parquets) — private archive, available on request.
- Live implementation: `modules/management/party_package.py`, `config/pp_config.json`,
  tests in `tests/test_party_package.py` (includes Brock's one-popper-per-marker scenario as a
  regression test).
- Related: [PAPER_h6_walkforward_2026-07-16.md](PAPER_h6_walkforward_2026-07-16.md) (the toll
  knife-edge), [PAPER_edge_hunt_falsifications_2026-07-14.md](PAPER_edge_hunt_falsifications_2026-07-14.md)
  (the six dead families), [../RESEARCH_PROGRAM.md](../RESEARCH_PROGRAM.md) (method).

*Written 2026-07-19, the day the ledger's first management-family hypothesis went from idea to
ten falsification rounds to a live forward experiment in one sitting.*
