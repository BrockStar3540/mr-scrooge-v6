# Mr. Scrooge V6

An autonomous OANDA forex trading platform with an unusual premise: **it uses no strategy.**

There are no entry "strategies" in the classical sense. The unit of decision is the **cell** — a (currency-pair × trading-session) coordinate. A cell trades only when a *validated setup* qualifies: a set of raw-indicator ranges whose edge survived a research gauntlet (walk-forward corpus validation, broker-fill anchoring, and live shadow evaluation), with full lineage recorded in its config. No validated setup = no trade. Exits are equally evidence-driven: each cell belongs to one of three **cost-aware exit classes** measured from its own excursion geometry and transaction-cost profile.

Why this architecture? Six versions of measurement. The short version: across three independent methods, entry-time features predicted **when** the market would move and **how far** — but never **which way**. Every "strategy" we tested was either a costume over that fact or a casualty of it. The full story: [docs/SCROOGE_HISTORY.md](docs/SCROOGE_HISTORY.md) · every defect we ever documented: [docs/BOOK_OF_BUGS.md](docs/BOOK_OF_BUGS.md) · the research library + archives (corpora, retired modules, old MLs, the strategy encyclopedia and the dead-ends graveyard): **Dropbox master archive** *(link published at launch)*.

> ⚠️ **This is research software for a practice account. Nothing here is financial advice. Forex trading with leverage can lose more than your deposit. If you run this, you own the outcomes.**

## Architecture (one screen)

```
OANDA v3 API ──> core/feed        market views: candles, pricing, spread, session tag
                 core/engine      two-cadence loop: scan (5 min) + manage (5 s)
                 modules/cells    THE decision layer: per-(pair×session) setups from
                                  config/cells/<PAIR>.json  (ranges + lineage + exits)
                 modules/playmaker legacy ticket plumbing + lock-era throttles
                 modules/cells/portfolio.py  risk caps: concurrency, per-pair, spread gate
                 modules/management  exit managers, chosen per setup class:
                    bracket.py    FAST  — server-side TP + SL + timeout, no trail
                    ratchet.py    MEDIUM/LONG — engage threshold + ATR-scaled trail
                 core/broker      order placement (SL/TP on fill), sizing, stop moves
                 ops/server.py    dashboard (:8084): LIVE / PAIRS / BOOK / HEALTH / SYSTEM
```

**The three exit classes** (measured, not designed — see the exit-classes paper in `docs/`): FAST cells (NY-fade sessions) take the quick slice via slippage-proof limit TP at a per-pair cost floor; MEDIUM cells run a spread-aware ratchet that never locks inside the toll; LONG cells (Asia/London extenders) engage late and trail wide. A global stop-freeze covers the daily rollover spread blowout (20:55–22:05 UTC).

## Setup

1. **Python 3.12+**, then `pip install -r requirements.txt`.
2. **Credentials — environment only, never in the repo.** Copy `.env.example` into a chmod-600 secrets file OUTSIDE the repo (we use `~/.openclaw/secrets.env`) and export it in the service environment. The bot reads `OANDA_API_URL`, `OANDA_API_TOKEN`, `OANDA_ACCOUNT_ID`.
3. Start on a **practice account** (`api-fxpractice.oanda.com`). The sizing default commits real margin percentages.
4. Run: `python3 main.py --live` (or install `ops/mr-scrooge-v6.service` as a user systemd unit).
5. Dashboard at `http://localhost:8084` — **MODULES** (module health: red/yellow/green per subsystem — loops, feed, broker, margin, exit-manager coverage, configs, calibration age, host resources), **LIVE** (positions with exit-class chips + management detail + rollover-freeze flag), **PAIRS** (per-pair indicator state), **BOOK** (all 24 cells, setup conditions with live values, class geometry tooltips), **HEALTH/SYSTEM**.

## Docs
[SETUP](docs/SETUP.md) · [ARCHITECTURE](docs/ARCHITECTURE.md) · [MODULES](docs/MODULES.md) · [CONFIGURATION](docs/CONFIGURATION.md) · [RATCHET & exit classes](docs/RATCHET.md) · [DEPLOYMENT](docs/DEPLOYMENT.md) · [AUDIT ledger](docs/AUDIT_TODO.md)

## Reading order for researchers
1. `docs/SCROOGE_HISTORY.md` — versions V1→V6, what each learned, where its remains are archived.
2. `docs/PAPER_cost_aware_exit_classes_2026-07-05.md` — the measurement arc behind the exit book (transaction costs, slippage, conversion, fill probabilities, excursion classes).
3. `research/README.md` — the truth hierarchy + validation protocol every finding must pass.
4. `docs/BOOK_OF_BUGS.md` — institutional memory; read before re-deriving any oddity.
5. `docs/AUDIT_TODO.md` — known cleanup items ported from V5, each gated on a fired-trade simulation.

## Contributing / collaborating
The archive link (corpora, retired modules, session diaries) exists so you can re-run or attack our conclusions. Ground rules: external ideas are welcome and go through the same gauntlet our own research does (leak-clean corpus → walk-forward → fired-trade sim → shadow); nothing merges on backtest enthusiasm alone. License & contribution policy: pending at launch.
