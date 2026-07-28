# The Bar Governor — autonomous promote & demote

**What it is:** the closing loop of the trial system. Every strategy setup in this bot runs
as a **shadow** first — stamped on live markets, scored on the forward price path, ranked on
the Shadowboard. The Bar Governor (`ops/governor.py`) is the daemon that acts on that
evidence: it **promotes** shadows that prove themselves to ACTIVE (live orders), and
**demotes** actives that lose their grip back to SHADOW. No human in the loop. The humans
set the standard; the bot flips the switches.

It runs **daily at 06:35 UTC**, immediately after the nightly scorers and the
[counterpart audit](../research/tools/counterpart_audit.py), and just before the daily
backup snapshots the result.

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
| **PROMOTE** SHADOW → ACTIVE | the full predicate (`core/trial_evidence.promotion_predicate`): raw n ≥ **20** v2 episodes **AND** ≥ **10 independent day/session blocks** **AND** average ≥ **+2.0 pips/episode net** **AND** the day-block **bootstrap** lower confidence bound > **0** **AND** the last-7-days average ≥ 0 (when it has ≥ 5 episodes) **AND** Benjamini–Hochberg **q ≤ 0.05** across the run's whole candidate docket |
| **DEMOTE** ACTIVE → SHADOW | **THE FAMILY RULE** (2026-07-28): the parent setup + the poppers its grid fired are ONE unit in **broker net pips** — family n ≥ 5 at **≤ −60p** (one popper SL) → demoted **and the cell's poppers switched off**; a family at **≥ +60p defends the seat** (broker green outranks the stamp simulator). **Judge-when-flat**: while any family trade is open, no verdict at all — the episode is scored when it completes. Without family evidence: era v2 n ≥ 20 with average < +2.0 (**the bar is lost on stamps**) |

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
- **Metric-version isolation (D-7).** Promotion evidence never mixes metric
  versions: v2 episodes only, mechanics-hash-matched. The migration was
  ledgered as one `METRIC-ERA-RESET` record per live setup on 2026-07-28 —
  every setup's evidence restarted at zero under the new metric. The
  reviewer recommended gating promotions off during the transition; the
  operator ruled promotions **ON** — materially the same outcome, since no
  setup can pass the predicate until its v2 sample accrues, and
  `allow_promotions` remains a one-edit kill switch. Demotions (broker
  fills) run daily regardless.

**Era clocks got stricter too:** any change to a setup's *mechanics*
(conditions, exit, side, sizing, horizon — prose excluded) resets its
evidence clock automatically via config-hash comparison, ledgered as
`ERA-RESET`. Manual dashboard tuning counts; nothing trades on stale proof.

## The rails

- **Max 2 promotions and 4 demotions per run** — evidence-strongest first; the rest wait.
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
| `allow_promotions` / `allow_demotions` | `true` / `true` | direction-specific switches |
| `min_raw_episodes` | `20` | minimum era v2 episodes (`bar_n` honored as a deprecated alias) |
| `min_independent_days` | `10` | minimum independent day/session blocks |
| `bar_avg` | `2.0` | net pips/episode bar |
| `lcb_min` | `0.0` | required block-bootstrap lower bound to promote |
| `bootstrap_reps` / `bootstrap_confidence` | `10000` / `0.95` | block bootstrap settings |
| `fdr_q` | `0.05` | Benjamini–Hochberg q-value ceiling across the docket |
| `recent_n` / `recent_min` | `5` / `0.0` | the 7-day guard |
| `family_min_trades` | `5` | minimum era family trades (parent + poppers) to convict or defend |
| `family_demote_pips` | `-60.0` | family era net pips at/below this → demote + poppers off |
| `family_defend_pips` | `60.0` | family era net pips at/above this → seat safe from bar_lost |
| `max_promotions` / `max_demotions` | `2` / `4` | per-run rails |
| `slippage_pips` | `0.5` | slippage haircut per episode |
| `per_test_z` | `2.33` | legacy-display LCB only — **not** a promotion input since D-7 |
| `default_era_start` | *(era anchor)* | evidence floor for setups with no recorded clock |

## Context

The governor automates the **activation bar** doctrine (2026-07-22) that was previously
applied by hand — see [RESEARCH_PROGRAM.md](RESEARCH_PROGRAM.md) for the doctrine's history
and [the README's trial-system section](../README.md) for where this sits in the pipeline.
Manual rulings remain possible at any time through the same dashboard controls; the governor
simply makes the default path evidence-driven rather than attention-driven.

> ⚠️ Research software on an OANDA practice account. The governor promotes to live *practice*
> trading; nothing here is financial advice.
