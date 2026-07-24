#!/usr/bin/env python3
"""research/tools/broker_setup_audit.py — per-SETUP broker-truth scoreboard.

Joins OANDA transactions: tradeOpened fills carry clientExtensions.comment JSON
with "su" = setup_id (core/engine.py exit-gear persistence), tradesClosed fills
carry realizedPL. Output = per (instrument, setup) realized USD + pips for
trades OPENED inside the era window — broker fills, not journal intent
(2026-06-21 lesson: only the broker has fills, manual closes, spread, P/L).

Trades opened before the era anchor are excluded (old-gear trades; counted in
the exclusions line). Open trades are listed separately as exposure, unrealized.

Usage: python3 research/tools/broker_setup_audit.py [--since 2026-07-19T00:00:00Z] [--json]
"""
from __future__ import annotations
import argparse, json, os, sys, urllib.request
from collections import defaultdict

DEFAULT_SINCE = "2026-07-19T00:00:00Z"   # engage 8.5 / lock 6 gear era


def _secrets():
    d = {}
    for ln in open(os.path.expanduser("~/.openclaw/secrets.env")):
        if "=" in ln and not ln.strip().startswith("#"):
            k, v = ln.rstrip("\n").split("=", 1)
            d[k.strip()] = v.strip()
    return d


def _pip(instr):
    return 0.01 if "JPY" in instr else 0.0001


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=DEFAULT_SINCE)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    S = _secrets()
    tok, url, acct = S["OANDA_API_TOKEN"], S["OANDA_API_URL"], S["OANDA_ACCOUNT_ID"]

    def api(p):
        full = p if p.startswith("http") else url + p
        r = urllib.request.Request(full, headers={"Authorization": "Bearer " + tok})
        return json.loads(urllib.request.urlopen(r, timeout=20).read())

    idx = api(f"/v3/accounts/{acct}/transactions?from={args.since}")
    txns = []
    for u in idx.get("pages", []):
        txns += api(u).get("transactions", [])

    # opens: tid -> {instrument, dir, price, su, tag, time}
    opens = {}
    for t in txns:
        if t.get("type") != "ORDER_FILL":
            continue
        to = t.get("tradeOpened")
        if not to:
            continue
        ext = to.get("clientExtensions") or {}
        su, tag = None, ext.get("tag", "")
        c = ext.get("comment", "")
        if c.startswith("{"):
            try:
                su = json.loads(c).get("su")
            except json.JSONDecodeError:
                pass
        units = float(to.get("units", 0))
        opens[str(to.get("tradeID"))] = {
            "instrument": t.get("instrument"),
            "dir": 1 if units > 0 else -1,
            "price": float(to.get("price", t.get("price", 0))),
            "su": su or "?", "tag": tag, "time": t.get("time", "")[:16],
        }

    # closes: join tradesClosed / tradeReduced back to opens
    groups = defaultdict(lambda: {"n": 0, "greens": 0, "usd": 0.0, "pips": 0.0,
                                  "trades": []})
    excluded = 0
    for t in txns:
        if t.get("type") != "ORDER_FILL":
            continue
        legs = list(t.get("tradesClosed") or [])
        if t.get("tradeReduced"):
            legs.append(t["tradeReduced"])
        for tc in legs:
            tid = str(tc.get("tradeID"))
            op = opens.get(tid)
            if op is None:          # opened before the era anchor — old gear
                excluded += 1
                continue
            pl = float(tc.get("realizedPL", 0))
            px = float(tc.get("price", t.get("price", 0)))
            pips = (px - op["price"]) / _pip(op["instrument"]) * op["dir"]
            k = (op["instrument"], op["su"], op["tag"])
            g = groups[k]
            g["n"] += 1
            g["greens"] += 1 if pl > 0 else 0
            g["usd"] += pl
            g["pips"] += pips
            g["trades"].append({"id": tid, "usd": round(pl, 2),
                                "pips": round(pips, 1), "t": op["time"]})

    # open exposure by setup
    open_rows = []
    try:
        for tr in api(f"/v3/accounts/{acct}/trades?state=OPEN&count=500").get("trades", []):
            ext = tr.get("clientExtensions") or {}
            su = "?"
            c = ext.get("comment", "")
            if c.startswith("{"):
                try:
                    su = json.loads(c).get("su", "?")
                except json.JSONDecodeError:
                    pass
            open_rows.append({"id": tr["id"], "instrument": tr["instrument"],
                              "su": su, "tag": ext.get("tag", ""),
                              "upl": float(tr.get("unrealizedPL", 0))})
    except Exception as e:
        print(f"open-trades fetch failed: {e}", file=sys.stderr)

    rows = []
    for (instr, su, tag), g in groups.items():
        rows.append({"instrument": instr, "setup": su, "tag": tag, "n": g["n"],
                     "greens": g["greens"], "usd": round(g["usd"], 2),
                     "pips": round(g["pips"], 1),
                     "avg_pips": round(g["pips"] / g["n"], 2),
                     "trades": g["trades"]})
    rows.sort(key=lambda r: r["usd"])

    if args.json:
        print(json.dumps({"since": args.since, "rows": rows,
                          "excluded_pre_era_closes": excluded,
                          "open": open_rows}))
        return

    print(f"Broker-truth per-setup scoreboard — trades OPENED since {args.since}"
          f" (closes of pre-era trades excluded: {excluded})\n")
    print(f"{'instrument':<10} {'setup':<34} {'tag':<8} {'n':>3} {'G/R':>6}"
          f" {'USD':>10} {'pips':>8} {'avg p':>7}")
    print("-" * 92)
    for r in rows:
        gr = f"{r['greens']}/{r['n'] - r['greens']}"
        print(f"{r['instrument']:<10} {r['setup']:<34} {r['tag']:<8} {r['n']:>3}"
              f" {gr:>6} {r['usd']:>10.2f} {r['pips']:>8.1f} {r['avg_pips']:>7.2f}")
    if open_rows:
        print("\nOPEN exposure (unrealized, not scored):")
        for o in open_rows:
            print(f"  {o['instrument']:<10} {o['su']:<34} {o['tag']:<8}"
                  f" trade={o['id']} uPL={o['upl']:+.2f}")


if __name__ == "__main__":
    main()
