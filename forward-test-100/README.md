# The 100-Trade Forward Test — the record

![The 100-trade forward test: +10.54%, 90/10, max drawdown −10.1%, and yes it paid the spread](../docs/images/forward_test_card.svg)

**The concluded practice test that sent this system live.** Window 2026-07-16 → 2026-07-29,
starting balance **$16,665.12** (broker-verified) → ending balance **$18,421.85** (**+10.54%**).
The 100-trade window went **90 wins / 10 losses (90.0%)** against an 82.2% breakeven
requirement. Full analysis: [the final report](../docs/FORWARD_TEST_100_REPORT.md) ·
the rules, declared before the result: [the protocol](../docs/FORWARD_TEST_PROTOCOL.md).

| File | What it is |
|---|---|
| [trades.csv](trades.csv) | the tape — every closed trade of the window, broker-verified (101 rows: the 100-trade window + one post-window operator close) |
| [equity.csv](equity.csv) | hourly NAV/balance snapshots across the window (the updater's columns changed mid-July; rows are normalized to one 8-column schema, blanks where a column didn't exist yet) |
| [equity.svg](equity.svg) | the final chart, frozen at close |

The complete raw broker export (11,564 transactions, account creation → close, every era
including the −84% research tuition) is public in
[the archive](https://www.dropbox.com/scl/fo/uyjwoj274ndzqg98ol72p/AEB6zn4q-jFexhZxVmYFRyc?rlkey=a06ocaqxuyz4at1dfkjmww1i9&st=kup4s0x9&dl=0)
under `proof-of-tape/`. This folder is immutable — the live real-money record lives at
[livelog/](../livelog/) and updates hourly.
