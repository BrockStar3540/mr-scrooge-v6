"""tests/test_deflation_sensitivity.py — the post-hoc closed-market
sensitivity for issue #9 (research/tools/deflation_sensitivity.py).

The closed-market window must match the live scorer's M5-gap test in both
DST regimes, and the dropped count must only count episodes the deflation
run would have used.
"""
import math

import pytest

from research.tools import deflation_sensitivity as ds


@pytest.mark.parametrize("t,closed", [
    # summer (EDT): last M5 bar opens Fri 20:55Z, first opens Sun 21:00Z
    ("2026-10-16T20:55:00+00:00", False),
    ("2026-10-16T20:56:00+00:00", True),
    ("2026-10-17T13:03:51+00:00", True),     # Saturday session-start cluster
    ("2026-10-18T20:45:00+00:00", True),     # Sunday stale-quote stamps
    ("2026-10-18T21:00:00+00:00", False),
    ("2026-10-19T12:00:00+00:00", False),
    # winter (EST): one hour later in UTC
    ("2026-11-13T21:30:00+00:00", False),
    ("2026-11-13T21:56:00+00:00", True),
    ("2026-11-15T21:30:00+00:00", True),
    ("2026-11-15T22:00:00+00:00", False),
])
def test_closed_market_window_tracks_new_york_close(t, closed):
    assert ds.is_closed_market(t) is closed


def test_saturday_filter_is_utc_saturday_only():
    assert ds.is_saturday("2026-10-17T00:00:00+00:00")
    assert not ds.is_saturday("2026-10-16T23:59:00+00:00")
    assert not ds.is_saturday("2026-10-18T13:00:00Z")


def test_split_counts_only_episodes_the_run_would_use():
    eps = {
        "a": {"t": "2026-10-17T07:00:00+00:00", "scores": {"mv": 2, "net240": -3.0}},
        "b": {"t": "2026-10-17T07:00:00+00:00", "scores": {"mv": 2, "net240": None}},
        "c": {"t": "2026-10-17T07:00:00+00:00", "scores": {"mv": 1, "net240": 4.0}},
        "d": {"t": "2026-10-19T07:00:00+00:00", "scores": {"mv": 2, "net240": 1.0}},
    }
    kept, dropped = ds.split_episodes(eps, ds.is_saturday)
    assert set(kept) == {"d"} and dropped == 1


def test_rank_pct_inverts_the_cscv_logit():
    assert ds.rank_pct(0.0) == pytest.approx(0.5)
    w = 0.5865
    assert ds.rank_pct(math.log(w / (1 - w))) == pytest.approx(w)
