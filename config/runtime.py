"""config/runtime.py — hot-reloaded runtime switches.

Currently just the soft TRADING PAUSE gate.

config/runtime.json:  {"trading_enabled": true}

The engine reads trading_enabled() EACH CYCLE (same hot-reload pattern as the
cell configs), so the dashboard toggle takes effect without a restart.

FAIL-SAFE: a missing or unreadable file defaults to ENABLED — we never silently
halt a running bot on a read error. The pause is a *soft* gate: it blocks NEW
entries only; management/exits of existing positions keep running. It is NOT a
process kill (the dashboard runs inside the engine process). A full stop is
`systemctl --user stop mr-scrooge-v6`.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

log = logging.getLogger("v6.runtime")

_REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_PATH = _REPO_ROOT / "config" / "runtime.json"

_last_warn = {"t": 0.0}


def _warn_once(msg: str) -> None:
    now = time.monotonic()
    if now - _last_warn["t"] > 3600:
        _last_warn["t"] = now
        log.warning(msg)


def load_runtime() -> dict:
    """Parse runtime.json → dict. Missing file → {} (defaults apply). A read/parse
    error → {} too, but logged (rate-limited) so the fail-safe is visible."""
    try:
        return json.loads(RUNTIME_PATH.read_text())
    except FileNotFoundError:
        return {}
    except Exception as exc:
        _warn_once(f"runtime.json unreadable ({exc}) — failing safe to trading_enabled=True")
        return {}


def trading_enabled() -> bool:
    """True unless the operator has explicitly paused trading. Fail-safe: any
    ambiguity (missing key/file, bad value, read error) → True (keep trading)."""
    v = load_runtime().get("trading_enabled", True)
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return True   # fail-safe: never halt on a malformed value


def set_trading_enabled(enabled: bool) -> dict:
    """Atomically persist the trading_enabled flag (preserving other keys)."""
    d = load_runtime()
    if not isinstance(d, dict):
        d = {}
    d["trading_enabled"] = bool(enabled)
    RUNTIME_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = RUNTIME_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=2))
    tmp.replace(RUNTIME_PATH)
    return d
