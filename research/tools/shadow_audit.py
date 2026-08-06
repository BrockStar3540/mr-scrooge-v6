#!/usr/bin/env python3
"""research/tools/shadow_audit.py — full census of the shadow book.

Answers, for every non-ACTIVE setup: is it alive, is it accruing, is it any
good, is it contradicted by real fills, and is it worth keeping? Dormant
shadows are not free — they sit in the hypothesis registry, clutter the board,
and (before the docket fix) taxed every real candidate's q-value.

Read-only. Usage: python3 research/tools/shadow_audit.py [--json] [--csv PATH]
"""
from __future__ import annotations
import argparse, json, sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
import urllib.request

NOW = datetime.now(timezone.utc)


def _age_days(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        s = iso if len(iso) > 10 else iso + "T00:00:00+00:00"
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return round((NOW - d).total_seconds() / 86400.0, 1)
    except Exception:
        return None


def classify(r: dict) -> tuple[str, str]:
    """(bucket, reason) — the operational verdict for one setup."""
    era, vc = r.get("era") or {}, r.get("vc") or {}
    eps, last_age = r.get("episodes") or 0, r.get("_last_age")
    wired_age = r.get("_wired_age")

    if r.get("status") == "EX-SIDE":
        return "RETIRED", "side no longer matches config"
    if r.get("vc_broker_agree") is False:
        return "TRUTH-CONTRADICTED", "virtual sim disagrees with this cell's own fills"
    if eps == 0:
        if wired_age is not None and wired_age >= 14:
            return "NEVER FIRED", f"wired {wired_age:.0f}d ago, zero episodes"
        return "WAITING", "wired recently, no episodes yet"
    if last_age is not None and last_age >= 7:
        return "STALLED", f"no stamp in {last_age:.0f}d"
    if r.get("bar_met"):
        return "PROMOTION-READY", "passes the full bar"
    if era.get("avg") is not None and era["avg"] < 0:
        return "BUILDING (negative)", f"era avg {era['avg']:+.2f}p"
    if era.get("n"):
        gn = max(0, (era.get("req_n") or 10) - era["n"])
        gd = max(0, (era.get("req_days") or 5) - era["days"])
        if gn == 0 and gd == 0:
            return "AT GATES (quality short)", "counts met; " + ",".join(era.get("codes") or [])
        return "BUILDING (positive)", f"needs {gn} eps / {gd} days"
    return "AWAITING V2", "no current-era v2 evidence"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--csv")
    args = ap.parse_args()

    board = json.loads(urllib.request.urlopen(
        "http://127.0.0.1:8084/api/shadowboard", timeout=120).read())
    rows = board if isinstance(board, list) else board.get("rows") or []
    db = json.load(open(REPO / "data" / "shadowboard.json"))

    last_stamp: dict = defaultdict(str)
    for e in db["episodes"].values():
        k = (e["cell"], e["setup"])
        if e["t"] > last_stamp[k]:
            last_stamp[k] = e["t"]

    out = []
    for r in rows:
        if r.get("status") == "ACTIVE":
            continue
        k = (r["cell"], r["setup"])
        r["_last_age"] = _age_days(last_stamp.get(k))
        r["_wired_age"] = _age_days(r.get("wired") or r.get("first"))
        bucket, why = classify(r)
        era, vc = r.get("era") or {}, r.get("vc") or {}
        out.append({
            "bucket": bucket, "why": why, "cell": r["cell"], "setup": r["setup"],
            "side": r.get("side"), "status": r.get("status"),
            "strikes": r.get("strikes") or 0,
            "eps": r.get("episodes") or 0,
            "n": era.get("n"), "days": era.get("days"),
            "avg": era.get("avg"), "lcb": era.get("lcb"), "q": era.get("q"),
            "vc_net": vc.get("net_mean"), "vc_cycles": vc.get("cycles"),
            "truth": r.get("vc_broker_agree"),
            "last_stamp_days": r["_last_age"], "wired_days": r["_wired_age"],
        })

    if args.json:
        print(json.dumps(out, indent=1)); return
    if args.csv:
        import csv
        with open(args.csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(out[0].keys())); w.writeheader()
            w.writerows(out)
        print(f"wrote {len(out)} rows -> {args.csv}")

    order = ["PROMOTION-READY", "AT GATES (quality short)", "TRUTH-CONTRADICTED",
             "BUILDING (positive)", "BUILDING (negative)", "STALLED",
             "NEVER FIRED", "WAITING", "AWAITING V2", "RETIRED"]
    counts = Counter(r["bucket"] for r in out)
    print(f"SHADOW BOOK AUDIT — {len(out)} non-ACTIVE setups, {NOW:%Y-%m-%d %H:%M}Z\n")
    for b in order:
        if counts.get(b):
            print(f"  {b:<26} {counts[b]:>4}")
    print()

    def show(bucket, limit=None, sort=None):
        rs = [r for r in out if r["bucket"] == bucket]
        if not rs:
            return
        rs.sort(key=sort or (lambda r: -(r["avg"] if r["avg"] is not None else -99)))
        print(f"── {bucket} ({len(rs)}) " + "─" * max(0, 56 - len(bucket)))
        for r in rs[:limit]:
            ev = (f"n{r['n']}/{r['days']}d avg{r['avg']:+6.2f} lcb{str(r['lcb']):>7} "
                  f"q{str(r['q']):>7}") if r["n"] else f"eps{r['eps']}"
            vcs = (f" vc{r['vc_net']:+.0f}p×{r['vc_cycles']}" if r.get("vc_cycles") else "")
            stk = f" {'🔻'*min(r['strikes'],3)}" if r["strikes"] else ""
            print(f"   {r['cell']}/{r['setup']:<32}{ev}{vcs}{stk}  [{r['why']}]")
        if limit and len(rs) > limit:
            print(f"   … and {len(rs)-limit} more")
        print()

    for b in order:
        show(b, limit=12 if b in ("BUILDING (positive)", "BUILDING (negative)",
                                  "WAITING", "AWAITING V2") else None)

    dead = [r for r in out if r["bucket"] in ("NEVER FIRED", "STALLED")]
    print(f"REGISTRY COST: {len(dead)} setups are dormant or stalled out of "
          f"{len(out)} — they occupy the hypothesis registry and the board "
          f"while producing no evidence.")


if __name__ == "__main__":
    main()
