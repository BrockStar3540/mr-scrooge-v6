---
name: "🏆 Contest Submission"
about: "Submit a strategy for the $10,000 Scrooge Strategy Contest (read CONTEST.md first)"
title: "[CONTEST] <strategy name>"
labels: ["contest"]
---

<!-- Read CONTEST.md before submitting. Incomplete or evidence-free submissions are declined
     without evaluation. One active submission per entrant. -->

## Strategy name

## Pairs
<!-- OANDA instruments, e.g. EUR_USD, GBP_JPY -->

## Sessions
<!-- asia / london / ny, or explicit UTC hour windows -->

## Entry rules
<!-- Exact, mechanical rules: indicator, timeframe, threshold, direction.
     Example: "SHORT when M5 Williams %R > -15 AND price within 0p of previous session high."
     Anything computable from OHLCV is fair game. If a human must interpret it, we can't wire it. -->

## Exit rules
<!-- Exact stop-loss size/placement, and when/how the trade exits: fixed TP, trailing rule
     (trigger/lock/trail distances), time stop, or indicator exit. Numbers, not vibes. -->

## Position/frequency notes (optional)
<!-- Max concurrent trades, re-entry rules, anything about sizing behavior. -->

## Your evidence (REQUIRED)
<!-- Backtest results, forward-test record, broker statements, published track record —
     something establishing this strategy has already shown validity. We are not a free
     hypothesis-testing service; the bot is open source, test it yourself first. -->

## Novelty statement
<!-- One paragraph: how this differs from the setups already published in config/cells/
     and from prior contest submissions. -->

## Confirmation
- [ ] I have read [CONTEST.md](../../CONTEST.md) and accept the terms, including that my
      submission becomes public, measurements by the repo's harness are final, and the
      maintainer is sole judge.
- [ ] I am 18+ and can lawfully receive the prize in my jurisdiction.
