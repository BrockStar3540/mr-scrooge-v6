"""B-140: graduation must survive one phantom full stop.

An all-green record has no spread, so its t-LCB equals its mean and six
+8p cycles graduated to full size automatically. Graduation now also needs
mean(cycles + [-stop]) > 0: the cycles must have banked more than one stop.
"""
from core.family_cycle import edge_lcb
from ops.governor import DEFAULT_CFG, book, graduation_ready, phantom_stop_cleared

CFG = dict(DEFAULT_CFG, cheater_graduate_cycles=6, graduate_phantom_stop=True,
           phantom_stop_default_pips=60.0)
SMALL_WINS = [7.0, 8.0, 6.0, 9.0, 7.0, 8.0]      # +45p, t-LCB +6.9


def test_six_small_wins_no_longer_graduate():
    assert edge_lcb(SMALL_WINS) > 0                # the old gate passes
    assert not phantom_stop_cleared(SMALL_WINS, 60.0, CFG)
    assert not graduation_ready(SMALL_WINS, edge_lcb(SMALL_WINS), 60.0, CFG)


def test_record_that_banked_more_than_a_stop_graduates():
    cyc = [12.0] * 6                               # +72p > one 60p stop
    assert graduation_ready(cyc, edge_lcb(cyc), 60.0, CFG)


def test_uses_the_setups_own_stop():
    cyc = [8.0] * 6                                # +48p
    assert not graduation_ready(cyc, 8.0, 50.0, CFG)
    assert graduation_ready(cyc, 8.0, 40.0, CFG)   # 48 > 40


def test_missing_stop_falls_back_to_default():
    cyc = [11.0] * 6                               # +66p
    assert phantom_stop_cleared(cyc, None, CFG)
    assert not phantom_stop_cleared(cyc, None, dict(CFG, phantom_stop_default_pips=70.0))


def test_exactly_one_stop_is_not_enough():
    assert not phantom_stop_cleared([10.0] * 6, 60.0, CFG)


def test_switch_off_restores_old_rule():
    off = dict(CFG, graduate_phantom_stop=False)
    assert graduation_ready(SMALL_WINS, edge_lcb(SMALL_WINS), 60.0, off)


def test_old_gates_still_apply():
    assert not graduation_ready([30.0] * 5, 30.0, 60.0, CFG)      # too few cycles
    assert not graduation_ready([30.0] * 6, -1.0, 60.0, CFG)      # LCB not positive
    assert not phantom_stop_cleared([], 60.0, CFG)


def test_book_carries_the_stop():
    assert any(m.get("sl_pips") for m in book().values())
