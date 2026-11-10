"""Rollover windows follow New York 17:00, not a fixed UTC clock."""
from datetime import datetime, timezone
from modules.management.base import in_rollover_freeze, in_rollover_guard_window

U = lambda y, mo, d, h, mi: datetime(y, mo, d, h, mi, tzinfo=timezone.utc)

def test_summer_edt():
    assert in_rollover_guard_window(U(2026, 8, 10, 20, 46)) and not in_rollover_guard_window(U(2026, 8, 10, 21, 46))
    assert in_rollover_freeze(U(2026, 8, 10, 20, 56)) and in_rollover_freeze(U(2026, 8, 10, 21, 30))
    assert not in_rollover_freeze(U(2026, 8, 10, 22, 6)) and not in_rollover_freeze(U(2026, 8, 10, 20, 54))

def test_winter_est():
    assert in_rollover_guard_window(U(2026, 11, 3, 21, 46)) and not in_rollover_guard_window(U(2026, 11, 3, 20, 46))
    assert in_rollover_freeze(U(2026, 11, 3, 21, 56)) and in_rollover_freeze(U(2026, 11, 3, 22, 30)) and in_rollover_freeze(U(2026, 11, 3, 23, 4))
    assert not in_rollover_freeze(U(2026, 11, 3, 20, 56)) and not in_rollover_freeze(U(2026, 11, 3, 23, 6))

def test_naive_is_utc():
    assert in_rollover_freeze(datetime(2026, 11, 3, 22, 10)) == in_rollover_freeze(U(2026, 11, 3, 22, 10))
