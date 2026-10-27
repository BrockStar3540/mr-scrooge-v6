# Results: deflated Sharpe + PBO/CSCV on the promoted set

**Spec:** [PREREGISTRATION.md](PREREGISTRATION.md), public in commit `48f82bf9` (2026-10-21 21:02 UTC) before the run.
**Run:** 2026-10-21 about 21:04 UTC on the Mac mini, with `research/tools/deflation_test.py` unchanged since registration.
**Raw output:** [results.json](results.json).

## Verdict (pre-registered rule, §5): **the bar measures the search**

| | Value | Rule |
|---|---|---|
| **D**, median DSR over the 163 ever-seated setups | **0.00** | D ≤ 0.5 → "measures the search" |
| **P**, PBO_bar (S = 16, 12,870 splits) | **0.03** | P ≤ 0.25 would be "doing work" |

The rule needs D > 0.5 **and** a low P before it calls the bar useful. D fails, so the verdict
is "measures the search". The two numbers point in different directions, though, and both
are reported here.

## What the numbers say

**1. No promoted setup clears what 1,701 tries would produce by luck.**

* The trials' daily Sharpe ratios have a cross-sectional variance of 0.0387. With
  N = M_ever = 1,701, the best zero-skill trial would be expected to show a **daily Sharpe of
  0.67**.
* The median ever-seated setup has a daily Sharpe of **0.13**, so its deflated excess
  Sharpe is −0.54.
* Of the 163 ever-seated setups, **0** have DSR ≥ 0.95 and **2** have DSR > 0.5.
* The 133 bar-promoted setups look the same: median DSR 0.00.
* Without deflation (PSR), 56 of the 163 pass at 95% and the median PSR is 0.80. The
  deflation is what takes them out.
* The verdict doesn't depend on the choice of N:

  | N used | Value of N | Median DSR |
  |---|---|---|
  | M_ever (primary) | 1,701 | 0.00 |
  | Trials with data | 1,667 | 0.00 |
  | Config versions | 2,915 | 0.00 |
  | Effective N (participation ratio of the correlation matrix) | 42 | 0.01 |

* The equal-weight promoted book makes +2.28 pips/day in shadow, with daily Sharpe 0.36 and
  PSR 0.999. Its DSR is 0.003. (This figure is optimistic, as noted in the pre-registration.)

**2. Inside the shadow data, the bar does rank setups better than chance.**

* **PBO_bar = 0.03.** In 97% of the 12,870 halvings, the setups that the bar replica picks
  on one half rank above the median trial on the other half.
* Their mean out-of-sample daily Sharpe is 0.18, against 0.07 for everything else. The
  margin is modest: the median logit is 0.35, which puts the selected set at about the
  59th percentile.
* With S = 8, PBO_bar is 0.06.
* The canonical single-best-pick version, **PBO_maxSR**, is 0.19 (0.19 at S = 8). Using only
  the 124 trials whose history covers the whole window, it is 0.33.

**3. Why the two tests disagree, and why the bar still fails.** PBO asks whether the bar's
picks beat the *other trials*. DSR asks whether they beat *luck at this search size*. The bar
passes the first test and fails the second: its picks are a little better than the rest of
the book, but nowhere near good enough to rule out selection.

The reference point matters as well. The rest of the book has a *positive* out-of-sample
Sharpe in the shadow data. The live broker record over the same era is −$1,277 over 986
trades (`livelog/`). A ranking edge inside an optimistic simulator is not evidence of a money
edge. That limit was registered in advance (§7).

## Deviations from the pre-registration

* **Registry commit.** §2 says the registry is "as published by this push". `registry.json`
  actually landed in the next commit, `276ca5e0`, about a minute after `48f82bf9`. The first
  `state_commit` run wrote it. The analysis used that file
  (SHA-256 `795a50a2…`, M_ever = 1,701).
* **No code changes after registration.** The script ran first time, as committed.
* **Data note (not a deviation).** 1,421 of the 70,097 episodes used (2.0%) are stamped on
  Saturdays, when FX is closed. They are included, as the spec requires. Why the shadow
  stamper produces them is a separate bug to investigate. It was found during this run and
  is not fixed here.

## Inputs

| | |
|---|---|
| Episodes | frozen copy of `data/shadowboard.json`, taken 2026-10-21 21:03 UTC; SHA-256 `e389bfd0c51603acc8298176fb727a1bdb9cfe3cd52b1af2fa1582a2ef33ac19` |
| Window | 2026-07-28 → 2026-10-20 (85 days, cutoff 2026-10-21 exclusive); 70,097 resolved v2 episodes; 1,667 trials with data |
| Registry | `research/registry/registry.json` @ `276ca5e0` (SHA-256 `795a50a259b8f3d628384cf5608ce16d9cfaf275846be3a1357968825fd5912e`) |
| Decisions | `research/registry/decisions.jsonl` @ `276ca5e0` (SHA-256 `f0c7c04ec031d42ccb04ecee73d67c7d6e542df26e7731aafb82f40afb33594b`) |

The frozen episode file is public as of 2026-10-27:
[`inputs/shadowboard_frozen_2026-10-21T2103Z.json.gz`](inputs/shadowboard_frozen_2026-10-21T2103Z.json.gz)
(3.5 MB gzipped; the gunzipped file hashes to `e389bfd0…` above). It was scanned for
credentials, account ids, hosts and IP addresses before publishing, and holds none. To re-run
against the registered inputs:

```
git show 276ca5e0:research/registry/registry.json   > registry.json
git show 276ca5e0:research/registry/decisions.jsonl > decisions.jsonl
mkdir cells && git archive 276ca5e0 config/cells config/setup_aliases.json | tar -x -C cells
gunzip -k research/deflation/inputs/shadowboard_frozen_2026-10-21T2103Z.json.gz
python research/tools/deflation_test.py \
    --episodes research/deflation/inputs/shadowboard_frozen_2026-10-21T2103Z.json \
    --registry registry.json --decisions decisions.jsonl \
    --cells cells/config/cells --aliases cells/config/setup_aliases.json \
    --cutoff 2026-10-21 --out results.json
```

## Addendum (2026-10-27): reproduction and closed-market sensitivity

Post-hoc, asked for on issue #9. Not part of the pre-registered verdict, and
PREREGISTRATION.md is unchanged.

**Reproduction.** The command above was re-run on Linux (Python 3.13, numpy 2.5) and the
three input hashes all match. Every field of `results.json` reproduces except
`median_logit_bar`, which differs in the fifth decimal (S = 16: 0.34963 published, 0.34965
re-run). The likely cause is tie order in `argsort` between numpy builds. No verdict
number moves.

**The "59th percentile".** RESULTS.md says the selected set sits "at about the 59th
percentile". That figure comes from inverting the median CSCV logit:
1 / (1 + e^(−0.3496)) = 0.587. It is a median across splits, not an average as the issue
#9 comment said. The sensitivity file now records it as `selected_oos_rank_pct_S16`.

**Closed-market episodes dropped.** `research/tools/deflation_sensitivity.py` runs the
registered `run()` unchanged on filtered copies of the frozen input. Output:
[`sensitivity_closed_market.json`](sensitivity_closed_market.json).

| Input | Episodes dropped | Median DSR | PBO_bar S=16 | PBO_bar S=8 | PBO_maxSR S=16 | Selected rank | Verdict rule |
|---|---:|---:|---:|---:|---:|---:|---|
| As registered | 0 | 0.00 | 0.032 | 0.057 | 0.190 | 0.587 | measures the search |
| Saturday stamps dropped | 1,421 | 0.00 | 0.034 | 0.100 | 0.178 | 0.582 | measures the search |
| All closed-market stamps dropped (NY Fri 16:55 → Sun 17:00) | 2,696 | 0.00 | 0.041 | 0.086 | 0.176 | 0.578 | measures the search |

The closed-market window is the calendar form of the live scorer's fix
(`ops/shadowboard._market_closed_at`, commit `e08d47ce`). On the live store, that fix marked
2,651 resolved episodes. PBO_bar stays low, DSR stays at zero, and the verdict doesn't
change. The weekend data issue doesn't drive either number.

**On the reading of the verdict.** At N = 1,701 over 85 market days, the zero-skill best
of N is about 0.67 daily Sharpe. Even the equal-weight book (0.36, PSR 0.999) deflates to
0.003. So this sample can't separate a modest real edge from the search. "Measures the
search" describes what the bar can certify at this length. It is not proof that the
selected setups have no edge. The separate evidence on that question is the live broker
record in `livelog/`, which these tests don't use.
