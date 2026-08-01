#!/usr/bin/env python3
"""research/tools/delta_promotion.py — THE selector-validation metric
(external-repo audit, 2026-07-31):

    Δ_promotion = E[R_next broker cycle | promoted]
                − E[R_next broker cycle | eligible but not promoted]

Measures whether the cheater selector ADDS VALUE over its own eligibility
pool — not whether promoted cells had pretty replay scores. Reads the
prospective snapshots (data/score_snapshots.jsonl, written at decision time,
hindsight-proof) and joins each snapshot to the setup's NEXT completed
broker family cycle (broker_setup_audit cycles, R = pips/60).

Prints n/means/delta; refuses to print a verdict below --min-n per arm.
Run after real commissioned history accrues; empty output today is correct.
"""
import argparse, json, subprocess, sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
R_PIPS = 60.0


def broker_cycles():
    out = subprocess.run(
        [sys.executable, str(REPO / "research" / "tools" / "broker_setup_audit.py"),
         "--since", "2026-07-29T11:00:00Z", "--json"],
        capture_output=True, text=True, timeout=300)
    fams = json.loads(out.stdout).get("families", [])
    cyc = {}
    for f in fams:
        key = f"{f['instrument']}|{f.get('session', '?')}|{f['setup']}"
        cyc[key] = sorted((c["start"], c["end"], c["pips"] / R_PIPS)
                          for c in f.get("cycles", []))
    return cyc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-n", type=int, default=5)
    args = ap.parse_args()
    snaps = []
    try:
        for ln in open(REPO / "data" / "score_snapshots.jsonl"):
            snaps.append(json.loads(ln))
    except OSError:
        print("no snapshots yet — accrues from governor runs")
        return
    cyc = broker_cycles()
    arms = {"promoted": [], "eligible_not": []}
    for s in snaps:
        if not s.get("eligible"):
            continue
        nxt = next((r for st, _, r in cyc.get(s["key"], [])
                    if st > s["t"][:16]), None)
        if nxt is None:
            continue
        arms["promoted" if s.get("promoted") else "eligible_not"].append(nxt)
    for arm, vals in arms.items():
        print(f"{arm}: n={len(vals)} "
              f"mean_R={sum(vals)/len(vals):+.3f}" if vals else f"{arm}: n=0")
    if all(len(v) >= args.min_n for v in arms.values()):
        d = (sum(arms["promoted"]) / len(arms["promoted"])
             - sum(arms["eligible_not"]) / len(arms["eligible_not"]))
        print(f"Δ_promotion = {d:+.3f} R/cycle")
    else:
        print(f"verdict withheld: need >= {args.min_n} joined outcomes per arm")


if __name__ == "__main__":
    main()
