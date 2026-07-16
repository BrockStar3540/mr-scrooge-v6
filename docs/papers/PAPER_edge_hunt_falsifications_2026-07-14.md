# The Edge Hunt: Five Falsifications, a Survivorship-Bias Discovery, and the Wide-Stop Turn

**Mr. Scrooge · research paper · 2026-07-14**
**Author: Brock (research direction, every hypothesis) + Claude Code (implementation, measurement)**
**Status: flagship result of the program. Live stops were changed only by the range-sized deploy
(a forward experiment), never on the sim alone. The decisive test remains owed (§7).**

---

## Abstract

After five months and six versions, we asked the program's founding question directly: **is there an
automatable price edge a retail trader can reach, net of cost, at all?** We tested five structurally
distinct price-edge families on leak-safe 8-year and 16-year corpora (eight OANDA majors, plus a
47-instrument CTA universe), each with a walk-forward or year-by-year discipline. **All five were
falsified, and all five died at the same wall: retail OANDA-majors spread exceeds any
price-predictable edge in the data.** The falsifications are M5 scalping (edge = cost), single-pair
daily trend (coin flip), diversified retail time-series momentum (gross Sharpe 0.08, net −0.22),
symmetric dual-ratchet straddle (you always own the loser), and tight-stop-and-reverse on "lopsided"
cells (the lopsidedness is realized direction, not a selectable property). Then a late-session turn:
widening stops — never tried above 20 pips in the program's history — flipped a 29-cell scan's
positive count from 4 to 17, and a head-to-head portfolio sim on an identical six-cell shortlist
showed tight stops driving the account to zero (Sharpe −3.54) while wide stops profited (Sharpe
1.05). The turn exposed a **survivorship bias in the program's own stop-tuning doctrine** — the
winners'-MAE-p75 rule measured adverse excursion only on trades that survived to win. The net
revision: there *is* a runnable-looking edge, but it is thin, low-Sharpe, gated on wide stops, and
shaped by exit geometry rather than direction. All numbers here are **sim** unless tagged broker; the
wide-stop thesis is an **open forward experiment**, not a claimed return.

---

## 1. Background

By July 2026 the bot had held and shed a sequence of direction theses (indicator signatures, strategy
portfolios, ML-authored strategies, per-cell timing — see
[`../RESEARCH_PROGRAM.md`](../RESEARCH_PROGRAM.md) §2). The account had drawn down ~84% across the
strategy eras on paper money, and each "edge" had dissolved as the measurement got honest (broker
truth, forward pip, walk-forward, the H1-leak repair). The operator's question was no longer "which
strategy," but whether the whole premise held. This session tested that premise to destruction on
corpora explicitly rebuilt to be leak-safe (post-B-078), extending to 16 years where the data allowed.

Two prior program findings frame it: the market **telegraphs WHEN and HOW FAR but not WHICH WAY** (the
0/144 signed-direction result), and **~83% of a five-week losing window was transaction cost** (963
broker fills). The edge hunt is what happens when those two facts are taken seriously enough to test
every remaining family against them.

---

## 2. Method

All heavy compute ran on lab hardware (never the live-trader host). Corpora: eight OANDA majors, M5/H1/D
candles, extended to 2010–2026 (16yr) where available; forward targets rebuilt leak-safe. The CTA test
used a 47-instrument universe (FX + metals + index + energy + ags + rates), 2010–2026, daily.

Each family was given a discipline appropriate to its claim:
- **Scalping / cost:** broker transaction CSV for the toll; a time-frame sweep (`tf_sweep`) for the
  cost-as-fraction-of-move at 1h/1d/4d holds.
- **Single-pair trend:** trend-aligned forward return vs 1d SMA at horizons 1h→4d; 32 regime gates
  (ADX/chop/Hurst/VHF × terciles × horizons), scored for year-consistency (`tf_regime`).
- **Diversified TSM:** canonical vol-targeted ensemble sign of [21,63,126,252]-day returns, hold-until-flip;
  full backtest + single-instrument diagnostic to validate the engine (`cta_backtest`, `cta_diag`).
- **Straddle:** enter long+short with live ratchet gear (SL12/trig6/trail2.5), 8 pairs, 16yr M5, hourly
  cadence; selector adjudication by trend-efficiency quintile.
- **Tight-stop-and-reverse (SAR):** enter the favorable side (tight stop S=5) chosen OOS on 2019–22,
  reverse into the breakout on stop, ratchet the reverse; test 2023–26; 24 cells, generic and at
  PDH/PDL structural levels.
- **Wide-stop turn:** an SL sweep 5→60; a 29-cell scan at fixed SL40 with added `ps_` features; a
  risk-normalized 6-cell portfolio sim (1%/trade, cap 3, compounding), **head-to-head** current-SL vs
  SL40 on the identical shortlist.

Rigor rules (program standing law): walk-forward or year-by-year truth; trimmed means (the uncapped
ratchet inflates tails); broker fills override sim; scope every claim to method + window.

---

## 3. Results — the five falsifications

**Finding 1 — M5 scalping cannot clear its own cost (structural).** Broker CSV: ~$2,046 spread over
~131 round trips ≈ 1.0–1.5 pips paid every trade. Best dialed setups make +0.8–1.3 pips/trade — **the
edge is the same size as the toll.** Cost is ~19% of the average move at a 1h hold, dropping to 3.6% at
1d and 1.8% at 4d. *The cost thesis is real: spread stops mattering only at the daily horizon.*

**Finding 2 — Single-pair daily trend is a coin flip.** 7.5yr, 8 majors: trend-aligned forward return
has ~0 gross edge at **every** horizon 1h→4d; hit rate pinned 49–50%. Of 32 regime gates, **none** was
net-positive with year-consistency; the trend-persistence regime (ADX-hi & Hurst-hi) was the *worst*
(0/6 years). Simple-filter single-pair direction prediction is not an edge.

**Finding 3 — Diversified retail TSM is ~break-even (the honest one).** 47 instruments, 2010–2026,
vol-targeted ensemble: **gross Sharpe 0.08, net Sharpe −0.22.** The engine is *validated, not buggy* —
single-instrument 2022 captures are correct (USD_JPY +13.6%, US10Y +8.0%, WTI +3.9%, rates sector
+7.4%) and the sector hierarchy is textbook (metals/energy best +0.20/+0.12, FX worst −0.26; ex-FX book
Sharpe 0.03). The ~0 is **venue + era**, scoped honestly (not "trend is fake"):
1. *Era:* published TSM Sharpe ~1 used the 1985–2009 golden age; 2011–2019 was a documented trend
   drought. Our 2010–2026 sample is mostly the hard era.
2. *Breadth:* pro CTAs trade 100–300+ futures across many sectors; OANDA gives ~47 mostly-correlated
   instruments (23/47 are dollar-driven FX crosses). Diversification Sharpe needs breadth we lack.
3. *Cost:* retail CFD spreads + daily-rebalance turnover turn gross ~0 into net negative.

**Finding 4 — Symmetric dual-ratchet straddle: you always own the loser.** Long+short with ratchet gear,
8 pairs, 16yr: net −0.9 to −2.6p per straddle, %positive 35–38%, **0/8 years positive on every pair.**
Sorting by trend-efficiency, the trendy quintile was *worst* (−1.59) — neither direction-WR nor
trendiness rescues it. Mechanism: a coin-flip pair *guarantees* you hold the −12 loser every entry; to
break even the winner must ratchet-capture > stop + 2× spread ≈ 14.5p every time, and the trail gives
it back. The 50/50 property that motivated the idea is exactly what dooms it — a long-straddle premium
that realized FX vol does not cover.

**Finding 5 — Tight-stop-and-reverse on "lopsided" cells: the lopsidedness isn't real.** Enter the
OOS-favorable side (tight stop S=5), reverse on stop, ratchet the reverse: **0/24 cells net-positive**,
−1.56p generic, −1.74p at PDH/PDL (worse — intraday FX mean-reverts there, no stop cascade). Win rate
52–57% but still negative (small wins can't cover double-spread + whipsaw tail). **Killer tell:**
`asym_train = 0.0` in *every* cell — cell-level forward excursion is **not** lopsided; the per-trade
MFE≫MAE we had been dialing on is *realized direction*, not a selectable cell property. Deep
implication: the dial-in method (quintile MAE/MFE separators) had largely been fitting realized-direction
noise in-sample — which explains the program's constant re-dialing and book-flips.

**Meta-synthesis.** Five structurally distinct families — scalp (edge = cost), single-pair trend (coin
flip), diversified TSM (needs breadth we lack), symmetric straddle (guaranteed loser stop), adaptive
SAR (asymmetry is realized direction) — **all die at one wall: retail OANDA-majors spread > any
price-predictable edge in the data.** This is method-scoped and robust across 16yr OOS: *not* "no edge
anywhere," but "no price-prediction edge clears retail cost for us."

---

## 4. Results — the turn

Reload-on-red-stop (re-enter the *same* direction, not reverse) flipped positive: USD/JPY +0.35p across
6 of 7 cells OOS. That pointed at the stop, not the entry. An **SL wide sweep** (never tried > 20p in
the program's history) showed expectancy rising ~monotonically to SL40–60, with USD/JPY cells crossing
neg→pos OOS. An **expanded 29-cell scan** at fixed SL40 (with `ps_` features added) improved 28/29 cells,
moved the positive count **4 → 17** (mean lift +0.67p, robust OOS), and resurrected ~10 shadow cells + 3
mis-tightened active cells (e.g. EUR_JPY/ny timing_lean_30, −0.52 → +0.93).

**The methodological bombshell.** The program's stop-tuning doctrine — tighten SL to the winners'
**MAE p75** — was **survivorship-biased**: MAE was measured only on trades that *survived to win*, blind
to the trades a tight stop would have killed that would have recovered. The morning's SL 12→7 and 20→5
tightenings were **backwards** for these cells. This is survivorship bias inside the *method*, not the
data, and it retroactively explains months of re-dialing.

**Capstone — head-to-head portfolio sim.** A 6-cell shortlist (positive at SL40, contained drawdown),
risk-normalized 1%/trade, cap 3, compounding, **identical cells in both runs**:

| Stop regime | Ann. return | Sharpe | maxDD | Calmar | positive years |
|---|---:|---:|---:|---:|---:|
| CURRENT (tight) | **−93%/yr** | **−3.54** | → zero | — | 0/8 (account → 0 every year) |
| WIDE (SL40) | **+25.4%/yr** | **1.05** | −40% | 0.64 | 8/8 (2022 +70; OOS 2019–25 all green) |
| RANGE-SIZED (40/50/60) | +… | **1.00** | **−31%** | — | rarest reds 14%, most big runners |

**What is trusted vs not.** The **head-to-head direction** — same cells, tight ruins / wide profits — is
selection-*un*biased and is the load-bearing result. The **absolute level is not**: inflators are named
— cell selection (6 best), 2026 partially in-sample (+119% that year), no slippage/financing/bid-ask
(wide stops slip), and a −40% DD that is brutal (Calmar 0.64 only mediocre). Honest estimate after
selection + costs: **Sharpe ~0.6–0.8** — a low-Sharpe grind, not a jackpot. A "recovery-rate classifier"
tried as a per-trade WIDEN gate was a **red herring** (corr +0.08 with profit; 12/29 false WIDENs).

The range-sized variant (SL sized to per-(pair × session) session swing: 40 quiet / 50 mid / 60 loud,
brackets→ratchet so runners express) gave the rarest reds and best drawdown containment, confirming
Brock's rare-red / runner-carried skew *in sim*, and was deployed to all 29 cells as the forward
experiment.

---

## 5. Results — the exit stack that shipped (broker-observed follow-ups)

Post-deploy operational findings (2026-07-15, broker + engine logs), included because they are the honest
texture of running the thesis live:
- **Trigger raise 3.5 → 7.5** book-wide: skips +3.5 scratch-engages; sim Sharpe 0.70 vs 0.60, avg green
  8.0 vs 5.9p. trig10 was worse; loosening the trail blows up to Sharpe 0.04.
- **B-090 (trail_mult bug):** the range-sized deploy left `trail_mult=1.0`, ATR-scaling the trail to ~5p
  and parking the ratchet stop *below breakeven* — green given up as red whenever atr_5m > trail_pips.
  Caught by Brock ("how does a 40-SL bot lose $8?"), fixed to fixed trail 2.5.
- **Break-even lock rejected on the spread floor:** locking a stop within a spread of entry realizes a
  spread-sized *loss*, not a scratch (BE→lock 0.5: Sharpe collapses to 0.12, loss rate 41%). Doctrine:
  never lock a stop within a spread of entry; the +7.5 trigger → +5 lock already guarantees a green
  net of spread once engaged.
- **Quiet-bot diagnosis:** not broken — wide stops hold longer and churn less *by design*; asia session
  has few active cells and dead overnight ATR gates cells out correctly.

---

## 6. Limitations

1. **Sim, not live.** Every Sharpe/return here is simulated. The forward practice-account tape is the
   only verdict, and it is not in yet.
2. **Selection + in-sample.** The capstone picked 6 best cells and 2026 is partially inside the tuning
   window; the absolute level is inflated (Sharpe ~0.6–0.8 after honest haircut).
3. **No slippage/financing modeled** in the portfolio sim; wide stops slip more when hit, and the
   rollover window blows spreads 4–10× (B-086).
4. **Path is rough.** Per-trade Sharpe on the raw cells is 0.01–0.05, R 0.001–0.02, maxDD −700…−3600p
   (median −2571 = 2–5yr of the cell's own profit); trades overlap heavily, so per-trade stats can't be
   naively annualized. The edge is thin and the ride is rough.
5. **Practice-account pricing;** live spreads must be re-measured after any switch to real capital.

---

## 7. The owed test (falsification criteria)

The wide-stop thesis is **OPEN**. It is promoted to a live *shadow* seat only if the decisive test
passes:
- **Walk-forward cell selection:** train 2019–22 / test 2023–26 (so the shortlist is not hand-picked on
  the same data it is scored on), **plus a slippage haircut.** If Sharpe survives ~0.7 there, a cell
  earns a shadow seat.
- **Falsified if:** the walk-forward + haircut fails ~0.7; or the forward tape at n ≥ 20 per cell shows
  avg-red not contained toward the wide stop, wide-stop slippage eating the runners the thesis depends
  on, or the many-small-greens / rare-big-green skew failing to appear.

**Net revision of the program:** the five falsifications are *revised, not reversed* — there is a
runnable-looking edge, but it is gated on wide stops and exit geometry, the tight-stop dial-in doctrine
was actively harmful and survivorship-biased, and the honest verdict is pending the walk-forward gauntlet.

---

## 8. Data availability

- Scripts (lab hardware): `tf_sweep.py`, `tf_regime.py`, `cta_backtest.py`, `cta_diag.py`, the SL sweep
  and 29-cell scan, and the 6-cell portfolio sim; equity curve `cta_equity.csv`.
- Corpora: leak-safe 8yr/16yr M5/H1/D feature sets and the broker-anchored truth matrix, archived at
  `/SCROOGE ARCHIVE/research-corpora/` (indexed in [`../../research/README.md`](../../research/README.md) §4).
- Session diaries: `/SCROOGE ARCHIVE/session-notes/2026-07-14 Edge Hunt/` and
  `.../2026-07-14 Deep-Dive Dial-In/`.
- Related defects: B-086 (rollover spread blowout), B-090 (trail_mult). See
  [`../BOOK_OF_BUGS.md`](../BOOK_OF_BUGS.md).
