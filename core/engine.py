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
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from config.pairs import PAIRS, PIP
from core.broker.oanda import DEFAULT_INITIAL_SL_PIPS
from modules.signals import formula_shadow as _formula_shadow
from modules.playmaker.playmaker import (TradeTicket, pm_margin_pct,
                                          pm_formula_shadow_enabled,
                                          pm_cell_shadow_enabled)
from modules.playmaker import lock_guard
from modules.management.base import Position
from modules.management.ratchet import RatchetManager, initial_sl_pips_for
from modules.management.bracket import BracketManager
from modules.cells import PairModule, CELL_EXECUTION_ENABLED
from modules.cells.portfolio import select_intent

log = logging.getLogger("v5.engine")

_SESSIONS = ["asia", "london", "ny"]


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

        log.info("V5 engine ready (cell_v1) | dry_run=%s | %d pairs | exec=%s",
                 dry_run, len(PAIRS), CELL_EXECUTION_ENABLED)

        # Lock guard startup: fingerprint check for all locked cells with snapshots
        self._lock_guard_status: dict = lock_guard.startup_check(log)

        if not dry_run:
            self._recover_open_positions()

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
            if pair in self.managers:
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
            )
            self.managers[pair] = RatchetManager(
                position=pos,
                broker=self.broker,
                dry_run=self.dry_run,
                initial_units=abs(int(float(t.get("initialUnits", t.get("currentUnits", 0))))),
            )
            elapsed_min = (now - entry_time).total_seconds() / 60
            log.info("RECOVERED %s %s | entry=%.5f | trade_id=%s | elapsed=%.1fm",
                     pair, direction, entry_price, trade_id, elapsed_min)
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
        if self.dry_run or not self.managers:
            return

        try:
            oanda_open = {t["id"] for t in self.broker.open_positions()}
        except Exception as exc:
            log.warning("open_positions failed: %s -- skip exit detection", exc)
            oanda_open = None

        for pair in list(self.managers.keys()):
            mgr = self.managers[pair]
            try:
                bid, ask = self.feed.pricing(pair)
                mid = (bid + ask) / 2.0
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
                    except Exception as exc:
                        log.warning("close_position %s: %s (OANDA may have beaten us)", pair, exc)
                if signal.net_pips < 0:
                    self._sl_history[pair] = now
                del self.managers[pair]

    def _cycle(self):
        now = datetime.now(timezone.utc)

        # Steps 1+2: manage open positions (exit detection + ratchet)
        self._manage(now)

        # Step 3: full candles for signal evaluation
        views = self.feed.get_views(PAIRS)
        self.last_feed_time = now
        self.feed_views_n   = len(views)

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
        _open_pos = {p: mgr.direction for p, mgr in self.managers.items()}
        _open_pos.update(opened_dirs)
        _intent = select_intent(
            [t.cell for t in tickets if t.cell is not None],
            open_pairs=set(self.managers.keys()) | opened_pairs,
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
        units = self.broker.size_units(ticket.pair, ticket.direction,
                                       margin_pct=pm_margin_pct())
        _mode    = str(getattr(_ep, "mode", "ratchet") or "ratchet") if _ep else "ratchet"
        _tp_pips = float(getattr(_ep, "tp_pips", 0.0) or 0.0) if _mode == "bracket" else 0.0
        trade = self.broker.place_market(
            ticket.pair, ticket.direction, units=units,
            entry_price=entry_price, sl_pips=initial_sl, tp_pips=_tp_pips,
        )

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
