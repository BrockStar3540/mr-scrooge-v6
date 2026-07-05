"""modules/cells/pair_module.py — PairModule (Phase C).

Holds the set of CellModules for one pair.  Session gate comes from the
per-session "enabled" flag in the pair's config/cells/<PAIR>.json.

Usage (from engine):
    pair_module = PairModule(pair, config_dict)
    ...
    for cell in pair_module.active_cells(now):
        intent = cell.evaluate(view, now)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Iterator, Optional

from .cell import CellModule, _load_pair_config

log = logging.getLogger("v5.cells")

# Session gate uses the CANONICAL session mapping (config/sessions.py) — a
# duplicated hour table here drifted once already (london 07-16 vs canonical
# 07-13) and would cross-stamp cells; single source of truth only.
from config.sessions import coarse_session as _coarse_session


def _in_session(session: str, hour_utc: int) -> bool:
    """True if hour_utc falls inside the session per config/sessions.py."""
    return _coarse_session(hour_utc) == session


class PairModule:
    """Holds CellModules for one pair.  Hot-reloads config each call to active_cells()."""

    def __init__(self, pair: str):
        self.pair = pair

    def active_cells(self, now: datetime) -> Iterator[CellModule]:
        """Yield CellModules whose session is currently active and enabled in config.

        Config is hot-reloaded from disk on each call (mtime check inside
        _load_pair_config — O(1) stat per call; no I/O on cache hit).
        Missing / malformed config → yields nothing silently.
        """
        cfg = _load_pair_config(self.pair)
        if cfg is None:
            return

        sessions_cfg = cfg.get("sessions", {})
        hour_utc = now.utctimetuple().tm_hour

        for session_name, session_cfg in sessions_cfg.items():
            if not isinstance(session_cfg, dict):
                continue
            if not session_cfg.get("enabled", False):
                continue
            if not _in_session(session_name, hour_utc):
                continue
            yield CellModule(pair=self.pair, session=session_name, config=session_cfg)
