"""modules/management/party_package.py — Party Package (V6.1, 2026-07-19).

Re-arming grid of "popper" trades hung off each parent (cell) position.

Brock's spec (research day 2026-07-19, Mini scrooge-research-tools/2026-07-19-scale-in/):
when a parent trade opens, lay grid levels every ``step_pips`` on the ADVERSE
side of the parent entry. An armed level FIRES a popper — a fully independent
trade in the parent's direction with its own server-side SL (``sl_pips`` from
ITS OWN fill) and its own ratchet (``trigger_pips``/``trail_pips``) — when
price crosses the level. A level RE-ARMS after its popper closes AND price
re-crosses the level from the favorable side, so oscillating tape harvests
repeatedly ("the waves").

Research verdict this deploys against: on sim costs the grid gross-harvests
~+100-150p/parent but pays more in spread+slippage toll. The practice tape is
the forward truth machine for that cost model — every popper is stamped
``engine=pp_v1`` in logs and tagged ``pp_v1`` in OANDA client extensions so
broker-truth scoring can attribute parent vs popper P&L exactly.

Safety posture:
  - Additive module: parents' entry/exit logic untouched.
  - Fires are gated on: pp enabled flag, engine not dry_run, trading pause,
    rollover freeze (20:55-22:05Z), spread fail-closed, total-trade cap and
    total-margin cap (poppers + parents both count).
  - All state persists to data/pp_state.json; open poppers are re-adopted on
    restart from their pp_v1 client extensions (grid rebuilt if state lost).
  - Kill switch: config/pp_config.json {"enabled": false} — hot-reloaded; open
    poppers keep being managed to exit, no new fires.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from config.pairs import PIP
from modules.playmaker.playmaker import (TradeTicket, pm_margin_pct,
                                          pm_max_concurrent,
                                          _MAX_SPREAD, _DEFAULT_MAX_SPREAD)
from config.runtime import trading_enabled
from .base import Position, in_rollover_freeze
from .ratchet import RatchetManager

log = logging.getLogger("v5.pp")

_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "pp_config.json"
_STATE_PATH  = Path(__file__).resolve().parent.parent.parent / "data" / "pp_state.json"

# Defaults mirror config/pp_config.json — used when the JSON is missing/corrupt.
_DEFAULTS: dict = {
    "enabled":              True,
    "step_pips":            15.0,   # LEGACY fallback when marker_pips absent
    # Explicit marker ladder (Brock 2026-07-22, sim: dense top double-harvests
    # shallow chop, skip -50, one deep rung): adverse offsets in pips.
    "marker_pips":          [10.0, 15.0, 20.0, 30.0, 40.0, 60.0],
    "sl_pips":              60.0,   # popper server-side SL from ITS OWN fill
    "trigger_pips":         8.5,    # popper ratchet engage (lock = trigger - trail = +6)
    "trail_pips":           2.5,    # popper trail (lock = trigger - trail)
    "max_levels":           8,      # deepest grid level (8 x 15p = 120p below anchor)
    "max_total_trades":     8,      # parents + poppers, book-wide
    "max_margin_pct_total": 0.8,    # parents + poppers, fraction of balance
    "grid_max_age_days":    7.0,    # retire a grid this long after parent entry
    "per_cell":             {},     # "PAIR|session|setup" (or "PAIR|session" or "PAIR") -> bool
}


def pp_config() -> dict:
    """Hot-reloaded pp config (same pattern as exit_config)."""
    try:
        with open(_CONFIG_PATH) as fh:
            raw = json.load(fh)
        cfg = dict(_DEFAULTS)
        for k, v in raw.items():
            if k not in _DEFAULTS:
                continue
            if isinstance(_DEFAULTS[k], dict):
                cfg[k] = dict(v) if isinstance(v, dict) else {}
            elif isinstance(_DEFAULTS[k], list):
                try:
                    lst = sorted(float(x) for x in v)
                    cfg[k] = lst if lst and all(x > 0 for x in lst) else list(_DEFAULTS[k])
                except (TypeError, ValueError):
                    cfg[k] = list(_DEFAULTS[k])
            elif isinstance(_DEFAULTS[k], bool):
                cfg[k] = bool(v)
            elif isinstance(_DEFAULTS[k], float):
                cfg[k] = float(v)
            else:
                cfg[k] = int(v)
        return cfg
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return dict(_DEFAULTS)


def pp_cell_enabled(cfg: dict, pair: str, session: str, setup_id: str) -> bool:
    """Per-cell popper opt-out. Most-specific key wins:
    "PAIR|session|setup" > "PAIR|session" > "PAIR" > default True."""
    pc = cfg.get("per_cell") or {}
    for key in (f"{pair}|{session}|{setup_id}", f"{pair}|{session}", pair):
        if key in pc:
            return bool(pc[key])
    return True


def _popper_exit_params(cfg: dict):
    from modules.cells.cell import ExitParams
    return ExitParams(sl_pips=float(cfg["sl_pips"]),
                      trigger_pips=float(cfg["trigger_pips"]),
                      trail_pips=float(cfg["trail_pips"]),
                      mode="ratchet")


def _okey(offset_pips) -> str:
    """Canonical string key for a marker offset (10.0 -> "10", 12.5 -> "12.5")."""
    return "%g" % float(offset_pips)


def _popper_client_ext(cfg: dict, offset_pips: float, anchor: float) -> dict:
    """OANDA tradeClientExtensions for a popper. tag=pp_v1 routes recovery away
    from the parent adopter; comment carries the gear + grid coordinates.
    lvl = the marker OFFSET in pips (ladder era, 2026-07-22)."""
    comment = json.dumps({"sl": cfg["sl_pips"], "tr": cfg["trigger_pips"],
                          "tp": cfg["trail_pips"], "lvl": float(offset_pips),
                          "anc": round(anchor, 5), "su": "pp_v1"},
                         separators=(",", ":"))
    return {"tag": "pp_v1", "comment": comment}


class Grid:
    """One re-arming grid per pair, anchored at the parent entry price."""

    def __init__(self, pair: str, side: str, anchor: float, created: datetime,
                 parent_setup: str = "?", cell_key: str = ""):
        self.pair = pair
        self.side = side                    # popper direction == parent direction
        self.anchor = anchor
        self.created = created
        self.parent_setup = parent_setup
        self.cell_key = cell_key            # "PAIR|session|setup" for the per-cell switch
        # marker key (_okey(offset_pips)) -> {"armed": bool, "trade_id": Optional[str]}
        self.levels: dict[str, dict] = {}
        # lifetime ledger (persisted)
        self.greens = 0
        self.knives = 0
        self.green_pips = 0.0
        self.knife_pips = 0.0
        self.fired_total = 0

    def level_price(self, offset_pips: float) -> float:
        pip = PIP[self.pair]
        off = float(offset_pips) * pip
        return self.anchor - off if self.side == "long" else self.anchor + off

    def to_dict(self) -> dict:
        return {"pair": self.pair, "side": self.side, "anchor": self.anchor,
                "created": self.created.isoformat(),
                "parent_setup": self.parent_setup,
                "cell_key": self.cell_key,
                "fmt": "offsets",   # ladder era (2026-07-22): keys are pip offsets
                "levels": dict(self.levels),
                "greens": self.greens, "knives": self.knives,
                "green_pips": round(self.green_pips, 1),
                "knife_pips": round(self.knife_pips, 1),
                "fired_total": self.fired_total}

    @classmethod
    def from_dict(cls, d: dict) -> "Grid":
        g = cls(d["pair"], d["side"], float(d["anchor"]),
                datetime.fromisoformat(d["created"]), d.get("parent_setup", "?"),
                d.get("cell_key", ""))
        raw = d.get("levels") or {}
        if d.get("fmt") == "offsets":
            g.levels = {str(k): dict(v) for k, v in raw.items()}
        else:  # migrate pre-ladder state: index keys 1..N at the legacy 15p step
            g.levels = {_okey(int(k) * 15.0): dict(v) for k, v in raw.items()}
        g.greens = int(d.get("greens", 0)); g.knives = int(d.get("knives", 0))
        g.green_pips = float(d.get("green_pips", 0.0))
        g.knife_pips = float(d.get("knife_pips", 0.0))
        g.fired_total = int(d.get("fired_total", 0))
        return g


class PartyPackage:
    """Grid + popper lifecycle. One instance owned by the Engine."""

    def __init__(self, broker, dry_run: bool):
        self.broker = broker
        self.dry_run = dry_run
        self.grids: dict[str, Grid] = {}              # pair -> Grid
        self.poppers: dict[str, RatchetManager] = {}  # trade_id -> manager
        self._popper_grid: dict[str, tuple[str, int]] = {}  # trade_id -> (pair, level_idx)
        self._load_state()

    # ── lifecycle hooks ──────────────────────────────────────────────────────

    def on_parent_open(self, pos: Position, setup_id: str = "?") -> None:
        cfg = pp_config()
        if not cfg["enabled"] or self.dry_run:
            return
        pair = pos.ticket.pair
        session = pos.ticket.session or "?"
        if not pp_cell_enabled(cfg, pair, session, setup_id):
            log.info("PP GRID skipped %s/%s setup=%s — poppers disabled for this cell "
                     "| engine=pp_v1", pair, session, setup_id)
            return
        if pair in self.grids:
            log.info("PP GRID exists for %s — parent joins existing grid | engine=pp_v1", pair)
            return
        g = Grid(pair, pos.ticket.direction, pos.entry_price,
                 pos.entry_time if pos.entry_time.tzinfo else
                 pos.entry_time.replace(tzinfo=timezone.utc), setup_id,
                 cell_key=f"{pair}|{session}|{setup_id}")
        for off in cfg["marker_pips"]:
            g.levels[_okey(off)] = {"armed": True, "trade_id": None}
        self.grids[pair] = g
        log.info("PP GRID armed %s %s anchor=%.5f markers=%s | engine=pp_v1 setup=%s",
                 pair, g.side, g.anchor,
                 "/".join("-" + _okey(o) for o in cfg["marker_pips"]), setup_id)
        self._save_state()

    def recover(self, trade: dict) -> None:
        """Adopt an open OANDA popper trade (tag=pp_v1) at startup."""
        pair = trade["instrument"]
        if pair not in PIP:
            return
        try:
            d = json.loads((trade.get("clientExtensions") or {}).get("comment", "{}"))
        except (ValueError, json.JSONDecodeError):
            d = {}
        units_signed = int(trade["currentUnits"])
        direction = "long" if units_signed > 0 else "short"
        entry_price = float(trade["price"])
        entry_time = datetime.fromisoformat(trade["openTime"].replace("Z", "+00:00"))
        trade_id = str(trade["id"])
        _rawlvl = float(d.get("lvl", 0) or 0)
        # migration: pre-ladder comments carried the level INDEX (1..8, 15p step);
        # ladder-era comments carry the offset in pips directly.
        lvl_off = _rawlvl * 15.0 if 0 < _rawlvl <= 9 else _rawlvl
        cfg = pp_config()

        if pair not in self.grids:
            anchor = float(d.get("anc", entry_price))
            g = Grid(pair, direction, anchor, entry_time, "recovered")
            for off in cfg["marker_pips"]:
                g.levels[_okey(off)] = {"armed": False, "trade_id": None}
            self.grids[pair] = g
            log.info("PP GRID rebuilt from popper recovery %s anchor=%.5f | engine=pp_v1",
                     pair, anchor)
        if lvl_off:
            # ensure a state slot exists even if the offset left the config ladder
            self.grids[pair].levels[_okey(lvl_off)] = {"armed": False, "trade_id": trade_id}

        ticket = TradeTicket(pair=pair, session="pp", direction=direction,
                             score=0.0, dir_certainty=0.0, mom_certainty=0.0,
                             vol_regime="pp", expected_pips=0.0,
                             timestamp=entry_time, reads={})
        from modules.cells.cell import ExitParams
        ep = ExitParams(sl_pips=float(d.get("sl", cfg["sl_pips"])),
                        trigger_pips=float(d.get("tr", cfg["trigger_pips"])),
                        trail_pips=float(d.get("tp", cfg["trail_pips"])), mode="ratchet")
        oanda_sl = (trade.get("stopLossOrder") or {}).get("price")
        pos = Position(ticket=ticket, entry_price=entry_price, entry_time=entry_time,
                       units=abs(units_signed), oanda_trade_id=trade_id,
                       pip_size=PIP[pair],
                       initial_sl_price=float(oanda_sl) if oanda_sl else 0.0,
                       exit_params=ep)
        self.poppers[trade_id] = RatchetManager(position=pos, broker=self.broker,
                                                dry_run=self.dry_run,
                                                initial_units=abs(units_signed))
        self._popper_grid[trade_id] = (pair, lvl_off)
        log.info("PP RECOVERED popper %s %s marker=-%sp @ %.5f trade_id=%s | engine=pp_v1",
                 pair, direction, _okey(lvl_off), entry_price, trade_id)
        self._save_state()

    # ── per-tick work ────────────────────────────────────────────────────────

    def tick(self, now: datetime, oanda_open: Optional[set],
             parent_pairs: set, pricing: Callable[[str], tuple]) -> None:
        """Called from Engine._manage after the parent loop. oanda_open is the
        already-fetched set of open trade ids (None = API failed this tick:
        skip exit detection, still no fires)."""
        if self.dry_run:
            return
        cfg = pp_config()

        # 1) popper exits: server-side stop hits
        if oanda_open is not None:
            for tid in list(self.poppers.keys()):
                if tid in oanda_open:
                    continue
                mgr = self.poppers[tid]
                pair, lvl = self._popper_grid.get(tid, (mgr.position.ticket.pair, 0))
                try:
                    bid, ask = pricing(pair)
                    mid = (bid + ask) / 2.0
                except Exception:
                    mid = mgr.position.entry_price
                net = mgr.net_pips(mid)
                self._book_exit(pair, lvl, tid, net, "server-stop", now)

        # 2) popper ratchet tick + local exit detect
        for tid in list(self.poppers.keys()):
            mgr = self.poppers[tid]
            pair, lvl = self._popper_grid.get(tid, (mgr.position.ticket.pair, 0))
            try:
                bid, ask = pricing(pair)
                mid = (bid + ask) / 2.0
            except Exception as exc:
                log.warning("PP pricing %s failed: %s", pair, exc)
                continue
            signal = mgr.update(mid, now)
            if signal:
                try:
                    self.broker.close_position(tid)
                except Exception as exc:
                    log.warning("PP close_position %s: %s (OANDA may have beaten us)",
                                tid, exc)
                self._book_exit(pair, lvl, tid, signal.net_pips, signal.reason, now)

        # 3) re-arm + fire per grid
        for pair in list(self.grids.keys()):
            g = self.grids[pair]
            try:
                bid, ask = pricing(pair)
            except Exception:
                continue
            mid = (bid + ask) / 2.0
            pip = PIP[pair]
            spread_pips = (ask - bid) / pip

            # retire stale grids: no parent, no open poppers, price back above
            # the shallowest marker (long) — or hard age cap
            busy = any(v["trade_id"] for v in g.levels.values())
            age_days = (now - g.created).total_seconds() / 86400.0
            first_lvl = g.level_price(min(cfg["marker_pips"]))
            back_in_zone = mid > first_lvl if g.side == "long" else mid < first_lvl
            if (pair not in parent_pairs and not busy
                    and (back_in_zone or age_days > cfg["grid_max_age_days"])):
                log.info("PP GRID retired %s | age=%.1fd fired=%d greens=%d knives=%d "
                         "net=%+.1fp | engine=pp_v1", pair, age_days, g.fired_total,
                         g.greens, g.knives, g.green_pips + g.knife_pips)
                del self.grids[pair]
                self._save_state()
                continue

            for off in cfg["marker_pips"]:
                key = _okey(off)
                lv = g.levels.setdefault(key, {"armed": True, "trade_id": None})
                price = g.level_price(off)
                if lv["trade_id"]:
                    continue                       # popper open at this marker
                crossed_back = mid > price if g.side == "long" else mid < price
                crossed_into = mid <= price if g.side == "long" else mid >= price
                if not lv["armed"]:
                    if crossed_back:
                        lv["armed"] = True
                    continue
                if not crossed_into:
                    continue
                # ---- fire gates ----
                if not cfg["enabled"]:
                    continue
                if g.cell_key:
                    _p, _s, _su = (g.cell_key.split("|") + ["?", "?"])[:3]
                    if not pp_cell_enabled(cfg, _p, _s, _su):
                        continue     # cell opted out — manage open poppers, no new fires
                if not trading_enabled():
                    continue
                if in_rollover_freeze(now):
                    continue
                if spread_pips <= 0.0 or spread_pips > _MAX_SPREAD.get(pair, _DEFAULT_MAX_SPREAD):
                    continue
                n_open = len(parent_pairs) + len(self.poppers)
                cap = min(int(cfg["max_total_trades"]), pm_max_concurrent())
                if n_open >= cap:
                    log.info("PP SKIP fire %s marker=-%sp reason=trade_cap (%d/%d) | engine=pp_v1",
                             pair, key, n_open, cap)
                    continue
                if (n_open + 1) * pm_margin_pct() > cfg["max_margin_pct_total"] + 1e-9:
                    log.info("PP SKIP fire %s marker=-%sp reason=margin_cap | engine=pp_v1", pair, key)
                    continue
                self._fire(g, off, bid, ask, now, cfg)

    # ── internals ────────────────────────────────────────────────────────────

    def _fire(self, g: Grid, offset_pips: float, bid: float, ask: float,
              now: datetime, cfg: dict) -> None:
        pair = g.pair
        key = _okey(offset_pips)
        entry_price = ask if g.side == "long" else bid
        try:
            units = self.broker.size_units(pair, g.side, margin_pct=pm_margin_pct())
            trade = self.broker.place_market(
                pair, g.side, units=units, entry_price=entry_price,
                sl_pips=float(cfg["sl_pips"]),
                client_ext=_popper_client_ext(cfg, offset_pips, g.anchor),
            )
        except Exception as exc:
            log.warning("PP FIRE failed %s marker=-%sp: %s", pair, key, exc)
            return
        trade_id = str(trade["id"])
        pip = PIP[pair]
        sl_price = (entry_price - cfg["sl_pips"] * pip if g.side == "long"
                    else entry_price + cfg["sl_pips"] * pip)
        ticket = TradeTicket(pair=pair, session="pp", direction=g.side,
                             score=0.0, dir_certainty=0.0, mom_certainty=0.0,
                             vol_regime="pp", expected_pips=0.0,
                             timestamp=now, reads={})
        pos = Position(ticket=ticket, entry_price=entry_price, entry_time=now,
                       units=units, oanda_trade_id=trade_id, pip_size=pip,
                       initial_sl_price=sl_price,
                       exit_params=_popper_exit_params(cfg))
        self.poppers[trade_id] = RatchetManager(position=pos, broker=self.broker,
                                                dry_run=self.dry_run,
                                                initial_units=units)
        self._popper_grid[trade_id] = (pair, float(offset_pips))
        g.levels[key] = {"armed": False, "trade_id": trade_id}
        g.fired_total += 1
        log.info("POPPER FIRE %s %s marker=-%sp @ %.5f | %d units | SL -%.1fp ratchet %.1f/%.1f "
                 "| trade_id=%s | engine=pp_v1 anchor=%.5f",
                 pair, g.side, key, entry_price, units, cfg["sl_pips"],
                 cfg["trigger_pips"], cfg["trail_pips"], trade_id, g.anchor)
        self._save_state()

    def _book_exit(self, pair: str, lvl_off: float, trade_id: str, net_pips: float,
                   reason: str, now: datetime) -> None:
        g = self.grids.get(pair)
        key = _okey(lvl_off)
        if g is not None:
            if net_pips > 0:
                g.greens += 1; g.green_pips += net_pips
            else:
                g.knives += 1; g.knife_pips += net_pips
            if key in g.levels and g.levels[key].get("trade_id") == trade_id:
                # disarmed until price re-crosses the marker from the favorable side
                g.levels[key] = {"armed": False, "trade_id": None}
        self.poppers.pop(trade_id, None)
        self._popper_grid.pop(trade_id, None)
        log.info("POPPER EXIT %s marker=-%sp | %s | net=%+.2fp | trade_id=%s | engine=pp_v1",
                 pair, key, reason, net_pips, trade_id)
        self._save_state()

    # ── introspection / persistence ──────────────────────────────────────────

    def open_popper_count(self) -> int:
        return len(self.poppers)

    def busy_pairs(self) -> set:
        """Pairs with an active grid (blocks a second parent on the same pair)."""
        return set(self.grids.keys())

    def state(self) -> dict:
        cfg = pp_config()
        out = {"enabled": bool(cfg["enabled"]), "config": cfg,
               "per_cell": dict(cfg.get("per_cell") or {}),
               "open_poppers": len(self.poppers), "grids": []}
        for pair, g in self.grids.items():
            d = g.to_dict()
            d["level_prices"] = {k: round(g.level_price(float(k)), 5)
                                 for k in sorted(g.levels.keys(), key=float)}
            popper_rows = []
            for tid, (p, lvl) in self._popper_grid.items():
                if p != pair:
                    continue
                mgr = self.poppers.get(tid)
                if mgr is None:
                    continue
                sgn = 1.0 if mgr.direction == "long" else -1.0
                peak_pips = sgn * (mgr.peak_price - mgr.position.entry_price) / mgr.pip
                locked = mgr.sl_locked_pips
                popper_rows.append({"trade_id": tid, "level": lvl,
                                    "entry": mgr.position.entry_price,
                                    "units": mgr.position.units,
                                    "peak_pips": round(peak_pips, 1),
                                    "sl_locked_pips": round(locked, 1) if locked is not None else None,
                                    "engaged": bool(locked is not None and locked > 0)})
            d["open"] = popper_rows
            out["grids"].append(d)
        return out

    def _save_state(self) -> None:
        try:
            _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            payload = {"grids": [g.to_dict() for g in self.grids.values()],
                       "saved": datetime.now(timezone.utc).isoformat()}
            tmp = _STATE_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, indent=1))
            tmp.replace(_STATE_PATH)
        except OSError as exc:
            log.warning("PP state save failed: %s", exc)

    def _load_state(self) -> None:
        try:
            if not _STATE_PATH.exists():
                return
            payload = json.loads(_STATE_PATH.read_text())
            for gd in payload.get("grids", []):
                g = Grid.from_dict(gd)
                # trade ids in persisted levels are reconciled by recover();
                # anything not re-adopted is cleared so levels can re-arm.
                for lv in g.levels.values():
                    lv["trade_id"] = None
                self.grids[g.pair] = g
            if self.grids:
                log.info("PP state loaded: %d grid(s) [%s]", len(self.grids),
                         ", ".join(self.grids.keys()))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            log.warning("PP state load failed (%s) — starting clean", exc)
