"""tests/test_deflation_test.py — the DSR / PBO-CSCV implementation behind
issue #9 (research/deflation/PREREGISTRATION.md).

The statistics are checked against their definitions and against synthetic
books with a known answer: pure noise must overfit about half the time, a
book with one real edge must not, and more trials must deflate harder.
"""
import math

import numpy as np
import pytest

from research.tools import deflation_test as dt


def test_expected_max_sr_matches_monte_carlo():
    rng = np.random.default_rng(7)
    n, var = 200, 0.04
    sims = rng.normal(0, math.sqrt(var), size=(4000, n)).max(axis=1).mean()
    assert dt.expected_max_sr(n, var) == pytest.approx(sims, rel=0.03)


def test_expected_max_sr_grows_with_trials_and_is_zero_for_one():
    assert dt.expected_max_sr(1, 0.05) == 0.0
    assert dt.expected_max_sr(10, 0.05) < dt.expected_max_sr(1701, 0.05)


def test_psr_is_half_at_the_benchmark_and_dsr_falls_with_n():
    assert dt.psr(0.2, 0.2, 60, 0.0, 3.0) == pytest.approx(0.5)
    sr0_small = dt.expected_max_sr(10, 0.02)
    sr0_big = dt.expected_max_sr(1701, 0.02)
    assert dt.psr(0.3, sr0_big, 60, 0, 3) < dt.psr(0.3, sr0_small, 60, 0, 3)


def test_psr_matches_bailey_formula_with_fat_tails():
    sr, sr0, t, g3, g4 = 0.15, 0.05, 250, -1.2, 9.0
    z = (sr - sr0) * math.sqrt(t - 1) / math.sqrt(1 - g3 * sr + (g4 - 1) / 4 * sr * sr)
    assert dt.psr(sr, sr0, t, g3, g4) == pytest.approx(dt._N.cdf(z))


def test_moments_normal_kurtosis_is_about_three():
    x = np.random.default_rng(1).normal(size=20000)
    _, _, _, g3, g4 = dt.moments(x)
    assert abs(g3) < 0.1 and g4 == pytest.approx(3.0, abs=0.15)


def test_participation_ratio_bounds():
    assert dt.participation_ratio(np.eye(5)) == pytest.approx(5.0)
    assert dt.participation_ratio(np.ones((5, 5))) == pytest.approx(1.0)


def test_contiguous_blocks_cover_every_row_once():
    b = dt.contiguous_blocks(61, 16)
    assert len(b) == 16
    assert np.concatenate(b).tolist() == list(range(61))


def _book(T=96, N=60, edge=None, seed=3):
    rng = np.random.default_rng(seed)
    R = rng.normal(0, 10, size=(T, N))
    if edge is not None:
        R[:, edge] += 6.0
    E_n = np.ones_like(R)
    return R, E_n, R.copy()


BAR = {"min_raw_episodes": 10, "min_independent_days": 5, "bar_avg": 2.0,
       "lcb_min": 0.0, "fdr_q": 0.10, "bootstrap_confidence": 0.95}


def test_pbo_of_pure_noise_is_near_one_half():
    R, E_n, E_sum = _book()
    bs = dt.BlockStats(R, E_n, E_sum, dt.contiguous_blocks(R.shape[0], 8))
    out = dt.cscv(bs, 8, 3, BAR, with_bar=False)
    assert out["splits"] == 70
    assert 0.2 <= out["pbo_max_sr"] <= 0.8


def test_pbo_of_a_book_with_one_real_edge_is_low_and_bar_finds_it():
    R, E_n, E_sum = _book(edge=11)
    bs = dt.BlockStats(R, E_n, E_sum, dt.contiguous_blocks(R.shape[0], 8))
    out = dt.cscv(bs, 8, 3, BAR)
    assert out["pbo_max_sr"] < 0.1
    assert out["pbo_bar"] < 0.1
    sel, _ = bs.bar(list(range(8)), BAR)
    assert 11 in sel.tolist()


def test_bar_replica_respects_counting_gates():
    R, E_n, E_sum = _book(T=16, N=4, edge=0)
    E_n[:, 0] = 0
    E_n[:3, 0] = 1               # only 3 day-blocks fired: below the 5-day gate
    E_sum[:, 0] = np.where(E_n[:, 0] > 0, 50.0, 0.0)
    bs = dt.BlockStats(R, E_n, E_sum, dt.contiguous_blocks(16, 4))
    sel, docket = bs.bar([0, 1, 2, 3], BAR)
    assert 0 not in sel.tolist()


def test_build_matrix_alive_window_and_zero_fill():
    days = ["2026-08-01", "2026-08-02", "2026-08-03", "2026-08-04"]
    eps = {"A|ny|x": [("2026-08-02", 5.0), ("2026-08-02", -1.0)],
           "B|ny|y": [("2026-08-04", 2.0)]}
    R, E_n, E_sum = dt.build_matrix(eps, ["A|ny|x", "B|ny|y"], days,
                                    {"A|ny|x": "2026-08-01T00:00", "B|ny|y": "2026-08-03T09:00"},
                                    {"A|ny|x": "2026-08-03T12:00"})
    assert R[:, 0].tolist()[:3] == [0.0, 4.0, 0.0] and math.isnan(R[3, 0])
    assert math.isnan(R[0, 1]) and R[2, 1] == 0.0 and R[3, 1] == 2.0
    assert E_n[1, 0] == 2 and E_sum[1, 0] == 4.0


def test_bh_is_the_governors():
    from core.trial_evidence import benjamini_hochberg
    assert dt.benjamini_hochberg is benjamini_hochberg
