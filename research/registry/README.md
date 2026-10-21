# The hypothesis registry (public)

This directory lists every strategy setup the Bar Governor has ever scored. It also gives
each setup's score at each governor decision, including the setups that were never
promoted. Its job is to make the multiple-testing denominator something anyone can count.
It was asked for in [issue #9](https://github.com/BrockStar3540/mr-scrooge-v6/issues/9).

The data is refreshed **hourly at :20 UTC** by [`ops/state_commit.py`](../../ops/state_commit.py),
which runs [`research/tools/registry_publish.py`](../tools/registry_publish.py) and commits
this directory on its own. The governor runs hourly at :35. The live trading record is in
[`livelog/`](../../livelog/).

## Files

| File | What it holds | How it changes |
|---|---|---|
| `registry.json` | One entry per `PAIR\|session\|setup` ever registered: `first_seen`, every mechanics hash it has had (`cfg_hashes`; a new hash is a new config version), status now, `ever_seated` (has it ever held a PROBE/ACTIVE seat, when first, and what shows it), counts of each decision type, its last decision, governor-run counts from the score snapshots, and its latest bar score. The top-level `counts` give **M_ever**, M_live, the number of config versions and the number ever seated. `bar` lists the promotion knobs in force. `first_seen_by_date` shows how the search grew. | Rewritten every hour |
| `decisions.jsonl` | Every governor, commissioner and operator decision in the governor ledger (`data/governor_ledger.jsonl`), with the scores the ledger recorded parsed into fields. `bar` holds n, day-blocks, net average, block LCB, BH q and the 7-day guard. `family` holds broker family cycles and net pips. `truth_gate` holds the virtual-vs-broker sign check. Rows with `scope: "book"` are book-wide changes, for example a slate of 140 new shadows or a seat-ceiling raise. | Rebuilt from the ledger every hour; append-only in practice |
| `bar_scores/YYYY-MM.jsonl` | The ordinary-lane bar evidence for **every** setup: era episodes `n`, independent day-blocks `days`, `net_avg` (pips, after costs), `block_lcb`, BH `q`, `promotable`, and the failure `codes` (`RAW_N`, `INDEPENDENT_DAYS`, `AVG`, `LCB`, `RECENT`, `FDR`). It comes from the dashboard's Shadowboard, which calls the same engine on the same inputs as the governor (`core/trial_evidence.py`). A row is written only when a setup's evidence changed. To get a setup's score at a given governor run, take its last row at or before that time. `t` is when the board was built. That is within about an hour of the governor run it sits next to, not the run itself. | Append-only, hourly, from 2026-10-21 |
| `cheater_scores/YYYY-MM.jsonl` | The Cheater lane's per-run score, summarized from `data/score_snapshots.jsonl` (500 MB, one line per setup per governor run since 2026-08-01). There is one row per setup per UTC day, written only when its status, heat, trust, cycle count, eligible or promoted value changed. | Append-only, daily, backfilled to 2026-08-01 |

## What's missing, and why

* **Bar scores before 2026-10-21 exist only for setups the governor acted on.** The
  governor computed every setup's bar evidence on every run, but it logged the numbers only
  for setups it promoted, demoted or graduated. That is the `bar` field in
  `decisions.jsonl`. `PROMOTE-GATED` rows (the bar was met but promotions were switched off)
  don't carry scores. From 2026-10-21 every setup's bar score is published hourly.
* **Dry runs are counted, not published.** `counts.dry_run_rows` in `registry.json` is the
  number left out.
* **Setups seated before the ledger existed** (hand-picked ACTIVE at the 2026-07-19 cutover)
  are marked `seated_source: "episode_stamp"`. They were found once from the shadow episodes
  stamped while they were ACTIVE, using `registry_publish.py --seed-episode-seats`.
* Raw episodes (`data/shadowboard.json`, about 70 MB) and the raw snapshot file stay private
  because of their size. Everything the governor decided on is summarized here.

## What it's used for

[`research/deflation/`](../deflation/) runs the deflated Sharpe ratio and PBO/CSCV tests on
the promoted set against this registry. That test was pre-registered before it was run.
