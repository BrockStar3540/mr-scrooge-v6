# Mr. Scrooge — The Book of Bugs

**Living institutional memory of every documented defect across the bot family (V1 → V6).**
Format per entry: id · era · area · symptom · root cause · fix · lesson. When something odd
surfaces, this book answers *"have we seen this before?"* before anyone re-derives it.

This is the single canonical copy. It began as a vault-hosted catalog (V1–V3) plus a repo
stub (V4–V5); the two were merged here so a reader with only this public repo has the whole
book. Nothing points off-repo for the content itself — the only external references are the
Dropbox `/SCROOGE/SCROOGE ARCHIVE/` paths where the original forensic source material (daily notes,
postmortems, commit-linked audits) is filed.

**Coverage:** B-001 → B-125, all recoverable, all present below (B-091+ = V6.1 live era). See *Records not recovered*
at the end — as of this consolidation there are **no gaps** in the B-001→B-090 range.

**Recurring-pattern index and "bugs that shaped architecture" tables are at the bottom** —
read those first if you want the compressed lessons rather than the chronology.

---

# V1 — "The Box Bot" era (≈ Feb–Mar 2026)

Source material: `scrooge-v1-exec-summary-feb-2026` (3 audit passes), `AUDIT.md` from the V1
repo, daily notes Mar 6/11/12/19/20/24. Public-safe forensic export archived at
`/SCROOGE/SCROOGE ARCHIVE/V3/scrooge-bug-catalog-V1-V3-export-2026-07-05.md`; raw daily notes at
`/SCROOGE/SCROOGE ARCHIVE/session-notes/2026-03-*`.

## Pre-deployment audit (Feb 2026)

### B-001 — Sucker-move termination not at zone
- **Area:** `signal_engine.py`
- **Fix:** enforce sucker-move termination at the pre-identified zone (Gate 4 logic).
- **Lesson:** behavioural patterns need explicit geometric anchoring; "moves *into* a zone" ≠ "moves *to* a zone."

### B-002 — Tier-1 zone test-count requirement
- **Area:** `zone_detector.py`
- **Fix:** Tier 1 requires daily alignment only, no test count.
- **Lesson:** over-specified zone classification rejected valid setups.

### B-003 — Time exit firing after TP1
- **Area:** `trade_manager.py`
- **Fix:** time exit only fires before TP1; trailing winners after TP1 run free.
- **Lesson:** time-based exits should never cut winning trades short.

### B-004 — Open-wait blocked premium setups
- **Area:** `main.py`
- **Fix:** open-wait exception at 50% size for Tier-1 + 80%+ ATR + John Wick / Power of Towers.
- **Lesson:** rules need escape valves for highest-conviction setups.

### B-005 — Gap detection not at boot
- **Area:** `zone_detector.py`
- **Fix:** gap detection redraws the box proactively before the first candle is evaluated.
- **Lesson:** boot-time state can't assume "no special conditions."

### B-006 — Box trade counter only incremented on entry
- **Area:** `main.py`
- **Fix:** new-box trade counter increments on every close.
- **Lesson:** per-box counters need to track both sides of the lifecycle.

### B-007 — Re-entry not wired
- **Area:** `main.py`
- **Fix:** re-entry wired via `assess_reentry()` on break-even stops.
- **Lesson:** liquidity-sweep theory needs explicit re-entry logic; absence is silent failure.

*(Two more pre-deployment items were "non-issues on closer inspection — implementation already matched spec intent.")*

## Live-deployment audit (Feb 2026 — Scrooge/forex + Sprite/crypto)

### B-008 — OANDA candle fetcher filtered the current forming bar
- **Symptom:** ATR consumed always appeared 100–120%.
- **Root cause:** fetcher excluded the in-progress bar from the ATR window.
- **Fix:** include the current bar.
- **Lesson:** "current forming bar" can be valid data depending on use case; default filtering is dangerous.

### B-009 — Limit orders rejected `WOULD_TRIGGER_IMMEDIATELY`
- **Symptom:** entry limits rejected by OANDA.
- **Root cause:** price moved past the limit between signal fire and order placement.
- **Fix:** switched to OANDA market orders with TP+SL on fill.
- **Lesson:** stale-price-at-placement is a recurring theme — see B-015.

### B-010 — Missing `register_entry` call → duplicate entries
- **Symptom:** same signal repeatedly entered each cycle.
- **Root cause:** no bookkeeping registered the entry.
- **Fix:** added a duplicate-entry guard.
- **Lesson:** every "entry happened" path needs an explicit state update.

### B-011 — `session_start = datetime.now()` on restart
- **Symptom:** open-wait reset every bot restart.
- **Root cause:** session start derived from process boot, not the actual market open.
- **Fix:** `_compute_session_start()` derives from `SESSION_WINDOWS`.
- **Lesson:** time anchors must be world-state, not process-state.

### B-012 — Missing `timeInForce: FOK` and `positionFill: DEFAULT`
- **Symptom:** OANDA order-field errors.
- **Root cause:** OANDA v20 requires explicit field setting; a sister bot's working client had them and Scrooge didn't.
- **Fix:** added the fields.
- **Lesson:** when a sister bot works and yours doesn't, diff the API payloads.

### B-013 — Units sent as float strings
- **Symptom:** OANDA rejecting orders.
- **Root cause:** `"-2430.0"` instead of `"-2430"`.
- **Fix:** format as an integer string.
- **Lesson:** API field types matter; float-vs-int silently breaks.

### B-014 — `clientExtensions` at order level instead of `tradeClientExtensions`
- **Symptom:** client ID not associated with the trade.
- **Root cause:** wrong key — `clientExtensions` is for the order; trades need `tradeClientExtensions`.
- **Fix:** use the right key.
- **Lesson:** OANDA v20 has parallel order-vs-trade nomenclature; easy to confuse.

### B-015 — `STOP_LOSS_ON_FILL_LOSS` rejection on stale prices
- **Symptom:** OANDA rejected orders when price moved past the stop level between signal and placement.
- **Fix:** staleness check — if current price is at/beyond the stop, skip entry.
- **Lesson:** cousin of B-009. Stale-price-at-placement is structural for any live-trading bot.

### B-016 — Sprite `zone_proximity_pct = 0.3%` (forex default on crypto)
- **Symptom:** ATOM at $1.942, PDL at $1.929 (0.67% away) failed the zone gate every cycle.
- **Fix:** widen to 1.5% for crypto.
- **Lesson:** strategy parameters that work for one asset class don't transfer; defaults are dangerous.

### B-017 — Sprite `cl_ord_id` rejection (Kraken)
- **Area:** Kraken API integration.
- **Lesson:** each exchange has its own ID rules.

### B-018 — Sprite position-size overflow on low-priced coins
- **Symptom:** tight stops on low-priced coins generating 1,000–3,000-unit orders on a $785 account.
- **Lesson:** sizing math has to account for unit cost as well as risk percentage.

### B-019 — Sprite post-only orders never filling at zone entry
- **Symptom:** orders queued but never executed.
- **Lesson:** post-only is wrong for entry-at-zone (need to cross the spread or pay the maker fee).

### B-020 — Sprite Kraken price-precision rejection
- **Symptom:** slippage-buffered prices rejected on precision.
- **Lesson:** each exchange has its own decimal-precision rules per asset.

## V1 discipline era (Mar 5–19, 2026 — source `AUDIT.md`)

### B-021 — Multiple concurrent bot instances
- **Date:** 2026-03-05
- **Symptom:** duplicate log lines; two engines writing simultaneously.
- **Root cause:** restart didn't enforce single-process.
- **Fix:** non-blocking file lock `logs/mr-scrooge.lock` + orphan-process sweep in `start.sh`.
- **Lesson:** process-uniqueness must be enforced, not assumed. The classic operational bug.

### B-022 — RR threshold too high
- **Date:** 2026-03-06 · **Fix:** `min_risk_reward 1.75 → 1.60`.
- **Lesson:** theoretical RR thresholds need empirical validation; 1.75 rejected profitable setups.

### B-023 — Native-close cooldown applied to wins
- **Date:** 2026-03-06 · **Fix:** profitable closes skip cooldown; only losses keep it.
- **Lesson:** cooldown is a loss-control mechanism, shouldn't penalize wins.

### B-024 — Net floor not pip-normalized
- **Date:** 2026-03-07
- **Symptom:** inconsistent profit floor across JPY vs non-JPY pairs.
- **Fix:** `min_net_profit_pips = 7` (was an absolute value).
- **Lesson:** pip-normalize all profit/loss thresholds; absolute units break across pair classes.

## V1 MASTER_THEORY realignment (Mar 11, 2026)

Not bugs per se but a category: **invented rules not in the source theory.** Source: `DAILY_NOTES_2026-03-11`.

### B-025 — Strict consecutive-candle counting in sucker move
- **Symptom:** rejected valid messy/choppy sucker moves (red-green-green-red-green).
- **Fix:** flexible window — count directional candles within `max_candles + 2`.
- **Lesson:** "consecutive" was invented; transcripts allowed pattern noise.

### B-026 — Mixed box-wall / candle-extreme stop placement
- **Fix:** always at the signal-candle extreme.
- **Lesson:** stop placement should match the entry signal's anatomy.

### B-027 — Zone-anchored triggers instead of candle-based
- **Fix:** trigger prices use candle high/low, not zone price.
- **Lesson:** entries trigger on candle behaviour, not zone proximity.

### B-028 — ATR gate (Gate 3) was a hard reject
- **Fix:** demoted to advisory.
- **Lesson:** MASTER_THEORY had no ATR-consumption requirement; the gate was over-engineered.

### B-029 — OTR gate (Gate 6) was a hard reject
- **Fix:** demoted to advisory.
- **Lesson:** same as B-028. Two of six gates were inventions.

### B-030 — Trend filter blocked Tier-1 zones
- **Fix:** Tier 1/2 zones override the trend block.
- **Lesson:** box-extreme entries are valid even against trend (per transcripts).

### B-031 — Hard 30-min time exit cut winners
- **Fix:** 4-hour backstop, only fires if price moved against the trade.
- **Lesson:** time exits should be safety nets, not arbitrary cuts.

### B-032 — `max_reentries_per_setup = 1`
- **Fix:** raised to 3 (transcripts: no hard limit).
- **Lesson:** limits must come from source theory, not gut feel.

## V1 green-exit crisis (Mar 12, 2026 — the most architecturally significant V1 bug)

Source: `DAILY_NOTES_2026-03-12`.

### B-033 — Infinite retry loop on LIMIT-TP rejection **[CRITICAL]**
- **Symptom:** bot tried to set a LIMIT TP after price had already reached/passed the target. OANDA rejected. `green_exit` / `set_tp` handlers fired every cycle with no escape.
- **Root cause:** reactive TP-setting + OANDA's "limit price already at/past market" rejection + no exit-once-rejected logic.
- **Fix:** **removed all reactive TP-setting and market-order exit logic.** Bot becomes SL-advancement only; OANDA's native GTC LIMIT TP at entry (as TP2) handles exit.
- **Lesson:** reactive order modifications in live markets are infinite-loop landmines. Anything that retries a same-cycle rejection needs explicit backoff or removal. **This is the origin of the "the bot never places market orders" doctrine that survives into V6.**

### B-034 — Stop-hit close via market order
- **Eliminated** in the same redesign.

### B-035 — `partial_tp` market close
- **Eliminated** in the same redesign.

### B-036 — Early break-even tied to old partial framework
- **Eliminated.** Replaced with "Stage 1: SL to entry when price reaches 50% to TP1."

## V1 30m-box experiment + 17-bug overhaul (Mar 19–20, 2026)

The experiment failed; reverting introduced 17 incidental fixes. Source: `AUDIT.md`.

### B-037 — `pkill` + `Popen` left orphan processes
- **Fix:** `systemctl --user restart`. · **Lesson:** use the OS supervisor.

### B-038 — `authHeaders()` ReferenceError in dashboard.html
- **Fix:** removed the orphan call (console error).

### B-039 — Timeframe-toggle buttons broken in dashboard
- **Fix:** re-wired the toggle handlers.

### B-040 — SL/TP in equity-% mode produced inconsistent risk
- **Fix:** migrated to fixed-pip: `sl_pips=10`, `tp1_pips=10`, `tp2_pips=30`.
- **Lesson:** pip-based stops give consistent risk across pairs; equity-% drifts.

### B-041 — `max_trade_risk_pct`, `target_profit_pct`, `tp1_allocation_pct` were dead code
- **Fix:** removed (sizing-ref only). · **Lesson:** dead config keys are dangerous — they look like they do something.

### B-042 — `_is_tp_reached()`, `get_position_size_multiplier()` dead code
- **Fix:** removed. · **Lesson:** same as B-041.

### B-043 — ON-DECK badge didn't show at max positions
- **Symptom:** an early return suppressed scoring.
- **Fix:** removed the early return; signals still score when the position cap is full.

### B-044 — Zone-cache poisoning
- **Symptom:** cache written on signal evaluation, not on actual order fire.
- **Fix:** cache write moved into `_fire_entry_candidate()`.
- **Lesson:** caches should only be authoritative on confirmed state changes.

### B-045 — JPY margin sizing wrong **[CRITICAL]**
- **Date:** 2026-03-20
- **Symptom:** all JPY-pair trades blocked.
- **Root cause:** formula was `current_price * margin_rate` (wrong for cross pairs — current_price is in JPY, margin_rate is USD).
- **Fix:** `base_price_usd * margin_rate`.
- **Lesson:** cross-pair pricing requires explicit base-currency normalization.

### B-046 — `equity = NAV` (included unrealized PnL)
- **Symptom:** sizing inflated by unrealized winners.
- **Fix:** `equity = balance` (excludes unrealized PnL).
- **Lesson:** size on realized cash, not paper gains.

### B-047 — Config tab had obsolete fields
- **Fix:** cleaned up.

### B-048 — Stale-candidate fallthrough
- **Symptom:** the top-ranked candidate going stale blocked all entries that cycle.
- **Fix:** ranking loop iterates all candidates until one fires.
- **Lesson:** ranked selection needs explicit fallthrough on staleness.

### B-049 — Dead `leverage` config key
- **Fix:** removed.

### B-050 — Fill-anchored SL/TP not recalculated
- **Symptom:** SL/TP placed pre-fill drifted from the actual fill price.
- **Fix:** after OANDA fill, recalc SL/TP from the fill price and update via `modify_trade_stop()` / `modify_trade_tp()`.
- **Lesson:** pre-fill prices are estimates; post-fill prices are truth.

### B-051 — RR sanity check missing
- **Symptom:** entries firing where actual RR was below `min_risk_reward`.
- **Fix:** block at fire time.

### B-052 — TP1 = 5 pips triggered break-even too tight
- **Symptom:** the 50% ratchet triggered break-even at +2.5 pips — too close to entry, constant scratch trades.
- **Fix:** TP1 = 10 pips → 50% ratchet at +5 pips.
- **Lesson:** tiny TPs cascade into tiny ratchet triggers; widen all together.

### B-053 — Sizing decompressors compounding
- **Symptom:** `get_position_size_multiplier()` applying box-age, off-peak and open-wait multipliers together.
- **Fix:** removed — sizing is straight 80%.
- **Lesson:** multipliers compound; if you can't predict the final value, you don't control it.

---

# V2 — transitional agent era (Mar 21 – Apr 15, 2026)

### B-054 — V2 silent skip from `return None` indentation **[CRITICAL — 4.5-hr outage]**
- **Date:** 2026-03-24 (caught in the morning) · **Commit:** `3203cfe`
- **Symptom:** no signals evaluated for ~4.5 hours. Bot looked healthy, logs continued, positions managed normally.
- **Root cause:** `return None` at 8-space indent in `coordinator.py:process_instrument()` should have been at 12-space (inside the `if not tradeable:` guard). Python parsed it as an unconditional function-level return.
- **Fix:** re-indent.
- **Lesson:** whitespace bugs in Python are dangerous — silent, no warning, no log gap. Mitigation: linters that flag suspicious early returns; review coordinator-level logic. **This is the origin of the live zero-signal-counter alerting.**

### B-055 — 46-order API spam on a dead position
- **Date:** 2026-04-10
- **Symptom:** SL-limit placement firing 46 times on a trade that no longer existed.
- **Root cause:** 4 actors (bot, ratchet, SL-limit, harvester) modifying the same OANDA trade with no shared state; the SL-limit couldn't see the position had vanished.
- **Fix:** introduced `TradeCoordinator` cross-process state file; `is_trade_alive` gate before SL-limit placement; `NO_POSITION_TO_REDUCE` cancel detection.
- **Lesson:** multi-actor systems need shared truth. State scattered across processes produces phantom-action bugs.

### B-056 — Ratchet/harvester SL race
- **Date:** 2026-04-10 (same audit as B-055)
- **Symptom:** ratchet and harvester both moving SL without coordination.
- **Fix:** `sl_owner` field in the coordination file; ratchet checks before pushing SL.
- **Lesson:** single-resource ownership requires an explicit handoff protocol.

### B-057 — Ratchet didn't see harvester tier state
- **Date:** 2026-04-10
- **Symptom:** ratchet's Stage-2 logic didn't know if T1 had been taken.
- **Fix:** ratchet reads `tiers_hit` from the coordination file to sync `partial_1_taken`.
- **Lesson:** cross-actor state must be read every cycle, not assumed.

---

# V3 — "The Matrix Era" (Apr 15 – 2026-06-16)

### B-058 — `_update_sessions` not updating `_last_screen`
- **Date:** 2026-04-09 (commit `28d0642`)
- **Symptom:** session rescan updated `active_instruments` but not `_last_screen`; dashboard showed stale spread/OTR data.
- **Fix:** one-line fix in `main.py` to update both.
- **Lesson:** per-cycle state has dependencies not enforced by types.

### B-059 — `client_id` NameError in `trade_state.py mark_dead()` **[CRASHING]**
- **Date:** 2026-04-15 (commit `8e7f7fa`)
- **Symptom:** harvester crashing on `mark_dead`. · **Fix:** variable-scoping fix.

### B-060 — Execution timing: instant-fill slippage
- **Date:** 2026-04-15 (commit `f28134f`)
- **Symptom:** stop-loss filling instantly on order placement due to fast price movement.
- **Fix:** 4 SL guardrails added.
- **Lesson:** order placement isn't atomic with intent; defenses needed.

### B-061 — Stale harvest LIMITs fired as naked positions
- **Date:** 2026-04-29 (commits `4ad40b3` + `143247d`)
- **Symptom:** orphan harvest LIMITs fired without parent positions (two-pass safety fix).
- **Fix:** pass 1 — GTD + ledger + cancel hooks; pass 2 — orphan sweep walks broker pending orders, not just the ledger.
- **Lesson:** ledger ≠ broker truth. Orphan detection must reconcile both.

### B-062 — Harvest same-cycle race (false `broker_side_gone` cancels)
- **Date:** 2026-04-30 (commits `373085e` + `73be822`)
- **Symptom:** `reconcile_pending_orders` cancelled new harvest LIMITs placed in the same cycle they were created.
- **Fix:** Option B — same-cycle placements union'd into `pending_on_broker`; 3 regression tests added.
- **Lesson:** reconciliation logic must understand same-cycle creates.

### B-063 — Ratchet 0.7 experiment regression
- **Date:** started 2026-04-29, rolled back 2026-04-30
- **Symptom:** `ratchet_lock_pct 0.5 → 0.7` produced −$245/trade across 27 trades.
- **Action:** rolled back to 0.5.
- **Lesson:** single-config experiments need pre-defined rollback criteria.

### B-064 — Strategy attribution fundamentally unreliable **[CRITICAL]**
- **Date:** existed pre-2026-05-04
- **Symptom:** `AuditEvent.strategy` missing/unpopulated; scan-cycle lookup window only 800 lines / ~60 s; many trades classified `strategy=unknown`.
- **Fix:** Patch A (`492a999`) threaded `strategy` through `AuditEvent`; Patch B.right (`73f1e41`) added deterministic `(order_id) → (strategy, scan_cycle)` linkage via `OrderAttributionWriter`.
- **Lesson:** attribution telemetry has to be designed in, not bolted on. Lookback windows that "should be enough" usually aren't. **This dates the trustworthy live-forensic audit window to post-attribution-fix.**

### B-065 — V2 Echo discriminator timeframe mismatch
- **Date:** 2026-05-08 (postmortem)
- **Symptom:** Echo split-point spread = 2.11 across pairs (should cluster near 0.30).
- **Root cause:** `atr_pips / atr_pips_mean_20` compared H1 ATR (V3 feature pipeline) to M5 trailing TR (computed locally) — different timeframes.
- **Fix:** Option 1 — `current_M5_range / mean(prior_20_M5_ranges)` (same timeframe, naturally near 1.0).
- **Lesson:** when two metrics compose into a ratio, name the source timeframe of each at design time. Generic feature names ("atr_pips") are not enough.

### B-066 — V2 corpus parquet engine missing (OOM-adjacent)
- **Date:** 2026-05-05
- **Symptom:** v1 corpus run completed all 18 min of compute, then crashed on parquet write: `Unable to find a usable engine; tried using: 'pyarrow', 'fastparquet'`.
- **Root cause:** used system `python3` (no pyarrow) instead of the research venv.
- **Fix:** switched interpreter + preflight check + CSV fallback + sidecar JSONL append.
- **Lesson:** defense-in-depth on persistence. Long compute should never lose its final output.

### B-067 — V2 corpus aggregator OOM on bootstrap CI **[CRITICAL]**
- **Date:** 2026-05-08
- **Symptom:** aggregator process killed mid-CI computation.
- **Root cause:** `numpy.random.choice(values, size=(n_boot, len(values)))` allocated 5.7 GB for one 360k-trade cell on a 3.7 GB box.
- **Fix:** normal-approximation CI for n≥1000 (saves ~5 GB per large cell); bootstrap for n<1000.
- **Lesson:** bootstrap memory cost is O(n_boot × n). At corpus scale, switch to analytical CI. **This is the origin of the "heavy compute never on the live-trader host" rule.**

## Box-drawing bug family (B-068 → B-074, catalogued 2026-05-11)

The box (daily PDH/PDL liquidity zone) is the foundational reference for every V1/V2 trade.
When it draws wrong, every trade off it is contaminated — so these carry explicit
**contaminated-window** notes for anyone backtesting on live-truth data. Forensic detail:
`/SCROOGE/SCROOGE ARCHIVE/docs-harvest/v3-repo-docs/` and the V1–V3 bug export.

### B-068 — Inverted boxes from a stale 200-bar slice (pre-2026-03-09)
- **Root cause:** `zone_detector._get_prior_day_hourly()` used `iloc[:24]` (OLDEST 24 of 200 bars), pulling data 8+ days old; the percentile filter "cleaned" yesterday's PDH/PDL using ancient bars, producing wildly wrong and sometimes fully inverted boxes (PDL > PDH). Bot took longs in clear downtrends.
- **Affected:** USD_CAD, EUR_NZD, GBP_CAD inverted; EUR/USD PDH inflated +900 pips.
- **Fix:** `iloc[:24] → iloc[-48:-24]` + a PDH>PDL sanity guard (2026-03-09).
- **Contaminated window:** unknown start → 2026-03-09 fix.

### B-069 — 30m rolling-box experiment broke profitability (2026-03-19 → 03-20)
- **Symptom:** replaced daily PDH/PDL with a 12h rolling `_build_30m_box()`; the box shifted every cycle while ATR/OTR/sucker gates were calibrated for daily geometry. Bot bled.
- **Fix:** commit `59e83b9` (2026-03-20) — full revert to the daily box.
- **Contaminated window:** 2026-03-19 evening → 2026-03-20 afternoon (~18–24h). **HARD-EXCLUDE from any live-truth backtest.**

### B-070 — Percentile filter over-clipping shrinks daily boxes (ongoing V1/V2)
- **Symptom:** the percentile filter on spike wicks clipped 0.33–0.39% of real range → shrunk half-box geometry → TPs closer to entry → tighter R:R; also caused crypto box rejection on low-vol days.
- **Fix:** flagged 2026-03-20, never fully removed in V1/V2.
- **Contaminated window:** ongoing through the V1/V2 lifetime (~5–15 pips/pair/day of compressed TPs).

### B-071 — Filtered PDH below market → OANDA 400 rejection cascade (2026-03-25)
- **Symptom:** the percentile filter clipped USD/CHF PDH 0.79248 → 0.78939; a long fired with TP2 = filtered PDH while market was 0.790+; OANDA rejected 5 market orders. `_calculate_targets()` validated `tp2 > entry_price` only, not vs current market.
- **Fix:** validate TP vs current market + cap the percentile filter.
- **Contaminated window:** 2026-03-24 (commit `3f14762e` unmasked this) → V1/V2 lifetime.

### B-072 — Box-reset amnesia at UTC midnight (regime era → 2026-03-29)
- **Symptom:** at 00:00 UTC the daily box recomputes; a pair BLOCKED for hours (score −6) instantly resets — new PDH/PDL → price "inside" → `box_contained(+1)` → prior negative signals forgotten → score jumps −6 → +1 → entry permitted → loss.
- **Affected:** USD/MXN (−$1,197), EUR/CHF, NZD/JPY; likely many pairs across many UTC midnights.
- **Fix:** hysteresis tightened — after BLOCKED (score ≤ −3), recovery requires score ≥ +2 (tag `REGIME_HYSTERESIS`, 2026-03-29).
- **Contaminated window:** every UTC midnight from regime activation through 2026-03-29. **EXCLUDE the first ~2h of every UTC day for pairs BLOCKED in the prior 24h.**

### B-073 — Stale-box snapshot → 7,883-pip absurd TPs (2026-04-09)
- **Symptom:** USD/CHF (×2) + GBP/CAD showed TP2 of 7,883 / 18,400 pips; the box snapshot in `_calculate_targets()` wasn't refreshed and old box carried into target math.
- **Fix:** 3× daily-ATR clamp on TP2 distance (a guard, not a root-cause fix; 2026-04-09).
- **Contaminated window:** unknown extent; conservatively, USD/CHF + GBP/CAD entries 2026-03-31 → 2026-04-09 are suspect.

### B-074 — Regime supervisor judges against the original box during alt-box state (open 2026-04-13)
- **Symptom:** when `using_alternative=True`, the signal engine traded alt-box PDH/PDL but the regime supervisor evaluated against the **original (broken) box** — two boxes of truth for the same instrument.
- **Affected:** USD_CHF, AUD_CAD, USD_MXN `score=1` trades on V1+V2 were ALL alt-box trades — fake-valid scores near the floor.
- **Fix:** score=1 floor (Phase 3A) was a band-aid; a structural fix was flagged for follow-up. Open as of 2026-04-13. **Backtest filter: treat `signal.score == 1` as a known-contaminated cohort; clean filter `signal.score >= 20`.**

---

# V4 — "Bucket-Keyed" era (2026-06-11 → 2026-06-18)

### B-075 — HTF features frozen AND mis-defined (fixed 2026-06-09)
- **Area:** feature pipeline (H20/H60 / htf_pct)
- **Symptom:** higher-timeframe alignment features never updated; values also semantically wrong (1H position-in-range [0..1] where a signed daily return was intended).
- **Fix:** alignment definition corrected + freeze repaired; 8yr re-validation of the align lever.
- **Lesson:** a feature can be wrong twice at once — check *definition* and *liveness* separately.

### B-076 — The exit bottleneck (found 2026-06-13; design defect, not a code bug)
- **Symptom:** harvest scale-out + net_ladder capped winners <20p while MFE showed 70% of winners ran 20p+, 57% ran 30p+ (max 907p).
- **Fix:** full-position ratchet cutover (bake-off +3.28p vs +0.75p harvest).
- **Lesson:** measure what the exit *left on the table*, not just what it banked. "The strategies aren't losers — the exit was."

### B-083 — Silently corrupt archive tarball (ops, 2026-06-18)
- **Symptom:** the V4-cutover Dropbox tarball had the correct size but held 342 of 3,924 files.
- **Fix/doctrine:** verify (`gzip -t` + content hash + file count) BEFORE deleting any source. Size match ≠ verification.

### B-085 — Factor weights dead ("x") live for months (V3/V4)
- **Symptom:** offline factor analysis kept informing decisions while the live wiring had the factors disabled.
- **Lesson/doctrine:** verify LIVE wiring before trusting any offline analysis of "the bot's" behavior.

---

# V5 — "Strategy-Free / The Cell Era" (2026-06-18 → present)

### B-077 — atr_conc scale bug: 14 cells structurally unable to fire (fixed 2026-07-03, `2c7367a`)
- **Symptom:** the feature lived in (0,1); profile gates required ≥4.0 → those cells could never fire, since V3-era activation.
- **Lesson:** every gate needs a fire-rate audit; a gate that never passes is indistinguishable from a bug-free filter unless you count.

### B-078 — H1 look-ahead leak in 8yr research parquets (found+fixed 2026-07-03)
- **Symptom:** all H1-feature research numbers pre-fix were optimistic upper bounds (some findings inflated 8–15× via overlap on top).
- **Fix:** parquets rebuilt leak-clean; affected findings quarantined + re-based (see `research/README.md` truth hierarchy).
- **Lesson:** leak-test the corpus BEFORE the discovery program, not after; label every artifact with its corpus generation.

### B-079 — Engine multi-open handling (fixed 2026-07-01)
- **Symptom:** concurrent-position bookkeeping defects when multiple pairs opened in one cycle.
- **Fix:** engine open-loop rework in the 07-01 throughput session.

### B-080 — ev_seq None crash (caught pre-flight, Phase D cutover 2026-07-04)
- **Symptom:** cell setups without ev_seq evidence crashed intent formatting at the cutover boundary.
- **Lesson:** schema-optional fields need explicit None paths the day a new config generation ships.

### B-081 — CAL scorer defect (fixed 2026-07-04)
- **Symptom:** the calibration truth-matrix scorer mis-read live expected-pips stamps in its first cycle.

### B-082 — Aggregator rules inverted by regime drift (retired 2026-07-03)
- **Symptom:** `atr_h1_relative`-keyed amplification rules validated on the 8yr corpus had INVERTED sign in 2026 (297k-bar confirm study).
- **Fix:** all aggregator rules emptied; per-cell evidence replaced global rules.
- **Lesson:** a rule validated on an 8-year average is a bet that the current year is average.

### B-084 — Journal-derived trade analysis missed 70 of 120 real trades (2026-06-21)
- **Symptom:** the bot journal logs INTENT (SIGNAL/ENTERED); fills, manual closes, spreads and realized P/L exist only at the broker.
- **Fix/doctrine:** the broker API is the sole trade-truth source; the journal is for wiring audits only.

### B-086 — Rollover stop-slippage wash class (measured 2026-07-04, fixed 2026-07-05)
- **Symptom:** ratchet locks filling ~0 despite +5p locked: at 21:00 UTC half-spreads blow out 4–10×, stops trigger on the widened side and slip (worst live specimen: +5.0p lock → +0.3p fill; slippage p90 8.8p in that hour vs 0.0p median otherwise).
- **Fix:** global 20:55–22:05 UTC stop-freeze (no tightening, no bot-side closes) + FAST cells exit via server-side limit TP (cannot slip) + no FAST entries ≥20:00 UTC.
- **Lesson:** the fee isn't charged twice — the wash mechanism is *slippage at spread blowout*; guard the clock, not the lock size.

### B-087 — Dashboard set-serialization crash (V3-era `/api/data`; pattern recurred in V5 dashboards)
- **Lesson:** every state endpoint needs a defensive serializer; one non-JSON type must degrade to a stub row, never a 500.

### B-088 — V4 wrapper alias direction mismatches (found 2026-07-09, read-only archaeology)
- **Area:** V4 `plugins/strategies/` wrappers vs `_v3_triggers/textbook.py` `_RENAME_MAP`
- **Symptom:** three wrappers' docstrings claim the trade direction was flipped at the 2026-06-17 rename (williams_extreme_fade "goes LONG", vol_coil_fade_long "goes SHORT", zscore_extreme_fade_l 'hi'→SHORT) but the alias map resolves each to the ORIGINAL probe — documentation and execution disagree on SIGN.
- **Impact:** any V4-era analysis that trusted wrapper docstrings for direction has sign-scrambled conclusions for these three families.
- **Lesson:** at every rename/flip, the alias map IS the behavior; docstrings are wishes. Test what the code does (the retrial did).

### B-089 — Live M5 time parsed as a string column → silent feature defaults (found+fixed ~2026-07-10)
- **Area:** prev-session structure feature build (`ps_high_dist` / `ps_low_dist` / `ps_pos`) in the live feed
- **Symptom:** the previous-session structure features silently returned defaults live; new PS-keyed shadow setups couldn't evaluate.
- **Root cause:** in the live path the M5 time was a **string** column, not a `DatetimeIndex`; the derivation hit an exception that a broad `except: pass` swallowed, returning default values.
- **Fix:** parse the ISO hour explicitly + log a warning instead of silently defaulting.
- **Lesson:** a bare `except: pass` around feature math turns a type mismatch into a silent wrong-answer. Live and corpus dtypes diverge — assert the index type, and never let a feature failure default without a log line.

### B-090 — ATR-scaled trail parked the ratchet stop below breakeven (green given up as red)
- **Date:** 2026-07-15 (Brock caught it: "how does a 40-SL bot lose $8?")
- **Area:** `modules/cells/cell.py` exit_params build + `modules/management/ratchet.py` `_compute_step_sl`
- **Symptom:** wide-stop (SL40-60) trades closing for tiny reds (−$0.85, −$7). The ratchet locked stops BELOW entry even on green peaks. Trace: trade 10428 peak=3.7p → sl=−1.5p.
- **Root cause:** the range-sized deploy (2026-07-14) set `trail_mult=1.0` on every cell. cell.py then OVERRIDES the fixed `trail_pips` with `clamp(trail_mult*atr_5m, trail_min, trail_max)`. With atr_5m≈5, effective trail=5 (not the 2.5 in config). `_compute_step_sl` returns `level − trail`; with trigger 3.5 and trail 5, locked stop = 3.5−5 = −1.5. So engaging at a low peak parked the stop below breakeven → any reversal exited red. Silently defeated the ratchet whenever atr_5m > trail_pips (i.e. almost always).
- **Impact:** every wide-stop trade in >2.5p-vol conditions gave up its green; the trigger/trail tuning (incl. the trigger-7.5 fix) was neutered because the trail wasn't fixed. Explains the single-digit W/L.
- **Fix:** `trail_mult 1.0 → 0.0` in the RANGE_SIZED generator block → fixed `trail_pips=2.5` used directly. Now engage +7.5 locks +5 (7.5−2.5) and trails 2.5; once engaged, cannot exit red barring slippage/gap.
- **Lesson:** a config `trail_pips` value is a LIE if `trail_mult>0` — the ATR scaler silently overrides it. When setting a fixed trail, set trail_mult=0. And Brock's heuristic holds: a wide-SL bot that loses small amounts is a trail/engage bug, not the stop.

---


## V6.1 live era (Jul 2026 — Party Package + instrumentation)

### B-091 — Public trade log labeled every direction backwards (and hid the poppers)
- **Date:** 2026-07-20 (Brock: "the live trade window isn't reflecting the closed popper" — it was, invisibly)
- **Area:** `ops/livelog_update.py` trade-row builder
- **Symptom:** first closed popper (long, +$115.88) appeared in `livelog/trades.csv` as an anonymous "AUD_USD short". Every historical row likewise inverted.
- **Root cause:** direction was taken from the CLOSING fill's unit sign — a sell closes a long. And rows carried no parent/popper attribution at all.
- **Fix:** one row per closed trade from `tradesClosed[]`; direction from the trade's own `initialUnits`; new `source` column (parent/popper) from broker client-extension tags. CSV rebuilds from transactions, so history self-healed.
- **Lesson:** a closing fill describes the CLOSE, not the trade. Attribution columns must exist before you need them.

### B-092 — Hourly cron kept reverting the README (template carried the config)
- **Date:** 2026-07-19/20 (Brock saw stale gear text after it had been "fixed")
- **Area:** `ops/livelog_update.py` README block template
- **Symptom:** README's live-config blurb showed engage 7.5 after the book moved to 8.5 — repeatedly, even after a manual edit.
- **Root cause:** the blurb lives between LIVE_BALANCE markers regenerated hourly from a hardcoded template string; editing the README edited the artifact, not the generator.
- **Fix:** gear text corrected in the template (ANCHOR_LABEL + SVG caption); regenerated immediately.
- **Lesson:** the find-the-real-tool rule applies to docs: never edit generated output, edit its generator.

### B-093 — Setup Scoreboard's sim column was dead on arrival (candle 400s)
- **Date:** 2026-07-20 (found while explaining the card to Brock)
- **Area:** `research/tools/cell_setup_score.py` `_fetch_candles`
- **Symptom:** dashboard "simulated EV vs expected" card showed stamp counts but `sim_ev = None` for every row, always.
- **Root cause:** candle request sent `from` + `to` + `count=500` together; OANDA v20 rejects the combination with HTTP 400 — every fetch, silently warned, never surfaced.
- **Fix:** dropped `count`. Card scored again on the next refresh.
- **Lesson:** a WARN that fires on 100% of calls is an outage, not a warning. Surface fetch-failure rates, not lines.

### B-094 — The whole shadow stack read retired journals after the cutover
- **Date:** 2026-07-22 (Brock: "the shadow tab isn't entirely accurate")
- **Area:** `cell_setup_score.py` + 5 research tools (`mr-scrooge-v5`); `ops/server.py` + `ops/shadowboard.py` + EC2 t20 scorer (default `mr-scrooge-v6-dryrun`)
- **Symptom:** stamp feed frozen at Jul 17; Setup Scoreboard scoring V5-era stamps; shadowboard/t20 boards stale — while the live V6 unit wrote 470+ fresh stamps nobody read.
- **Root cause:** journald unit names hardcoded/defaulted to units retired at the 2026-07-18 cutover. The known deferred item ("v5 namespaces are load-bearing") came due.
- **Fix:** every consumer pointed at `mr-scrooge-v6` (env-overridable). Disclosure logged: shadow-tab reads before the fix — including one promotion round — were prior-era data.
- **Lesson:** a rename/cutover isn't done when the service runs; it's done when every READER of the service's outputs is migrated. Keep a consumer inventory per producer.

### B-095 — Scoreboards keyed rows by status-at-stamp-time (and a silent worker ate the fix)
- **Date:** 2026-07-22
- **Area:** `ops/shadowboard.py` `_aggregate` + `cell_setup_score.py` grouping
- **Symptom:** promoted setups still showed SHADOW rows; setups that changed status split into two rows with divided stats; after the first fix attempt, the shadowboard rendered EMPTY.
- **Root cause:** (a) status captured at stamp time was used as row identity/label; (b) the fix's `_cfgst` binding missed its anchor → NameError inside the refresh worker, which swallows exceptions and cached nothing — the board failed silent.
- **Fix:** rows group by setup identity only; status joined LIVE from config/cells at aggregate time; binding placed correctly and verified by direct `_aggregate` call (36 rows).
- **Lesson:** decision surfaces must show what a thing IS, not what it was when observed. And background workers that swallow exceptions turn one-line bugs into invisible outages — log them loud.

---

### B-096 — Ladder deploy insta-fired a marker 85p below its level (and a config scp ate the per-cell switch)
- **Date:** 2026-07-23 (caught within minutes of the marker-ladder deploy)
- **Area:** `party_package.py` tick (new-marker arming) + deploy procedure
- **Symptom:** seconds after the ladder restart, a "-10" popper fired on the switched-OFF GBP/london grid — at market, ~85p below the marker's nominal price.
- **Root cause:** two compounding errors. (1) New ladder keys added to an EXISTING deep-underwater grid were armed `True`; the fire check saw price beyond the marker and fired immediately at the current (much worse) price. (2) The deploy scp'd a scratchpad `pp_config.json` over the live file, silently erasing the `per_cell: {GBP_USD|london: false}` opt-out — the artifact-over-generator sin (B-092) applied to config.
- **Fix:** new markers on a live grid arm only if price is still on the favorable side (else disarmed, waiting for re-cross); inert off-config slots are pruned; regression tests for both. per_cell restored via the API. Deploy rule: merge-managed configs are never scp'd whole — only touched via their write endpoints.
- **Lesson:** "armed" is a statement about the PATH (price hasn't crossed yet), not a default. And any config a dashboard writes is a generator's output — edit it through the writer, never by file copy.

---

### B-097 — Broker-cancelled fire treated as a fill: phantom popper + 82-attempt retry storm
- **Date:** 2026-07-23/24 (Brock: "dozens of cancelled trades — FIFO requirement")
- **Area:** `party_package.py` `_fire` + OANDA US FIFO safeguard
- **Symptom:** 82 ORDER_CANCEL(FIFO_VIOLATION_SAFEGUARD_VIOLATION) in ~9h — all the SAME USD_JPY −10 popper, re-fired every oscillation of price across its marker. A phantom popper with `trade_id=""` sat in the registry. (No fills, no fees, no naked trades — FOK orders died cleanly.)
- **Root cause:** two. (1) OANDA's FIFO safeguard rejected the new same-instrument long's on-fill SL while older UJ longs were open — with opaque logic (an identical 5-deep AUD stack passed all day). (2) OUR bug: `_fire` took `trade["id"]` from a fill-less response as an empty string, registered it as success — and since `""` is falsy, the marker never read as busy, so every re-cross re-fired.
- **Fix:** fires verify a real fill; a rejected fire marks the marker with a 30-min cooldown; 3 straight rejections suspend the grid's fires for 2h (any real fill resets the streak). Regression test simulates the FIFO cancel.
- **Lesson:** a broker response is not a fill until it contains one — and every external rejection path needs backoff, or the market's oscillation becomes your retry loop.

---

### B-098 — Setup Scoreboard + stamp feed dead since 07-22: a mid-function paste truncated main()
- **Date:** 2026-07-24 (Brock: "these dashboard sections are not working")
- **Area:** `research/tools/cell_setup_score.py` + `ops/server.py` (`_journal_unit`, `_cellscore_refresh`)
- **Symptom:** Setup Scoreboard showed `scorer error: Expecting value: line 1 column 1`; CELLSHADOW stamp feed showed 0 stamps / 48h — while the engine stamped ~400/day and shadowboard read them fine.
- **Root cause:** three, all latent since the 07-22 staleness overhaul. (1) The status-join edit pasted `def _config_status():` into the MIDDLE of `main()` at column 0 — syntactically valid Python that ended `main()` after the "Found N lines" print and swallowed the rest of the body as unreachable code inside the new function. The scorer exited 0 with empty stdout. (2) `server.py`'s `_journal_unit()` still defaulted to the retired `mr-scrooge-v6-dryrun` unit — the 07-22 fix updated shadowboard.py and the scorer but missed the third copy of the same default. (3) `_cellscore_refresh()` reset its `refreshing` flag AFTER the `return` (unreachable), so the first failed refresh wedged the error in the cache until the next process restart.
- **Fix:** `_config_status` moved above `main()` and the body re-stitched; `_journal_unit()` default → `mr-scrooge-v6`; flag reset moved into `finally`; scorer subprocess timeout 120s → 600s (verified real run 66s, 31 setups).
- **Lesson:** an insert-a-helper edit can silently bisect the enclosing function — Python won't object if the orphaned remainder still indents under the new def. Smoke-test the artifact the edit serves (run the scorer, curl the endpoint), not just the importability. And a default that exists in three files isn't a default, it's three bugs waiting to drift.

### B-099 — Config-order trial bias: first-ACTIVE early return starved every later setup of stamps
- **Date:** 2026-07-27 (external review, claim verified true)
- **Area:** `modules/cells/cell.py` evaluation loop
- **Symptom:** setups listed after an ACTIVE setup in a cell's config stamped far less than their conditions warranted — their shadow evidence accrued at a fraction of the fair rate.
- **Root cause:** the evaluation loop returned on the first ACTIVE setup that fired, skipping stamp evaluation for everything after it in config order. Trial fairness depended on JSON array position.
- **Fix:** every setup evaluates and stamps every cycle; the first ACTIVE result is selected after the loop. 3 regression tests.
- **Lesson:** in a trial system, the *evidence pipeline* must be unconditional — any early exit in scoring is a thumb on the scale, even when the trading decision itself is correct.

### B-100 — Config validator frozen at the July-04 schema: rejected all 18 live configs (and nobody noticed)
- **Date:** 2026-07-27 (external review)
- **Area:** config validator + `config/cells/*.json`
- **Symptom:** the validator declared every live cell config invalid (18/18) while the bot traded them happily — so the tool guarding the configs had been decorative for weeks.
- **Root cause:** schema written at the July-04 cell-era cutover, never updated as fields evolved; the pair list was also a third hardcoded copy.
- **Fix:** schema synced to live reality, pair list reads `config.pairs`, and `tests/test_cell_config_schema.py` validates every shipped config parametrically (with anti-vacuity corruption tests so a always-passing validator fails loud).
- **Lesson:** a validator that isn't in CI drifts into fiction; enforce it against the real artifacts on every run, and make the test suite prove the validator can still say no.

### B-101 — Dashboard writers callable cross-origin (CORS `*`) + DNS-rebinding exposure
- **Date:** 2026-07-27/28 (external review rounds 1–2)
- **Area:** `ops/server.py` HTTP layer
- **Symptom:** any web page in the operator's browser could POST to the localhost dashboard's write endpoints (status flips, pause, config writes); a DNS-rebinding page could reach it without CORS at all.
- **Root cause:** `Access-Control-Allow-Origin: *` on all endpoints; no Host validation; no auth on writers.
- **Fix (staged):** wildcard removed + same-origin write guard (Origin must match Host) → Host allowlist (421 on unknown hosts, beats rebinding — live-verified) + `X-Scrooge-Token` auth on writers + outbound OANDA host allowlist (token can't be exfiltrated by a poisoned URL). Footnote: the allowlist initially locked out the operator's own Tailscale-serve hostname (421) — allowlisted via systemd drop-in.
- **Lesson:** "it only binds to localhost" is not a security boundary while a browser sits on the same host.

### B-102 — Fail-open runtime controls: a corrupt file could re-enable trading
- **Date:** 2026-07-27/28 (external review; R2 added last-known-good)
- **Area:** trading pause, `pp_config.json`, governor config readers
- **Symptom:** unreadable/corrupt control files silently fell back to permissive defaults — a truncated pause file meant trading ON; a corrupt pp_config re-armed grids and erased per-cell opt-outs.
- **Root cause:** `except: return default` on safety switches, with the default being the permissive state.
- **Fix:** fail-closed across the board (corrupt pause can never re-enable; corrupt pp_config can never re-arm; corrupt governor config disables the run) with per-path last-known-good retention; the legacy fail-open test was doctrine-reversed. The reviewer predicted the LKG cache would flake under randomized test order (4/5 seeds) — reproduced, then fixed with path-keyed state.
- **Lesson:** for a control whose job is to say STOP, every failure mode must also mean stop.

### B-103 — Execution truth (D-5): quote-anchored stops, mid-price management, unreconciled order intents
- **Date:** 2026-07-28 (external review finding 3, shipped staged)
- **Area:** order placement, ratchet/management pricing, broker glue
- **Symptom cluster:** (a) SL priced off the pre-order quote, not the actual fill — slippage silently widened or tightened real risk; (b) the ratchet keyed off mid, flattering every popper by half the spread; (c) an HTTPError during order submission was treated as "no order" — but OANDA may have accepted it (PENDING/404-now ≠ never-existed), risking duplicates and orphans; empty parent fill responses were adopted as entries.
- **Fix:** fill-anchored SL distances + fills adopted as true entries with slippage logging; management on the executable side (bid for long exits / ask for shorts); `sv6-*` client order intent ids with timeout reconciliation and an order-finality quarantine (entries + popper fires halt until every intent is proven filled or rejected; empty fills rejected).
- **Lesson:** the trade you *intended* is not the trade you *have* — every price the system acts on must come from the broker's side of the fill, and every submission must be reconciled to a terminal state.

### B-104 — The promotion math measured a different game than the account played (D-6/D-7)
- **Date:** 2026-07-28 (external review finding 6 + round 2)
- **Area:** shadow scoring, governor promotion statistics
- **Symptom:** stamps scored frictionless mid drift at a fixed 240m horizon; overlapping episodes were counted as independent; ~150 hypotheses were tested daily at per-test 95% confidence. Poster child: the t20s twins showed +1.38p "gross tease" that was −1.1p net of cost.
- **Root cause:** the metric predated the cost doctrine and the exit geometry; the statistics predated the docket's size.
- **Fix:** executable-exit-v2 metric (stamped executable entry, bid/ask path, the setup's own exit simulated worst-case intrabar), net-of-cost everywhere, overlap-aware effective n, day/session block bootstrap, BH-FDR across the docket, sequential-peeking guard — and a one-time METRIC-ERA-RESET so no setup carries old-metric proof into the new era.
- **Lesson:** measure candidates in the units the account pays, or the promotion pipeline becomes a machine for discovering measurement error.

### B-105 — Demotion was blind to poppers: a −$858 family could not lose its seat
- **Date:** 2026-07-28/29 (found via the forward-test tape; fixed as the FAMILY RULE, v6.7.x)
- **Area:** `ops/governor.py` fills evidence
- **Symptom:** the forward test's single loss driver — GBP/USD-long `rvol_low_240`, −$858 across 20 fills — was invisible to demotion: the fills rule filtered `tag == cell_v1`, so 18 popper losses didn't exist as evidence, and the 2-trade parent leg was under the n≥5 floor.
- **Root cause:** demotion evidence predated the Party Package; poppers (51 of the window's 101 trades) were never added to it.
- **Fix:** poppers self-attribute their parent setup (`psu` in client extensions; grid-anchor join for older fills); the governor convicts and defends on **family** net pips (±60p at n≥5), switches the cell's poppers off with a lost seat, and — after the parent-stops-first boundary case — issues **no verdict while any family trade is open** (judge-when-flat).
- **Lesson:** if a subsystem can lose money, it must be attributable to a seat the governor can take away; unattributed P/L is unaccountable P/L.

### B-106 — Governor ledger card rendered `undefined/undefined/undefined` for era-reset entries
- **Date:** 2026-07-28 (caught in a screenshot during the v6.8.0 dashboard work)
- **Area:** `ops/panel.html` ledger renderer
- **Symptom:** METRIC-ERA-RESET / ERA-RESET ledger lines displayed `undefined/undefined/undefined` where the setup should be.
- **Root cause:** the renderer assumed every ledger entry carries `pair/session/setup`; reset entries carry a single `key` field.
- **Fix:** renderer falls back to `key` (pipes → slashes). Cosmetic, but the ledger is the governor's public face — it shouldn't stutter.
- **Lesson:** when a log format grows a second shape, every consumer of the first shape is now a renderer bug waiting for a screenshot.

### B-107 — Live gearing landed as dead top-level keys: first real-money fill sized at 10%, not 15%
- **Date:** 2026-07-29 (caught on live trade #1, minutes after entry)
- **Area:** `config/playmaker_config.json` + the cutover script
- **Symptom:** the first live fill (GBP_USD short, 3,762 units) carried ~10% margin sizing — the practice gearing — despite the cutover \setting\ 15%/6.
- **Root cause:** `pm_margin_pct()` / `pm_max_concurrent()` read `[ccount\][...]`; the cutover script wrote the new values at the top level of the JSON — legal, present, and completely unread. The B-092/B-096 lesson in a new costume: an edit that lands outside the read path is a no-op wearing a diff.
- **Fix:** values set inside the `account` block, strays deleted, effective values verified through the actual readers (`pm_margin_pct() == 0.15`). Hot-reload applies from the next fire; trade #1 keeps its smaller size (conservative — no action).
- **Lesson:** after changing a config, verify through the FUNCTION that reads it, never by re-reading the file. The file agreeing with you proves nothing about what the program sees.

### B-108 — Setup Scoreboard died on the replay crosses: a fourth hardcoded pair map
- **Date:** 2026-07-29 (Brock: "scorer error" on the SHADOW tab)
- **Area:** `research/tools/cell_setup_score.py`
- **Symptom:** the Setup Scoreboard card showed `scorer error: ... exit status 1`; the scorer crashed with `KeyError: AUD_CAD` the moment a replay-book cross stamp entered its window.
- **Root cause:** the scorer carried its own hardcoded 8-pair `PIP`/`SPREAD_PIPS` maps, written before the v6.3 replay shadow book added ten cross pairs. B-098's closing lesson ("a default that exists in three files isn't a default, it's three bugs waiting to drift") — this was file four.
- **Fix:** `.get()` with the universal FX rule (`0.01` for JPY quotes, `0.0001` otherwise; conservative cross spreads). The dashboard card self-heals on its next refresh (the B-098 fix put the flag reset in `finally`).
- **Lesson:** every hardcoded pair list is a time bomb armed by the next pair added. Grep for the others before they go off.

### B-109 — The dashboard said PRACTICE while trading real money
- **Date:** 2026-07-29 (caught during the SHADOW-tab accuracy audit, hours after the cutover)
- **Area:** `config/credentials.local.json` mode flag + the header banner; also the SHADOW tab's phase banner
- **Symptom:** the top banner read "● PRACTICE — PAPER TRADING" with a green tint while the $2,500 real-money account traded beneath it. Separately, the SHADOW tab's phase banner still showed the July-5 "shadow week — day 24 of 7" countdown, green and stale, three weeks after its window closed.
- **Root cause:** the cutover swapped the *credentials* (secrets.env outranks everything, so trading was genuinely live) but never flipped the cosmetic-but-critical `mode` flag the header renders from — and the resume-trading confirmation gate keys off the same flag, so the "TRADE REAL MONEY" typed-confirm requirement was silently inactive. The phase banner was simply never retired when its era ended.
- **Fix:** mode → live (red **LIVE — REAL MONEY** header), `SCROOGE_ALLOW_LIVE=1` armed via systemd drop-in, phase banner replaced with the live-era status line.
- **Lesson:** a cutover isn't done when the money moves — it's done when every label, gate, and banner agrees about which world it's in. The scariest state isn't wrong; it's *plausible*.

### B-110 — The public P/L would have counted deposits as profit (fixed before it could)
- **Date:** 2026-07-29 (fixed pre-emptively, before any deposit existed)
- **Area:** `ops/livelog_update.py` start-balance reconstruction
- **Symptom (latent):** the livelog reconstructs the starting balance as `balance − realized − financing`, assuming zero external transfers. The first real deposit would have silently inflated the published "trading profit" by its full amount — the exact dishonesty this repo exists to never commit, on its most public number.
- **Fix:** `TRANSFER_FUNDS` transactions are backed out of the reconstruction; the headline % uses a simple-Dietz time-weighted capital base; `equity.csv` gained a `net_deposits` column (young file normalized in place — the mixed-schema render lesson applied proactively); the README discloses added capital automatically.
- **Lesson:** audit every derived public number for the assumption that will someday stop holding. The best bug report is the one filed before the bug can happen.

### B-111 — The cutover pause turned 10 tests red: fixtures were reading production runtime state
- **Date:** 2026-07-29 (caught post-push — the failure itself was masked in the moment)
- **Area:** `tests/test_party_package.py`, `tests/test_family_ledger.py` + the release pipeline
- **Symptom:** every popper fire test failed the moment live trading was paused — and the red suite still got pushed once, because `pytest … | tail -1` reports *tail's* exit code, not pytest's.
- **Root cause:** two. (1) The fire-gate calls `trading_enabled()`, which reads the real `config/runtime.json` — the fixtures never isolated it, so the test suite's result depended on whether the live bot happened to be paused. (2) The pipe swallowed the failing exit status, so the guard-rail didn't guard.
- **Fix:** fixtures monkeypatch `trading_enabled`; suite green under any live-box state.
- **Lesson:** a test that reads production state isn't a test, it's a mood ring — and any check whose exit code passes through a pipe isn't a check.

### B-112 — The live account mangles client extensions: two real-money poppers orphaned, judge-when-flat bypassed
- **Date:** 2026-07-30 (Brock: "2/3 open trades not showing on the dashboard")
- **Area:** OANDA live `trades` endpoint vs the transaction stream; `core/engine.py` recovery dispatch; `party_package.recover`; `broker_setup_audit` open-trade attribution
- **Symptom:** broker held 3 open trades; the engine tracked 1. Two EUR/JPY poppers (green, past ratchet-engage) sat **unmanaged for ~16 hours** — server-side −60p stops intact, but no ratchet locking profits. Compounding: the same two were invisible to family accounting, so their family read "flat" and was **demoted mid-episode — a judge-when-flat violation** (on full data the conviction still stood: −172p ≤ −60p).
- **Root cause:** the **live** account returns mangled `clientExtensions` on the *trades* endpoint — `tag` becomes `"0"` and `comment` truncates to ~32 chars — while the **transaction stream carries them pristine**. (Practice never did this.) Everything keyed on the trades-endpoint copy: popper recovery filtered `tag == "pp_v1"` (missed → poppers fell to the parent path and were dropped), parent gear `json.loads` failed on truncation, and the audit's open-trade attribution read the same mangled copy (→ `n_open` undercounted → flat-when-not).
- **Fix (three layers):** (1) recovery classifies popper-vs-parent by **comment shape** with the tag as a hint only, and both decoders regex-extract whatever fields survive truncation; (2) both comment encoders reordered **most-critical-fields-first** (`su` leads parent comments, `anc`/`lvl` lead popper comments) so even a 32-char surviving prefix carries what recovery and family attribution need; (3) the audit's open-trade attribution now prefers the trade's **opening transaction** record (pristine) over the trades-endpoint copy. Recovery verified live: both poppers adopted, ratchet locked +24p and +16p within seconds, one already banked green.
- **Lesson:** the same field from two API endpoints is two different fields. Trust the stream you verified — and design every wire format so the *front* of it is the part you can't live without.

### B-113 — Manual status flips invisible for up to 15 minutes: the SHADOW board served baked-in status from its cache
- **Date:** 2026-07-30 (Brock: "i tried to switch those 3 cells active manually… it shows them still as shadows")
- **Area:** `ops/shadowboard.py` (board cache), `ops/server.py` (`/api/cell/status`)
- **Symptom:** Brock flipped three shadows ACTIVE from the dashboard; the config write succeeded and the engine would trade them on its next scan — but every dashboard refresh kept showing them as SHADOW, "waiting to promote." The operator couldn't tell whether his own switch had worked.
- **Root cause:** the board payload is rebuilt at most every 15 minutes (`_REFRESH_S = 900`) and served stale-while-revalidate; each row's `status` was joined from `config/cells` **at build time only**, so a flip made inside the cache window was baked over by the pre-flip snapshot until the next rebuild happened to run.
- **Fix (two layers):** (1) `get_board()` now re-joins `config/cells` **at serve time** — where the live status differs from the cached row it patches status + tier in place (flagged `flip_pending`, EX-SIDE rows untouched) and re-sorts, so status is always the live truth even from a stale payload; (2) `POST /api/cell/status` invalidates the board cache, so the next page load kicks an immediate full rebuild. Five regression tests; suite 296.
- **Lesson:** cache aggregates, never state. A number that changes when the operator throws a switch must be read fresh on every serve — the human's control loop breaks the moment the display stops trusting the switch.

### B-114 — The B-112 fix broke the classifier it fed: four live trades orphaned by my own deploy restarts
- **Date:** 2026-07-31 (Brock: "the dashboard is not showing all of the open trades… and the ratchet isnt managing them!")
- **Area:** `core/engine.py` recovery classification (`_looks_like_popper`, formerly inline)
- **Symptom:** 6 open real-money trades at the broker; engine tracked 2. The 4-trade GBP/USD grid (parent + 3 poppers, ~+30p in flight) sat unmanaged all morning with stops still at entry −60p — no ratchet, no lock, ~$51 of open profit one reversal away from a −$90 swing. A 5th trade (a popper) was mis-adopted as a "parent" with default gear.
- **Root cause:** a regression **caused by the B-112 fix itself.** 6.11.1 reordered popper comments critical-fields-first (`anc`/`lvl`/`psu` lead) so truncated live copies keep what attribution needs — but the recovery *classifier* still required `"sl"` and `"tr"` in the comment, and the reorder pushed exactly those past the live account's ~32-char truncation. Every truncated popper failed the popper test → fell to the parent path → the one-parent-per-pair rule **silently** `continue`d all but the first same-pair trade. Triggered by the v6.12.3/v6.12.4 deploy restarts (03:28/03:44Z); B-112's own verification hadn't caught it because the then-open poppers carried OLD-format comments with `sl`/`tr` up front.
- **Fix:** (1) classifier matches both encodings — new-format prefix fields (`anc`/`lvl`/`psu`) OR legacy `sl`+`tr` — and is extracted to module level with regression tests pinning the exact truncated live copies; (2) the one-parent-per-pair skip now logs a WARNING naming the unadopted trade — silence is what let four trades vanish; (3) remediation before the fix: stops manually moved to +6p lock, then post-fix recovery adopted 6/6 and the ratchet re-locked above the manual floor within one manage cycle.
- **Lesson:** when you change a wire format, grep for every consumer of the OLD shape — the encoder, the decoder, and the *classifier* are three different programs. And any recovery path that declines a live trade must say so out loud; the orphan you don't log is the one the operator finds by eye.

### B-115 — The Setup Scoreboard counted stamps as trades: one runaway afternoon read as "78 trades, 100% WR"
- **Date:** 2026-07-31 (Brock: "78 trades, 100% WR?")
- **Area:** `research/tools/cell_setup_score.py` (the /api/cellscore scoreboard), SHADOW-tab Setup Scoreboard table
- **Symptom:** `ps_floor_break_short` EUR/JPY/london showed **78 trades at 100% WR, +67.9p sim EV** — its true episode record was 15 decisions going 8W/7L, with +71 of the +72 cumulative pips coming from ONE afternoon (the 07-30 EUR/JPY London collapse). `kc_up_short_lean` showed "503 trades, 100% WR, +7.2p"; per-episode it is a **10-decision, 62.5% WR, −5.2p loser.**
- **Root cause:** double distortion. (1) The engine re-stamps a setup every scan cycle while its conditions hold, and the scorer counted every stamp as an independent trade — a four-hour runaway = dozens of "wins" riding one move. (2) The rate-limit cap simmed only the most recent 50 *stamps*, so a single clustered day didn't just inflate N — it **became the entire sim sample**.
- **Fix:** stamps are collapsed into EPISODES before scoring (stamps ≤30 min apart = one entry decision — the same `_EP_GAP_S` rule the shadowboard uses); the sim runs one entry per episode, most recent 50 episodes; the table shows `N eps (stamps)` with the tooltip explaining why. Unit tests pin the collapse semantics.
- **Lesson:** N is the most dangerous column on any scoreboard — before trusting it, ask what one row-unit *is*. A monitor that re-observes the same event must never present observations as decisions; independence is a property you build, not one you get.

### B-116 — The public live graph froze between closes: per-trade x-axis, NAV nowhere on the chart
- **Date:** 2026-07-31 (Brock: "is the real money tracker graph on the git rep having issues? doesnt seem to be up-to-date")
- **Area:** `ops/livelog_update.py` stat-card SVG
- **Symptom:** the README's real-money equity card looked stale all morning — the curve hadn't moved since the 08:14Z close while NAV swung $2,267 → $2,430 with six open trades. Data was fine (hourly cron green, equity.csv current); the *chart* only drew the realized curve on a per-trade index axis, so hours of open-trade reality were invisible.
- **Root cause:** chart design, not pipeline failure. X = trade number (not time), Y = realized only. A quiet-closes morning therefore rendered as a frozen line — indistinguishable from a dead updater, which is exactly how the operator read it.
- **Fix:** the card now plots on a TIME axis with both truths: bold realized steps at each close, plus a thin hourly NAV line (incl. open trades) from equity.csv, with a legend and both end-dots. The chart moves every hour because the account does.
- **Lesson:** a public tracker that can look frozen while healthy will be read as broken — and the reader is right, because "is it alive?" is the first thing a graph must answer. Plot time on the time axis.

### B-117 — Family evidence merged across sessions and counted legs as observations
- **Date:** 2026-07-31 (design review, verified in code)
- **Area:** `broker_setup_audit.py` family join; `ops/governor.py` family verdicts; `ops/shadowboard.py` family lookups
- **Symptom:** two structural attribution errors in the evidence the governor convicts and defends on. (1) Families were keyed `(instrument, setup)` — session omitted, while 47 setup ids repeat across sessions (GBP_USD `timing_lean_30` exists in asia AND london): their broker evidence silently merged. (2) `family n` counted closed LEGS: one grid excursion producing six closed trades read as "n=6, 6-for-6" when it was ONE correlated market episode.
- **Fix:** families keyed `(instrument, session, setup)` — poppers inherit the session of the parent that armed their grid; legs are chained into **GRID CYCLES** by open-interval overlap (family flat = cycle boundary; a cycle an open leg extends is censored). Verdicts now run on completed cycles: convict at `family_min_cycles≥2` on net, **or ONE catastrophic cycle ≤ −90p** (asymmetric, per charter); defend needs `family_defend_cycles≥3`. First live run re-graded the book: the "6-for-6" GBP grid = 1 completed cycle (honest: promising, unproven); the re-seated EUR_JPY lean = 1 catastrophic −144p cycle (convicts on sight when flat).
- **Lesson:** the unit of evidence is the decision, not the fill. Correlated legs are one observation wearing six hats — and any join key missing a dimension the config repeats across is silently pooling different strategies.

### B-118 — A red suite got pushed through a pipe, again — by the author of the B-111 writeup
- **Date:** 2026-07-31 (caught one commit later, same session)
- **Area:** release discipline; `config/cell_schema.py`; `ops/shadowboard.py`
- **Symptom:** v6.14.4 (wired-date backfill) shipped with **19 failing schema tests** — the new `wired` field wasn't whitelisted, PROBE wasn't a schema-legal status, and the queued-row loop unpacked a 2-tuple from a now-3-tuple (which would have silently killed board rebuilds inside the refresh thread's catch-all).
- **Root cause:** the commit chain ran `pytest -q | tail -1` and proceeded on tail's exit code — the **exact** pipe sin B-111 documented on 2026-07-29, recommitted verbatim by the same author two days later. The check that isn't allowed to fail the pipeline isn't a check.
- **Fix:** schema whitelists `wired`, VALID_STATUSES gains PROBE, queued unpack tolerates the extended tuple; fix-commit ran under `set -e` with the exit code unpiped. Suite 348 green before push.
- **Lesson:** B-111's lesson didn't fail — its *enforcement* did. A lesson that lives in a document and not in the tooling will be re-learned at the worst available moment. (CI caught it too — the red run on GitHub was the backstop that a local pipe can't swallow.)

### B-119 — HTTP 200 is not a fill: phantom popper exits on a halted market
- **Date:** 2026-08-01 (caught by the Commissioner's reconcile guard: "broker=6 tracked=5 missing=['7059']")
- **Area:** `core/broker/oanda.py` close_position; `modules/management/party_package.py` exit booking; `core/engine.py` parent close path
- **Symptom:** over the weekend halt, the engine repeatedly "closed" popper 7059, logged `CLOSED`, booked a **+8.0p exit into the grid ledger** and dropped tracking — while the trade stayed open at the broker. The reconciler then re-adopted it, the manager re-signalled, and the loop repeated (~every close attempt, 10 phantom exits in 40 minutes). Live money was never lost — the trade kept its server-side stop — but the pp ledger took phantom greens and the family stayed judged-open.
- **Root cause:** OANDA answers a close request with **HTTP 200 even when the close order is created-and-CANCELLED** (`orderCancelTransaction`, here reason `MARKET_HALTED`; `FIFO_VIOLATION` is the same shape). `close_position` logged CLOSED on any 200, and both exit paths booked the exit unconditionally — the `except` clause only ever imagined network errors ("OANDA may have beaten us").
- **Fix:** `close_position` inspects the response — cancel-without-fill raises typed `CloseRejected(reason)`. The popper path keeps the trade tracked on rejection with a 30-min backoff (no order-hammering through the halt); the parent path keeps its manager instead of deleting it onto a live position. Only a confirmed fill, or a genuinely-gone trade, books an exit. Regression test drives a rejecting broker through the production tick.
- **Lesson:** a 200 status is transport, not truth — the *transaction inside* is the verdict. Same family as B-111/118 (the unexamined success path): every broker mutation needs its result READ, not assumed. And the autonomy stack worked exactly as designed: the Commissioner's guard flagged the mismatch hours before any human looked.
- **Guard (2026-07-31, Brock: "put a pipe guard so that doesn't happen again"):** `ops/hooks/pre-push` — versioned git hook (installed via `git config core.hooksPath ops/hooks`) that runs the full suite UNPIPED and the secrets sweep over the outgoing diff on every push, blocking at the git layer. Verified both directions: green suite pushes, a deliberate red test blocked the push. The lesson now lives in the tooling.







---

# Recurring patterns (architectural lessons)

These bug families repeat across versions:

| Pattern | Examples | Mitigation |
|---|---|---|
| **Stale price at order placement** | B-009, B-015, B-060 | Staleness check before send |
| **Multi-actor race on shared resource** | B-055, B-056, B-057 | Shared state + ownership protocol (TradeCoordinator) |
| **Reactive market-order loop** | B-033 | Bot never places market orders; OANDA native handles exits |
| **Pip-normalization across pair classes** | B-024, B-040, B-045 | All thresholds in pips, never raw price units |
| **Cross-pair / cross-asset parameter defaults** | B-016, B-045 | Parameter classes per pair-class |
| **Silent zero-signal / silent-default outages** | B-054, B-089 | Cycle-level scan counters; never `except: pass` around feature math |
| **Dead config keys** | B-041, B-042, B-049 | Periodic audit; type-check the config loader |
| **Stale telemetry / cache** | B-044, B-058, B-087 | Centralize state update on confirmed events; defensive serializers |
| **Per-trade attribution / truth-source gaps** | B-064, B-084 | Design attribution in from day 1; broker fills are truth, journal is intent |
| **Pre-fill vs post-fill prices** | B-050 | Always recompute on fill |
| **Box / reference-geometry contamination** | B-068 → B-074 | Sanity-guard the reference; carry contaminated-window notes into backtests |
| **A config value silently overridden by a scaler** | B-090 | When a fixed value must hold, zero out the multiplier that can override it |
| **A rule validated on a long average, wrong in-regime** | B-082 | Walk-forward + regime labels; the current year isn't the average |
| **Readers left behind by a producer rename/cutover** | B-092, B-094 | Edit generators not artifacts; keep a consumer inventory and migrate it with the producer |
| **Silent failure in a background worker / 100%-rate WARN** | B-093, B-095 | Failure-rate telemetry; workers must log exceptions loud, never cache-nothing |

## Bugs that shaped the current architecture

| Bug | Decision it triggered (survives into V6) |
|---|---|
| B-033 (infinite retry loop) | The bot never places reactive market orders — exits ride OANDA-native / server-side brackets. |
| B-045 (JPY margin) | Cross-pair sizing math made explicit. |
| B-054 (silent V2 skip) | Live signal counters / skip-rate visibility on the dashboard. |
| B-055 (46-order spam) | The shared-state coordination pattern. |
| B-064 (attribution unreliable) | Live broker-forensic audit windows dated post-attribution-fix; broker fills are ground truth. |
| B-065 (Echo timeframe) | Every composed ratio names the source timeframe of each term. |
| B-067 (aggregator OOM) | Heavy compute never runs on the live-trader host. |
| B-078 (H1 leak) | Leak-test the corpus before the discovery program; label every artifact by corpus generation. |
| B-086 (rollover wash) | Global rollover stop-freeze + server-side TP for FAST cells. |
| B-090 (ATR trail override) | Fixed-trail cells set `trail_mult=0`; the dashboard flags any ATR-scaled trail in red. |

---

# Legacy defects recovered from session archives

Defects documented in the operator's **dated pre-repo session archives** (Dropbox
`/LLM Sessions/…/Trading/`) that predate the B-numbering system and were never assigned a B-id.
They are recorded here for the historical record with an **`L-` designation so they do not consume
or renumber any B-id.** The B-001 → B-090 range remains intact and uninvented (see below).

### L-01 — USD/JPY "pitchfork" runaway re-entry (V1, no loss-memory)
- **Date:** 2026-03-01/02 · **Source:** *Dropbox `/LLM Sessions/…/Trading/2026-03-02 Scrooge bot
  USDJPY runaway re-entry bug`* (primary log, recovered 2026-07).
- **Symptom:** the live V1 bot placed **20 identical USD/JPY SELL entries** on the `pitchfork` signal,
  every 10 minutes for 3h10m (13:13 → 16:23 UTC), each filled at 110.51 and stopped at 111.49 within
  ~1 second — ~98 pips × 20 ≈ $177 on 1,000-unit clips. Price was already at/above the stop at each
  entry; the signal kept firing into an already-invalidated zone.
- **Root cause:** no trade-outcome awareness — no loss memory, no consecutive-loss halt, no
  post-stop cooldown, and no pre-entry price validation (reject a SELL when price ≥ stop). The bot
  had no concept of "I just lost this trade."
- **Fix / lesson:** the primal circuit-breaker lesson of the whole program — hard breakers must live
  at the **bot** level, not only the broker: max consecutive losses → halt the symbol, daily-loss
  cap → halt all, cooldown after a stop, and a pre-entry price-vs-stop guard. Bitter irony: the
  genesis spec (*2026-02-14*) had **called for exactly these breakers**; the first live build shipped
  without them. Related later B-entries in the same lineage: **B-007** (re-entry not wired), **B-023**
  (cooldown wrongly applied to wins), **B-025** (consecutive-candle counting).

### B-120 — the unreachable throne: Commissioner qualifier detection deadlocked
- **Date:** 2026-08-05 (caught answering the operator's "how long until those shadows promote?" — the honest answer was "never")
- **Area:** `ops/commissioner.py` check_dryrun; interaction with `ops/governor.py` candidate gating
- **Symptom:** the Commissioner sat in VALIDATING indefinitely with clean health passes accruing (2 passes ≥6h apart on the books) while the cheater-v4 lane it exists to open stayed dark — despite 13 candidates passing the complete v4 ticket on current evidence (top: EUR_JPY/asia/box_pdl_short_t20s at +4.73R covered over 6 resolved virtual cycles).
- **Root cause:** `check_dryrun` ran a **plain** `governor.py --dry-run` and grepped stdout for "CHEATER-PROBE". But the governor only *builds* cheater candidates when `cheater_promotion_enabled` (false — that is what the Commissioner is waiting to enable) or `--cheater-diagnostic` is passed. Circular dependency: the qualifier signal required the lane the qualifier was supposed to unlock. The VALIDATING → COMMISSIONED_1 transition was unreachable by construction.
- **Fix:** the health battery now runs `--dry-run --cheater-diagnostic` (evaluates the full ticket while admission stays OFF, never queues a flip) and detects both "CHEATER-PROBE" and "cheater-v4 diagnostic QUALIFIED". Timeout 900 → 1500s for the replay budget.
- **Lesson:** a state machine's advance condition must be provably reachable — test the *transition*, not just the states. Nobody noticed for 5 days because "healthy, waiting for evidence" looks identical to "healthy, structurally unable to see evidence." When a gate waits on a signal, ask: can the signal fire while the gate is closed?

### B-121 — the censor that ate the losses: 27% of all evidence silently discarded
- **Date:** 2026-08-06 (Brock: "it is statistically improbable that they have found zero entries over this amount of time")
- **Area:** `core/shadow_execution.py` simulate_shadow_exit; `ops/shadowboard.py` _score_v2
- **Symptom:** setups selected from an 8-year corpus *for high trade frequency* showed zero episodes after weeks live. Audit found 616 of 2240 episodes (27%) carrying a score block with `net240=None`, some 9 days old. Whole cells looked dead; entire families looked profitable.
- **Root cause:** the replay was TRUNCATED at `horizon_min` (`bars = bars[:horizon_bars]`). Anything that had not hit a stop or ratchet exit inside 4 hours was labelled "still open" and its net was dropped from every aggregate. The reasoning in the 2026-07-31 charter was sound — the live ratchet has no timeout, so an unresolved trade is not an outcome — but "unresolved" in practice meant **we stopped watching**.
- **Why it was worse than a data gap:** the discard was NOT random. Measured on a 60-episode sample, 80% of censored stamps resolve when followed to a real exit, and the recovered set is **75% winners averaging −4.5p** — one in four ran to a FULL STOP. Slow losers were being deleted preferentially, so every cell in the book read better than reality. Two live seats had been funded on flattered evidence (`CAD_JPY/asia/ps_ceil_fade_short` ACTIVE +13.50 → −22.50p; `USD_CHF/london/ps_ceil_fade_short` PROBE +6.83 → −12.50p) and both were demoted within 12h of the evidence becoming honest.
- **Fix:** `simulate_shadow_exit` gains `max_bars`; `_score_v2` follows a still-open stamp to its real exit via a paged M5 fetch, capped at `FOLLOW_MAX_DAYS`=5 (inside the bot's own `grid_max_age_days`=7). MFE/MAE stay scoped to the horizon window so `hit≥trig`/`hitSL` keep their meaning. `research/tools/rescore_censored.py` recovered the backlog: **503 of 657, 0 failures**. Cells with era evidence 171 → 193; 61 of 131 grown cells got WORSE.
- **Lesson:** a measurement that throws data away must justify WHAT it throws away, not just why. Censoring on "did it finish inside our window" silently selects on outcome speed — and losers are slower. Any filter applied to results needs its discarded set audited at least once, or the survivors quietly become the story.

### B-122 — the lane that could never sit: ordinary promotions starved the commissioned seat
- **Date:** 2026-08-06 (found while answering "so we actually have 6 shadows about to promote?")
- **Area:** `ops/governor.py` cheater seat allocation
- **Symptom:** the Commissioner reached COMMISSIONED_1 and enabled the cheater lane with one seat — and the lane seated nothing, ever. It did not merely fail to admit; it skipped candidate EVALUATION entirely.
- **Root cause:** `seats_free = cheater_max_seats − probe_seat_count(bmap)`, and `probe_seat_count` counts EVERY PROBE regardless of which lane opened it. Two ordinary-lane PROBEs therefore zeroed the cheater allowance permanently. The cap was written when ordinary promotions were dark and had never had to share.
- **Fix:** two pools. `cheater_seat_count()` reads the lane's own seat book (policy cap); a new **`max_probe_seats_total`** is a durable, status-derived ceiling across BOTH lanes (the real risk control, surviving loss of governor state). The commissioned seat is RESERVED, not first-come. The ordinary lane also gained a standing ceiling it never had — `max_promotions` only ever bounded promotions *per run*, so live PROBEs could accumulate without limit.
- **Lesson:** when a second consumer appears for a shared resource, re-derive the allocation instead of assuming the old formula still means what it did. And a cap counted from non-durable state is a policy, not a safety control — say which one you are building.

### B-123 — the guard that tested less than CI, and the cron that flooded it
- **Date:** 2026-08-06/07 (Brock: "we have a bunch of error messages in the git rep")
- **Area:** `.github/workflows/tests.yml`; `ops/hooks/pre-push`
- **Symptom:** red marks across the public repo's commit history, including on the bot's own automated commits — while the suite passed locally and in a clean CI-matching venv.
- **Root cause (two, unrelated):** (1) the failing runs executed **ZERO steps** and were cancelled after ~15 minutes — jobs that never got a runner, not tests that failed. 24 of 30 commits/day are the hourly livelog cron touching only `equity.csv`, `equity.svg` and a README badge line; every one triggered a full run and starved the queue. (2) CI runs the suite twice — fixed order AND randomised (`pytest-randomly`) — but the pre-push hook ran it once, unrandomised, and the plugin was not even installed on the box. The guard was testing a weaker property than CI and would have passed order-dependent breakage.
- **Fix:** `paths-ignore` for livelog/README/docs (skips only when EVERY changed path matches, so README+code commits still run), a concurrency group so a newer push supersedes a queued one, and `timeout-minutes: 15`. The hook now runs BOTH orders and HARD FAILS without `pytest-randomly`, using a `.venv-test` built with `--system-site-packages` so the plugins never touch the interpreter the live trader runs on. Verified both directions: green push passes, missing plugin blocks with rc=1.
- **Lesson:** **a cancelled job records zero steps; a real failure names the failing step.** Check that before assuming the tests broke. And a guard is only as strong as the weakest thing it actually runs — if CI tests a property the local hook does not, the hook is decoration on that property.

---

### B-124 — the mute button nobody could hear: a stale spread table silently vetoed every CAD_JPY entry

- **Discovered:** 2026-08-07, operator-prompted ("very busy Asian week, something is wrong with that cell") after a strategy audit flagged CAD_JPY/asia as ACTIVE with zero broker fills since wiring (2026-07-27).
- **Area:** `modules/cells/portfolio.py` (`select_intent`); `modules/playmaker/playmaker.py` (`_MAX_SPREAD` table); `modules/management/party_package.py` (popper fire gate).
- **Symptom:** CAD_JPY/asia `ps_ceil_fade_short` stamped CELLSHADOW as `status=ACTIVE` with passing conditions for 11 days (91 stamps on 2026-08-06 alone) yet never placed a single broker order. The shadow scorer kept accruing governor-facing evidence for a seat that could not execute.
- **Root cause (two, compounding):** (1) the playmaker-era `_MAX_SPREAD` table listed only 8 pairs; unlisted pairs fell to `_DEFAULT_MAX_SPREAD = 3.0` pips. CAD_JPY's floor spread over 14 days of stamps was **3.4p** (mode 3.5–3.7) — the cap sat below the pair's best-ever spread, so 100% of its intents were vetoed, structurally and forever. (2) the veto was **silent**: the currency-cap branch logged CELLSKIP, but the spread and cooldown branches `continue`d with no trace — invisible to the journal, the dashboard, and a full audit.
- **Fix (v6.25.1):** the max-spread entry veto is REMOVED at all three sites (operator decision: the ratchet exit and broker-truth net-of-cost cycle scoring already price the spread toll; a hard entry veto from the pre-ratchet era double-filtered on a stale table). The `spread <= 0` bad-tick fail-closed guards remain. Every surviving veto in `select_intent` now logs a CELLSKIP reason (`bad_tick`, `post_loss_cooldown`), and the popper bad-tick skip logs `PP SKIP ... reason=bad_tick`.
- **Lesson:** every gate that can suppress a trade must say so in the journal — a silent `continue` is a mute button nobody can hear, and 11 days of "no sample yet" was actually 11 days of vetoed signal. And any per-pair table is a liability the day a new pair is wired: the default value decides, and nobody looks at the default. Cost controls belong in the exit/scoring layer that is actually measured, not in unmeasured entry vetoes.

---

### B-125 — the flip nobody signed: a dashboard POST silently reversed a governor promotion

- **Discovered:** 2026-08-10, while answering "how do the shadows look" — EUR_USD/ny/rg1_range_scalp_short (promoted 2026-08-08T00:35Z with the docket's best stats: q=0.004, blcb=+5.19) was back in SHADOW with no demotion in the ledger.
- **Area:** `ops/server.py` POST `/api/cell/status`; `ops/governor.py` `flip()`; `ops/panel.html` status UI.
- **Symptom:** at 2026-08-08T07:21:39Z a `PROBE -> SHADOW` flip was applied through the dashboard endpoint — the ONLY off-tick flip in journal retention. The journal line said "(dashboard)" and nothing else: no actor, no source address, no ledger entry. The governor's own flips ride the same endpoint, so the ledger (the operator contract) captured governor actions but was structurally blind to everyone else's.
- **Forensics:** governor (no tick, no ledger), commissioner (clean battery), test suite (planted-PROBE experiment in a repo copy survived a full run; no test touches the live API), counterpart-audit cron (ran clean that day), virtual-scores/livelog/backup/mirror crons (no cell writers), and the engine (never writes configs) — all ruled out with evidence. Source remains unknown.
- **Fix (v6.27.1):** every `/api/cell/status` flip now (1) logs `actor` (from the POST body; `UNATTRIBUTED` when absent) plus the client address, and (2) appends a `GOVERNOR-FLIP`/`OPERATOR-FLIP` entry to `data/governor_ledger.jsonl` — never raising on ledger failure (a ledger problem must not fail the flip). The governor sends `actor="governor"`; the panel UI sends `actor="dashboard-ui"`. The reversed promotion was restored by operator order 2026-08-10 (OPERATOR-FLIP in the ledger).
- **Lesson:** an audit trail that only covers the well-behaved writer is decoration — the same endpoint that serves the governor serves anyone on the network, and the ledger must hear about ALL of them or "read the ledger" is a false contract.

---

# Records not recovered

As of this consolidation (2026-07-16), **every id in the B-001 → B-090 range has a recoverable
record and appears above.** There are no gaps and no invented entries. If a future gap is
discovered, list it here as a one-liner (id + best-known era + where a trace might exist in
`/SCROOGE/SCROOGE ARCHIVE/`) rather than reconstructing it from memory — a partial-but-true book beats
a complete-but-invented one.

*Source-of-record note: the V1–V3 catalog (B-001→B-074) was originally maintained in the
Obsidian ops vault and is reproduced here in full; its public-safe export lives at
`/SCROOGE/SCROOGE ARCHIVE/V3/scrooge-bug-catalog-V1-V3-export-2026-07-05.md`. V4–V5 entries
(B-075→B-090) were authored in-repo. This file is now the single canonical Book of Bugs.*
