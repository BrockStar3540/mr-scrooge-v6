#!/usr/bin/env python3
"""research/tools/parity_check.py — V5-live vs V6-shadow decision parity.

Compares CYCLE lines (intent sets + picked) from the two journals over a
window. V6 must decide identically to V5 before it may go live. Exit behavior
is not comparable (shadow places nothing) — this checks the DECISION layer.

Usage:  python3 research/tools/parity_check.py --since "2026-07-06" [--until ...]
Exit 0 = parity, 1 = mismatches found, 2 = insufficient data.
"""
import argparse, re, subprocess, sys
from collections import OrderedDict

CYCLE_RE = re.compile(r"CYCLE (\S+) picked=(\S+) intents=(\d+)(.*)")
INTENT_RE = re.compile(r"(\w+/\w+/\w+) setup=(\S+)")

def journal(unit, since, until):
    cmd = ["journalctl", "--user", "-u", unit, "--no-pager", "--since", since]
    if until: cmd += ["--until", until]
    out = subprocess.run(cmd, capture_output=True, text=True).stdout
    cycles = OrderedDict()
    for line in out.splitlines():
        m = CYCLE_RE.search(line)
        if not m: continue
        ts, picked, n, rest = m.groups()
        bucket = ts[:16]  # minute bucket aligns the 5-min grids
        intents = frozenset(INTENT_RE.findall(rest))
        cycles[bucket] = {"picked": picked, "n": int(n), "intents": intents, "ts": ts}
    return cycles

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", required=True)
    ap.add_argument("--until", default=None)
    ap.add_argument("--live-unit", default="mr-scrooge-v5")
    ap.add_argument("--shadow-unit", default="mr-scrooge-v6-dryrun")
    a = ap.parse_args()
    live, shadow = journal(a.live_unit, a.since, a.until), journal(a.shadow_unit, a.since, a.until)
    common = [b for b in live if b in shadow]
    if len(common) < 10:
        print(f"INSUFFICIENT: only {len(common)} aligned cycles (live={len(live)} shadow={len(shadow)})")
        sys.exit(2)
    mism = []
    for b in common:
        L, S = live[b], shadow[b]
        if L["intents"] != S["intents"] or L["picked"] != S["picked"]:
            mism.append((b, L, S))
    print(f"aligned cycles: {len(common)} | intent+pick parity: {len(common)-len(mism)} | MISMATCHES: {len(mism)}")
    for b, L, S in mism[:20]:
        print(f"  {b}  live picked={L['picked']} intents={sorted(L['intents'])}")
        print(f"  {'':16}shadow picked={S['picked']} intents={sorted(S['intents'])}")
    if mism: sys.exit(1)
    print("VERDICT: PARITY — shadow decides identically to live over the window")
    sys.exit(0)

if __name__ == "__main__":
    main()
