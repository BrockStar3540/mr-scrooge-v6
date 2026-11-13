"""config/day_gate.py — hot-reloaded "bad day" entry filter (Brock, 2026-11-13: "just try it").

Skips NEW entries (cell parents and popper fires) on FX trading days that were the book's worst in the live
tape, except for setup families that did fine on those days. FX trading day = New York clock + 7h (rolls at
17:00 ET), the same definition the day-cut research used (trade-book-2026-11-06/skip_days*.py).

Bad day = FX trading day Thursday or Friday, or a scheduled-event day (config/day_gate.json "event_days":
date -> currencies, ["ALL"] = every pair) when the pair carries that currency.
Exempt family = setup_id equals the family name or starts with "<family>_" (same rule as the trade book).

This is an experiment, not a proven edge: the research found no day rule that beat random day-skipping with
confidence, and exemptions picked in advance did worse out of sample. Kill-switch: "enabled": false (hot-reload,
no restart). FAIL-OPEN on any config error (it is a filter, not a safety control): the bot then trades as before.
Only entries are gated; open positions and the ratchet are never touched.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

log = logging.getLogger("v6.daygate")
_PATH = Path(__file__).resolve().parent / "day_gate.json"
_NY = ZoneInfo("America/New_York")
_cache: dict = {"mtime": None, "cfg": None}
_seen: set = set()
_warn_ts = {"t": 0.0}


def _load() -> dict | None:
    try:
        mt = _PATH.stat().st_mtime
        if _cache["mtime"] != mt:
            _cache["cfg"] = json.loads(_PATH.read_text())
            _cache["mtime"] = mt
        return _cache["cfg"]
    except FileNotFoundError:
        return None
    except Exception as exc:                       # malformed -> fail open, warn hourly
        if time.monotonic() - _warn_ts["t"] > 3600:
            _warn_ts["t"] = time.monotonic()
            log.warning("day_gate.json unreadable (%s) — FAILING OPEN (no day filter)", exc)
        return None


def fx_trading_day(now: datetime) -> date:
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return (now.astimezone(_NY) + timedelta(hours=7)).date()


def family_exempt(setup_id: str, families) -> bool:
    sid = setup_id or ""
    return any(sid == f or sid.startswith(f + "_") for f in families or ())


def reason(now: datetime, pair: str, setup_id: str, cfg: dict | None = None) -> str | None:
    """Why this entry is skipped, or None to allow it."""
    cfg = cfg if cfg is not None else _load()
    if not cfg or not cfg.get("enabled", False):
        return None
    if family_exempt(setup_id, cfg.get("exempt_families")):
        return None
    d = fx_trading_day(now)
    if d.weekday() in set(cfg.get("skip_weekdays", [])):
        return "weekday-" + d.strftime("%a")
    cur = (cfg.get("event_days") or {}).get(d.isoformat())
    if cur and ("ALL" in cur or set(pair.split("_")) & set(cur)):
        return "event-" + d.isoformat()
    return None


def blocked(now: datetime, pair: str, setup_id: str, extra: str = "") -> bool:
    r = reason(now, pair, setup_id)
    if r is None:
        return False
    key = (pair, setup_id, fx_trading_day(now))
    if key not in _seen:                          # one log line per pair/setup/day (first signal of the day)
        _seen.add(key)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        log.info("DAYGATE skip %s setup=%s reason=%s t=%s%s | engine=day_gate", pair, setup_id, r,
                 now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), extra)
    return True


def _intent_extra(i) -> str:
    """Side and exit geometry of a skipped CellIntent, so the gate test can replay what the gate refused."""
    ep = getattr(i, "exit_params", None)
    f = lambda n: getattr(ep, n, 0.0) if ep is not None else 0.0
    return (f" side={getattr(i, 'side', '?')} h={getattr(i, 'horizon_min', 0)} sl={f('sl_pips')} trig={f('trigger_pips')}"
            f" trail={f('trail_pips')} eng={f('engage_pips')} englock={f('engage_lock_pips')} mode={getattr(ep, 'mode', '?')}"
            f" probe={int(bool(getattr(i, 'probe', False)))}")


def filter_intents(intents: list, now: datetime) -> list:
    """Drop gated CellIntents (shadow stamps already happened inside evaluate)."""
    return [i for i in intents if not blocked(now, i.pair, i.setup_id, _intent_extra(i))]
