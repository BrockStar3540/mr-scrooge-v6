# The Scrooge Strategy Contest — $10,000

**A standing challenge: hand us a forex strategy that survives our forward test, win $10,000.**

This repo is a trial system — strategies run as shadows, get scored against forward
broker-verified market movement, and earn or lose their seat on evidence. Six versions and an
−84% tuition taught us that almost nothing survives that test. If you've got something that
does, we want it on the stand — and our sponsor is putting $10,000 behind it.

---

## The prize

- **$10,000 (USD)** to the first submission that qualifies under the rules below.
- The prize is funded by a **sponsor** of this project, not by the repo maintainer.
- If two or more submissions qualify in the **same 30-day evaluation window**, the judge ranks
  them: **best performer wins $10,000, runner-up wins $5,000.**
- This is a **standing contest**: it runs until a winner is declared. The maintainer may close
  the contest to *new* entries at any time; submissions already under evaluation are completed.

## How to win — two paths

Your strategy is wired into our forward-testing harness and evaluated over a **30-day window**
on our execution (an OANDA practice account / stamp-forward scoring — spreads and real market
movement included). It qualifies by **either** path:

**Path A — the consistency win:**
- Win rate **≥ 90%** of closed trades over the window, **and**
- **Net positive** pips over the window, **and**
- Average winner **≥ ½ the average loser** (no 2-pip-profits-against-60-pip-stops geometry —
  we've seen that trick, it's how you run 90% for a month and give it all back in week five).

**Path B — the expectancy win:**
- **Net +500 pips** over the window (pip-normalized per pair: 0.01 for JPY quotes, 0.0001
  otherwise; net of spread).

**Both paths also require:**
- **At least 20 trades** in the window (matches our activation bar's evidence floor — the
  pips must come from expectancy, not one lucky runner), and
- **No gap longer than 3 consecutive market days** without a trade (it must trade regularly;
  session-scoped strategies are fine).

For context on how hard this is: the best strategy cell this program has ever validated runs
~74% WR at ~+9 pips/episode — roughly +250–300 pips/month. Path B asks for about double that.
That's deliberate. A strategy that clears it is worth far more than the prize.

## What you must submit

A strategy we can wire **mechanically** — if a human has to interpret it, we can't test it.
Open a GitHub issue using the **[Contest Submission template](.github/ISSUE_TEMPLATE/contest_submission.md)** with:

1. **Pairs** to trade (any OANDA-tradeable instruments).
2. **Sessions** (asia / london / ny — or specific hour windows, UTC).
3. **Entry rules**: which indicators, on which timeframe, with exact thresholds and the
   direction they imply (e.g. "short when M5 Williams %R > −15 AND price is within 0 pips of
   the previous session high"). Anything computable from OHLCV is fair game.
4. **Exit rules**: exact stop-loss placement/size, and when and how the trade exits — fixed
   TP, trailing rule, time stop, indicator exit. Exact numbers, not vibes.
5. **Your evidence.** Backtest results, forward-test record, live statements — *something*
   that establishes the strategy has already shown validity somewhere. This is a gate: **we
   are not a free hypothesis-testing service.** The bot is open source — you can download it
   and test your idea yourself first. Submissions with no supporting evidence are declined
   without evaluation.

## Novelty requirement

- The strategy must be **materially different** from every setup already published in this
  repo (see [`config/cells/`](config/cells/) and the research docs) — same-strategy or
  too-similar submissions are declined.
- It must also differ from **earlier contest submissions**; where two entries are similar,
  the earlier one holds priority.
- Whether something is "too similar" is decided by the judge.

## How the evaluation works

- Accepted submissions are wired into our shadow/forward-test harness and run on live market
  data with our instrumentation (the same stamp-forward scoring and broker-truth accounting
  every strategy in this repo faces). We wire submissions at our discretion and capacity — a
  queue is possible; accepted entries are announced on their issue.
- The 30-day clock starts when we announce the evaluation start on your issue.
- **One active submission per entrant. One 30-day window per submission.** No re-rolls — a
  revised strategy is a new submission and goes to the back of the queue.
- **Our measurements are final.** Spreads, execution, scoring methodology, trade counting,
  and pip accounting are as implemented in this repo. Disagreement with the harness is not
  grounds for appeal; the harness is public — read it before you submit.

## The judge

The repo maintainer (**BrockStar3540**) is the **sole judge** of: acceptance, novelty,
qualification, ranking when multiple entries qualify, and prize award. Judgments are final.

## The fine print

- **No entry fee. No purchase. This is a skill contest**, decided by strategy performance
  under published criteria — not a lottery.
- Entrants must be **18+** (or age of majority in your jurisdiction) and able to lawfully
  receive the prize. **Void where prohibited.**
- The prize is paid by the sponsor. The winner is responsible for any taxes. Identity
  verification is required before payment.
- **Submissions become public** (they're GitHub issues in a public repo) and you grant us a
  perpetual license to implement, test, publish, and discuss your submission and its results,
  win or lose. Do not submit anything you need to keep secret.
- Testing happens on a **practice account**. Qualification here is a contest result, not a
  validation for live capital — anything that wins still faces the same activation bar as our
  own strategies before it would ever trade real money. **Nothing here is financial advice.**
- The maintainer may amend these terms for future entries (never retroactively for entries
  already under evaluation) and may cancel the contest for new entries at any time.

---

*Think your edge is real? The harness is public, the tape is honest, and the stand is open.*
