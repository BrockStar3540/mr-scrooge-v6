# The insurance-seller theory of Mr. Scrooge V6, and what we tested against it

*Written 2026-11-13 from the live record of 1,170 closed V6 trades (2026-07-29 to 2026-11-06, every trade in [`livelog/`](../../livelog/)).
Companion documents: [the live test of the bad-day gate](../LIVE_TEST_BAD_DAY_GATE.md) and the [entry-filter forward test](../FORWARD_TEST_FILTERS_2026-11-10.md).
[Issue #9](https://github.com/BrockStar3540/mr-scrooge-v6/issues/9) gave us a method for judging evidence. This paper states the theory that was missing: why the book loses and what would make it win.*

## 1. The theory

V6 sells insurance. It collects a small premium very often and pays a large claim rarely.

| | Live record |
|---|---|
| Win rate | 78% |
| Average win | +8.7 pips (877 of the 913 winners are ratchet-lock exits) |
| Average loss | −40.4 pips (the stop is 40, 50 or 60 pips, sized to the session's swing) |
| Break-even win rate | 40.4 / (8.7 + 40.4) = **82.3%** |
| Gap to break-even | **+4.3 points** of win rate (about +8.4 for +2 pips a trade) |

The expectation per trade is `w × avg_win − (1 − w) × avg_loss`. The book sits about four points of win rate short.

**The claims cluster.** 136 trades (12%) lost $15 or more; together they cost −$4,341, while the other 88% made +$2,735. The ten worst trading days account for 108% of the net loss. Losses are not spread evenly: a few days where many seats are wrong at once do the damage.

An insurer can only get ahead three ways, and each one is a testable claim:

1. **Raise the premium** (win rate or average win). Needs information about direction.
2. **Cut the claims** (smaller or rarer losses). Tighter stops, earlier exits, fewer exposed days.
3. **Cut the cost of doing business** (spread, financing, slippage).

## 2. Lever by lever: what the live tape says

**Cut the claims with tighter stops: tested, loses.** Replaying all 1,170 real entries on M1 bid/ask with the exit-side prices, the live stops give −1,380 pips. Scaling every stop by ×0.3 to ×0.75 is worse. A flat stop of 3, 5, 7 or 10 pips gives −1,745 to −2,335 pips with win rates of 17% to 52%. Fixed take-profits are far worse. The stop is wide because the setups need room: a tight stop turns the book into a coin flip paying the spread. The pre-V6 tight-stop era agrees (524 trades, median stop 12.5 pips, 40% win rate, −2.7 pips a trade).

**Cut the claims with an earlier exit: one thing helped.** A 24-hour reaper on any trade still red is the best exit change in the replay (−950 pips against −1,380), and it is live.

**Cut the claims by not trading certain times: nothing robust.** About 100 cuts by weekday, session, hour, pair, family and calendar (day of month, month end, holidays, central-bank days). Almost any cut looks good in the sample because the book loses 2.1 pips a trade on average, so skipping any trades flatters the result. Against that random-skipping benchmark and with walk-forward selection, no time-of-day, pair or family cut survived. Details in section 3.

**Cut the cost: nothing left to cut.** Spread is paid on every trade; the stops and the ratchet already price it. See the [falsification table](../../README.md#what-we-falsified): the edge before costs roughly equals the toll.

**Raise the premium with direction: nothing yet.** A directional signal that lifted the win rate by +4.3 points would make the book break even; +8.4 would make it earn about two pips a trade. The shadow board of about 1,800 hypotheses does not supply it: its walk-forward picks do no better than random picks of the same size, and the simulator overstates real fills by about 2.9 pips a trade, so its "promote ready" list is not evidence of live profit.

**News: untested.** V5 had a news blackout (CPI, jobs, FOMC); V6 reads technical inputs only. In the live tape, positions open at a scheduled release average −17.5 pips (59 trades), but that is not beyond what the same clock times show on non-event days (p = 0.44). A news-tone or surprise signal is the one input family the bot has never been given. Open-source building blocks exist (FinBERT headline sentiment, GDELT news tone, free economic-calendar scrapers) and no public repo we found shows verified out-of-sample FX news profits. The next test is a pre-registered one on our own trades before anything goes near the live book.

## 3. The bad-day finding, and why it is an experiment, not a result

Trading days are counted on the FX clock (New York time + 7 hours, rolling at 17:00 ET). Using 1,170 trades over 73 trading days:

| Rule (skip these days) | Skipped trades | Avg pips | A random set of days is this bad |
|---|---:|---:|---:|
| Event days for the pair's currency (jobs, CPI, PPI, FOMC, ECB, BoE, BoJ) | 258 | −4.46 | 11% of the time |
| Thursdays | 270 | −3.49 | 13% |
| Fridays | 273 | −3.63 | 11% |
| Mondays / Tuesdays / Wednesdays | 231 / 174 / 222 | −0.55 / −1.21 / −0.82 | 74% to 81% (most random day sets are worse) |
| News days + Thursdays + Fridays | 617 | −3.37 (other days −0.67) | **kept 553 trades: 83% win, −0.67 pips; random day-skips match about 5%** |

Two cautions, both from our own tests. (a) We tested 33 calendar features; one or two pass at 5% by luck alone. The strongest raw result (a month-end window, p = 0.008) is about 0.26 once the 33 tests and four boundary choices are counted. (b) Thursday is not stable across the sample (−3.3, −2.4, −5.5 pips a trade by thirds).

**Family exemptions.** Some families hold up on the bad days: liq_sweep_fade +4.6 pips (12 trades), classic_willr_fade +3.8 (26), control_atr5m_60 +2.0 (49), rg1_range_scalp +1.3 (59). None beats random day sets (chance 23% to 70%). Choosing exemptions from the first half of the record and scoring the second half (trades from 2026-09-17): no skipping −1,166 pips, skipping every bad day −237, skipping with the chosen exemptions −383. Random exemptions of the same size do as well 71% of the time. Hindsight-picked exemptions on the whole sample look better (kept 699 trades, −48 pips) but are scored on the data that chose them.

**Conclusion of the analysis:** a day gate removes premium as well as claims and leaves the average trade slightly negative in the sample. The pattern is plausible (the losses do cluster), but it does not clear our own bar. It is therefore run live as an experiment with a pre-registered pass/fail rule, not promoted as a finding. See [the live test](../LIVE_TEST_BAD_DAY_GATE.md).

## 4. Other results worth knowing

- **Rollover bug (fixed, v6.31.2).** The rollover freeze and guard used fixed UTC hours, wrong after the 2026-11-01 clock change; they now follow New York 17:00. No realized damage was found.
- **Evidence bar.** Per issue #9, 20-cycle results sit within noise (standard deviation 23.2 pips) and the old audition bar passes about 45% of the time by chance; the live standard since 2026-10-21 is broker fills only.
- **Forward test.** On 2026-11-10 we froze six entry-filter rules and a decision rule before any new trade existed ([pre-registration](../FORWARD_TEST_FILTERS_2026-11-10.md)). Scoring is pending.

## 5. What would change our mind

The theory predicts that the book turns profitable only if the win rate rises about 4.3 points or the average loss falls without the win rate falling. Evidence that would count: a direction signal (news or otherwise) that adds that much on trades it never saw, or a live gate-era record that clears the pre-registered rule. Evidence that would refute the day-gate idea: gate-era kept trades at or below zero over 150 trades, or random day-skips matching it at p ≥ 0.05.

Method notes: permutation and time-clustered nulls, walk-forward selection, a random-skipping benchmark, M1 bid/ask replay with exit-side prices. The scripts behind these tables read a joined trade book built from the public tape and raw OANDA exports in [`livelog/`](../../livelog/); they are not yet in the repo.
