# Modules — what runs, where, and why

Current as of V6 (2026-07-05, cell era + cost-aware exit classes). One section per
module; the **health** column names the MODULES-tab check that watches it.

| module | path | responsibility | health check |
|---|---|---|---|
| Feed | `core/feed/oanda.py` | candles (M5/H1), live pricing, spread, session tagging → `MarketView` per pair | `feed.candles` |
| Engine | `core/engine.py` | two-cadence loop: full scan every 5 min (manage → views → cells → portfolio → enter), manage tick every 5 s (exit detection + trail updates); position recovery on restart | `engine.scan_loop`, `engine.manage_loop` |
| Cells | `modules/cells/cell.py`, `pair_module.py` | THE decision layer. Each (pair × session) cell evaluates its setups from `config/cells/<PAIR>.json`: raw-indicator conditions, side, per-setup exit params (resolved ATR trail, bracket TP, entry cutoff). ACTIVE setups emit `CellIntent`; SHADOW setups stamp only | `cells.configs` |
| Portfolio | `modules/cells/portfolio.py` | risk caps only, no alpha: max concurrent, one-per-pair, currency exposure, cooldowns, spread fail-closed gate | (governed via caps; visible in BOOK) |
| Playmaker (remnant) | `modules/playmaker/playmaker.py`, `lock_guard.py` | cell-era leftovers that still serve: `TradeTicket` shape for dashboard/journal, `_MAX_SPREAD` table, session-instance throttles. The signal-scoring role is retired | `playmaker.lock_guard` |
| Exit managers | `modules/management/` | one manager per open trade, selected by the setup's exit class: `bracket.py` (FAST: server-side TP+SL+timeout, no trail, rollover flat) · `ratchet.py` (MEDIUM/LONG: engage threshold + ATR-scaled trail). Global 20:55–22:05 UTC stop-freeze in `base.py` | `exits.managers`, `exits.rollover_freeze` |
| Broker | `core/broker/oanda.py` | market orders with SL/TP on fill, sizing (margin model), stop moves, closes. Credentials from environment only | `broker.api`, `account.margin` |
| Signals (instruments) | `modules/signals/` | falsification instruments, not strategy: `formula_shadow.py` (log-only formula stamps), `calibration.py` (monthly truth-matrix artifact reader) | `signals.formula_shadow`, `calibration.artifact` |
| Dashboard | `ops/server.py`, `ops/panel.html`, `ops/health.py` | `:8084` panel + JSON APIs; MODULES tab = red/yellow/green per subsystem | (self) |

**Data flow, one line:** OANDA → MarketView → each in-session cell evaluates → intents → portfolio caps pick → broker order (SL/TP on fill) → exit manager per class → broker truth for all accounting.

**Retired stacks** (direction_v2/momentum_v3 scoring, inversions, cert composites) live in the V5 repo `modules/archive/signals_legacy/` and the Dropbox graveyard — see `SCROOGE_HISTORY.md`.
