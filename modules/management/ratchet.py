"""modules/management/ratchet.py — Step-trail ratchet exit manager for V5.

ALL live knob values come from config/exit_config.json (hot-reloaded on every
cadence check via _load_config()).  Defaults in _DEFAULTS are the ultimate
fallback used only when the JSON is missing or corrupt.

Live values as of 2026-07-03 (from config/exit_config.json "defaults"):
  initial_sl_pips  = 20.0   — hard server-side SL placed at entry (pips from entry)
  step_engage_min  =  0.0   — minutes after entry before first cadence check (0 = immediate)
  step_cadence_min =  0.5   — minutes between SL evaluation checks (~every 30s)
  step_trigger_pips=  7.5   — peak MFE required before first SL movement
  step_trail_pips  =  2.5   — SL parks this many pips behind the step level
  step_size_pips   =  2.5   — ratchet step size (new SL level every N pips above trigger)

Per-pair overrides in exit_config.json "per_pair" are merged on top of defaults.

How stops work:
  1. Entry: broker places hard SL at initial_sl_pips server-side (OANDA order)
  2. Every step_cadence_min: if peak ≥ step_trigger_pips, compute step level and lock SL
  3. SL only ever moves in the profitable direction (never backwards)
  4. OANDA executes the stop server-side — engine polls open_positions() for exits
  5. Belt-and-suspenders: update() also returns ExitSignal if price crosses locked SL
"""
from __future__ import annotations
import json
import logging
import math
from datetime import datetime
from pathlib import Path
from typing import Optional

from .base import Position, ExitSignal, TradeManager, in_rollover_freeze

log = logging.getLogger("v5.ratchet")

# Pre-rollover stop guard (2026-07-08): at 21:00 UTC half-spreads run 4-10x and
# a resting server-side stop within blowout range is triggered by the widening
# itself (live specimen 2026-07-08: -12.4p fill carrying ~5.6p half-spread at
# 21:18Z). Between 20:45-20:55, while pricing is still clean, positions whose
# stop sits within this many pips of price are flattened at market; deeper
# stops ride the window untouched.
_ROLLOVER_GUARD_PIPS = 10.0

# Defaults — match exit_config.json; used when JSON is missing or corrupt
_DEFAULTS: dict = {
    "initial_sl_pips":   12.0,   # initial server-side stop loss (pips from entry, abs)
    "step_engage_min":   0.0,    # minutes before first cadence check (0 = immediate)
    "step_cadence_min":  20.0,   # minutes between SL evaluation checks
    "step_size_pips":    5.0,    # ratchet step size (SL level every N pips above trigger)
    "step_trigger_pips": 10.0,   # peak MFE required before first SL movement
    "step_trail_pips":   6.0,    # SL parks this many pips behind the step level
}

_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "exit_config.json"


def _coerce(k: str, v):
    if isinstance(v, bool):
        return v
    return float(v)

def _load_config(pair: Optional[str] = None) -> dict:
    """Return effective exit knobs. Supports both schemas:
       v2 nested: {"defaults": {...}, "per_pair": {"EUR_USD": {...}}}
       v1 flat:   {"step_trigger_pips": ..., ...}        (legacy fallback)
    With pair given, per-pair overrides are merged on top of defaults."""
    try:
        raw = json.loads(_CONFIG_PATH.read_text())
        if isinstance(raw.get("defaults"), dict):
            defaults = {k: _coerce(k, v) for k, v in raw["defaults"].items() if not k.startswith("_")}
            cfg = {**_DEFAULTS, **defaults}
            if pair:
                override = raw.get("per_pair", {}).get(pair) or {}
                cfg.update({k: _coerce(k, v) for k, v in override.items() if not k.startswith("_")})
            return cfg
        # legacy flat schema
        return {**_DEFAULTS, **{k: _coerce(k, v) for k, v in raw.items() if not k.startswith("_")}}
    except Exception:
        return _DEFAULTS.copy()


def initial_sl_pips_for(pair: str) -> float:
    """Public helper for the engine — initial server-side SL for a fresh trade."""
    return _load_config(pair)["initial_sl_pips"]


class RatchetManager(TradeManager):
    """One instance per open trade. Calls broker.move_stop() when step level advances.

    In dry_run mode: full logic runs for logging, API call is skipped.
    """

    def __init__(self, position: Position, broker=None, dry_run: bool = False,
                 initial_units: Optional[int] = None, **_legacy_kwargs):
        self.position       = position
        self.broker         = broker
        self.dry_run        = dry_run
        self.pip            = position.pip_size
        self.direction      = position.ticket.direction   # "long" | "short"
        # Original units at fill — needed so partial closes are a percentage of
        # the INITIAL position (not the post-TP1 remainder).
        self.initial_units  = int(initial_units if initial_units is not None else position.units)

        # Peak tracks best price seen; initialise to entry
        self.peak_price     = position.entry_price

        # sl_locked_pips: current locked SL expressed as pips from entry in the
        # profit direction (positive = in profit, negative = still below entry).
        # Initialised from the OANDA server SL so we never move it backwards.
        if position.initial_sl_price != 0.0:
            self.sl_locked_pips: Optional[float] = self._price_to_sl_pips(position.initial_sl_price)
        else:
            self.sl_locked_pips = None

        self.last_check_time = position.entry_time

    # ── Public interface ─────────────────────────────────────────────────────

    def name(self) -> str:
        return "ratchet"

    def net_pips(self, current_price: float) -> float:
        """Unrealised P&L in pips at the given price."""
        if self.direction == "long":
            return (current_price - self.position.entry_price) / self.pip
        return (self.position.entry_price - current_price) / self.pip

    def update(self, current_price: float, current_time: datetime) -> Optional[ExitSignal]:
        """Called each engine cycle (every 5 min).

        1. Updates peak.
        2. On cadence: reads config, computes new SL level, calls broker.move_stop
           if the level improves.
        3. Belt-and-suspenders: returns ExitSignal if price crosses the locked SL
           (OANDA server-side stop is the primary exit mechanism).
        """
        self._update_peak(current_price)

        # Pre-rollover stop guard: flatten cleanly at 20:45-20:55 if the stop
        # is close enough for the 21:00 spread blowout to trigger it.
        hm = current_time.hour * 60 + current_time.minute
        if (20 * 60 + 45) <= hm < (20 * 60 + 55) and self.sl_locked_pips is not None:
            sl_price = self._sl_pips_to_price(self.sl_locked_pips)
            if abs(current_price - sl_price) / self.pip <= _ROLLOVER_GUARD_PIPS:
                return self._make_exit(current_price, current_time, "rollover_guard_flat")

        # Rollover freeze: no stop-tightening, no bot-side closes 20:55-22:05 UTC.
        if in_rollover_freeze(current_time):
            return None

        cfg             = _load_config(self.position.ticket.pair)
        # Per-trade exit params (Phase C prepared, activated at Phase D cutover).
        # When position.exit_params is set, override the three ratchet knobs.
        # When absent, behaviour is byte-identical to the current exit_config path.
        _ep = getattr(self.position, 'exit_params', None)
        if _ep is not None:
            cfg = dict(cfg)  # shallow copy — don't mutate the shared dict
            cfg['initial_sl_pips']   = float(_ep.sl_pips)
            cfg['step_trigger_pips'] = float(_ep.trigger_pips)
            cfg['step_trail_pips']   = float(_ep.trail_pips)
            cfg['step_engage_pips'] = float(getattr(_ep, 'engage_pips', 0.0) or 0.0)
            cfg['step_engage_lock_pips'] = float(getattr(_ep, 'engage_lock_pips', 0.0) or 0.0)

        elapsed_total   = (current_time - self.position.entry_time).total_seconds() / 60
        elapsed_check   = (current_time - self.last_check_time).total_seconds() / 60
        engage_ok       = elapsed_total >= cfg["step_engage_min"]
        cadence_ok      = elapsed_check >= cfg["step_cadence_min"]

        if engage_ok and cadence_ok:
            self.last_check_time = current_time
            self._evaluate_and_lock(cfg, current_time)

        # Local belt-and-suspenders stop detection
        return self._check_stop_hit(current_price, current_time)

    # ── Core step logic ───────────────────────────────────────────────────────

    def _evaluate_and_lock(self, cfg: dict, ts: datetime) -> None:
        peak_pips = self._peak_pips()
        new_sl    = self._compute_step_sl(peak_pips, cfg)

        if new_sl is None:
            return   # peak hasn't reached trigger yet

        # Only tighten — never move SL backwards
        if self.sl_locked_pips is not None and new_sl <= self.sl_locked_pips:
            return

        self.sl_locked_pips = new_sl
        self._push_stop(new_sl, peak_pips, ts)

    @staticmethod
    def _compute_step_sl(peak_pips: float, cfg: dict) -> Optional[float]:
        """Return new SL in profit-direction pips from entry, or None if trigger not reached."""
        trigger = cfg["step_trigger_pips"]
        step    = cfg["step_size_pips"]
        trail   = cfg["step_trail_pips"]
        # Two-phase (v6.30.0): optional early engage lock ahead of the step
        # machine. MUST stay formula-identical to core.shadow_execution
        # ._ratchet_lock — the scorer replays exactly this.
        engage      = float(cfg.get("step_engage_pips", 0.0) or 0.0)
        engage_lock = float(cfg.get("step_engage_lock_pips", 0.0) or 0.0)

        best = None
        if engage > 0 and engage_lock > 0 and peak_pips >= engage:
            best = engage_lock
        if peak_pips >= trigger:
            level = math.floor((peak_pips - trigger) / step) * step + trigger
            cand = level - trail
            if best is None or cand > best:
                best = cand
        return best

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _update_peak(self, price: float) -> None:
        if self.direction == "long":
            if price > self.peak_price:
                self.peak_price = price
        else:
            if price < self.peak_price:
                self.peak_price = price

    def _peak_pips(self) -> float:
        """MFE in pips (always positive = favorable)."""
        if self.direction == "long":
            return round((self.peak_price - self.position.entry_price) / self.pip, 4)
        return round((self.position.entry_price - self.peak_price) / self.pip, 4)

    def _sl_pips_to_price(self, sl_pips: float) -> float:
        """Convert SL expressed as profit-direction pips from entry → absolute price."""
        if self.direction == "long":
            return self.position.entry_price + sl_pips * self.pip
        return self.position.entry_price - sl_pips * self.pip

    def _price_to_sl_pips(self, price: float) -> float:
        """Inverse: absolute price → profit-direction pips from entry."""
        if self.direction == "long":
            return round((price - self.position.entry_price) / self.pip, 4)
        return round((self.position.entry_price - price) / self.pip, 4)

    def _check_stop_hit(self, price: float, ts: datetime) -> Optional[ExitSignal]:
        if self.sl_locked_pips is None:
            return None
        sl_price = self._sl_pips_to_price(self.sl_locked_pips)
        if self.direction == "long" and price <= sl_price:
            return self._make_exit(sl_price, ts, "ratchet_stop")
        if self.direction == "short" and price >= sl_price:
            return self._make_exit(sl_price, ts, "ratchet_stop")
        return None

    def _push_stop(self, sl_pips: float, peak_pips: float, ts: datetime) -> None:
        pair     = self.position.ticket.pair
        sl_price = self._sl_pips_to_price(sl_pips)
        log.info("RATCHET %s | peak=%.1fp sl=%.1fp → %.5f | trade_id=%s",
                 pair, peak_pips, sl_pips, sl_price, self.position.oanda_trade_id)

        if self.dry_run or self.broker is None:
            return
        try:
            self.broker.move_stop(self.position.oanda_trade_id, sl_price, pair)
        except Exception as exc:
            log.error("move_stop failed %s: %s", pair, exc)

    def _make_exit(self, price: float, ts: datetime, reason: str) -> ExitSignal:
        return ExitSignal(
            position=self.position,
            exit_price=price,
            exit_time=ts,
            reason=reason,
            net_pips=round(self.net_pips(price), 2),
        )
