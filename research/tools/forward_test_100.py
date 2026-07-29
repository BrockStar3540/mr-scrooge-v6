#!/usr/bin/env python3
"""research/tools/forward_test_100.py — the 100-trade forward-test write-up generator.

Pre-registered by docs/FORWARD_TEST_PROTOCOL.md (2026-07-28): when the current-config
window reaches 100 closed trades, this produces the draft report from broker truth —
starting balance, ending balance, the tape's geometry, per-family attribution.
Run: python3 research/tools/forward_test_100.py   (writes docs/FORWARD_TEST_100_REPORT.md)
"""
from __future__ import annotations
import csv, json, os, subprocess, sys, urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ANCHOR_TS = "2026-07-16T01:11:00Z"
FREEZE_TS = "2026-07-29T10:24:28Z"   # trading paused; test ended by operator
START_BAL = 16665.12          # broker-verified pre-first-fill (see protocol doc)
LIVE_STAKE = 2500.00


def _secrets():
    d = {}
    for ln in open(os.path.expanduser("~/.openclaw/secrets.env")):
        if "=" in ln and not ln.strip().startswith("#"):
            k, v = ln.rstrip("\n").split("=", 1)
            d[k.strip()] = v.strip()
    return d


def main():
    S = _secrets()
    url, tok, acct = S["OANDA_API_URL"], S["OANDA_API_TOKEN"], S["OANDA_ACCOUNT_ID"]

    def api(p):
        full = p if p.startswith("http") else url + p
        r = urllib.request.Request(full, headers={"Authorization": "Bearer " + tok})
        return json.loads(urllib.request.urlopen(r, timeout=30).read())

    acc = api(f"/v3/accounts/{acct}/summary")["account"]
    bal, nav = float(acc["balance"]), float(acc["NAV"])
    open_n = int(acc["openTradeCount"])

    # ASTERISK RULE (Brock, 2026-07-29): the operator ended the test by hand —
    # post-freeze closes with reason MARKET_ORDER_TRADE_CLOSE are shown but
    # EXCLUDED from the strategy statistics (they measure the operator's
    # impatience, not the system's exits). Identified from broker reasons.
    manual = set()
    idx = api(f"/v3/accounts/{acct}/transactions?from={FREEZE_TS}")
    for u in idx.get("pages", []):
        for t in api(u).get("transactions", []):
            if (t.get("type") == "ORDER_FILL"
                    and t.get("reason") == "MARKET_ORDER_TRADE_CLOSE"):
                legs = list(t.get("tradesClosed") or [])
                if t.get("tradeReduced"):
                    legs.append(t["tradeReduced"])
                for tc in legs:
                    manual.add((t["time"][:19] + "Z",
                                round(float(tc.get("realizedPL", 0)), 2)))

    all_rows = list(csv.DictReader(open(REPO / "livelog" / "trades.csv")))
    star = [r for r in all_rows
            if (r["close_utc"], round(float(r["realized_usd"]), 2)) in manual]
    rows = [r for r in all_rows if r not in star]
    n, n_all = len(rows), len(all_rows)
    wins = [float(r["realized_usd"]) for r in rows if float(r["realized_usd"]) > 0]
    losses = [float(r["realized_usd"]) for r in rows if float(r["realized_usd"]) < 0]
    realized = sum(wins) + sum(losses)
    by_src = {}
    for r in rows:
        s = r["source"] if r["source"] in ("parent", "popper") else "legacy"
        by_src.setdefault(s, []).append(float(r["realized_usd"]))

    fam_md = "*(family audit unavailable)*"
    try:
        out = subprocess.run([sys.executable, str(REPO / "research" / "tools" / "broker_setup_audit.py"),
                              "--since", ANCHOR_TS, "--json"],
                             capture_output=True, text=True, timeout=180)
        fams = sorted(json.loads(out.stdout).get("families", []), key=lambda f: f["usd"])
        fam_md = "| family | trades (P/pp) | G/R | USD | pips |\n|---|---|---|---|---|\n" + "\n".join(
            f"| {f['instrument']} {f['setup']} | {f['n']} ({f['n_parents']}/{f['n_poppers']}) "
            f"| {f['greens']}/{f['n']-f['greens']} | {f['usd']:+.2f} | {f['pips']:+.1f} |"
            for f in fams)
    except Exception as e:
        fam_md += f" ({e})"

    aw = sum(wins) / len(wins) if wins else 0
    al = sum(losses) / len(losses) if losses else 0
    be = abs(al) / (aw + abs(al)) * 100 if (aw or al) else 0
    ret = (bal - START_BAL) / START_BAL * 100

    final = (REPO / "livelog" / ".ft100_alerted").exists() and open_n == 0
    star_md = ""
    if star:
        star_md = ("\n### * Excluded from the statistics — operator close-outs\n\n"
                   "The test was ended by hand: trading was paused at "
                   f"{FREEZE_TS} and the last open positions were closed manually. "
                   "Those closes are on the tape and in the balance, but they measure "
                   "the operator's decision to stop, not the system's exits — so they "
                   "carry an asterisk and sit outside the strategy statistics:\n\n"
                   "| close (UTC) | instrument | dir | realized | source |\n|---|---|---|---|---|\n"
                   + "\n".join(
                       f"| {r['close_utc']} * | {r['instrument']} | {r['direction']} "
                       f"| ${float(r['realized_usd']):+.2f} | {r['source']} (manual close) |"
                       for r in star) + "\n")

    report = f"""# The 100-Trade Forward Test — final report{'' if final else ' (DRAFT — window not yet complete)'}

*Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} from broker records.
Pre-registered endpoint and consequences: [FORWARD_TEST_PROTOCOL.md](FORWARD_TEST_PROTOCOL.md).*

## The number that matters

| | |
|---|---|
| **Starting balance** (2026-07-16, pre-first-fill, broker-verified) | **${START_BAL:,.2f}** |
| **Ending balance** (account flat) | **${bal:,.2f}** |
| **Return over the window** | **{ret:+.2f}%** |
| Natural closes (the strategy statistics) | {n} |
| Operator close-outs (asterisked, excluded from stats) | {len(star)} |
| Total tape | {n_all} |

A precision note, because honesty is the product here: the protocol said "the 100th
closed trade." The operator froze entries and closed the final open positions by hand
with the natural tape at {n} closes — so the strategy sample is **{n} system-managed
trades**, the two hand-closes are asterisked below, and the balance numbers include
everything. Nothing is hidden in either direction.

## The tape

- **W/L (natural closes):** {len(wins)}/{len(losses)} ({len(wins)/n*100:.1f}% win rate)
- **Realized (natural closes):** ${realized:+,.2f} · avg win ${aw:+.2f} · avg loss ${al:+.2f}
- **Breakeven win rate the geometry demanded:** {be:.1f}%
- **By source:** """ + " · ".join(
        f"{s} {len(v)} trades ${sum(v):+,.2f}" for s, v in sorted(by_src.items())) + f"""
- Full tape: [livelog/trades.csv](../livelog/trades.csv) · equity: [livelog/equity.csv](../livelog/equity.csv)
{star_md}

## Per-family attribution (parent + its poppers, one unit)

{fam_md}

## What changed mid-window (disclosed)

- 07-19: engage 7.5 → 8.5 regear (whole book, open trades re-geared broker-side).
- 07-28: the FAMILY RULE + judge-when-flat (v6.7.x) — demotion re-grounded in family
  broker net pips; motivated by this very tape's one losing family.

## What 100 trades is — and isn't

**100 trades in a two-week window is not proof of sustained edge — by any means.** It's one
market regime and a sample small enough that variance alone could paint either verdict. It
is enough for *us, personally,* to try live trading with a small stake — that is the whole
claim. Use your own discernment; results vary over time, and when things go wrong the
drawdown can be substantial (this account's history includes a −84% research tuition; the
falsification record is public). The troublesome cells were demoted mid-window, and the
system now promotes and demotes seats autonomously as each cell earns or loses them.

## The decision

Per the pre-registered protocol: the practice account is closed with this report, and the
system goes **live with ${LIVE_STAKE:,.2f} real money** — `margin_pct_per_trade` 0.10 → 0.15,
`max_concurrent_trades` 8 → 6, popper `max_margin_pct_total` 0.8 → 0.9, everything else
exactly as tested. The live record publishes to this repo hourly, same as this one did.
"""
    out_p = REPO / "docs" / "FORWARD_TEST_100_REPORT.md"
    out_p.write_text(report)
    print(f"wrote {out_p} ({'DRAFT — ' if n < 100 else ''}{n} trades, bal ${bal:,.2f}, {ret:+.2f}%)")


if __name__ == "__main__":
    main()
