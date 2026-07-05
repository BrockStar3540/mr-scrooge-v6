# Playmaker — entry gating

The Playmaker is the entry-side decision layer. It takes per-pair direction + momentum stamps and decides:

1. Does each pair pass the cert + score + spread gates? → filter to eligible
2. If any are eligible, which one wins the tournament? → highest `|composite_score|`, breaking ties by `expected_pips`
3. Emit the winner as a PairTicket for the broker.

The Playmaker code lives at `modules/playmaker/playmaker.py`.

## Per-pair eligibility gates

A pair is eligible to trade if **all** of:

| Gate | Floor | Source |
|---|---:|---|
| `min_direction_score` | 0.25 | `playmaker_config.json` defaults |
| `min_dir_certainty` | 0.30 | `playmaker_config.json` defaults |
| `min_mom_certainty` | 0.25 | `playmaker_config.json` defaults |
| spread cost gate | spread < expected_pips × 0.25 | hard-coded |
| per-pair cooldown | last close was ≥ N minutes ago | `playmaker_config.json` per-pair |
| per-pair caps | open positions on this pair < cap | `playmaker_config.json` per-pair |
| account state | balance + margin allow new position | OANDA `account()` |

Per-pair overrides in `playmaker_config.json` look like:
```json
{
  "per_pair": {
    "EUR_USD": {
      "min_direction_score": 0.30,
      "cooldown_minutes": 15
    }
  }
}
```

If a per-pair override exists, it replaces the default for that pair only.

## Tournament

Among eligible pairs:

- **Primary rank**: `|composite_score|` = `|direction.score × dir_certainty × mom_certainty|`
- **Secondary rank** (ties): `expected_pips` from the momentum stamp

The highest-ranked pair wins. The PairTicket has `composite_score`, `dir_certainty`, `mom_certainty`, `expected_pips`, `vol_regime`, and `rivals` (number of other eligible pairs this cycle).

The Playmaker logs the chosen winner as:
```
SIGNAL <pair> <dir> | score=<composite> d_cert=<X> m_cert=<Y> expected=<Z>p vol=<regime> rivals=<N>
```

## How v2/v3 modules interact with the gates

When the v2/v3 modules activate, their per-cell gates are **upstream** of the Playmaker. The flow becomes:

1. `direction_v2.stamp(view)` dual-computes and emits a `DirectionStamp`. If the cell has weak conviction or aggregator-rules pull the score toward zero, the bias may be `block` (|score| < 0.15) — and the pair is filtered out before the Playmaker sees it.

2. `momentum_v3.stamp(view, direction)` looks up the (pair, session, direction) cell. If the per-cell gates fail (e.g., `rvol_5bar < floor`), the module emits `certainty = 0.0`. The Playmaker's existing `min_mom_certainty ≥ 0.25` floor then rejects the pair.

So **no Playmaker code change is needed** to activate v3 — the cell-level gating happens in the module and the Playmaker just sees a low certainty.

## Why the gates exist

| Gate | What it filters |
|---|---|
| `min_direction_score` | Pairs where direction is too weak to bet on |
| `min_dir_certainty` | Pairs where the direction signal has low agreement among features |
| `min_mom_certainty` | Pairs where the volatility regime is ambiguous or `expected_pips` is unreliable |
| spread cost | Trades where spread eats more than 25% of expected move |
| cooldown | Don't immediately re-enter after closing on same pair |
| per-pair caps | Don't pyramid into a single pair |
| account state | Don't trade when margin / balance won't support it |

## What if no pair passes the gates?

The cycle ends with no SIGNAL line logged. The engine waits for the next `_cycle()` (300s later). No order is placed.

## Editing safely

`playmaker_config.json` is hot-reloaded. Two paths:

- **PLAYMAKER tab** on the dashboard — guarded edits with cross-rule validation.
- **Direct JSON edit** — faster for scripting, no validation.

Convention is to bump `min_direction_score` or `min_mom_certainty` if the bot is firing too freely; lower them if the bot is too quiet.

## Reads / observability

Every cycle that finds at least one eligible pair logs a SIGNAL line. Cycles where no pair passes the gates are silent (by design — log noise reduction).

The CANDIDATES tab on the dashboard shows, for each pair this cycle, the score, certainties, expected_pips, and which gates passed/failed. Useful for debugging "why did the bot pick X over Y."

## Account-level safety

Account-level concerns (margin, balance, daily loss cap) are checked at the top of `playmaker.evaluate()`. If they fail, no pair is eligible regardless of signal strength. See `playmaker_config.json` `account_settings` for the per-account knobs.
