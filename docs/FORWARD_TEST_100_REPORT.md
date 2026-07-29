# The 100-Trade Forward Test — final report

*Generated 2026-07-29 11:48 UTC from broker records.
Pre-registered endpoint and consequences: [FORWARD_TEST_PROTOCOL.md](FORWARD_TEST_PROTOCOL.md).*

![stat card](images/forward_test_card.svg)

## The number that matters

| | |
|---|---|
| **Starting balance** (2026-07-16, pre-first-fill, broker-verified) | **$16,665.12** |
| **Ending balance** (account flat) | **$18,421.85** |
| **Return over the window** | **+10.54%** |
| The window (protocol: the first 100 closed trades) | 100 |
| Post-window closes (asterisked, outside the stats) | 1 |
| Total tape | 101 |

## The tape

- **W/L (the 100-trade window):** 90/10 (90.0% win rate)
- **Realized (window):** $+1,793.50 · avg win $+40.97 · avg loss $-189.40
- **Breakeven win rate the geometry demanded:** 82.2%
- **By source:** legacy 3 trades $+158.73 · parent 39 trades $+828.55 · popper 58 trades $+806.22
- Full tape: [forward-test-100/trades.csv](../forward-test-100/trades.csv) · equity: [forward-test-100/equity.csv](../forward-test-100/equity.csv) · final chart: [equity.svg](../forward-test-100/equity.svg)

### † Inside the window, closed by the operator

Trading was paused at 2026-07-29T10:24:28Z with the tape at 99 closes; the operator then closed the remaining open positions by hand. The **100th close of the window was one of those hand-closes** — the protocol's endpoint is "the 100th closed trade," so it counts, and it is disclosed here rather than buried:

| close (UTC) | instrument | dir | realized | source |
|---|---|---|---|---|
| 2026-07-29T10:31:31Z † | GBP_USD | short | $+5.25 | popper (operator close, in-window) |

### * After the window — not in the statistics

The window ended at close #100. Later closes are on the tape and in the ending balance, but outside the pre-registered window:

| close (UTC) | instrument | dir | realized | source |
|---|---|---|---|---|
| 2026-07-29T10:46:09Z * | GBP_USD | short | $-23.09 | parent (operator close, post-window) |


## Per-family attribution (parent + its poppers, one unit)

| family | trades (P/pp) | G/R | USD | pips |
|---|---|---|---|---|


## What changed mid-window (disclosed)

- 07-19: engage 7.5 → 8.5 regear (whole book, open trades re-geared broker-side).
- 07-28: the FAMILY RULE + judge-when-flat (v6.7.x) — demotion re-grounded in family
  broker net pips; motivated by this very tape's one losing family.

## What 100 trades is — and isn't

**100 trades in a two-week window is not proof of sustained edge — by any means.** It's one
market regime and a sample small enough that variance alone could paint either verdict. It
is enough for *us, personally,* to try live trading with a small stake — that is the whole
claim. Use your own discernment; results vary over time, and when things go wrong the
drawdown can be substantial (this account's history includes a −84% research tuition; the
falsification record is public). The troublesome cells were demoted mid-window, and the
system now promotes and demotes seats autonomously as each cell earns or loses them.

## The decision

Per the pre-registered protocol: the practice account is closed with this report, and the
system goes **live with $2,500.00 real money** — `margin_pct_per_trade` 0.10 → 0.15,
`max_concurrent_trades` 8 → 6, popper `max_margin_pct_total` 0.8 → 0.9, everything else
exactly as tested. The live record publishes to this repo hourly, same as this one did.
