# Ratchet exit

> **V6 status (2026-07-05):** the ratchet is now ONE OF THREE exit classes —
> FAST cells use `bracket.py` (server-side TP, no trail) and only MEDIUM/LONG
> cells run this ratchet, with per-setup overrides (`trigger`=engage, ATR-scaled
> trail) from the cell configs. The V4-ported TP1/TP2 partial-close ladder was
> REMOVED at the V6 port (never enabled live). Global rollover stop-freeze
> 20:55–22:05 UTC applies. Full derivation: [PAPER_cost_aware_exit_classes_2026-07-05.md](PAPER_cost_aware_exit_classes_2026-07-05.md).

V5 uses a single ratchet-only exit. No TP — wins ride until the trailing SL hits.

## Live configuration

Held in `config/exit_config.json` (hot-reloaded by the engine, no restart needed). Current values:

| Knob | Value | Meaning |
|---|---:|---|
| `initial_sl_pips` | 20.0 | SL distance from fill at entry |
| `step_engage_min` | 0.0 | Minutes before ratchet logic starts running per trade |
| `step_cadence_min` | 0.5 | Re-evaluate the ratchet every 30 seconds |
| `step_trigger_pips` | 7.5 | Peak MFE in pips required to ARM the first rung |
| `step_trail_pips` | 2.5 | When a rung arms, SL parks at `peak − step_trail_pips` |
| `step_size_pips` | 2.5 | Distance between consecutive rungs |

## How a ratchet plays out

```
Entry — SL = -20p

Peak hits +7.5p  (first rung)
   → SL moves to +5p
Peak hits +10p   (next rung at trigger + 1×size)
   → SL moves to +7.5p
Peak hits +12.5p (next rung)
   → SL moves to +10p
Peak hits +15p
   → SL moves to +12.5p
... continues every +2.5p of new peak
```

If the price then retraces to the locked SL, OANDA fills the close server-side. The engine notices the closed position on next `_manage()` poll and logs `EXIT (server stop hit) <pair> | trade_id=<id> | approx_net=<pips>p`.

If the peak NEVER reaches +7.5p, the SL stays at -20p and the trade either closes at full loss or recovers and arms later.

## Cadence

`_manage()` runs every 30 seconds. Per open trade it:

1. Calls OANDA `pricing()` to get current bid/ask.
2. Computes current pips from entry, updates the per-trade `peak_pips`.
3. If a new rung is reached, computes new SL and patches the server-side stop via `orders/{id}` PATCH.
4. If the server-side SL has been hit since last poll, logs an EXIT and reconciles state.

`step_cadence_min = 0.5` controls the minimum gap between rung re-locks for the same trade. With it at 30s, the ratchet can chase moves bar-by-bar.

## Retune history

See [../CHANGELOG.md](../CHANGELOG.md) for full chronology. Key retunes:

- `[2026-06-19 06:15 UTC]` commit `249f970` — trigger 4.5 → 7.5, trail 1.5 → 2.5, size 5.0 → 2.5. Brock-requested. **Diagnosed same day as the cause of a -612 USD swing**: ~50% of historical winners peak in the +4.5-7.5p zone and now never arm. The launch-week smoke analysis is archived under `/SCROOGE ARCHIVE/session-notes/2026-06-19_*` (indexed in [../research/README.md](../research/README.md) §4). Revert/redesign pending.

- `[2026-06-18 EOD]` — `initial_sl_pips` widened 12 → 20. Trades were hitting -12p stops on noise that would have run to profit; the ratchet was supposed to do the tightening, the initial was over-aggressive.

## Editing safely

Two paths:

**Option 1 — Edit via the dashboard TUNE tab.** Goes through server-side validation (cross-rules: `step_trail < step_trigger`, etc.). Reflects in the running engine within one config-reload cycle.

**Option 2 — Edit the JSON directly on disk.** Faster for scripting. The engine re-reads on every cycle so the change applies next time around. No restart. **But:** no server-side validation. If you typo a value the engine logs an error and falls back to last known-good.

In both cases, always back up the config file before editing — convention is `config/exit_config.json.bak-pre-<changeName>`. Backups eventually get archived (see [../CHANGELOG.md](../CHANGELOG.md) `[2026-06-19] repo cleanup`).

## What the ratchet does NOT do

- **No time-based exit.** A trade can stay open indefinitely if it never trips the SL.
- **No averaging-down or scaling-in.** Each entry is a one-shot trade.
- **No partial closes.** The TP1/TP2 ladder was removed in V6 — winners ride the full position (bake-off verdict, 2026-06-13).
- **No equity-based hard stop.** Account-level safety is the Playmaker's pre-entry concern, not the ratchet's.

## Reads / observability

Per-trade ratchet state is on each `Position`:
- `sl_locked_pips` — current SL distance from entry, negative until first arm
- `peak_pips` — best MFE seen since entry
- `sl_price` — actual SL price at OANDA
- `elapsed_min` — minutes since fill

Visible in `/api/state` and the LIVE tab of the dashboard.

Ratchet arm events log as:
```
RATCHET <pair> | peak=<X>p sl=<Y>p → <new_sl_price> | trade_id=<id>
```

Per-cycle lock heartbeat (when engaged):
```
RATCHET <pair> LOCK | engaged=True floor=<X> peak=<Y> net_pips=<Z>
```

Search journalctl by trade_id to reconstruct any past trade's ratchet history.
