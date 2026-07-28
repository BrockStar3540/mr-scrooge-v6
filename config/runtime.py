"""config/runtime.py — hot-reloaded runtime switches.

Currently just the soft TRADING PAUSE gate.

config/runtime.json:  {"trading_enabled": true}

The engine reads trading_enabled() EACH CYCLE (same hot-reload pattern as the
cell configs), so the dashboard toggle takes effect without a restart.

FAIL-CLOSED (2026-07-27, external-review fix — this used to fail OPEN):
a corrupted pause file must never restart trading. Policy:
  - valid file             -> the value, cached as last-known-good (LKG)
  - unreadable / malformed -> the LKG if one exists, else False (PAUSED)
  - file genuinely absent  -> the LKG if one exists, else True
    (fresh install with no runtime.json ever written = never configured;
     the dashboard writes the file on first toggle)
The pause is a *soft* gate: it blocks NEW entries only; management/exits of
existing positions keep running. A full stop is
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

from config.safe_config import PathLKG

_last_warn = {"t": 0.0}
# Path-scoped LKG (review round 2): state can never leak across paths.
_runtime_lkg: PathLKG[bool] = PathLKG()


def _warn_once(msg: str) -> None:
    now = time.monotonic()
    if now - _last_warn["t"] > 3600:
        _last_warn["t"] = now
        log.warning(msg)


def _coerce_bool(v) -> bool | None:
    """Strict-ish bool coercion; None = malformed (NOT a silent default)."""
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)) and v in (0, 1):
        return bool(v)
    if isinstance(v, str) and v.strip().lower() in ("1", "true", "yes", "on"):
        return True
    if isinstance(v, str) and v.strip().lower() in ("0", "false", "no", "off"):
        return False
    return None


def load_runtime() -> dict:
    """Parse runtime.json → dict, or None-marker dicts on failure paths."""
    try:
        return {"_ok": True, "data": json.loads(RUNTIME_PATH.read_text())}
    except FileNotFoundError:
        return {"_ok": False, "missing": True}
    except Exception as exc:
        _warn_once(f"runtime.json unreadable ({exc}) — FAILING CLOSED "
                   f"(last-known-good or paused); fix or delete the file")
        return {"_ok": False, "missing": False}


def trading_enabled() -> bool:
    """The soft trading gate. Fail-CLOSED: corruption can never re-enable.
    NOTE: a key present with a malformed value (incl. null) is CORRUPTION,
    not a default — it fails closed (review round 2 contract)."""
    r = load_runtime()
    previous = _runtime_lkg.get(RUNTIME_PATH)
    if r["_ok"]:
        if "trading_enabled" not in r["data"]:
            return _runtime_lkg.remember(RUNTIME_PATH, True)  # valid file, key absent
        v = _coerce_bool(r["data"].get("trading_enabled"))
        if v is None:
            _warn_once("runtime.json trading_enabled is malformed — FAILING "
                       "CLOSED (last-known-good or paused)")
            return previous if previous is not None else False
        return _runtime_lkg.remember(RUNTIME_PATH, v)
    if r.get("missing"):
        # absent file = never configured; LKG wins if we ever read one
        return previous if previous is not None else True
    return previous if previous is not None else False   # unreadable


def set_trading_enabled(enabled: bool) -> dict:
    """Atomically persist the trading_enabled flag (preserving other keys).
    A corrupted existing file is replaced rather than merged — the write is
    the operator's explicit intent and re-establishes a valid file."""
    r = load_runtime()
    d = r["data"] if r["_ok"] and isinstance(r.get("data"), dict) else {}
    d["trading_enabled"] = bool(enabled)
    RUNTIME_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = RUNTIME_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=2))
    tmp.replace(RUNTIME_PATH)
    _runtime_lkg.remember(RUNTIME_PATH, bool(enabled))
    return d
