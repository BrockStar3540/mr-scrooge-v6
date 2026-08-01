# External-repo strategy audit — 2026-07-31 (Brock's slate)

Six public trading-bot repositories audited at source level (code, datasets,
backtests, execution paths — not READMEs). Verdict: **none contains a
demonstrated, deployable edge.** Two contained ideas worth trialing at zero
authority; two contained dashboard patterns worth borrowing.

| Repo | Strategy | Edge evidence | Verdict |
|---|---|---|---|
| naimkatiman/tradeclaw (MIT) | weighted RSI/MACD/EMA/BB/Stoch votes; VWAP-EMA-BB pullback variant | its own costed BTC H1 test: PF 0.809, −11.12%, all walk-forward folds nonpositive | borrow the EVIDENCE SYSTEM, trial the VWAP pullback at zero prior |
| logiccrafterdz/EuroScope (MIT) | regime-routed trend / mean-reversion / breakout | committed "performance report" = ONE smoke-test trade | trial the regime split at zero prior; borrow ops-shell ideas (kill switch, data health, decision reasoning) |
| NadirAliOfficial/monsterfx (MIT) | EMA cross + filters | none; claimed bot file is 1 byte, EA uncompilable | nothing to take |
| 26medias/bot-lazy-trader (NO LICENSE) | weekly straddle | code contradicts strategy (LIMIT where STOP required) | nothing; unlicensed — no code reuse |
| ryu878/MT5-python-bot (Apache-2.0) | unbounded adverse averaging, needs >92.86% WR to break even | none (author calls it a learning experiment) | nothing |
| Cortex-AI-Network/crypto-arbitrage (MIT) | `random.uniform(140,145)` presented as arbitrage scanning; fabricated tx results | fabricated | table LAYOUT only; never run its binary or give it credentials |

## What was actually taken (v6.16.0)
- 42 zero-authority SHADOW cells (`tc_vwapbb_*` ×24, `es_trend/meanrev/breakout` ×18),
  each carrying its source's honest evidence note (including TradeClaw's own negative test).
- Feed features `vwap_dist_pips` + `adx14` to express them faithfully.
- Dashboard: evidence-accounting chips, open-floor risk truth, freshness, the governor
  decision ledger, prospective score snapshots, and the Δ_promotion metric — all re-based
  on family cycles and risk units, never heuristic "confidence."

Provenance note: this audit and implementation spec came from a separate agent session
whose branch was stranded in an unpushable workspace; re-implemented from its published
spec on 2026-07-31.
