#!/usr/bin/env python3
"""ops/livelog_update.py — the public live track record for the CURRENT config.

Runs on EC2 (has the OANDA token via ~/.openclaw/secrets.env). Tracks the
practice account's performance SINCE THE CURRENT EXIT CONFIG went live — the
range-sized wide-stop ratchet (SL 40/50/60 · engage +7.5 · trail 2.5 fixed),
fully deployed 2026-07-16 01:11 UTC (the B-090 trail_mult=0 fix completed it).
Earlier trades belong to prior configs and are deliberately NOT counted.

Headline = realized P/L of trades closed under this config (the honest record),
plus current open trades. The OANDA token NEVER leaves EC2 and NEVER enters the
repo; published output is numbers only (no account id, no token). Practice
account. Fail-soft: OANDA unreachable → files untouched, exit 0.

To re-anchor on a future config change: bump ANCHOR_TS + ANCHOR_LABEL, delete
livelog/trades.csv + livelog/.seed, and re-run.
"""
import csv, json, os, re, subprocess, sys, urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LIVELOG = REPO / "livelog"
README = REPO / "README.md"
EQUITY = LIVELOG / "equity.csv"
TRADES = LIVELOG / "trades.csv"
SVG = LIVELOG / "equity.svg"

ANCHOR_TS = "2026-07-16T01:11:00Z"
ANCHOR_LABEL = "range-sized wide-stop ratchet · SL 40/50/60 · engage +7.5 → lock +5 → trail 2.5 fixed"
ANCHOR_HUMAN = "2026-07-16"

def secrets():
    d = {}
    for ln in open(os.path.expanduser("~/.openclaw/secrets.env")):
        if "=" in ln and not ln.strip().startswith("#"):
            k, v = ln.rstrip("\n").split("=", 1); d[k.strip()] = v.strip()
    return d
S = secrets()
TOK, URL, ACCT = S.get("OANDA_API_TOKEN"), S.get("OANDA_API_URL"), S.get("OANDA_ACCOUNT_ID")

def api(p):
    r = urllib.request.Request(URL + p, headers={"Authorization": "Bearer " + TOK})
    return json.loads(urllib.request.urlopen(r, timeout=20).read())
def fetch(u):
    r = urllib.request.Request(u, headers={"Authorization": "Bearer " + TOK})
    return json.loads(urllib.request.urlopen(r, timeout=20).read()).get("transactions", [])

try:
    summ = api(f"/v3/accounts/{ACCT}/summary")["account"]
except Exception as e:
    print(f"livelog: OANDA unreachable ({e}) — left as-is", file=sys.stderr); sys.exit(0)

LIVELOG.mkdir(exist_ok=True)
now = datetime.now(timezone.utc)
nav = float(summ["NAV"]); bal = float(summ["balance"])
upl = float(summ["unrealizedPL"]); opn = int(summ["openTradeCount"])

# ── rebuild the trade log for THIS config from the broker (source of truth) ───
try:
    idx = api(f"/v3/accounts/{ACCT}/transactions?from={ANCHOR_TS}")
    txns = []
    for u in idx.get("pages", []):
        txns += fetch(u)
    rows, realized, financing = [], 0.0, 0.0
    for t in txns:
        if t.get("type") == "DAILY_FINANCING":
            financing += float(t.get("financing", t.get("amount", 0)))
        if t.get("type") == "ORDER_FILL" and float(t.get("pl", 0)) != 0 and t.get("time", "") >= ANCHOR_TS:
            u = float(t.get("units", 0)); pl = float(t["pl"])
            rows.append([t["time"][:19] + "Z", t.get("instrument", "?"),
                         "long" if u > 0 else "short", abs(int(u)), f"{pl:.2f}"])
            realized += pl
    rows.sort(key=lambda r: r[0])
    with open(TRADES, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["close_utc", "instrument", "direction", "units", "realized_usd"])
        w.writerows(rows)
    n_tr = len(rows); n_green = sum(1 for r in rows if float(r[4]) > 0); n_red = n_tr - n_green
    wr = (n_green / n_tr * 100) if n_tr else 0.0
except Exception as e:
    print(f"livelog: trade rebuild failed ({e})", file=sys.stderr); sys.exit(0)

# starting balance at anchor, reconstructed & self-consistent (no deposits on this acct)
start_bal = bal - realized - financing
tot = realized + upl  # config-to-date: booked greens + open marks
pct = (tot / start_bal * 100) if start_bal else 0.0

# ── equity snapshot (NAV over time, from first run forward) ───────────────────
new_eq = not EQUITY.exists()
with open(EQUITY, "a", newline="") as f:
    w = csv.writer(f)
    if new_eq: w.writerow(["utc", "nav", "balance", "unrealized_pl", "open_trades", "realized_since_config"])
    w.writerow([now.strftime("%Y-%m-%dT%H:%M:%SZ"), f"{nav:.2f}", f"{bal:.2f}", f"{upl:.2f}", opn, f"{realized:.2f}"])

rsign = "+" if realized >= 0 else "−"
usign = "+" if upl >= 0 else "−"
tsign = "+" if tot >= 0 else "−"
GREEN, RED, DIM, TXT = "#3fb950", "#f85149", "#7d8590", "#e6edf3"
ACC = GREEN if tot >= 0 else RED

# ── dashboard stat-card SVG (the eye-popper) ──────────────────────────────────
try:
    # realized equity curve: start balance stepped by each trade's P/L
    eq = [start_bal]; run = start_bal
    for r in rows:
        run += float(r[4]); eq.append(run)
    if len(eq) < 2: eq = [start_bal, bal]
    lo, hi = min(eq), max(eq); rng = (hi - lo) or 1
    cx0, cx1, cy0, cy1 = 40, 860, 208, 268
    xs = [cx0 + i*(cx1-cx0)/(len(eq)-1) for i in range(len(eq))]
    ys = [cy1 - (v-lo)/rng*(cy1-cy0) for v in eq]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    area = f"{cx0},{cy1} " + line + f" {cx1},{cy1}"
    def stat(x, label, value, vcol=TXT):
        return (f'<text x="{x}" y="172" font-family="system-ui,-apple-system,sans-serif" '
                f'font-size="12" fill="{DIM}" letter-spacing="1">{label}</text>'
                f'<text x="{x}" y="197" font-family="system-ui,-apple-system,sans-serif" '
                f'font-size="21" font-weight="700" fill="{vcol}">{value}</text>')
    streak = f"{n_green}/{n_tr} · 100% GREEN" if n_red == 0 and n_tr else f"{n_green}/{n_tr} green"
    hero = f"{tsign}${abs(tot):,.2f}"
    pct_x = 52 + len(hero) * 37
    parts = [
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 300" width="100%" font-family="system-ui,-apple-system,sans-serif">',
      '<defs><linearGradient id="bg" x1="0" y1="0" x2="0" y2="1">',
      '<stop offset="0" stop-color="#161b22"/><stop offset="1" stop-color="#0d1117"/></linearGradient>',
      '<linearGradient id="fill" x1="0" y1="0" x2="0" y2="1">',
      f'<stop offset="0" stop-color="{ACC}" stop-opacity="0.35"/><stop offset="1" stop-color="{ACC}" stop-opacity="0"/></linearGradient></defs>',
      '<rect x="1" y="1" width="898" height="298" rx="16" fill="url(#bg)" stroke="#30363d"/>',
      f'<circle cx="40" cy="42" r="6" fill="{GREEN}"/>',
      f'<text x="56" y="47" font-size="14" font-weight="700" fill="{TXT}" letter-spacing="2">LIVE</text>',
      f'<text x="98" y="47" font-size="14" fill="{DIM}" letter-spacing="1">· MR. SCROOGE — CURRENT CONFIG</text>',
      f'<text x="862" y="47" font-size="12" fill="{DIM}" text-anchor="end">NAV ${nav:,.2f}</text>',
      f'<text x="38" y="118" font-size="66" font-weight="800" fill="{ACC}">{hero}</text>',
      f'<text x="{pct_x}" y="118" font-size="26" font-weight="700" fill="{ACC}">{"▲" if tot>=0 else "▼"} {pct:+.2f}%</text>',
      f'<text x="40" y="140" font-size="12" fill="{DIM}">config-to-date · realized + open, since {ANCHOR_HUMAN}</text>',
      stat(40,  "REALIZED", f"{rsign}${abs(realized):,.2f}", GREEN if realized>=0 else RED),
      stat(250, "TRADES", streak, GREEN if n_red==0 else TXT),
      stat(470, "OPEN", f"{opn} ({usign}${abs(upl):,.2f})"),
      stat(690, "WIN RATE", f"{(n_green/n_tr*100 if n_tr else 0):.0f}%"),
      f'<polygon points="{area}" fill="url(#fill)"/>',
      f'<polyline points="{line}" fill="none" stroke="{ACC}" stroke-width="2.5"/>',
      f'<circle cx="{xs[-1]:.1f}" cy="{ys[-1]:.1f}" r="4" fill="{ACC}"/>',
      f'<text x="40" y="290" font-size="11" fill="#6e7681">range-sized wide-stop ratchet · engage +7.5 → lock +5 → trail 2.5 fixed · OANDA practice · broker-verified · updated {now.strftime("%Y-%m-%d %H:%M UTC")}</text>',
      '</svg>\n',
    ]
    SVG.write_text("".join(parts))
except Exception as e:
    print(f"livelog: card svg skipped ({e})", file=sys.stderr)

# ── badge row (shields.io static, regenerated each run) ───────────────────────
def badge(label, msg, color):
    enc = lambda s: (str(s).replace("-", "--").replace("_", "__").replace(" ", "_")
                     .replace("%", "%25").replace("$", "%24").replace("+", "%2B"))
    return f"https://img.shields.io/badge/{enc(label)}-{enc(msg)}-{color}?style=flat-square"
b_pl   = badge("P/L", f"{tsign}${abs(tot):,.2f} ({pct:+.2f}%)", "3fb950" if tot>=0 else "f85149")
b_tr   = badge("trades", f"{n_green}/{n_tr} green" if n_red else f"{n_tr} · 100% green", "3fb950")
b_open = badge("open", f"{opn} ({usign}${abs(upl):,.0f})", "58a6ff")
b_live = badge("status", "LIVE", "3fb950")

# ── README block ──────────────────────────────────────────────────────────────
rec = f"{n_green}/{n_tr} green" + (f" ({n_red} red)" if n_red else ", 100% green so far")
block = (
    f"<!-- LIVE_BALANCE_START -->\n"
    f'<div align="center">\n\n'
    f"![status]({b_live}) ![P/L]({b_pl}) ![trades]({b_tr}) ![open]({b_open})\n\n"
    f"[![live track record](livelog/equity.svg)](livelog/trades.csv)\n\n"
    f"</div>\n\n"
    f"> **Live track record of the *current* configuration** — {ANCHOR_LABEL}, live since {ANCHOR_HUMAN}, "
    f"auto-updated hourly from **broker-verified fills** ([trades](livelog/trades.csv) · [equity](livelog/equity.csv)). "
    f"Small sample, honest record. Prior configs and the −84% research tuition are a different story — "
    f"[read the history](docs/SCROOGE_HISTORY.md). Practice account, not real money.\n"
    f"<!-- LIVE_BALANCE_END -->")
txt = README.read_text()
new = re.sub(r"<!-- LIVE_BALANCE_START -->.*?<!-- LIVE_BALANCE_END -->", block, txt, flags=re.S)
if new != txt: README.write_text(new)

# ── commit + push if changed ──────────────────────────────────────────────────
os.chdir(REPO)
subprocess.run(["git", "add", "livelog", "README.md"], check=False)
if subprocess.run(["git", "diff", "--cached", "--quiet"]).returncode != 0:
    msg = f"livelog: current config {rsign}${abs(realized):,.2f} realized / {n_tr} trades ({rec}), NAV ${nav:,.2f} @ {now.strftime('%Y-%m-%dT%H:%MZ')}"
    subprocess.run(["git", "commit", "-q", "-m", msg,
                    "-m", "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"], check=False)
    subprocess.run(["git", "push", "-q"], check=False)
    print(f"livelog: pushed — {n_tr} trades, {rsign}${abs(realized):,.2f} realized, NAV ${nav:,.2f}")
else:
    print("livelog: no change")
