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

def _exit_geo():
    """(pair, session, setup_id) -> (trigger_pips, sl_pips) from config/cells,
    read fresh — hit>=trig and hit-SL% must follow the LIVE gear, so a re-tuned
    trigger or a range-sized stop (40/50/60) re-scores the columns on the next
    build instead of silently using a stale constant."""
    import glob
    out = {}
    for f in glob.glob(str(_ROOT / "config" / "cells" / "*.json")):
        pair = os.path.basename(f)[:-5]
        try:
            d = json.load(open(f))
        except (OSError, ValueError):
            continue
        for sess, sd in (d.get("sessions") or {}).items():
            for su in sd.get("setups", []):
                ex = su.get("exit") or {}
                out[(pair, sess, su.get("id"))] = (ex.get("trigger_pips"),
                                                   ex.get("sl_pips"))
    return out


def _hit_thresholds(geo, pair, sess, setup):
    """(engage_thr, death_thr) for one setup. Engage = trigger + 0.5p (mfe240
    is mid; executable must clear the trigger — Brock's 9p rule, 20.5 t20s).
    Death = SL - 0.5p (mid UNDERstates adverse excursion: the executable side
    hits the stop before mid does). Fallbacks: trigger 20/t20s else 8.5, SL 60."""
    trig, sl = geo.get((pair, sess, setup), (None, None))
    if trig is None:
        trig = 20.0 if setup.endswith("_t20s") else 8.5
    return trig + 0.5, (sl or 60.0) - 0.5

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
    # CENSORED (charter, 2026-07-31): the live ratchet has no timeout, so a
    # sim that reaches the horizon without a stop/ratchet exit is an episode
    # STILL OPEN, not a closed outcome. Its MFE/MAE are real observations;
    # its "net" is not — net240=None drops it from every net/WR aggregate.
    if o.exit_reason == "horizon":
        return {"mv": 2, "net240": None, "mfe240": o.mfe_pips,
                "mae240": o.mae_pips, "net60": None, "mfe60": None,
                "mae60": None, "exit_reason": "horizon", "censored": True,
                "exit_bar": o.exit_bar, "ambiguous": o.ambiguous_bar}
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

_FAM_CACHE: dict = {"ts": 0.0, "data": {}}
_FAM_TTL_S = 600     # broker families view refreshed at most every 10 min


def _families():
    """(pair, family_setup) -> broker families row (parent + poppers, one
    unit, incl. n_open). Cached; runs only inside the refresh daemon thread,
    never in a request handler. Empty dict on any failure — the board then
    simply shows no family column, it never breaks."""
    now = time.time()
    if now - _FAM_CACHE["ts"] < _FAM_TTL_S:
        return _FAM_CACHE["data"]
    try:
        import sys as _sys
        out = subprocess.run(
            [_sys.executable, str(_ROOT / "research" / "tools" / "broker_setup_audit.py"),
             "--json"], capture_output=True, text=True, timeout=180)
        fams = {(r["instrument"], r.get("session", "?"), r["setup"]): r
                for r in json.loads(out.stdout).get("families", [])}
        _FAM_CACHE.update(ts=now, data=fams)
    except Exception:
        _FAM_CACHE["ts"] = now          # don't hammer a failing audit
    return _FAM_CACHE["data"]


# Governor-ordered tiers — the board sorts EXACTLY the way capital moves,
# with the most ACTIONABLE tier first (Brock, 2026-07-29): demote-due leads,
# then the best seats, then the promotion pipeline.
TIER_LABELS = {
    0: "DEMOTE DUE — loses the seat at the next 06:35Z run",
    1: "DEFENDED — broker family green, seat safe",
    2: "ACTIVE — holding (or episode open, verdict deferred)",
    3: "PROMOTE READY — passes the full bar at the next 06:35Z run",
    4: "BUILDING EVIDENCE — shadows accruing the era-v2 sample",
    5: "AWAITING V2 / QUEUED — no era-v2 evidence yet (legacy v1 history never counts toward the bar; the era sample restarted 2026-07-28)",
    7: "RETIRED / EX-SIDE — history kept as the autopsy",
}


def _gov_verdict(status, era_dict, e_obj, f, gc, min_raw, lifetime_eps=0):
    """One row's governor view -> (tier, verdict, reason, score).
    Mirrors ops.governor exactly: ACTIVE rows through active_verdict (family
    rule + judge-when-flat, e_obj = the SetupEvidence the governor reads),
    SHADOW rows through the promotion predicate (era_dict = its display form).
    lifetime_eps distinguishes AWAITING V2 (has legacy history, era restarted)
    from QUEUED (never scored anything)."""
    from ops.governor import active_verdict as _av
    if status == "ACTIVE":
        demote, reason = _av(e_obj, f, gc, min_raw)
        famnet = f["net_pips"] if f else 0.0
        if demote:
            return 0, "DEMOTE DUE", reason, famnet
        if reason == "family_green":
            return 1, "DEFENDED", reason, famnet
        if reason == "episode_open":
            return 2, "DEFERRED", reason, famnet
        return 2, "HOLDING", reason, \
            (famnet or (era_dict.get("avg") if era_dict else 0) or 0)
    # SHADOW
    if era_dict and era_dict.get("promotable"):
        return 3, "PROMOTE READY", "passes full bar", (era_dict.get("lcb") or 0)
    if era_dict and gc.get("cheater_promotion_enabled", False) and (
            (era_dict.get("n") or 0) >= int(gc.get("cheater_min_n", 3))) and (
            (era_dict.get("avg") or 0) * era_dict["n"]
            >= float(gc.get("cheater_cum_pips", 100.0))):
        cum = (era_dict.get("avg") or 0) * era_dict["n"]
        return 3, "PROMOTE READY", (
            f"CHEATER rule: era cum {cum:+.1f}p >= "
            f"+{gc.get('cheater_cum_pips', 100.0):.0f}p — hot hand, bar bypassed"), cum
    if era_dict:
        passed = 6 - len(era_dict.get("codes") or [])
        return 4, "BUILDING", "needs " + ",".join(era_dict.get("codes") or []), \
            passed * 1000 + (era_dict.get("avg") or 0)
    if lifetime_eps:
        return 5, "AWAITING V2", (
            "has lifetime legacy-metric history only — the 2026-07-28 metric "
            "reset restarted every era sample at zero; promotes ONLY on new "
            "executable-exit-v2 episodes (bar: n>=20, 10 day-blocks, "
            "avg>=+2p, LCB>0, FDR)"), float(lifetime_eps)
    return 5, "QUEUED", "no scored episodes yet", 0.0


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
    _geo = _exit_geo()
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
    # D-7: the trophy IS the governor's promotion predicate — one shared
    # engine (current era, executable-exit-v2 only, block bootstrap, BH-FDR).
    # Lifetime columns stay as research context; only `era` governs capital.
    _gov_ok = False
    try:
        from core.trial_evidence import current_era_evidence
        from ops.governor import book as _gbook, cfg as _gcfg, \
            load_state as _gstate, _aliases as _gal, \
            family_era_view as _fview, active_verdict as _averdict
        _gc_full = _gcfg()
        _eras = (_gstate() or {}).get("era_start", {})
        _ev = current_era_evidence(db["episodes"], _gbook(), _gstate(),
                                   _gc_full, aliases=_gal())
        _gov_ok = True
    except Exception:
        _ev, _gc_full, _eras = {}, dict(_gc), {}
    _fams = _families() if _gov_ok else {}
    _min_raw = int(_gc_full.get("min_raw_episodes", _gc_full.get("bar_n", 20)))
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
        _e = None if _status == "EX-SIDE" else _ev.get(
            (pair, cell.split("/")[1] if "/" in cell else "?", setup))
        era = None
        if _e:
            era = {"n": _e.raw_n, "days": _e.independent_days,
                   "avg": _e.net_avg, "lcb": _e.block_lcb, "q": _e.q_value,
                   "promotable": _e.promotable,
                   "codes": list(_e.reason_codes)}
        # THE GOVERNOR'S OWN VIEW (v6.8.0): each row carries the verdict the
        # governor would reach today — family rule, judge-when-flat, promotion
        # predicate — plus the tier that orders the board exactly as capital
        # moves. Best seats at the top, demote-due at the bottom.
        _te, _td = _hit_thresholds(_geo, pair,
                                   cell.split("/")[1] if "/" in cell else "?", setup)
        gov = None
        if _gov_ok and _status in ("ACTIVE", "SHADOW"):
            sess = cell.split("/")[1] if "/" in cell else "?"
            fam_row = _fams.get((pair, sess, setup))
            f = None
            if fam_row is not None:
                era_start = _eras.get("|".join((pair, sess, setup)),
                                      str(_gc_full.get("default_era_start", "")))
                f = _fview(fam_row, era_start)
            tier, verdict, reason, score = _gov_verdict(
                _status, era, _e, f, _gc_full, _min_raw, lifetime_eps=len(rows))
            gov = {"tier": tier, "verdict": verdict, "reason": reason,
                   "score": round(float(score), 2), "family": f}
        out.append({
            "cell": cell, "setup": setup, "side": side,
            "status": _status,
            "episodes": len(rows),
            "cum_net240": round(sum(nets), 1),      # net-of-cost (D-6)
            "avg_net240": round(avg, 2),            # net-of-cost (D-6)
            "lcb": lcb,
            "wr": round(sum(1 for n in nets if n > 0)/len(nets), 3),
            # hit_eng / hit_sl (2026-07-30, Brock): the two events that decide
            # a trade's fate, on the setup's OWN config geometry. Engage locks
            # +6 and cannot lose; death eats the full stop. At lock 6 / SL 60
            # one death costs ten engages — the pair of columns IS the
            # breakeven math. (hit>=6p retired: it measured the lock level and
            # flattered almost-winners — rvol_low_240_t20s touched +6p in 61%
            # of episodes, reached its 20p trigger in 17%.)
            "hit_eng": round(sum(1 for x in s if x["mfe240"] >= _te)/len(s), 3),
            "hit_sl": round(sum(1 for x in s if x["mae240"] >= _td)/len(s), 3),
            "med_mfe": round(st.median(x["mfe240"] for x in s), 1),
            "med_mae": round(st.median(x["mae240"] for x in s), 1),
            # net60 exists only on legacy-mid-v1 scores (v2 exits when the
            # SETUP says, not at a fixed 60m checkpoint)
            "avg_net60": (round(sum(_n60)/len(_n60), 2)
                          if (_n60 := [x["net60"] for x in s
                                       if x.get("net60") is not None]) else None),
            "n_v2": sum(1 for x in s if x.get("mv") == 2),
            "n_censored": sum(1 for x in s if x.get("censored")),
            "n_ambig": sum(1 for x in s if x.get("ambiguous")),
            "last7_avg": round(sum(last7)/len(last7), 2) if last7 else None,
            "last7_n": len(last7),
            "n_eff": n_eff,
            "first": min(r["t"] for r in rows)[:10],
            # D-7: the trophy equals the governor's promotion predicate
            # EXACTLY (current-era v2 evidence, block bootstrap, FDR) —
            # the board can never award what the governor would reject.
            "era": era,
            "bar_met": bool(era and era["promotable"]),
            "gov": gov,
        })
    # QUEUED rows (2026-07-27, Brock: "I don't see the new pairs on the board"):
    # every wired ACTIVE/SHADOW setup with zero scored episodes still gets a
    # row, so the docket is visible — waiting is a state, not an absence.
    have = {(r["cell"], r["setup"]) for r in out}
    for (pair, sess, sid), (status, side) in _cfgst.items():
        cell = f"{pair}/{sess}"
        if status in ("ACTIVE", "SHADOW") and (cell, sid) not in have:
            gov = None
            if _gov_ok:
                fam_row = _fams.get((pair, sess, sid))
                f = _fview(fam_row, _eras.get(
                    "|".join((pair, sess, sid)),
                    str(_gc_full.get("default_era_start", "")))) if fam_row else None
                tier, verdict, reason, score = _gov_verdict(
                    status, None, None, f, _gc_full, _min_raw)
                gov = {"tier": tier, "verdict": verdict, "reason": reason,
                       "score": round(float(score), 2), "family": f}
            out.append({
                "cell": cell, "setup": sid, "side": side, "status": status,
                "episodes": 0, "cum_net240": None, "avg_net240": None,
                "lcb": None, "wr": None, "hit_eng": None, "hit_sl": None,
                "med_mfe": None,
                "med_mae": None, "avg_net60": None, "n_v2": 0, "n_ambig": 0,
                "last7_avg": None, "era": None,
                "last7_n": 0, "first": None, "bar_met": False, "queued": True,
                "gov": gov,
            })
    # GOVERNOR ORDER (v6.8.0): tier asc (defended seats first, demote-due
    # last-but-for-retired), score desc inside a tier — the board reads
    # top-to-bottom exactly as the governor ranks the book. Rows without a
    # gov view (EX-SIDE, engine-degraded) fall back to the old LCB order.
    out.sort(key=_row_key)
    return out


def _row_key(r):
    """Governor board order — module-level so the B-113 serve-time status
    overlay can re-sort the cached rows after a flip."""
    g = r.get("gov")
    tier = g["tier"] if g else 7
    score = g["score"] if g else (r["lcb"] if r["lcb"] is not None else -1e9)
    # tier 0 (demote due): WORST first — urgency order; every other tier:
    # best first.
    return (tier, score if tier == 0 else -score,
            -(r["avg_net240"] if r["avg_net240"] is not None else 1e9))

_REFRESHING = {"on": False}

def _refresh_worker():
    """Runs in a daemon thread — never inside a dashboard request."""
    try:
        db = _refresh()
        rows = _aggregate(db)
        active = [r["avg_net240"] for r in rows
                  if r["status"] == "ACTIVE" and r["avg_net240"] is not None]
        data = {"rows": rows,
                "tiers": TIER_LABELS,
                "active_median": round(sorted(active)[len(active)//2], 2) if active else None,
                "pending": sum(1 for e in db["episodes"].values() if not e["scores"]),
                "generated": datetime.now(timezone.utc).isoformat()}
        with _LOCK:
            _CACHE.update(ts=time.time(), data=data)
    except Exception:
        pass
    finally:
        _REFRESHING["on"] = False

def invalidate():
    """A status flip just landed (POST /api/cell/status) — mark the cached
    board stale so the next GET kicks an immediate background rebuild. The
    B-113 overlay keeps the served rows truthful in the meantime."""
    with _LOCK:
        _CACHE["ts"] = 0.0


def _overlay_live_status(data):
    """B-113: the board payload is cached up to 15 min, but STATUS must never
    be stale — a manual (or governor) flip has already changed what the
    engine trades. Re-join config/cells at serve time; where the live status
    differs from the baked row, patch status + tier in place, flag the row
    (flip_pending) so the UI knows the full governor view is still
    rebuilding, and re-sort. EX-SIDE rows keep their autopsy badge (the
    side-aware join from build time owns them)."""
    rows = data.get("rows") or []
    if not rows:
        return
    cfg = _config_status()
    changed = False
    for r in rows:
        if r.get("status") == "EX-SIDE":
            continue
        pair, _, sess = (r.get("cell") or "").partition("/")
        st = cfg.get((pair, sess or "?", r.get("setup")))
        if not st or st[0] == r.get("status"):
            continue
        if st[1] not in (r.get("side"), "?", None):
            continue          # side retired since build — EX-SIDE logic owns it
        live = st[0]
        r["status"] = live
        r["flip_pending"] = True
        g = r.get("gov")
        if g is not None:
            if live == "ACTIVE":
                g.update(tier=2, verdict="HOLDING",
                         reason="seated since the last board build — full "
                                "family/bar view on the next refresh")
            elif live == "SHADOW":
                g.update(tier=4 if r.get("era") else 5,
                         verdict="BUILDING" if r.get("era") else "QUEUED",
                         reason="benched since the last board build — full "
                                "view on the next refresh")
            else:             # DISABLED — off the governor's docket entirely
                r["gov"] = None
        changed = True
    if changed:
        rows.sort(key=_row_key)


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
    try:
        _overlay_live_status(data)   # B-113: status is always live truth
    except Exception:
        pass
    return data
