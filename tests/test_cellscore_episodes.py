"""B-115: the Setup Scoreboard must count EPISODES, not stamps.

One four-hour runaway move re-stamps every scan cycle -> dozens of stamps
riding one trade. Stamp-level counting read a single +71p EUR_JPY afternoon
as "78 trades, 100% WR" (true episode record: 15 episodes, 8W/7L)."""
from datetime import datetime, timedelta, timezone
from research.tools.cell_setup_score import collapse_episodes


def ts(minutes):
    return datetime(2026, 7, 30, 10, 0, tzinfo=timezone.utc) + timedelta(minutes=minutes)


def test_cluster_collapses_to_one_episode():
    # a 4-hour runaway stamping every 5 minutes = ONE decision
    stamps = [ts(m) for m in range(0, 240, 5)]
    assert collapse_episodes(stamps) == [ts(0)]


def test_gap_over_30min_starts_new_episode():
    stamps = [ts(0), ts(5), ts(40), ts(45), ts(120)]
    assert collapse_episodes(stamps) == [ts(0), ts(40), ts(120)]


def test_exactly_30min_is_same_episode_and_31_is_not():
    assert collapse_episodes([ts(0), ts(30)]) == [ts(0)]
    assert collapse_episodes([ts(0), ts(31)]) == [ts(0), ts(31)]


def test_empty_and_single():
    assert collapse_episodes([]) == []
    assert collapse_episodes([ts(7)]) == [ts(7)]
