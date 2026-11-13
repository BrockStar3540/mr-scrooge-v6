# Scrooge V6 entry-filter forward test: pre-registration

*Status: running. Registered 2026-11-10, rules frozen. See the [live test of the bad-day gate](LIVE_TEST_BAD_DAY_GATE.md) for how the live gate (2026-11-13) affects scoring.*

**Registered:** 2026-11-10, before the 08:30 UTC cutoff, with the owner's go-ahead.
**The test itself changes nothing in the live bot.** Every rule below is a fixed function of a trade's entry time, family and setup, so the rules are scored offline on each new trade from the broker record. (The separate bad-day gate of 2026-11-13 is its own experiment, see the status line above.)

## Why

The 2026-11-06 to 11-10 analysis (1,170 V6 trades, the shadow board, calendar tests) found cuts that look good on past data but are break-even at best out of sample, and found that the book loses about 2.1 pips per trade so any rule that skips trades flatters itself. A forward test on trades that did not exist when the rules were written is the only clean answer.

## Frozen rules

Forward sample = V6 trades **entered at or after 2026-11-10 08:30 UTC** that have since closed. A popper inherits the entry time and session of the latest earlier parent with the same pair, direction and setup.

The four cut slots:
- **THU:** entry weekday in New York time is Thursday.
- **P1620:** parent entry between 16:00 and 20:00 UTC (poppers inherit).
- **P36:** parent entry 3 to 6 hours after its session opened, with sessions asia 22-07, london 07-13, ny 13-22 UTC (poppers inherit).
- **MONFRI:** Monday entries from 16:00 New York time, or Friday entries before 04:00 New York time.

| ID | Rule (a trade is SKIPPED when) |
|---|---|
| F0 | never (the live book, the control) |
| FA | it falls in any of the four cut slots, any family |
| FT | its family is not control_atr5m_60, rg1_range_scalp or ps_floor_fade |
| FB | not a top-3 family, or in any cut slot |
| FC | not a top-3 family, or in a cut slot the family is not exempt from. Exemptions: control_atr5m_60 from P1620 and P36; rg1_range_scalp from P36 and MONFRI; ps_floor_fade from MONFRI |
| FD | rg1_range_scalp only: 6 or more hours after session open, or New York 00:00 to 04:00 |

The weekly walk-forward selector (`pipeline_wf.py`, family level) is a separate pre-registered rule that keeps running on its own: its test weeks from 2026-11-10 onward are the forward sample.

## What is measured

For each rule: kept trades, win rate, average pips, total pips, net dollars after financing, big losses (realized -$15 or worse), and the pips and dollars of the skipped trades. Each rule is compared with random skipping of the same number of trades (4,000 draws), because the book loses on average.

## Decision rule (frozen)

A rule is considered for live use only after **at least 150 forward trades or 8 full weeks**, and only if its kept trades show a **positive total** and beat random skipping at **p < 0.05**. Anything less means no live change. New ideas get a new ID and a new registration time; these rules are not edited.

## How to run

Scored offline from the broker record by a script that re-dumps the transaction history, rebuilds the joined trade book and first re-checks that the rules reproduce the earlier in-sample numbers (FA keeps 542 of 1,170 trades, +269 pips, +$5).

## Caveats

Roughly 6 live seats and a 4% size mean the sample grows slowly; 150 trades may take longer than 8 weeks. The simulator behind the shadow board overstates real fills by about 2.9 pips per trade, so shadow results are not used here. Only real fills count.
