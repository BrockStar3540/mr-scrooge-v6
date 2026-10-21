from datetime import datetime, timezone

from ops.rolling_winrate import rolling_table, window_stats

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)


def row(day, usd):
    return [f"2026-10-{day:02d}T10:00:00Z", "EUR_USD", "long", "1000", f"{usd}", "parent"]


ROWS = [row(1, 5.0), row(2, -10.0), row(16, 3.0), row(20, 2.0), row(21, -1.0)]


def test_all_time_counts_every_row():
    assert window_stats(ROWS, NOW) == (5, 3, -1.0)


def test_window_cut_is_by_close_time():
    n, w, net = window_stats(ROWS, NOW, 7)   # cut 10-14 12:00 -> 16th, 20th, 21st
    assert (n, w) == (3, 2) and abs(net - 4.0) < 1e-9


def test_zero_realized_is_not_a_win():
    assert window_stats([row(20, 0.0)], NOW) == (1, 0, 0.0)


def test_table_rows_and_trend_arrows():
    t = rolling_table(ROWS, NOW).splitlines()
    assert t[2].startswith("| **All-time** | 5 | **60.0%**")
    assert len(t) == 3 + 5                     # header, rule, all-time, 5 windows
    seven = next(l for l in t if l.startswith("| Last 7 days"))
    assert "**66.7%**" in seven and "▲ +6.7 pts" in seven and "+$4.00" in seven


def test_empty_window_renders_dashes():
    t = rolling_table([row(1, 5.0)], NOW)
    assert "| Last 7 days | 0 | — | — | — |" in t
