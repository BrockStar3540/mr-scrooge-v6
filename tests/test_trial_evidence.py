"""tests/test_trial_evidence.py — D-7 stage D: block bootstrap, BH-FDR, and
the single shared promotion predicate."""
from datetime import datetime, timezone

import pytest

from core.trial_evidence import (BlockInference, SetupEvidence,
                                 TrialObservation, benjamini_hochberg,
                                 block_bootstrap_mean, current_era_evidence,
                                 promotion_predicate)

KEY = ("EUR_USD", "london", "s1")


def _obs(day, net, sess="london"):
    return TrialObservation(key=KEY, timestamp=f"2026-07-{day:02d}T10:00:00+00:00",
                            block_id=f"2026-07-{day:02d}|{sess}", net_pips=net,
                            metric_version="executable-exit-v2")


# ── block bootstrap ──────────────────────────────────────────────────────────

def test_single_block_yields_no_bounds():
    b = block_bootstrap_mean([_obs(1, 5.0), _obs(1, 7.0)])
    assert b.independent_blocks == 1
    assert b.lcb is None and b.p_value is None
    assert b.mean == pytest.approx(6.0)


def test_bootstrap_is_deterministic():
    obs = [_obs(d, n) for d, n in zip(range(1, 13), [4, -2, 6, 3, 5, -1,
                                                     7, 2, 4, 3, 6, 1])]
    a = block_bootstrap_mean(obs, reps=3000)
    b = block_bootstrap_mean(obs, reps=3000)
    assert a == b, "same evidence must always yield the same bounds"


def test_consistent_edge_clears_zero():
    obs = [_obs(d, 4.0 + (d % 3)) for d in range(1, 15)]
    b = block_bootstrap_mean(obs, reps=3000)
    assert b.independent_blocks == 14
    assert b.lcb is not None and b.lcb > 0
    assert b.p_value < 0.01


def test_noise_does_not_clear_zero():
    obs = [_obs(d, 8.0 if d % 2 else -8.5) for d in range(1, 13)]
    b = block_bootstrap_mean(obs, reps=3000)
    assert b.lcb is None or b.lcb <= 0 or b.p_value > 0.05


def test_blocks_group_within_day():
    # 40 episodes on TWO days = 2 independent blocks, not 40
    obs = [_obs(1, 3.0)] * 20 + [_obs(2, 4.0)] * 20
    b = block_bootstrap_mean(obs, reps=1000)
    assert b.independent_blocks == 2


# ── BH-FDR ───────────────────────────────────────────────────────────────────

def test_bh_known_values():
    q = benjamini_hochberg({"a": 0.01, "b": 0.02, "c": 0.5})
    assert q["a"] == pytest.approx(0.03)
    assert q["b"] == pytest.approx(0.03)
    assert q["c"] == pytest.approx(0.5)


def test_bh_monotone_and_capped():
    q = benjamini_hochberg({"a": 0.04, "b": 0.9, "c": 0.5, "d": 1.0})
    assert q["a"] <= q["c"] <= q["b"] <= q["d"] <= 1.0


def test_bh_single_hypothesis_unchanged():
    assert benjamini_hochberg({"a": 0.03})["a"] == pytest.approx(0.03)


# ── the shared predicate ─────────────────────────────────────────────────────

CFG = {"min_raw_episodes": 20, "min_independent_days": 10, "bar_avg": 2.0,
       "lcb_min": 0.0, "recent_n": 5, "recent_min": 0.0, "fdr_q": 0.05}


def _ev(**over):
    base = dict(key=KEY, raw_n=24, effective_n=18.0, independent_days=11,
                net_avg=3.2, recent_n=6, recent_avg=1.0, block_lcb=0.8,
                p_value=0.004, q_value=0.031)
    base.update(over)
    return SetupEvidence(**base)


def test_predicate_full_pass():
    ok, why = promotion_predicate(_ev(), CFG)
    assert ok and why == ()


@pytest.mark.parametrize("over,code", [
    (dict(raw_n=19), "RAW_N"),
    (dict(independent_days=9), "INDEPENDENT_DAYS"),
    (dict(net_avg=1.9), "AVG"),
    (dict(block_lcb=0.0), "LCB"),
    (dict(block_lcb=None), "LCB"),
    (dict(recent_avg=-0.5), "RECENT"),
    (dict(q_value=0.06), "FDR"),
    (dict(q_value=None), "FDR"),
])
def test_predicate_failure_codes(over, code):
    ok, why = promotion_predicate(_ev(**over), CFG)
    assert not ok and code in why


def test_predicate_recent_needs_sample():
    # a thin recent window (n < recent_n) must not veto
    ok, why = promotion_predicate(_ev(recent_n=3, recent_avg=-5.0), CFG)
    assert ok


# ── current_era_evidence ─────────────────────────────────────────────────────

def _episode(day, net240, mv=2, mech="h1", side="long", t_hour=10, setup="s1"):
    e = {"cell": "EUR_USD/london", "setup": setup, "side": side,
         "status": "SHADOW",
         "t": f"2026-07-{day:02d}T{t_hour:02d}:00:00+00:00",
         "spread": 2.0,
         "scores": {"net240": net240, "mfe240": 10, "mae240": 3}}
    if mv == 2:
        e["scores"]["mv"] = 2
        e["mech"] = mech
    return e


BOOK = {KEY: {"status": "SHADOW", "side": "long", "manual_only": False,
              "cfg_hash": "h1"}}
GCFG = dict(CFG, slippage_pips=0.5, bootstrap_reps=1500,
            default_era_start="2026-07-01T00:00:00+00:00")
NOW = datetime(2026, 7, 28, tzinfo=timezone.utc)


def test_evidence_counts_only_v2_matching_mechanics():
    eps = {f"a{d}": _episode(d, 5.0) for d in range(1, 13)}
    eps["legacy"] = _episode(14, 50.0, mv=1)            # legacy-mid-v1: out
    eps["stale"] = _episode(15, 50.0, mech="OLD")       # mechanics changed: out
    eps["wrongside"] = _episode(16, 50.0, side="short") # side mismatch: out
    ev = current_era_evidence(eps, BOOK, {}, GCFG, now=NOW)
    assert ev[KEY].raw_n == 12
    assert ev[KEY].independent_days == 12
    assert ev[KEY].net_avg == pytest.approx(4.5)   # 5.0 − 0.5 slippage only


def test_evidence_respects_era_clock():
    eps = {f"a{d}": _episode(d, 5.0) for d in range(1, 13)}
    state = {"era_start": {"EUR_USD|london|s1": "2026-07-10T00:00:00+00:00"}}
    ev = current_era_evidence(eps, BOOK, state, GCFG, now=NOW)
    assert ev[KEY].raw_n == 3   # days 10, 11, 12 only


def test_evidence_promotable_end_to_end():
    # 22 episodes over 11 days, consistent +5 gross → promotable
    eps = {}
    for d in range(10, 21):
        eps[f"m{d}"] = _episode(d, 5.0, t_hour=9)
        eps[f"n{d}"] = _episode(d, 6.0, t_hour=12)
    ev = current_era_evidence(eps, BOOK, {}, GCFG, now=NOW)
    e = ev[KEY]
    assert e.raw_n == 22 and e.independent_days == 11
    assert e.q_value is not None and e.q_value <= 0.05
    assert e.promotable, e.reason_codes


def test_evidence_thin_sample_not_promotable():
    eps = {f"a{d}": _episode(d, 5.0) for d in range(1, 6)}
    ev = current_era_evidence(eps, BOOK, {}, GCFG, now=NOW)
    assert not ev[KEY].promotable
    assert "RAW_N" in ev[KEY].reason_codes
