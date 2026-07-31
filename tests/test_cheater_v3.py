"""Cheater v3 (charter, 2026-07-31): the risk-covered family-cycle ticket.

Every gate exists to stop one freak episode buying a seat; the policy
selector selects the management mode the evidence actually supports."""
from ops.governor import cheater_v3_predicate, cheater_v3_policy

C = {"cheater_min_cycles": 3, "cheater_min_days": 2,
     "cheater_min_positive_cycles": 2, "cheater_min_risk_covered_gain": 1.25,
     "cheater_min_harvest_coverage": 1.20, "cheater_max_single_cycle_share": 0.60,
     "cheater_require_flat": True}


def R(**kw):
    base = {"cycles": 4, "days": 3, "u_list": [0.5, 0.4, 0.3, 0.2],
            "last_censored": False, "U_pp": 0.35, "U_par": 0.10}
    base.update(kw)
    return base


def test_clean_pass():
    ok, why = cheater_v3_predicate(R(), C)
    assert ok and "CS=+1.40R" in why


def test_one_freak_cycle_cannot_buy_a_seat():
    # +2.0R total but 80% from one cycle: share gate kills it
    ok, why = cheater_v3_predicate(R(u_list=[1.6, 0.2, 0.2, 0.0]), C)
    assert not ok and "60%" in why


def test_cs_threshold_is_hard():
    ok, why = cheater_v3_predicate(R(u_list=[0.5, 0.4, 0.3, 0.06]), C)
    assert ok                                        # CS = 1.26 clears 1.25
    ok, why = cheater_v3_predicate(R(u_list=[0.5, 0.4, 0.3, 0.04]), C)
    assert not ok and "CS" in why                    # CS = 1.24 misses by 0.01


def test_open_cycle_blocks_when_flat_required():
    ok, why = cheater_v3_predicate(R(last_censored=True), C)
    assert not ok and "open" in why


def test_needs_two_positive_and_two_days():
    ok, _ = cheater_v3_predicate(R(u_list=[2.0, -0.1, -0.1, -0.1]), C)
    assert not ok
    ok, why = cheater_v3_predicate(R(days=1), C)
    assert not ok and "days" in why


def test_coverage_gate_with_prior():
    ok, _ = cheater_v3_predicate(R(u_list=[0.5, 0.5, 0.5, -0.1]), C)
    assert ok                            # cov = (1.5+.5)/(0.1+.5) = 3.33
    # high-churn shape: CS=+1.30 clears, but coverage (8.8/7.5)=1.17 < 1.20 —
    # the gate catches gain built on huge gross-loss churn
    ok, why = cheater_v3_predicate(
        R(cycles=6, u_list=[2.4, 2.0, 2.0, 1.9, -3.5, -3.5]), C)
    assert not ok and "coverage" in why


def test_policy_selector_grid_lift():
    assert cheater_v3_policy({"U_pp": 0.4, "U_par": 0.1,
                              "grid_lift_lcb": 0.05}) == "FAMILY_PP"
    # strong parent, harmful grid -> seat WITHOUT poppers
    assert cheater_v3_policy({"U_pp": -0.2, "U_par": 0.3,
                              "grid_lift_lcb": -0.1}) == "PARENT_ONLY"
    # both negative -> no seat regardless of the predicate
    assert cheater_v3_policy({"U_pp": -0.2, "U_par": -0.1,
                              "grid_lift_lcb": -0.1}) == "NONE"
    assert cheater_v3_policy({"U_pp": None, "U_par": None}) == "NONE"
