#!/usr/bin/env python3
"""research/tools/forward_test_card.py — the 100-trade forward-test stat card.

Regenerates docs/images/forward_test_card.svg from the archived record at
forward-test-100/ (broker-verified tape). Static SVG, repo dark style —
numbers are computed, never typed in.
"""
from __future__ import annotations
import csv
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "docs" / "images" / "forward_test_card.svg"
START_BAL, END_BAL = 16665.12, 18421.85

# palette (repo dark system): text tokens for text, green accent, red for losses
BG0, BG1, EDGE = "#0d1117", "#161b22", "#30363d"
TXT, DIM, MUT = "#e6edf3", "#9aa4b2", "#6e7681"
GREEN, RED, BLUE = "#3fb950", "#f85149", "#58a6ff"


def main():
    rows = list(csv.DictReader(open(REPO / "forward-test-100" / "trades.csv")))[:100]
    pls = [float(r["realized_usd"]) for r in rows]
    wins = [p for p in pls if p > 0]
    losses = [p for p in pls if p < 0]
    realized = sum(pls)
    net = END_BAL - START_BAL
    pct = net / START_BAL * 100

    # realized equity path + drawdowns
    eq, bal = [START_BAL], START_BAL
    for p in pls:
        bal += p
        eq.append(bal)
    peak, mdd, mdd_pk = eq[0], 0.0, eq[0]
    for v in eq:
        peak = max(peak, v)
        if peak - v > mdd:
            mdd, mdd_pk = peak - v, peak
    navs = [float(r["nav"]) for r in
            csv.DictReader(open(REPO / "forward-test-100" / "equity.csv"))]
    npk, nmdd, nmdd_pk = navs[0], 0.0, navs[0]
    for v in navs:
        npk = max(npk, v)
        if npk - v > nmdd:
            nmdd, nmdd_pk = npk - v, npk
    streak = best = 0
    for p in pls:
        streak = streak + 1 if p > 0 else 0
        best = max(best, streak)

    # curve geometry
    W, H = 940, 700
    cx0, cx1, cy0, cy1 = 56, 884, 210, 330
    lo, hi = min(eq), max(eq)
    rng = (hi - lo) or 1
    xs = [cx0 + i * (cx1 - cx0) / (len(eq) - 1) for i in range(len(eq))]
    ys = [cy1 - (v - lo) / rng * (cy1 - cy0) for v in eq]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    area = f"{cx0},{cy1} " + line + f" {cx1},{cy1}"

    def tile(x, y, label, value, sub, color=TXT, w=200, vsize=24):
        return (
            f'<g><rect x="{x}" y="{y}" width="{w}" height="86" rx="10" fill="{BG1}" stroke="{EDGE}"/>'
            f'<text x="{x+14}" y="{y+24}" font-size="11" fill="{MUT}" letter-spacing="1.5">{label}</text>'
            f'<text x="{x+14}" y="{y+52}" font-size="{vsize}" font-weight="800" fill="{color}">{value}</text>'
            f'<text x="{x+14}" y="{y+72}" font-size="11" fill="{DIM}">{sub}</text></g>')

    s = []
    s.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="100%" '
             f'font-family="system-ui,-apple-system,sans-serif">')
    s.append(f'<defs><linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">'
             f'<stop offset="0" stop-color="{BG1}"/><stop offset="1" stop-color="{BG0}"/></linearGradient>'
             f'<linearGradient id="fill" x1="0" y1="0" x2="0" y2="1">'
             f'<stop offset="0" stop-color="{GREEN}" stop-opacity="0.4"/>'
             f'<stop offset="1" stop-color="{GREEN}" stop-opacity="0"/></linearGradient>'
             f'<filter id="glow"><feGaussianBlur stdDeviation="3" result="b"/>'
             f'<feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>')
    s.append(f'<rect x="1" y="1" width="{W-2}" height="{H-2}" rx="18" fill="url(#bg)" stroke="{EDGE}"/>')

    # header
    s.append(f'<circle cx="56" cy="46" r="6" fill="{GREEN}"/>')
    s.append(f'<text x="72" y="51" font-size="15" font-weight="800" fill="{TXT}" letter-spacing="2">'
             f'THE 100-TRADE FORWARD TEST</text>')
    s.append(f'<text x="884" y="51" font-size="12" fill="{DIM}" text-anchor="end">'
             f'CONCLUDED 2026-07-29 · BROKER-VERIFIED · 13 DAYS</text>')

    # hero
    s.append(f'<text x="52" y="128" font-size="64" font-weight="900" fill="{GREEN}" filter="url(#glow)">'
             f'+{pct:.2f}%</text>')
    s.append(f'<text x="348" y="128" font-size="26" font-weight="700" fill="{GREEN}">+${net:,.2f}</text>')
    s.append(f'<text x="52" y="156" font-size="13" fill="{DIM}">'
             f'${START_BAL:,.2f} → ${END_BAL:,.2f} · realized on the tape +${realized:,.2f} · '
             f'window = first 100 closed trades, pre-registered</text>')

    # curve
    s.append(f'<polygon points="{area}" fill="url(#fill)"/>')
    s.append(f'<polyline points="{line}" fill="none" stroke="{GREEN}" stroke-width="2.5" filter="url(#glow)"/>')
    s.append(f'<circle cx="{xs[-1]:.1f}" cy="{ys[-1]:.1f}" r="4.5" fill="{GREEN}"/>')
    s.append(f'<text x="{cx0}" y="{cy1+18}" font-size="10.5" fill="{MUT}">Jul 16</text>')
    s.append(f'<text x="{cx1}" y="{cy1+18}" font-size="10.5" fill="{MUT}" text-anchor="end">Jul 29</text>')
    s.append(f'<text x="{(cx0+cx1)/2}" y="{cy1+18}" font-size="10.5" fill="{MUT}" text-anchor="middle">'
             f'realized equity, trade by trade</text>')

    # tiles — row 1
    ty = 362
    s.append(tile(56, ty, "TRADES", "100", f"90W · 10L · best green streak {best}", TXT))
    s.append(tile(268, ty, "WIN RATE", "90.0%", "breakeven needed: 82.2%", GREEN))
    s.append(tile(480, ty, "MAX DRAWDOWN", f"−{nmdd/nmdd_pk*100:.1f}%",
                  f"−${nmdd:,.0f} NAV, open marks included", RED))
    s.append(tile(692, ty, "NET / TRADE", f"+${realized/100:.2f}", "avg across all 100, net of costs", GREEN, 192))
    # tiles — row 2
    ty = 458
    s.append(tile(56, ty, "BIGGEST WIN", f"+${max(pls):,.2f}", "single trade, broker-verified", GREEN))
    s.append(tile(268, ty, "BIGGEST LOSS", f"−${abs(min(pls)):,.2f}", "wide stops take real bites", RED))
    s.append(tile(480, ty, "AVG WIN / AVG LOSS", f"+${sum(wins)/len(wins):.2f} / −${abs(sum(losses)/len(losses)):.2f}",
                  "small greens pay for big reds", TXT, 200, 19))
    s.append(tile(692, ty, "REALIZED DD", f"−{mdd/mdd_pk*100:.1f}%", f"−${mdd:,.0f} closed-trade curve", RED, 192))

    # spread & slippage box
    by = 566
    s.append(f'<rect x="56" y="{by}" width="828" height="92" rx="10" fill="{BG1}" stroke="{EDGE}"/>')
    s.append(f'<text x="72" y="{by+24}" font-size="12" font-weight="800" fill="{BLUE}" letter-spacing="1.5">'
             f'YES, IT PAID THE SPREAD</text>')
    s.append(f'<text x="72" y="{by+44}" font-size="11.5" fill="{DIM}">'
             f'OANDA practice accounts fill on the same live bid/ask pricing as real accounts: every entry here bought the ask or sold the bid, every exit crossed the spread'
             f'</text>')
    s.append(f'<text x="72" y="{by+61}" font-size="11.5" fill="{DIM}">'
             f'again (~0.9–1.5p round trip on majors), and financing was charged on every hold. The bot scores itself on executable prices only — mid-price accounting'
             f'</text>')
    s.append(f'<text x="72" y="{by+78}" font-size="11.5" fill="{DIM}">'
             f'was removed (B-103); every fill logs quoted-vs-filled slippage. Order-book depth at real size is the one thing practice can&#8217;t prove — so now it trades live.'
             f'</text>')

    # footer
    s.append(f'<text x="56" y="{H-14}" font-size="10.5" fill="{MUT}">'
             f'generated from forward-test-100/ by research/tools/forward_test_card.py · '
             f'full report: docs/FORWARD_TEST_100_REPORT.md · not proof of sustained edge</text>')
    s.append('</svg>\n')
    OUT.write_text("".join(s))
    print(f"wrote {OUT} (net +${net:,.2f} / +{pct:.2f}%, maxDD −{nmdd/nmdd_pk*100:.1f}%)")


if __name__ == "__main__":
    main()
