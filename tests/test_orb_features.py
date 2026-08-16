"""tests/test_orb_features.py — session opening-range feature (v6.28.0).

Synthetic bars, pip=1.0 (structure-features convention). The critical
property under test is FAIL-CLOSED FORMATION: orb_range_pips must be 0.0
until the session run has 3 confirmed M5 bars, because every ORB setup gates
on `orb_range_pips min` — a forming range must veto, silently firing on a
1-bar "range" would be a B-128-class defect in reverse.
"""
from core.feed.structure import session_orb

PIP = 1.0


def _mk(run_len, prior=10):
    """prior bars of session 0, then run_len bars of session 1.
    Session-1 ORB bars: highs 105,107,106 lows 95,97,96 -> ORB 107/95."""
    labels = [0] * prior + [1] * run_len
    highs = [100.0] * prior + [105.0, 107.0, 106.0, 104.0, 103.0][:run_len]
    lows = [90.0] * prior + [95.0, 97.0, 96.0, 99.0, 100.0][:run_len]
    while len(highs) < len(labels):
        highs.append(103.0); lows.append(100.0)
    return labels, highs, lows


def test_forming_range_is_fail_closed():
    for run in (1, 2):
        labels, hi, lo = _mk(run)
        d_hi, d_lo, pos, rng = session_orb(labels, hi, lo, 101.0, PIP)
        assert rng == 0.0 and pos == 0.5 and d_hi == 0.0 and d_lo == 0.0


def test_formed_range_arithmetic():
    labels, hi, lo = _mk(4)
    d_hi, d_lo, pos, rng = session_orb(labels, hi, lo, 101.0, PIP)
    assert rng == 12.0                    # 107 - 95
    assert d_hi == -6.0                   # 101 - 107
    assert d_lo == 6.0                    # 101 - 95
    assert pos == 0.5                     # (101-95)/12

def test_orb_freezes_after_first_three_bars():
    # bar 4 makes a higher high (110) — ORB must NOT expand
    labels, hi, lo = _mk(5)
    hi[-2] = 110.0
    _, _, _, rng = session_orb(labels, hi, lo, 101.0, PIP)
    assert rng == 12.0


def test_new_session_resets_the_range():
    labels, hi, lo = _mk(5)
    labels += [2, 2, 2]                   # next session begins
    hi += [200.0, 202.0, 201.0]
    lo += [190.0, 192.0, 191.0]
    d_hi, d_lo, pos, rng = session_orb(labels, hi, lo, 196.0, PIP)
    assert rng == 12.0                    # 202 - 190
    assert d_lo == 6.0                    # 196 - 190
    assert 0.0 < pos < 1.0


def test_breakout_position_exceeds_one():
    labels, hi, lo = _mk(4)
    _, _, pos, rng = session_orb(labels, hi, lo, 113.0, PIP)
    assert rng == 12.0 and pos == 1.5     # 6 pips above the high


def test_degenerate_inputs_are_neutral():
    assert session_orb([], [], [], 100.0, PIP) == (0.0, 0.0, 0.5, 0.0)
    labels, hi, lo = _mk(4)
    assert session_orb(labels, hi, lo, 101.0, 0.0) == (0.0, 0.0, 0.5, 0.0)
