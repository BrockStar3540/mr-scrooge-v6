"""tests/test_gear_5_4.py — operator gear 2026-10-28 (Brock).

Spec, from the operator: "engage at +5 and lock in +4, then ratchet up every
2+ locking. so at +7 lock in +5, at +9 lock in +7. do the same with the
poppers."

Also pins the popper loader bug it exposed: pp_config() dropped every key not
in _DEFAULTS, so engage_pips/engage_lock_pips in config/pp_config.json never
reached a popper (08-18 -> 10-28).
"""
import json
from pathlib import Path

import pytest

from core.shadow_execution import _ratchet_lock
from modules.management.ratchet import RatchetManager

ROOT = Path(__file__).resolve().parents[1]
GEAR = {"step_trigger_pips": 7.0, "step_size_pips": 2.0,
        "step_trail_pips": 2.0, "step_engage_pips": 5.0,
        "step_engage_lock_pips": 4.0}
SPEC = [(4.9, None), (5.0, 4.0), (6.9, 4.0), (7.0, 5.0), (8.9, 5.0),
        (9.0, 7.0), (11.0, 9.0), (20.0, 17.0)]


@pytest.mark.parametrize("peak,want", SPEC)
def test_live_manager_matches_operator_spec(peak, want):
    assert RatchetManager._compute_step_sl(peak, GEAR) == want


@pytest.mark.parametrize("peak,want", SPEC)
def test_simulator_matches_operator_spec(peak, want):
    assert _ratchet_lock(peak, trigger=7.0, step=2.0, trail=2.0,
                         engage=5.0, engage_lock=4.0) == want


def test_popper_loader_keeps_engage_keys():
    from modules.management.party_package import pp_config, _popper_exit_params
    cfg = pp_config()
    raw = json.loads((ROOT / "config" / "pp_config.json").read_text())
    assert cfg["engage_pips"] == raw["engage_pips"] == 5.0
    assert cfg["engage_lock_pips"] == raw["engage_lock_pips"] == 4.0
    ep = _popper_exit_params(cfg)
    assert (ep.trigger_pips, ep.trail_pips, ep.engage_pips, ep.engage_lock_pips) == (7.0, 2.0, 5.0, 4.0)


def test_every_pp_config_key_survives_the_loader():
    """No silent drops: every non-note key in the file is honoured."""
    from modules.management.party_package import pp_config
    raw = json.loads((ROOT / "config" / "pp_config.json").read_text())
    cfg = pp_config()
    dropped = [k for k in raw if not k.startswith("_") and k not in cfg]
    assert dropped == []


def test_standard_setups_all_on_deployed_gear():
    """Every standard-gear setup carries 7/2 + 5->4; only custom (t20s) gear differs."""
    seen = 0
    for f in sorted((ROOT / "config" / "cells").glob("*.json")):
        for s in json.loads(f.read_text())["sessions"].values():
            for su in s.get("setups", []):
                e = su.get("exit") or {}
                g = (e.get("trigger_pips"), e.get("trail_pips"), e.get("engage_pips"), e.get("engage_lock_pips"))
                assert g != (9.0, 2.0, 7.5, 6.0), f"{f.name} {su['id']} still on the 08-18 gear"
                seen += g == (7.0, 2.0, 5.0, 4.0)
    assert seen > 0


def test_recovered_parent_never_arms_a_new_grid():
    """2026-10-28: a restart armed a popper grid for a recovered USD_CAD parent
    whose setup has poppers off in every session (session reads "recovery")."""
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from modules.management.party_package import PartyPackage
    pp = PartyPackage.__new__(PartyPackage)
    pp.grids, pp.dry_run = {}, False
    pp._save_state = lambda: None
    pos = SimpleNamespace(ticket=SimpleNamespace(pair="USD_CAD", session="recovery", direction="short"),
                          entry_price=1.40380, entry_time=datetime(2026, 10, 27, 15, 53, tzinfo=timezone.utc),
                          oanda_trade_id="39438")
    pp.on_parent_open(pos, setup_id="echo_box_fade_short")
    assert pp.grids == {}
