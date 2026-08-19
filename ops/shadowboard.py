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
_LATCH_TIMEOUT_S = 600    # B-133: presume a refresh thread dead after this lease
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

# How far past the horizon a still-open stamp may be followed before we give
# up and call it genuinely censored. 5 days of M5 bars; live grids retire at
# grid_max_age_days=7, so this sits inside the window the bot itself allows.
FOLLOW_MAX_DAYS = 5.0


def _candles_ba(pair, t0, n_bars, url, tok):
    """n_bars of M5 bid/ask candles from t0, paged (OANDA caps count at 500)."""
    out, cur, left = [], t0, int(n_bars)
    while left > 0:
        take = min(500, left)
        u = (f"{url}/v3/instruments/{pair}/candles?granularity=M5"
             f"&from={cur.strftime('%Y-%m-%dT%H:%M:%SZ')}&count={take}&price=BA")
        try:
            cs = json.load(urllib.request.urlopen(urllib.request.Request(
                u, headers={"Authorization": f"Bearer {tok}"}), timeout=25))["candles"]
        except Exception:
            break
        cs = [c for c in cs if c.get("complete", True)]
        if not cs:
            break
        out += cs
        left -= len(cs)
        if len(cs) < take:
            break                      # ran out of history (stamp near "now")
        cur = datetime.fromisoformat(cs[-1]["time"].replace("Z", "+00:00")) \
            + timedelta(minutes=5)
    return out


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
    # STILL OPEN AT THE HORIZON — the live ratchet has no timeout, so this is
    # not an outcome yet. The 2026-07-31 charter censored it here and dropped
    # the episode from every aggregate; measured 2026-08-06 that was discarding
    # 616 of 2240 episodes (27%), biased toward trades that merely DRIFTED
    # (neither stop nor trail), so any slow-moving setup could never accrue
    # evidence and looked dead. We now FOLLOW IT to a real exit, which is what
    # the live position would have done. MFE/MAE stay scoped to the horizon
    # window so the hit>=trig / hitSL columns keep their meaning.
    if o.exit_reason == "horizon":
        follow_bars = int(FOLLOW_MAX_DAYS * 24 * 60 / 5)
        ext_cs = _candles_ba(pair, t0, follow_bars, url, tok)
        ext = (simulate_shadow_exit(stamp, ext_cs, _pip(pair), max_bars=follow_bars)
               if len(ext_cs) > len(cs) else None)
        if ext is not None and ext.exit_reason != "horizon":
            return {"mv": 2, "net240": ext.net_pips, "mfe240": o.mfe_pips,
                    "mae240": o.mae_pips, "net60": None, "mfe60": None,
                    "mae60": None, "exit_reason": ext.exit_reason,
                    "exit_bar": ext.exit_bar, "ambiguous": ext.ambiguous_bar,
                    "followed": True, "follow_bars": ext.exit_bar,
                    "mfe_full": ext.mfe_pips, "mae_full": ext.mae_pips}
        # genuinely unresolved even after FOLLOW_MAX_DAYS — still censored
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

def _needs_score(ep, now) -> bool:
    """B-129: which episodes does a refresh (re)score?

    An episode used to be scored EXACTLY ONCE, minutes after its horizon — so
    the v6.24 "follow a still-open trade to its real exit (cap 5 days)" could
    only follow through candles that existed at that single moment. Any trade
    still drifting at score time was stamped censored:true and NEVER looked at
    again, silently re-creating the exact censoring bias v6.24 was built to
    kill (2,900+ censored episodes by 2026-08-16; 108 cells rendered as
    never-fired). Now: unscored episodes score at maturity as before, and
    CENSORED episodes are re-scored on every refresh until they resolve or
    their STAMP age truly exceeds FOLLOW_MAX_DAYS — then censored_final pins
    them and they are never fetched again."""
    sc = ep.get("scores")
    if sc is None:
        t0 = datetime.fromisoformat(ep["t"])
        mature_s = ((int(ep.get("horizon_min") or 240) + 5) * 60
                    if ep.get("mv") == 2 else _MATURE_S)
        return (now - t0).total_seconds() >= mature_s
    if sc.get("censored") and not sc.get("censored_final"):
        return True
    return False


def _refresh(max_new_scores=40):
    db = _load()
    eps = _fold_stamps(_stamps(), db["episodes"])
    now = datetime.now(timezone.utc)
    n_scored = 0
    # Fresh episodes first (never starved by the censored backlog), then
    # censored re-scores oldest-first, all within the same fetch budget.
    fresh = [(k, e) for k, e in eps.items()
             if e.get("scores") is None and _needs_score(e, now)]
    retry = sorted(((k, e) for k, e in eps.items()
                    if e.get("scores") is not None and _needs_score(e, now)),
                   key=lambda kv: kv[1]["t"])
    for ek, ep in fresh + retry:
        if n_scored >= max_new_scores: break
        t0 = datetime.fromisoformat(ep["t"])
        try:
            if ep.get("mv") == 2:
                ep["scores"] = _score_v2(ep, t0)
            else:
                ep["scores"] = _score(ep["cell"].split("/")[0], t0, ep["side"])
            sc = ep.get("scores") or {}
            if sc.get("censored") and                     (now - t0).total_seconds() >= FOLLOW_MAX_DAYS * 86400:
                sc["censored_final"] = True   # past cap — stop retrying
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
                                                       su.get("side", "?"),
                                                       su.get("wired"),
                                                       su.get("watch"))
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
        _full = json.loads(out.stdout)
        fams = {(r["instrument"], r.get("session", "?"), r["setup"]): r
                for r in _full.get("families", [])}
        _FAM_CACHE.update(ts=now, data=fams, full=_full)
    except Exception:
        _FAM_CACHE["ts"] = now          # don't hammer a failing audit
    return _FAM_CACHE["data"]


_VC_CACHE: dict = {"mtime": 0.0, "rows": {}, "t": None}


def _virtual_cycles():
    """data/virtual_cycles.json — batch virtual FAMILY-cycle scores
    (ops/virtual_scores.py, 6h cron). Stale >13h => served with stale flag."""
    f = _ROOT / "data" / "virtual_cycles.json"
    try:
        mt = f.stat().st_mtime
        if mt != _VC_CACHE["mtime"]:
            d = json.loads(f.read_text())
            _VC_CACHE.update(mtime=mt, rows=d.get("rows", {}), t=d.get("t"))
    except (OSError, ValueError):
        return {}, None, True
    stale = (time.time() - _VC_CACHE["mtime"]) > 13 * 3600
    return _VC_CACHE["rows"], _VC_CACHE["t"], stale


def broker_truth():
    """BROKER TRUTH scoreboard (2026-08-04, operator: "I need functional
    data"): one row per family that has EVER filled on the broker, every
    number derived from OANDA transaction-stream fills — realized $, pips,
    completed cycles, cycle win rate, worst/best cycle — plus an account
    reconciliation block proving the attribution covers every close the
    account realized in the window. Zero simulator content."""
    # CACHE-ONLY by design: the broker audit subprocess runs in the refresh
    # daemon (via _families() inside _aggregate), never in a request handler —
    # an empty result just means the first daemon refresh hasn't landed yet.
    full = _FAM_CACHE.get("full") or {}
    st_map = _config_status()
    out = []
    for f in full.get("families", []):
        cyc = f.get("cycles") or []
        cw = [c for c in cyc if (c.get("pips") or 0) > 0]
        by_usd = sorted((c for c in cyc if c.get("usd") is not None),
                        key=lambda c: c["usd"])
        stt = st_map.get((f["instrument"], f.get("session", "?"), f["setup"]))
        out.append({
            "cell": f'{f["instrument"]}/{f.get("session", "?")}',
            "setup": f["setup"],
            "status": stt[0] if stt else "RETIRED",
            "legs": f.get("n", 0),
            "parents": f.get("n_parents", 0),
            "poppers": f.get("n_poppers", 0),
            "leg_greens": f.get("greens", 0),
            "usd": f.get("usd"),
            "pips": f.get("pips"),
            "cycles": f.get("n_cycles", 0),
            "cycle_wr": (round(len(cw) / len(cyc), 3) if cyc else None),
            "avg_cycle_usd": (round(sum(c["usd"] for c in cyc) / len(cyc), 2)
                              if cyc else None),
            "worst_cycle_usd": by_usd[0]["usd"] if by_usd else None,
            "best_cycle_usd": by_usd[-1]["usd"] if by_usd else None,
            "avg_cycle_bps": f.get("cycle_bps"),
            "n_open": f.get("n_open", 0),
            "open_upl": f.get("open_upl"),
            "open_floor_usd": f.get("open_floor_usd"),
            # IN-PROGRESS CYCLE (2026-08-04, operator: a -$86 leg closed
            # mid-cycle and the row read like nothing happened): realized $
            # inside the current censored cycle = family total minus all
            # completed cycles. Only meaningful while legs are open.
            "open_cycle_usd": (round((f.get("usd") or 0)
                                     - sum(c.get("usd") or 0 for c in cyc), 2)
                               if f.get("n_open") else None),
            "last_close": max((c.get("end") or "" for c in cyc), default=None),
            "last_fill": max((t.get("ct") or "" for t in f.get("trades") or []),
                             default=None) or None,
        })
    out.sort(key=lambda r: r["usd"] if r["usd"] is not None else 0)
    tot = {"usd": round(sum(r["usd"] or 0 for r in out), 2),
           "pips": round(sum(r["pips"] or 0 for r in out), 1),
           "legs": sum(r["legs"] for r in out),
           "cycles": sum(r["cycles"] for r in out),
           "open": sum(r["n_open"] for r in out)}
    return {"since": full.get("since"), "rows": out, "totals": tot,
            "account": full.get("account"),
            "excluded_pre_era_closes": full.get("excluded_pre_era_closes")}


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
    if status in ("ACTIVE", "PROBE"):
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


def governor_sample(rows, era_start, cfg_hash):
    """FUNCTIONAL-DATA RULE (2026-08-04, operator): the board's stat columns
    must be computed on the EXACT sample the governor promotes on — current
    era, executable-exit-v2 only, mechanics matching the setup's current
    config. Lifetime blends (v1 frictionless + dead eras) made 15 of 174 rows
    show the WRONG SIGN vs governor evidence. Returns the filtered rows."""
    out = []
    for r in rows:
        sc = r.get("scores") or {}
        if sc.get("mv") != 2:
            continue
        if era_start and r["t"] < era_start:
            continue
        if cfg_hash and r.get("mech") and r["mech"] != cfg_hash:
            continue
        out.append(r)
    return out


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
    try:
        with open(_ROOT / "data" / "heat_scores.json") as _hf:
            _heat = json.load(_hf).get("scores", {})
    except (OSError, ValueError):
        _heat = {}
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
        from core.trial_evidence import current_era_evidence, required_bar
        from ops.governor import book as _gbook, cfg as _gcfg, \
            load_state as _gstate, _aliases as _gal, \
            family_era_view as _fview, active_verdict as _averdict
        _gc_full = _gcfg()
        _gst_full = _gstate() or {}
        _eras = _gst_full.get("era_start", {})
        _strk = _gst_full.get("demotion_counts", {})
        _bmap = _gbook()
        _ev = current_era_evidence(db["episodes"], _bmap, _gstate(),
                                   _gc_full, aliases=_gal())
        _gov_ok = True
    except Exception:
        _ev, _gc_full, _eras, _strk, _bmap = {}, dict(_gc), {}, {}, {}
    _fams = _families() if _gov_ok else {}
    _min_raw = int(_gc_full.get("min_raw_episodes", _gc_full.get("bar_n", 20)))
    for (cell, setup, side), g in groups.items():
        rows = g["rows"]
        pair = cell.split("/")[0]
        _sess0 = cell.split("/")[1] if "/" in cell else "?"
        # LIFETIME BLEND — research context ONLY (v1+v2, all eras). Shown in
        # tooltips, never in the stat columns.
        life_nets = [n for n in (episode_net(r["scores"]["net240"],
                                             r.get("spread"), pair,
                                             slippage_pips=_slip,
                                             executable=bool(r["scores"].get("mv") == 2))
                                 if r["scores"].get("net240") is not None else None
                                 for r in rows) if n is not None]
        # GOVERNOR-GRADE SAMPLE — what every visible stat column now uses.
        _meta_b = _bmap.get((pair, _sess0, setup)) if _gov_ok else None
        _era0 = (_eras.get("|".join((pair, _sess0, setup)),
                           str(_gc_full.get("default_era_start", "")))
                 if _gov_ok else "")
        grows = (governor_sample(rows, _era0,
                                 (_meta_b or {}).get("cfg_hash"))
                 if _gov_ok else rows)
        s = [r["scores"] for r in grows if r["scores"].get("net240") is not None]
        nets_all = [episode_net(x["net240"], r.get("spread"), pair,
                                slippage_pips=_slip,
                                executable=bool(x.get("mv") == 2))
                    for r, x in zip([r for r in grows
                                     if r["scores"].get("net240") is not None], s)]
        last7 = [net for r, net in zip([r for r in grows
                                        if r["scores"].get("net240") is not None],
                                       nets_all)
                 if net is not None and r["t"] >= cutoff7]
        nets = [n for n in nets_all if n is not None]   # censored excluded
        # B-130: a group whose every episode is still censored used to emit NO
        # row — the board then backfilled a QUEUED "no scored episodes yet"
        # placeholder, rendering 108 cells (566 real stamps) as never-fired.
        # Stamped-but-unresolved must read as RESOLVING, never as absence.
        avg = (sum(nets) / len(nets)) if nets else None
        n_eff = effective_n([r["t"] for r in grows]) if grows else None
        lcb = _tlcb(nets, n_eff, _z) if nets else None
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
        _sess = cell.split("/")[1] if "/" in cell else "?"
        # STRIKE RULE: lifetime demotion count — permanent, raises the bar
        _stk_n = int(_strk.get("|".join((pair, _sess, setup)), 0))
        _vc_rows, _vc_t, _vc_stale = _virtual_cycles()
        _vc = _vc_rows.get("|".join((cell, setup, side)))
        if _vc is not None:
            _vc = dict(_vc, stale=_vc_stale)
        era = None
        if _e:
            _rq = required_bar(_gc_full, _stk_n)
            era = {"n": _e.raw_n, "days": _e.independent_days,
                   "avg": _e.net_avg, "lcb": _e.block_lcb, "q": _e.q_value,
                   "promotable": _e.promotable,
                   "req_n": _rq[0], "req_days": _rq[1],
                   "codes": list(_e.reason_codes)}
        # THE GOVERNOR'S OWN VIEW (v6.8.0): each row carries the verdict the
        # governor would reach today — family rule, judge-when-flat, promotion
        # predicate — plus the tier that orders the board exactly as capital
        # moves. Best seats at the top, demote-due at the bottom.
        _te, _td = _hit_thresholds(_geo, pair,
                                   cell.split("/")[1] if "/" in cell else "?", setup)
        gov = None
        if _gov_ok and _status in ("ACTIVE", "PROBE", "SHADOW"):
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
        # TRUTH CHECK vs the FULL broker window (not the era view — a
        # demotion resets the era clock, but real fills stay real).
        _fam_full = _fams.get((pair, _sess, setup)) or {}
        _tc_agree = (
            ((_vc.get("net_mean") or 0) > 0) == ((_fam_full.get("usd") or 0) > 0)
            if (_vc and _vc.get("cycles") and (_fam_full.get("n") or 0) > 0)
            else None)
        # MIRROR of the governor's truth_check_gate: the board must never
        # award PROMOTE READY to a cell the gate would block.
        if gov and _tc_agree is False and gov.get("verdict") == "PROMOTE READY":
            gov["verdict"] = "TRUTH BLOCKED"
            gov["reason"] = ("virtual family sim contradicts this cell's own "
                             "broker fills — promotion gated (truth_check_gate); "
                             + (gov.get("reason") or ""))
        out.append({
            "cell": cell, "setup": setup, "side": side,
            "status": _status,
            "watch": (_st[3] if _st and len(_st) > 3 else None),
            "strikes": _stk_n,
            # ALL stat columns: governor-grade sample (current era, v2,
            # mechanics-matched, net-of-cost). None = no such evidence yet.
            "episodes": len(nets),
            "cum_net240": round(sum(nets), 1) if nets else None,
            "avg_net240": round(avg, 2) if avg is not None else None,
            "lcb": lcb,
            "wr": (round(sum(1 for n in nets if n > 0)/len(nets), 3)
                   if nets else None),
            # hit_eng / hit_sl (2026-07-30, Brock): the two events that decide
            # a trade's fate, on the setup's OWN config geometry. Engage locks
            # +6 and cannot lose; death eats the full stop. At lock 6 / SL 60
            # one death costs ten engages — the pair of columns IS the
            # breakeven math. (hit>=6p retired: it measured the lock level and
            # flattered almost-winners — rvol_low_240_t20s touched +6p in 61%
            # of episodes, reached its 20p trigger in 17%.)
            "hit_eng": (round(sum(1 for x in s if x["mfe240"] >= _te)/len(s), 3)
                        if s else None),
            "hit_sl": (round(sum(1 for x in s if x["mae240"] >= _td)/len(s), 3)
                       if s else None),
            "med_mfe": (round(st.median(x["mfe240"] for x in s), 1)
                        if s else None),
            "med_mae": (round(st.median(x["mae240"] for x in s), 1)
                        if s else None),
            # net60 exists only on legacy-mid-v1 scores (v2 exits when the
            # SETUP says, not at a fixed 60m checkpoint)
            "avg_net60": (round(sum(_n60)/len(_n60), 2)
                          if (_n60 := [x["net60"] for x in s
                                       if x.get("net60") is not None]) else None),
            "n_v2": len(s),
            "n_censored": sum(1 for r in grows if r["scores"].get("censored")),
            "n_ambig": sum(1 for x in s if x.get("ambiguous")),
            # LIFETIME BLEND — context only, never decisions: all eras, both
            # metric versions. This is what the columns used to show and why
            # 15 rows had the wrong sign.
            "life": {"n": len(life_nets), "stamps": len(rows),
                     "avg": round(sum(life_nets)/len(life_nets), 2) if life_nets else None,
                     "cum": round(sum(life_nets), 1) if life_nets else None,
                     "wr": (round(sum(1 for n in life_nets if n > 0)
                                  / len(life_nets), 3) if life_nets else None),
                     "v1_n": sum(1 for r in rows
                                 if r["scores"].get("mv") != 2)},
            "last7_avg": round(sum(last7)/len(last7), 2) if last7 else None,
            "last7_n": len(last7),
            "n_eff": n_eff,
            "first": min(r["t"] for r in rows)[:10],
            # D-7: the trophy equals the governor's promotion predicate
            # EXACTLY (current-era v2 evidence, block bootstrap, FDR) —
            # the board can never award what the governor would reject.
            "era": era,
            # VIRTUAL FAMILY CYCLES — the best forward metric for shadows
            # (parent + popper grid over real candles). Validation 2026-08-04:
            # broker sign agreement 5/10 vs the parent/horizon sim's 3/10 —
            # residual gap is the live-selection effect (charter defect #6),
            # so any cell where BROKER data contradicts the sim gets flagged.
            "vc": _vc,
            # None = no broker evidence; False = sim contradicts real fills
            # (drives the ❌ badge AND the governor's truth_check_gate).
            "vc_broker_agree": _tc_agree,
            "bar_met": bool(era and era["promotable"]),
            "gov": gov,
            "ht": _heat.get("|".join((pair,
                                      cell.split("/")[1] if "/" in cell else "?",
                                      setup))),
        })
    # QUEUED rows (2026-07-27, Brock: "I don't see the new pairs on the board"):
    # every wired ACTIVE/SHADOW setup with zero scored episodes still gets a
    # row, so the docket is visible — waiting is a state, not an absence.
    have = {(r["cell"], r["setup"]) for r in out}
    for (pair, sess, sid), (status, side, *_x) in _cfgst.items():
        _watch = _x[1] if len(_x) > 1 else None
        cell = f"{pair}/{sess}"
        if status in ("ACTIVE", "PROBE", "SHADOW") and (cell, sid) not in have:
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
                "watch": _watch,
                "episodes": 0, "cum_net240": None, "avg_net240": None,
                "lcb": None, "wr": None, "hit_eng": None, "hit_sl": None,
                "med_mfe": None,
                "med_mae": None, "avg_net60": None, "n_v2": 0, "n_ambig": 0,
                "last7_avg": None, "era": None,
                "last7_n": 0, "first": None, "bar_met": False, "queued": True,
                "wired": (_cfgst.get((pair, sess, sid)) or (None, None, None))[2]
                if len(_cfgst.get((pair, sess, sid)) or ()) > 2 else None,
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

_REFRESHING = {"on": False, "since": 0.0}

def _refresh_worker():
    """Runs in a daemon thread — never inside a dashboard request."""
    try:
        db = _refresh()
        rows = _aggregate(db)
        active = [r["avg_net240"] for r in rows
                  if r["status"] == "ACTIVE" and r["avg_net240"] is not None]
        # enhanced dashboard (2026-07-31): board-level EVIDENCE ACCOUNTING +
        # RISK TRUTH + FRESHNESS — TradeClaw-inspired, Scrooge-native units
        _n_cens = sum(r.get("n_censored") or 0 for r in rows)
        _n_eps = sum(r.get("episodes") or 0 for r in rows)
        _fam_open = [r for r in rows
                     if r.get("gov") and (r["gov"].get("family") or {}).get("n_open")]
        _floor = sum((r["gov"]["family"].get("open_floor_usd") or 0)
                     for r in _fam_open
                     if isinstance(r["gov"]["family"].get("open_floor_usd"),
                                   (int, float)))
        _cyc_total = sum(((r.get("gov") or {}).get("family") or {}).get("n_cycles") or 0
                         for r in rows if r.get("gov"))
        try:
            _heat_age_s = time.time() - os.path.getmtime(_ROOT / "data" / "heat_scores.json")
        except OSError:
            _heat_age_s = None
        _meta = {"episodes_total": _n_eps, "episodes_censored": _n_cens,
                 "family_cycles_completed": _cyc_total,
                 "families_open": len(_fam_open),
                 "open_floor_usd": round(_floor, 2),
                 "heat_age_s": (round(_heat_age_s) if _heat_age_s is not None
                                else None)}
        # 24h MOVERS (audit enhancement 2026-08-19): tier changes vs a rolling
        # baseline so promotions/demotions/at-the-gates motion reads at a
        # glance. Baseline resets when older than 24h.
        movers, movers_since = [], None
        try:
            _bl_path = _ROOT / "data" / "board_tier_baseline.json"
            _cur = {f"{r['cell']}|{r['setup']}": (r.get("gov") or {}).get("tier", 7)
                    for r in rows}
            _bl = json.loads(_bl_path.read_text()) if _bl_path.exists() else None
            if _bl and time.time() - _bl.get("ts", 0) <= 86400:
                movers_since = _bl.get("iso")
                for _k, _tn in _cur.items():
                    _to = _bl.get("tiers", {}).get(_k)
                    if _to is not None and _to != _tn:
                        _cell, _setup = _k.split("|", 1)
                        movers.append({"cell": _cell, "setup": _setup,
                                       "from": _to, "to": _tn})
                movers.sort(key=lambda m: (m["to"] - m["from"]))
            else:
                _bl_path.write_text(json.dumps(
                    {"ts": time.time(),
                     "iso": datetime.now(timezone.utc).isoformat(),
                     "tiers": _cur}))
                movers_since = None
        except Exception:
            pass
        data = {"rows": rows,
                "movers": movers, "movers_since": movers_since,
                "meta": _meta,
                "tiers": TIER_LABELS,
                "active_median": round(sorted(active)[len(active)//2], 2) if active else None,
                "pending": sum(1 for e in db["episodes"].values() if not e["scores"]),
                "generated": datetime.now(timezone.utc).isoformat()}
        with _LOCK:
            _CACHE.update(ts=time.time(), data=data)
    except Exception:
        # B-133: a bare pass here hid every failure while the board silently
        # served stale rows. Crashes now land in the journal.
        import sys as _s, traceback as _tb
        print("[shadowboard] refresh worker crashed:\n" + _tb.format_exc(),
              file=_s.stderr, flush=True)
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
    if stale:
        _now = time.time()
        _hung = (_REFRESHING["on"] and _REFRESHING["since"]
                 and _now - _REFRESHING["since"] > _LATCH_TIMEOUT_S)
        if not _REFRESHING["on"] or _hung:
            if _hung:
                import sys as _s
                print(f"[shadowboard] B-133: refresh latch held past its "
                      f"{_LATCH_TIMEOUT_S}s lease - presuming the worker "
                      "dead/hung and starting a new one",
                      file=_s.stderr, flush=True)
            _REFRESHING["on"] = True
            _REFRESHING["since"] = _now
            threading.Thread(target=_refresh_worker, daemon=True, name="shadowboard-refresh").start()
    if data is None:
        return {"rows": [], "active_median": None, "pending": None,
                "generated": None, "building": True}
    try:
        _overlay_live_status(data)   # B-113: status is always live truth
    except Exception:
        pass
    return data
