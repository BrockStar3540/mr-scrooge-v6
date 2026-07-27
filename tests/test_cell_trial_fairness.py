"""tests/test_cell_trial_fairness.py — every setup stamps, every cycle.

Regression for the 2026-07-27 external-review finding: CellModule.evaluate()
used to RETURN as soon as the first ACTIVE setup qualified, so later setups in
the cell were neither evaluated nor stamped that cycle. That starved the newest
shadows (always appended last) and biased the trial by config order.

The contract now: ALL setups evaluate and all qualifying setups emit a
CELLSHADOW stamp; the returned intent is the first qualifying ACTIVE.
"""
import logging
from datetime import datetime, timezone
from types import SimpleNamespace

from modules.cells.cell import CellModule


def _view(**feats):
    base = {"willr_m5": -50.0, "rsi14": 50.0, "atr_5m": 3.0}
    base.update(feats)
    return SimpleNamespace(**base)


def _cell(setups):
    return CellModule("EUR_USD", "london", {"enabled": True, "setups": setups})


def _setup(sid, status, side="long", feature="willr_m5", mx=0.0):
    return {"id": sid, "side": side, "status": status,
            "conditions": [{"feature": feature, "max": mx}],
            "exit": {"sl_pips": 50, "trigger_pips": 8.5, "trail_pips": 2.5},
            "evidence": {"ev_seq": 0.0}}


def _stamped_ids(caplog):
    out = []
    for rec in caplog.records:
        msg = rec.getMessage()
        if "CELLSHADOW" in msg:
            out.append(msg.split("setup=")[1].split()[0])
    return out


def test_active_qualifier_does_not_starve_later_setups(caplog, monkeypatch):
    monkeypatch.setattr("modules.cells.cell._exec_enabled", lambda: True)
    cell = _cell([
        _setup("first_active", "ACTIVE"),
        _setup("later_shadow", "SHADOW"),
        _setup("last_shadow", "SHADOW"),
    ])
    with caplog.at_level(logging.INFO):
        intent = cell.evaluate(_view(), datetime.now(timezone.utc))
    stamped = _stamped_ids(caplog)
    assert intent is not None and intent.setup_id == "first_active"
    assert stamped == ["first_active", "later_shadow", "last_shadow"], (
        "an ACTIVE qualifier must not suppress later setups' stamps")


def test_first_active_wins_but_second_active_still_stamps(caplog, monkeypatch):
    monkeypatch.setattr("modules.cells.cell._exec_enabled", lambda: True)
    cell = _cell([
        _setup("shadow_up_front", "SHADOW"),
        _setup("active_a", "ACTIVE"),
        _setup("active_b", "ACTIVE"),
    ])
    with caplog.at_level(logging.INFO):
        intent = cell.evaluate(_view(), datetime.now(timezone.utc))
    stamped = _stamped_ids(caplog)
    assert intent.setup_id == "active_a"
    assert stamped == ["shadow_up_front", "active_a", "active_b"]


def test_non_qualifying_setups_do_not_stamp(caplog, monkeypatch):
    monkeypatch.setattr("modules.cells.cell._exec_enabled", lambda: True)
    cell = _cell([
        _setup("qualifies", "SHADOW"),
        _setup("blocked", "SHADOW", mx=-90.0),   # willr −50 fails max −90
    ])
    with caplog.at_level(logging.INFO):
        intent = cell.evaluate(_view(), datetime.now(timezone.utc))
    assert intent is None
    assert _stamped_ids(caplog) == ["qualifies"]
