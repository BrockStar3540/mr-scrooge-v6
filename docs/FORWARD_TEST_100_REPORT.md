# The 100-Trade Forward Test — final report

*Generated 2026-07-29 11:03 UTC from broker records.
Pre-registered endpoint and consequences: [FORWARD_TEST_PROTOCOL.md](FORWARD_TEST_PROTOCOL.md).*

## The number that matters

| | |
|---|---|
| **Starting balance** (2026-07-16, pre-first-fill, broker-verified) | **$16,665.12** |
| **Ending balance** (account flat) | **$18,421.85** |
| **Return over the window** | **+10.54%** |
| Natural closes (the strategy statistics) | 99 |
| Operator close-outs (asterisked, excluded from stats) | 2 |
| Total tape | 101 |

A precision note, because honesty is the product here: the protocol said "the 100th
closed trade." The operator froze entries and closed the final open positions by hand
with the natural tape at 99 closes — so the strategy sample is **99 system-managed
trades**, the two hand-closes are asterisked below, and the balance numbers include
everything. Nothing is hidden in either direction.

## The tape

- **W/L (natural closes):** 89/10 (89.9% win rate)
- **Realized (natural closes):** $+1,788.25 · avg win $+41.37 · avg loss $-189.40
- **Breakeven win rate the geometry demanded:** 82.1%
- **By source:** legacy 3 trades $+158.73 · parent 39 trades $+828.55 · popper 57 trades $+800.97
- Full tape: [livelog/trades.csv](../livelog/trades.csv) · equity: [livelog/equity.csv](../livelog/equity.csv)

### * Excluded from the statistics — operator close-outs

The test was ended by hand: trading was paused at 2026-07-29T10:24:28Z and the last open positions were closed manually. Those closes are on the tape and in the balance, but they measure the operator's decision to stop, not the system's exits — so they carry an asterisk and sit outside the strategy statistics:

| close (UTC) | instrument | dir | realized | source |
|---|---|---|---|---|
| 2026-07-29T10:31:31Z * | GBP_USD | short | $+5.25 | popper (manual close) |
| 2026-07-29T10:46:09Z * | GBP_USD | short | $-23.09 | parent (manual close) |


## Per-family attribution (parent + its poppers, one unit)

| family | trades (P/pp) | G/R | USD | pips |
|---|---|---|---|---|
| GBP_USD rvol_low_240 | 20 (2/18) | 13/7 | -858.37 | -331.7 |
| AUD_USD classic_extension_fade_long | 6 (3/3) | 5/1 | +10.95 | +1.6 |
| EUR_JPY timing_lean_30 | 1 (1/0) | 1/0 | +18.06 | +10.0 |
| USD_JPY timing_lean_30 | 2 (2/0) | 2/0 | +34.35 | +15.7 |
| GBP_USD classic_box_fade_long | 5 (3/2) | 5/0 | +107.77 | +41.4 |
| GBP_USD control_rvol_60 | 3 (3/0) | 3/0 | +131.72 | +25.9 |
| GBP_USD control_rvol_60_t20s | 11 (1/10) | 10/1 | +199.20 | +74.3 |
| USD_JPY control_atr5m_60 | 26 (13/13) | 25/1 | +300.57 | +124.1 |
| EUR_USD ps_floor_fade_long | 7 (5/2) | 7/0 | +473.78 | +61.7 |
| AUD_USD control_atrconc_60 | 3 (3/0) | 3/0 | +475.29 | +49.4 |
| AUD_USD kc_up_long_lean | 14 (4/10) | 13/1 | +718.42 | +72.7 |

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
