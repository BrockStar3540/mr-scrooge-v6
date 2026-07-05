"""ops/health.py — Module Health panel backend (V6, 2026-07-05).

One status per bot module: green / yellow / red + a one-line detail.
Consumed by GET /api/module_health and the dashboard MODULES tab.
Philosophy: every check answers "is this aspect of the bot alive and sane
RIGHT NOW", from live engine state + cheap probes. No check may throw —
a failing check reports itself red, never breaks the endpoint.
"""
from __future__ import annotations
import json, os, shutil, time
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_CACHE: dict = {"ts": 0.0, "data": None}
_BROKER_CACHE: dict = {"ts": 0.0, "summary": None, "open": None, "err": None}

GREEN, YELLOW, RED = "green", "yellow", "red"
_RANK = {GREEN: 0, YELLOW: 1, RED: 2}


def _age_s(dt) -> float:
    if dt is None:
        return float("inf")
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (now - dt).total_seconds()


def _broker_probe(engine):
    """Cached (60s) broker reachability + open trades."""
    now = time.time()
    if now - _BROKER_CACHE["ts"] < 60:
        return _BROKER_CACHE
    try:
        _BROKER_CACHE["summary"] = engine.broker.account_summary()
        _BROKER_CACHE["open"] = engine.broker.open_positions()
        _BROKER_CACHE["err"] = None
    except Exception as exc:
        _BROKER_CACHE["err"] = str(exc)[:120]
    _BROKER_CACHE["ts"] = now
    return _BROKER_CACHE


def _mk(module, status, detail, metric=None):
    return {"module": module, "status": status, "detail": detail, "metric": metric}


def _check_engine_scan(engine):
    age = _age_s(engine.last_cycle_time)
    if age < 600:   return _mk("engine.scan_loop", GREEN, f"last full cycle {age:.0f}s ago", round(age))
    if age < 1800:  return _mk("engine.scan_loop", YELLOW, f"cycle stale: {age/60:.1f}m", round(age))
    return _mk("engine.scan_loop", RED, "no full cycle in 30m+" if age != float("inf") else "never cycled", None)


def _check_engine_manage(engine):
    age = _age_s(getattr(engine, "last_manage_time", None))
    n = len(getattr(engine, "managers", {}))
    if n == 0 and age == float("inf"):
        return _mk("engine.manage_loop", GREEN, "no open positions to manage", 0)
    if age < 60:   return _mk("engine.manage_loop", GREEN, f"tick {age:.0f}s ago · {n} position(s)", round(age))
    if age < 300:  return _mk("engine.manage_loop", YELLOW, f"tick stale {age:.0f}s · {n} position(s)", round(age))
    return _mk("engine.manage_loop", RED, f"manage tick dead {age/60:.0f}m+ with {n} open position(s)", None)


def _check_feed(engine):
    age = _age_s(getattr(engine, "last_feed_time", None))
    nv = getattr(engine, "feed_views_n", None)
    from config.pairs import PAIRS
    want = len(PAIRS)
    if age < 660 and nv == want: return _mk("feed.candles", GREEN, f"{nv}/{want} pair views, {age:.0f}s ago", nv)
    if age < 660 and nv:         return _mk("feed.candles", YELLOW, f"partial views {nv}/{want}", nv)
    if age < 1800:               return _mk("feed.candles", YELLOW, f"views stale {age/60:.1f}m", nv)
    return _mk("feed.candles", RED, "no market views 30m+", nv)


def _check_broker(engine):
    b = _broker_probe(engine)
    if b["err"]: return _mk("broker.api", RED, f"API error: {b['err']}")
    return _mk("broker.api", GREEN, "authenticated, account reachable")


def _check_margin(engine):
    b = _broker_probe(engine)
    s = b["summary"] or {}
    try:
        used = float(s.get("marginUsed", 0)); nav = float(s.get("NAV", 0)) or 1.0
        pct = 100.0 * used / nav
    except Exception:
        return _mk("account.margin", YELLOW, "margin figures unavailable")
    if pct < 50: return _mk("account.margin", GREEN, f"margin used {pct:.0f}% of NAV", round(pct))
    if pct < 80: return _mk("account.margin", YELLOW, f"margin used {pct:.0f}% of NAV", round(pct))
    return _mk("account.margin", RED, f"margin used {pct:.0f}% of NAV — closeout risk zone", round(pct))


def _check_exit_managers(engine):
    """THE safety check: every broker-open trade must have a manager."""
    if getattr(engine, "dry_run", False):
        return _mk("exits.managers", GREEN,
                   "dry-run instance — broker trades belong to the live bot")
    b = _broker_probe(engine)
    if b["err"]: return _mk("exits.managers", YELLOW, "cannot compare (broker unreachable)")
    open_ids = {str(t.get("id")) for t in (b["open"] or [])}
    mgr_ids = {m.position.oanda_trade_id for m in getattr(engine, "managers", {}).values()}
    orphans = open_ids - mgr_ids            # broker trade, no manager — BAD
    stale   = mgr_ids - open_ids            # manager, no broker trade — cleanup lag
    if orphans: return _mk("exits.managers", RED, f"{len(orphans)} broker trade(s) UNMANAGED: {sorted(orphans)[:3]}", len(orphans))
    if stale:   return _mk("exits.managers", YELLOW, f"{len(stale)} stale manager(s) awaiting cleanup", len(stale))
    return _mk("exits.managers", GREEN, f"{len(mgr_ids)}/{len(open_ids)} open trades managed", len(mgr_ids))


def _check_cells(engine):
    mods = getattr(engine, "_pair_modules", {})
    from config.pairs import PAIRS
    n, want = len(mods), len(PAIRS)
    bad = []
    for f in sorted((_ROOT / "config" / "cells").glob("*.json")):
        try: json.loads(f.read_text())
        except Exception: bad.append(f.name)
    if bad:      return _mk("cells.configs", RED, f"unparseable cell config(s): {bad}")
    if n < want: return _mk("cells.configs", YELLOW, f"{n}/{want} pair modules loaded", n)
    return _mk("cells.configs", GREEN, f"{n}/{want} pair modules, all configs parse", n)


def _check_configs(engine):
    bad = []
    for name in ("exit_config.json", "playmaker_config.json"):
        try: json.loads((_ROOT / "config" / name).read_text())
        except Exception: bad.append(name)
    if bad: return _mk("config.hot_reload", RED, f"unparseable: {bad} (hot-reload will fall back to defaults)")
    return _mk("config.hot_reload", GREEN, "exit + playmaker configs parse")


def _check_calibration(engine):
    f = _ROOT / "config" / "cell_calibration.json"
    if not f.exists(): return _mk("calibration.artifact", YELLOW, "no calibration artifact")
    days = (time.time() - f.stat().st_mtime) / 86400
    if days < 40: return _mk("calibration.artifact", GREEN, f"artifact {days:.0f}d old (monthly refit)", round(days))
    if days < 75: return _mk("calibration.artifact", YELLOW, f"artifact {days:.0f}d old — refit overdue?", round(days))
    return _mk("calibration.artifact", RED, f"artifact {days:.0f}d old — refit pipeline broken?", round(days))


def _check_lock_guard(engine):
    st = getattr(engine, "_lock_guard_status", None)
    if not st: return _mk("playmaker.lock_guard", GREEN, "no lock snapshots to check (locks retired)")
    bad = [k for k, ok in st.items() if not ok]
    if bad: return _mk("playmaker.lock_guard", YELLOW, f"fingerprint drift flagged: {bad[:3]}", len(bad))
    return _mk("playmaker.lock_guard", GREEN, f"{len(st)} lock snapshot(s) consistent", len(st))


def _check_formula_shadow(engine):
    try:
        from modules.signals import formula_shadow as fs
        on = bool(fs.formula_shadow_enabled())
        return _mk("signals.formula_shadow", GREEN if on else YELLOW,
                   "stamping enabled" if on else "disabled (instrument off)")
    except Exception as exc:
        return _mk("signals.formula_shadow", YELLOW, f"module probe failed: {str(exc)[:60]}")


def _check_resources(engine):
    du = shutil.disk_usage("/")
    disk_pct = 100.0 * du.used / du.total
    avail_mb = None
    try:
        for line in open("/proc/meminfo"):
            if line.startswith("MemAvailable"):
                avail_mb = int(line.split()[1]) / 1024; break
    except Exception:
        pass
    if disk_pct > 90 or (avail_mb is not None and avail_mb < 250):
        return _mk("host.resources", RED, f"disk {disk_pct:.0f}% · RAM avail {avail_mb and round(avail_mb)}MB — OOM killed a trader host once (B-era 06-12)")
    if disk_pct > 80 or (avail_mb is not None and avail_mb < 500):
        return _mk("host.resources", YELLOW, f"disk {disk_pct:.0f}% · RAM avail {avail_mb and round(avail_mb)}MB")
    return _mk("host.resources", GREEN, f"disk {disk_pct:.0f}% · RAM avail {avail_mb and round(avail_mb)}MB")


def _check_rollover(engine):
    from modules.management.base import in_rollover_freeze
    frozen = in_rollover_freeze(datetime.now(timezone.utc))
    return _mk("exits.rollover_freeze", GREEN,
               "ACTIVE — stops frozen 20:55–22:05 UTC (by design)" if frozen else "inactive (outside window)")


_CHECKS = [_check_engine_scan, _check_engine_manage, _check_feed, _check_broker,
           _check_margin, _check_exit_managers, _check_cells, _check_configs,
           _check_calibration, _check_lock_guard, _check_formula_shadow,
           _check_resources, _check_rollover]


def snapshot(engine) -> dict:
    now = time.time()
    if _CACHE["data"] is not None and now - _CACHE["ts"] < 5:
        return _CACHE["data"]
    modules = []
    for chk in _CHECKS:
        try:
            modules.append(chk(engine))
        except Exception as exc:
            modules.append(_mk(chk.__name__.replace("_check_", ""), RED, f"check crashed: {str(exc)[:80]}"))
    overall = max((m["status"] for m in modules), key=lambda s: _RANK[s])
    data = {"overall": overall, "modules": modules,
            "ts": datetime.now(timezone.utc).isoformat()}
    _CACHE.update(ts=now, data=data)
    return data
