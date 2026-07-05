"""modules/management/bracket.py — fixed-bracket exit manager (FAST slice class).

Cost-aware slicer exits (2026-07-05, Brock live order):
  * TP = server-side limit placed on fill (takeProfitOnFill) — cannot slip.
  * SL = server-side stop placed on fill (standard V5 path).
  * timeout_min: if neither side hit, flat at market.
  * Rollover: force-flat 20:45–20:55 UTC; inside the 20:55–22:05 blowout window
    NO bot-initiated closes (server orders stay armed).
No trailing — trailing stops are what produced +5-lock→wash fills at rollover.
Lineage: research/sessions/2026-07-04_cell_transaction_costs (spread/slippage/
conversion math) + 2026-07-05_ratchet_profiles (class map, fill probabilities).
"""
from __future__ import annotations
import logging
from datetime import datetime
from typing import Optional

from .base import Position, ExitSignal, TradeManager, in_rollover_freeze

log = logging.getLogger("v5.bracket")

_FLAT_START = 20 * 60 + 45   # 20:45 UTC — brackets go flat before rollover
_FLAT_END   = 20 * 60 + 55   # 20:55 UTC — after this the freeze owns the window


class BracketManager(TradeManager):
    """One instance per open FAST-class trade. TP/SL live server-side; this
    manager only enforces the timeout and the pre-rollover flat."""

    def __init__(self, position: Position, broker=None, dry_run: bool = False,
                 initial_units: Optional[int] = None, **_ignored):
        self.position   = position
        self.broker     = broker
        self.dry_run    = dry_run
        self.pip        = position.pip_size
        self.direction  = position.ticket.direction
        self.peak_price = position.entry_price
        ep = getattr(position, "exit_params", None)
        self.timeout_min = float(getattr(ep, "timeout_min", 0.0) or 0.0)
        self.tp_pips     = float(getattr(ep, "tp_pips", 0.0) or 0.0)
        # Static SL expressed in profit-direction pips (negative = below entry);
        # dashboard-compatible with RatchetManager.sl_locked_pips.
        if position.initial_sl_price != 0.0:
            self.sl_locked_pips: Optional[float] = self._price_to_sl_pips(position.initial_sl_price)
        else:
            self.sl_locked_pips = None

    def name(self) -> str:
        return "bracket"

    def net_pips(self, current_price: float) -> float:
        if self.direction == "long":
            return (current_price - self.position.entry_price) / self.pip
        return (self.position.entry_price - current_price) / self.pip

    def update(self, current_price: float, current_time: datetime) -> Optional[ExitSignal]:
        self._update_peak(current_price)

        # Never fire a bot-side close into the rollover spread blowout.
        if in_rollover_freeze(current_time):
            return None

        hm = current_time.hour * 60 + current_time.minute
        if _FLAT_START <= hm < _FLAT_END:
            return self._make_exit(current_price, current_time, "rollover_flat")

        if self.timeout_min > 0:
            elapsed = (current_time - self.position.entry_time).total_seconds() / 60
            if elapsed >= self.timeout_min:
                return self._make_exit(current_price, current_time, "bracket_timeout")
        return None

    # ── helpers (RatchetManager-compatible surface for dashboard) ────────────

    def _update_peak(self, price: float) -> None:
        if self.direction == "long":
            if price > self.peak_price: self.peak_price = price
        elif price < self.peak_price:
            self.peak_price = price

    def _peak_pips(self) -> float:
        if self.direction == "long":
            return round((self.peak_price - self.position.entry_price) / self.pip, 4)
        return round((self.position.entry_price - self.peak_price) / self.pip, 4)

    def _sl_pips_to_price(self, sl_pips: float) -> float:
        if self.direction == "long":
            return self.position.entry_price + sl_pips * self.pip
        return self.position.entry_price - sl_pips * self.pip

    def _price_to_sl_pips(self, price: float) -> float:
        if self.direction == "long":
            return round((price - self.position.entry_price) / self.pip, 4)
        return round((self.position.entry_price - price) / self.pip, 4)

    def _make_exit(self, price: float, ts: datetime, reason: str) -> ExitSignal:
        return ExitSignal(position=self.position, exit_price=price, exit_time=ts,
                          reason=reason, net_pips=round(self.net_pips(price), 2))
