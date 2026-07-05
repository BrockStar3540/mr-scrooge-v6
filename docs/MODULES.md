# Signal modules — live (v2 direction + v3 momentum)

This doc describes the **live** v2/v3 modules — wired into `modules/signals/__init__.py` as of 2026-06-20. The v1 modules (`direction.py` + `momentum.py`) are retained in the repo as the previous calibration but no longer imported; see [signal-module-spec.md](signal-module-spec.md) for the v1 history.

For the historical reasoning behind why we built these → [EDGE_REPORT.md](EDGE_REPORT.md) and the session research at [../research/sessions/](../research/sessions/).

## Direction module v2

File: `modules/signals/direction_v2.py` + `modules/signals/direction_profiles.py`.

### Architecture

- Each cell is keyed by `(pair × session × direction)` = 48 cells.
- `DirectionModule.__init__(pair, session)` loads **both** the long-side and short-side profile for that cell.
- `DirectionModule.stamp(view)` dual-computes:
  1. Score with the long-profile feature weights
  2. Score with the short-profile feature weights
  3. Pick whichever has stronger `|score|`
- DirectionStamp shape is unchanged (bias / score / certainty / reads) so the Playmaker doesn't need to change.

### Cell assignment

| Profile | Cells | Distribution |
|---|---:|---|
| `continuation_strong` | 14 | mostly asia/JPY long+short, NY USD/JPY |
| `reversion` | 10 | NY non-JPY, EUR_JPY/london |
| `default` (V5 v1 unchanged) | 24 | cells without per-direction live evidence |

`continuation_strong` boosts h1_ret_1bar, trend_4h, HTF features; halves PDL; reduces reversion family. `reversion` boosts mean-reversion family 2-4×; reduces trend/HTF/PDH/PDL.

### Aggregator amplifier rules

Apply across all profiles after the base weights are loaded:

| Condition | Effect |
|---|---|
| `atr_conc > 2.5` | HTF + structural features × 1.5 |
| `atr_h1_relative > 1.6` | Reversion family × 1.3 |
| `atr_h1_relative > 1.6` | HTF/continuation features × 0.5 |

Weights re-normalize after rules so `\|total\|` = 1.

### Reads payload

In addition to the standard reads, v2 emits:
- `long_score` and `short_score` (both raw, signed)
- `active_side` — which side won the dual-compute
- `long_profile` and `short_profile` — names + evidence tags for both

Useful for shadow-mode debugging when you want to see what the not-chosen side would have said.

## Momentum module v3

File: `modules/signals/momentum_v3.py` + `modules/signals/momentum_profiles.py`.

### Architecture

- Each cell is keyed by `(pair × session × direction)` = 48 cells.
- `MomentumModule.__init__(pair, session)` loads per-pair tuning constants.
- `MomentumModule.stamp(view, direction)` requires the `direction` argument from the caller (engine flow: `direction_stamp = direction.stamp(view); momentum_stamp = momentum.stamp(view, direction_stamp.bias)`).
- When the (pair, session, direction) profile's gates fail, `certainty = 0.0` is emitted and the existing Playmaker `min_mom_certainty = 0.25` floor rejects the entry automatically. **No Playmaker code changes to activate.**

### Profile templates

| Profile | Used when | Gates |
|---|---|---|
| `asia_volume_rev` | Asia cells with evidence | `rvol_5bar ≥ floor` AND `\|h1_ret_1bar\| ≥ floor` AND `adr_consumed ≤ ceiling`. Reversion confirm (h1_ret opposite of trend_4h) gives a cert boost. |
| `london_exhaustion` | London cells | `adr_consumed ≤ 1.20` AND `atr_conc ≥ floor` AND `\|h1_ret_1bar\| ≥ floor`. |
| `ny_volatility` | NY cells with evidence | `atr_conc ≥ floor` AND `atr_5m ≥ 2.5p` AND `\|h1_ret_1bar\| ≥ floor` AND `rvol_5bar ≤ 1.5`. Continuation confirm (h1_ret same sign as trend_4h) boosts cert. |
| `ny_volatility_strict` | NY cells with BAD evidence | Same as `ny_volatility` but 1.5× floors. |
| `default` | NO_DATA cells | V5 v1 behavior unchanged. |

Distribution: 30 default, 7 london_exhaustion, 4 asia_volume_rev, 4 ny_volatility, 3 ny_volatility_strict.

### Per-pair tuning

Same profile, different constants per pair. Example for `asia_volume_rev`:

| Pair | h1_ret floor | rvol floor | expected_pips scaler |
|---|---:|---:|---:|
| AUD_JPY | 2.0p | 1.0 | 0.25 |
| USD_JPY | 3.0p | 1.2 | 0.30 |
| AUD_USD | 2.0p | 1.0 | 0.30 |

Pair tuning lives in `momentum_profiles.PAIR_TUNING`.

### Evidence-strictness multiplier

Layered on top of per-pair tuning. Each cell carries an evidence tag (STRONG / MEDIUM / MEDIUM_STRICT / WEAK / BAD / NO_DATA). Multipliers:

| Evidence | Floor multiplier |
|---|---:|
| STRONG | 1.00× |
| MEDIUM | 1.10× |
| MEDIUM_STRICT | 1.20× |
| WEAK | 1.20× |
| BAD | 1.40× |
| NO_DATA | 1.00× (paired with `default` profile → V5 v1 behavior) |

A BAD-evidence cell on `ny_volatility_strict` runs with effective floors of `base × 1.5 × 1.4` = 2.1× the baseline — designed to filter out the no-momentum entries the live evidence showed losing.

### Chaos veto

`atr_conc ≥ 15` → `certainty = 0` regardless of profile. Carried over from v1 — extreme atr_conc means the bar is in a degenerate volatility regime that doesn't predict well.

### `wall_frac` amplifier

When the cell's gates pass AND `wall_frac > 5.0`, `expected_pips` is boosted × 1.3. Live evidence from yesterday's smoke v3 found wall_frac correlates +0.95 with `pip_high` in 3 of 5 multi-trade cells.

## How direction + momentum flow together

```python
def evaluate_pair(pair, session, view):
    d_stamp = direction_v2.stamp(view)
    if d_stamp.bias == "block":
        return None
    m_stamp = momentum_v3.stamp(view, d_stamp.bias)
    return PairTicket(direction=d_stamp, momentum=m_stamp)
```

The Playmaker then applies its `min_*` gates and runs the tournament. See [PLAYMAKER.md](PLAYMAKER.md) for the gate semantics.

## Cell coverage matrix

For an at-a-glance view of which cells have non-default profiles in each module:

| | Asia long | Asia short | London long | London short | NY long | NY short |
|---|:-:|:-:|:-:|:-:|:-:|:-:|
| AUD_JPY | def | cont-S STR | rev BAD | def WEAK | cont-S MOD | cont-S MOD |
| AUD_USD | def | cont-S MED | def | def | rev WEAK | rev WEAK |
| EUR_JPY | cont-S MOD | cont-S MOD | rev WEAK | rev BAD | cont-S WEAK | def |
| EUR_USD | def | def | def | rev MED | def | rev STR |
| GBP_USD | def | def | cont-S MED | cont-S STR | def | rev STR |
| USD_CAD | def | def | def | def | rev MOD | def |
| USD_CHF | def | def | cont-S MOD | def | rev MOD | def |
| USD_JPY | cont-S WEAK | cont-S MEDSTR | def | def | cont-S WEAK | cont-S WEAK |

(cells show direction-module profile assignment; momentum-module assignment is parallel — see `momentum_profiles.PROFILE_ASSIGNMENT`.)

## Testing

Module tests live in `modules/signals/`:

- `test_per_direction.py` — six smoke tests covering 48-cell coverage, dual-compute, per-direction differentiation, chaos veto, evidence-strictness
- `test_momentum_v3.py` — momentum-only smoke tests
- `test_modules_smoke.py` — v2 staging smoke

Run all:
```bash
cd modules/signals
python3 test_per_direction.py
python3 test_momentum_v3.py
python3 test_modules_smoke.py
```

## What's NOT yet built

- Per-(pair × session × direction) **calibration anchors**. The D1/D10 normalization anchors in `factor_sweep.json` are per-(pair × session) only. Adding a direction axis to the anchors would require re-running the aggregator sweep with the long/short split — a Mini compute job, not yet scheduled.
- Per-direction `expected_pips` calibration. Currently the scaler is per-pair only.
- Aggregator amplifier rules that are direction-aware. Currently the 3 rules apply symmetrically.

These are tracked in [ROADMAP.md](ROADMAP.md).
