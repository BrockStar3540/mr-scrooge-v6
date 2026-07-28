"""core/trial_events.py — versioned, structured trial stamps (D-7).

The old CELLSHADOW line is free-form tokens carrying no executable entry; the
scorer later anchored on a candle open minutes after the decision. TRIALSTAMP
is one JSON object per qualifying setup, logged alongside CELLSHADOW (legacy
consumers keep working), carrying everything the shadow-execution scorer
needs: the stamped bid/ask, the EXECUTABLE entry (ask for longs, bid for
shorts), the setup's own exit geometry, and a mechanics hash so evidence can
never straddle a config change.

METRIC VERSIONS
  legacy-mid-v1       — pre-D-7 episodes: mid-candle drift at a fixed 240m
  executable-exit-v2  — D-7: stamped executable entry, bid/ask path, the
                        setup's own exit simulation
Never mix versions inside one promotion sample.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Optional

METRIC_LEGACY = "legacy-mid-v1"
METRIC_V2 = "executable-exit-v2"

_MECHANICS_KEYS = ("side", "conditions", "exit", "sizing", "horizon_min")


def mechanics_hash(setup: dict) -> str:
    """Hash of a setup's MECHANICS (not its prose). One implementation for
    stamps, the governor's era clocks, and the evidence engine."""
    core = {k: setup.get(k) for k in _MECHANICS_KEYS}
    return hashlib.sha256(
        json.dumps(core, sort_keys=True, default=str).encode()).hexdigest()[:16]


@dataclass(frozen=True)
class TrialStamp:
    version: int
    timestamp: str            # ISO-8601 UTC
    pair: str
    session: str
    setup_id: str
    side: str
    status: str
    bid: float
    ask: float
    entry: float              # executable: ask for long, bid for short
    spread_pips: float
    horizon_min: int
    exit_config: dict
    mechanics_hash: str

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"), default=str)


def make_stamp(*, now: datetime, pair: str, session: str, setup: dict,
               status: str, view) -> Optional[TrialStamp]:
    """Build a TrialStamp from a qualifying setup + live view. Returns None if
    the view lacks bid/ask (stamp degraded — caller logs and skips v2)."""
    bid = getattr(view, "bid", None)
    ask = getattr(view, "ask", None)
    try:
        bid, ask = float(bid), float(ask)
        if bid <= 0 or ask <= 0:
            return None
    except (TypeError, ValueError):
        return None
    side = setup.get("side", "?")
    return TrialStamp(
        version=2,
        timestamp=now.isoformat(),
        pair=pair,
        session=session,
        setup_id=str(setup.get("id", "?")),
        side=side,
        status=status,
        bid=bid,
        ask=ask,
        entry=ask if side == "long" else bid,
        spread_pips=float(getattr(view, "spread_pips", 0.0) or 0.0),
        horizon_min=int(setup.get("horizon_min", 240)),
        exit_config=dict(setup.get("exit") or {}),
        mechanics_hash=mechanics_hash(setup),
    )


def parse_stamp(line: str) -> Optional[dict]:
    """Parse a TRIALSTAMP journal line (anything before the JSON is ignored)."""
    i = line.find("TRIALSTAMP ")
    if i < 0:
        return None
    payload = line[i + len("TRIALSTAMP "):].strip()
    try:
        d = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if not isinstance(d, dict) or d.get("version") != 2:
        return None
    return d
