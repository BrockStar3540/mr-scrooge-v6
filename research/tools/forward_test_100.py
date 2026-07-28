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
        r = urllib.request.Request(url + p, headers={"Authorization": "Bearer " + tok})
        return json.loads(urllib.request.urlopen(r, timeout=30).read())

    acc = api(f"/v3/accounts/{acct}/summary")["account"]
    bal, nav = float(acc["balance"]), float(acc["NAV"])
    open_n = int(acc["openTradeCount"])

    rows = list(csv.DictReader(open(REPO / "livelog" / "trades.csv")))
    n = len(rows)
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

    report = f"""# The 100-Trade Forward Test — final report{' (DRAFT — window not yet complete)' if n < 100 else ''}

*Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} from broker records.
Pre-registered endpoint and consequences: [FORWARD_TEST_PROTOCOL.md](FORWARD_TEST_PROTOCOL.md).*

## The number that matters

| | |
|---|---|
| **Starting balance** (2026-07-16, pre-first-fill, broker-verified) | **${START_BAL:,.2f}** |
| **Ending balance** | **${bal:,.2f}** |
| **Return over the window** | **{ret:+.2f}%** |
| Closed trades | {n} |
| Open at generation | {open_n} (record ends flat per protocol) |

## The tape

- **W/L:** {len(wins)}/{len(losses)} ({len(wins)/n*100:.1f}% win rate)
- **Realized:** ${realized:+,.2f} · avg win ${aw:+.2f} · avg loss ${al:+.2f}
- **Breakeven win rate the geometry demanded:** {be:.1f}%
- **By source:** """ + " · ".join(
        f"{s} {len(v)} trades ${sum(v):+,.2f}" for s, v in sorted(by_src.items())) + f"""
- Full tape: [livelog/trades.csv](../livelog/trades.csv) · equity: [livelog/equity.csv](../livelog/equity.csv)

## Per-family attribution (parent + its poppers, one unit)

{fam_md}

## What changed mid-window (disclosed)

- 07-19: engage 7.5 → 8.5 regear (whole book, open trades re-geared broker-side).
- 07-28: the FAMILY RULE + judge-when-flat (v6.7.x) — demotion re-grounded in family
  broker net pips; motivated by this very tape's one losing family.

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
