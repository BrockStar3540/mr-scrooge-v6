# Mr. Scrooge — The Book of Bugs

**Living institutional memory of every documented defect across the bot family (V1 → V6).**
Format per entry: id · era · area · symptom · root cause · fix · lesson. When something odd
surfaces, this book answers *"have we seen this before?"* before anyone re-derives it.

This is the single canonical copy. It began as a vault-hosted catalog (V1–V3) plus a repo
stub (V4–V5); the two were merged here so a reader with only this public repo has the whole
book. Nothing points off-repo for the content itself — the only external references are the
Dropbox `/SCROOGE ARCHIVE/` paths where the original forensic source material (daily notes,
postmortems, commit-linked audits) is filed.

**Coverage:** B-001 → B-095, all recoverable, all present below (B-091+ = V6.1 live era). See *Records not recovered*
at the end — as of this consolidation there are **no gaps** in the B-001→B-090 range.

**Recurring-pattern index and "bugs that shaped architecture" tables are at the bottom** —
read those first if you want the compressed lessons rather than the chronology.

---

# V1 — "The Box Bot" era (≈ Feb–Mar 2026)

Source material: `scrooge-v1-exec-summary-feb-2026` (3 audit passes), `AUDIT.md` from the V1
repo, daily notes Mar 6/11/12/19/20/24. Public-safe forensic export archived at
`/SCROOGE ARCHIVE/V3/scrooge-bug-catalog-V1-V3-export-2026-07-05.md`; raw daily notes at
`/SCROOGE ARCHIVE/session-notes/2026-03-*`.

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
`/SCROOGE ARCHIVE/docs-harvest/v3-repo-docs/` and the V1–V3 bug export.

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

---

# Records not recovered

As of this consolidation (2026-07-16), **every id in the B-001 → B-090 range has a recoverable
record and appears above.** There are no gaps and no invented entries. If a future gap is
discovered, list it here as a one-liner (id + best-known era + where a trace might exist in
`/SCROOGE ARCHIVE/`) rather than reconstructing it from memory — a partial-but-true book beats
a complete-but-invented one.

*Source-of-record note: the V1–V3 catalog (B-001→B-074) was originally maintained in the
Obsidian ops vault and is reproduced here in full; its public-safe export lives at
`/SCROOGE ARCHIVE/V3/scrooge-bug-catalog-V1-V3-export-2026-07-05.md`. V4–V5 entries
(B-075→B-090) were authored in-repo. This file is now the single canonical Book of Bugs.*
