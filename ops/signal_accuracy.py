"""ops/signal_accuracy.py — grade the Signal Command Center's consensus calls
against forward executable price (cron hourly, 2026-08-27).

Episode rule: consecutive same-direction snapshot rows for one pair with gaps
≤ GAP_S form ONE consensus episode; the FIRST row is the scored call. Scoring
every row would grade the same market move many times over (overlapping
samples); scoring the first answers the question a manual trader actually
asks — "consensus just appeared: is it right?". max_conf/n_snaps are kept per
episode for later analysis.

Scoring (honest, D-7 style):
  entry  = first complete M5 candle at/after the call — ASK open for LONG,
           BID open for SHORT (the executable side; ~1-4 min after the board
           shows the call, which is what a human acting on it would get)
  p30/p60/p120/p240/p480 = signed pips at the close of the Nth trading bar
           after entry, exiting on the OPPOSITE side (spread honestly paid).
           Checkpoints index TRADING bars, so a Friday-late call scores
           across the weekend gap in bar-time, same as the shadow sim.
  No censoring class: a checkpoint that lacks bars yet simply stays unscored
  until the bars exist (B-129 lesson — wait, never discard). Episodes with no
  candles after MAX_AGE_D days are marked dead ("no_data").

Aggregates (rebuilt every run, CURRENT formula hash only — a formula change
starts a fresh sample): overall + per confidence band + per pair×direction,
each with n / hit-rate / avg pips per checkpoint. data/signal_accuracy.json
is served by GET /api/signal_accuracy and rendered on /signals.

The calls file is pruned of rows older than PRUNE_DAYS (episodes are long
since assembled and scored by then; the scored record lives in the store).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

CALLS = _ROOT / "data" / "signal_calls.jsonl"
STORE = _ROOT / "data" / "signal_accuracy.json"

GAP_S = 15 * 60            # snapshot gap that splits a consensus episode
CKPTS = (30, 60, 120, 240, 480)   # minutes after entry (trading bars × 5m)
PRUNE_DAYS = 7
MAX_AGE_D = 3              # no candles after this ⇒ dead episode
BANDS = ((0, 25), (25, 50), (50, 75), (75, 101))


def _pip(pair: str) -> float:
    return 0.01 if "JPY" in pair else 0.0001


def _parse_ts(s: str) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def load_calls(path: Path = CALLS) -> list:
    rows = []
    try:
        for ln in path.read_text().splitlines():
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            t = _parse_ts(r.get("ts", ""))
            if t is None or r.get("dir") not in ("LONG", "SHORT"):
                continue
            r["_t"] = t
            rows.append(r)
    except OSError:
        pass
    rows.sort(key=lambda r: (r["pair"], r["_t"]))
    return rows


def assemble_episodes(rows: list) -> dict:
    """episode_id -> call record. First row of a run is the call; later rows
    only update n_snaps / max_conf / last_ts."""
    eps: dict = {}
    cur_ep = None
    for r in rows:
        new_run = (
            cur_ep is None
            or r["pair"] != cur_ep["pair"]
            or r["dir"] != cur_ep["dir"]
            or (r["_t"] - cur_ep["_last"]).total_seconds() > GAP_S
        )
        if new_run:
            eid = "%s|%s|%s" % (r["pair"], r["dir"], r["_t"].isoformat())
            cur_ep = {
                "id": eid, "pair": r["pair"], "dir": r["dir"],
                "ts": r["_t"].isoformat(), "_last": r["_t"],
                "conf": r.get("conf"), "net": r.get("net"),
                "agree": r.get("agree"), "dist": r.get("dist"),
                "hold_min": r.get("hold_min"), "n_sig": r.get("n_sig"),
                "fhash": r.get("fhash"),
                "n_snaps": 1, "max_conf": r.get("conf") or 0,
            }
            eps[eid] = cur_ep
        else:
            cur_ep["_last"] = r["_t"]
            cur_ep["n_snaps"] += 1
            if (r.get("conf") or 0) > cur_ep["max_conf"]:
                cur_ep["max_conf"] = r.get("conf") or 0
    for ep in eps.values():
        ep["last_ts"] = ep.pop("_last").isoformat()
    return eps


def _fetch_candles(pair: str, t0: datetime, n_bars: int) -> list:
    """M5 bid/ask candles from t0 — one implementation, reused from the
    shadowboard scorer (find the real tool, don't rebuild it)."""
    from ops.shadowboard import _candles_ba, _creds
    url, tok = _creds()
    return _candles_ba(pair, t0, n_bars, url, tok)


def score_episode(ep: dict, candles: list) -> dict:
    """Fill in every checkpoint the candle path can already answer.
    Returns {} when no entry bar exists yet."""
    t0 = _parse_ts(ep["ts"])
    entry_i = None
    for i, c in enumerate(candles):
        ct = _parse_ts(str(c.get("time", "")).replace("Z", "+00:00"))
        if ct is not None and ct >= t0 and c.get("complete", True):
            entry_i = i
            break
    if entry_i is None:
        return {}
    long_side = ep["dir"] == "LONG"
    try:
        entry = float(candles[entry_i]["ask" if long_side else "bid"]["o"])
    except (KeyError, TypeError, ValueError):
        return {}
    pip = _pip(ep["pair"])
    out = {"entry": entry, "entry_time": candles[entry_i].get("time")}
    for ck in CKPTS:
        j = entry_i + ck // 5 - 1
        if j >= len(candles) or j < entry_i:
            continue                      # bars don't exist yet — wait
        try:
            exit_px = float(candles[j]["bid" if long_side else "ask"]["c"])
        except (KeyError, TypeError, ValueError):
            continue
        pips = (exit_px - entry) / pip if long_side else (entry - exit_px) / pip
        out["p%d" % ck] = round(pips, 1)
    return out


def _summ(vals: list) -> dict:
    n = len(vals)
    if not n:
        return {"n": 0, "hit": None, "avg": None}
    return {"n": n,
            "hit": round(sum(1 for v in vals if v > 0) / n, 3),
            "avg": round(sum(vals) / n, 2)}


def aggregates(eps: dict, fhash: str) -> dict:
    sel = [e for e in eps.values()
           if e.get("fhash") == fhash and e.get("scores")]
    ck_keys = ["p%d" % c for c in CKPTS]

    def block(group):
        out = {}
        for k in ck_keys:
            out[k] = _summ([e["scores"][k] for e in group if k in e["scores"]])
        return out

    bands = {}
    for lo, hi in BANDS:
        grp = [e for e in sel if lo <= (e.get("conf") or 0) < hi]
        bands["%d-%d" % (lo, min(hi, 100))] = dict(block(grp), n_calls=len(grp))
    pairs: dict = {}
    for e in sel:
        d = pairs.setdefault(e["pair"], {"n_calls": 0, "dirs": {}})
        d["n_calls"] += 1
        dd = d["dirs"].setdefault(e["dir"], [])
        dd.append(e)
    for p, d in pairs.items():
        d["dirs"] = {dr: dict(block(grp), n_calls=len(grp))
                     for dr, grp in d["dirs"].items()}
    return {"n_calls": len(sel), "checkpoints": block(sel),
            "bands": bands, "pairs": pairs}


def run(now: Optional[datetime] = None, fetch=None, calls_path: Path = CALLS,
        store_path: Path = STORE) -> dict:
    from ops.signal_center import formula_hash
    now = now or datetime.now(timezone.utc)
    fetch = fetch or _fetch_candles
    try:
        store = json.loads(store_path.read_text())
    except (OSError, ValueError):
        store = {}
    episodes: dict = store.get("episodes", {})

    fresh = assemble_episodes(load_calls(calls_path))
    for eid, ep in fresh.items():
        old = episodes.get(eid)
        if old:                          # keep scores; refresh run metadata
            for k in ("n_snaps", "max_conf", "last_ts"):
                old[k] = ep[k]
        else:
            episodes[eid] = ep

    scored = dead = 0
    for eid, ep in episodes.items():
        if ep.get("dead"):
            continue
        have = ep.get("scores") or {}
        pending = [c for c in CKPTS if "p%d" % c not in have]
        if not pending:
            continue
        t0 = _parse_ts(ep["ts"])
        age_min = (now - t0).total_seconds() / 60.0
        # earliest pending checkpoint can't have bars yet ⇒ skip quietly
        if age_min < min(pending) + 10:
            continue
        want_bars = min(CKPTS[-1], int(age_min)) // 5 + 3
        candles = fetch(ep["pair"], t0, want_bars)
        s = score_episode(ep, candles)
        if s:
            have.update(s)
            ep["scores"] = have
            scored += 1
        elif age_min > MAX_AGE_D * 1440:
            ep["dead"] = "no_data"
            dead += 1

    fh = formula_hash()
    store = {
        "generated_at": now.isoformat(),
        "formula_hash": fh,
        "gap_s": GAP_S, "checkpoints": list(CKPTS),
        "episodes": episodes,
        "aggregates": aggregates(episodes, fh),
    }
    tmp = tempfile.NamedTemporaryFile(
        "w", dir=str(store_path.parent), delete=False, suffix=".tmp")
    with tmp:
        json.dump(store, tmp, separators=(",", ":"))
    os.replace(tmp.name, store_path)

    # prune the calls file (the scored record lives in the store); a row we
    # cannot parse is kept — pruning must never be the thing that eats data
    try:
        cutoff = now - timedelta(days=PRUNE_DAYS)
        keep = []
        for ln in calls_path.read_text().splitlines():
            t = None
            try:
                t = _parse_ts(json.loads(ln).get("ts", ""))
            except (ValueError, AttributeError):
                pass
            if t is None or t >= cutoff:
                keep.append(ln)
        ctmp = calls_path.with_suffix(".tmp")
        ctmp.write_text("\n".join(keep) + ("\n" if keep else ""))
        os.replace(ctmp, calls_path)
    except OSError:
        pass
    return {"episodes": len(episodes), "scored_now": scored, "dead_now": dead,
            "n_calls_current_formula": store["aggregates"]["n_calls"]}


if __name__ == "__main__":
    print("signal_accuracy:", json.dumps(run()))
