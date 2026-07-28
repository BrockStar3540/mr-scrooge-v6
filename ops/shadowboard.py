"""ops/shadowboard.py — persistent stamp-forward scoreboard (ported from V5, 2026-07-15).

Every stamp (SHADOW *and* ACTIVE setups stamp) is episode-deduped (30-min gap)
and scored on its forward M5 path. Scores persist in data/shadowboard.json and
accumulate for the life of the bot — the dashboard shows cumulative stats, not
a day's view. Shadows and ACTIVE setups are scored on the IDENTICAL metric, so
the board answers directly: are any shadows beating the live book's entries?
This is the data layer the shadow->active promotion pipeline reads from.

TWO METRIC VERSIONS coexist (D-7, external review round 2):
  legacy-mid-v1      — pre-D-7 CELLSHADOW-only episodes: frictionless mid
                       drift, candle-open anchored, fixed 240m close. Costs
                       deducted afterward (stamped spread + slippage).
  executable-exit-v2 — episodes opened WITH a TRIALSTAMP: entry is the
                       STAMPED executable price (ask long / bid short), the
                       forward path is bid/ask candles (price=BA), and the
                       exit is the setup's OWN geometry replayed by
                       core/shadow_execution (worst-case intrabar). Spread is
                       already paid inside that geometry, so cost adjustment
                       deducts slippage ONLY (core.trial_stats.episode_net).
Versions are marked per episode score ("mv": 2) and never silently conflated;
the evidence engine (D-7 stages D/E) promotes on v2 samples only.

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
    """All trial stamps from the journal (cell era) in ONE scan: legacy
    CELLSHADOW token lines and D-7 TRIALSTAMP JSON lines, so the episode
    dedup sees both and never double-counts one firing. Row shape:
    (t, cell, setup, side, status, spread, v2_payload_or_None)."""
    out = subprocess.run(
        ["journalctl", "--user", "-u", _journal_unit(), "--since", _SINCE,
         "-o", "short-iso", "--no-pager", "--grep", "CELLSHADOW|TRIALSTAMP"],
        capture_output=True, text=True, timeout=60).stdout
    from core.trial_events import parse_stamp
    rows = []
    for line in out.splitlines():
        try:
            t = datetime.fromisoformat(line.split()[0]).astimezone(timezone.utc)
        except Exception:
            continue
        if "TRIALSTAMP " in line:
            d = parse_stamp(line)
            if not d:
                continue
            rows.append((t, f'{d.get("pair")}/{d.get("session")}',
                         str(d.get("setup_id")), d.get("side", "?"),
                         d.get("status", "?"), d.get("spread_pips"), d))
            continue
        try:
            i = line.index("CELLSHADOW ")
            parts = line[i:].split()
            cell, setup, side = parts[1], parts[2].split("=")[1], parts[3].split("=")[1]
            status = next((p.split("=")[1] for p in parts if p.startswith("status=")), "?")
            spread = next((p.split("=")[1] for p in parts if p.startswith("spread=")), None)
            spread = float(spread) if spread is not None else None
            rows.append((t, cell, setup, side, status, spread, None))
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

def _score_v2(ep, t0):
    """D-7 scorer: bid/ask candles + the setup's OWN exit, replayed from the
    STAMPED executable entry by core/shadow_execution. Spread is inside the
    geometry; aggregation must deduct slippage only (episode_net)."""
    from core.shadow_execution import simulate_shadow_exit
    pair = ep["cell"].split("/")[0]
    url, tok = _creds()
    horizon = int(ep.get("horizon_min") or 240)
    count = min(500, max(13, horizon // 5 + 2))
    u = (f"{url}/v3/instruments/{pair}/candles?granularity=M5"
         f"&from={t0.strftime('%Y-%m-%dT%H:%M:%SZ')}&count={count}&price=BA")
    cs = json.load(urllib.request.urlopen(urllib.request.Request(
        u, headers={"Authorization": f"Bearer {tok}"}), timeout=20))["candles"]
    cs = [c for c in cs if c.get("complete", True)]
    stamp = {"side": ep["side"], "entry": ep.get("entry"),
             "horizon_min": horizon, "exit_config": ep.get("exit_config") or {}}
    o = simulate_shadow_exit(stamp, cs, _pip(pair))
    if o is None:
        return None
    return {"mv": 2, "net240": o.net_pips, "mfe240": o.mfe_pips,
            "mae240": o.mae_pips, "net60": None, "mfe60": None, "mae60": None,
            "exit_reason": o.exit_reason, "exit_bar": o.exit_bar,
            "ambiguous": o.ambiguous_bar}

def _fold_stamps(rows, eps):
    """Episode-dedup stamps into eps (pure — unit-testable). CELLSHADOW and
    TRIALSTAMP are emitted in the same cycle; a TRIALSTAMP within 2 min of
    its episode's OPENING stamp upgrades that episode to the v2 metric
    (executable entry + the setup's exit geometry) instead of creating a
    duplicate. Later within-episode stamps never re-anchor the entry."""
    last_by_key, cur = {}, {}
    for t, cell, setup, side, status, spread, v2 in sorted(rows, key=lambda r: r[0]):
        key = f"{cell}|{setup}|{side}"
        prev = last_by_key.get(key)
        if prev is None or (t - prev).total_seconds() > _EP_GAP_S:
            ek = f"{key}|{t.strftime('%Y-%m-%dT%H:%M')}"
            cur[key] = (ek, t)
            if ek not in eps:
                eps[ek] = {"cell": cell, "setup": setup, "side": side,
                           "status": status, "t": t.isoformat(),
                           "scores": None, "spread": spread}
        else:
            ek = cur.get(key, (None, None))[0]
        last_by_key[key] = t
        if v2 and ek and ek in eps and "mv" not in eps[ek]:
            t0 = cur[key][1]
            if (t - t0).total_seconds() <= 120:
                eps[ek].update(
                    mv=2, entry=v2.get("entry"), bid=v2.get("bid"),
                    ask=v2.get("ask"), spread=v2.get("spread_pips"),
                    horizon_min=v2.get("horizon_min", 240),
                    exit_config=v2.get("exit_config") or {},
                    mech=v2.get("mechanics_hash"))
    return eps

def _load():
    try: return json.loads(_STORE.read_text())
    except Exception: return {"episodes": {}}

def _save(db):
    _STORE.parent.mkdir(exist_ok=True)
    tmp = _STORE.with_suffix(".tmp"); tmp.write_text(json.dumps(db)); tmp.replace(_STORE)

def _refresh(max_new_scores=40):
    db = _load()
    eps = _fold_stamps(_stamps(), db["episodes"])
    now = datetime.now(timezone.utc)
    n_scored = 0
    for ek, ep in eps.items():
        if ep["scores"] is not None or n_scored >= max_new_scores: continue
        t0 = datetime.fromisoformat(ep["t"])
        # v2 episodes mature at their OWN horizon (+1 bar); legacy at 240m+5.
        mature_s = ((int(ep.get("horizon_min") or 240) + 5) * 60
                    if ep.get("mv") == 2 else _MATURE_S)
        if (now - t0).total_seconds() < mature_s: continue
        try:
            if ep.get("mv") == 2:
                ep["scores"] = _score_v2(ep, t0)
            else:
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

def _setup_aliases():
    """(cell, setup, side) -> new setup id. Continuity across renames (a setup
    reorganized under an honest name keeps its stamped history — 2026-07-27,
    Brock: sides are never flipped in place; counterparts get their own names)."""
    import json as _json
    try:
        rows = _json.loads((_ROOT / "config" / "setup_aliases.json").read_text())
        return {(r["cell"], r["setup"], r["side"]): r["as"] for r in rows}
    except Exception:
        return {}

def _aggregate(db):
    import statistics as st
    aliases = _setup_aliases()
    groups = {}
    for ep in db["episodes"].values():
        if not ep["scores"]: continue
        _sid = aliases.get((ep["cell"], ep["setup"], ep["side"]), ep["setup"])
        key = (ep["cell"], _sid, ep["side"])
        groups.setdefault(key, {"status": ep["status"], "rows": []})  # fallback: stamped
        groups[key]["rows"].append(ep)
        groups[key]["status"] = ep["status"]  # provisional; overridden by config below
    out = []
    _cfgst = _config_status()
    cutoff7 = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    # D-6 (external review): the board judges by the EXACT metric the governor
    # promotes on — cost-adjusted nets, overlap-aware effective n, deflated z
    # from governor config. D-7: cost adjustment is METRIC-VERSION aware —
    # executable-exit-v2 scores already paid the spread in their geometry.
    from core.trial_stats import effective_n, episode_net, lcb as _tlcb
    try:
        _gc = json.loads((_ROOT / "config" / "governor_config.json").read_text())
    except Exception:
        _gc = {}
    _z = float(_gc.get("z_promote", 2.33))
    _slip = float(_gc.get("slippage_pips", 0.5))
    for (cell, setup, side), g in groups.items():
        rows = g["rows"]; s = [r["scores"] for r in rows]
        pair = cell.split("/")[0]
        nets = [episode_net(x["net240"], r.get("spread"), pair,
                            slippage_pips=_slip,
                            executable=bool(x.get("mv") == 2))
                for r, x in zip(rows, s)]
        last7 = [net for r, net in zip(rows, nets) if r["t"] >= cutoff7]
        avg = sum(nets) / len(nets)
        n_eff = effective_n([r["t"] for r in rows])
        lcb = _tlcb(nets, n_eff, _z)
        _st = _cfgst.get((cell.split("/")[0], cell.split("/")[1] if "/" in cell else "?", setup))
        # Side-aware status join (2026-07-27): a row whose side no longer matches
        # the config (an MAE-flip retired it) must not inherit the live side's
        # ACTIVE badge — it shows EX-SIDE and keeps its history as the autopsy.
        if _st and _st[1] not in (side, "?"):
            _status = "EX-SIDE"
        else:
            _status = _st[0] if _st else g["status"]
        out.append({
            "cell": cell, "setup": setup, "side": side,
            "status": _status,
            "episodes": len(rows),
            "cum_net240": round(sum(nets), 1),      # net-of-cost (D-6)
            "avg_net240": round(avg, 2),            # net-of-cost (D-6)
            "lcb": lcb,
            "wr": round(sum(1 for n in nets if n > 0)/len(nets), 3),
            "hit6": round(sum(1 for x in s if x["mfe240"] >= 6)/len(s), 3),
            "med_mfe": round(st.median(x["mfe240"] for x in s), 1),
            "med_mae": round(st.median(x["mae240"] for x in s), 1),
            # net60 exists only on legacy-mid-v1 scores (v2 exits when the
            # SETUP says, not at a fixed 60m checkpoint)
            "avg_net60": (round(sum(_n60)/len(_n60), 2)
                          if (_n60 := [x["net60"] for x in s
                                       if x.get("net60") is not None]) else None),
            "n_v2": sum(1 for x in s if x.get("mv") == 2),
            "n_ambig": sum(1 for x in s if x.get("ambiguous")),
            "last7_avg": round(sum(last7)/len(last7), 2) if last7 else None,
            "last7_n": len(last7),
            "n_eff": n_eff,
            "first": min(r["t"] for r in rows)[:10],
            # ACTIVATION BAR, net-of-cost basis (D-6): n>=20 episodes AND
            # avg >= +2.0p AFTER spread+slippage — "+2p clear of the toll"
            # is now literal, not aspirational. ACTIVE without the bar = on
            # borrowed status; SHADOW meeting it = promotable.
            "bar_met": bool(len(rows) >= 20 and avg >= 2.0),
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
                "med_mae": None, "avg_net60": None, "n_v2": 0, "n_ambig": 0,
                "last7_avg": None,
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
