#!/usr/bin/env python3
"""research/tools/regear_rescore_2026-08-25.py — the honest backfill after the
v6.32.0 gear unification (operator: "back fill the data for the shadows and
probes that got lost").

The unify reset 1,169 era clocks (correct: old-gear scores don't describe
7.5/6.0 behavior), emptying the promotion samples. But the STAMPS are gear-
independent entries with real forward paths — so the evidence is
reconstructed honestly by re-replaying every in-scope episode under the
setup's CURRENT (unified two-phase) exit geometry: same entries, same
bid/ask paths, new mechanics. Each rescored episode is flagged
"regear": "2026-08-25" for provenance. Era clocks are then restored from the
pre-unify backup (explicit entries) or fall back to default_era_start — the
sample they gate is now mechanics-matched to the live book.

Scope: v2-replayable episodes (entry + exit_config present), stamped before
the unify, at/after the cell's restored era start. `_t20s` cells are skipped
entirely (gear unchanged; scores remain valid; eras untouched by the unify).

RUN WITH THE TRADER STOPPED (shares data/shadowboard.json with the daemon).
Usage: python3 regear_rescore_2026-08-25.py [--dry-run] [--threads 6]
"""
from __future__ import annotations
import argparse, json, os, sys, tempfile, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
import ops.shadowboard as sb

DB = REPO / "data" / "shadowboard.json"
GS = REPO / "data" / "governor_state.json"
PRE = Path("/tmp/gov_state_preunify.json")
UNIFY_TS = "2026-08-24T18:30"


def atomic_write(path, obj):
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(obj, f)
    os.replace(tmp, path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--threads", type=int, default=6)
    args = ap.parse_args()

    pre_eras = json.loads(PRE.read_text())["era_start"]
    gc = json.loads((REPO / "config" / "governor_config.json").read_text())
    default_era = str(gc.get("default_era_start", "2026-07-19"))[:19]

    exits = {}
    for f in (REPO / "config" / "cells").glob("*.json"):
        cfg = json.loads(f.read_text())
        for sess, b in (cfg.get("sessions") or {}).items():
            for s in (b.get("setups") or []):
                if "_t20s" in str(s.get("id", "")):
                    continue
                if isinstance(s.get("exit"), dict):
                    exits[(cfg.get("pair", f.stem), sess, s["id"])] = s["exit"]

    db = json.loads(DB.read_text())
    eps = db["episodes"]
    todo = []
    for k, e in eps.items():
        setup = str(e.get("setup", ""))
        if "_t20s" in setup:
            continue
        if str(e.get("t", ""))[:16] >= UNIFY_TS:
            continue                      # stamped under the new gear already
        if e.get("entry") is None or not isinstance(e.get("exit_config"), dict):
            continue                      # legacy-v1: not exec-replayable
        try:
            pair, sess = e["cell"].split("/", 1)
        except ValueError:
            continue
        key = "|".join((pair, sess, setup))
        era = str(pre_eras.get(key, default_era))[:19]
        if str(e.get("t", ""))[:19] < era:
            continue                      # outside the restored era sample
        cur_exit = exits.get((pair, sess, setup))
        if cur_exit is None:
            continue                      # shed/unknown setup
        todo.append((k, cur_exit))

    print(f"in-scope episodes to regear-rescore: {len(todo)}", flush=True)
    if args.dry_run:
        return

    bak = DB.with_name("shadowboard.json.pre-regear-20260825")
    if not bak.exists():
        bak.write_text(DB.read_text())
        print(f"backup written: {bak.name}", flush=True)

    def work(item):
        k, cur_exit = item
        e = dict(eps[k])
        e["exit_config"] = dict(cur_exit)
        try:
            s = sb._score_v2(e, datetime.fromisoformat(eps[k]["t"]))
        except Exception:
            return k, None, None
        return k, s, dict(cur_exit)

    done = ok = failed = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.threads) as ex:
        futs = [ex.submit(work, it) for it in todo]
        for fut in as_completed(futs):
            k, s, cx = fut.result()
            done += 1
            if s is not None:
                eps[k]["scores"] = s
                eps[k]["exit_config"] = cx
                eps[k]["regear"] = "2026-08-25"
                ok += 1
            else:
                failed += 1
            if done % 200 == 0 or done == len(todo):
                atomic_write(DB, db)
                print(f"  {done}/{len(todo)} ok={ok} failed={failed} "
                      f"{(time.time()-t0)/60:.1f}min", flush=True)
    atomic_write(DB, db)

    gs = json.loads(GS.read_text())
    eras = gs.get("era_start", {})
    restored = dropped = 0
    for key, val in list(eras.items()):
        if str(val)[:10] == "2026-08-24":
            if key in pre_eras:
                eras[key] = pre_eras[key]
                restored += 1
            else:
                del eras[key]
                dropped += 1
    atomic_write(GS, gs)
    print(f"eras: restored {restored} explicit, dropped {dropped} to default "
          f"({default_era[:10]})", flush=True)
    print(f"DONE ok={ok} failed={failed} in {(time.time()-t0)/60:.1f}min", flush=True)


if __name__ == "__main__":
    main()
