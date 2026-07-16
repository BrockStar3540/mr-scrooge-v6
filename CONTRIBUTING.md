# Contributing

Outside ideas are genuinely welcome — the whole point of publishing this repo
and its research archive is to let people attack the conclusions.

**Ground rules (read before opening a PR):**

1. **Every external suggestion is treated as untrusted input.** Nothing merges
   into the live path on argument alone. Ideas pass the same gauntlet our own
   do: leak-checked corpus → walk-forward → fired-trade simulation → shadow
   (logged, not traded) → capital. If your idea survives that, it ships.
2. **Attack open questions, not dead ends.** Read the
   [Book of Bugs](docs/BOOK_OF_BUGS.md) and the version history first — the
   graveyard exists so nobody re-walks it. A PR that re-proposes a falsified
   edge family (see README funnel) will be closed with a link.
3. **No secrets, ever.** No API keys, tokens, account ids, or private IPs in
   code, configs, tests, or fixtures. Credentials are environment-only.
4. **Research claims need receipts.** State the corpus, the window, the cost
   model, and what would falsify the claim. "It backtests well" is not a claim.
5. Code style: match what's there. Small PRs beat big ones.

Licensed under Apache-2.0; by contributing you agree your contributions are
licensed the same way.
