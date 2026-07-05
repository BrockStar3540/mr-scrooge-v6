# V5 Cellular Architecture — Phase A Specification
**2026-07-04 · APPROVED DIRECTION (Brock: "phase A, no side, go for it") · implements docs/CELL_ARCHITECTURE_PLAN.md**

---

## 1. CellModule interface (frozen)

One CellModule instance per (pair × session). A cell may define setups for one side, both
sides, or none. The engine calls exactly one method per scan cycle per active session:

```python
class CellModule:
    def __init__(self, pair: str, session: str, config: dict): ...
    def evaluate(self, view: MarketView, now: datetime) -> CellIntent | None
```

`CellIntent` (returned only when a setup fully qualifies; None otherwise — silence is the
default state of a cell):

```python
@dataclass
class CellIntent:
    pair: str; session: str
    side: str                  # "long" | "short" — from the qualifying setup, never guessed
    setup_id: str              # which setup fired (config key) — logged on every trade
    horizon_min: int           # the setup's evaluation horizon (20/30/60/240)
    exit_params: ExitParams    # SL / trigger / trail from the setup's exit block
    units_hint: float          # risk-normalized size incl. any size_modulator effect
    conds_snapshot: dict       # feature values at qualification (for stamps/audit)
    expected: dict             # {ev_seq, wr, lineage} from config (for logs/scoring)
```

Rules:
- A cell with `setups: []` (NO-SIDE) never returns an intent. It still stamps (see §6).
- No cell reads another cell's state. No cell reads module-level composites (d_cert/m_cert
  are retired vocabulary).
- All thresholds resolve at evaluate-time from the loaded config (hot-reload by mtime check
  once per cycle, same pattern as _pm_load).

## 2. Cell config schema

One file per pair: `config/cells/<PAIR>.json`. Top-level: `{"pair", "generated", "generator",
"sessions": {"asia": CELLCFG, "london": CELLCFG, "ny": CELLCFG}}`. A session absent or with
`"enabled": false` = session gate closed (replaces PAIR_SESSIONS).

```jsonc
CELLCFG = {
  "enabled": true,
  "structure": {                    // from the truth-matrix tiering — informational + guard
    "tier": 1,                      // 1 gross-breakeven / 2 middling / 3 unharvestable
    "rh_offer_rate_60m": 0.34,      // RANGE_HARVEST base rates by horizon
    "dead_rate_60m": 0.30,
    "lineage": "truth-matrix-2026-07"
  },
  "setups": [                       // ZERO OR MORE. Empty = NO-SIDE cell.
    {
      "id": "rvol_low_240",         // unique within cell
      "side": "long",               // REQUIRED — the setup IS sided (Brock: no-side rule)
      "class": "FORMULA",           // FORMULA | LEAN | TIMING (provenance class)
      "status": "ACTIVE",           // ACTIVE | SHADOW (stamps only) | SUSPENDED (tripped)
      "horizon_min": 240,
      "conditions": [               // ALL must pass; ranges only, never point values
        {"feature": "rvol_5bar", "min": null, "max": null,          // absolute form, OR:
         "pct_window_days": 90, "pct_lo": 4.8, "pct_hi": 25.2,      // rolling-percentile form
         "resolved": [0.670, 0.862], "resolved_at": "2026-07-04"}   // generator writes these
      ],
      "exit": {"sl_pips": 12.0, "trigger_pips": 10.0, "trail_pips": 1.5},
      "sizing": {"risk_pct": 0.5,                                    // of balance, risk-normalized:
                 "size_modulators": [                                // multiply units, never side
                   {"feature": "atr_h1_relative", "gte": 0.954, "mult": 1.5,
                    "lineage": "regime-edges-2026-07 (+2.08 vs +0.21)"}]},
      "tripwires": {
        "monthly": {"metric": "atr_h1_relative_monthly_mean", "gte": null,  // null = size-only
                    "action": "size_down"},
        "fast": {"last_n": 20, "min_ev": -0.5, "action": "suspend"}},       // from live stamps
      "evidence": {"ev_seq": 0.35, "oos_years_positive": 7, "drift": "STABLE",
                   "source": "formula-history-2026-07-04", "n_floor_status": "deep-oos-passed"}
    }
  ],
  "notes": "free text — audit trail"
}
```

Schema rules:
- **Every threshold carries lineage.** A value without `evidence`/`lineage` fails config
  validation (the generator enforces; hand edits must include it).
- **Percentile-form is canonical** for any condition whose study showed regime drift; the
  monthly generator re-resolves `resolved` values; the engine reads only `resolved`.
- **Side is per-setup, not per-cell** — a cell may hold a long setup and a short setup
  (e.g. AUD_USD/london both sides per broker record).
- `status: "SHADOW"` setups evaluate and stamp but never return intents — the promotion
  path for every new setup (log-first, always).

## 3. Side policy (Brock-approved: NO-SIDE)

- FORMULA setups: side stated by the validated formula. (GBP_USD/london long-240 today.)
- LEAN setups: side from the cell's PERSISTENT lean, entered only when the lean's feature
  confirms within its configured range. (Candidates: USD_JPY/london via atr_h1_relative,
  AUD_USD/london via vwap_dist once fed.)
- **Cells with neither: `setups: []` → the cell does not trade.** No composite scores, no
  tiebreakers, no coin-flips. Expected initial book: ~1/3 of cells NO-SIDE — they remain in
  the monthly discovery loop, which is the only path back to ACTIVE (a discovered setup
  enters as SHADOW, earns ACTIVE via the gauntlet).

## 4. Engine flow (Phase C implements)

```
per scan cycle:
  views = feed.get_views(active_pairs)
  intents = []
  for pair_module in pairs:                    # session gate inside
      for cell in pair_module.active_cells(now):
          intent = cell.evaluate(view, now)    # SHADOW setups stamp here too
          if intent: intents.append(intent)
  portfolio.select(intents, open_positions)    # caps: max_concurrent, per-currency-dir,
                                               # one-per-pair, spread sanity; NO alpha logic
  → broker.place(intent, exit_params from intent)   # per-trade exit params (ratchet reads
                                               # the trade's own SL/trigger/trail)
```

Portfolio layer keeps ONLY risk arithmetic. If two intents survive caps, prefer higher
`expected.ev_seq` (measured, not scored). RatchetManager: mechanics unchanged; parameters
come from the trade, not from a global config (exit_config.json retires at cutover;
Position gains `exit_params`).

## 5. What retires at cutover (Phase D)

direction_v2, momentum_v3, direction_profiles, momentum_profiles, profile_shadow →
`modules/archive/` (importable; replay tooling may still use them). factor_sweep.json →
archived with them. Playmaker's per_cell_* gate dicts, inverted_live_cells,
inverted_live_directions, disabled_cells, PAIR_SESSIONS → all dissolve into cell configs
(the generator writes the equivalents; a migration script produces the v1 configs and a
side-by-side diff for review). exit_config.json → per-setup exit blocks. locked_cells.json
→ `priority_analysis` flags inside cell notes + the snapshot/audit tooling repurposed for
cell-config change tracking.

## 6. Instrumentation contract (unchanged culture, new labels)

- Every evaluate() emits nothing on silence; qualifying SHADOW setups emit
  `CELLSHADOW <pair>/<session> setup=<id> side=<s> conds=<snapshot>`; ACTIVE qualifications
  that lose portfolio selection emit `CELLSKIP` with the reason (cap type).
- Every placed trade logs `setup_id` + `engine=cell_v1` — era separation forever.
- Scorers: one generic `cell_setup_score.py` replaces formula_shadow_score (reads
  CELLSHADOW + trade outcomes per setup_id; PRIMARY/SHADOW reported separately).
- CAL continues unchanged (distance-estimator comparison is orthogonal).

## 7. Initial book (Phase B generates; preview from current evidence)

- ACTIVE: GBP_USD/london `rvol_low_240` long (the §2 example — sole deep-validated setup).
- SHADOW: per-cell 20/30m TIMING setups (atr_5m band, side from lean where a lean exists)
  in Tier-1/2 lean-cells; AUD_JPY/ny short-240 regime setup (also requires session-enable);
  CONTROL formulas continue as SHADOW with negative expectations (falsification stamps).
- NO-SIDE: the ~20 lean-less/formula-less cells + all Tier-3 cells (their configs carry the
  structural evidence in `notes`).
- Pending phase-A output: the 4 cert-gate cells' re-derivation verdicts decide whether
  their historical edges re-enter as raw-condition LEAN setups or the cells open as NO-SIDE.

## 8. Acceptance criteria for Phase A→B handoff

1. This spec committed + Brock-reviewed.
2. Schema validated by 3 hand-written example configs (formula cell, lean cell, NO-SIDE
   cell) that a reference validator script accepts.
3. Cert-gate re-derivation report delivered with per-cell verdicts.
4. Phase B ticket: extend v5_monthly_refit.sh to emit config/cells/*.json per this schema.
