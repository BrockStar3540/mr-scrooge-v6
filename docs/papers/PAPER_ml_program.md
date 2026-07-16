# The Machine-Learning Program: Judges, Authors, a Sealed Lab, and Why the Live Bot Now Runs None of It

**Mr. Scrooge · research paper · covering 2026-05 → 2026-07 (written 2026-07-16)**
**Author: Brock (objectives, doctrine, every "no bias" rule) + Claude Code (implementation, measurement)**
**Status: retrospective. Every ML system described here is retired from the live path; the cell-era
V5/V6 bot runs no live ML (§10). All numbers scoped sim / live / broker; anything resting on
pre-2026-07-03 H1-parquet features is an upper bound (B-078).**

---

## Abstract

Between May and July 2026 the program built, deployed, and retired a complete family of machine-learning
systems: direction classifiers, two generations of entry "brains" (a net-ladder committee, then a
pip-utility regressor), a continuous exit brain, a bucket-keyed gating brain with learned TAKE/AVOID
maps, a strategy-*authoring* discovery engine, a sealed research lab with a five-step promotion gate,
and a nightly pattern-mining loop. Several produced genuinely strong out-of-sample **backtests** — the
discovery engine's authored strategies held +8.42 pips on unseen years; the utility brain's selections
held +4.86 pips OOS; the sealed lab's two-layer selector beat the live book by ~70% across five
walk-forward folds. Yet when each system was judged by the standard the program eventually adopted —
**broker-fill truth on its own live trades** — none of the edges survived: the live tape lost money
under every brain, one brain was measurably *anti-calibrated*, a fifth of the training-map structure was
walk-forward overfit, the backtest labels under-charged real exit slippage by 2–4 pips, and the H1
look-ahead leak (B-078) re-based much of the corpus evidence as upper bounds. The honest conclusion is
not that gradient-boosted trees cannot rank forex entries — they demonstrably can, in sim — but that on
this venue the sim-to-live gap (cost, slippage, leakage, survivorship, regime) was consistently the same
size as the modeled edge. **Measurement beat modeling.** What survived into the live V5/V6 bot is the
ML program's *discipline* — walk-forward as the activation primitive, unbiased training, the utility
objective, train/serve parity checks — applied to deterministic, human-auditable rules rather than to
live models.

---

## 1. Background

By late May 2026 the V3 bot's "intelligence" was a stack of frozen lab lookup tables (a 16k-cell matrix,
per-pair wins/loss rule modules) plus one live LightGBM classifier gate. The ML program proper begins
with the audit that found this out (*ml-lab build spec, 2026-06-04*): the edge was static artifacts, not
live learning, and at least one model had been fed dead features for months (the frozen `htf_pct_20/60`
factors, fixed 2026-06-09 — the origin of the *verify-live-wiring* doctrine). The two months that follow
are a rapid succession of ML systems, each fixing the previous one's diagnosed flaw. This paper
documents each system: what it was, what it trained on, what it measured, why it was retired, and where
its artifact lives (all artifacts: [`../DATA_AND_MODELS.md`](../DATA_AND_MODELS.md)).

---

## 2. Early direction ML (ties to hypothesis H1)

**What it was.** The direct attack on H1 (indicator-direction prediction — see
[`../RESEARCH_PROGRAM.md`](../RESEARCH_PROGRAM.md)): per-(pair × session × direction) gradient-boosted
classifiers predicting *which way*, isotonic-calibrated per cell, walk-forward gated.

**Training data + objective.** Phase 1 keyed by pair × session with `(price_move > 0)` labels — caught
in review as a label/target mismatch (the entry gate optimizes `net > 0`, not raw sign). Phase 2
retrained **104 cells** per (pair × session × direction) on the cost-aware label.

**Measured (sim).** Phase 2 median out-of-fold accuracy **68.9%**; the walk-forward gate activated **57
of 92** cells with sufficient sample. The distribution was the interesting part: USD_JPY — a flagship
pair — activated only 1 of 11 cells, while USD_CHF/asia/short, from the "weakest pair," was the single
most predictable cell (77.3% OOF). Injected as brain features, the whole direction block was worth
**0.59% → 0.83% combined gain** — marginal.

**Why retired.** Three escalating verdicts. (a) As features: sub-1% gain. (b) As a live V5 module
(`direction_v2`/`momentum_v3` "certainty" stack): the broker tape showed the brain **anti-calibrated** —
`m_cert` *negatively* correlated with wins over the live window (broker, 36 V5-era trades). (c) As a
question: the truth-matrix test returned **0/144** robust signed-direction relationships, and the edge
hunt falsified direction prediction structurally. The certainty stack was archived at the cell-era
cutover (2026-07-04); re-derivation showed its raw-indicator locks survived verbatim while the composite
certainty scores were proxies at best.

**Artifacts.** `direction_ml.tar.gz`, `direction_artifacts_v2.tar.gz` (see the catalog).

---

## 3. pips_brain v3 → v4: the "no bias in training" rebuild

**v3 — the net-ladder committee (live until 2026-06-13).** A committee of raw-continuous LightGBM heads
(`p7`/`pmom`/`pfast`/`pbig`/`eoffer`) scoring candidates against the capped `net_ladder` exit label,
gated at a hand-set floor (raised 0.50 → 0.65 in its final session). Its live character: a capped-exit
fade-scalp brain — ~+8p picks with near-zero losses, but only ~2% of candidates cleared, and it
structurally *could not chase big wins* because its own training label capped them (sim).

**The rebuild philosophy (Brock, 2026-06-13, firm).** Every place human judgment had been imposed on
what the model *learns* was removed: threshold targets → predict the raw continuous outcome; dropped
"noise" features → include ALL ("you don't decide what's noise"); curated trades → train on all pairs,
all 21 strategies, winners AND losers; hand-picked calibration floors → deleted. **The objective is
allowed — what counts as "good" is the goal, not bias.** Brock's pip-utility curve encoded the goal:

```
net < −6      →  2·net        losses past −6 cost double to recover
−6 ≤ net < 20 →  net − 6      +6 pips is the floor of "good"
20 ≤ net < 30 →  2·net − 26   bonus for letting winners run
net ≥ 30      →  3·net − 56   big bonus for the rare big runs
```

**v4 — the utility brain (live 2026-06-13 → V4 retirement).** A single LightGBM regressor predicting
`E[utility]` on the **`net_ratchet`** label (the live ratchet exit simulated over the forward path, ~1p
assumed cost) from ~57 raw indicators + pair/session/direction — no buckets, no `strategy_id` shortcut,
direction-keyed end to end. Gate: take iff `E[util] ≥ floor` (top-2% threshold). Golden-set locked at
serving (boot-time refusal on drift, not a months-long bleed). A methodological aside from its own
training: AUC is the *wrong* scorecard for a gated brain — the corpus includes losers on purpose so the
model learns the boundary; judge by outcomes on the trades it *picks*.

**Measured (sim).** 8-pair deploy at floor 2.90 (top-2%): OOS selected **+4.86p/trade**, 20%/11% of
picks reaching +20/+30, utility +2.68. Majors strong (USD_CAD +12.4p at 23% loss rate); JPY pairs
positive but high-variance and volume-dominant. Walk-forward positive 2022–26 (2021 weak). A real
train/serve bug was caught and fixed in passing: the live feed fetched only 60 M5 bars where the corpus
used 320, serving `OBV_z`/`realized_vol` as NaN — window bumped, parity verified.

**Why retired.** The brain itself was never falsified in isolation — it was carried into the bucket-keyed
era (§5) as BUCKET21 and retired with all of V4 at the 2026-06-18 cutover; and the broader verdicts (its
`net_ratchet` label under-charged real trail slippage by 2–4p, §6; the live book under all brains was
losing on broker truth, §10) removed its reason to exist.

**Artifacts.** `pips_brain_v3_2026-06-13.tar.gz`, `pips_brain_v4.tar.gz`.

---

## 4. The exit-brain family

Exit ML ran parallel to entry ML, always as an *overlay* on deterministic exits:

- **The floor-0.65 net_ladder committee** (above) doubled as the exit-era judge until the exit-bottleneck
  finding (B-076: the ladder banked ≥20p on 0.0% of trades while 70% of winners ran +20) made its label
  obsolete — the committee was fallback-retained for harvest mode, never falsified, just superseded by a
  better label.
- **The E[utility]-on-net_ratchet brain** (§3) — after the three-way exit bake-off (ratchet **+3.28p** vs
  harvest +0.75p, sim, 8yr M5) the entry brain was retrained on what the ratchet actually earns.
- **The continuous 8-pair exit brain** (`exit_serving_cont.py`): an XGBoost regressor predicting
  *remaining MFE* from the raw continuous entry vector + profit-so-far + recent range + bars elapsed —
  no factor buckets (the JPY sidecars never had them; going continuous was the clean fix). Holdout
  correlation **0.87** vs the old 4-pair bucketed model's 0.75; behaviorally sensible: RIDE calls
  (pred ≥ 25) averaged 52p actual, TAKE calls (pred < 18) averaged 11p (sim). Golden-locked, served as a
  ratchet overlay.

**Why retired.** With V4. The V5→V6 exit line kept the *deterministic* half of the lesson: exit geometry
matched to measured cell excursion class (the three-speed book), with the ML overlay dropped — the
cost-aware exit paper's fill-probability tables do with arithmetic what the exit brain did with a model.

---

## 5. BUCKET21: bucket-keyed gating and the TAKE/AVOID maps

**What it was.** The V4 endgame brain (2026-06-15 →): every strategy (pair × session × direction)-locked,
and the brain given *learned context maps* as features. The 128 buckets = 8 pairs × 8 sessions × 2
directions.

**Training data + objective.** `util(net_real)` — the utility curve on a realistic-cost label with 3–4p
slippage already charged (the lesson of the same-day range-expansion failure, §6). Feature set: 53 raw
indicators + 4 identity + 2 map features, 28 strategy categorical levels.

**Measured (sim).** The map features dominated: `bucket_take_score` 9.8% gain (#1) +
`bucket_avoid_score` 6.5% (#2) — **16.3% combined**, ahead of every market indicator. The maps held
1,769 TAKE and 16,026 AVOID conjunctions; the AVOID side's weight is the finding that *what NOT to
trade is informationally as valuable as what to trade*. And the era's honest baseline: **all 128 bucket
baselines were negative on net_real (−2.05p avg)** — the strategy book traded blindly was a uniformly
losing operation; whatever edge existed lived *only* in brain-filtered, bucket-gated firings. Enumeration
yields were brutally selective: 9,600 K=2 atoms → 104 survivors (0.5%); 918 9-combos → 5; 284 box/dbb
cells → 2.

**The structural failure (the reason this section is a cautionary tale).** The AVOID map grew faster
than the TAKE map with every leaker hunt until the brain's critical zone covered the live regime and the
bot **silently stopped trading** (2026-06-15). Two numerical quick-fixes failed (floor hack; AVOID
rescaling — the brain just relearned the slope). The real fix was evidentiary: a **walk-forward gate**
run over all 23,211 AVOID conjunctions killed **65%** as in-sample overfit (the worst source,
`K2_avoid_enumeration`, 80% killed). The pruned brain's admissible share went 4.6% → 24.6% of corpus.
Cost of the whole broken-brain era as later accounted: a **$626/day bleed for 14 days** (live) before
the silence forced the diagnosis. The gate became the architecture: from then on, *nothing wires live
until it earns it on unseen forward data*.

**Why retired.** With V4 at the 2026-06-18 cutover, seven days into the brain-version arc (v3 → v17:
pruned maps v12, direction features v15, vol-amplifier v16, amplifier-rescue cells v17). The final
sniper-narrow 211-plugin book had produced **no live trades** by the cutover — corpus-validated, never
live-validated.

**Artifacts.** The BUCKET21 series + `bucket_take_avoid_maps.json` inside the V4 models tree (catalog:
"V4 models/artifacts"); the strategy roster in the archived encyclopedia (condensed:
[`historical/RETIRED_STRATEGIES.md`](historical/RETIRED_STRATEGIES.md)).

---

## 6. The strategy-discovery engine: the ML as author

**What it was.** The franchise turn (2026-06-14): instead of judging human strategies, the ML *proposed*
its own. Pipeline: build an **unbiased all-bars corpus** (674k rows, 7yr, *every* bar sampled, both
directions, net_ratchet-labeled — removing the where-humans-fire bias); rank all 57 indicators by
two-head LightGBM gain; rank value-levels within each; enumerate conjunctions (apriori-pruned); score;
**discover on 2019–2022 only, validate on unseen 2023–2026**; formalize survivors as explicit named
rules.

**Measured (sim).** The headline OOS result of the whole ML program: **51 of 52** discovered strategies
stayed positive on unseen years — 23,095 fires · 66% win · **+8.42p** vs a +1.4p all-bars base, stable
year-by-year through 2020 and 2022. One robust edge emerged: **trend-pullback** (`trend_4h_pct` the only
strong standalone driver; `ema20_dist_pct` #1 by gain but interactive — the linchpin *partner*).
Widening the indicator set added alternative partners, not new edge families — reach ~12× at an
undiluted +6.5p. A separate 30/30-positive multi-fold stress check through 2020/2022 exists but is
**in-sample** (selection used those years); the walk-forward is the verdict that counts. Wired live
2026-06-14 as 30 `ml_tp_*` plugins after live-featurizer verification (891 fires · 84% · +14.85p, sim on
live code path).

**The failure that scoped it (same day).** A breadth expansion (42 broad value-range `ml_rng_*`/
`ml_drop_*` strategies at floor 0.0) lost **~$628 in 5 hours live** and was un-wound. Root causes, each a
program lesson: (1) `net_ratchet` labels assumed 1p cost but the **real ratchet trail slips 3–5p** (US
account: guaranteed stops disabled; the trail is a plain stop-market) — the backtest overstated edge by
2–4p, fatal to near-zero-edge admits; (2) floor-0 admitted ~0-E[util] trades by design; (3) the brain
over-rated strong-trend setups that were higher-timeframe-countertrend. The narrow 30-strategy core
stayed; the broad book did not.

**Why retired.** The `ml_tp_*` roster was preserved aside and then retired with the strategy concept
itself at the V5 cutover. The later factor verdict (2026-06-16) explains why the discovery could not
simply be re-run for more: its surviving edge was **concentrated and collinear** — dozens of "survivors"
were the same AUD_JPY-short phenomenon measured different ways, and no new cells could be expanded from
the corpus. Method validated; portfolio not.

**Artifacts.** `allbars_corpus.tar.gz`, the discovery scripts in `scrooge_research_scripts.tar.gz`,
`factor_lift_v1.tar.gz` (the adversarial-validation rig that scoped it).

---

## 7. The sealed ML Lab: research with a promotion gate

**What it was.** A deliberately *sealed* research instance (built from 2026-06-04) on separate lab
hardware: read-only on the live bot's decision streams and OANDA transactions, seeded with a clone of the
live edge, **never able to place orders or write live config**. Its output surface: protests,
opportunities, mined cells, drift reports — every proposal backtested, then *manually* wired, never
auto-applied.

**Measured (sim — the five-step promotion gate, run 2026-06-04).** The lab's validated result was a
two-layer selector: the **miner map** (cell-specific align≥3 allow-list; 19 of 25 candidate cells held a
chronological OOS split) plus an **instance-level ranker** (gradient-boosted win classifier). Under the
live green-exit ladder: take-all −0.09p · miner map +0.94p · ranker top-30% +1.59p · **layered +3.09p**
(n=4,919, WR 60%) vs the deployed align=4 book's +1.81p. The gate then hardened it: 5/5 expanding
walk-forward folds positive and above the book; retrained in real LightGBM the layered edge reached
+3.49p idealized; and — the deployability step — translated from a global top-30% sort (not realizable
live) to an **absolute p_win threshold**: +2.96p at q70, or the low-risk variant (unchanged align=4 book
+ ranker cutoff) at +2.85p. A flagged theory ("live p_win compression = a broken feed wire; fixing it is
the biggest gain") was **refuted** by a controlled comparison — the win was replacing the
wrong-granularity family-level v0 gate with an instance-level model, not patching a wire. The verdict
rule that generalized: **read the structural map's EV, not the ranker layer's EV** — the map (where the
edge lives) carries the result when the ranker's AUC goes weak out-of-regime, so promotion decisions key
on map EV with the ranker as a selector on top.

**The hard caveat (why it never went live).** All of it stood on a **6-month corpus** (Nov 2025 – May
2026) — no 2020/2022 regime evidence. The gate's own verdict: paper-first, and extend the corpus before
any expansion. A faithful 7-year signal-corpus backfill was launched (using the *real* V3 generator,
recovered after an earlier wrong "it's lost" conclusion — the origin of the *find-the-real-tool* rule;
the assembler validated 14/14 factors against the existing corpus). **The V3 line was retired on
2026-06-16, days later, before the regime-gate re-run concluded** — no record of a completed 7yr
re-verdict was found, and the wiring proposal (Path A/B) was never deployed. The lab's promotion-gate
discipline, not its selector, is what carried forward.

**Artifacts.** Lab scripts/models per the build spec (`ml-lab/` tree inside the V3 full mirror);
`ml-observer-v3era.tar.gz`; the staged `v1_instance` LightGBM artifact (model.txt + feature_meta.json).

---

## 8. The cellular-knowledge pattern loop

**What it was.** A nightly cron on lab hardware: seed RNG by date → pick a random ~10–15-indicator
subset → beam-search high-purity winner (≥+6p) / loser (<0) fingerprints → **OOS-validate each on a
150-day time holdout** (most runs add nothing — correctly rejecting training flukes) → dedup and
accumulate into a persistent `cellular_knowledge.json` (re-finds increment a confirmation counter).

**Measured (sim).** The durable asymmetry: **loser fingerprints reach ~94% purity; winner fingerprints
cap at ~65%.** The highest-value patterns are "never trade this," not "always trade this" — avoiding
pure losers beats chasing pure winners.

**Why feeding patterns back as features was rejected (don't re-litigate).** Tested and refused: the
brain already encodes the strong patterns (a known loser fingerprint scored ≈ −7 with ~98% of its
instances auto-declined at the floor), and bolting mined indicators on as features *hurt* the existing
book (−1.09p). The right transmission was **retraining on the label** — the brain absorbs patterns via
the relabel→retrain loop, while the miner's real value is the **X-ray** (visible failure modes) and the
**early-warning radar** (pockets the static brain mishandles). The companion continuous-learning loop
(relabel live fills nightly → retrain on lab hardware → golden-gated deploy that can never downgrade)
ran live from 2026-06-13 and immediately earned its keep by catching that the deployed brain was
**180 days stale**, promoting a fresher one (+1.48 holdout utility).

**Artifacts.** `pattern_loop.py`, `cellular_knowledge.json` and the relabel/retrain scripts (archived in
the session-notes loose files and `scrooge_research_scripts.tar.gz`).

---

## 9. Results summary (all systems, scoped)

| System | Best measured result | Scope | Live verdict |
|---|---|---|---|
| Direction ML (Phase 2) | 68.9% median OOF; 57/92 cells activated | sim | features worth <1%; V5 stack anti-calibrated on broker tape; 0/144 direction |
| pips_brain v3 (committee) | ~+8p picks, ~2% admit rate | sim | superseded — its own label capped winners (B-076) |
| pips_brain v4 (utility) | +4.86p OOS selected at floor 2.90 | sim | retired with V4; label under-charged slippage 2–4p |
| Continuous exit brain | corr 0.87; RIDE 52p vs TAKE 11p | sim | retired with V4; replaced by deterministic exit classes |
| BUCKET21 + TAKE/AVOID | maps = 16.3% of gain; pruned brain 24.6% admissible | sim | 65% of AVOID map was overfit; $626/day × 14d bleed (live); no live trades by cutover |
| Discovery engine | 51/52 strategies +8.42p on unseen years | sim | breadth variant lost $628/5h (live); core retired at V5 cutover |
| Sealed ML Lab | layered selector +3.09p vs book +1.81p, 5/5 folds | sim | never wired (6-month corpus caveat; V3 retired first) |
| Pattern loop | loser fingerprints ~94% pure | sim | kept as X-ray only; feature feedback rejected (−1.09p) |

The column that matters is the last one. Every sim edge that reached the live tape was consumed by some
combination of cost, slippage, leakage, overfit maps, or regime — and the live book across the whole ML
era was net losing on broker truth (−$6,114 over the final 120 V4+V5 trades; ~83% of a five-week loss
window was transaction cost).

---

## 10. Why the cell-era V5/V6 bot runs no live ML

The ending is undramatic and evidence-shaped:

1. **Broker-fill truth arrived** (2026-06-20/21) and the brains failed it. The measurement overhaul
   found the journal had missed 70 of 120 real trades, the V5 brain's certainty anti-calibrated, and
   ~5 winner cells out of 48 — none of which required a model to trade.
2. **The corpus evidence was re-based.** The H1 look-ahead leak (B-078, fixed 2026-07-03) made every
   pre-fix H1-feature backtest an upper bound — retroactively softening the very numbers the brains had
   been promoted on.
3. **Direction died as a question.** 0/144 signed-direction relationships; five falsified edge families;
   the market telegraphs WHEN and HOW FAR, never WHICH WAY. A direction-predicting model has nothing to
   predict.
4. **What remained didn't need ML.** The surviving structure — per-cell excursion geometry, cost floors,
   session-sized stops, ratchet exits — is arithmetic on measured distributions. The cost-aware exit
   book does with fill-probability tables what the exit brain did with a regressor, and is auditable.
5. **Sample-size honesty.** Cells produce 5–50 live trades per config era. No per-cell model can be
   trained or validated at that n; deterministic rules with n≥20 governance can at least be *judged*.

What the ML program left behind is doctrine, all of it live in V5/V6: walk-forward as the activation
primitive; unbiased training with the opinionated objective ("the objective is the goal, not bias");
train/serve parity as a tested invariant; golden-gated deploys that can never downgrade; judge a
selector by the trades it picks, not population AUC; avoid-knowledge is as valuable as take-knowledge;
and the sealed-lab separation of research from execution. If a future edge earns a live seat through the
walk-forward + slippage gauntlet, the serving scaffolding (golden sets, floors, parity checks) exists
and is documented. Until then, **the bot's intelligence is its measurement.**

---

## 11. Limitations

1. **Retrospective, written from contemporaneous notes.** Sources are the dated vault/session notes and
   retired-repo docs (provenance in §12); where a note's number could not be independently re-derived it
   is reported as recorded, with scope.
2. **Sim numbers carry the era's known inflators:** `net_ratchet`'s ~1p cost assumption (real trail
   slippage 3–5p), pre-B-078 H1 features (upper bounds), and uncapped-ratchet magnitude tails.
3. **Not exhaustive.** V3's meal-cell/matrix-router ML prehistory (pre-May-28 archive sweep, much of it
   survivorship-biased and buried by its own audit) is summarized only where it shaped later systems.
4. **Unresolved threads are stated as unresolved:** the ML Lab's 7-year regime re-verdict (launched, V3
   retired first) and the exit-brain auto-retrain extension were never completed.

## 12. Data availability

Every model and corpus named here is catalogued with framework, training data, era, leak status, and
archive path in [`../DATA_AND_MODELS.md`](../DATA_AND_MODELS.md) (public archive link at the top of that
file). Primary written sources: the operator's dated research-session notes (Dropbox
`/SCROOGE ARCHIVE/session-notes/`, 2026-06-04 → 2026-06-15 for the systems here), the retired V4 repo
docs (`/SCROOGE ARCHIVE/docs-harvest/v4-repo-docs/`: `RESEARCH_METHODOLOGY.md`, `BACKTEST_RESULTS.md`,
`STRATEGY_ENCYCLOPEDIA.md`, `FACTOR_RESEARCH_VERDICT.md`), and the ML-lab build/findings/wiring notes
(2026-06-04). Related defects: B-076 (exit bottleneck), B-078 (H1 leak), B-084 (journal gap), B-085
(dead live factors). See [`../BOOK_OF_BUGS.md`](../BOOK_OF_BUGS.md).
