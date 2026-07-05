"""modules/cells — V5 cellular architecture (Phase C, shadow-only).

Public API
----------
  CellModule     — per (pair × session); evaluate() returns CellIntent | None
  CellIntent     — dataclass; returned when a setup fully qualifies
  ExitParams     — dataclass; per-setup exit geometry (sl / trigger / trail)
  PairModule     — holds CellModules for one pair; session gate from config

Phase-C mode
------------
  CELL_EXECUTION_ENABLED = False

  While this flag is False, *all* setups behave as shadow regardless of their
  config status — they evaluate, stamp a CELLSHADOW log line, and return None.
  The flag is the sole gate; flip it at Phase-D cutover (one-line change here
  + engine wiring of the returned intent).

Kill-switch
-----------
  defaults.cell_shadow_enabled in playmaker_config.json (hot-reload via the
  pm_cell_shadow_enabled() accessor in modules/playmaker/playmaker.py).
  When False, cell evaluation is skipped entirely (no stamps, no cost).
"""
from .cell import CellModule, CellIntent, ExitParams
from .pair_module import PairModule

__all__ = ["CellModule", "CellIntent", "ExitParams", "PairModule"]

# ── Phase-C execution gate ────────────────────────────────────────────────────
# FLIP THIS TO True AT PHASE-D CUTOVER ONLY.
# Every place this is checked is enumerated in core/engine.py comments.
CELL_EXECUTION_ENABLED: bool = True  # Phase D cutover 2026-07-04 — Brock explicit order
