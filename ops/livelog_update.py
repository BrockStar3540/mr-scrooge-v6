#!/usr/bin/env python3
"""ops/livelog_update.py — the public live track record for the CURRENT config.

Runs on EC2 (has the OANDA token via ~/.openclaw/secrets.env). Tracks the
REAL-MONEY account's performance since the live cutover (2026-07-29, $2,500
stake), executed per the pre-registered protocol after the 100-trade practice
window closed at +10.54% (docs/FORWARD_TEST_100_REPORT.md). The practice-era
record is archived at forward-test-100/ and is immutable.

Headline = realized P/L of trades closed under this config (the honest record),
plus current open trades. The OANDA token NEVER leaves EC2 and NEVER enters the
repo; published output is numbers only (no account id, no token). REAL money.
Fail-soft: OANDA unreachable → files untouched, exit 0.

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

# LIVE ERA (2026-07-29): the real-money account, cut over per the pre-registered
# protocol after the 100-trade practice window closed at +10.54%. Same code,
# same book, gearing 15%/trade · 6 max for the smaller stake. The practice
# record is archived at forward-test-100/.
ANCHOR_TS = "2026-07-29T11:00:00Z"
ANCHOR_LABEL = "range-sized wide-stop ratchet · SL 40/50/60 · engage +8.5 → lock +6 → trail 2.5 fixed + Party Package popper grids · 15%/trade · 6 max"
ANCHOR_HUMAN = "2026-07-29"

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
    # (direction, source) per trade id. Strategy (B-091 follow-up: per-trade GETs
    # rate-limited -> "?" rows): persistent cache + ONE batch closed-trades call;
    # per-trade GET only as last resort. Trade metadata is immutable, so cached
    # entries never expire (unknown "?" entries are retried).
    _META_F = LIVELOG / ".trade_meta_cache.json"
    try:
        _trade_meta_cache = {k: tuple(v) for k, v in json.load(open(_META_F)).items()
                             if v[0] != "?" and v[1] != "?"}
    except Exception:
        _trade_meta_cache = {}
    def _absorb(tr):
        tid = str(tr.get("id", ""))
        iu = float(tr.get("initialUnits", 0) or 0)
        d = "long" if iu > 0 else "short" if iu < 0 else "?"
        tag = (tr.get("clientExtensions") or {}).get("tag", "")
        _base = str(tag or "").split(";", 1)[0]
        src = "popper" if _base == "pp_v1" else "parent" if _base == "cell_v1" else "-"
        _trade_meta_cache[tid] = (d, src)
    # PRIMARY meta source: the OPENING fills in the same transaction window.
    # tradeOpened carries tradeID + units sign + clientExtensions.tag — no extra
    # API calls, and immune to the trades-endpoint retention quirk (some closed
    # trade ids 404 on /trades/{id} yet are fully present in transactions).
    for t in txns:
        if t.get("type") != "ORDER_FILL":
            continue
        to = t.get("tradeOpened")
        if to:
            _absorb({"id": to.get("tradeID"), "initialUnits": to.get("units"),
                     "clientExtensions": to.get("clientExtensions")})
    try:  # secondary: open trades batch (covers pre-window opens still running)
        for tr in api(f"/v3/accounts/{ACCT}/trades?state=OPEN&count=500").get("trades", []):
            _absorb(tr)
    except Exception as e:
        print(f"livelog: open-trades meta failed ({e})", file=sys.stderr)
    def _trade_meta(tid):
        if tid in _trade_meta_cache:
            return _trade_meta_cache[tid]
        d, src = "?", "?"
        try:
            tr = api(f"/v3/accounts/{ACCT}/trades/{tid}").get("trade", {})
            _absorb(tr)
            return _trade_meta_cache.get(tid, (d, src))
        except Exception:
            pass
        _trade_meta_cache[tid] = (d, src)
        return d, src
    # DEPOSIT-AWARE (2026-07-29): external transfers must never read as trading
    # P/L. Each TRANSFER_FUNDS since the anchor is collected with its timestamp;
    # the start balance backs them out, and the headline % uses a simple-Dietz
    # denominator (each deposit weighted by the fraction of the window it was
    # actually at work) so a deposit neither inflates nor dilutes the bot's %.
    transfers = []            # (iso_time, amount) — deposits +, withdrawals −
    for t in txns:
        if t.get("type") == "TRANSFER_FUNDS":
            transfers.append((t.get("time", ""), float(t.get("amount", 0))))
        if t.get("type") == "DAILY_FINANCING":
            financing += float(t.get("financing", t.get("amount", 0)))
        if t.get("type") == "ORDER_FILL" and float(t.get("pl", 0)) != 0 and t.get("time", "") >= ANCHOR_TS:
            realized += float(t["pl"])
            closed = t.get("tradesClosed") or t.get("tradesReduced") or []
            if not closed:   # fallback: one row from the fill itself, inverted sign
                u = float(t.get("units", 0))
                rows.append([t["time"][:19] + "Z", t.get("instrument", "?"),
                             "short" if u > 0 else "long", abs(int(u)),
                             f"{float(t['pl']):.2f}", "-"])
                continue
            for c in closed:   # one row PER CLOSED TRADE (a fill can close several)
                tid = c.get("tradeID", "")
                d, src = _trade_meta(tid)
                if d == "?":   # last resort: invert the closing fill's sign
                    u = float(c.get("units", t.get("units", 0)) or 0)
                    d = "short" if u > 0 else "long" if u < 0 else "?"
                    src = src if src != "?" else "-"
                rows.append([t["time"][:19] + "Z", t.get("instrument", "?"),
                             d, abs(int(float(c.get("units", 0)))),
                             f"{float(c.get('realizedPL', 0)):.2f}", src])
    rows.sort(key=lambda r: r[0])
    with open(TRADES, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["close_utc", "instrument", "direction", "units", "realized_usd", "source"])
        w.writerows(rows)
    try:
        _META_F.write_text(json.dumps({k: list(v) for k, v in _trade_meta_cache.items()}))
    except Exception:
        pass
    n_tr = len(rows); n_green = sum(1 for r in rows if float(r[4]) > 0); n_red = n_tr - n_green
    n_pop = sum(1 for r in rows if r[5] == "popper")
    wr = (n_green / n_tr * 100) if n_tr else 0.0
except Exception as e:
    print(f"livelog: trade rebuild failed ({e})", file=sys.stderr); sys.exit(0)

# (The 100-trade forward-test trigger lived here 07-28→07-29; the window
# closed at 99 natural trades + 2 operator close-outs — see
# docs/FORWARD_TEST_100_REPORT.md. The live era needs no endpoint flag.)

# starting balance at anchor, reconstructed & self-consistent — deposits and
# withdrawals since the anchor are backed OUT, so external money never reads
# as trading P/L.
net_transfers = sum(a for _, a in transfers)
start_bal = bal - realized - financing - net_transfers
tot = realized + upl  # config-to-date: booked greens + open marks — transfers never touch this
# Simple-Dietz capital base: start balance plus each transfer weighted by the
# fraction of the window it was actually invested. With zero transfers this is
# exactly start_bal (identical to the old formula).
_t0 = datetime.fromisoformat(ANCHOR_TS.replace("Z", "+00:00"))
_span = max((now - _t0).total_seconds(), 1.0)
_dietz = start_bal + sum(
    a * max(0.0, min(1.0, 1.0 - (datetime.fromisoformat(ts[:26].rstrip("Z") + "+00:00")
                                 - _t0).total_seconds() / _span))
    for ts, a in transfers if ts)
pct = (tot / _dietz * 100) if _dietz else 0.0

# ── equity snapshot (NAV over time, from first run forward) ───────────────────
new_eq = not EQUITY.exists()
with open(EQUITY, "a", newline="") as f:
    w = csv.writer(f)
    if new_eq: w.writerow(["utc", "nav", "balance", "unrealized_pl", "open_trades",
                           "realized_since_config", "net_deposits"])
    w.writerow([now.strftime("%Y-%m-%dT%H:%M:%SZ"), f"{nav:.2f}", f"{bal:.2f}", f"{upl:.2f}", opn,
                f"{realized:.2f}", f"{net_transfers:.2f}"])

rsign = "+" if realized >= 0 else "−"
usign = "+" if upl >= 0 else "−"
tsign = "+" if tot >= 0 else "−"
GREEN, RED, DIM, TXT = "#3fb950", "#f85149", "#7d8590", "#e6edf3"
ACC = GREEN if tot >= 0 else RED

# ── dashboard stat-card SVG (the eye-popper) ──────────────────────────────────
try:
    # B-116: chart on a TIME axis with BOTH curves — the old per-trade x-axis
    # froze the graph between closes while NAV moved all day, so a green
    # morning with 6 open trades looked like a stale chart. Bold line =
    # realized (steps at closes); thin blue = hourly NAV (includes open).
    _p = lambda s: datetime.fromisoformat(s.replace("Z", "+00:00"))
    t0 = _p(ANCHOR_TS); t1 = now if now > t0 else t0
    span = (t1 - t0).total_seconds() or 1.0
    cx0, cx1, cy0, cy1 = 40, 860, 208, 268
    def _x(t):
        frac = ((t if not isinstance(t, str) else _p(t)) - t0).total_seconds()/span
        return cx0 + max(0.0, min(1.0, frac))*(cx1-cx0)
    r_pts = [(t0, start_bal)]; run = start_bal
    for r in rows:
        run += float(r[4]); r_pts.append((_p(r[0]), run))
    r_pts.append((t1, run))
    n_pts = []
    try:
        with open(EQUITY) as _f:
            for _row in csv.DictReader(_f):
                try:
                    n_pts.append((_p(_row["utc"]), float(_row["nav"])))
                except (KeyError, ValueError):
                    continue
    except OSError:
        n_pts = []
    vals = [v for _, v in r_pts] + [v for _, v in n_pts]
    lo, hi = min(vals), max(vals); rng = (hi - lo) or 1
    def _y(v): return cy1 - (v-lo)/rng*(cy1-cy0)
    seg = [f"{_x(r_pts[0][0]):.1f},{_y(r_pts[0][1]):.1f}"]
    for _i in range(1, len(r_pts)):          # step shape: flat until the close
        _px = _x(r_pts[_i][0])
        seg.append(f"{_px:.1f},{_y(r_pts[_i-1][1]):.1f}")
        seg.append(f"{_px:.1f},{_y(r_pts[_i][1]):.1f}")
    line = " ".join(seg)
    area = f"{cx0},{cy1} " + line + f" {cx1},{cy1}"
    nav_line = " ".join(f"{_x(t):.1f},{_y(v):.1f}" for t, v in n_pts)
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
      f'<text x="98" y="47" font-size="14" fill="{DIM}" letter-spacing="1">· MR. SCROOGE — REAL MONEY</text>',
      f'<text x="862" y="47" font-size="12" fill="{DIM}" text-anchor="end">NAV ${nav:,.2f}</text>',
      f'<text x="38" y="118" font-size="66" font-weight="800" fill="{ACC}">{hero}</text>',
      f'<text x="{pct_x}" y="118" font-size="26" font-weight="700" fill="{ACC}">{"▲" if tot>=0 else "▼"} {pct:+.2f}%</text>',
      f'<text x="40" y="140" font-size="12" fill="{DIM}">config-to-date · realized + open, since {ANCHOR_HUMAN}</text>',
      stat(40,  "REALIZED", f"{rsign}${abs(realized):,.2f}", GREEN if realized>=0 else RED),
      stat(250, "TRADES", streak, GREEN if n_red==0 else TXT),
      stat(470, "OPEN", f"{opn} ({usign}${abs(upl):,.2f})"),
      stat(690, "WIN RATE", f"{(n_green/n_tr*100 if n_tr else 0):.0f}%"),
      f'<polygon points="{area}" fill="url(#fill)"/>',
      (f'<polyline points="{nav_line}" fill="none" stroke="#58a6ff" '
       f'stroke-width="1.4" opacity="0.9"/>' if n_pts else ''),
      f'<polyline points="{line}" fill="none" stroke="{ACC}" stroke-width="2.5"/>',
      f'<circle cx="{_x(t1):.1f}" cy="{_y(run):.1f}" r="4" fill="{ACC}"/>',
      (f'<circle cx="{_x(n_pts[-1][0]):.1f}" cy="{_y(n_pts[-1][1]):.1f}" r="3" '
       f'fill="#58a6ff"/>' if n_pts else ''),
      f'<text x="860" y="203" font-size="10" text-anchor="end" fill="{DIM}">'
      f'<tspan fill="{ACC}">━ realized</tspan>  <tspan fill="#58a6ff">─ NAV incl. open (hourly)</tspan></text>',
      f'<text x="40" y="290" font-size="11" fill="#6e7681">range-sized wide-stop ratchet · engage +8.5 → lock +6 → trail 2.5 · poppers · 15%/trade · OANDA LIVE — real money · broker-verified · updated {now.strftime("%Y-%m-%d %H:%M UTC")}</text>',
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
    + (f"> **Capital added since cutover: {'+' if net_transfers >= 0 else '−'}${abs(net_transfers):,.2f}** — "
       f"backed out of the record: deposits/withdrawals never count as trading P/L, and the headline % is "
       f"time-weighted against the capital actually at work.\n>\n" if abs(net_transfers) >= 0.01 else "")
    + f"> **🔴 REAL-MONEY track record** — ${2500:,} live stake since {ANCHOR_HUMAN}, cut over after the "
    f"[100-trade practice test](docs/FORWARD_TEST_100_REPORT.md) (+10.54%, pre-registered protocol). "
    f"{ANCHOR_LABEL} ({n_pop} popper trade{'' if n_pop==1 else 's'} in the record), auto-updated hourly from "
    f"**broker-verified fills** ([trades](livelog/trades.csv) · [equity](livelog/equity.csv)). Small sample, "
    f"honest record — some trades sit red for days under the wide stops before exiting green; that is the design, "
    f"not a malfunction. Prior configs and the −84% research tuition: [the history](docs/SCROOGE_HISTORY.md). "
    f"The concluded practice record is archived at [forward-test-100/](https://github.com/BrockStar3540/mr-scrooge-v6/tree/main/forward-test-100).\n"
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
    _push = subprocess.run(["git", "push", "-q"], check=False,
                           capture_output=True, text=True)
    if _push.returncode == 0:
        print(f"livelog: pushed — {n_tr} trades, {rsign}${abs(realized):,.2f} realized, NAV ${nav:,.2f}")
    else:
        # B-131: a blocked push used to print as success — 16 commits piled up
        # behind a red pre-push hook while this log said "pushed".
        print(f"livelog: COMMITTED but PUSH FAILED (rc={_push.returncode}): "
              f"{(_push.stderr or '').strip()[-300:]}", file=sys.stderr)
else:
    print("livelog: no change")
