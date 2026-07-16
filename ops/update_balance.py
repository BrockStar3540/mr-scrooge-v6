#!/usr/bin/env python3
"""Rewrite the live-balance line in README.md from the running dashboard.

Called by the pre-commit hook (ops/hooks/pre-commit) so every push carries the
current practice-account NAV. Fails SOFT: if the dashboard is unreachable the
README is left untouched and the commit proceeds.
"""
import json, os, re, sys, urllib.request
from datetime import datetime, timezone
from pathlib import Path

README = Path(__file__).resolve().parents[1] / "README.md"
PORT = os.environ.get("DASHBOARD_PORT", "8084")

try:
    with urllib.request.urlopen(f"http://localhost:{PORT}/api/state", timeout=5) as r:
        acct = json.load(r)["account"]
except Exception as e:
    print(f"update_balance: dashboard unreachable ({e}) — README left as-is", file=sys.stderr)
    sys.exit(0)

now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
trades = int(acct.get("open_trades", 0))
line = (f"**Live practice-account NAV: ${acct['nav']:,.2f}** · "
        f"{trades} open trade{'' if trades == 1 else 's'} · as of {now} "
        f"*(auto-updated on every push)*")
text = README.read_text()
new = re.sub(r"<!-- LIVE_BALANCE_START -->.*?<!-- LIVE_BALANCE_END -->",
             f"<!-- LIVE_BALANCE_START -->\n{line}\n<!-- LIVE_BALANCE_END -->",
             text, flags=re.S)
if new != text:
    README.write_text(new)
    print("update_balance: README NAV line refreshed")
