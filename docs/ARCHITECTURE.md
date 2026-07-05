# Architecture

```
                 ┌────────────────────────────────────────────┐
   OANDA v3 ────▶│ core/feed        MarketView per pair       │
                 └──────────────┬─────────────────────────────┘
                                ▼   every 5 min (scan)
                 ┌────────────────────────────────────────────┐
                 │ modules/cells    (pair × session) setups    │
                 │   config/cells/<PAIR>.json — conditions,    │
                 │   side, lineage, exit class per setup       │
                 └──────────────┬─────────────────────────────┘
                                ▼ CellIntents
                 ┌────────────────────────────────────────────┐
                 │ modules/cells/portfolio  risk caps, no alpha│
                 └──────────────┬─────────────────────────────┘
                                ▼ picked intent(s)
                 ┌────────────────────────────────────────────┐
                 │ core/broker      market order + SL/TP on fill│
                 └──────────────┬─────────────────────────────┘
                                ▼ Position
                 ┌────────────────────────────────────────────┐
                 │ modules/management   every 5 s (manage)     │
                 │  FAST → BracketManager (TP/SL/timeout)      │
                 │  MED/LONG → RatchetManager (engage + ATR    │
                 │  trail) · global rollover freeze 20:55–22:05│
                 └────────────────────────────────────────────┘
   ops/server.py dashboard (:8084) + ops/health.py MODULES tab watch everything
```

Principles: **no strategy layer** (cells + validated setups only) · **broker truth**
(journal logs intent; the broker is the only P/L source) · **cost-aware exits**
(class per cell from measured excursion geometry + transaction costs) · **hot-reload
configs** (cell JSONs, exit, playmaker read per cycle). Per-module detail: [MODULES.md](MODULES.md).
