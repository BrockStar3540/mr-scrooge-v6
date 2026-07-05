# Configuration

Two hot-reloaded JSON files drive runtime behavior. Both are read on every engine cycle so changes apply immediately — no restart.

## `config/exit_config.json`

Schema v2 with `defaults` + `per_pair` overrides.

### Knobs

| Field | Type | Current default | Notes |
|---|---|---:|---|
| `initial_sl_pips` | float | 20.0 | SL distance from fill at entry |
| `step_engage_min` | float | 0.0 | Minutes after fill before ratchet logic runs |
| `step_cadence_min` | float | 0.5 | Minimum gap between rung re-locks |
| `step_trigger_pips` | float | 7.5 | Peak MFE required to arm first rung |
| `step_trail_pips` | float | 2.5 | SL parks `peak − trail` when rung arms |
| `step_size_pips` | float | 2.5 | Distance between consecutive rungs |
| `tp1_enabled` | bool | false | Toggle partial close at TP1 |
| `tp1_at_pips` | float | 12.0 | TP1 distance from entry |
| `tp1_close_pct` | float | 0.5 | Fraction of position to close at TP1 |
| `tp1_lock_pips` | float | 6.0 | SL moves to this after TP1 fills |
| `tp2_enabled` | bool | false | Toggle partial close at TP2 |
| `tp2_at_pips` | float | 20.0 | TP2 distance from entry |
| `tp2_close_pct` | float | 0.25 | Fraction of position to close at TP2 |

### Cross-rule validation

When edited via the dashboard TUNE tab, server-side validation enforces:
- `step_trail_pips < step_trigger_pips`
- `tp1_close_pct + tp2_close_pct < 1.0` (when both enabled)
- `tp1_at_pips < tp2_at_pips`
- `tp1_enabled = true` requires `tp1_at_pips > 0`

### Per-pair overrides

```json
{
  "schema": "v2",
  "defaults": { ... },
  "per_pair": {
    "EUR_USD": {
      "initial_sl_pips": 15.0,
      "step_trigger_pips": 6.0
    }
  }
}
```

Per-pair overrides REPLACE the matching `defaults` field for that pair only.

## `config/playmaker_config.json`

Schema v2 with `account_settings` + `defaults` + `per_pair`.

### Account-level knobs

| Field | Type | Purpose |
|---|---|---|
| `account_settings.max_concurrent_positions` | int | Cap across all pairs |
| `account_settings.max_daily_loss_pct` | float | Halt new entries if today's loss > this |
| `account_settings.margin_utilization_max` | float | Don't enter if margin used > this |
| `account_settings.risk_per_trade_pct` | float | Sizing per trade |

### Per-pair defaults

| Field | Type | Default | Notes |
|---|---|---:|---|
| `min_direction_score` | float | 0.25 | Direction-signal floor |
| `min_dir_certainty` | float | 0.30 | Direction-cert floor |
| `min_mom_certainty` | float | 0.25 | Momentum-cert floor |
| `cooldown_minutes` | int | 5 | Gap after last close before re-entering |
| `max_open_positions` | int | 1 | Per-pair concurrent positions |
| `enabled` | bool | true | Hard disable a pair |

### Per-pair overrides

Same shape as exit_config: `per_pair: { "<PAIR>": { ... } }`. Any field present in an override replaces the default for that pair.

## Calibration data — `data/factor_sweep.json`

NOT a config — a calibration data file. Holds D1-D10 per-feature percentile anchors per (pair × session) used by both Direction and Momentum modules for normalization.

- Updated only when a new aggregator sweep is run (currently last: 2026-06-18, on Mini at `/Volumes/Alien Device/scrooge-research/v5_aggregator_test_2026-06-18/`).
- Read on module `__init__`; cached for the life of the process.
- Restart V5 after editing.

If `factor_sweep.json` is absent or a cell is missing, modules fall back to hard-coded `_FALLBACK` anchors. Not catastrophic but less accurate normalization.

## Session boundaries — `config/sessions.py`

Static Python module. Defines UTC hour → coarse session label used by the modules:

```python
def coarse_session(hour_utc: int) -> str:
    if  7 <= hour_utc < 13: return "london"
    if 13 <= hour_utc < 22: return "ny"
    return "asia"
```

Editing this requires a service restart. Sessions are stable enough that this is rare.

## Secrets

NEVER stored in config files or committed to the repo. Loaded from `~/.openclaw/secrets.env` (chmod 600) on EC2 at service start. Includes:
- `OANDA_API_TOKEN`
- `OANDA_ACCOUNT_ID`
- `OANDA_API_URL` (practice vs live endpoint)
- `DROPBOX_REFRESH_TOKEN` + `DROPBOX_APP_KEY` + `DROPBOX_APP_SECRET` (for the nightly backup cron)

If running locally for testing, copy the same file to `~/.openclaw/secrets.env` on your machine.

## Backups before editing

Convention: before any config edit, `cp config/<file>.json config/<file>.json.bak-pre-<changeName>`. Backups eventually get archived; see [../CHANGELOG.md](../CHANGELOG.md) `[2026-06-19] repo cleanup` for the archive pattern.

For live config changes that the engine reads on next cycle, the backup is your only rollback path — there's no other history.
