"""tests/test_party_package.py — Party Package (V6.1) grid mechanics.

Covers: grid arming on parent open, popper fire on level cross, level re-arm
after close + re-cross (the harvesting loop), trade-count cap, kill switch,
recovery from pp_v1 client extensions, and state persistence round-trip.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

import modules.management.party_package as ppm
from modules.management.base import Position
from modules.playmaker.playmaker import TradeTicket


NOW = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)   # far from rollover


class FakeBroker:
    def __init__(self):
        self.orders = []
        self.next_id = 100
        self.closed = []

    def size_units(self, pair, direction, margin_pct=None, **kw):
        return 1000

    def place_market(self, pair, direction, units, entry_price=None,
                     sl_pips=None, client_ext=None, tp_pips=0.0):
        self.next_id += 1
        self.orders.append({"pair": pair, "direction": direction, "units": units,
                            "sl_pips": sl_pips, "client_ext": client_ext})
        return {"id": str(self.next_id)}

    def close_position(self, trade_id, units="ALL"):
        self.closed.append(trade_id)
        return {}

    def move_stop(self, trade_id, new_sl_price, pair):
        return {}

    def account_balance(self):
        return 10_000.0


def _cfg(tmp_path, **over):
    cfg = {"enabled": True, "step_pips": 15.0, "sl_pips": 60.0,
           "trigger_pips": 8.5, "trail_pips": 2.5, "max_levels": 8,
           "max_total_trades": 8, "max_margin_pct_total": 0.8,
           "grid_max_age_days": 7.0}
    cfg.update(over)
    p = tmp_path / "pp_config.json"
    p.write_text(json.dumps(cfg))
    return p


@pytest.fixture
def pp(tmp_path, monkeypatch):
    monkeypatch.setattr(ppm, "_CONFIG_PATH", _cfg(tmp_path))
    monkeypatch.setattr(ppm, "_STATE_PATH", tmp_path / "pp_state.json")
    return ppm.PartyPackage(FakeBroker(), dry_run=False)


def _parent(pair="EUR_USD", side="long", price=1.10000):
    ticket = TradeTicket(pair=pair, session="london", direction=side,
                         score=0.0, dir_certainty=0.0, mom_certainty=0.0,
                         vol_regime="cell", expected_pips=0.0,
                         timestamp=NOW, reads={})
    return Position(ticket=ticket, entry_price=price, entry_time=NOW,
                    units=1000, oanda_trade_id="1", pip_size=0.0001)


def _pricing(mid, spread_pips=1.0, pip=0.0001):
    half = spread_pips * pip / 2
    return lambda pair: (mid - half, mid + half)


def test_grid_arms_on_parent_open(pp):
    pp.on_parent_open(_parent(), "setup_x")
    g = pp.grids["EUR_USD"]
    assert len(g.levels) == 8
    assert all(v["armed"] and v["trade_id"] is None for v in g.levels.values())
    # level 1 sits step_pips below the long anchor
    assert g.level_price(1, 15.0) == pytest.approx(1.10000 - 15 * 0.0001)


def test_popper_fires_on_cross(pp):
    pp.on_parent_open(_parent(), "setup_x")
    # price drops through level 1 (-15p)
    pp.tick(NOW, set(), {"EUR_USD"}, _pricing(1.09840))
    assert pp.open_popper_count() == 1
    order = pp.broker.orders[0]
    assert order["direction"] == "long" and order["sl_pips"] == 60.0
    assert order["client_ext"]["tag"] == "pp_v1"
    lv = pp.grids["EUR_USD"].levels[1]
    assert lv["trade_id"] is not None and not lv["armed"]


def test_rearm_after_close_and_recross(pp):
    pp.on_parent_open(_parent(), "setup_x")
    pp.tick(NOW, set(), {"EUR_USD"}, _pricing(1.09840))          # fire lvl 1
    tid = next(iter(pp.poppers))
    # popper closes server-side (id absent from oanda_open) while price is low
    pp.tick(NOW, set(), {"EUR_USD"}, _pricing(1.09840))
    # id not in oanda_open -> booked; level spent (disarmed, no re-fire yet)
    assert tid not in pp.poppers
    lv = pp.grids["EUR_USD"].levels[1]
    assert lv["trade_id"] is None and not lv["armed"]
    n_orders = len(pp.broker.orders)
    # price recrosses ABOVE the level -> re-arms (no fire at this price)
    pp.tick(NOW, set(), {"EUR_USD"}, _pricing(1.09900))
    assert pp.grids["EUR_USD"].levels[1]["armed"]
    # price drops through again -> second popper fires at the same level
    pp.tick(NOW, set(), {"EUR_USD"}, _pricing(1.09840))
    assert len(pp.broker.orders) == n_orders + 1
    assert pp.grids["EUR_USD"].fired_total == 2


def test_one_popper_per_mile_marker(pp):
    """Brock's exact scenario (2026-07-19): parent -15 fires #15; price wanders
    -20 -> -10 -> back to -15 with #15 still open => NO second #15. Only -30
    births #30, giving two active poppers."""
    pp.on_parent_open(_parent(), "setup_x")                       # anchor 1.10000
    oanda_open = set()
    pp.tick(NOW, oanda_open, {"EUR_USD"}, _pricing(1.09845))      # -15.5p -> #15 fires
    assert pp.open_popper_count() == 1
    oanda_open = set(pp.poppers.keys())                           # popper stays open
    pp.tick(NOW, oanda_open, {"EUR_USD"}, _pricing(1.09800))      # -20: no marker there
    pp.tick(NOW, oanda_open, {"EUR_USD"}, _pricing(1.09900))      # back to -10
    pp.tick(NOW, oanda_open, {"EUR_USD"}, _pricing(1.09845))      # back to -15.5
    assert pp.open_popper_count() == 1                            # #15 NOT duplicated
    assert len(pp.broker.orders) == 1
    pp.tick(NOW, oanda_open, {"EUR_USD"}, _pricing(1.09690))      # -31: #30 fires
    assert pp.open_popper_count() == 2
    lvls = pp.grids["EUR_USD"].levels
    assert lvls[1]["trade_id"] and lvls[2]["trade_id"]            # #15 and #30 both live


def test_popper_ratchet_gear(pp):
    pp.on_parent_open(_parent(), "setup_x")
    pp.tick(NOW, set(), {"EUR_USD"}, _pricing(1.09845))
    mgr = next(iter(pp.poppers.values()))
    assert mgr.position.exit_params.trigger_pips == 8.5
    assert mgr.position.exit_params.trail_pips == 2.5             # lock = +6


def test_trade_cap_blocks_fire(pp, tmp_path, monkeypatch):
    monkeypatch.setattr(ppm, "_CONFIG_PATH", _cfg(tmp_path, max_total_trades=1))
    pp.on_parent_open(_parent(), "setup_x")
    # parent already counts 1 of 1 -> no fire even though level crossed
    pp.tick(NOW, set(), {"EUR_USD"}, _pricing(1.09840))
    assert pp.open_popper_count() == 0


def test_kill_switch_blocks_fire_but_keeps_grid(pp, tmp_path, monkeypatch):
    pp.on_parent_open(_parent(), "setup_x")
    monkeypatch.setattr(ppm, "_CONFIG_PATH", _cfg(tmp_path, enabled=False))
    pp.tick(NOW, set(), {"EUR_USD"}, _pricing(1.09840))
    assert pp.open_popper_count() == 0
    assert "EUR_USD" in pp.grids


def test_recover_rebuilds_grid_and_popper(pp):
    trade = {
        "instrument": "EUR_USD", "currentUnits": "1000", "price": "1.09850",
        "id": "777", "openTime": "2026-07-20T09:00:00.000000Z",
        "clientExtensions": {"tag": "pp_v1", "comment": json.dumps(
            {"sl": 60.0, "tr": 12.5, "tp": 2.5, "lvl": 1, "anc": 1.10000,
             "su": "pp_v1"})},
        "stopLossOrder": {"price": "1.09250"},
    }
    pp.recover(trade)
    assert "777" in pp.poppers
    g = pp.grids["EUR_USD"]
    assert g.anchor == pytest.approx(1.10000)
    assert g.levels[1]["trade_id"] == "777"
    mgr = pp.poppers["777"]
    assert mgr.position.exit_params.sl_pips == 60.0
    assert mgr.position.exit_params.trigger_pips == 12.5


def test_state_persistence_roundtrip(pp, tmp_path):
    pp.on_parent_open(_parent(), "setup_x")
    pp.tick(NOW, set(), {"EUR_USD"}, _pricing(1.09840))          # fire lvl 1
    pp2 = ppm.PartyPackage(FakeBroker(), dry_run=False)          # fresh boot
    assert "EUR_USD" in pp2.grids
    # persisted trade ids are cleared pending recover() reconciliation
    assert pp2.grids["EUR_USD"].levels[1]["trade_id"] is None
    assert pp2.grids["EUR_USD"].fired_total == 1


def test_dashboard_state_shape(pp):
    pp.on_parent_open(_parent(), "setup_x")
    pp.tick(NOW, set(), {"EUR_USD"}, _pricing(1.09840))
    st = pp.state()
    assert st["enabled"] is True and st["open_poppers"] == 1
    g = st["grids"][0]
    assert g["pair"] == "EUR_USD" and g["level_prices"]["1"]
    assert g["open"][0]["level"] == 1
