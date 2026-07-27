"""core/exec_truth.py — execution-price truth helpers (D-5, external review).

Two tiny, heavily-tested functions shared by the parent entry path, the popper
fire path, and the manage loop:

  adopt_fill(quoted, trade, direction, pip)
      The broker's orderFillTransaction price is the ONLY true entry. Returns
      (entry_price, slippage_pips) — entry is the broker fill when parseable,
      else the pre-order quote (with slippage None so callers can log the
      degradation loudly). Slippage is signed COST: positive = filled worse
      than quoted (long filled higher / short filled lower).

  executable_price(bid, ask, direction)
      The price a position could actually exit at RIGHT NOW: bid for longs,
      ask for shorts. Management decisions (peak/MFE, ratchet engage, lock,
      trail, net display) must use this, never mid — at an 8.5p trigger the
      half-spread is not bookkeeping.
"""
from __future__ import annotations

from typing import Optional, Tuple


def adopt_fill(quoted: float, trade: dict, direction: str,
               pip: float) -> Tuple[float, Optional[float]]:
    """(entry_price, slippage_pips) from a broker place_market result."""
    raw = (trade or {}).get("price")
    try:
        fill = float(raw)
        if fill <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return float(quoted), None
    sign = 1.0 if direction == "long" else -1.0
    slippage = (fill - float(quoted)) * sign / pip
    return fill, round(slippage, 2)


def executable_price(bid: float, ask: float, direction: str) -> float:
    """The liquidation-side price: longs exit at bid, shorts exit at ask."""
    return bid if direction == "long" else ask
