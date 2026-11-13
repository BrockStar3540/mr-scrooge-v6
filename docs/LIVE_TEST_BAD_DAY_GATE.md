# Live test: the bad-day gate

**Registered 2026-11-13, before any gate-era trade closed. Live since 2026-11-13 03:11 UTC (v6.32.0).**
Theory and evidence: [the insurance-seller paper](papers/PAPER_insurance_seller_theory_2026-11-13.md).

## What is running

`config/day_gate.py` with `config/day_gate.json`, hot-reloaded each cycle. New entries are skipped, both cell parents (`core/engine.py`) and popper fires (`modules/management/party_package.py`), when:

- the **FX trading day** is a Thursday or a Friday (New York clock + 7 hours, so the day rolls at 17:00 ET), or
- the day is listed under `event_days` for a currency of the pair (`ALL` = every pair; today only the FOMC decision on 2026-12-09), **unless**
- the setup belongs to an **exempt family**: `liq_sweep_fade`, `classic_willr_fade`, `control_atr5m_60`, `rg1_range_scalp` (a setup matches when its id equals the family name or starts with it plus an underscore).

Open trades, the ratchet and the reaper are never touched. A missing or unreadable config means no filter. Each skipped signal writes one `DAYGATE skip <pair> setup=<id> reason=<weekday-Thu|weekday-Fri|event-DATE>` line per pair, setup and day. `"enabled": false` switches the gate off without a restart. Tests: [`tests/test_day_gate.py`](../tests/test_day_gate.py).

## Hypothesis

H1: on days the gate skips, the non-exempt book loses more per trade than on other days, so removing those days raises pips per trade of the remaining book.
In the 1,170-trade tape before the gate, those days averaged −3.37 pips a trade against −0.67 on all other days (617 trades against 553). The analysis did **not** clear our own bar: random day-skipping of the same size matches it about 5% of the time, and exemptions picked in advance did worse than no exemptions in the second half of the record. This is why it is a live experiment, not a promoted rule.

## Measurement (frozen)

- **Kept record:** every V6 trade entered after 2026-11-13 03:11 UTC (parents and poppers), net pips fill to fill, win rate, realized dollars after financing, trades with a realized loss of $15 or more.
- **Skipped side:** each `DAYGATE skip` line is replayed from M1 bid/ask with the live exit rules to estimate what the gate refused. This is an estimate: the replay disagrees with real fills by a few pips a trade, so it is used for the comparison below and never reported as realized profit.
- **Benchmark:** the replayed no-gate stream (kept plus skipped) is the control. The gate's kept trades are compared with 4,000 random sets of whole trading days with the same number of trades removed, because the book loses on average and any skipping flatters itself.
- **Baseline:** −2.10 pips a trade over the 1,170 trades before the gate.

## Decision rule (frozen)

Read the result at **150 closed gate-era trades or 2027-02-05 (12 weeks), whichever comes first**.

- **Keep the gate** if kept trades show a positive total in pips **and** beat random day-skipping at p < 0.05.
- **Switch it off** (`enabled: false`) otherwise.
- Fewer than 100 trades at 12 weeks means the result is inconclusive and the gate stays on until 150 trades.
- Exemptions and weekdays are not edited during the test. A different rule gets a new ID and a new registration time.

## Interaction with the entry-filter forward test

The [forward test registered on 2026-11-10](FORWARD_TEST_FILTERS_2026-11-10.md) scores rules from live trades. The live book has been filtered since 2026-11-13 03:11 UTC, so its rules that include a Thursday or a Monday-to-Friday cut are scored only on trades entered from 2026-11-10 08:30 UTC to that moment. The gate itself is judged by this document's rule.

## Caveats

About six live seats at 4% size produce a few trades a day, and the gate removes roughly half of them in the sample, so 150 trades may take most of the 12 weeks. A short, bad stretch does not refute a 12-week test and a short, good stretch does not confirm it.
