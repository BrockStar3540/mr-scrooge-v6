<div align="center">

# Mr. Scrooge V6

### A forex bot with no strategy — on purpose.

*Six versions · 8 years of data · 20 pairs · 100+ strategies · 50+ indicators — boiled down to one falsifiable idea:*
**you can't predict direction, but you can price movement, size the stop to the room the market actually gives, and refuse to give a winner back.**

![license](https://img.shields.io/badge/license-Apache--2.0-808a94) &nbsp; ![account](https://img.shields.io/badge/account-OANDA_practice-cf8e3e) &nbsp; **`41 tests passing`** &nbsp; **`forward test · verdict pending`**

</div>

<!-- LIVE_BALANCE_START -->
<div align="center">

![status](https://img.shields.io/badge/status-LIVE-3fb950?style=flat-square) ![P/L](https://img.shields.io/badge/P/L-%2B%24179.67_(%2B1.08%25)-3fb950?style=flat-square) ![trades](https://img.shields.io/badge/trades-9_·_100%25_green-3fb950?style=flat-square) ![open](https://img.shields.io/badge/open-3_(−%24256)-58a6ff?style=flat-square)

[![live track record](livelog/equity.svg)](livelog/trades.csv)

</div>

> **Live track record of the *current* configuration** — range-sized wide-stop ratchet · SL 40/50/60 · engage +7.5 → lock +5 → trail 2.5 fixed, live since 2026-07-16, auto-updated hourly from **broker-verified fills** ([trades](livelog/trades.csv) · [equity](livelog/equity.csv)). Small sample, honest record. Prior configs and the −84% research tuition are a different story — [read the history](docs/SCROOGE_HISTORY.md). Practice account, not real money.
<!-- LIVE_BALANCE_END -->

---

## The tape — what the tuition cost

![The tuition: practice-account equity from $100k to the $15,598 low to ~$16.8k](docs/images/account_tape.svg)

Everything here was paid for on one practice account, and we publish its tape rather than curate it. It opened at **$100,000 (Mar 22, 2026)** and bottomed at **$15,598 (Jun 10, 2026)** — an **−84% drawdown** across the V1→V4 strategy eras. That number is the strongest argument in this repo: five versions of increasingly careful research could not out-predict the market. V5's measurement overhaul (broker-fill truth, cell-era falsification discipline) stopped the bleeding; whether the wide-stop book can climb is the open forward experiment.

## The game — house, not gambler

Most bots wager that some indicator reveals *which way* price will go. We spent five versions proving it doesn't: **across three independent methods, entry features predicted WHEN price moves and HOW FAR — never WHICH WAY** (0 of 144 feature×cell combos carried signed direction). So V6 plays the house's game:

- **Trade only where the table is measured.** The unit is the **cell** — one (pair × session), profiled from 8 years of broker-anchored fills: how far price travels, how often, how fast, what the round-trip toll costs.
- **Enter on presumed *movement*, never presumed *direction*.** A cell trades only when a **validated setup** fires — mostly volatility-timing (`atr_5m` is the master knob), side set by measured persistence. No setup → no trade. That's the whole "strategy."
- **Let the exit earn — and give it room.** The only edge that survived audit lives in stops wide enough that noise doesn't kill a slow winner, plus a ratchet that locks green once a move proves itself.
- **Wide stops, after a hard lesson.** The old tighten-to-winners'-MAE dial-in was **survivorship-biased** — MAE was measured only on trades that survived to win, blind to the ones a tight stop would have killed first. An 8-yr head-to-head: tight book blew up, wide book profited.
- **One exit engine, everywhere.** A range-sized wide-stop ratchet: SL **40 / 50 / 60 pips** by session swing; trigger **+7.5 → lock +5 → trail 2.5 fixed**; **no timeout**. Brackets removed so runners can express. ([B-090](docs/BOOK_OF_BUGS.md) killed an ATR-scaled trail that gave green back as red.)
- **Portfolio caps are risk only, no alpha:** `max_concurrent = 4`, `max_per_currency_direction = 4`.

## The pipeline

```mermaid
flowchart LR
    A[OANDA feed] --> B{cells<br/>pair × session}
    B -- "validated setup fires" --> C[portfolio caps<br/>risk only]
    B -. "no setup → sit out" .-> Z((flat))
    C --> D[order + server-side wide SL]
    D --> E[range-sized wide-stop ratchet<br/>SL 40/50/60 · +7.5→lock+5→trail 2.5 · no timeout]
    E --> F[broker fills = the only truth]
    F -- "forward tape vs predictions" --> B
    style Z fill:#808a94,stroke:#666,color:#fff
```

*Book today: 29 validated setups across 14 cells — 9 active (● live · ◐ shadow-validating · — dormant, awaiting monthly refit).*

## What we falsified

Five edge families died at the same wall — on retail OANDA majors, no price-*prediction* edge cleared cost — then a sixth move revised the exit itself. Full write-ups: **[docs/papers/PAPER_edge_hunt_falsifications_2026-07-14.md](docs/papers/PAPER_edge_hunt_falsifications_2026-07-14.md)**.

| edge family | verdict |
|---|---|
| M5 scalping | edge ≈ its own transaction cost |
| Single-pair daily trend | a coin flip |
| Diversified retail TSM | real edge, but needs institutional breadth/cheap execution — net Sharpe −0.22 on our venue |
| Symmetric both-sides straddle | you always own the loser |
| Tight-stop-and-reverse | the "asymmetry" was realized direction, not a selectable property |
| **→ the turn** | tighten-to-MAE dial-in was **survivorship-biased** → the wide-stop book |

## The forward test now running

The wide-stop deployment is a **forward experiment on a practice account**, scored weekly against **broker fills** (never our own logs), per class, at n≥20 before any verdict — no aggregate blending across eras. The head-to-head is a selection-biased, no-slippage sim: raw ~Sharpe 1.05 / +25%/yr, honest haircut **~Sharpe 0.6–0.8 with a ~−40% max drawdown** — a low-Sharpe grind, not a jackpot. The trusted part is the *direction* (wide beats tight on the same cells); the level is not a promise. Decisive test still owed: **walk-forward (train 2019–22 / test 2023–26) + slippage haircut**. Details: [docs/RESEARCH_PROGRAM.md](docs/RESEARCH_PROGRAM.md), [docs/ROADMAP.md](docs/ROADMAP.md).

## Read the research

| | |
|---|---|
| 🧭 **[Research Program](docs/RESEARCH_PROGRAM.md)** | **start here** — the falsification method, open questions |
| 📜 **[History V1→V6](docs/SCROOGE_HISTORY.md)** | every version, the edge-hunt arc, the survivorship turn |
| 🐛 **[Book of Bugs](docs/BOOK_OF_BUGS.md)** | B-001→B-090 — every dead end and defect, on purpose |
| 📄 **[Papers index](docs/papers/)** | incl. the [cost-aware exit-classes paper](docs/PAPER_cost_aware_exit_classes_2026-07-05.md) (the chapter the wide-stop turn revised) |
| 🔬 **[Research & data index](research/README.md)** | corpora, retired modules, the strategy graveyard |
| 📦 **[The Archive (Dropbox)](https://www.dropbox.com/scl/fo/uyjwoj274ndzqg98ol72p/AEB6zn4q-jFexhZxVmYFRyc?rlkey=a06ocaqxuyz4at1dfkjmww1i9&st=kup4s0x9&dl=0)** | download the corpora & trained models — test them, modify them, attack them |
| ⚙️ **[Setup](docs/SETUP.md)** | OANDA **practice** account, install, services — **credentials via env vars only** |
| 📊 **Dashboard** | local panel `:8084` — LIVE / TUNE / PLAYMAKER / PAIRS / HEALTH ([docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)) |
| 🤝 **[Contributing](CONTRIBUTING.md)** | external ideas welcome, treated as untrusted input — same falsification gauntlet our own ideas face |
| ⚖️ **[License](LICENSE)** | Apache-2.0 |

*Think we're wrong? Good. [The archive](https://www.dropbox.com/scl/fo/uyjwoj274ndzqg98ol72p/AEB6zn4q-jFexhZxVmYFRyc?rlkey=a06ocaqxuyz4at1dfkjmww1i9&st=kup4s0x9&dl=0) ships the corpora and every retired experiment so you can re-run the analysis and attack the conclusions — leak-checked corpus → walk-forward → fired-trade sim → shadow → capital. Nothing reaches the live path without passing that gauntlet.*

---

> ⚠️ **Research software on an OANDA practice account. Not financial advice. The wide-stop result is a simulation with known inflators and its live verdict is pending. Leveraged forex can lose more than your deposit. If you run this, the outcomes are yours.**
