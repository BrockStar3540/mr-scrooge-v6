# The Bar Governor — autonomous promote & demote

**What it is:** the closing loop of the trial system. Every strategy setup in this bot runs
as a **shadow** first — stamped on live markets, scored on the forward price path, ranked on
the Shadowboard. The Bar Governor (`ops/governor.py`) is the daemon that acts on that
evidence: an enabled admission lane can move a shadow to a reduced-risk **PROBE**;
completed broker family cycles then graduate it to ACTIVE or demote it to SHADOW.
It runs every SIX HOURS (00:35/06:35/12:35/18:35 UTC). Humans set the standard and
commission admission lanes; the bot applies it.

## The standard (what it's tuned to)

All evidence is **current-era** (see *Era clocks* below) and **config-side only** — a
setup's retired or mirrored direction can never affect its own verdict.

Since **D-7 (2026-07-28)** the promotion sample counts only
**executable-exit-v2** episodes — stamped executable entry (ask long / bid
short), bid/ask forward path, the setup's *own* exit geometry simulated
worst-case intrabar, mechanics-hash-matched to the current config. The old
legacy-mid-v1 mid-drift tape remains on the board as research context but
never governs capital.

| Switch | Fires when |
|---|---|
| **ADMIT (Cheater v4 — separate opt-in, default OFF)** SHADOW → PROBE | Independently qualify PARENT_ONLY and FAMILY_PP on complete virtual family cycles: ≥ **+1.25R** covered gain, ≥ **3 resolved cycles / 2 days**, ≥2 positive cycles, ≤60% single-cycle gain share, coverage ≥1.20. Missing or censored replay vetoes admission. FAMILY_PP additionally needs ≥3 paired cycles with **GridLift LCB90 > 0**. One 0.33× whole-family seat maximum. |
| **ADMIT (ordinary lane — ON since 2026-08-03, operator decision)** SHADOW → PROBE | The D-7 parent/horizon predicate at the operator bar: **n ≥ 10 era v2 episodes / ≥ 5 independent day-blocks**, avg ≥ +2.0p, block LCB > 0, BH-FDR q ≤ 0.05. All admissions land on a 0.33× PROBE, max 2 per run, one seat per (pair, side) cluster. |
| **TRUTH-CHECK GATE (2026-08-04, operator)** | A shadow whose **virtual family-cycle** sign (parent + popper grid replayed over real M5 bid/ask candles, `data/virtual_cycles.json`, 6h batch) **contradicts its own broker fills** (full window — era resets never erase real fills) cannot promote: proven-wrong sim never spends money. Ledger action `PROMOTE-GATED-TRUTH`; the board mirrors it as **TRUTH BLOCKED** and a ❌ badge. Measured basis: parent/horizon sim agreed with broker sign 3/10, virtual family 5/10 — contradictions are flagged and gated, never averaged away. |
| **THREE-STRIKES RULE (2026-08-03, operator)** | Every executed demotion is a **permanent strike** (`governor_state.demotion_counts`, 🔻 badge per strike on the dashboard, forever). An ever-demoted cell re-promotes only over the **redemption bar: n ≥ 20 / days ≥ 10** — the relaxed bar is for first offenders only. The **3rd strike retires the cell to DISABLED**: untouchable by every automation, manual re-enable only. |
| **GRADUATE** PROBE → ACTIVE | ≥6 completed broker family cycles with positive family edge LCB. |
| **DEMOTE** ACTIVE/PROBE → SHADOW | Completed broker family cycles are the unit: net ≤−60p after ≥2 cycles, or one catastrophic cycle ≤−90p. A seat defends at ≥3 cycles and ≥+60p. Cheater PROBE adds a fast leash: one ≤−45p cycle, cumulative loss after 2, or two consecutive red cycles. Judge-when-flat always applies. |

Why these numbers: the measured retail execution toll on majors is ~0.4–0.5 pips per round
trip, and six of seven edge families this program falsified died at exactly that wall — so
any claimed edge under ~1 pip is indistinguishable from zero. **+2.0 pips/episode** is the
margin at which an edge is distinguishable from the toll; **n ≥ 20** is where a per-setup
average starts to mean something; the **LCB > 0** requirement stops a lucky low-variance
streak from sneaking over the bar; and the **7-day check** stops a decaying setup from being
promoted on the strength of its own past.

Demotion runs on **family accounting** (Brock, 2026-07-28: "net loss is the key"). The
7/16→7/28 forward test showed per-leg views mislead in both directions: one family's parents
looked red (−$74) inside a +$718 family, while the book's one true loser hid a −$858 family
behind a 2-trade parent leg — invisible to a parents-only fills rule. So every popper fill now
carries its parent's setup id (`psu` in client extensions; older fills join via the grid
anchor = parent entry price), `research/tools/broker_setup_audit.py` aggregates the
**families** view, and the governor convicts or defends on the family's era net pips —
spread, slippage, manual closes and the live exit all included, because it IS the broker
record. Stamps still decide promotion and still demote setups with no family record.

## The statistics (D-6 → D-7, 2026-07-28)

All decision statistics live in **one shared engine**
(`core/trial_evidence.py`) consumed by the governor *and* the Shadowboard —
the dashboard trophy and a promotion are the same test, so the board can
never award what the governor would reject.

- **Net-of-cost utility (D-6).** Legacy stamps are haircut by their stamped
  entry-time spread plus a slippage constant (`slippage_pips`, default 0.5).
  v2 episodes already *paid* the spread inside their executable geometry, so
  only slippage is deducted (`core.trial_stats.episode_net`) — no
  double-charging, no free rides. "+2.0 pips/episode" means +2 **after** the
  toll, literally, under both metrics.
- **Day/session block bootstrap (D-7).** Episodes cluster within a session's
  day, so the promotion denominator is the number of independent
  `YYYY-MM-DD|session` blocks, not the episode count. The lower confidence
  bound and p-value come from resampling whole blocks (10,000 reps,
  deterministic seed from the block ids — identical evidence always yields
  identical bounds). The old gap-weighted `n_eff` survives as a display
  diagnostic only.
- **Benjamini–Hochberg FDR (D-7).** With ~150 hypotheses live, per-test
  bounds are a false-discovery machine. Each run computes BH q-values across
  the entire candidate docket; promotion requires **q ≤ 0.05**. The
  hypothesis registry (`data/hypothesis_registry.json`) documents everything
  ever examined.
- **Sequential-peeking guard (D-7).** A setup that fails the bar is not
  re-tested until it has at least one *new* independent block
  (`last_eval_blocks` in governor state) — daily re-rolls of unchanged
  evidence can't fish their way over the line. The counter clears on any
  flip (fresh era).
- **Metric-version isolation (D-7).** Parent/horizon evidence never mixes metric
  versions: v2 episodes only, mechanics-hash-matched. The migration was ledgered
  as one `METRIC-ERA-RESET` per live setup. That historical admission lane is now
  diagnostic-only by default (`allow_promotions: false`); Cheater v4 reads raw
  era-clocked episodes and performs its own family replay. Demotions run every
  six hours regardless.

**Era clocks got stricter too:** any change to a setup's *mechanics*
(conditions, exit, side, sizing, horizon — prose excluded) resets its
evidence clock automatically via config-hash comparison, ledgered as
`ERA-RESET`. Manual dashboard tuning counts; nothing trades on stale proof.

## The rails

- **DISABLED is sacred**: a manually disabled setup is untouchable by every automation —
  the bar, the cheater rule, the counterpart audit, all of it. The governor skips
  non-ACTIVE/PROBE/SHADOW statuses AND re-checks the live status at flip time, so disabling a
  cell mid-run can never be overridden by a stale snapshot. Only a human re-enables.
- **Cheater commissioning cap is one PROBE seat**; max 4 demotions per run.
- **No grid crosses a governance era.** A transition quiesces new fires, retires the
  exact flat grid, establishes PP_ON/PARENT_ONLY, and only then changes status. Busy or
  ambiguously-owned legacy grids remain quiesced and block the flip.
- **Sides are never flipped.** A losing direction gets a *counterpart* setup (own name, own
  record) via the daily MAE-flip counterpart audit — never an in-place inversion.
- **DISABLED setups and setups marked `"manual_only": true`** in `config/cells/` are never
  touched.
- All flips go through the dashboard's own validated status writer (hot-reloaded,
  journaled) — the governor has no private write path.
- **Demotion is cheap by design**: a demoted setup keeps stamping as a shadow at zero cost
  and can re-earn the seat through the same bar.

## Era clocks — evidence never blends across eras

Every flip (and every first sighting of a setup) restarts that setup's **evidence clock**,
kept in `data/governor_state.json`. Episodes stamped before the clock don't count. This is
a hard lesson encoded: exit-gear changes and config cutovers change what a setup *is*, and
judging today's configuration by last month's tape is how survivorship sneaks back in. A
promotion earned in one era must be re-earned if the configuration changes.

## The ledger

Every decision — including dry-runs — is appended to **`data/governor_ledger.jsonl`** with
its full evidence string (era n, average, LCB, 7-day window, fills record). The Shadowboard
card shows the most recent decisions. If you're wondering *why* a setup moved, the ledger is
the answer; there is no undisclosed judgment.

## The ON/OFF switch

The **SHADOW tab** of the dashboard carries the toggle
(`AUTO-PROMOTE/DEMOTE: ON/OFF`). OFF means the book only changes by hand — stamping,
scoring, and the Shadowboard all keep running, but no statuses move. The switch writes
`"enabled"` in `config/governor_config.json`; the same file holds every tuning knob:

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | master switch (also on the dashboard) |
| `allow_promotions` / `allow_demotions` | `false` / `true` | ordinary admission / demotion switches (shipped config: `true` / `true` since 2026-08-03) |
| `redemption_min_raw_episodes` / `redemption_min_independent_days` | `20` / `10` | the stricter counting bar for ever-demoted cells |
| `strike_disable_count` | `3` | the strike that permanently DISABLEs the cell |
| `truth_check_gate` | `true` | block promotion when virtual family sign contradicts the cell's broker fills |
| `cheater_promotion_enabled` | `false` | separate Cheater v4 admission switch |
| `cheater_max_seats` | `1` | maximum simultaneous PROBE seats; any current PROBE consumes the slot so a lost auxiliary registry cannot bypass the cap |
| `cheater_replay_days` | `8.0` | replay window (at least live 7-day grid age + one day) |
| `cheater_min_paired_cycles` / `cheater_min_grid_lift_lcb` | `3` / `0.0` | PP_ON incremental-edge proof |
| `min_raw_episodes` | `20` | minimum era v2 episodes (`bar_n` honored as a deprecated alias; shipped config: `10` since 2026-08-03) |
| `min_independent_days` | `10` | minimum independent day/session blocks (shipped config: `5` since 2026-08-03) |
| `bar_avg` | `2.0` | net pips/episode bar |
| `lcb_min` | `0.0` | required block-bootstrap lower bound to promote |
| `bootstrap_reps` / `bootstrap_confidence` | `10000` / `0.95` | block bootstrap settings |
| `fdr_q` | `0.05` | Benjamini–Hochberg q-value ceiling across the docket |
| `recent_n` / `recent_min` | `5` / `0.0` | the 7-day guard |
| `family_min_cycles` / `family_defend_cycles` | `2` / `3` | completed broker-cycle conviction / defense floors |
| `family_demote_pips` | `-60.0` | family era net pips at/below this → demote + poppers off |
| `family_defend_pips` | `60.0` | family era net pips at/above this → seat safe from bar_lost |
| `max_promotions` / `max_demotions` | `2` / `4` | per-run rails |
| `slippage_pips` | `0.5` | slippage haircut per episode |
| `per_test_z` | `2.33` | legacy-display LCB only — **not** a promotion input since D-7 |
| `default_era_start` | *(era anchor)* | evidence floor for setups with no recorded clock |

### Safe commissioning dry-run

`python ops/governor.py --dry-run --cheater-diagnostic` evaluates the entire raw
Cheater candidate docket even while both admission switches are OFF. It prints each
policy verdict and a qualified/declined summary, never queues a status flip, and refuses
to run without `--dry-run`. Use `--cheater-diagnostic-limit N` for a bounded smoke test.

## Context

The governor automates the **activation bar** doctrine (2026-07-22) that was previously
applied by hand — see [RESEARCH_PROGRAM.md](RESEARCH_PROGRAM.md) for the doctrine's history
and [the README's trial-system section](../README.md) for where this sits in the pipeline.
Manual rulings remain possible at any time through the same dashboard controls; the governor
simply makes the default path evidence-driven rather than attention-driven.

> ⚠️ Research software on an OANDA practice account. The governor promotes to live *practice*
> trading; nothing here is financial advice.
