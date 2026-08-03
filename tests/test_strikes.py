"""tests/test_strikes.py — STRIKE RULE (2026-08-03, operator).

Every executed demotion is a permanent strike. Ever-demoted cells promote
only over the stricter redemption bar (20 raw episodes / 10 independent
days); the strike that reaches strike_disable_count retires the cell to
DISABLED — untouchable by automation, manual re-enable only.
"""
import json
from pathlib import Path

from core.trial_evidence import (SetupEvidence, promotion_predicate,
                                 required_bar, current_era_evidence)
from ops.governor import DEFAULT_CFG, demote_target

CFG = {"min_raw_episodes": 10, "min_independent_days": 5, "bar_avg": 2.0,
       "lcb_min": 0.0, "recent_n": 5, "recent_min": 0.0, "fdr_q": 0.05,
       "redemption_min_raw_episodes": 20, "redemption_min_independent_days": 10,
       "strike_disable_count": 3}


def _ev(n, days, strikes=0):
    return SetupEvidence(key=("EUR_USD", "london", "x"), raw_n=n,
                         effective_n=float(n), independent_days=days,
                         net_avg=5.0, recent_n=0, recent_avg=None,
                         block_lcb=1.0, p_value=0.01, q_value=0.01,
                         strikes=strikes)


def test_required_bar_first_offender_vs_struck():
    assert required_bar(CFG, 0) == (10, 5)
    assert required_bar(CFG, 1) == (20, 10)
    assert required_bar(CFG, 7) == (20, 10)   # forever, not decaying


def test_first_offender_passes_relaxed_bar():
    ok, codes = promotion_predicate(_ev(12, 6), CFG)
    assert ok and not codes


def test_struck_setup_held_to_redemption_bar():
    ok, codes = promotion_predicate(_ev(12, 6, strikes=1), CFG)
    assert not ok
    assert "RAW_N" in codes and "INDEPENDENT_DAYS" in codes


def test_struck_setup_can_clear_redemption_bar():
    ok, codes = promotion_predicate(_ev(20, 10, strikes=2), CFG)
    assert ok and not codes


def test_three_strikes_disables():
    assert demote_target(0, CFG) == ("SHADOW", 1)
    assert demote_target(1, CFG) == ("SHADOW", 2)
    assert demote_target(2, CFG) == ("DISABLED", 3)
    assert demote_target(9, CFG) == ("DISABLED", 10)   # past the limit stays out


def test_default_cfg_carries_strike_keys():
    assert DEFAULT_CFG["strike_disable_count"] == 3
    assert DEFAULT_CFG["redemption_min_raw_episodes"] == 20
    assert DEFAULT_CFG["redemption_min_independent_days"] == 10


def test_shipped_config_carries_strike_keys():
    cfg = json.loads((Path(__file__).parents[1]
                      / "config" / "governor_config.json").read_text())
    assert cfg["strike_disable_count"] == 3
    assert cfg["redemption_min_raw_episodes"] == 20
    assert cfg["redemption_min_independent_days"] == 10


def test_current_era_evidence_wires_strikes_from_state():
    episodes = {
        f"e{i}": {"cell": "EUR_USD/london", "setup": "x", "side": "short",
                  "t": f"2026-07-{10+i:02d}T09:00:00+00:00",
                  "scores": {"mv": 2, "net240": 12.0}, "spread": 0.6}
        for i in range(12)
    }
    book = {("EUR_USD", "london", "x"): {"status": "SHADOW", "side": "short",
                                         "cfg_hash": None}}
    state = {"era_start": {},
             "demotion_counts": {"EUR_USD|london|x": 1}}
    ev = current_era_evidence(episodes, book, state, CFG)
    e = ev[("EUR_USD", "london", "x")]
    assert e.strikes == 1
    # 12 episodes / 12 days clears the relaxed 10/5 bar but NOT redemption 20/10
    assert not e.promotable
    assert "RAW_N" in e.reason_codes
