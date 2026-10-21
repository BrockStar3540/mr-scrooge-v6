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

The episode file is private because of its size, about 70 MB. The frozen copy (3.5 MB
gzipped, hash verified after archiving) is kept in the research archive under
`research-corpora/issue9-deflation-2026-10-21/` and is available on request, so anyone can
re-run:

```
python research/tools/deflation_test.py --episodes shadowboard.json --cutoff 2026-10-21 \
    --out results.json
```
