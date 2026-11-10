from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo
from ..playmaker.playmaker import TradeTicket


@dataclass
class Position:
    ticket:         TradeTicket
    entry_price:    float
    entry_time:     datetime
    units:          int
    oanda_trade_id: str
    pip_size:       float
    initial_sl_price: float = 0.0  # OANDA SL at open; ratchet inits from this
    # Per-trade exit params from cell setup (Phase C: prepared, unused until cutover)
    # When present, RatchetManager reads these instead of exit_config.json.
    # When absent (None), current exit_config behaviour is byte-identical.
    exit_params: Optional[object] = None  # ExitParams from modules.cells (avoid circular import)


@dataclass
class ExitSignal:
    position:   Position
    exit_price: float
    exit_time:  datetime
    reason:     str    # "ratchet_stop" | "time_exit" | "manual"
    net_pips:   float


_NY = ZoneInfo("America/New_York")


def _ny_minutes(ts) -> int:
    """Minutes since local midnight in New York for ts (a naive ts is treated as UTC).
    OANDA's daily rollover follows New York 17:00, so the spread blowout sits at
    21:00 UTC in summer (EDT) and 22:00 UTC in winter (EST)."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    t = ts.astimezone(_NY)
    return t.hour * 60 + t.minute


def in_rollover_freeze(ts) -> bool:
    """True from 16:55 to 18:05 New York time: 20:55-22:05 UTC in summer (EDT),
    21:55-23:05 UTC in winter (EST) - the daily rollover spread blowout.
    Measured 2026-07-04 (research/sessions/2026-07-04_cell_transaction_costs):
    half-spreads 4-10x normal, stop-fill slippage med 0.8p / p90 8.8p at rollover.
    M1 bid/ask check 2026-11-08: blowout moved 21:00 -> 22:00 UTC on 2026-11-01.
    No manager may tighten a stop or fire a bot-initiated close inside it."""
    m = _ny_minutes(ts)
    return (16 * 60 + 55) <= m < (18 * 60 + 5)


def in_rollover_guard_window(ts) -> bool:
    """True from 16:45 to 16:55 New York time: the pre-rollover flat window
    (20:45-20:55 UTC in summer, 21:45-21:55 UTC in winter)."""
    m = _ny_minutes(ts)
    return (16 * 60 + 45) <= m < (16 * 60 + 55)


class TradeManager(ABC):
    """Abstract base -- one instance per open position."""

    @abstractmethod
    def update(self, current_price: float, current_time: datetime) -> Optional[ExitSignal]:
        """Called on each M5 bar. Returns ExitSignal when position should close."""
        ...

    @abstractmethod
    def name(self) -> str:
        ...
