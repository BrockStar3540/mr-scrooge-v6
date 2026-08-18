"""tests/test_two_phase_ratchet.py — v6.30.0 operator gear (2026-08-18).

Spec, verbatim from the operator: "start engaging at 7.5 from now on, locking
in 6.0+, and then when it goes to 9.0 lock in 7.0+ and so forth every 2+ lock
in, i.e. +11.0 lock in +9.0".

Encoded as: engage_pips 7.5 / engage_lock_pips 6.0 ahead of the floor-step
machine trigger 9.0 / step 2.0 / trail 2.0. The live manager and the shadow
simulator MUST stay formula-identical — the scorer replays what the money
does (parity test below sweeps both).
"""
import pytest

from core.shadow_execution import _ratchet_lock
from modules.management.ratchet import RatchetManager

GEAR = {"step_trigger_pips": 9.0, "step_size_pips": 2.0,
        "step_trail_pips": 2.0, "step_engage_pips": 7.5,
        "step_engage_lock_pips": 6.0}

# (peak, expected lock) — the operator's checkpoints plus boundaries
SPEC = [(7.4, None), (7.5, 6.0), (8.9, 6.0),
        (9.0, 7.0), (10.9, 7.0),
        (11.0, 9.0), (12.9, 9.0),
        (13.0, 11.0), (19.0, 17.0), (20.0, 17.0)]


@pytest.mark.parametrize("peak,want", SPEC)
def test_live_manager_matches_operator_spec(peak, want):
    assert RatchetManager._compute_step_sl(peak, GEAR) == want


@pytest.mark.parametrize("peak,want", SPEC)
def test_simulator_matches_operator_spec(peak, want):
    got = _ratchet_lock(peak, trigger=9.0, step=2.0, trail=2.0,
                        engage=7.5, engage_lock=6.0)
    assert got == want


def test_live_and_sim_parity_sweep():
    """Same lock at every 0.1p peak from 0 to 40 — sim IS the money's math."""
    for i in range(0, 401):
        peak = i / 10.0
        live = RatchetManager._compute_step_sl(peak, GEAR)
        sim = _ratchet_lock(peak, trigger=9.0, step=2.0, trail=2.0,
                            engage=7.5, engage_lock=6.0)
        assert live == sim, f"divergence at peak {peak}: live {live} sim {sim}"


def test_old_gear_unchanged_without_engage_keys():
    """engage=0 must be byte-identical to the single-phase formula (t20s twins
    and any custom-gear setup keep their exact old behaviour)."""
    old = {"step_trigger_pips": 8.5, "step_size_pips": 2.0,
           "step_trail_pips": 2.5}
    for peak, want in [(8.4, None), (8.5, 6.0), (10.4, 6.0),
                       (10.5, 8.0), (12.5, 10.0)]:
        assert RatchetManager._compute_step_sl(peak, old) == want
        assert _ratchet_lock(peak, 8.5, 2.0, 2.5) == want


def test_engage_never_loosens_the_step_lock():
    # at peak 13 the step lock (11.0) must win over the engage lock (6.0)
    assert RatchetManager._compute_step_sl(13.0, GEAR) == 11.0
