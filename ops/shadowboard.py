"""ops/shadowboard.py — persistent stamp-forward scoreboard (ported from V5, 2026-07-15).

Every CELLSHADOW stamp (SHADOW *and* ACTIVE setups stamp) is episode-deduped
(30-min gap) and scored on its forward M5 path: net/MFE/MAE at 60m and 240m,
side-signed. Scores persist in data/shadowboard.json and accumulate for the
life of the bot — the dashboard shows cumulative stats, not a day's view.
Shadows and ACTIVE setups are scored on the IDENTICAL metric, so the board
answers directly: are any shadows beating the live book's entries? This is the
data layer the shadow->active promotion pipeline reads from.

V6 port adaptations (see docs/AUDIT_TODO.md):
  (a) The journald unit name is parameterized via SCROOGE_JOURNAL_UNIT (V5
      hardcoded mr-scrooge-v5). Default mr-scrooge-v6-dryrun (mr-scrooge-v6
      once live) so the board reads the V6 shadow's own stamps.
  (b) All scoring stays in a daemon thread (_refresh_worker); get_board() only
      ever returns the cache and kicks the thread — the dashboard server is
      single-threaded, so scoring must never run inline in a request handler
      (2026-07-09 lesson).
"""
from __future__ import annotations
import json, os, subprocess, threading, time, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

_ROOT  = Path(__file__).resolve().parent.parent
_STORE = _ROOT / "data" / "shadowboard.json"
_LOCK  = threading.Lock()
_CACHE: dict = {"ts": 0.0, "data": None}
_REFRESH_S = 900          # rebuild aggregates at most every 15 min
_EP_GAP_S  = 1800         # stamps >30 min apart = new episode
_MATURE_S  = 245 * 60     # episode scoreable once 240m+5m old
_SINCE     = "2026-07-04 08:00"   # journal query lower bound (cell-era cutover)

# (a) parameterized journald unit — default to the V6 dry-run shadow.
def _journal_unit() -> str:
    return os.environ.get("SCROOGE_JOURNAL_UNIT", "mr-scrooge-v6")

def _pip(pair): return 0.01 if "JPY" in pair else 0.0001

def _creds():
    from core.broker.oanda import _secrets
    s = _secrets()
    return (s.get("OANDA_API_URL", "https://api-fxpractice.oanda.com").rstrip("/"),
            s["OANDA_API_TOKEN"])

def _stamps():
    """All CELLSHADOW stamps from the journal (cell era)."""
    out = subprocess.run(
        ["journalctl", "--user", "-u", _journal_unit(), "--since", _SINCE,
         "-o", "short-iso", "--no-pager", "--grep", "CELLSHADOW"],
        capture_output=True, text=True, timeout=60).stdout
    rows = []
    for line in out.splitlines():
        try:
            ts = line.split()[0]
            i = line.index("CELLSHADOW ")
            parts = line[i:].split()
            cell, setup, side = parts[1], parts[2].split("=")[1], parts[3].split("=")[1]
            status = next((p.split("=")[1] for p in parts if p.startswith("status=")), "?")
            rows.append((datetime.fromisoformat(ts).astimezone(timezone.utc), cell, setup, side, status))
        except Exception:
            continue
    return rows

def _score(pair, t0, side):
    url, tok = _creds()
    u = (f"{url}/v3/instruments/{pair}/candles?granularity=M5"
         f"&from={t0.strftime('%Y-%m-%dT%H:%M:%SZ')}&count=49&price=M")
    cs = json.load(urllib.request.urlopen(urllib.request.Request(
        u, headers={"Authorization": f"Bearer {tok}"}), timeout=20))["candles"]
    if len(cs) < 13: return None
    pm = _pip(pair); entry = float(cs[0]["mid"]["o"])
    def leg(sub):
        hs = [float(c["mid"]["h"]) for c in sub]; ls = [float(c["mid"]["l"]) for c in sub]
        close = float(sub[-1]["mid"]["c"])
        if side == "long":
            return round((max(hs)-entry)/pm,1), round((entry-min(ls))/pm,1), round((close-entry)/pm,1)
        return round((entry-min(ls))/pm,1), round((max(hs)-entry)/pm,1), round((entry-close)/pm,1)
    mfe60, mae60, net60 = leg(cs[:13])
    mfe240, mae240, net240 = leg(cs)
    return {"mfe60": mfe60, "mae60": mae60, "net60": net60,
            "mfe240": mfe240, "mae240": mae240, "net240": net240}

def _load():
    try: return json.loads(_STORE.read_text())
    except Exception: return {"episodes": {}}

def _save(db):
    _STORE.parent.mkdir(exist_ok=True)
    tmp = _STORE.with_suffix(".tmp"); tmp.write_text(json.dumps(db)); tmp.replace(_STORE)

def _refresh(max_new_scores=40):
    db = _load()
    eps = db["episodes"]
    last_by_key = {}
    for t, cell, setup, side, status in sorted(_stamps()):
        key = f"{cell}|{setup}|{side}"
        prev = last_by_key.get(key)
        if prev is None or (t - prev).total_seconds() > _EP_GAP_S:
            ek = f"{key}|{t.strftime('%Y-%m-%dT%H:%M')}"
            if ek not in eps:
                eps[ek] = {"cell": cell, "setup": setup, "side": side, "status": status,
                           "t": t.isoformat(), "scores": None}
        last_by_key[key] = t
    now = datetime.now(timezone.utc)
    n_scored = 0
    for ek, ep in eps.items():
        if ep["scores"] is not None or n_scored >= max_new_scores: continue
        t0 = datetime.fromisoformat(ep["t"])
        if (now - t0).total_seconds() < _MATURE_S: continue
        try:
            ep["scores"] = _score(ep["cell"].split("/")[0], t0, ep["side"])
            n_scored += 1; time.sleep(0.05)
        except Exception:
            continue
    _save(db)
    return db



def _config_status():
    """(pair, session, setup_id) -> (CURRENT status, side) from config/cells
    (read fresh). The stamped status is what the setup WAS when it fired;
    promote/demote decisions need what it IS (2026-07-22, Brock). Side rides
    along so wired-but-unscored setups can appear as queued rows (2026-07-27)."""
    import json as _json
    from pathlib import Path as _P
    out = {}
    cdir = _P(__file__).resolve().parents[1] / "config" / "cells"
    try:
        for f in cdir.glob("*.json"):
            try:
                d = _json.loads(f.read_text())
            except Exception:
                continue
            pair = d.get("pair") or f.stem
            for sess, b in (d.get("sessions") or {}).items():
                for su in (b.get("setups") or []):
                    out[(pair, sess, su.get("id"))] = (su.get("status", "?"),
                                                       su.get("side", "?"))
    except OSError:
        pass
    return out

def _aggregate(db):
    import statistics as st
    groups = {}
    for ep in db["episodes"].values():
        if not ep["scores"]: continue
        key = (ep["cell"], ep["setup"], ep["side"])
        groups.setdefault(key, {"status": ep["status"], "rows": []})  # fallback: stamped
        groups[key]["rows"].append(ep)
        groups[key]["status"] = ep["status"]  # provisional; overridden by config below
    out = []
    _cfgst = _config_status()
    cutoff7 = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    for (cell, setup, side), g in groups.items():
        rows = g["rows"]; s = [r["scores"] for r in rows]
        nets = [x["net240"] for x in s]
        last7 = [r["scores"]["net240"] for r in rows if r["t"] >= cutoff7]
        # LCB (2026-07-24, Brock): 95% one-sided lower confidence bound on the
        # MEAN net240 — lcb = avg - 1.645*sd/sqrt(n). Small-n glamour rows
        # (3 eps, +8p avg) rank below big-n proven rows; n<2 has no variance
        # estimate -> None, sorts to the bottom ("too new, no sample").
        avg = sum(nets) / len(nets)
        lcb = (round(avg - 1.645 * st.stdev(nets) / len(nets) ** 0.5, 2)
               if len(nets) >= 2 else None)
        _st = _cfgst.get((cell.split("/")[0], cell.split("/")[1] if "/" in cell else "?", setup))
        out.append({
            "cell": cell, "setup": setup, "side": side,
            "status": _st[0] if _st else g["status"],
            "episodes": len(rows),
            "cum_net240": round(sum(nets), 1),
            "avg_net240": round(avg, 2),
            "lcb": lcb,
            "wr": round(sum(1 for n in nets if n > 0)/len(nets), 3),
            "hit6": round(sum(1 for x in s if x["mfe240"] >= 6)/len(s), 3),
            "med_mfe": round(st.median(x["mfe240"] for x in s), 1),
            "med_mae": round(st.median(x["mae240"] for x in s), 1),
            "avg_net60": round(sum(x["net60"] for x in s)/len(s), 2),
            "last7_avg": round(sum(last7)/len(last7), 2) if last7 else None,
            "last7_n": len(last7),
            "first": min(r["t"] for r in rows)[:10],
            # ACTIVATION BAR (2026-07-22, post-storm doctrine): current-era
            # evidence of n>=20 episodes AND avg net240 >= +2.0p (a margin that
            # clears toll uncertainty). ACTIVE without the bar = on borrowed
            # status; SHADOW meeting it = promotable.
            "bar_met": bool(len(rows) >= 20 and (sum(nets)/len(nets)) >= 2.0),
        })
    # QUEUED rows (2026-07-27, Brock: "I don't see the new pairs on the board"):
    # every wired ACTIVE/SHADOW setup with zero scored episodes still gets a
    # row, so the docket is visible — waiting is a state, not an absence.
    have = {(r["cell"], r["setup"]) for r in out}
    for (pair, sess, sid), (status, side) in _cfgst.items():
        cell = f"{pair}/{sess}"
        if status in ("ACTIVE", "SHADOW") and (cell, sid) not in have:
            out.append({
                "cell": cell, "setup": sid, "side": side, "status": status,
                "episodes": 0, "cum_net240": None, "avg_net240": None,
                "lcb": None, "wr": None, "hit6": None, "med_mfe": None,
                "med_mae": None, "avg_net60": None, "last7_avg": None,
                "last7_n": 0, "first": None, "bar_met": False, "queued": True,
            })
    # Sort by LCB (evidence-weighted), not raw avg — None (n<2) sorts last,
    # queued (no episodes) after everything scored.
    out.sort(key=lambda r: (r["lcb"] is not None,
                            r["lcb"] if r["lcb"] is not None else 0.0,
                            r["avg_net240"] if r["avg_net240"] is not None else -1e9),
             reverse=True)
    return out

_REFRESHING = {"on": False}

def _refresh_worker():
    """Runs in a daemon thread — never inside a dashboard request."""
    try:
        db = _refresh()
        rows = _aggregate(db)
        active = [r["avg_net240"] for r in rows
                  if r["status"] == "ACTIVE" and r["avg_net240"] is not None]
        data = {"rows": rows,
                "active_median": round(sorted(active)[len(active)//2], 2) if active else None,
                "pending": sum(1 for e in db["episodes"].values() if not e["scores"]),
                "generated": datetime.now(timezone.utc).isoformat()}
        with _LOCK:
            _CACHE.update(ts=time.time(), data=data)
    except Exception:
        pass
    finally:
        _REFRESHING["on"] = False

def get_board():
    """INSTANT: returns the cached board (or a building placeholder) and kicks
    a background refresh when stale. Never blocks the single-threaded server."""
    with _LOCK:
        stale = _CACHE["data"] is None or time.time() - _CACHE["ts"] >= _REFRESH_S
        data = _CACHE["data"]
    if stale and not _REFRESHING["on"]:
        _REFRESHING["on"] = True
        threading.Thread(target=_refresh_worker, daemon=True, name="shadowboard-refresh").start()
    if data is None:
        return {"rows": [], "active_median": None, "pending": None,
                "generated": None, "building": True}
    return data
