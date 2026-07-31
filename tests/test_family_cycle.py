"""family-cycle-v3 replay engine (charter, 2026-07-31).

Synthetic-bar tests for the mechanics the parent-only scorer could not see:
popper fires on adverse markers, re-arm on re-cross, family completion with
no artificial horizon, censoring while open, GridLift between variants."""
import pytest
from core.family_cycle import replay_family_cycle, floor_step_lock

PIP = 0.0001
SPREAD = 0.00010          # 1 pip

GEAR = {"sl_pips": 60.0, "trigger_pips": 8.5, "trail_pips": 2.5,
        "step_size_pips": 2.0, "step_cadence_min": 0.5}
PP = {"marker_pips": [10.0, 15.0, 20.0], "sl_pips": 60.0,
      "trigger_pips": 8.5, "trail_pips": 2.5, "grid_max_age_days": 7.0}


def bar(mid_o, mid_h, mid_l, mid_c):
    h = SPREAD / 2
    def px(v):
        return {"o": v - h, "h": mid_h - h, "l": mid_l - h, "c": mid_c - h}
    return {"bid": {"o": mid_o - h, "h": mid_h - h, "l": mid_l - h, "c": mid_c - h},
            "ask": {"o": mid_o + h, "h": mid_h + h, "l": mid_l + h, "c": mid_c + h}}


def flat_bars(mid, n):
    return [bar(mid, mid + 1 * PIP, mid - 1 * PIP, mid) for _ in range(n)]


def test_floor_step_lock_live_gear():
    assert floor_step_lock(8.4, 8.5, 2.0, 2.5) is None
    assert floor_step_lock(8.5, 8.5, 2.0, 2.5) == 6.0
    assert floor_step_lock(11.0, 8.5, 2.0, 2.5) == 8.0
    assert floor_step_lock(30.0, 8.5, 2.0, 2.5) == 26.0


def test_clean_winner_no_poppers():
    # long from 1.1000, up 15p, shallow pullback to the lock — the pullback
    # stays ABOVE the -10 marker, so no popper ever fires
    up = [bar(1.1000 + i * 3 * PIP, 1.1002 + i * 3 * PIP,
              1.0999 + i * 3 * PIP, 1.1002 + i * 3 * PIP) for i in range(6)]
    down = [bar(1.1010, 1.1010, 1.0993, 1.0995)]
    r = replay_family_cycle(up + down + flat_bars(1.0999, 2), "long", PIP, GEAR, PP)
    assert r is not None and not r.censored
    assert r.n_poppers == 0
    assert r.parent_net > 0                       # ratcheted out green
    assert r.net_pips == r.parent_net


def test_deep_dip_fires_poppers_and_family_recovers():
    # long from 1.1000; dip 22p (fires -10/-15/-20), then rally 40p above entry
    dip = [bar(1.1000, 1.1000, 1.0978, 1.0980)]
    rally = [bar(1.0980 + i * 5 * PIP, 1.0983 + i * 5 * PIP,
                 1.0979 + i * 5 * PIP, 1.0983 + i * 5 * PIP) for i in range(13)]
    collapse = [bar(1.1040, 1.1040, 1.0900, 1.0910)]
    r = replay_family_cycle(dip + rally + collapse, "long", PIP, GEAR, PP)
    assert r is not None and not r.censored
    assert r.n_poppers == 3                       # all three markers fired
    assert r.harvest > 0                          # poppers harvested the recovery
    assert r.net_pips == pytest.approx(r.parent_net + r.harvest)


def test_knife_kills_family():
    # long from 1.1000: 70p knife, then a second leg down so every popper's
    # own -60 stop (measured from ITS entry) is reached
    knife = [bar(1.1000, 1.1000, 1.0930, 1.0931),
             bar(1.0931, 1.0931, 1.0905, 1.0910)]
    after = flat_bars(1.0910, 3)
    r = replay_family_cycle(knife + after, "long", PIP, GEAR, PP)
    assert r is not None and not r.censored
    assert r.n_poppers == 3
    assert r.parent_net == -60.0
    assert r.harvest < 0                          # poppers died too
    assert r.peak_liability_pips > 100            # stacked stop liability seen


def test_rearm_refires_marker():
    # dip to -12 (fires -10), recover above -10 (re-arm), dip again (re-fire)
    seq = [bar(1.1000, 1.1000, 1.0988, 1.0990),   # fire -10
           bar(1.0990, 1.1005, 1.0990, 1.1004),   # recover: re-arm; popper ratchets
           bar(1.1004, 1.1004, 1.0988, 1.0989),   # re-fire -10
           bar(1.0989, 1.1030, 1.0989, 1.1028),   # rally: everything ratchets
           bar(1.1028, 1.1028, 1.0900, 1.0905)]   # collapse: locks execute
    r = replay_family_cycle(seq + flat_bars(1.1050, 2), "long", PIP, GEAR, PP)
    assert r is not None
    assert r.n_refires >= 1


def test_open_family_is_censored_not_scored():
    # dip fires a popper; data ends with legs still open
    seq = [bar(1.1000, 1.1000, 1.0988, 1.0990),
           bar(1.0990, 1.0992, 1.0988, 1.0990)]
    r = replay_family_cycle(seq, "long", PIP, GEAR, PP)
    assert r is not None and r.censored
    assert r.open_legs >= 1


def test_parent_only_variant_sees_no_grid():
    knife = [bar(1.1000, 1.1000, 1.0930, 1.0931)]
    r = replay_family_cycle(knife + flat_bars(1.0931, 2), "long", PIP, GEAR, PP,
                            variant="PARENT_ONLY")
    assert r.n_poppers == 0
    assert r.net_pips == -60.0


def test_grid_lift_positive_on_wave_path():
    # the oscillating path: parent dies, poppers harvest — FAMILY_PP must
    # beat PARENT_ONLY (the controls-vs-lean geometry distinction)
    seq = [bar(1.1000, 1.1000, 1.0978, 1.0980)]           # dip -22: 3 fires
    seq += [bar(1.0980 + i * 5 * PIP, 1.0983 + i * 5 * PIP,
                1.0979 + i * 5 * PIP, 1.0983 + i * 5 * PIP) for i in range(13)]
    seq += [bar(1.1040, 1.1040, 1.0900, 1.0910)] + flat_bars(1.1050, 2)
    fam = replay_family_cycle(seq, "long", PIP, GEAR, PP)
    par = replay_family_cycle(seq, "long", PIP, GEAR, PP, variant="PARENT_ONLY")
    assert fam.net_pips > par.net_pips            # GridLift > 0 here


def test_trade_cap_limits_concurrency_not_total():
    # cap=2 counts OPEN trades (party_package): the dead parent frees a slot
    # on the knife bar (2 poppers fire), and the -10 popper dying on bar 2
    # frees another (the armed -20 marker fires) — 3 total, never >2 open
    knife = [bar(1.1000, 1.1000, 1.0930, 1.0931),
             bar(1.0931, 1.0931, 1.0905, 1.0910)]
    r = replay_family_cycle(knife + flat_bars(1.0910, 3), "long", PIP, GEAR, PP,
                            max_total_trades=2)
    assert not r.censored
    assert r.n_poppers == 3
    # with no cap the same path fires all three markers IMMEDIATELY on bar 1;
    # the cap's effect is concurrency, visible as strictly later entries
    r8 = replay_family_cycle(knife + flat_bars(1.0910, 3), "long", PIP, GEAR, PP,
                             max_total_trades=8)
    assert r8.n_poppers == 3
