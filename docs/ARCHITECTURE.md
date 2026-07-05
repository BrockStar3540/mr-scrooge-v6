# Architecture

High-level system diagram + per-component summary. For deep dives on individual modules see the other docs.

## System diagram

```
                ┌─────────────────────────┐
                │  OANDA price feed       │
                │  M5 candles · H1 · D    │
                │  spread · tick volume   │
                └───────────┬─────────────┘
                            │
                            ▼
                ┌─────────────────────────┐
                │  Engine loop            │  scan 300s · manage 30s
                │  builds MarketView      │
                │  per pair               │
                └───────────┬─────────────┘
                            │  24 dir features
                            │  10 mom features
                            │  + aggregators (atr_conc, atr_h1_relative,
                            │    wall_frac, trend_4h, htf_pct_20/60,
                            │    adr_consumed)
                            ▼
              ┌─────────────────────────────────┐
              │  DirectionModule per pair       │
              │  × session × direction          │  48 cells
              │  dual-compute long + short      │
              │  pick stronger |score|          │
              │  → DirectionStamp               │
              └───────────────┬─────────────────┘
                              │  bias · score · certainty
                              ▼
              ┌─────────────────────────────────┐
              │  MomentumModule per pair        │
              │  × session × direction          │  48 cells
              │  per-cell gates + scaler        │
              │  → MomentumStamp                │
              └───────────────┬─────────────────┘
                              │  vol_regime · expected_pips · certainty
                              ▼
              ┌─────────────────────────────────┐
              │  Playmaker                      │
              │  min_direction_score ≥ 0.25     │
              │  min_dir_certainty   ≥ 0.30     │
              │  min_mom_certainty   ≥ 0.25     │
              │  spread cost gate               │
              │  per-pair cooldown + caps       │
              │  → tournament across eligible   │
              └───────────────┬─────────────────┘
                              │  winning PairTicket
                              ▼
              ┌─────────────────────────────────┐
              │  Broker (OANDA)                 │
              │  market order                   │
              │  server-side SL = -20p          │
              │  no TP (ratchet-only)           │
              └───────────────┬─────────────────┘
                              │  trade_id
                              ▼
              ┌─────────────────────────────────┐
              │  RatchetManager (per trade)     │
              │  poll every 30s                 │
              │  step_trigger · trail · size    │
              │  patch OANDA SL on rung trips   │
              │  exit when SL hit               │
              └─────────────────────────────────┘
```

For a more polished visual of the same pipeline with the 48-cell expansion, see the diagram rendered in the project's GitHub social card or run the visualizer in your editor.

## Engine loop cadence

The engine runs two cadences:

- **`_cycle()` every 300s** — full pipeline. Pulls candles, rebuilds MarketView, calls Direction + Momentum modules per pair, runs Playmaker tournament, places order if a winner exists.
- **`_manage()` every 30s** — cheap loop. Checks open trades against OANDA `pricing()`, runs RatchetManager to update SL, detects exits.

`step_cadence_min = 0.5` (in `exit_config.json`) means the ratchet can re-lock every 30 seconds.

## Service + supervision

V5 runs as a systemd user service on EC2: `mr-scrooge-v5.service`. Activated via `systemctl --user`. Restart policy = `on-failure`.

- Service unit: `~/.config/systemd/user/mr-scrooge-v5.service`
- Working dir: `~/mr-scrooge-v5/`
- venv: `~/mr-scrooge-v5/.venv/`
- Entry point: `python -m main` (which loads engine + ops/server)

Two ports:
- `:8084` — primary dashboard (5 tabs: LIVE / PAIRS / TUNE / PLAYMAKER / HEALTH)
- `:8090` — control panel for service ops (start/stop/restart, log tail, deploy git pull + restart)

## Data flow

```
OANDA REST (us-trade vs practice)
   │
   ├─── candles (M5, H1, D)         → engine MarketView build
   ├─── pricing  (bid/ask)          → ratchet poll
   ├─── positions                   → state reconciliation
   ├─── orders   (market + SL)      → broker submit
   └─── transactions                → trade lifecycle log
```

Local state:
```
~/mr-scrooge-v5/
├── config/        live-editable JSON configs (hot-reloaded)
├── data/          factor_sweep.json (D1-D10 per-cell anchor calibration)
└── tests/         smoke + unit
```

Vault state (read-only mirror to Obsidian on EC2):
```
/data/obsidian-vault/wiki/systems/
├── cockpit.md                       routing index, V5 banner
├── quick-status.md                  alerts/positions auto-update 5m
├── service-health-dashboard.md      all machines/services red/green
└── agent-activity-log.md            cross-agent history
```

## Components — one-line each

| Component | File | Purpose |
|---|---|---|
| Engine | `core/engine.py` | Main loop: scan/manage cadence, view build, module orchestration, tournament |
| Broker | `core/broker/oanda.py` | OANDA REST client — orders, pricing, positions |
| Feed | `core/feed/oanda.py` | Candle fetching with retry + rate-limit handling |
| Sessions | `config/sessions.py` | UTC hour → coarse session (asia/london/ny) |
| Direction module v1 | `modules/signals/direction.py` | RETAINED — V5's original per-(pair × session) direction signal; no longer imported |
| Direction module v2 | `modules/signals/direction_v2.py` | LIVE — per-(pair × session × direction), dual-compute |
| Direction profiles | `modules/signals/direction_profiles.py` | 48-cell `PROFILE_ASSIGNMENT` + 3 templates + aggregator rules |
| Momentum module v1 | `modules/signals/momentum.py` | RETAINED — V5's original momentum module; no longer imported |
| Momentum module v2 | `modules/signals/momentum_v2.py` | RETAINED — intermediate per-(pair × session) momentum; superseded by v3 |
| Momentum module v3 | `modules/signals/momentum_v3.py` | LIVE — per-(pair × session × direction), `stamp(view, direction)` |
| Momentum profiles | `modules/signals/momentum_profiles.py` | 48-cell `PROFILE_ASSIGNMENT` + 5 templates + per-pair tuning |
| Playmaker | `modules/playmaker/playmaker.py` | Entry gates + tournament across eligible pairs |
| Ratchet | `modules/management/ratchet.py` | Step-trail SL ratchet, polls OANDA, patches server-side SL |
| Panel | `ops/panel.html` | Dashboard HTML (vanilla JS, polls /api/state every 10s) |
| Server | `ops/server.py` | API + dashboard host on :8084 |

For the per-(pair × session × direction) details of direction_v2 + momentum_v3 see [MODULES.md](MODULES.md).

## Why each layer exists

- **MarketView** decouples feature computation from signal logic. One source of truth per cycle; all modules read from the same numbers.
- **DirectionModule** answers "do conditions favor long or short here?" Outputs a signed bias + score + certainty.
- **MomentumModule** answers "how big a move can we expect and how confident are we?" Outputs expected_pips + certainty.
- **Playmaker** decouples gate logic from signal logic. The same gates apply to every signal; only the inputs change. Tournament across pairs picks the best opportunity per cycle.
- **Broker** isolates OANDA REST quirks (rate limits, retry, ID mapping) from the rest of the system.
- **RatchetManager** runs at a tighter cadence than the entry loop because exits need to react to intra-bar moves.
