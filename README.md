<div align="center">

# Mr. Scrooge V6

### A forex bot that puts strategies on trial.

*Every strategy and entry/exit indicator runs as a **shadow** first — stamped on live markets, scored against forward broker-verified movement, and **promoted to live capital only when it clears an evidence bar**. Setups that degrade get demoted by the same evidence — **autonomously, daily, by a published standard**. The book is whatever survives.*

*Six versions · 8 years of data · **18 pairs scanning · ~200 setups on trial** · 100+ strategies tried · 50+ indicators — and one falsifiable core finding:*
**you can't predict direction, but you can price movement, size the stop to the room the market actually gives, and refuse to give a winner back.**

*An open-source algorithmic **forex trading bot** for **OANDA**, written in **Python** — with a live control-panel dashboard, an autonomous promote/demote governor, a full backtesting research program, and an honest, broker-verified track record.*

![license](https://img.shields.io/badge/license-Apache--2.0-808a94) &nbsp; ![account](https://img.shields.io/badge/account-OANDA_practice-cf8e3e) &nbsp; [![tests](https://github.com/BrockStar3540/mr-scrooge-v6/actions/workflows/tests.yml/badge.svg)](https://github.com/BrockStar3540/mr-scrooge-v6/actions/workflows/tests.yml) &nbsp; [![release](https://img.shields.io/github/v/release/BrockStar3540/mr-scrooge-v6?color=3fb950&label=release)](https://github.com/BrockStar3540/mr-scrooge-v6/releases) &nbsp; [![governor](https://img.shields.io/badge/bar_governor-autonomous-58a6ff)](docs/GOVERNOR.md) &nbsp; **[`forward test · verdict at trade #100`](docs/FORWARD_TEST_PROTOCOL.md)**

</div>

<!-- LIVE_BALANCE_START -->
<div align="center">

![status](https://img.shields.io/badge/status-LIVE-3fb950?style=flat-square) ![P/L](https://img.shields.io/badge/P/L-%2B%241,509.28_(%2B9.06%25)-3fb950?style=flat-square) ![trades](https://img.shields.io/badge/trades-85/95_green-3fb950?style=flat-square) ![open](https://img.shields.io/badge/open-2_(%2B%2420)-58a6ff?style=flat-square)

[![live track record](livelog/equity.svg)](livelog/trades.csv)

</div>

> **Live track record of the *current* configuration** — range-sized wide-stop ratchet · SL 40/50/60 · engage +8.5 → lock +6 → trail 2.5 fixed (7.5→8.5 on 2026-07-19) + Party Package popper grids (V6.1), live since 2026-07-16 (55 popper trades in the record), auto-updated hourly from **broker-verified fills** ([trades](livelog/trades.csv) · [equity](livelog/equity.csv)). Small sample, honest record. Prior configs and the −84% research tuition are a different story — [read the history](docs/SCROOGE_HISTORY.md). Practice account, not real money.
<!-- LIVE_BALANCE_END -->

---

## The tape — what the tuition cost

![The tape: practice-account balance from $100k through the $15,598 low to today](docs/images/account_tape.svg)

Everything here was paid for on one practice account, and we publish its tape rather than curate it. It opened at **$100,000 (Mar 22, 2026)** and bottomed at **$15,598** (July 10 by daily closing balance) — an **−84% drawdown** across the V1→V4 strategy eras. That number is the strongest argument in this repo: five versions of increasingly careful research could not out-predict the market. V5's measurement overhaul (broker-fill truth, cell-era falsification discipline) stopped the bleeding; the V6 trial system is the climb attempt. The chart regenerates from broker transaction balances (`research/tools/account_tape.py`) — it can't go stale and it can't be curated.

## The game — house, not gambler

Most bots wager that some indicator reveals *which way* price will go. We spent five versions proving it doesn't: **across three independent methods, entry features predicted WHEN price moves and HOW FAR — never WHICH WAY** (0 of 144 feature×cell combos carried signed direction). So V6 plays the house's game:

- **Trade only where the table is measured.** The unit is the **cell** — one (pair × session), profiled from 8 years of broker-anchored fills: how far price travels, how often, how fast, what the round-trip toll costs.
- **Enter on presumed *movement*, never presumed *direction*.** A cell trades only when a **validated setup** fires — explicit, mechanical conditions on standard indicators. No setup → no trade. That's the whole "strategy."
- **Names never lie about direction.** A setup keeps its name-true side forever. When a losing setup's adverse excursion outsizes its favorable (the MAE-flip signature), a daily audit automatically wires a **counterpart** setup firing the opposite direction at the same trigger — its own name, its own record, its own trial.
- **Let the exit earn — and give it room.** The only edge that survived audit lives in stops wide enough that noise doesn't kill a slow winner, plus a ratchet that locks green once a move proves itself.
- **Wide stops, after a hard lesson.** The old tighten-to-winners'-MAE dial-in was **survivorship-biased** — MAE was measured only on trades that survived to win, blind to the ones a tight stop would have killed first. An 8-yr head-to-head: tight book blew up, wide book profited.
- **One exit engine, everywhere.** A range-sized wide-stop ratchet: SL **40 / 50 / 60 pips** by session swing; trigger **+8.5 → lock +6 → trail 2.5 fixed**; **no timeout**. Brackets removed so runners can express. ([B-090](docs/BOOK_OF_BUGS.md) killed an ATR-scaled trail that gave green back as red.)
- **Party Package (V6.1, forward experiment).** Every parent trade hangs a **re-arming grid of "poppers"**: independent same-direction trades fired at laddered adverse levels, each with its own 60p server-side SL and its own ratchet. Simulated verdict on our cost model: the grid gross-harvests ~+100–150p/parent and pays *more* than that in toll — this deployment is the live test of exactly that claim ([full paper](docs/papers/PAPER_party_package_scale_in_2026-07-19.md)). Global kill switch + per-cell opt-outs on the dashboard.
- **Portfolio caps are risk only, no alpha:** `max_concurrent = 8` (parents + poppers), `max_per_currency_direction = 4`, 10% of balance notional per trade, ~80% total exposure ceiling.

## The trial system — how a strategy earns (and loses) its seat

Nothing in this repo trades because we believe in it. Every setup — ours, resurrected from old
tapes, or contributed — walks the same ladder:

1. **Shadow.** The setup is wired into a cell with explicit entry conditions and stamps a
   `CELLSHADOW` line every time it would have fired — zero orders, zero risk. Stamps are
   episode-deduped and scored on the **forward M5 path** (net pips at 240m) — market truth,
   not our own exit luck.
2. **The Shadowboard.** Every setup, ACTIVE and SHADOW alike, is scored on the identical
   metric and **sorted exactly as the governor acts** — defended actives at the top, then
   holding/deferred, promote-ready shadows, shadows building evidence (ranked by how many
   bar conditions they already pass), queued ⏳ rows, and demote-due at the bottom. Each
   row's **verdict** (DEFENDED / HOLDING / DEFERRED / PROMOTE READY / BUILDING / DEMOTE
   DUE) is computed by the governor's own code, so the board can never disagree with the
   06:35Z run — the whole docket is visible, waiting is a state, not an absence.
3. **Promotion — the activation bar, flipped automatically.** The **[Bar Governor](docs/GOVERNOR.md)**
   (`ops/governor.py`, daily) promotes a shadow to ACTIVE when its **current-era** evidence
   clears the full predicate: **n ≥ 20 executable-exit episodes across ≥ 10 independent
   day/session blocks, ≥ +2.0 net pips/episode, a positive day-block bootstrap lower
   bound, a non-negative last-7-days, and a Benjamini–Hochberg q ≤ 0.05 across the whole
   candidate docket** — margins chosen because the measured execution toll makes any
   sub-1p claimed edge indistinguishable from zero, with real multiple-testing control
   because ~150 hypotheses run at once. Shadow trials are scored on **executable prices**
   (entry at the stamped ask/bid, the setup's own exit geometry simulated worst-case
   intrabar), never frictionless mid drift. A setup that fails is re-tested only when it
   has *new* independent evidence. No human in the loop; the dashboard trophy is computed
   by the **same predicate** the governor promotes on — they can never disagree.
4. **Demotion — the FAMILY RULE: net loss is the key.** A parent setup and the poppers its
   grid fired are **one economic unit**, tracked in **broker net pips** (every popper fill
   carries its parent's setup id). Family n ≥ 5 at **−60p or worse** → demoted, and the
   cell's poppers are switched off with it; family at **+60p or better defends the seat** —
   real broker green outranks the worst-case stamp simulator. Only unfamilied actives fall
   back to the stamp bar (era v2 n ≥ 20, avg < +2.0) — audited against the broker, never
   our own journal. **Judge-when-flat:** while any family trade is open there is no verdict
   at all — a parent can stop −60p while its poppers are still riding toward +30p, so the
   episode is scored only when it completes, never mid-scale-in. Demoted setups keep
   stamping as shadows and can re-earn the seat. Every flip
   restarts that setup's evidence clock: **proof never blends across eras**, and every
   decision is written to a public ledger (`data/governor_ledger.jsonl`). Rails: max 2
   promotions + 4 demotions per day, sides never flipped, `manual_only` respected.

**The autonomous day:** `06:30Z` the [counterpart audit](research/tools/counterpart_audit.py)
wires opposite-direction twins for any MAE-heavy loser → `06:35Z` the governor promotes and
demotes by the bar → `06:45Z` a change-gated, twice-verified backup snapshots the result.
The humans set the standard; the bot flips the switches.

**Currently on trial (~200 setups):**
- **The replay shadow book** — 10 pairs the book never traded (CAD, CHF, NZD crosses +
  GBP/JPY), resurrected from this account's own March/April 2026 tapes where session-extreme
  fades and trend-pullback entries kept winning. The standing prior: cross spread toll kills
  most of them — and that verdict would be the system working.
- **The Strategy-Book five** — the strongest threshold-translatable strategies from the
  retired June-era book (extended-move fades both sides, band fades both sides, Bollinger
  reversion, range scalps), thresholds verbatim, on their original 4-major backtest universe.
  Their claimed EVs are known upper bounds (a corpus look-ahead was found and fixed later);
  the current-era stamps are the re-measurement, and errata now ship inside the archived
  originals.
- **Strategy E** — the June white paper's trend-pullback short, re-adjudicated forward under
  the live exit after its numbers were superseded ([errata in the archive](docs/DATA_AND_MODELS.md)).
- **The t20 wider-engage gears** — the one material positive in the falsification ledger,
  running as scored shadow twins on the majors.

**Until a strategy cell has proven its edge, this is a forward-testing bot** — the live book
is only the setups currently holding the bar.

## The pipeline

```mermaid
flowchart LR
    A[OANDA feed<br/>18 pairs] --> B{cells<br/>pair × session}
    B -- "ACTIVE setup fires" --> C[portfolio caps<br/>risk only] --> D[order +<br/>server-side wide SL] --> E[ratchet exit<br/>engage +8.5 → lock +6 → trail 2.5] --> F[broker fills<br/>= the only truth]
    B -. "every setup stamps<br/>(zero risk)" .-> S[Shadowboard<br/>LCB-ranked evidence]
    F -- "fills audit" --> G{{Bar Governor<br/>daily · autonomous}}
    S -- "era evidence" --> G
    G -- "bar met → promote" --> B
    G -- "bar lost → demote" --> B
    S -- "MAE ≫ MFE loser" --> H[counterpart audit<br/>opposite-direction twin] -.-> B
    style G fill:#1f6feb,stroke:#58a6ff,color:#fff
```

*Book today: 18 pairs · 54 cells · ~200 setups on the docket (8 ACTIVE cells holding seats, everything else stamping as shadows). Exit gear book-wide: engage +8.5 → lock +6 → trail 2.5. Nothing is DISABLED — under the governor, nothing is beyond the reach of evidence.*

## The dashboard

A self-contained local control panel (`127.0.0.1:8084` — [bind elsewhere](docs/DASHBOARD.md) with `DASHBOARD_HOST`): live account + open trades, per-pair signal cards, the cell book, live exit tuning, popper switches, credentials, and the trading pause. Two tabs worth showing:

**SHADOW — the trial courtroom.** The Bar Governor card states the full standard — the
promotion bar, the family rule, judge-when-flat — above a Shadowboard sorted exactly as the
governor acts (defended seats first, demote-due last), with each row carrying the governor's
own verdict, its broker family net pips, and promote/demote controls:

![The SHADOW tab: the governor's standard + the verdict-ranked Shadowboard](docs/images/dashboard-shadow.png)

**INDICATORS — why is/isn't it firing.** Every pair leads with its current session's ACTIVE
setups as live condition bars — green zone + marker when in range, the blocking condition
named when not, a READY glow when a setup is armed:

![The INDICATORS tab: per-pair why-not-firing condition bars](docs/images/dashboard-indicators.png)

## What we falsified

Five edge families died at the same wall — on retail OANDA majors, no price-*prediction* edge cleared cost — then a sixth move revised the exit itself. Full write-ups: **[docs/papers/PAPER_edge_hunt_falsifications_2026-07-14.md](docs/papers/PAPER_edge_hunt_falsifications_2026-07-14.md)**. When later findings superseded our own published numbers (a corpus H1 look-ahead, a winner-capping exit family), we shipped **errata into the archived originals** rather than quietly moving on.

| edge family | verdict |
|---|---|
| M5 scalping | edge ≈ its own transaction cost |
| Single-pair daily trend | a coin flip |
| Diversified retail TSM | real edge, but needs institutional breadth/cheap execution — net Sharpe −0.22 on our venue |
| Symmetric both-sides straddle | you always own the loser |
| Tight-stop-and-reverse | the "asymmetry" was realized direction, not a selectable property |
| **→ the turn** | tighten-to-MAE dial-in was **survivorship-biased** → the wide-stop book |
| Wide-stop book (H6, pre-registered WF) | gross Sharpe 1.26 real, **net 0.03** — the edge equals the execution toll ([paper](docs/papers/PAPER_h6_walkforward_2026-07-16.md)) |
| Scale-in / popper grids (10 rounds) | gross harvest ~+100–150p/parent is **real**; toll ~130–190p is bigger; the majors are **first-passage fair** at every lock level ([paper](docs/papers/PAPER_party_package_scale_in_2026-07-19.md)) |

## The forward tests now running

Everything live is a **forward experiment on a practice account**, scored against **broker fills**
(never our own logs), per configuration, at n≥20 before any verdict — no aggregate blending across eras.

> **📜 The 100-trade protocol (pre-registered 2026-07-28):** the current-config window
> **ends at its 100th closed trade** — then the full write-up publishes here (starting
> balance **$16,665.12** broker-verified, ending balance, the whole tape), the practice
> account closes, and the system goes **live with $2,500 real money** at 15%/trade,
> 6 trades max — same hourly public livelog, same graph, real fills. The endpoint, the
> consequences, and the live gearing were all declared *before* the result was known:
> [docs/FORWARD_TEST_PROTOCOL.md](docs/FORWARD_TEST_PROTOCOL.md). To be plain: **100
> trades in two weeks is not proof of sustained edge** — it's enough for *us personally*
> to try live with a small stake. Use your own discernment; results vary over time, and
> when things go wrong the drawdown can be substantial.

1. **The wide-stop parent book** — the decisive walk-forward
   [falsified the level](docs/papers/PAPER_h6_walkforward_2026-07-16.md): gross Sharpe 1.26,
   **net 0.03** after realistic slippage. The edge is real and exactly the size of the toll;
   the practice tape is the standing measurement of that knife-edge.
2. **The t20 wider-engage shadow** — the one material positive in the ledger (blind-test
   Sharpe +0.57, avg green +8 → +22p, zero overfit gap), running as scored shadow twins.
3. **The Party Package (V6.1)** — re-arming popper grids, deployed *against* their own sim
   verdict on purpose: real fills will confirm or refute the *cost model itself* — the one
   variable no offline sim can settle ([paper](docs/papers/PAPER_party_package_scale_in_2026-07-19.md)).
   First 12 days of tape (90 fills): one family produced the entire net loss — GBP/USD-long
   parents+poppers −$858 while every other family ran green — which is what motivated the
   **family rule** (v6.7): the parent and its poppers are judged as one unit, in broker net
   pips, only when the episode is flat.
4. **The replay shadow book (v6.3)** — 10 never-traded pairs running the shapes that won on
   them in the March/April 2026 tapes, shadows only, activation bar as the sole judge.
5. **The arraigned record (v6.4)** — Strategy E and the Strategy-Book five, re-tested forward
   under the live exit after errata superseded their backtest numbers.
6. **The Bar Governor itself (v6.5)** — the autonomy loop is the newest experiment: does an
   evidence-gated, self-governing book outperform a hand-curated one? Its every decision is
   in the [public ledger](data/governor_ledger.jsonl).

Details: [docs/RESEARCH_PROGRAM.md](docs/RESEARCH_PROGRAM.md), [docs/ROADMAP.md](docs/ROADMAP.md).

## 🏆 The $10,000 Strategy Contest

<div align="center"><a href="CONTEST.md"><img src="docs/images/contest_badge.png" alt="$10,000 Contest Prize" width="300"></a></div>

Think you have a strategy that can survive this harness? **Our sponsor has put $10,000 on
it.** Submit a fully mechanical strategy — pairs, sessions, exact entry indicators, exact exit
rules, plus your own evidence it works — and we'll put it on trial in the same forward-testing
harness everything here faces. Run **90% winners (profitably)** or **net +500 pips in 30
days** under our measurement and the prize is yours. Standing contest until someone wins;
if two qualify in the same window, best takes $10,000 and the runner-up $5,000.

**Read the full rules: [CONTEST.md](CONTEST.md)** · submit via the
[contest issue template](.github/ISSUE_TEMPLATE/contest_submission.md).

## Read the research

| | |
|---|---|
| 🧭 **[Research Program](docs/RESEARCH_PROGRAM.md)** | **start here** — the falsification method, the activation-bar doctrine, open dockets |
| 🤖 **[The Bar Governor](docs/GOVERNOR.md)** | the autonomous promote/demote loop — the standard, why the numbers, the rails, the ledger, the ON/OFF switch |
| 📜 **[History V1→V6](docs/SCROOGE_HISTORY.md)** | every version, the edge-hunt arc, the survivorship turn |
| 🐛 **[Book of Bugs](docs/BOOK_OF_BUGS.md)** | B-001→B-098 — every dead end and defect, on purpose |
| 📄 **[Papers index](docs/papers/)** | incl. the [cost-aware exit-classes paper](docs/PAPER_cost_aware_exit_classes_2026-07-05.md) (the chapter the wide-stop turn revised) |
| 🔬 **[Research & data index](research/README.md)** | corpora, retired modules, the strategy graveyard |
| 📦 **[The Archive (Dropbox)](https://www.dropbox.com/scl/fo/uyjwoj274ndzqg98ol72p/AEB6zn4q-jFexhZxVmYFRyc?rlkey=a06ocaqxuyz4at1dfkjmww1i9&st=kup4s0x9&dl=0)** | the readable research record — papers, session notes, backtest results & version history, **with errata where later findings superseded them** (raw corpora / models / code privately archived, available on request) |
| ⚙️ **[Setup](docs/SETUP.md)** | from-zero install: OANDA **practice** account, venv, credentials (dashboard **or** env vars), run |
| 📊 **[Dashboard](docs/DASHBOARD.md)** | the local control panel at `:8084` — every tab, every switch, `DASHBOARD_HOST` for LAN use |
| 🏆 **[Contest Terms](CONTEST.md)** | the standing $10,000 strategy challenge — rules, criteria, how to submit |
| 🤝 **[Contributing](CONTRIBUTING.md)** | external ideas welcome, treated as untrusted input — same falsification gauntlet our own ideas face |
| ⚖️ **[License](LICENSE)** | Apache-2.0 |

*Think we're wrong? Good. [The archive](https://www.dropbox.com/scl/fo/uyjwoj274ndzqg98ol72p/AEB6zn4q-jFexhZxVmYFRyc?rlkey=a06ocaqxuyz4at1dfkjmww1i9&st=kup4s0x9&dl=0) holds the papers, notes, and backtest results; the raw corpora are available on request so you can re-run the analysis and attack the conclusions — leak-checked corpus → walk-forward → fired-trade sim → shadow → capital. Nothing reaches the live path without passing that gauntlet.*

## ☕ Support this work

I built this in the open over **hundreds of hours and millions of paid AI-coding tokens** — and I'm not rich. There's no fund or company behind it, just me putting the whole thing out there, losses and all.

If you got value from it, learned something from the falsifications, or just appreciate a trading project that shows its −84% tape instead of hiding it — consider buying me a coffee. Every bit genuinely helps, and the more support there is, the more inclined I am to keep building public projects like this one.

[![Buy Me a Coffee](https://img.shields.io/badge/☕_Buy_me_a_coffee-BrockStar3540-ffdd00?style=for-the-badge&logo=buymeacoffee&logoColor=black)](https://buymeacoffee.com/BrockStar3540)

---

> ⚠️ **Research software on an OANDA practice account. Not financial advice. The wide-stop result is a simulation with known inflators and its live verdict is pending. Leveraged forex can lose more than your deposit. If you run this, the outcomes are yours.**
