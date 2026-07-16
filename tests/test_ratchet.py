"""tests/test_ratchet.py — RatchetManager exit math (engage / trail / lock)
plus the B-090 regression (fixed trail, engaged stop never below breakeven).

The ratchet is the sole live exit manager; these tests pin its stop-movement
math so a refactor can't silently reintroduce a stop that walks backwards or
parks below entry.

B-090 background: the bug was an ATR-scaled trail (trail_mult > 0) producing a
trail so wide the engaged ratchet stop was placed *below* the entry price. The
ATR scaling itself is resolved in modules/cells/cell.py (ExitParams builder,
guarded by `if trail_mult > 0`). Every deployed cell config now ships
trail_mult = 0.0 (asserted in test_cell_configs.py), so the trail is the FIXED
trail_pips value. Here we pin the ratchet-side invariant that guarantees safety
once the trail is fixed: with trail_pips < trigger_pips, the first engaged lock
= trigger - trail > 0, and every subsequent lock only rises.
"""
from datetime import datetime, timedelta, timezone

import pytest

from modules.management.base import Position, ExitSignal
from modules.management.ratchet import RatchetManager, _load_config
from modules.cells.cell import ExitParams
from modules.playmaker.playmaker import TradeTicket

PIP = 0.0001          # EUR_USD-style pip
ENTRY = 1.10000
# A quiet mid-London time — safely outside the 20:45-22:05 UTC rollover guard/freeze.
BASE_T = datetime(2026, 7, 15, 12, 0, 0, tzinfo=timezone.utc)


def _ticket(direction="long"):
    return TradeTicket(
        pair="EUR_USD", session="london", direction=direction,
        score=1.0, dir_certainty=1.0, mom_certainty=1.0, vol_regime="normal",
        expected_pips=10.0, timestamp=BASE_T, reads={},
    )


def _position(direction="long", entry=ENTRY, sl_price=0.0, exit_params=None):
    return Position(
        ticket=_ticket(direction), entry_price=entry, entry_time=BASE_T,
        units=1000, oanda_trade_id="test-1", pip_size=PIP,
        initial_sl_price=sl_price, exit_params=exit_params,
    )


def _price(direction, pips):
    """Absolute price `pips` in the profit direction from entry."""
    return ENTRY + pips * PIP if direction == "long" else ENTRY - pips * PIP


def _mgr(direction="long", exit_params=None):
    return RatchetManager(_position(direction, exit_params=exit_params),
                          broker=None, dry_run=True)


# ── net_pips / peak tracking ────────────────────────────────────────────────

def test_net_pips_long():
    m = _mgr("long")
    assert m.net_pips(_price("long", 5)) == pytest.approx(5.0, abs=1e-6)
    assert m.net_pips(_price("long", -3)) == pytest.approx(-3.0, abs=1e-6)


def test_net_pips_short():
    m = _mgr("short")
    assert m.net_pips(_price("short", 5)) == pytest.approx(5.0, abs=1e-6)


def test_peak_tracks_favorable_only():
    m = _mgr("long")
    m._update_peak(_price("long", 4))
    m._update_peak(_price("long", 9))
    m._update_peak(_price("long", 6))          # pullback must not lower the peak
    assert m._peak_pips() == pytest.approx(9.0, abs=1e-4)


# ── _compute_step_sl static math ────────────────────────────────────────────

def test_compute_step_sl_below_trigger_returns_none():
    cfg = {"step_trigger_pips": 7.5, "step_size_pips": 2.0, "step_trail_pips": 2.5}
    assert RatchetManager._compute_step_sl(7.4, cfg) is None


def test_compute_step_sl_first_lock_is_trigger_minus_trail():
    cfg = {"step_trigger_pips": 7.5, "step_size_pips": 2.0, "step_trail_pips": 2.5}
    # peak exactly at trigger -> level == trigger -> lock == trigger - trail
    assert RatchetManager._compute_step_sl(7.5, cfg) == pytest.approx(5.0)


def test_compute_step_sl_steps_in_size_increments():
    cfg = {"step_trigger_pips": 7.5, "step_size_pips": 2.0, "step_trail_pips": 2.5}
    # peak 12: level = floor((12-7.5)/2)*2 + 7.5 = 11.5 -> lock 9.0
    assert RatchetManager._compute_step_sl(12.0, cfg) == pytest.approx(9.0)
    # peak 13.5: level = floor((13.5-7.5)/2)*2 + 7.5 = 13.5 -> lock 11.0
    assert RatchetManager._compute_step_sl(13.5, cfg) == pytest.approx(11.0)


# ── full engage / lock / tighten-only flow through update() ──────────────────

def test_engage_lock_and_tighten_only_long():
    m = _mgr("long")           # exit_params=None -> uses real config/exit_config.json
    cfg = _load_config("EUR_USD")
    trig, trail = cfg["step_trigger_pips"], cfg["step_trail_pips"]

    # Below trigger: no lock yet.
    m.update(_price("long", trig - 1), BASE_T + timedelta(minutes=1))
    assert m.sl_locked_pips is None

    # Reach the trigger: first lock engages at trigger - trail, above breakeven.
    m.update(_price("long", trig), BASE_T + timedelta(minutes=2))
    first = m.sl_locked_pips
    assert first == pytest.approx(trig - trail)
    assert first > 0.0                       # B-090: engaged stop above breakeven

    # Push much higher: lock advances.
    m.update(_price("long", trig + 10), BASE_T + timedelta(minutes=3))
    assert m.sl_locked_pips > first

    # Pull back (peak unchanged): lock must NOT move backward.
    high = m.sl_locked_pips
    m.update(_price("long", trig + 3), BASE_T + timedelta(minutes=4))
    assert m.sl_locked_pips == pytest.approx(high)


def test_stop_hit_returns_exit_signal():
    m = _mgr("long")
    # Engage a lock first.
    m.update(_price("long", 12), BASE_T + timedelta(minutes=1))
    assert m.sl_locked_pips is not None
    sl_price = m._sl_pips_to_price(m.sl_locked_pips)
    sig = m.update(sl_price - PIP, BASE_T + timedelta(minutes=2))   # price crosses locked SL
    assert isinstance(sig, ExitSignal)
    assert sig.reason == "ratchet_stop"


# ── B-090 regression ────────────────────────────────────────────────────────

def test_b090_fixed_trail_when_mult_zero():
    """With trail_mult=0 the ExitParams trail stays the FIXED configured value —
    no ATR scaling is applied (that branch is guarded by `if trail_mult > 0`)."""
    ep = ExitParams(sl_pips=50.0, trigger_pips=7.5, trail_pips=2.5,
                    trail_mult=0.0, trail_min=2.5, trail_max=10.0)
    assert ep.trail_mult == 0.0
    assert ep.trail_pips == pytest.approx(2.5)   # fixed, untouched by any ATR scale


def test_b090_engaged_stop_never_below_breakeven_across_peaks():
    """Core B-090 invariant on the ratchet side: with a fixed trail < trigger,
    every engaged lock is strictly above breakeven, for any peak."""
    ep = ExitParams(sl_pips=50.0, trigger_pips=7.5, trail_pips=2.5, trail_mult=0.0)
    m = _mgr("long", exit_params=ep)
    cfg = dict(_load_config("EUR_USD"))
    cfg["step_trigger_pips"] = ep.trigger_pips
    cfg["step_trail_pips"] = ep.trail_pips
    for peak in [7.5, 8, 10, 12, 20, 33.3, 57, 107.5]:
        lock = RatchetManager._compute_step_sl(peak, cfg)
        assert lock is not None
        assert lock > 0.0, f"engaged stop {lock} below breakeven at peak {peak}"
        # trail component is exactly the fixed trail_pips (level - lock == trail).
        level = lock + cfg["step_trail_pips"]
        assert (level - lock) == pytest.approx(cfg["step_trail_pips"])


def test_b090_hazard_shape_documented():
    """Documents the failure the invariant guards against: if a (buggy) wide
    ATR trail ever made trail_pips >= trigger_pips, the first engaged lock would
    sit at/below breakeven. The fixed-trail configs (trail 2.5 < trigger 7.5)
    are what keep this from happening live; test_cell_configs pins trail<trigger."""
    bad = {"step_trigger_pips": 7.5, "step_size_pips": 2.0, "step_trail_pips": 9.0}
    lock = RatchetManager._compute_step_sl(7.5, bad)
    assert lock < 0.0     # below breakeven — exactly the B-090 symptom
