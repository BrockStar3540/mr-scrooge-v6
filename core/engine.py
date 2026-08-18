"""core/engine.py — V5 main loop (cell era, Phase D cutover 2026-07-04).

Flow per M5 bar:
  1. Feed: get_views() → list[MarketView] for all pairs
  2. Ratchet tick: for each open position, update peak/floor → move server SL
  3. Exit detection: poll broker.open_positions(); remove managers for closed trades
  4. Cells: every in-session CellModule evaluates its setups against the view.
     SHADOW setups stamp CELLSHADOW; ACTIVE setups return CellIntents.
  5. Portfolio: modules.cells.portfolio.select_intent — risk caps only, no alpha
  6. Entry: size units + place market order; Position carries the setup's
     exit_params so the ratchet runs the setup's own SL/trigger/trail.

The direction_v2/momentum_v3 stack is RETIRED (the V5 repo modules/archive/signals_legacy/ + Dropbox graveyard,
rollback tag pre-cell-cutover-2026-07-04). A cell with no qualifying ACTIVE
setup trades nothing — silence is the default state of the book.
"""
from __future__ import annotations
import collections
import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from config.pairs import PAIRS, PIP
from core.broker.oanda import DEFAULT_INITIAL_SL_PIPS, OrderUncertain, CloseRejected
from modules.signals import formula_shadow as _formula_shadow
from modules.playmaker.playmaker import (TradeTicket, pm_margin_pct, pm_probe_mult,
                                          pm_max_concurrent,
                                          pm_formula_shadow_enabled,
                                          pm_cell_shadow_enabled)
from modules.playmaker import lock_guard
from modules.management.base import Position
from modules.management.ratchet import RatchetManager, initial_sl_pips_for
from modules.management.bracket import BracketManager
from modules.management.party_package import PartyPackage
from modules.cells import PairModule, CELL_EXECUTION_ENABLED
from modules.cells.portfolio import select_intent
from config.runtime import trading_enabled, reaper_config, reap_due
from core.exec_truth import adopt_fill, executable_price

log = logging.getLogger("v5.engine")

_SESSIONS = ["asia", "london", "ny"]



def _encode_exit_ext(ep, setup_id: str) -> dict:
    """Compact exit-gear payload for OANDA tradeClientExtensions (comment
    field is limited to 128 chars — zero-valued keys are omitted)."""
    # B-112: the LIVE account truncates the comment to ~32 chars on the trades
    # endpoint — field ORDER is survival order. su first (family attribution
    # depends on it), then the gear.
    d = {"su": setup_id, "m": ep.mode, "sl": ep.sl_pips,
         "tr": ep.trigger_pips, "tp": ep.trail_pips}
    for k, v in (("tpp", ep.tp_pips), ("to", ep.timeout_min), ("tm", ep.trail_mult),
                 ("tmin", ep.trail_min), ("tmax", ep.trail_max)):
        if v:
            d[k] = v
    comment = json.dumps(d, separators=(",", ":"))
    if len(comment) > 128:  # last resort: drop the setup id, keep the gear
        del d["su"]
        comment = json.dumps(d, separators=(",", ":"))
    return {"tag": "cell_v1", "comment": comment}


def _looks_like_popper(client_ext: dict) -> bool:
    """Popper-vs-parent classification for recovery (B-112 / B-114).

    LIVE accounts mangle clientExtensions on the trades endpoint: tag -> "0",
    comment truncated to ~32 chars — so neither field can be trusted whole.
    B-114: the 6.11.1 critical-fields-first reorder puts anc/lvl/psu at the
    FRONT of popper comments, which pushes sl/tr past the truncation point;
    the old sl+tr test then misclassified every truncated popper as a parent,
    and the one-parent-per-pair rule silently swallowed the rest of that
    pair's trades (four live GBP trades orphaned 2026-07-31). Classify on
    whatever survives the cut: the tag when intact, the new-format prefix
    fields, or the legacy sl+tr pair. Parent comments start {"m": or {"su":
    by construction (_encode_exit_ext) and never match.
    """
    cm = (client_ext.get("comment") or "")
    return (str(client_ext.get("tag") or "").startswith("pp_v1") or
            (cm.startswith("{") and
             not cm.startswith('{"m":') and
             not cm.startswith('{"su":') and
             ('"anc"' in cm or '"lvl"' in cm or '"psu"' in cm or
              ('"sl"' in cm and '"tr"' in cm))))


def _decode_exit_ext(trade: dict):
    """Parse persisted exit gear off an OANDA trade dict. Returns
    (ExitParams, setup_id) or None (absent / foreign / unparseable)."""
    comment = (trade.get("clientExtensions") or {}).get("comment", "")
    if not comment.startswith("{"):
        return None
    try:
        d = json.loads(comment)
        from modules.cells.cell import ExitParams
        ep = ExitParams(
            sl_pips=float(d["sl"]), trigger_pips=float(d["tr"]),
            trail_pips=float(d["tp"]), mode=str(d.get("m", "ratchet")),
            tp_pips=float(d.get("tpp", 0.0)), timeout_min=float(d.get("to", 0.0)),
            trail_mult=float(d.get("tm", 0.0)), trail_min=float(d.get("tmin", 0.0)),
            trail_max=float(d.get("tmax", 0.0)),
        )
        from modules.cells.cell import migrate_stale_gear
        return migrate_stale_gear(ep), str(d.get("su", "persisted"))
    except (KeyError, ValueError, TypeError, json.JSONDecodeError):
        # B-112 lenient fallback: the live trades endpoint truncates comments,
        # breaking json.loads. Regex-extract whatever gear fields survived;
        # anything missing falls back to ExitParams defaults downstream (the
        # adopter logs gear provenance either way).
        import re as _re
        def _f(key):
            m = _re.search(r'"%s":([0-9.]+)' % key, comment)
            return float(m.group(1)) if m else None
        m_su = _re.search(r'"su":"([^"]*)"?', comment)
        mode_m = _re.search(r'"m":"([a-z]+)"?', comment)
        if _f("sl") is None and not m_su:
            return None
        try:
            from modules.cells.cell import ExitParams
            ep = ExitParams(
                sl_pips=_f("sl") or 40.0, trigger_pips=_f("tr") or 8.5,
                trail_pips=_f("tp") or 2.5,
                mode=(mode_m.group(1) if mode_m else "ratchet"))
            from modules.cells.cell import migrate_stale_gear
            return migrate_stale_gear(ep), (m_su.group(1) if m_su else "persisted-truncated")
        except Exception:
            return None

class Engine:
    def __init__(self, feed, broker, dry_run: bool = True):
        self.feed     = feed
        self.broker   = broker
        self.dry_run  = dry_run

        # Legacy module registries retired at Phase D — kept as empty dicts so
        # the dashboard serializer and any stray reader stays alive.
        self.dir_mods, self.mom_mods = {}, {}
        # pair → RatchetManager; one entry per open trade
        self.managers: dict[str, RatchetManager] = {}
        # pair -> datetime of last losing exit (portfolio cooldown)
        self._sl_history: dict[str, datetime] = {}
        # cell_opens: "<pair>|<session>|<traded_dir>|<session_instance_key>" -> int
        # In-memory only — resets on restart (per-session bookkeeping)
        self._cell_opens: dict[str, int] = {}
        # Trading-pause transition tracker (log once per ON<->PAUSED flip).
        self._trading_enabled_prev: bool = True

        # Dashboard state — updated each cycle
        self.last_views:        list = []
        self.last_tickets:      list = []
        self.last_trade_ticket: Optional[TradeTicket] = None
        self.recent_events:     collections.deque = collections.deque(maxlen=40)
        self.cycle_count:       int = 0
        self.last_cycle_time:   Optional[datetime] = None
        # Module-health heartbeats (ops/health.py)
        self.last_manage_time:  Optional[datetime] = None
        self.last_feed_time:    Optional[datetime] = None
        self.feed_views_n:      int = 0

        # ── Cell pair modules — THE strategy source (Phase D) ─────────────────
        # Built from config/cells/<PAIR>.json.  Missing files = cells absent.
        # PairModule hot-reloads config on each call to active_cells().
        from pathlib import Path as _Path
        _cells_dir = _Path(__file__).resolve().parents[1] / 'config' / 'cells'
        if not _cells_dir.exists():
            log.error('cells: config/cells/ directory ABSENT — the cell era engine '
                      'has no strategy source; the bot will trade NOTHING')
        self._pair_modules: dict[str, PairModule] = {
            pair: PairModule(pair) for pair in PAIRS
        }

        # ── Party Package (V6.1) — re-arming popper grids, additive module ────
        self.pp = PartyPackage(broker, dry_run)

        log.info("V5 engine ready (cell_v1) | dry_run=%s | %d pairs | exec=%s",
                 dry_run, len(PAIRS), CELL_EXECUTION_ENABLED)

        # Lock guard startup: fingerprint check for all locked cells with snapshots
        self._lock_guard_status: dict = lock_guard.startup_check(log)

        if not dry_run:
            self._recover_open_positions()

    _last_reconcile = None

    def _recover_open_positions(self) -> None:
        """Adopt any existing OANDA open trades at startup.

        Allows clean V4→V5 handoff without closing positions, and survives
        process restarts without orphaning trades.
        """
        try:
            trades = self.broker.open_positions()
        except Exception as exc:
            log.error("recovery: cannot fetch open positions: %s", exc)
            return

        if not trades:
            log.info("recovery: no open trades to adopt")
            return

        now = datetime.now(timezone.utc)
        for t in trades:
            pair = t["instrument"]
            # Poppers belong to the Party Package — they must never be adopted
            # as parent managers (multiple per pair, own gear).
            # B-112: the LIVE account mangles clientExtensions on the trades
            # endpoint (tag -> "0", comment truncated ~32 chars), so the tag
            # check alone orphaned live poppers. Classify by COMMENT SHAPE as
            # the fallback: parent gear comments start {"m": / {"su": (see
            # _encode_exit_ext); popper comments carry sl/tr/tp gear without
            # those keys. pp.recover() is already truncation-tolerant.
            _ce = t.get("clientExtensions") or {}
            _cm = _ce.get("comment", "") or ""
            _is_popper = _looks_like_popper(_ce)
            if _is_popper:
                try:
                    self.pp.recover(t)
                except Exception as exc:
                    log.exception("PP popper recovery failed for trade %s: %s",
                                  t.get("id"), exc)
                continue
            if pair in self.managers:
                # B-114 alarm: silence here is how four live trades vanished.
                log.warning("recovery: %s trade %s NOT adopted — pair already "
                            "has a parent manager; if this is a popper whose "
                            "comment lost its markers to truncation, it is now "
                            "UNMANAGED (server-side SL only)", pair, t.get("id"))
                continue
            if pair not in PIP:
                log.warning("recovery: unknown pair %s — skipping", pair)
                continue

            units_signed = int(t["currentUnits"])
            direction    = "long" if units_signed > 0 else "short"
            entry_price  = float(t["price"])
            entry_time   = datetime.fromisoformat(t["openTime"].replace("Z", "+00:00"))
            trade_id     = str(t["id"])

            # Stub ticket — just enough for RatchetManager to know pair + direction
            ticket = TradeTicket(
                pair=pair, session="recovery", direction=direction,
                score=0.0, dir_certainty=0.0, mom_certainty=0.0,
                vol_regime="unknown", expected_pips=0.0,
                timestamp=entry_time, reads={},
            )
            _persisted = _decode_exit_ext(t)
            oanda_sl = t.get("stopLossOrder", {}).get("price")
            initial_sl_price = float(oanda_sl) if oanda_sl else 0.0
            pos = Position(
                ticket=ticket,
                entry_price=entry_price,
                entry_time=entry_time,
                units=abs(units_signed),
                oanda_trade_id=trade_id,
                pip_size=PIP[pair],
                initial_sl_price=initial_sl_price,
                exit_params=_persisted[0] if _persisted else None,
            )
            _rec_mgr = RatchetManager
            if _persisted and _persisted[0].mode == "bracket":
                from modules.management.bracket import BracketManager as _BM
                _rec_mgr = _BM
            self.managers[pair] = _rec_mgr(
                position=pos,
                broker=self.broker,
                dry_run=self.dry_run,
                initial_units=abs(int(float(t.get("initialUnits", t.get("currentUnits", 0))))),
            )
            elapsed_min = (now - entry_time).total_seconds() / 60
            log.info("RECOVERED %s %s | entry=%.5f | trade_id=%s | elapsed=%.1fm | gear=%s",
                     pair, direction, entry_price, trade_id, elapsed_min,
                     f"persisted({_persisted[1]})" if _persisted else "exit_config-defaults")
            # Party Package (V6.1): recovered parents get grids too, anchored at
            # their original entry (idempotent — existing grids are kept).
            try:
                self.pp.on_parent_open(pos, _persisted[1] if _persisted else "recovered")
            except Exception as exc:
                log.exception("PP on_parent_open (recovery) failed: %s", exc)
            self.recent_events.append(
                f"{datetime.now(timezone.utc).strftime('%H:%M:%S')} RECOVERED {pair} {direction} @ {entry_price:.5f}"
            )

    def run_forever(self, scan_interval_seconds: int = 300, manage_interval_seconds: int = 30):
        log.info("V5 engine starting (dry_run=%s, scan=%ds, manage=%ds)",
                 self.dry_run, scan_interval_seconds, manage_interval_seconds)
        ticks_per_scan = max(1, round(scan_interval_seconds / manage_interval_seconds))
        i = 0
        while True:
            try:
                if i % ticks_per_scan == 0:
                    self._cycle()                              # full: manage + scan + enter
                else:
                    self._manage(datetime.now(timezone.utc))   # fast: exit-detect + ratchet only
            except Exception as exc:
                log.exception("loop error: %s", exc)
            time.sleep(manage_interval_seconds)
            i += 1

    def _manage(self, now: datetime) -> None:
        self.last_manage_time = now
        """Fast path -- runs every manage_interval. Detect server-side stop hits and
        tick the ratchet for each open position using a cheap pricing() poll (no
        candle fetch). The ratchet re-locks at step_cadence_min granularity, so this
        is what lets the trailing stop follow the peak between 5-min scan cycles."""
        if self.dry_run:
            return
        # RECONCILER (Brock, 2026-07-31: "all automated"): every 5 minutes,
        # regardless of what the engine THINKS it tracks, compare the broker's
        # open trades against the tracked set and adopt any orphan on the spot
        # via the recovery path (idempotent). This closes the B-112/B-114
        # class permanently — a restart, a wire-format bug, or a lost state
        # file self-heals within one reconcile tick instead of waiting for a
        # human to eyeball the dashboard against the broker app.
        _recon_due = (self._last_reconcile is None or
                      (now - self._last_reconcile).total_seconds() >= 300)
        if not self.managers and not self.pp.poppers and not self.pp.grids                 and not _recon_due:
            return

        try:
            _open_trades = self.broker.open_positions()
            oanda_open = {t["id"] for t in _open_trades}
        except Exception as exc:
            log.warning("open_positions failed: %s -- skip exit detection", exc)
            _open_trades, oanda_open = None, None

        if _recon_due and _open_trades is not None:
            self._last_reconcile = now
            _tracked = {str(m.position.oanda_trade_id)
                        for m in self.managers.values()}
            _tracked |= set(self.pp.poppers.keys())
            _orphans = [t for t in _open_trades if str(t["id"]) not in _tracked]
            if _orphans:
                log.warning("RECONCILER: %d broker trade(s) untracked %s — "
                            "re-running recovery adoption now",
                            len(_orphans),
                            [(t["id"], t["instrument"]) for t in _orphans])
                try:
                    self._recover_open_positions()
                    self.recent_events.append(
                        f"{now.strftime('%H:%M:%S')} RECONCILER adopted "
                        f"{len(_orphans)} orphan trade(s)")
                except Exception as exc:
                    log.exception("RECONCILER recovery failed: %s", exc)

        _rcfg = reaper_config()

        for pair in list(self.managers.keys()):
            mgr = self.managers[pair]
            try:
                bid, ask = self.feed.pricing(pair)
                # D-5 (external review): manage on the EXECUTABLE price — the
                # one this position could actually exit at (long: bid, short:
                # ask). Mid flattered peak/engage/lock by half the spread,
                # which is not bookkeeping at an 8.5p trigger.
                mid = executable_price(bid, ask, mgr.position.ticket.direction)
            except Exception as exc:
                log.warning("pricing %s failed: %s -- using entry price", pair, exc)
                mid = mgr.position.entry_price

            # Server-side stop already hit on OANDA
            if oanda_open is not None and mgr.position.oanda_trade_id not in oanda_open:
                _net = mgr.net_pips(mid)
                log.info("EXIT (server stop hit) %s | trade_id=%s | approx_net=%.2fp",
                         pair, mgr.position.oanda_trade_id, _net)
                self.recent_events.append(
                    f"{now.strftime('%H:%M:%S')} EXIT {pair} server-stop approx {'+' if _net >= 0 else ''}{_net:.1f}p"
                )
                if _net < 0:
                    self._sl_history[pair] = now
                del self.managers[pair]
                continue

            # STALE-RED REAPER (operator, 2026-08-08): red past the age cap
            # hogs a concurrency seat ready cells could use — close at market.
            # Same B-119 discipline as every close: a rejection keeps the
            # manager; only a confirmed close (or already-gone) books it.
            if _rcfg["enabled"]:
                _rnet = mgr.net_pips(mid)
                if reap_due(mgr.position.entry_time, now, _rnet, _rcfg):
                    log.info("EXIT (reaper: red > %.0fh) %s | trade_id=%s | net=%.2fp",
                             _rcfg["hours"], pair, mgr.position.oanda_trade_id, _rnet)
                    if not self.dry_run:
                        try:
                            self.broker.close_position(mgr.position.oanda_trade_id)
                        except CloseRejected as cr:
                            log.warning("reaper close rejected %s (%s) — manager "
                                        "kept, will retry", pair, cr.reason)
                            continue
                        except Exception as exc:
                            _gone = "404" in str(exc) or "does not exist" in str(exc).lower()
                            if not _gone:
                                log.warning("reaper close_position %s failed (%s) "
                                            "— manager kept", pair, exc)
                                continue
                            log.info("reaper close %s: already gone at broker", pair)
                    self.recent_events.append(
                        f"{now.strftime('%H:%M:%S')} REAP {pair} red>{_rcfg['hours']:.0f}h {_rnet:.1f}p")
                    self._sl_history[pair] = now   # reaped = a loss; cooldown applies
                    del self.managers[pair]
                    continue

            # Tick ratchet -- may call broker.move_stop() if the floor tightens
            signal = mgr.update(mid, now)
            if signal:
                log.info("EXIT (local detect) %s | %s | net=%.2fp",
                         pair, signal.reason, signal.net_pips)
                self.recent_events.append(
                    f"{now.strftime('%H:%M:%S')} EXIT {pair} {signal.reason} {'+' if signal.net_pips >= 0 else ''}{signal.net_pips:.1f}p"
                )
                if not self.dry_run:
                    try:
                        self.broker.close_position(mgr.position.oanda_trade_id)
                    except CloseRejected as cr:
                        # B-119: the broker KEPT the trade (MARKET_HALTED /
                        # FIFO). Deleting the manager here would orphan a
                        # live position on a phantom exit — keep managing.
                        log.warning("parent close rejected %s (%s) — manager "
                                    "kept, will retry", pair, cr.reason)
                        continue
                    except Exception as exc:
                        _gone = "404" in str(exc) or "does not exist" in str(exc).lower()
                        if not _gone:
                            log.warning("parent close_position %s failed (%s) "
                                        "— manager kept", pair, exc)
                            continue
                        log.info("parent close %s: already gone at broker", pair)
                if signal.net_pips < 0:
                    self._sl_history[pair] = now
                del self.managers[pair]

        # ── Party Package tick (V6.1): popper exits, ratchets, re-arm + fire ──
        # Additive and fenced — a PP failure can never touch parent management.
        try:
            self.pp.tick(now, oanda_open, set(self.managers.keys()),
                         self.feed.pricing)
        except Exception as exc:
            log.exception("PP tick failed: %s", exc)

    def _cycle(self):
        now = datetime.now(timezone.utc)

        # Steps 1+2: manage open positions (exit detection + ratchet).
        # ALWAYS runs — the trading-pause gate below only blocks NEW entries;
        # open positions keep being managed (ratchet + server-side stops) even
        # when paused.
        self._manage(now)

        # Trading-pause gate (hot-reload each cycle via config/runtime.json).
        # Fail-safe: trading_enabled() returns True on any read error. Log once
        # per ON<->PAUSED transition.
        _trading_on = trading_enabled()
        if _trading_on != self._trading_enabled_prev:
            if _trading_on:
                log.info("TRADING RESUMED — new entries re-enabled")
            else:
                log.warning("TRADING PAUSED — new entries suppressed (open positions still managed)")
            self._trading_enabled_prev = _trading_on

        # Step 3: full candles for signal evaluation
        # Review round 2: try to resolve quarantined order intents each cycle
        # (no-op when the quarantine is empty; a proven rejection clears it,
        # a proven fill stays flagged until a restart adopts the orphan).
        try:
            if getattr(self.broker, "quarantined", None):
                self.broker.retry_quarantine()
        except Exception as exc:
            log.warning("quarantine retry pass failed: %s", exc)

        views = self.feed.get_views(PAIRS)
        self.last_feed_time = now
        self.feed_views_n   = len(views)

        # Box direction-discovery probes (log-only, never trades). Ported from
        # V5 (Brock 2026-07-10): collect the full indicator vector at box
        # center/ceiling/floor to later mine for a which-way / breakout filter.
        # Additive + wrapped in try/except so a probe failure can never touch
        # trading. Scorer: research/tools/center_probe_score.py
        try:
            from modules.research import center_probe
            center_probe.observe(views, now)
        except Exception as _cpe:
            log.warning("center_probe hook failed: %s", _cpe)

        # ── Step 4: cells — THE strategy source ──────────────────────────────
        # Every in-session cell evaluates its setups. SHADOW setups stamp
        # CELLSHADOW and return None; ACTIVE setups return CellIntents.
        # Kill-switch: defaults.cell_shadow_enabled (hot-reload) — with the cell
        # era live this is the bot's master entry switch: off = no new trades.
        intents: list = []
        if pm_cell_shadow_enabled():
            for _pair_mod in self._pair_modules.values():
                _pview = next((v for v in views if v.pair == _pair_mod.pair), None)
                if _pview is None:
                    continue
                for _cell in _pair_mod.active_cells(now):
                    try:
                        _it = _cell.evaluate(_pview, now)
                        if _it is not None:
                            intents.append(_it)
                    except Exception as _ce:
                        log.warning('cells: evaluate %s/%s raised: %s',
                                    _pair_mod.pair, _cell.session, _ce)

        # Dashboard-compatible tickets from intents (TradeTicket shape retained)
        tickets = [self._ticket_from_intent(_it, now, rivals=len(intents) - 1)
                   for _it in intents]

        # ── Step 5: portfolio — risk caps only, no alpha ──────────────────────
        trade_ticket = self._select(tickets, views, now,
                                    opened_pairs=set(), opened_dirs={})

        # ── Update dashboard state ────────────────────────────────────────────
        self.last_views        = views
        self.last_tickets      = tickets
        self.last_trade_ticket = trade_ticket
        self.cycle_count      += 1
        self.last_cycle_time   = now

        # ── Per-cycle summary line (cell era) ─────────────────────────────────
        # CYCLE <iso_ts> picked=<pair/sess/dir or NONE> intents=<n>
        #   | <pair>/<sess>/<side> setup=<id> ev_seq=<x> | ...
        _picked_tag = "NONE"
        if trade_ticket is not None:
            _picked_tag = f"{trade_ticket.pair}/{trade_ticket.session}/{trade_ticket.direction}"
        _cycle_parts = [f"CYCLE {now.isoformat()} picked={_picked_tag} intents={len(intents)}"]
        for _it in intents:
            _cycle_parts.append(
                f"{_it.pair}/{_it.session}/{_it.side} setup={_it.setup_id} "
                f"ev_seq={(_it.expected.get('ev_seq') or 0.0):+.2f}"
            )
        log.info(" | ".join(_cycle_parts))

        # ── Formula shadow stamps (log-only, view-based) ──────────────────────
        # Independent falsification instrument — evaluates registry formulas on
        # raw features. Kill-switch: defaults.formula_shadow_enabled (hot-reload).
        # Scorer: research/tools/formula_shadow_score.py --since YYYY-MM-DD.
        if pm_formula_shadow_enabled() and _formula_shadow.formula_shadow_enabled():
            for _v in views:
                for _fe in _formula_shadow.get_entries_for(_v.pair, _v.session):
                    if _fe.status == "INACTIVE":
                        continue   # INACTIVE-pending-feed-extension; skip silently
                    _n_met, _n_total = _formula_shadow.evaluate(_fe, _v)
                    if _n_met == _n_total and _n_total > 0:
                        log.info(
                            "FORMULA %s qualifies side=%s conds_met=%d/%d"
                            " geo=%s/%s/%s exp_ev=%+.2f status=%s ts=%s",
                            _fe.cell, _fe.direction,
                            _n_met, _n_total,
                            _fe.target_sl, _fe.target_trigger, _fe.target_trail,
                            _fe.expected_ev, _fe.status, now.isoformat(),
                        )

        if trade_ticket is None:
            return

        # TRADING PAUSE: suppress ALL new entries this cycle. Dashboard state
        # (tickets/intents/last_trade_ticket) is already updated above so the UI
        # still shows what WOULD have fired; open positions were already managed.
        if not _trading_on:
            return

        # Open every cap-passing intent this cycle (up to max_concurrent).
        # Re-select each iteration with opened pairs excluded; select_intent
        # re-enforces max_concurrent, 1-per-pair, cooldown, spread, currency cap.
        opened_pairs: set[str] = set()
        opened_dirs: dict[str, str] = {}   # pair -> traded direction, this cycle
        picked = trade_ticket
        while picked is not None:
            self._signal_and_open(picked, views, now)
            opened_pairs.add(picked.pair)
            opened_dirs[picked.pair] = picked.direction
            picked = self._select(tickets, views, now, opened_pairs, opened_dirs)

    # ── Cell-era helpers ──────────────────────────────────────────────────────

    def _ticket_from_intent(self, intent, now: datetime, rivals: int = 0) -> TradeTicket:
        """Dashboard/journal-compatible TradeTicket wrapping a CellIntent."""
        _ev = float(intent.expected.get("ev_seq") or 0.0)
        return TradeTicket(
            pair=intent.pair, session=intent.session, direction=intent.side,
            score=_ev, dir_certainty=0.0, mom_certainty=0.0,
            vol_regime="cell", expected_pips=_ev,
            timestamp=now,
            reads={"cell": {"setup_id": intent.setup_id,
                            "horizon_min": intent.horizon_min,
                            "lineage": intent.expected.get("lineage", "")},
                   "direction": {}, "momentum": {}},
            rivals=rivals,
            cell=intent,
        )

    def _select(self, tickets: list, views: list, now: datetime,
                opened_pairs: set, opened_dirs: dict) -> Optional[TradeTicket]:
        """Portfolio selection over remaining tickets; returns a ticket or None.
        Exposure map = live managers overlaid with this cycle's opens (covers
        dry_run, where _open_trade never registers a manager)."""
        # V6.1: poppers count toward the concurrent-trade cap, and a pair with
        # an active popper grid may not open a second parent.
        if len(self.managers) + self.pp.open_popper_count() >= pm_max_concurrent():
            return None
        _open_pos = {p: mgr.direction for p, mgr in self.managers.items()}
        _open_pos.update(opened_dirs)
        _intent = select_intent(
            [t.cell for t in tickets if t.cell is not None],
            open_pairs=set(self.managers.keys()) | opened_pairs | self.pp.busy_pairs(),
            open_positions=list(_open_pos.items()),
            views=views,
            sl_history=self._sl_history,
            now=now,
        )
        if _intent is None:
            return None
        return next(t for t in tickets if t.cell is _intent)

    def _signal_and_open(self, trade_ticket, views, now):
        _it = trade_ticket.cell
        _ep = _it.exit_params if _it is not None else None
        _conds = _it.conds_snapshot if _it is not None else {}
        log.info("SIGNAL %s %s | engine=cell_v1 setup=%s h=%dm ev_seq=%+.2f rivals=%d "
                 "| exit=%.1f/%.1f/%.1f | conds=%s",
                 trade_ticket.pair, trade_ticket.direction,
                 _it.setup_id if _it else "?",
                 _it.horizon_min if _it else 0,
                 trade_ticket.expected_pips, trade_ticket.rivals,
                 _ep.sl_pips if _ep else 0.0,
                 _ep.trigger_pips if _ep else 0.0,
                 _ep.trail_pips if _ep else 0.0,
                 _conds)

        if not self.dry_run:
            self._open_trade(trade_ticket, views, now)

    def _open_trade(self, ticket: TradeTicket, views: list, now: datetime):
        # Review round 2: while ANY order intent is quarantined (fate unproven
        # at the broker), no new entries — management continues elsewhere.
        if getattr(self.broker, "quarantined", None):
            log.critical("ENTRY BLOCKED %s — %d order intent(s) in quarantine; "
                         "no new entries until the broker proves their fate",
                         ticket.pair, len(self.broker.quarantined))
            return
        view = next(v for v in views if v.pair == ticket.pair)
        pip  = PIP[ticket.pair]

        entry_price = view.ask if ticket.direction == "long" else view.bid
        # Cell era: the setup's own exit geometry drives the order SL and the
        # ratchet (Position.exit_params → RatchetManager override). Fallback to
        # the legacy per-pair SL only for cell-less tickets (recovery stubs).
        _it = ticket.cell
        _ep = _it.exit_params if _it is not None else None
        initial_sl = float(_ep.sl_pips) if _ep is not None else initial_sl_pips_for(ticket.pair)
        # Sizing: margin model unchanged at cutover (pm_margin_pct) — per-setup
        # risk_pct normalization is a flagged follow-up, NOT silently invented.
        _mp = pm_margin_pct()
        if _it is not None and getattr(_it, "probe", False):
            _mp *= pm_probe_mult()     # PROBE seat: reduced-size audition
        units = self.broker.size_units(ticket.pair, ticket.direction,
                                       margin_pct=_mp)
        _mode    = str(getattr(_ep, "mode", "ratchet") or "ratchet") if _ep else "ratchet"
        _tp_pips = float(getattr(_ep, "tp_pips", 0.0) or 0.0) if _mode == "bracket" else 0.0
        try:
            trade = self.broker.place_market(
                ticket.pair, ticket.direction, units=units,
                entry_price=entry_price, sl_pips=initial_sl, tp_pips=_tp_pips,
                client_ext=_encode_exit_ext(_ep, _it.setup_id) if _ep is not None else None,
            )
        except OrderUncertain as exc:
            log.critical("ORDER QUARANTINE intent=%s (%s) — new entries disabled "
                         "pending broker reconciliation; existing management "
                         "unaffected", exc.intent_id, ticket.pair)
            self.recent_events.append(
                f"{now.strftime('%H:%M:%S')} QUARANTINE {ticket.pair} intent={exc.intent_id}")
            return

        # Review round 2: an empty trade id is a broker-proven NO-FILL (the
        # poppers already refused these, B-097) — a parent Position must never
        # be built around oanda_trade_id="".
        if not str(trade.get("id") or ""):
            log.warning("ENTRY REJECTED %s %s — broker returned no filled trade "
                        "(order cancelled/rejected); no position created",
                        ticket.pair, ticket.direction)
            return

        # D-5 (external review): the broker's fill is the ONLY true entry.
        # Position, SL reference, and every ratchet baseline derive from it —
        # the pre-order quote was just the estimate we sized against. (The
        # server-side SL is already fill-anchored: place_market sends distance.)
        quoted = entry_price
        entry_price, slippage = adopt_fill(quoted, trade, ticket.direction, pip)
        if slippage is None:
            log.warning("FILL price missing from broker response %s trade_id=%s — "
                        "falling back to pre-order quote %.5f (entry truth degraded)",
                        ticket.pair, trade.get("id"), quoted)
        else:
            log.info("FILL %s %s quoted=%.5f filled=%.5f slippage=%+.2fp spread=%.1fp",
                     ticket.pair, ticket.direction, quoted, entry_price, slippage,
                     float(getattr(view, "spread_pips", 0.0) or 0.0))

        initial_sl_price = (entry_price - initial_sl * pip
                            if ticket.direction == "long"
                            else entry_price + initial_sl * pip)
        pos = Position(
            ticket=ticket,
            entry_price=entry_price,
            entry_time=now,
            units=units,
            oanda_trade_id=str(trade["id"]),
            pip_size=pip,
            initial_sl_price=initial_sl_price,
            exit_params=_ep,
        )
        _mgr_cls = BracketManager if _mode == "bracket" else RatchetManager
        self.managers[ticket.pair] = _mgr_cls(
            position=pos,
            broker=self.broker,
            dry_run=self.dry_run,
            initial_units=units,
        )
        log.info("ENTERED %s %s @ %.5f | %d units | SL -%.1fp | trade_id=%s | "
                 "engine=cell_v1 setup=%s exit_mode=%s tp=%.1fp",
                 ticket.pair, ticket.direction, entry_price, units,
                 initial_sl, trade["id"],
                 _it.setup_id if _it else "recovery", _mode, _tp_pips)
        # Party Package (V6.1): hang the popper grid off this parent.
        try:
            self.pp.on_parent_open(pos, _it.setup_id if _it else "?",
                                   probe=bool(_it and getattr(_it, "probe", False)))
        except Exception as exc:
            log.exception("PP on_parent_open failed: %s", exc)
        self.recent_events.append(
            f"{now.strftime('%H:%M:%S')} ENTER {ticket.pair} {ticket.direction} @ {entry_price:.5f}"
        )
        # Increment per-session-instance open count for locked cell throttle tracking.
        # Prune keys older than 2 days to bound dict size.
        _inst = lock_guard.session_instance_key(ticket.session, now)
        _opens_key = f"{ticket.pair}|{ticket.session}|{ticket.direction}|{_inst}"
        self._cell_opens[_opens_key] = self._cell_opens.get(_opens_key, 0) + 1
        from datetime import timedelta as _td
        _cutoff_date = (now - _td(days=2)).strftime("%Y-%m-%d")
        self._cell_opens = {k: v for k, v in self._cell_opens.items()
                            if k.split("|")[-1].split("@")[-1] >= _cutoff_date}
