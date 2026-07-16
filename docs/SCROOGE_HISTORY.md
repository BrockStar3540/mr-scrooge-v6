# Mr. Scrooge — Version History (V1 → V6)

**The log.** One entry per era: the thesis it bet on, the method it used, the numbers it
actually measured, what falsified or superseded it, and what carried forward. The git repo
stays clean and current; the **Dropbox `/SCROOGE ARCHIVE/` is the graveyard** — every retired
version, corpus and session diary is filed there by era and referenced from this log, never
copied back in. Full forensic bug history: [BOOK_OF_BUGS.md](BOOK_OF_BUGS.md).

Every performance number below is scoped to how it was measured — **sim**, **live** (bot
journal / intent), or **broker** (OANDA fills, the only trade-truth source). Those scopes are
not interchangeable and were never upgraded when copied here.

> **The current bot (V5, cell era) uses NO strategy in the classical sense.** There are no
> entry "strategies" — the (pair × session) **cell** is the unit; a cell trades only when a
> validated setup (raw-indicator ranges with full research lineage) qualifies, is sized by
> portfolio caps, and is exited by a cost-aware ratchet class. No validated setup = no trade.
> See [`PAPER_cost_aware_exit_classes_2026-07-05.md`](PAPER_cost_aware_exit_classes_2026-07-05.md)
> and [`../research/README.md`](../research/README.md) for the evidence chain.

---

## The tape — one practice account, five eras

Everything below was paid for on a single **OANDA practice account** (paper money, not real
capital — "the live trader" means the running bot, not a funded account). The account opened
at **$100,000 on 2026-03-22** (V1) and bottomed at **$15,598 on 2026-06-10** — an **−84%
drawdown** across the V1→V4 strategy eras and early V5. Every falsified strategy, every exit
that strangled a winner, every bug in the Book of Bugs was charged against that balance. It is
the strongest single argument in this project: five versions of increasingly careful research
could not out-predict the market, and the account kept the receipts. V5's measurement overhaul
(broker-fill truth + cell-era falsification discipline) is what stopped the bleeding; whether
the wide-stop book can climb is the open forward experiment. (The live NAV line lives in the
repo README and is auto-updated on every push.)

---

## V1 — "The Box Bot" (≈ Feb–Mar 2026)

- **Origin (primary sources, recovered 2026-07).** V1's *first* identity, before the box playbook,
  was a micro-breakout **"Sniper Bot"** scoped in the OANDA-agent genesis conversation (*Dropbox
  `/LLM Sessions/…/Trading/2026-02-14 Building a forex trading agent with OANDA API`*): 1–2 pairs
  (EUR/USD + GBP/USD), high-liquidity windows only, one position at a time, tight stop + time-based
  exit — on a **Node/TypeScript + Supabase** engine with a Lovable dashboard, later re-homed to the
  Python line. That conversation already fixed three ideas the whole program kept: the **risk dial**
  (a single 0.1–1.0 aggression slider), the **fee-aware minimum-move gate** (`MinMove = SpreadCost +
  Commission + SlippageBuffer`, skip anything that can't clear it), and a full set of **circuit
  breakers** (max daily loss/trades, consecutive-loss cooldown, news blackout). A sibling crypto bot
  ("Mr. Wonderful") was scoped the same fortnight (*2026-02-28 Kraken fee research*), sharing the
  cost-awareness DNA. Live paper-trading ran in Feb–early March **before** the tracked $100k account
  opened (2026-03-22). See [`RESEARCH_PROGRAM.md`](RESEARCH_PROGRAM.md) §1 for how this genesis frames
  the program's research question.
- **Thesis:** a discretionary Darvas-box playbook — daily PDH/PDL liquidity zones, sucker-moves,
  John Wick / Power-of-Towers setups, tiered zone classification — can be automated rule-for-rule.
- **Method:** hand-coded gates (`zone_detector`, `signal_engine`, `trade_manager`); first live
  deployment on OANDA practice. Validated against trade transcripts and a formal pre-deployment
  audit (3 passes).
- **Measured:** no clean aggregate survives — the box geometry itself was contaminated for much
  of the run (inverted boxes, stale slices, midnight box-reset amnesia; **B-068 → B-074**). The
  honest read is that any "edge" was inseparable from the box bugs.
- **Falsified / superseded:** the pre-deployment and daily-notes audits surfaced ~53 defects
  (**B-001 → B-053**), including the green-exit infinite-retry crisis (**B-033**) that
  established the still-standing doctrine *the bot never places reactive market orders*. A 30m
  rolling-box experiment (**B-069**) broke profitability and was reverted. Superseded in the
  V2/V3 transition. The earliest live failure on record — a USD/JPY *pitchfork*-signal **runaway
  re-entry** (2026-03-01/02: 20 identical SELL stop-outs in 3h10m, ~98 pips each, no loss-memory
  or cooldown) — is the primal circuit-breaker lesson, recovered from a dated session archive and
  catalogued under *legacy defects* in [`BOOK_OF_BUGS.md`](BOOK_OF_BUGS.md); notably the genesis
  spec had *called for* exactly those breakers, which the first live build shipped without.
- **Carried forward:** geometric anchoring of behavioural rules; pip-normalized thresholds;
  fixed-pip stops over equity-%; single-process enforcement; the no-reactive-market-order rule.
- **Graveyard:** `/SCROOGE ARCHIVE/V3/archives/mr-scrooge-v1/` (code, Trade-Strategy PDFs, exec
  summaries, AUDIT.md) and `/SCROOGE ARCHIVE/session-notes/2026-03-*` (daily notes).

## V2 — transitional agent era (Mar 21 – Apr 15, 2026)

- **Thesis:** re-house the bot inside the agent-workspace framework and coordinate multiple
  actors (bot / ratchet / harvester / SL-limit) around one broker position.
- **Method:** short-lived rewrite; mostly scaffolding that fed V3. First corpus/aggregator
  research compute began here.
- **Measured / falsified:** the multi-actor design produced the phantom-action bug family —
  a 4.5-hour silent zero-signal outage from a mis-indented `return None` (**B-054**), 46-order
  API spam on a dead position (**B-055**), and SL-ownership races (**B-056/B-057**). The
  corpus work hit OOM ceilings on the small box (**B-066/B-067**), which is the origin of the
  *heavy compute never on the live-trader host* rule.
- **Carried forward:** the shared-state `TradeCoordinator` pattern; single-resource ownership
  protocols; live zero-signal counters.
- **Graveyard:** `/SCROOGE ARCHIVE/V3/archives/legacy/.../mr-scrooge-v2/`.

## V3 — "The Matrix Era" (Apr 15 – 2026-06-16)

- **Thesis:** score entries with a factor matrix and route by regime — factor weights, routing
  tables, observe-mode gates, the first ML brains, and box-geometry forensics.
- **Method:** the longest-lived version and the origin of the bug-catalog discipline
  (**B-058 → B-074**). Factor scoring + strategy attribution telemetry + a live/shadow split.
- **Measured:** attribution was found *fundamentally unreliable* until designed-in
  (**B-064**), which dates every trustworthy live-forensic window to post-fix. Factor weights
  were discovered dead ("x") live for months while offline analysis kept trusting them
  (**B-085**) — the origin of *verify LIVE wiring before trusting offline analysis*.
- **Falsified / superseded:** retired 2026-06-16 when its service was disabled at the V4
  unified-dashboard cutover. The matrix approach was superseded, but its bug discipline,
  its exit-design lessons, and its attribution rigor all carried forward.
- **Carried forward:** the Book of Bugs itself; "exit design dominates results"; broker-vs-live
  divergence needs institutional memory; the box contaminated-window notes.
- **Graveyard:** `/SCROOGE ARCHIVE/V3/` (`SCROOGE_MASTER_INDEX.md` inside; code + data tarballs,
  matrix-era routing tables, a ~25 GB research corpus, the V1–V3 bug-catalog export). Retired
  V3/V4 repo docs (ADRs, evolution timeline, execution physics, research methodology) are
  harvested under `/SCROOGE ARCHIVE/docs-harvest/v3-repo-docs/`.

## V4 — "Bucket-Keyed" (2026-06-11 → 2026-06-18)

- **Thesis:** gate every strategy by its (pair × session × direction) **bucket** and let a
  utility ML brain pick among firings — the edge lives in brain-filtered bucket firings, not
  in any strategy standalone.
- **Method:** a 129-strategy live book (textbook + bucket-keyed combos), the BUCKET21 utility
  brain trained on `net_real` with per-bucket TAKE/AVOID maps as its top two features, and a
  unified dashboard. Mid-life it swapped the harvest scale-out ladder for a full-position
  **ratchet** runner exit.
- **Measured (the finding that defined the family):** **the exits were the bottleneck, not the
  strategies (B-076).** On 1.1M trades / 21 strategies / 4 pairs / 8yr, the exit ladder banked
  ≥20p on **0.0%** of trades while MFE showed **70%** of winners ran 20p+ and **57%** ran 30p+
  (max 907p); every loss was a fixed −10p. The trend/breakout strategies were *built to run* and
  the exit was throwing the runners away. The ratchet bake-off (8yr M5, Brock pip-utility)
  scored **+3.28p/trade vs +0.75p harvest** (sim); the 8-pair OOS holdout selected **+4.86p/trade**
  at floor, util +2.68 (sim). All 128 baseline buckets were negative — edge existed only in
  brain-filtered firings.
- **Falsified / superseded:** retired 2026-06-18 after **7 days** — killed by its own
  measurement honesty. The exit-bottleneck finding made a clean-room strategy-free rebuild the
  obvious next move.
- **Carried forward:** the ratchet runner exit; the cell (pair × session × direction) framing;
  Brock's pip-utility objective (floor +6, 20+/30+ bonuses, losses count 2×); the no-bias
  training principle (train on all pairs / all strategies / winners **and** losers).
- **Graveyard:** `/SCROOGE ARCHIVE/V4/` (`SCROOGE_V4_INDEX.md`; `archives/V4-Archive-2026-06-18/`
  code+data tarballs, verified 3,924 members intact after B-083; `backtest-sources/`). Retired
  V4 repo docs (strategy encyclopedia, backtest results, research methodology) are under
  `/SCROOGE ARCHIVE/docs-harvest/v4-repo-docs/`.

## V5 — "Strategy-Free / The Cell Era" (2026-06-18 → present)

A ground-up rebuild that grew through several distinct arcs. Day-by-day detail is in
[`../CHANGELOG.md`](../CHANGELOG.md); session diaries are in `/SCROOGE ARCHIVE/session-notes/`.

### Arc 1 — Launch (2026-06-18 → 06-20)
- **Thesis:** replace named strategies with per-(pair × session × direction) `direction_v2` /
  `momentum_v3` modules, a deterministic playmaker, and a step-trail ratchet.
- **Measured:** the modules went live 06-20 but had **zero live trades** through the launch
  weekend (market windows). The prior tape read **−$6,114 over 120 trades (V4+V5), −$2,234 over
  36 V5-era trades** (broker), and the V5_v1 brain was *anti-calibrated* (m_cert negatively
  correlated with wins). Whatever was live was losing.

### Arc 2 — The methodology overhaul (2026-06-20/21 weekend)
The two days that now define how the project is measured — 23 commits, 12 research sessions.
- **Thesis → standing law:** measure from **broker fills, not the journal** (the 44-trade
  journal matrix had missed **70 of the real 120 trades**, B-084); use **1H forward pip, not
  realized P/L**, to judge *entries* (exit logic flips ~32% of trades from market direction);
  include manual-closed trades; **walk-forward everything** (train <2024, test ≥2024); resolve
  **per-cell, never global**.
- **Headline finding — NY is a momentum-FADE session** for all 8 pairs, confirmed four
  independent ways (broker P/L, broker 1H-forward-pip, 8yr walk-forward, ALIGN resolution).
  V5 lost in NY because its direction engine trend-followed `h1_ret_1bar` into a fade regime.
  Unification: short-term momentum *without* higher-timeframe backing = exhaustion/fade; *with*
  backing = continuation.
- **Also:** the **MAE-flip doctrine** (a losing cell with MAE ≫ MFE is the right signal wired
  backwards → flip the entry); ~5 broker-confirmed winner cells out of 48 (e.g. USD_CAD/ny/long
  +6.61p, EUR_USD/london/short +6.31p, broker fwd, n≈7); 10 cells disabled; a consolidated
  48-cell ruleset. Scope caveat: winner-cell N was 5–9 trades at derivation — early-era
  evidence; the *method* is what stands.
- **Superseded:** many magnitude figures from this weekend were later found to sit on the
  H1-leak parquets (**B-078**, below) and are upper bounds; the *directions* (NY-fade, per-cell
  disagreement) survived on clean anchors.

### Arc 3 — Exit-bottleneck confirmation and the ratchet, in V5 (2026-06-13 lineage → V5)
The exit-bottleneck finding (B-076) and the ratchet runner exit were first proven in the V4
window (2026-06-13) and carried into V5 as the base exit. Brock's pip-utility objective and the
no-bias training principle were locked here: reward-shaping (floor +6, +20 pays 2×, +30 pays 3×,
losses ≥6p hurt 2×) is *allowed* because it is the goal; the *training* must carry no bias
(no threshold targets, no dropped features, no curated trades, no human-picked floors).

### Arc 4 — The truth week & H1-leak repair (2026-07-01 → 07-03)
- **B-078 — the H1 look-ahead leak:** research parquets had joined H1 features on open-time,
  injecting up to 55 minutes of future bar into every H1 feature. **All H1-feature research
  numbers before 2026-07-03 are upper bounds** (some inflated 8–15×). Parquets were rebuilt
  leak-clean; tainted sessions were quarantined and re-based. Clean anchors are broker
  measurements, M5 features, and any post-fix corpus.
- **The truth matrix:** a per-bar dual-direction forward MFE/MAE table (8 pairs × 8yr,
  broker-anchored **r = 0.84–0.90** on ~155 V5 trades) became the reference for exit geometry;
  a 90-config ratchet EV sweep and a 48-cell calibration artifact were built on it.
- **Cost accounting from broker fills:** on 963 fills (05-31 → 07-03), the RT spread cost was
  **$18.6k against −$22.5k net P/L — ~83% of the loss was transaction cost**; the 21:00 UTC
  rollover blows spreads out 4–10× (**B-086**).

### Arc 5 — The cell-era cutover (Phase D, 2026-07-04)
- **Thesis, made literal:** the (pair × session) **cell** IS the strategy unit. The
  `direction_v2`/`momentum_v3` stack was retired to `modules/archive/signals_legacy/`
  (rollback tag `pre-cell-cutover-2026-07-04`); execution became CellModule → CellIntent →
  portfolio risk caps → order, with per-setup exits on `Position.exit_params`.
- **Book at cutover:** 10 ACTIVE / 3 SHADOW (CONTROL formulas = negative-EV falsification
  instruments that must never promote) / 11 NO-SIDE / 3 DISABLED. Direction-persistence rule:
  lock-era traded sides govern a cell until same-engine n≥20 argues otherwise. Finding on the
  retired locks: raw-indicator locks survived re-derivation verbatim; composite "certainty"
  locks were proxies at best.

### Arc 6 — Cost-aware three-speed exit book (2026-07-05)
Exit geometry must match a cell's excursion class: **FAST** cells exit on server-side TP
brackets at per-pair cost floors (cannot slip); **MEDIUM** cells run spread-aware ATR-scaled
ratchets; **LONG** cells are late-engage runners; a global rollover stop-freeze (20:55–22:05
UTC) closes the wash. Full writeup: [`PAPER_cost_aware_exit_classes_2026-07-05.md`](PAPER_cost_aware_exit_classes_2026-07-05.md).

### Arc 7 — The dial-in weeks (2026-07-06 → 07-14)
Per-cell tuning with a repeatable method: side-check via side-signed drift in the exact
condition window; SL set to winners' MAE p75; quintile MAE/MFE separators cut only clean
worst-end blocks, combined-verified (n≥250, gain ≥+1.5p); live flips over shadow-waiting
(Brock doctrine); a cemetery for sideless setups. Outcomes across the weeks: several live side
flips (AUD_USD/lon, GBP/asia, AJ/ny timing, UJ/lon), SL resizes, dead-band refreshes, and a
scoreboard judged on shrinking avg-loss (toward ~−50) rather than win-rate alone. A key
insight: the same indicator flips meaning across cells (`atr_h1_relative` is a cap on
UJ/asia, a floor on EUR_JPY/ny).

### Arc 8 — The edge hunt: five falsifications, then the wide-stop turn (2026-07-14)
The session that asked *"since February — is there an automatable edge at all?"* on 8yr/16yr
leak-safe corpora. **Five structurally distinct price-edge families were falsified**, all
dying at the same wall — retail OANDA-majors spread > any price-predictable edge in the data:
1. **M5 scalping** — the edge (+0.8–1.3p) is the same size as the toll (~1.0–1.5p spread).
2. **Single-pair daily trend** — ~0 gross edge at every 1h→4d horizon; hit-rate 49–50%; 0/32
   regime gates net-positive with year-consistency.
3. **Diversified retail TSM** (47 instruments, 2010–2026, vol-targeted) — **gross Sharpe 0.08,
   net Sharpe −0.22**; the engine validated (2022 captures correct) but the venue lacks the
   breadth/cost a real CTA needs.
4. **Symmetric dual-ratchet straddle** — net −0.9 to −2.6p/straddle, 0/8 years positive on
   every pair; a coin-flip pair guarantees you hold the −12 loser every entry.
5. **Tight-stop-and-reverse on "lopsided" cells** — 0/24 cells net-positive; the tell was
   `asym_train = 0.0` in every cell: per-trade MFE≫MAE is *realized direction*, not a
   selectable cell property.

**Then the turn (late session, Brock).** Reload-on-red-stop (re-enter same direction) flipped
positive; a wide-SL sweep (never tried >20) showed expectancy rising ~monotonically to SL40-60;
a 29-cell scan at fixed SL40 moved the positive count 4 → 17 (mean +0.67p, robust OOS). The
**methodological bombshell:** the tighten-to-winners'-MAE-p75 dial-in was **survivorship-biased**
— MAE was measured only on trades that survived to win, blind to the trades a tight stop killed
that would have recovered. That morning's tightenings were backwards for these cells.

**Capstone portfolio sim (head-to-head, same 6-cell shortlist, both runs):**
- **CURRENT (tight stops):** −93%/yr, Sharpe −3.54 — account → zero every year (sim).
- **WIDE (SL40):** +25.4%/yr, Sharpe 1.05, maxDD −40%, Calmar 0.64, positive all 8 years (sim).
The **head-to-head direction** (wide beats tight on identical cells) is the selection-unbiased
part and is trusted. The **absolute level is not** — inflators are named honestly: cell
selection (6 best), 2026 partially in-sample, no slippage/financing (wide stops slip). Honest
haircut ≈ **Sharpe 0.6–0.8** — a low-Sharpe grind, not a jackpot. Net revision of the five
falsifications: there IS a runnable-looking edge, but it is gated on WIDE stops, and the
tight-stop dial-in doctrine was actively harmful. **Live stops were not changed on the sim
alone.**

### Arc 9 — Range-sized stops deployed (2026-07-14 late)
Per-(pair × session) swing was measured (chronic quiet regimes confirmed: USD_CHF/asia med 28p
on a 143-day sub-40 streak). A range-sized SL (40 quiet / 50 mid / 60 loud) with brackets→ratchet
beat both tight and flat-40 in the 6-cell sim (rarest reds 14%, best drawdown, most big runners)
and was deployed to all 29 cells. This is the current live book — a **forward experiment on the
practice account**, not a promoted result; the decisive test still owed is walk-forward cell
selection (train 2019–22 / test 2023–26) plus a slippage haircut.

### Arc 10 — Exit retuning and B-090 (2026-07-15/16)
Brock-driven exit-mechanic work: the ratchet **trigger was raised 3.5 → 7.5** book-wide (skip
scratch-engages; sim Sharpe 0.70 vs 0.60). Then Brock caught **B-090** ("how does a 40-SL bot
lose $8?"): the range-sized deploy had left `trail_mult=1.0`, so `cell.py` ATR-scaled the trail
to ~5p and parked the ratchet stop *below breakeven* — green given up as red, silently defeating
the whole ratchet whenever atr_5m > trail_pips. Fixed by `trail_mult → 0` (fixed trail 2.5): now
engage +7.5 locks +5 and, once engaged, a trade cannot exit red barring slippage/gap. A
break-even lock was tested and **rejected** on the spread floor (a "flat" price is already −1
spread; locking within a spread of entry realizes a loss, not a scratch). Doctrine added: never
lock a stop within a spread of entry.

- **Key papers/reports (in repo):** [`PAPER_cost_aware_exit_classes_2026-07-05.md`](PAPER_cost_aware_exit_classes_2026-07-05.md),
  [`../research/README.md`](../research/README.md) (truth hierarchy + validation protocol),
  [`../CHANGELOG.md`](../CHANGELOG.md).
- **Learned (scoped):** ~83% of a 5-week losing window was transaction cost (broker); the market
  telegraphs WHEN and HOW FAR but not WHICH WAY (five falsifications, sim + broker); tight stops
  were converting a thin-but-real edge into losses (sim head-to-head); exit geometry must match
  cell excursion class.
- **Graveyard:** `/SCROOGE ARCHIVE/V5/` (`SCROOGE_V5_INDEX.md`, archives, test data);
  session diaries under `/SCROOGE ARCHIVE/session-notes/`; research corpora and truth-matrix
  parquets under `/SCROOGE ARCHIVE/research-corpora/`.

## V6 — public rebuild (repo created 2026-07-05; pre-live)

- **Thesis:** everything durable from V5, in a clean public repo — no credentials, no account
  identifiers, no private network topology, ever, including git history.
- **Method:** ported from V5 on 2026-07-05 with an audit pass (fresh history, legacy archive
  left behind, lock-era fingerprint checks retired — see [`AUDIT_TODO.md`](AUDIT_TODO.md) for
  the sim-gated removal ledger). A dry-run shadow runs the same engine in parallel with V5, and
  a **parity gauntlet** compares their decisions cycle-by-cycle. That gauntlet caught its own
  failure mode (2026-07-13): a config-sync gap meant the shadow traded *retired sides* for three
  days while the tool reported it as engine drift — fixed, and the discipline "any V5 dial-in
  touching generator overrides must be ported to V6 in the same session" was written into the
  ledger.
- **Carries forward:** the cell architecture, the three-speed exit book, the measurement
  doctrine, this history log, and the Book of Bugs. Everything else lives in the graveyard and
  is referenced, not carried.

---

## Graveyard map (Dropbox `/SCROOGE ARCHIVE/`)

The archive is the single consolidated graveyard + research library. Its own entry points are
`00_MASTER_INDEX.md`, `00_HISTORY_V1-V6.md`, and `00_BOOK_OF_BUGS_V4-V5.md`.

| Path | Contents |
|---|---|
| `/SCROOGE ARCHIVE/V3/` | V1+V2+V3 complete: code, data, matrix-era routing tables, V3-era master index, the V1–V3 bug-catalog export, the original box bot + Trade-Strategy library |
| `/SCROOGE ARCHIVE/V4/` | Bucket-keyed era: code+data tarballs (verified intact), backtest sources, `SCROOGE_V4_INDEX.md` |
| `/SCROOGE ARCHIVE/V5/` | Strategy-free/cell era: `SCROOGE_V5_INDEX.md`, archives, test + H1 trade data |
| `/SCROOGE ARCHIVE/session-notes/` | Dated research-session diaries (2026-03 daily notes → present) — the working record behind every CHANGELOG entry, plus Brock's Bot Strategy Book |
| `/SCROOGE ARCHIVE/docs-harvest/` | Full `docs/` trees lifted from the retired V3 and V4 repos: ADRs, evolution timeline, strategy encyclopedia, execution physics, research methodology, fix postmortems |
| `/SCROOGE ARCHIVE/research-corpora/` | Backtest corpora and truth-matrix parquets (8 pairs × 8yr forward MFE/MAE, broker-anchored), qtl 8yr feature sets, ML-lab and direction-ML artifacts — everything needed to reproduce or challenge the research |

*Archive access is private. Curated folders can be shared by link on request — the archive
contains operational material and is link-shared only after a per-folder sanitization review.*
