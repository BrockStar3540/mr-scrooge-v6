"""ops/rolling_winrate.py — rolling win-rate table for the README live block.

All-time plus the last 90/60/30/15/7 days of closed live trades, so the README
shows the trend, not just the lifetime average. Pure: takes the livelog trade
rows ([close_utc, instrument, direction, units, realized_usd, source]) and a
clock, returns markdown. A win is realized_usd > 0, the same rule as the card.
"""
from datetime import datetime, timedelta

WINDOWS = (90, 60, 30, 15, 7)


def _ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def window_stats(rows, now, days=None):
    """(trades, wins, net_usd) for rows closed in the last `days` (None = all)."""
    cut = None if days is None else now - timedelta(days=days)
    n = wins = 0
    net = 0.0
    for r in rows:
        if cut is not None and _ts(r[0]) < cut:
            continue
        v = float(r[4])
        n += 1
        wins += v > 0
        net += v
    return n, wins, net


def rolling_table(rows, now):
    """Markdown table: window · trades · win rate · vs all-time · net P/L."""
    n_all, w_all, net_all = window_stats(rows, now)
    wr_all = w_all / n_all * 100 if n_all else 0.0

    def usd(x):
        return f"{'+' if x >= 0 else '−'}${abs(x):,.2f}"

    out = ["| Window | Trades | Win rate | vs all-time | Net P/L |",
           "|---|---:|---:|---:|---:|",
           f"| **All-time** | {n_all} | **{wr_all:.1f}%** | — | {usd(net_all)} |"]
    for d in WINDOWS:
        n, w, net = window_stats(rows, now, d)
        if not n:
            out.append(f"| Last {d} days | 0 | — | — | — |")
            continue
        wr = w / n * 100
        diff = wr - wr_all
        arrow = "▲" if diff > 0.05 else "▼" if diff < -0.05 else "＝"
        out.append(f"| Last {d} days | {n} | **{wr:.1f}%** | {arrow} {f'{diff:+.1f}'.replace('-', '−')} pts | {usd(net)} |")
    return "\n".join(out)
