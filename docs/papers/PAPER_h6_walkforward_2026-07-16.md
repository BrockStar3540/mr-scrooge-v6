# H6, Tested: A Pre-Registered Walk-Forward Falsification of the Wide-Stop Thesis

**Mr. Scrooge · research paper · 2026-07-16**
**Author: Brock (the hypothesis, the range rule, the gear) + Claude Code (pre-registered design,
implementation, measurement)**
**Status: the monograph's closing chapter. H6 — the program's final surviving hypothesis — is
FALSIFIED as-tested. Live stops unchanged; nothing promoted to shadow. All numbers sim, on the
leak-clean corpus.**

---

## Abstract

The wide-stop thesis (H6) was the program's last open hypothesis: that tight stops had been converting
a thin-but-real edge into losses, and that wide session-sized stops with a prove-it ratchet let it
express. It survived the 2026-07-14 in-sample capstone (Sharpe ~1.0) with its inflators explicitly
named, and the decisive test was pre-committed: **walk-forward cell selection plus a slippage
haircut, pass bar Sharpe ≥ 0.70.** We ran that test with the design frozen before the run: selection
strictly on 2019–2022 (which kept only 3 of 29 candidate cells), testing strictly on 2023–2026, on an
engine first validated by exact (0%-deviation) reproduction of the original capstone, under a
pre-registered tiered slippage model (~0.8–1.2p round-trip). **Result: net test-window Sharpe 0.03
against the 0.70 bar — H6 is falsified as-tested.** The autopsy is precise: the *identical* frozen
book with slippage set to zero scores Sharpe **1.26** (+32%/yr), and a flat-slippage sweep locates the
knife-edge at **~0.4 pips round-trip** — half the defensible retail estimate. The gross edge is real;
it is simply the same size as the execution toll, the exact wall that killed the edge hunt's other
five families. Every robustness row (flat-SL, alternate trigger, an exploratory 18-cell loose
selection) fails the bar in the same direction, and the design's known impurities (candidate
thresholds dialed on full history) can only have *flattered* the result, making the falsification
conservative. The gross edge is also non-stationary — strong 2023–24, near-dead 2025–26 — a second,
independent decay signal. The practice-account forward tape continues as the live check of the same
question, with expectations reset accordingly.

---

## 1. Background

H6 emerged late on 2026-07-14 as the revision of five falsifications
([`PAPER_edge_hunt_falsifications_2026-07-14.md`](PAPER_edge_hunt_falsifications_2026-07-14.md)): a
head-to-head portfolio sim on identical cells showed tight stops ruining (Sharpe −3.54) what wide
stops earned (Sharpe 1.05), and exposed the winners'-MAE stop doctrine as survivorship-biased. The
in-sample result was deployed to the practice account as a forward experiment — but its own write-up
named the inflators (6 hand-picked cells, 2026 partially in-sample, zero slippage), guessed "realistic
Sharpe ~0.6–0.8 after honest selection + costs," and pre-committed the decisive test: **walk-forward
selection (train 2019–22 / test 2023–26) + slippage haircut; a cell earns a live shadow seat only if
Sharpe survives ~0.7.** This paper is that test, run two days later. Nothing in the design was chosen
after seeing a test-window number.

---

## 2. Pre-registered design (frozen before the run)

- **Windows.** TRAIN = 2019-01-01 → 2022-12-31. TEST = 2023-01-01 → end of data (2026-07-03). Nothing
  from the test window may influence any selection or parameter.
- **Candidate universe.** The same 29-cell setup universe the 07-14 sweep used (all statuses —
  active, shadow, disabled; a broad graveyard scan), *not* today's live book (which was picked using
  2026 data).
- **Selection, TRAIN only.** Per cell: (1) SL tier from the TRAIN-window session median range via
  Brock's range rule (<35p → SL40, <48p → SL50, else SL60), measured on 2019–22 bars only;
  (2) simulate the wide-stop ratchet (train tier, trigger 7.5 / trail 2.5 fixed) over TRAIN bars,
  net of spread + slippage; (3) keep iff train net expectancy > 0 **and** n ≥ 40. Freeze the book.
- **Costs.** The engine charges one full round-trip bid-ask spread per trade (buy-ask/sell-bid;
  verified in reproduction — charged once, not double-counted). On top, a deterministic slippage
  model, paid in selection *and* test: entry fill 0.4p every trade; exit fill tier-scaled on
  stop-outs (SL40 → 0.4p, SL50 → 0.6p, SL60 → 0.8p — the p90 stress case for loud-session stops),
  0.4p on horizon exits. Total ≈ 0.8p (calm) to 1.2p (loud stop-out) on top of ~1.0–1.7p spread.
- **Portfolio mechanics.** Identical to the 07-14 capstone: risk-normalized 1%/trade, concurrent
  cap 3, real compounding, on the frozen train-selected book.
- **Pass bar (stated first).** Net test Sharpe ≥ 0.70 → H6 confirmed research-grade; 0.30–0.70 →
  weakened; < 0.30 → **falsified**.
- **Robustness rows, same frozen book, no re-selection:** flat-SL40; trigger 3.5 (the pre-2026
  default, bounding the known trigger-gear impurity); no-slippage; per-year returns.

## 3. Engine validation

Before trusting any walk-forward number, the original 07-14 scripts were re-run *unmodified* on the
corpus and required to match the vault-recorded capstone within ±10%. They matched **exactly** (0%
deviation) on all four recorded runs — WIDE SL40 (+25.4%/yr, Sharpe 1.05, DD −39.9%, Calmar 0.64),
CURRENT-tight (−93%/yr, Sharpe −3.54), flat-40 (1.05/−40%), and range-sized (1.00/−31%). The
walk-forward numbers below are trustworthy with respect to the engine.

---

## 4. Results

### 4.1 Verdict

**H6 is FALSIFIED as-tested.** Test-window net Sharpe **0.03** (bar: 0.70). CAGR −2.1%, maxDD −50.9%,
Calmar −0.04, n = 7,582 trades (sim, leak-clean corpus).

The kill is **entirely the execution cost**: the identical frozen book with no slippage scores Sharpe
**1.26** (+32.1%/yr). The wide-stop edge exists gross and equals the toll — the same wall as the
edge hunt's other five families.

### 4.2 Train selection: the universe was already thin

Only **3 of 29** candidates passed train-only selection (net expectancy > 0, n ≥ 40):

| cell | side | SL tier (train) | n_train | train exp (net p) |
|---|---|---|---:|---:|
| AUD_JPY/ny · regime_short_240 | short | 50 | 1,298 | +0.321 |
| USD_JPY/london · timing_lean_30 | long | 40 | 2,055 | +0.278 |
| EUR_JPY/asia · box_pdl_short | short | 50 | 4,586 | +0.089 |

The other 26 had *negative* train net expectancy (−0.06 to −1.92p): under an honest, cost-bearing,
train-only view, most of the wide-stop universe is unprofitable before the test window is ever
touched. Note the asymmetry: the one thin-n cell (AUD_JPY, 181 test trades) is the only test-positive
cell (+3.50p mean); the two big-n cells that carry the book's trade count are net-negative on test
(−0.06p and −0.67p) *despite 84% win rates* — the ratchet gives back on winners and the wide −50
losers plus slippage overwhelm the many small greens. The rare-red/runner skew appears exactly as
H6 predicted, and still loses net.

### 4.3 Main run and robustness (frozen book, no re-selection)

| variant | n | CAGR | Sharpe | maxDD | per-year 23/24/25/26 |
|---|---:|---:|---:|---:|---|
| **MAIN** range-SL, trig 7.5, +slip | 7,582 | **−2.1%** | **0.03** | −50.9% | +18 / +20 / −33 / −6 |
| flat-SL40, trig 7.5, +slip | 7,700 | −0.7% | 0.11 | −56.1% | +26 / +37 / −39 / −10 |
| range-SL, trig 3.5, +slip | 8,431 | −10.6% | −0.54 | −52.6% | −2 / −11 / −37 / +4 |
| range-SL, trig 7.5, **no-slip** | 7,582 | +32.1% | **1.26** | −25.3% | +88 / +88 / +7 / +7 |

Every cost-bearing configuration fails the bar. The trigger-3.5 row (the pre-2026 default) is *worse*
than 7.5, so the known trigger impurity did not flatter the registered run. And even the frictionless
run is front-loaded: **+88%/+88% in 2023–24 collapsing to +7%/+7% in 2025–26** — the gross edge is
decaying independently of the cost story.

### 4.4 Selection-strictness probe (exploratory, non-registered)

To rule out "only 3 cells passed because slippage-in-selection was too strict," selection was loosened
to spread-only train expectancy (18/29 cells pass) and re-tested: **+slip Sharpe −1.25** (CAGR −36.5%),
no-slip **+1.41**. A bigger book makes the slippage kill *more* decisive. The falsification is robust
to selection strictness: 3 cells or 18, the book is strongly positive gross and flat-to-negative net.
The wall is cost, not selection.

### 4.5 The slippage knife-edge (the honest frame)

Flat per-trade round-trip slippage swept on the registered book, test window:

| slippage (p/trade) | Sharpe | CAGR | final equity |
|---:|---:|---:|---:|
| 0.0 | 1.26 | +32.1% | 4.10× |
| 0.2 | 0.98 | +23.2% | 2.88× |
| **0.4** | **0.70** | +15.0% | 2.03× ← exactly the pass bar |
| 0.6 | 0.41 | +7.3% | 1.43× |
| **0.8** | **0.12** | +0.1% | 1.00× ← net break-even |
| 1.0 | −0.16 | −6.6% | 0.71× |
| 1.2 | −0.45 | −12.9% | 0.50× |

The book clears the research bar **only if total round-trip slippage ≤ ~0.4p** (0.2p per fill). The
defensible central estimate for retail majors — from the program's own measured stop-fill
distribution (median ~0p calm, p90 0.8p; far worse at rollover/news) — is ~0.8–1.0p round-trip, where
the book is break-even to negative; the registered tiered model (~0.8p equivalent) lands at 0.03,
consistent with the sweep. **The gross per-trade edge (~0.3–0.8p on the high-n cells) is literally the
same magnitude as the execution toll.** This is the paper's core claim, stated as a sensitivity rather
than a point estimate: H6 is not "no edge" — it is "edge ≤ cost at any execution quality this venue
realistically offers."

## 5. Comparison with the 07-14 in-sample capstone

| | 07-14 capstone | this test |
|---|---|---|
| cell selection | 6 best, picked on full history | 3, train-2019-22 only |
| window | full 2019–2026 (test contaminated) | 2023–2026 only |
| slippage | none | pre-registered tiered |
| Sharpe | 1.00–1.05 | **0.03** (0.11 flat-40) |

The 07-14 note predicted "realistic Sharpe ~0.6–0.8 after honest selection + costs." The honest test
came in *below* the optimistic haircut because both corrections bit harder than guessed: walk-forward
selection shrank the book to 3 marginal cells, and slippage consumed the thin gross edge. The
in-sample Sharpe ~1.0 was selection bias + look-ahead + zero cost — not a durable edge.

## 6. Limitations

1. **Grey-box candidate universe (biggest, and it cuts one way).** The 29 candidates' entry-condition
   thresholds were dialed on full-history data in prior sessions; only the *selection* and *SL tiers*
   were train-only. This look-ahead can only **flatter** the result — pre-optimized candidates should
   over-perform — so it makes the falsification more robust, not less.
2. **Trigger gear (7.5) was chosen on 2026 data** — bounded by the trig-3.5 robustness row, which was
   worse (−0.54); the impurity does not rescue H6.
3. **The slippage model is an assumption, not per-fill measurement on this account.** Values come from
   the documented corpus stop-fill distribution plus a conservative nonzero entry charge; §4.5 exposes
   the full sensitivity. A live A/B of realized fills vs mid would tighten it; it cannot plausibly
   land below the 0.4p knife-edge for a wide-stop book whose losers are stop-market fills.
4. **Sim conventions** carried from the validated engine: spread charged once (verified, not
   double-counted); fills at bar close with stops checked on intra-bar H/L; horizon force-close at 12h
   (the live bot does not force-close; same convention as the reproduced capstone); all candidates run
   as wide-stop ratchet regardless of their live bracket mode (that *is* the hypothesis).
5. **Single 3.5-year test regime** (2023 → mid-2026, partial 2026) — and the per-year table shows the
   gross edge is non-stationary even within it.
6. **Corpus:** the 2026-07-03 post-leak-fix truth-matrix build; M5 features (clean anchors per the
   truth hierarchy).

## 7. Conclusion

The program's six-hypothesis ledger is now closed: H1–H5 falsified or revised, and H6 — the last one
standing — **falsified as-tested** by a pre-registered walk-forward with an honest cost model, on a
validated engine, with every robustness row agreeing and the design's impurities pointing the
forgiving way. The wide-stop insight was real as far as it went: tight stops *were* destroying the
gross edge (the head-to-head stands), and the gross edge *does* exist (Sharpe 1.26 frictionless). What
it is not is capturable — the toll at the door equals the take. This is the sixth structurally
distinct edge family to die at the same wall, and it completes the monograph's central finding: on
this venue, at retail execution quality, **no price-prediction edge the program could construct
clears its own transaction cost.** Do not promote to live shadow; live stops unchanged. The
practice-account forward tape continues as an independent live check of the same question — its value
now is measuring realized slippage and testing the sim's conventions, with expectations reset to the
knife-edge, not the jackpot. The remaining honest directions are the edge hunt's non-tuning forks:
execution/structure/cost edges (pay less rather than predict better), running trend tiny as a
diversifier, or concluding the venue has no automatable price edge and weighting effort elsewhere.

## Addendum (2026-07-16, same day): the stale-exit mechanism test — also falsified

A pre-registered follow-up tested the one mechanism hypothesis the main result left standing (Brock):
*trades that fire but never reach the +7.5p engage drift toward the wide stop; cutting them after T
hours should cut the red rate without gutting the greens.* Design frozen before the run: T swept
**on TRAIN only** (in {4, 8, 12, 24, 48, 96}h) on the registered 3-cell book, T\* frozen, tested once
on 2023-26 under the same cost model (stale exits pay the market-exit charge); material bar test
Sharpe >= 0.30, revive-H6 bar >= 0.70. Honesty gate first: the engine reproduced this paper's
registered baseline exactly (test net Sharpe 0.034; red rate 15.5%; avg green +8.09p / avg red
-45.46p) before the rule ran. One structural constraint surfaced, not hidden: the harness ride
horizon is 12h, so T >= 12h cannot fire -- bounded by the extended-horizon probe below.

**Verdict: FALSIFIED below the 0.30 material bar.** Every T that actually cuts trades *lowers*
Sharpe on train (T=4h: 0.165 -> -0.228; T=8h: -0.037), so the train argmax froze to **T\* = 12h -- a
structural no-op** (0% staled; test 0.034, identical to baseline). The test-window robustness rows
are monotone: the more the rule cuts, the worse (T=8h -> -0.025; T=4h -> **-0.210**). All sim, same
scope as the main result.

Two findings earn the addendum:

1. **The mechanism (diagnostic decomposition at the live-cut settings).** Pre-engage, "drifters" and
   "winners-in-waiting" are **the same population** -- reaching +7.5p *is* the winner definition, so
   time-to-engage carries no separating information, and any cut sacrifices future winners ~1:1
   against the drift it avoids. At T=4h: +7,809p of avoided drift vs **-9,119p of forgone late
   engagers -- all 354 of them baseline winners** (net -1,310p); at T=8h the pips roughly wash
   (+212p) but Sharpe still falls, because the rule shaves the right tail while the avoided reds
   were already capped by the stop. Each staled trade also books a certain ~ -19 to -22p exit loss.
2. **The factual premise is refuted.** An exploratory 5-day extended-horizon probe (H=1440 bars)
   shows the multi-day drifter population does not exist: **all 1,374 test-window reds are fast
   stop-outs (median hold 2.2h, p90 7.1h, zero horizon-drifters)** -- the wide stop is far in price
   but reached quickly when a trade is wrong (baseline trades overall: median 0.6h, p90 3.7h, max
   84.9h). The probe also confirms the 12h harness horizon is not an artifact of the main result:
   the mechanism fails at every T under the 5-day horizon too (argmax again a no-op).

Scope: the registered 3-cell wide-stop book, the leak-clean M5 truth corpus (the ride/stop/engage
logic is pure OHLC path, so the H1-leak note does not bind), 2023-26 test window, trig 7.5 / trail
2.5, range-tier SL, the same tiered-slippage portfolio mechanics; T\* train-selected only, no cell
re-selection. Artifacts (pre-registered design, sweep tables, decomposition, extended-horizon probe):
`/SCROOGE ARCHIVE/session-notes/2026-07-16_stale_exit/`.

The addendum strengthens the paper's conclusion from a second angle: not only does the wide-stop
book fail net of cost -- its loss profile has no exploitable time structure left to rescue it. The
reds are fast, the greens define themselves only by engaging, and the insurance-book shape (many
small greens, rare capped reds) is already the optimum of its own mechanism family.

## 8. Data availability

- Full pre-registered results file, frozen design, selection table (all 29 candidate verdicts), main
  and robustness runs, per-cell test contributions, slippage sweep, and daily test-window equity
  curve: `/SCROOGE ARCHIVE/session-notes/2026-07-16_h6_walkforward/` (`wf.py`, `probe.py`,
  `gear_fresh.json` candidate universe, `selected_book.json`, `wf_results.csv`, `per_cell_test.csv`,
  `per_year_main.csv`, `slip_sweep_main.csv`, `equity_test_main.csv`).
- Engine (reused unmodified for the reproduction gate): the 07-14 edge-hunt tools
  (`portfolio_sim.py`, `range_sized_sl.py`), archived with the edge-hunt session
  (`/SCROOGE ARCHIVE/session-notes/2026-07-14 Edge Hunt/`).
- Corpus: the leak-clean truth-matrix build (catalog: [`../DATA_AND_MODELS.md`](../DATA_AND_MODELS.md),
  `v5-truth-matrix.tar.gz` — CLEAN).
- Antecedents: [`PAPER_edge_hunt_falsifications_2026-07-14.md`](PAPER_edge_hunt_falsifications_2026-07-14.md)
  (the in-sample capstone + the owed-test pre-commitment);
  [`../RESEARCH_PROGRAM.md`](../RESEARCH_PROGRAM.md) (H6 ledger entry).
