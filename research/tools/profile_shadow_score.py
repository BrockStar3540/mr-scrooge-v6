#!/usr/bin/env python3
"""Score the corrected-profile shadow: parse SHADOW_PROFILE journal lines,
pull the 1H forward from OANDA M5, and report live-stack vs corrected-stack
mean signed forward pips per (pair, session) — plus who won the disagreements.

Companion to modules/signals/profile_shadow.py (2026-07-02 shadow dual-stamp
of the 2026-audit corrected profile assignment, mostly reversion). Run on EC2
(has OANDA token + journalctl) every few days as lines accumulate. When the
corrected stack beats live on ~2 weeks of settled calls, take the result to
Brock before flipping any live profiles.

Line format (engine _cycle, one per pair per scan cycle on disagreement-or-nonblock):
  SHADOW_PROFILE GBP_USD/ny live=short/-0.312/0.55 corr=long/+0.207/0.48 \\
    ts=2026-07-02T18:05:00+00:00

Scoring model: signed 1H forward pip per stack (block = no call = 0.0 in
disagreement scoring, excluded from the stack's mean). Gross of spread — both
stacks would pay the same spread, so the comparison is spread-neutral.

Usage:
  profile_shadow_score.py [--since YYYY-MM-DD]
"""
import argparse, bisect, json, os, re, subprocess, urllib.parse, urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.join(_os.path.dirname(__file__), "..", ".."))
from config.pairs import PIP  # canonical 18-pair map (B-108: no more private copies)
FWD_BARS = 12          # 12 x M5 = 60 min forward
SETTLE_S = 3900        # need 60 min + buffer before a call is scoreable

for ln in open(os.path.expanduser("~/.openclaw/secrets.env")):
    if "=" in ln and not ln.strip().startswith("#"):
        k, v = ln.strip().split("=", 1); os.environ[k.strip()] = v.strip().strip('"').strip("'")
TOKEN = os.environ["OANDA_API_TOKEN"]
BASE  = os.environ.get("OANDA_API_URL", "https://api-fxtrade.oanda.com")

RX = re.compile(r"SHADOW_PROFILE (\w+)/(\w+) "
                r"live=(\w+)/([+-][\d.]+)/([\d.]+) "
                r"corr=(\w+)/([+-][\d.]+)/([\d.]+) ts=(\S+)")


def parse_journal(since: str) -> list[dict]:
    raw = subprocess.run(
        ["journalctl", "--user", "-u", "mr-scrooge-v6", "--since", since, "--no-pager", "-o", "cat"],
        env={**os.environ, "XDG_RUNTIME_DIR": f"/run/user/{os.getuid()}", "SYSTEMD_PAGER": ""},
        capture_output=True, text=True).stdout
    sigs = []
    for line in raw.splitlines():
        m = RX.search(line)
        if m:
            pair, sess, lb, ls, lc, cb, cs, cc, ts = m.groups()
            sigs.append({"pair": pair, "session": sess,
                         "live_bias": lb, "live_score": float(ls), "live_cert": float(lc),
                         "corr_bias": cb, "corr_score": float(cs), "corr_cert": float(cc),
                         "ts": datetime.fromisoformat(ts)})
    return sigs


def fetch_m5_series(pair: str, start: datetime, end: datetime) -> tuple[list[datetime], list[float]]:
    """Paginated M5 mid-close series covering [start, end] (5000-candle chunks)."""
    times: list[datetime] = []
    closes: list[float] = []
    cur = start
    while cur < end:
        url = f"{BASE}/v3/instruments/{pair}/candles?" + urllib.parse.urlencode({
            "from": cur.isoformat().replace("+00:00", "Z"),
            "granularity": "M5", "price": "M", "count": 5000})
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {TOKEN}"})
        data = json.loads(urllib.request.urlopen(req, timeout=30).read())
        cs = [c for c in data.get("candles", []) if c.get("complete")]
        if not cs:
            break
        for c in cs:
            t = datetime.fromisoformat(c["time"].replace("Z", "+00:00"))
            if not times or t > times[-1]:
                times.append(t); closes.append(float(c["mid"]["c"]))
        last = datetime.fromisoformat(cs[-1]["time"].replace("Z", "+00:00"))
        if last <= cur:
            break
        cur = last
    return times, closes


def signed(bias: str, fwd: float) -> float | None:
    """Signed forward pip for one stack's call; None when the stack said block."""
    if bias == "long":  return fwd
    if bias == "short": return -fwd
    return None


def main():
    ap = argparse.ArgumentParser(description="Score SHADOW_PROFILE lines vs OANDA 1H forward")
    ap.add_argument("--since", default="2026-07-02", help="journalctl --since (YYYY-MM-DD)")
    args = ap.parse_args()

    sigs = parse_journal(args.since)
    print(f"SHADOW_PROFILE lines parsed: {len(sigs)}")
    if not sigs:
        print("No shadow-profile lines yet. They appear once per pair per scan cycle when the")
        print("live and corrected stacks disagree on bias or either is non-block. Re-run later.")
        return

    now = datetime.now(timezone.utc)
    settled = [s for s in sigs if (now - s["ts"]).total_seconds() >= SETTLE_S]
    print(f"Settled (1H forward available): {len(settled)}")
    if not settled:
        print("Lines exist but none settled yet (need 60min+ elapsed). Re-run later.")
        return

    # One paginated candle fetch per pair covering all its signals
    by_pair: dict[str, list[dict]] = defaultdict(list)
    for s in settled:
        by_pair[s["pair"]].append(s)

    rows = []
    for pair, ss in sorted(by_pair.items()):
        t0 = min(s["ts"] for s in ss) - timedelta(minutes=10)
        t1 = max(s["ts"] for s in ss) + timedelta(minutes=75)
        times, closes = fetch_m5_series(pair, t0, t1)
        if len(times) < FWD_BARS + 1:
            print(f"  {pair}: insufficient candles ({len(times)}) — skipped")
            continue
        for s in ss:
            i = bisect.bisect_right(times, s["ts"]) - 1   # last bar at/before ts
            if i < 0 or i + FWD_BARS >= len(closes):
                continue
            fwd = (closes[i + FWD_BARS] - closes[i]) / PIP[pair]
            rows.append({**s, "fwd_60m": round(fwd, 2),
                         "live_pip": signed(s["live_bias"], fwd),
                         "corr_pip": signed(s["corr_bias"], fwd)})

    print(f"Scored against OANDA 1H forward: {len(rows)}")
    if not rows:
        return

    import statistics as st
    print("\n=== SHADOW_PROFILE RESULTS per (pair, session) ===")
    by_cell: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        by_cell[(r["pair"], r["session"])].append(r)
    for (pair, sess), rs in sorted(by_cell.items()):
        live = [r["live_pip"] for r in rs if r["live_pip"] is not None]
        corr = [r["corr_pip"] for r in rs if r["corr_pip"] is not None]
        dis  = [r for r in rs if r["live_bias"] != r["corr_bias"]]
        # Disagreement scoring: block = flat = 0.0
        corr_w = sum(1 for r in dis if (r["corr_pip"] or 0.0) > (r["live_pip"] or 0.0))
        live_w = sum(1 for r in dis if (r["live_pip"] or 0.0) > (r["corr_pip"] or 0.0))
        print(f"\n  {pair}/{sess}  (n={len(rs)} scored lines)")
        print(f"    live stack:  {len(live):3d} calls  mean fwd {st.mean(live):+.2f}p" if live
              else "    live stack:    0 calls (all block)")
        print(f"    corr stack:  {len(corr):3d} calls  mean fwd {st.mean(corr):+.2f}p" if corr
              else "    corr stack:    0 calls (all block)")
        print(f"    disagreements: {len(dis)}  -> corrected won {corr_w}, live won {live_w}, "
              f"ties {len(dis) - corr_w - live_w}")

    out = "/tmp/profile_shadow_results.json"
    json.dump([{**r, "ts": r["ts"].isoformat()} for r in rows], open(out, "w"), indent=2, default=str)
    print(f"\n-> {out}")


if __name__ == "__main__":
    main()
