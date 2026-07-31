#!/usr/bin/env python3
"""research/tools/delta_hot_walkforward.py — THE pre-registered experiment
(charter, 2026-07-31).

The adaptive governor's central hypothesis, stated falsifiably:

    Recent cell-family performance predicts its next family outcome.

Test: walk every virtual family cycle in time order. At each cycle's START,
compute each cell's Heat (2-day half-life two-speed score) using ONLY cycles
that COMPLETED strictly before that moment. Rank cells with history into
quartiles. Then:

    Delta_hot = E[U_next | top heat quartile] - E[U_next | everyone else]

Positive and stable across the walk => rotation is edge. Zero or negative =>
the Heat/Trust governor is a story, and the fixed book wins. Benchmarks
reported alongside: hot-book (top-K by heat), random-K (seeded), equal-weight,
controls-only (setup id contains "control").

Dataset: virtual FAMILY_PP cycles via core/family_cycle over M5 bid/ask
candles, cached in data/walkforward_cycles.json (delete to rebuild).
All rankings use only information available before the next cycle begins.

Usage: delta_hot_walkforward.py [--since ISO] [--min-eps 3] [--limit 12]
                                [--top-k 4] [--seed 7] [--rebuild]
"""
import argparse, json, math, random, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from core.family_cycle import replay_family_cycle, two_speed_score, HEAT_HALF_LIFE_D
import research.tools.family_cycle_replay as fcr
from research.tools.cell_setup_score import collapse_episodes

CACHE = REPO / "data" / "walkforward_cycles.json"


def build_dataset(since, min_eps, limit, max_days):
    db = json.load(open(REPO / "data" / "shadowboard.json"))
    eps = {}
    for e in db["episodes"].values():
        t = datetime.fromisoformat(e["t"])
        if t < since:
            continue
        pair, _, sess = e["cell"].partition("/")
        eps.setdefault((pair, sess, e["setup"], e["side"]), []).append(t)
    out = {}
    now = datetime.now(timezone.utc)
    todo = [(k, sorted(v)) for k, v in eps.items() if len(v) >= min_eps]
    print(f"dataset: {len(todo)} cells with >= {min_eps} stamps", file=sys.stderr)
    db_full = json.load(open(REPO / "data" / "shadowboard.json"))
    for n_done, ((pair, sess, sid, side), ts) in enumerate(sorted(todo)):
        recs = fcr.episode_records(db_full, pair, sess, sid)[-limit:]
        if len(recs) < min_eps:
            continue
        gear0, pp = fcr._setup_exit(pair, sess, sid), fcr._pp()
        rows = []
        for rec in recs:
            t = rec["t"]
            gear = dict(rec.get("exit_config") or gear0)
            gear.setdefault("step_size_pips", 2.0)
            gear.setdefault("step_cadence_min", 0.5)
            t1 = min(t + timedelta(days=max_days), now)
            bars = fcr._ba_candles(pair, t, t1)
            if len(bars) < 3:
                continue
            r = replay_family_cycle(bars, side, fcr.PIP(pair), gear, pp, "FAMILY_PP",
                                    entry_px=rec.get("entry"))
            if r is None or r.censored:
                continue
            liab = max(r.peak_liability_pips, 1.0)
            rows.append({"t": t.isoformat(),
                         "end": (t + timedelta(minutes=r.duration_min)).isoformat(),
                         "U": round(r.net_pips / liab, 4), "net": r.net_pips})
        if rows:
            out["|".join((pair, sess, sid, side))] = rows
        if (n_done + 1) % 10 == 0:
            print(f"  {n_done + 1}/{len(todo)} cells replayed", file=sys.stderr)
    return out


def walkforward(ds, top_k, seed):
    events = []           # (start_dt, key, U)
    hist = {}             # key -> [(end_dt, U)] completed
    for key, rows in ds.items():
        for r in rows:
            events.append((datetime.fromisoformat(r["t"]), key,
                           datetime.fromisoformat(r["end"]), r["U"]))
    events.sort(key=lambda x: x[0])
    completed = []        # (end_dt, key, U) — appended as time passes
    recs = []
    rng = random.Random(seed)
    for start, key, end, u in events:
        # heat for every key from cycles completed strictly before `start`
        heats = {}
        for k2 in ds:
            evs = [(e, uu) for e, k3, uu in completed if k3 == k2 and e < start]
            if evs:
                heats[k2] = two_speed_score(evs, start, HEAT_HALF_LIFE_D)["score"]
        if key in heats and len(heats) >= 4:
            ranked = sorted(heats, key=lambda k2: -(heats[k2] or 0))
            q = ranked.index(key) / len(ranked)          # 0 = hottest
            top_cut = max(1, len(ranked) // 4)
            recs.append({"t": start.isoformat(), "key": key, "U": u,
                         "hot": key in ranked[:top_cut],
                         "hot_book": key in ranked[:top_k],
                         "rand_book": key in rng.sample(list(heats), min(top_k, len(heats))),
                         "control": "control" in key})
        completed.append((end, key, u))
    return recs


def summarize(recs):
    def mean(xs):
        return sum(xs) / len(xs) if xs else None
    hot = [r["U"] for r in recs if r["hot"]]
    rest = [r["U"] for r in recs if not r["hot"]]
    out = {
        "n_events_ranked": len(recs),
        "delta_hot": (round(mean(hot) - mean(rest), 4)
                      if hot and rest else None),
        "U_top_quartile": round(mean(hot), 4) if hot else None,
        "n_top": len(hot),
        "U_rest": round(mean(rest), 4) if rest else None,
        "books": {
            "hot_topK": round(mean([r["U"] for r in recs if r["hot_book"]]) or 0, 4),
            "random_K": round(mean([r["U"] for r in recs if r["rand_book"]]) or 0, 4),
            "equal_weight": round(mean([r["U"] for r in recs]) or 0, 4),
            "controls_only": (round(mean([r["U"] for r in recs if r["control"]]), 4)
                              if any(r["control"] for r in recs) else None),
        },
    }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-07-04T00:00:00")
    ap.add_argument("--min-eps", type=int, default=3)
    ap.add_argument("--limit", type=int, default=12)
    ap.add_argument("--max-days", type=float, default=2.5)
    ap.add_argument("--top-k", type=int, default=4)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--rebuild", action="store_true")
    args = ap.parse_args()
    since = datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc)
    if CACHE.exists() and not args.rebuild:
        ds = json.loads(CACHE.read_text())
        print(f"dataset: cache hit ({len(ds)} cells) — --rebuild to refresh",
              file=sys.stderr)
    else:
        ds = build_dataset(since, args.min_eps, args.limit, args.max_days)
        CACHE.write_text(json.dumps(ds))
        print(f"dataset: built + cached ({len(ds)} cells)", file=sys.stderr)
    recs = walkforward(ds, args.top_k, args.seed)
    print(json.dumps(summarize(recs), indent=1))


if __name__ == "__main__":
    main()
