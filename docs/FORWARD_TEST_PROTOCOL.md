# The Forward-Test Protocol — the 100-trade window

**Formal amendment, 2026-07-28 (operator ruling).** The current-configuration forward test
is no longer open-ended: it has a defined endpoint, a write-up obligation, and a declared
consequence. This page is the pre-registration.

## The window

- **Anchor:** 2026-07-16 01:11 UTC — the current-config deploy (range-sized wide-stop
  ratchet, SL 40/50/60, engage +8.5 / lock +6 / trail 2.5 fixed, Party Package popper
  grids). Config evolution *inside* the window (the 7.5→8.5 regear on 07-19, the family
  rule and judge-when-flat on 07-28) is documented in the CHANGELOG — the tape is the
  tape, and the write-up will say so.
- **Starting balance:** **$16,665.12** — broker-verified, the account balance immediately
  before the window's first fill (2026-07-16 01:40:29 UTC). No deposits or withdrawals
  occur on this account during the window.
- **Endpoint:** the **100th closed trade** of the window (parents, poppers, and manual
  closes all count — broker fills, never our own journal). The hourly livelog cron raises
  the flag the hour trade #100 closes.

## What 100 trades is — and isn't

Let's be plain: **100 trades in a two-week window is not proof of sustained edge — by any
means.** It's two weeks of one market regime, one config lineage, and a sample small enough
that variance alone could paint either verdict. We know that.

It is enough for **us, personally,** to be willing to try live trading with a small stake —
that is the entire claim being made here. If you're reading this: use your own discernment.
Results can and will vary over time, and if things go wrong the drawdown can be
substantial — this account's own history includes a −84% research tuition, and the
program's falsification record is public in this repo.

What this protocol is, is honesty about how we got here and what we're doing next: the
troublesome cells were demoted, and the system now promotes and demotes seats autonomously
as each cell **earns them or loses them** — the Bar Governor on the promotion side, the
family rule (broker net pips, judged when flat) on the demotion side. The live record will
be public either way.

## At trade #100

1. **Freeze** — no new practice entries; open positions are managed to their natural
   exits (judge-when-flat applies to the account close-out too: the record ends flat,
   not mid-episode).
2. **Write-up** — published in this repo: starting balance, ending balance, the full
   100-trade tape (already public at [livelog/trades.csv](../livelog/trades.csv)),
   win/loss geometry, per-family attribution, and what the family rule changed mid-test.
   Generator: `research/tools/forward_test_100.py`.
3. **Close the practice account.** The practice livelog (trades, equity, graph) is
   archived in-repo as the concluded test — the record stays public and immutable.
4. **Go live with $2,500 real money.** Deliberately small: the point of the forward test
   was never the practice balance, it was whether the system clears its costs on real
   fills. Real money is the only remaining referee.

## The live configuration

| Knob | Practice (the test) | Live | Why |
|---|---|---|---|
| `margin_pct_per_trade` | 0.10 | **0.15** | smaller capital — fewer, larger seats |
| `max_concurrent_trades` | 8 | **6** | same total exposure envelope (~90% vs 80%) |
| `max_margin_pct_total` (poppers) | 0.8 | **0.9** | must not bind below 6 × 15% |
| Everything else | — | unchanged | the governor, the family rule, the bar |

The wider per-trade sizing is a capital-scaling decision, not a strategy change — entries,
exits, the governor, and the family rule carry over exactly as tested.

## The live record — same glass house

From the first live fill, the **same hourly livelog pipeline** publishes to this repo:
broker-verified trades, the equity curve, and the README graph — real money, numbers only
(no account identifiers, no credentials; the token never leaves the trading host). The
practice record remains archived beside it. Anyone can follow the live progress the same
way they could follow the test.

## Sequencing note

The live credential stays parked and inert until the cutover moment itself, which is
executed with the operator present — nothing in this protocol wires real money early.
