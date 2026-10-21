# Pre-registration: does the Bar Governor's bar select edge, or measure the search?

**Registered:** 2026-10-21, before any of the statistics below were computed.
**Asked for in:** [issue #9](https://github.com/BrockStar3540/mr-scrooge-v6/issues/9) (rytjy), answered 2026-10-21.
**Code:** [`research/tools/deflation_test.py`](../tools/deflation_test.py), committed with this file and not yet run on real data.
**Trial registry:** [`research/registry/`](../registry/README.md), published in the same push.
**Results:** `research/deflation/RESULTS.md` and `results.json`, in a later commit. That commit may not change this file.

## 1. The question

The governor promotes a shadow setup to a PROBE seat when it clears a bar: at least 10
executable-exit-v2 episodes over at least 5 independent day-blocks, net average of +2.0 pips
or more after costs, a day-block bootstrap 95% lower bound above 0, and a Benjamini–Hochberg
q of 0.10 or less. BH runs over the *docket*, which is only the setups that have reached
their counting gates. More than 1,700 setups have been scored. rytjy's point is that a bar
like this may mostly measure how many setups we tried.

Two standard tests answer that:

* **Deflated Sharpe ratio** (Bailey & López de Prado, 2014). This is the probability that a
  setup's true Sharpe ratio is above zero, after allowing for the best of *N* trials being
  lucky. The benchmark is the Sharpe that the best of *N* zero-skill trials would be expected
  to show, given how widely our trials' Sharpe ratios are spread.
* **Probability of backtest overfitting via CSCV** (Bailey, Borwein, López de Prado & Zhu,
  2017). Split the history into blocks. Select on half the blocks, judge on the other half,
  and repeat over every split. PBO is the share of splits where the selection lands at or
  below the median trial out of sample.

## 2. Data (frozen before the run)

* **Trials.** Every key `PAIR|session|setup` in `research/registry/registry.json` as
  published by this push. The primary *N* is that file's `M_ever`, which was 1,701 on
  2026-10-21.
* **Returns.** Resolved executable-exit-v2 shadow episodes from `data/shadowboard.json`.
  These are the governor's own promotion sample type. Each episode's net pips is
  `core.trial_stats.episode_net(net240, spread, pair, slippage_pips=0.5, executable=True)`,
  which is the same cost model the governor uses. Episodes are mapped through
  `config/setup_aliases.json`. Episodes whose side differs from the setup's configured side
  (retired directions) are dropped.
* **Whole life, not era-clocked.** The governor's era clocks reset with every flip and
  config change, so they can't define a common matrix. Each trial uses every resolved
  episode it has.
* **Daily series.** One row per UTC day on which the book has at least one episode. A
  trial's value for a day is the sum of its episodes' net pips. It is 0 on days the trial was
  alive but did not fire. It is missing before the trial's registry `first_seen` date and
  after the first ledger decision that set it DISABLED (or after its last episode, if it was
  removed from config).
* **Cutoff.** The run uses a copy of `data/shadowboard.json` taken after this commit is
  pushed. The first excluded date is the UTC date of the copy. The copy's SHA-256 is recorded
  in `results.json`.

## 3. The promoted set

As committed on the issue, the primary set is **every setup ever PROBE or ACTIVE**. A setup
belongs to it if any of these shows it: a published ledger decision that set it
PROBE/ACTIVE, a score snapshot with that status, its config status at publish time, or any
episode stamped while it was ACTIVE/PROBE. The last source covers setups seated by hand at
launch, before the ledger existed.

The secondary set is the **bar-promoted only** subset: setups with a non-dry-run `PROMOTE` or
`CHEATER-PROBE` ledger decision.

## 4. The statistics

**Sharpe ratio.** Per-day (not annualized): mean over standard deviation (ddof = 1) of the
trial's daily series over its alive days. A trial needs at least 10 alive days and a non-zero
standard deviation to get one.

**DSR, primary.** Computed for each setup in the promoted set as
`DSR = Φ( (SR − SR₀) · √(T−1) / √(1 − γ₃·SR + (γ₄−1)/4 · SR²) )`, where γ₃ is skewness and
γ₄ is non-excess kurtosis of that setup's daily series, and T is its alive days.
`SR₀ = √V · ((1−γ)·Φ⁻¹(1−1/N) + γ·Φ⁻¹(1−1/(N·e)))`, where γ is the Euler–Mascheroni
constant, V is the cross-sectional variance of the Sharpe ratios of all trials that have one,
and N = M_ever.

* The headline is the **median DSR across the promoted set**, together with the
  **median deflated excess Sharpe, SR − SR₀**.
* In the reply on the issue we used "DSR > 0" to mean that the deflated excess Sharpe is
  positive. That is the same thing as a DSR probability above 0.5. "DSR near 0" means the
  probability is at or below 0.5: the promoted setups do no better than the luckiest of N
  zero-skill trials would.
* The results also report the number of promoted setups with DSR ≥ 0.95, the
  un-deflated PSR, and the bar-promoted subset.

**N sensitivity (reported, not used for the verdict).** We also report DSR with N set to
(a) the trials that have data, (b) the number of config versions (the sum of registry
hashes), and (c) an effective N. The effective N is the participation ratio of the
eigenvalues of the trials' daily-return correlation matrix, with missing days set to 0.

**Book DSR (secondary).** An equal-weight daily average over the promoted set's alive members,
deflated with the same SR₀. This is optimistic, because a diversified book's Sharpe isn't
drawn from the single-trial distribution that V describes. It is reported for context only.

**PBO, CSCV.** The market days are split into **S = 16 contiguous blocks**, which gives all
12,870 in-sample/out-of-sample halvings. In each split, a trial is ranked only if it has at
least 5 alive days in each half. The out-of-sample relative rank is ω = rank/(n+1), where
rank 1 is the worst, and λ = ln(ω/(1−ω)).

* **PBO_maxSR** (canonical): select the single trial with the highest in-sample Sharpe.
  PBO is the share of splits with λ ≤ 0.
* **PBO_bar** (primary, because it tests the bar itself): select the set that the
  governor's ordinary-lane predicate would promote using in-sample episodes only:
  * n ≥ 10 episodes, and at least 5 day-blocks with a fire;
  * episode-mean net ≥ +2.0 pips;
  * day-block 95% lower bound > 0;
  * BH q ≤ 0.10 over the in-sample docket.

  The day-block bootstrap is replaced by its normal approximation, so that 12,870 splits are
  feasible. It uses the mean of block means with SE = sd(block means)/√B; the bound is
  mean − 1.645·SE and p = 1 − Φ(mean/SE). BH is the governor's own
  `core.trial_evidence.benjamini_hochberg`. λ is the logit of the mean ω of the selected
  setups. PBO_bar is the share of splits with λ ≤ 0, among splits where something was
  selected. Splits with no selection are counted and reported.
* The replica leaves out the parts of the bar that need broker fills or live state: the
  truth-check gate, strikes and the redemption bar, the cluster filter, seat caps, and the
  7-day recent guard (it is undefined on non-contiguous halves).
* **Sensitivity (reported, not used for the verdict):** S = 8 (70 splits), and PBO_maxSR on
  only the trials whose series spans the whole window.

## 5. The verdict rule, fixed now

Let D be the median DSR over the promoted set and P = PBO_bar at S = 16.

| Outcome | Condition |
|---|---|
| **The bar is doing work** | D > 0.5 **and** P ≤ 0.25 |
| **The bar measures the search** | D ≤ 0.5 **or** P ≥ 0.5 |
| **Inconclusive** | D > 0.5 and 0.25 < P < 0.5 |

The script prints the verdict from exactly this rule. The result is posted on issue #9
whichever way it comes out.

## 6. Our prediction

**We expect "the bar measures the search."** The reasons:

* The 2026-10-01 geometry study of 747 live trades found that the live exit (about +9 pip
  wins against stops of about −47 pips) wins about 80% of trades with *no* entry drift. A driftless entry can therefore
  clear a mean-based bar on a short streak.
* The live record since 2026-07-19 is −$1,277 over 986 trades. Since the 2026-10-12 book cut
  it is −$41 over 73 trades.

A result of "doing work" would contradict both of those.

## 7. Known limits, stated in advance

* About 60 market days is a short history. DSR's √(T−1) term and PBO's 16 blocks of about
  4 days each are both thin.
* Shadow episodes are not broker fills. The live book adds popper grids, reaper closes and
  sizing that the shadows don't have. This tests the *selection rule* on the governor's own
  evidence, not the dollar P&L.
* Setups are not independent: there are twins, counterparts and dial variants of the same
  signal. That is why effective N is reported. The verdict uses M_ever because that is the
  denominator we committed to.
* If the code has to change after this commit, for example to fix a crash, each change is
  listed under "Deviations" in RESULTS.md with its commit. The rule in §5 does not change.
