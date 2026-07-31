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
from modules.playmaker.playmaker import (TradeTicket, pm_margin_pct, pm_probe_mult,
                                          pm_max_concurrent,
                                          _MAX_SPREAD, _DEFAULT_MAX_SPREAD)
from config.runtime import trading_enabled
from core.exec_truth import adopt_fill, executable_price
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


from config.safe_config import PathLKG
_pp_lkg: PathLKG[dict] = PathLKG()   # path-scoped LKG (review round 2)

def pp_config() -> dict:
    """Hot-reloaded pp config (same pattern as exit_config).

    FAIL-CLOSED (2026-07-27, external-review fix): a corrupted pp_config.json
    used to fall back to _DEFAULTS — which has enabled=True and an EMPTY
    per_cell map, i.e. corruption silently re-armed every grid and erased the
    operator's opt-outs (the B-096 accident class). Now: last-known-good if we
    have one, else defaults with the poppers OFF.
    """
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
        return _pp_lkg.remember(_CONFIG_PATH, cfg)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        previous = _pp_lkg.get(_CONFIG_PATH)
        if previous is not None:
            return previous
        log.warning("pp_config.json unreadable (%s) with no last-known-good — "
                    "FAILING CLOSED (poppers disabled)", exc)
        safe = dict(_DEFAULTS)
        safe["enabled"] = False
        return safe


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


def _popper_client_ext(cfg: dict, offset_pips: float, anchor: float,
                       parent_setup: str = "", gid: str = "") -> dict:
    """OANDA tradeClientExtensions for a popper. tag=pp_v1 routes recovery away
    from the parent adopter; comment carries the gear + grid coordinates.
    lvl = the marker OFFSET in pips (ladder era, 2026-07-22).
    psu = the PARENT setup id (family ledger, 2026-07-28): every popper fill
    self-attributes to the family that spawned it — the governor's family
    net-pips demote/defend rule reads it straight off the broker. OANDA caps
    the comment at 128 chars, so psu is truncated defensively."""
    # B-112: live truncates comments to ~32 chars — field ORDER is survival
    # order. anc first (the family anchor-join), then lvl, then psu, then the
    # gear (recoverable from pp_config defaults anyway).
    fields = {"anc": round(anchor, 5), "lvl": float(offset_pips)}
    if parent_setup and parent_setup not in ("?", "recovered"):
        fields["psu"] = parent_setup[:40]
    fields.update({"sl": cfg["sl_pips"], "tr": cfg["trigger_pips"],
                   "tp": cfg["trail_pips"], "su": "pp_v1"})
    tag = f"pp_v1;g={gid}" if gid else "pp_v1"
    return {"tag": tag,
            "comment": json.dumps(fields, separators=(",", ":"))}


def _cell_status(cell_key: str) -> Optional[str]:
    """Current status for an exact ``PAIR|session|setup`` grid owner.

    ``None`` is deliberately distinct from ACTIVE: callers reconciling legacy
    state must fail toward reduced risk when the book cannot be read.
    """
    try:
        pair, sess, sid = (cell_key.split("|") + ["", ""])[:3]
        cfg_path = _STATE_PATH.parent.parent / "config" / "cells" / f"{pair}.json"
        d = json.loads(cfg_path.read_text())
        for su in d.get("sessions", {}).get(sess, {}).get("setups", []):
            if su.get("id") == sid:
                return str(su.get("status") or "?")
    except Exception:
        pass
    return None


class Grid:
    """One re-arming grid per pair, anchored at the parent entry price."""

    def __init__(self, pair: str, side: str, anchor: float, created: datetime,
                 parent_setup: str = "?", cell_key: str = "", gid: str = "",
                 probe: bool = False, quiesced: bool = False):
        self.pair = pair
        self.side = side                    # popper direction == parent direction
        self.anchor = anchor
        self.created = created
        self.parent_setup = parent_setup
        self.cell_key = cell_key            # "PAIR|session|setup" for the per-cell switch
        # grid_id (2026-07-31, family-cycle program): the CREATING parent's
        # OANDA trade id. Every popper carries it in the TAG ("pp_v1;g=<id>"),
        # which the transaction stream preserves pristine even on live
        # accounts — attribution becomes an exact join to the originating
        # family, no anchor heuristics. Empty for pre-gid grids (state
        # migration) — those poppers fall back to psu/anchor join.
        self.gid = str(gid or "")
        # PROBE grids (external review 2026-07-31): a 0.33x audition must be
        # a 0.33x FAMILY — every popper this grid fires inherits the reduced
        # sizing, or "5% probe" quietly becomes 5% parent + 15% poppers.
        self.probe = bool(probe)
        # Governance transitions persistently quiesce a grid before changing
        # the seat era. Existing legs keep being managed; no new popper may
        # fire. This is independent of the hot-reloaded per-cell switch so a
        # restart or ambiguous legacy owner cannot reopen the race.
        self.quiesced = bool(quiesced)
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
                "cell_key": self.cell_key, "gid": self.gid,
                "probe": self.probe, "quiesced": self.quiesced,
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
                d.get("cell_key", ""), d.get("gid", ""),
                bool(d.get("probe", False)), bool(d.get("quiesced", False)))
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

    def on_parent_open(self, pos: Position, setup_id: str = "?",
                       probe: bool = False) -> None:
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
            g = self.grids[pair]
            requested_key = f"{pair}|{session}|{setup_id}"
            if g.quiesced:
                log.warning("PP GRID is governance-quiesced %s (%s) — parent "
                            "cannot re-arm it | engine=pp_v1", pair, g.cell_key)
                return
            if g.cell_key and g.cell_key != requested_key:
                log.error("PP GRID OWNER MISMATCH %s existing=%s requested=%s — "
                          "parent will not inherit another family's grid | engine=pp_v1",
                          pair, g.cell_key, requested_key)
                return
            # Never let a PROBE parent inherit a persisted full-size grid.  The
            # reverse transition remains reduced until the flat grid is retired
            # and a fresh ACTIVE parent creates a new one.
            if probe and not g.probe:
                g.probe = True
                self._save_state()
                log.warning("PP GRID forced to PROBE sizing %s (%s) — existing "
                            "grid retained conservatively | engine=pp_v1",
                            pair, requested_key)
            log.info("PP GRID exists for %s — parent joins existing grid | engine=pp_v1", pair)
            return
        g = Grid(pair, pos.ticket.direction, pos.entry_price,
                 pos.entry_time if pos.entry_time.tzinfo else
                 pos.entry_time.replace(tzinfo=timezone.utc), setup_id,
                 cell_key=f"{pair}|{session}|{setup_id}",
                 gid=str(getattr(pos, "oanda_trade_id", "") or ""),
                 probe=probe)
        for off in cfg["marker_pips"]:
            g.levels[_okey(off)] = {"armed": True, "trade_id": None}
        self.grids[pair] = g
        log.info("PP GRID armed %s %s anchor=%.5f markers=%s | engine=pp_v1 setup=%s",
                 pair, g.side, g.anchor,
                 "/".join("-" + _okey(o) for o in cfg["marker_pips"]), setup_id)
        self._save_state()

    def retire_cell_grid(self, cell_key: str,
                         parent_pairs: Optional[set] = None) -> dict:
        """Retire a flat grid before a governance/policy era transition.

        A grid owns its anchor, creator gid, policy and sizing for its entire
        lifetime.  Reusing it after DEMOTE/PROMOTE/GRADUATE crosses evidence
        eras and can turn a reduced PROBE into full-size poppers.  Retirement
        therefore fails closed while any parent or popper is open and requires
        an exact owner match.
        """
        parts = str(cell_key or "").split("|")
        if len(parts) != 3 or any(not p for p in parts):
            return {"ok": False, "error": f"bad exact cell key: {cell_key!r}"}
        pair = parts[0]
        g = self.grids.get(pair)
        if g is None:
            return {"ok": True, "retired": False, "reason": "no-grid"}
        parents = parent_pairs or set()
        open_poppers = [tid for tid, (p, _) in self._popper_grid.items()
                        if p == pair and tid in self.poppers]
        level_busy = [str(lv.get("trade_id")) for lv in g.levels.values()
                      if lv.get("trade_id")]
        is_busy = pair in parents or bool(open_poppers) or bool(level_busy)
        if g.cell_key != cell_key:
            if g.cell_key:
                # One grid per pair: another exact family owns this one. It is
                # not stale state for the requested cell and must not be killed.
                return {"ok": True, "retired": False,
                        "reason": "other-cell-grid", "grid_cell": g.cell_key,
                        "requested_cell": cell_key}
            # Recovered legacy state without an exact owner is ambiguous. Stop
            # new fires and require open risk to flatten; never guess a session
            # from setup text. Once flat, removing an inert ambiguous grid is
            # safe and unblocks exact ownership for the next parent.
            if is_busy:
                g.quiesced = True
                self._save_state()
                return {"ok": False, "error": "grid-owner-unknown-quiesced",
                        "requested_cell": cell_key, "quiesced": True}
            del self.grids[pair]
            self._save_state()
            return {"ok": True, "retired": True,
                    "reason": "legacy-owner-unknown-flat", "cell": cell_key,
                    "old_gid": g.gid, "old_anchor": g.anchor,
                    "old_probe": g.probe}
        if is_busy:
            g.quiesced = True
            self._save_state()
            return {"ok": False, "error": "grid-not-flat",
                    "parent_open": pair in parents,
                    "open_poppers": sorted(set(open_poppers + level_busy)),
                    "quiesced": True}
        del self.grids[pair]
        self._save_state()
        log.info("PP GRID retired for governance transition %s anchor=%.5f gid=%s "
                 "| engine=pp_v1", cell_key, g.anchor, g.gid or "-")
        return {"ok": True, "retired": True, "cell": cell_key,
                "old_gid": g.gid, "old_anchor": g.anchor,
                "old_probe": g.probe}

    def recover(self, trade: dict) -> None:
        """Adopt an open OANDA popper trade (tag pp_v1[;g=<id>]) at startup.
        IDEMPOTENT (reconciler era, 2026-07-31): an already-tracked popper is
        a no-op, so the self-healing loop can re-run recovery wholesale."""
        if str(trade.get("id") or "") in self.poppers:
            return
        pair = trade["instrument"]
        _tag = (trade.get("clientExtensions") or {}).get("tag", "") or ""
        _gid = _tag.split(";g=", 1)[1] if ";g=" in _tag else ""
        if pair not in PIP:
            return
        _cm = (trade.get("clientExtensions") or {}).get("comment", "{}") or "{}"
        try:
            d = json.loads(_cm)
        except (ValueError, json.JSONDecodeError):
            # B-112 lenient fallback: live truncates comments — regex-extract
            # whatever survived (anc/lvl lead the field order for exactly this).
            import re as _re
            d = {}
            for k in ("anc", "lvl", "sl", "tr", "tp"):
                m = _re.search(r'"%s":([0-9.]+)' % k, _cm)
                if m:
                    d[k] = float(m.group(1))
            m = _re.search(r'"psu":"([^"]*)"?', _cm)
            if m:
                d["psu"] = m.group(1)
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
            g = Grid(pair, direction, anchor, entry_time,
                     d.get("psu") or "recovered")
            for off in cfg["marker_pips"]:
                g.levels[_okey(off)] = {"armed": False, "trade_id": None}
            if _gid:
                g.gid = _gid
            # A popper can reconstruct pair/anchor/setup but not the parent's
            # exact session. Manage the recovered leg, but never manufacture
            # new risk from an ambiguously-owned grid.
            g.quiesced = True
            self.grids[pair] = g
            log.warning("PP GRID rebuilt QUIESCED from popper recovery %s "
                        "anchor=%.5f gid=%s | engine=pp_v1",
                        pair, anchor, g.gid or "-")
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
                    # D-5: net measured at the EXECUTABLE side (long exits at
                    # bid, short at ask) — mid flattered every popper by half
                    # the spread.
                    px = executable_price(bid, ask, mgr.position.ticket.direction)
                except Exception:
                    px = mgr.position.entry_price
                net = mgr.net_pips(px)
                self._book_exit(pair, lvl, tid, net, "server-stop", now)

        # 2) popper ratchet tick + local exit detect
        for tid in list(self.poppers.keys()):
            mgr = self.poppers[tid]
            pair, lvl = self._popper_grid.get(tid, (mgr.position.ticket.pair, 0))
            try:
                bid, ask = pricing(pair)
                # D-5: the ratchet keys off the price this popper could
                # actually exit at — never mid.
                px = executable_price(bid, ask, mgr.position.ticket.direction)
            except Exception as exc:
                log.warning("PP pricing %s failed: %s", pair, exc)
                continue
            signal = mgr.update(px, now)
            if signal:
                try:
                    self.broker.close_position(tid)
                except Exception as exc:
                    log.warning("PP close_position %s: %s (OANDA may have beaten us)",
                                tid, exc)
                self._book_exit(pair, lvl, tid, signal.net_pips, signal.reason, now)

        # 3) re-arm + fire per grid
        # NOTE (D-5): marker CROSSING below stays mid-based on purpose — a
        # marker is a level definition (like the mid-based view features that
        # define entries), not a liquidation decision. The fill itself is
        # truth-adopted in _fire; management above uses executable prices.
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

            # prune inert slots that left the config ladder (no open popper)
            _cfg_keys = {_okey(o) for o in cfg["marker_pips"]}
            for _k in [k for k in g.levels
                       if k not in _cfg_keys and not g.levels[k]["trade_id"]]:
                del g.levels[_k]

            _now_ts = now.timestamp()
            if getattr(g, "suspended_until", 0) > _now_ts:
                continue   # grid fires suspended after repeated broker rejections

            for off in cfg["marker_pips"]:
                key = _okey(off)
                price = g.level_price(off)
                lv = g.levels.get(key)
                if lv is not None and lv.get("cooldown_until", 0) > _now_ts:
                    continue   # marker cooling down after a rejected fire
                if lv is None:
                    # NEW marker on a live grid: arm only if price is still on
                    # the favorable side — never insta-fire at a worse price
                    # than the marker itself (B-096: ladder deploy fired a
                    # "-10" popper 85p below its level on an underwater grid).
                    _crossed = mid <= price if g.side == "long" else mid >= price
                    lv = g.levels[key] = {"armed": not _crossed, "trade_id": None}
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
                if g.quiesced:
                    continue     # manage existing legs; governance forbids fires
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
        # Review round 2: quarantined order intents halt ALL new entries,
        # popper fires included — management of existing trades continues.
        if getattr(self.broker, "quarantined", None):
            log.warning("PP FIRE BLOCKED %s marker=-%sp — order quarantine active",
                        pair, key)
            return
        entry_price = ask if g.side == "long" else bid
        try:
            _mp = pm_margin_pct()
            if g.probe:
                _mp *= pm_probe_mult()   # PROBE family: poppers audition too
            units = self.broker.size_units(pair, g.side, margin_pct=_mp)
            trade = self.broker.place_market(
                pair, g.side, units=units, entry_price=entry_price,
                sl_pips=float(cfg["sl_pips"]),
                client_ext=_popper_client_ext(cfg, offset_pips, g.anchor,
                                              g.parent_setup, gid=g.gid),
            )
        except Exception as exc:
            log.warning("PP FIRE failed %s marker=-%sp: %s", pair, key, exc)
            self._fire_rejected(g, key, now, str(exc))
            return
        trade_id = str(trade.get("id") or "")
        if not trade_id:
            # Order placed but NOT filled — on US LIVE accounts this is almost
            # always the FIFO safeguard rejecting the ATTACHED stop while older
            # same-instrument trades are open (B-097; far stricter live than
            # practice, and it was thinning the grids to ~half density).
            # TWO-STEP DODGE (Brock, 2026-07-30): retry ONCE as a naked market
            # order, then attach the stop immediately after the fill. If the
            # stop cannot be attached, the position is closed on the spot —
            # a popper is NEVER left naked.
            log.warning("PP FIRE no-fill %s marker=-%sp (FIFO safeguard?) — "
                        "retrying two-step | engine=pp_v1", pair, key)
            try:
                trade = self.broker.place_market(
                    pair, g.side, units=units, entry_price=entry_price,
                    sl_pips=0.0,
                    client_ext=_popper_client_ext(cfg, offset_pips, g.anchor,
                                                  g.parent_setup, gid=g.gid),
                )
            except Exception as exc:
                log.warning("PP FIRE two-step failed %s marker=-%sp: %s",
                            pair, key, exc)
                self._fire_rejected(g, key, now, str(exc))
                return
            trade_id = str(trade.get("id") or "")
            if not trade_id:
                log.warning("PP FIRE rejected (no fill, both attempts) %s "
                            "marker=-%sp | engine=pp_v1", pair, key)
                self._fire_rejected(g, key, now, "no-fill")
                return
            pip = PIP[pair]
            fill_px = float(trade.get("price") or entry_price)
            sl_px = (fill_px - cfg["sl_pips"] * pip if g.side == "long"
                     else fill_px + cfg["sl_pips"] * pip)
            try:
                self.broker.move_stop(trade_id, sl_px, pair)
                log.info("PP FIRE two-step OK %s marker=-%sp trade_id=%s — "
                         "SL attached post-fill @ %.5f | engine=pp_v1",
                         pair, key, trade_id, sl_px)
            except Exception as exc:
                log.error("PP FIRE two-step SL ATTACH FAILED %s trade_id=%s "
                          "(%s) — closing immediately, never naked | engine=pp_v1",
                          pair, trade_id, exc)
                try:
                    self.broker.close_position(trade_id)
                except Exception as exc2:
                    log.critical("PP two-step emergency close FAILED %s "
                                 "trade_id=%s: %s — MANUAL ACTION NEEDED",
                                 pair, trade_id, exc2)
                self._fire_rejected(g, key, now, "sl-attach-failed")
                return
        pip = PIP[pair]
        # D-5 (external review): adopt the broker fill as the popper's true
        # entry — SL reference and ratchet baseline follow it (the server-side
        # SL is already fill-anchored via place_market's distance form).
        quoted = entry_price
        entry_price, slippage = adopt_fill(quoted, trade, g.side, pip)
        if slippage is None:
            log.warning("PP FILL price missing %s trade_id=%s — using pre-order "
                        "quote %.5f (entry truth degraded)", pair, trade_id, quoted)
        else:
            log.info("PP FILL %s %s quoted=%.5f filled=%.5f slippage=%+.2fp | engine=pp_v1",
                     pair, g.side, quoted, entry_price, slippage)
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
        g.fire_fails = 0                      # a real fill resets the rejection streak
        log.info("POPPER FIRE %s %s marker=-%sp @ %.5f | %d units | SL -%.1fp ratchet %.1f/%.1f "
                 "| trade_id=%s | engine=pp_v1 anchor=%.5f",
                 pair, g.side, key, entry_price, units, cfg["sl_pips"],
                 cfg["trigger_pips"], cfg["trail_pips"], trade_id, g.anchor)
        self._save_state()

    _FIRE_COOLDOWN_S = 1800      # 30 min per-marker cooldown after a rejected fire
    _GRID_SUSPEND_S  = 7200      # 2 h grid-wide fire suspension after 3 straight rejections

    def _fire_rejected(self, g: Grid, key: str, now: datetime, why: str) -> None:
        """A fire attempt produced no fill: cool the marker down and, on repeated
        rejections, suspend the whole grid's fires — never retry-storm (B-097)."""
        ts = now.timestamp()
        lv = g.levels.get(key) or {}
        lv.update({"armed": False, "trade_id": None, "cooldown_until": ts + self._FIRE_COOLDOWN_S})
        g.levels[key] = lv
        g.fire_fails = getattr(g, "fire_fails", 0) + 1
        if g.fire_fails >= 3:
            g.suspended_until = ts + self._GRID_SUSPEND_S
            log.warning("PP GRID %s fires SUSPENDED %dmin after %d straight rejections (%s) "
                        "| engine=pp_v1", g.pair, self._GRID_SUSPEND_S // 60, g.fire_fails, why)
            g.fire_fails = 0

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
                # Reconcile against the CURRENT seat on every load, not only
                # when the field is missing.  ACTIVE->SHADOW->PROBE can leave
                # an explicit probe:false grid behind; that is the dangerous
                # state.  Unknown legacy ownership fails toward reduced size.
                status = _cell_status(g.cell_key)
                if status == "PROBE" and not g.probe:
                    g.probe = True
                    log.warning("PP GRID reconciled to PROBE sizing %s (%s) "
                                "persisted_probe=%s | engine=pp_v1",
                                g.pair, g.cell_key, gd.get("probe"))
                elif "probe" not in gd and status is None:
                    g.probe = True
                    log.warning("PP GRID owner status unavailable %s (%s) — "
                                "legacy state forced to reduced sizing | engine=pp_v1",
                                g.pair, g.cell_key)
                if status not in ("ACTIVE", "PROBE"):
                    g.quiesced = True
                    log.warning("PP GRID owner is not a live seat %s (%s, status=%s) "
                                "— fires quiesced | engine=pp_v1",
                                g.pair, g.cell_key, status)
                self.grids[g.pair] = g
            if self.grids:
                log.info("PP state loaded: %d grid(s) [%s]", len(self.grids),
                         ", ".join(self.grids.keys()))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            log.warning("PP state load failed (%s) — starting clean", exc)
