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

| Switch | Fires when |
|---|---|
| **PROMOTE** SHADOW → ACTIVE | n ≥ **20** scored episodes **AND** average ≥ **+2.0 pips/episode** **AND** the 95% lower confidence bound (`avg − 1.645·σ/√n`) > **0** **AND** the last-7-days average is ≥ 0 (when it has ≥ 5 episodes) |
| **DEMOTE** ACTIVE → SHADOW | era n ≥ 20 with average < +2.0 (**the bar is lost on stamps**), **OR** era **broker fills** n ≥ 5 with a negative average (**fills convict faster than stamps**) |

Why these numbers: the measured retail execution toll on majors is ~0.4–0.5 pips per round
trip, and six of seven edge families this program falsified died at exactly that wall — so
any claimed edge under ~1 pip is indistinguishable from zero. **+2.0 pips/episode** is the
margin at which an edge is distinguishable from the toll; **n ≥ 20** is where a per-setup
average starts to mean something; the **LCB > 0** requirement stops a lucky low-variance
streak from sneaking over the bar; and the **7-day check** stops a decaying setup from being
promoted on the strength of its own past.

Demotion is deliberately double-tracked: shadow stamps measure the *entry's* forward path,
but **broker-verified fills** (via `research/tools/broker_setup_audit.py`) include spread,
slippage, and the live exit — and they convict faster. A setup that is net-negative on ≥ 5
real fills loses its seat even if its stamp tape still looks acceptable.

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
| `bar_n` | `20` | minimum era episodes for either verdict |
| `bar_avg` | `2.0` | pips/episode bar |
| `lcb_min` | `0.0` | required lower confidence bound to promote |
| `recent_n` / `recent_min` | `5` / `0.0` | the 7-day guard |
| `fills_n` / `fills_avg_max` | `5` / `0.0` | broker-fills demotion trigger |
| `max_promotions` / `max_demotions` | `2` / `4` | per-run rails |
| `default_era_start` | *(era anchor)* | evidence floor for setups with no recorded clock |

## Context

The governor automates the **activation bar** doctrine (2026-07-22) that was previously
applied by hand — see [RESEARCH_PROGRAM.md](RESEARCH_PROGRAM.md) for the doctrine's history
and [the README's trial-system section](../README.md) for where this sits in the pipeline.
Manual rulings remain possible at any time through the same dashboard controls; the governor
simply makes the default path evidence-driven rather than attention-driven.

> ⚠️ Research software on an OANDA practice account. The governor promotes to live *practice*
> trading; nothing here is financial advice.
