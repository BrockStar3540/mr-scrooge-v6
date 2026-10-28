"""Scrooge V6 — pips by exit type for a window of closed live trades (read-only).

Built 2026-10-28 for Brock's 4h-reaper week (reaper 4h / any red from
2026-10-28T07:11:27Z, gear +5 -> +4 then trail 2 from 07:06Z).

  python3 reaper_week.py [--since ISO] [--until ISO] [--compare-days N]

Exit types (from OANDA's own fill reason + the trade's age/P&L at close):
  ratchet lock  STOP_LOSS_ORDER fill, pips > 0  (the moved stop banked a win)
  stop-out      STOP_LOSS_ORDER fill, pips <= 0 (original stop, or a lock at/below 0)
  reaper        MARKET_ORDER_TRADE_CLOSE, open >= reaper hours and red
  other close   any other bot/operator market close
Pips come from the broker fill prices (spread included). Prints a markdown
report; nothing is written anywhere.
"""
import argparse, collections, datetime as dt, json, os, urllib.request

ap = argparse.ArgumentParser()
ap.add_argument("--since", default="2026-10-28T07:11:27Z")
ap.add_argument("--until", default=None)
ap.add_argument("--compare-days", type=float, default=7.0,
                help="also report the same-length window just before --since")
ap.add_argument("--reaper-hours", type=float, default=4.0)
a = ap.parse_args()

S = {}
for ln in open(os.path.expanduser("~/.openclaw/secrets.env")):
    if "=" in ln and not ln.strip().startswith("#"):
        k, v = ln.rstrip("\n").split("=", 1); S[k.strip()] = v.strip()
TOK, URL, ACCT = S["OANDA_API_TOKEN"], S["OANDA_API_URL"], S["OANDA_ACCOUNT_ID"]


def get(u):
    r = urllib.request.Request(u if u.startswith("http") else URL + u,
                               headers={"Authorization": "Bearer " + TOK})
    return json.loads(urllib.request.urlopen(r, timeout=30).read())


P = lambda s: dt.datetime.fromisoformat(s.replace("Z", "")[:19]).replace(tzinfo=dt.timezone.utc)
since = P(a.since)
until = P(a.until) if a.until else dt.datetime.now(dt.timezone.utc)
before = since - dt.timedelta(days=a.compare_days)
# opens can precede a window by days: pull from well before the comparison window
pull_from = (before - dt.timedelta(days=14)).strftime("%Y-%m-%dT%H:%M:%SZ")
tx = []
for u in get(f"/v3/accounts/{ACCT}/transactions?from={pull_from}")["pages"]:
    tx += get(u)["transactions"]

opens = {}
for t in tx:
    if t["type"] == "ORDER_FILL" and t.get("tradeOpened"):
        to = t["tradeOpened"]
        tag = ((to.get("clientExtensions") or {}).get("tag", "") or "").split(";", 1)[0]
        opens[to["tradeID"]] = dict(time=t["time"], price=float(t["price"]), units=float(to["units"]),
                                    src={"pp_v1": "popper", "cell_v1": "parent"}.get(tag, "-"))
closes = []
for t in tx:
    if t["type"] != "ORDER_FILL" or float(t.get("pl", 0)) == 0:
        continue
    for c in t.get("tradesClosed") or []:
        o = opens.get(c["tradeID"])
        if not o:
            continue
        ps = 0.01 if "JPY" in t["instrument"] else 0.0001
        sg = 1 if o["units"] > 0 else -1
        pips = sg * (float(t["price"]) - o["price"]) / ps
        hold = (P(t["time"]) - P(o["time"])).total_seconds() / 3600
        if t.get("reason") == "STOP_LOSS_ORDER":
            kind = "ratchet lock" if pips > 0 else "stop-out"
        elif hold >= a.reaper_hours and pips < 0:
            kind = "reaper"
        else:
            kind = "other close"
        closes.append(dict(time=P(t["time"]), inst=t["instrument"], src=o["src"], kind=kind,
                           pips=pips, usd=float(c["realizedPL"]), hold=hold))

KINDS = ("ratchet lock", "stop-out", "reaper", "other close")


def table(lo, hi, title):
    w = [x for x in closes if lo <= x["time"] < hi]
    out = [f"### {title}", f"{lo:%Y-%m-%d %H:%MZ} → {hi:%Y-%m-%d %H:%MZ} · {len(w)} closed trades", "",
           "| Exit type | Trades | Pips | Pips/trade | USD | Median hold |",
           "|---|---:|---:|---:|---:|---:|"]
    for k in KINDS + ("all",):
        xs = [x for x in w if k == "all" or x["kind"] == k]
        if not xs and k != "all":
            continue
        n = len(xs); p = sum(x["pips"] for x in xs); u = sum(x["usd"] for x in xs)
        hs = sorted(x["hold"] for x in xs)
        med = f"{hs[len(hs)//2]:.1f}h" if hs else "-"
        lab = f"**{k}**" if k == "all" else k
        out.append(f"| {lab} | {n} | {p:+.1f} | {(p/n if n else 0):+.2f} | {u:+.2f} | {med} |")
    by = collections.defaultdict(lambda: [0, 0.0])
    for x in w:
        by[x["src"]][0] += 1; by[x["src"]][1] += x["pips"]
    out.append("")
    out.append("By family: " + " · ".join(f"{s} {n} trades {p:+.1f}p" for s, (n, p) in sorted(by.items())))
    wins = [x for x in w if x["pips"] > 0]; losses = [x for x in w if x["pips"] <= 0]
    if w:
        aw = sum(x["pips"] for x in wins) / len(wins) if wins else 0
        al = sum(x["pips"] for x in losses) / len(losses) if losses else 0
        be = (-al / (aw - al)) if wins and losses else float("nan")
        out.append(f"Win rate {len(wins)/len(w):.1%} · avg win {aw:+.1f}p · avg loss {al:+.1f}p · break-even win rate {be:.1%}")
    return "\n".join(out)


print(table(since, until, f"Reaper {a.reaper_hours:g}h week"))
print()
print(table(before, since, f"Previous {a.compare_days:g} days (24h reaper; +7.5→+6 gear until 10-28 07:06Z)"))
