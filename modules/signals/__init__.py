"""modules/signals — shared market-data structures + retained instruments.

CELL ERA (Phase D cutover 2026-07-04): the direction_v2/momentum_v3 strategy
stack is RETIRED — archived importable at the V5 repo modules/archive/signals_legacy/ + Dropbox graveyard
(rollback tag pre-cell-cutover-2026-07-04). What remains here:

  base.py           MarketView / PairTicket dataclasses (feed + tooling)
  calibration.py    per-cell calibration artifact reader (dashboard/evidence)
  formula_shadow.py FORMULA stamp instrument (view-based, engine-independent)
"""
from __future__ import annotations
from .base import MarketView, PairTicket

__all__ = [
    "MarketView",
    "PairTicket",
]
