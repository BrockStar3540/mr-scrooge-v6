#!/usr/bin/env python3
"""research/tools/broker_setup_audit.py — per-SETUP broker-truth scoreboard.

Joins OANDA transactions: tradeOpened fills carry clientExtensions.comment JSON
with "su" = setup_id (core/engine.py exit-gear persistence), tradesClosed fills
carry realizedPL. Output = per (instrument, setup) realized USD + pips for
trades OPENED inside the era window — broker fills, not journal intent
(2026-06-21 lesson: only the broker has fills, manual closes, spread, P/L).

Trades opened before the era anchor are excluded (old-gear trades; counted in
the exclusions line). Open trades are listed separately as exposure, unrealized.

FAMILIES (2026-07-28): a parent and the poppers its grid fired are ONE economic
unit — the 7/16→7/28 forward test showed per-leg views mislead in both
directions (kc_up_long_lean parents red −$74 but family +$718; rvol_low_240
parents −$130 hiding a −$858 family). The "families" output aggregates
parent+popper fills per (instrument, family setup): poppers attribute via the
stamped "psu" (2026-07-28+) or the grid-anchor→parent-entry price join for
older fills. The governor's net-pips demote/defend rule reads this block.

Usage: python3 research/tools/broker_setup_audit.py [--since 2026-07-19T00:00:00Z] [--json]
"""
from __future__ import annotations
import argparse, json, os, sys, urllib.request
from collections import defaultdict

DEFAULT_SINCE = "2026-07-19T00:00:00Z"   # engage 8.5 / lock 6 gear era
PP_ANC_JOIN_PIPS = 30.0   # max |grid anchor − parent open| for the backfill join


def family_setup(op: dict, parent_opens: list) -> str:
    """The FAMILY a fill belongs to. Parents (tag=cell_v1) are their own setup;
    poppers (tag=pp_v1) belong to the parent setup that armed their grid —
    via the stamped "psu", or for pre-stamp fills the grid anchor joined to
    the nearest same-instrument/direction parent open (the anchor IS the
    parent's entry price). Returns "?" when a popper can't be attributed."""
    if op["tag"] != "pp_v1":
        return op["su"]
    if op.get("psu"):
        return op["psu"]
    anc = op.get("anc")
    if not isinstance(anc, (int, float)):
        return "?"
    best, bestd = None, PP_ANC_JOIN_PIPS
    for p in parent_opens:
        if p["instrument"] != op["instrument"] or p["dir"] != op["dir"]:
            continue
        d = abs(p["price"] - anc) / _pip(op["instrument"])
        if d <= bestd:
            best, bestd = p["su"], d
    return best or "?"


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
        tag, meta = ext.get("tag", ""), {}
        c = ext.get("comment", "")
        if c.startswith("{"):
            try:
                meta = json.loads(c)
            except json.JSONDecodeError:
                pass
        units = float(to.get("units", 0))
        opens[str(to.get("tradeID"))] = {
            "instrument": t.get("instrument"),
            "dir": 1 if units > 0 else -1,
            "price": float(to.get("price", t.get("price", 0))),
            "su": meta.get("su") or "?", "tag": tag,
            "psu": meta.get("psu"), "anc": meta.get("anc"),
            "time": t.get("time", "")[:16],
        }

    # closes: join tradesClosed / tradeReduced back to opens
    groups = defaultdict(lambda: {"n": 0, "greens": 0, "usd": 0.0, "pips": 0.0,
                                  "trades": []})
    fams = defaultdict(lambda: {"n": 0, "greens": 0, "usd": 0.0, "pips": 0.0,
                                "n_parents": 0, "n_poppers": 0, "trades": []})
    parent_opens = [o for o in opens.values() if o["tag"] == "cell_v1"]
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
            trade = {"id": tid, "usd": round(pl, 2),
                     "pips": round(pips, 1), "t": op["time"]}
            g["trades"].append(trade)
            # family view: parents + their poppers as one economic unit
            if op["tag"] in ("cell_v1", "pp_v1"):
                fam = family_setup(op, parent_opens)
                if fam != "?":
                    fg = fams[(op["instrument"], fam)]
                    fg["n"] += 1
                    fg["greens"] += 1 if pl > 0 else 0
                    fg["usd"] += pl
                    fg["pips"] += pips
                    src = "popper" if op["tag"] == "pp_v1" else "parent"
                    fg["n_poppers" if src == "popper" else "n_parents"] += 1
                    fg["trades"].append(dict(trade, src=src))

    # open exposure by setup — also family-attributed, because an open trade
    # DEFERS its family's verdict (judge-when-flat, Brock 2026-07-28: a parent
    # can stop −60 while its poppers are still riding toward +30; convicting
    # or defending mid-episode judges half a scale-in).
    open_rows = []
    try:
        for tr in api(f"/v3/accounts/{acct}/trades?state=OPEN&count=500").get("trades", []):
            tid = str(tr.get("id"))
            units = float(tr.get("currentUnits", 0))
            # B-112: the LIVE trades endpoint mangles clientExtensions (tag ->
            # "0", comment truncated ~32 chars) — which made open poppers
            # invisible here and let a family be judged "flat" mid-episode.
            # The TRANSACTION stream is pristine, and `opens` was built from
            # it — prefer that record; the endpoint copy is the fallback.
            op = opens.get(tid)
            if op is None:
                ext = tr.get("clientExtensions") or {}
                meta = {}
                c = ext.get("comment", "")
                if c.startswith("{"):
                    try:
                        meta = json.loads(c)
                    except json.JSONDecodeError:
                        import re as _re
                        for k in ("anc",):
                            m = _re.search(r'"%s":([0-9.]+)' % k, c)
                            if m:
                                meta[k] = float(m.group(1))
                        for k in ("su", "psu"):
                            m = _re.search(r'"%s":"([^"]*)"?' % k, c)
                            if m:
                                meta[k] = m.group(1)
                tag = ext.get("tag", "")
                if tag not in ("cell_v1", "pp_v1") and c.startswith("{"):
                    tag = "cell_v1" if c.startswith(('{"m":', '{"su":')) else "pp_v1"
                op = {"instrument": tr["instrument"], "dir": 1 if units > 0 else -1,
                      "su": meta.get("su") or "?", "tag": tag,
                      "psu": meta.get("psu"), "anc": meta.get("anc")}
            fam = (family_setup(op, parent_opens)
                   if op["tag"] in ("cell_v1", "pp_v1") else "?")
            open_rows.append({"id": tid, "instrument": tr["instrument"],
                              "su": op["su"], "tag": op["tag"], "family": fam,
                              "upl": float(tr.get("unrealizedPL", 0))})
    except Exception as e:
        print(f"open-trades fetch failed: {e}", file=sys.stderr)

    open_by_fam = defaultdict(lambda: {"n": 0, "upl": 0.0})
    for o in open_rows:
        if o["family"] != "?":
            ob = open_by_fam[(o["instrument"], o["family"])]
            ob["n"] += 1
            ob["upl"] += o["upl"]
    for k in open_by_fam:        # open-only families must still reach callers
        fams[k]                  # defaultdict: materializes an empty closed row

    rows = []
    for (instr, su, tag), g in groups.items():
        rows.append({"instrument": instr, "setup": su, "tag": tag, "n": g["n"],
                     "greens": g["greens"], "usd": round(g["usd"], 2),
                     "pips": round(g["pips"], 1),
                     "avg_pips": round(g["pips"] / g["n"], 2),
                     "trades": g["trades"]})
    rows.sort(key=lambda r: r["usd"])

    fam_rows = []
    for (instr, fam), g in fams.items():
        ob = open_by_fam.get((instr, fam), {"n": 0, "upl": 0.0})
        fam_rows.append({"instrument": instr, "setup": fam, "n": g["n"],
                         "greens": g["greens"], "usd": round(g["usd"], 2),
                         "pips": round(g["pips"], 1),
                         "avg_pips": (round(g["pips"] / g["n"], 2)
                                      if g["n"] else None),
                         "n_parents": g["n_parents"],
                         "n_poppers": g["n_poppers"],
                         "n_open": ob["n"],
                         "open_upl": round(ob["upl"], 2),
                         "trades": g["trades"]})
    fam_rows.sort(key=lambda r: r["pips"])

    if args.json:
        print(json.dumps({"since": args.since, "rows": rows,
                          "families": fam_rows,
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
    print("\nFAMILIES (parent setup + its poppers, one economic unit; "
          "open>0 = verdict deferred until flat):")
    print(f"{'instrument':<10} {'family setup':<34} {'n':>3} {'P/pp':>7} {'G/R':>6}"
          f" {'USD':>10} {'pips':>8} {'avg p':>7} {'open':>5}")
    print("-" * 99)
    for r in fam_rows:
        gr = f"{r['greens']}/{r['n'] - r['greens']}"
        pp = f"{r['n_parents']}/{r['n_poppers']}"
        avg = f"{r['avg_pips']:7.2f}" if r["avg_pips"] is not None else "      —"
        print(f"{r['instrument']:<10} {r['setup']:<34} {r['n']:>3} {pp:>7}"
              f" {gr:>6} {r['usd']:>10.2f} {r['pips']:>8.1f} {avg} {r['n_open']:>5}")
    if open_rows:
        print("\nOPEN exposure (unrealized, not scored):")
        for o in open_rows:
            print(f"  {o['instrument']:<10} {o['su']:<34} {o['tag']:<8}"
                  f" trade={o['id']} uPL={o['upl']:+.2f}")


if __name__ == "__main__":
    main()
