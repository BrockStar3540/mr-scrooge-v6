"""tests/test_trial_stats.py — D-6 statistics corrections."""
import pytest

from core.trial_stats import (cost_adjusted_nets, default_spread,
                              effective_n, lcb)


def _iso(minute):
    return f"2026-07-28T{minute // 60:02d}:{minute % 60:02d}:00+00:00"


# ── effective_n ──────────────────────────────────────────────────────────────

def test_effective_n_fully_independent_episodes_count_fully():
    times = [_iso(m) for m in (0, 240, 480, 720)]     # 4h apart = no overlap
    assert effective_n(times) == 4.0


def test_effective_n_dense_episodes_shrink():
    # 8 episodes 30 min apart, all inside one 240m label window:
    # 1 + 7 * (30/240) = 1.875 effective observations, not 8
    times = [_iso(30 * i) for i in range(8)]
    assert effective_n(times) == pytest.approx(1.88, abs=0.01)


def test_effective_n_empty_and_single():
    assert effective_n([]) == 0.0
    assert effective_n([_iso(0)]) == 1.0


# ── cost adjustment ──────────────────────────────────────────────────────────

def test_cost_uses_stamped_spread_when_present():
    nets = cost_adjusted_nets([10.0, 10.0], [1.2, None], "EUR_USD",
                              slippage_pips=0.5)
    assert nets[0] == pytest.approx(10.0 - 1.2 - 0.5)
    assert nets[1] == pytest.approx(10.0 - 1.5 - 0.5)   # USD-major fallback


def test_cross_pairs_pay_the_cross_fallback():
    nets = cost_adjusted_nets([10.0], [None], "CAD_JPY", slippage_pips=0.5)
    assert nets[0] == pytest.approx(10.0 - 3.0 - 0.5)
    assert default_spread("GBP_CAD") == 3.0
    assert default_spread("USD_JPY") == 1.5


# ── deflated, overlap-aware LCB ──────────────────────────────────────────────

def test_lcb_uses_effective_n_not_raw_n():
    vals = [5.0, 7.0, 6.0, 8.0, 6.5, 7.5, 5.5, 6.0]
    wide = lcb(vals, n_eff=8.0, z=2.33)
    tight = lcb(vals, n_eff=2.0, z=2.33)
    assert wide is not None and tight is not None
    assert tight < wide, "shrinking the effective n must widen the bound"


def test_lcb_no_sample_returns_none():
    assert lcb([5.0], n_eff=1.0, z=2.33) is None
    assert lcb([5.0, 6.0], n_eff=1.0, z=2.33) is None


def test_higher_z_is_stricter():
    vals = [3.0, 4.0, 2.5, 3.5, 4.5, 3.0]
    assert lcb(vals, 6.0, z=2.33) < lcb(vals, 6.0, z=1.645)
