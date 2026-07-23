"""tests/test_party_package.py — Party Package grid mechanics (ladder era, 2026-07-22).

Covers: grid arming on parent open (marker ladder), popper fire on marker cross
(including multi-marker bars), one-popper-per-marker (Brock's scenario), re-arm
after close + re-cross, trade-count cap, kill switch, per-cell switch, recovery
from pp_v1 client extensions (both index-era and offset-era comments), and state
persistence round-trip with pre-ladder migration.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

import modules.management.party_package as ppm
from modules.management.base import Position
from modules.playmaker.playmaker import TradeTicket


NOW = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)   # far from rollover
LADDER = [10.0, 15.0, 20.0, 30.0, 40.0, 60.0]


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
    cfg = {"enabled": True, "marker_pips": LADDER, "sl_pips": 60.0,
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


def test_grid_arms_with_ladder(pp):
    pp.on_parent_open(_parent(), "setup_x")
    g = pp.grids["EUR_USD"]
    assert sorted(g.levels.keys(), key=float) == ["10", "15", "20", "30", "40", "60"]
    assert all(v["armed"] and v["trade_id"] is None for v in g.levels.values())
    assert g.level_price(10.0) == pytest.approx(1.10000 - 10 * 0.0001)
    assert g.level_price(60.0) == pytest.approx(1.10000 - 60 * 0.0001)


def test_single_marker_fire(pp):
    pp.on_parent_open(_parent(), "setup_x")
    pp.tick(NOW, set(), {"EUR_USD"}, _pricing(1.09895))          # -10.5p: only -10 crossed
    assert pp.open_popper_count() == 1
    order = pp.broker.orders[0]
    assert order["direction"] == "long" and order["sl_pips"] == 60.0
    assert order["client_ext"]["tag"] == "pp_v1"
    assert json.loads(order["client_ext"]["comment"])["lvl"] == 10.0
    lv = pp.grids["EUR_USD"].levels["10"]
    assert lv["trade_id"] is not None and not lv["armed"]


def test_multi_marker_bar_fires_each_once(pp):
    pp.on_parent_open(_parent(), "setup_x")
    pp.tick(NOW, set(), {"EUR_USD"}, _pricing(1.09845))          # -15.5p: -10 and -15
    assert pp.open_popper_count() == 2
    lvls = pp.grids["EUR_USD"].levels
    assert lvls["10"]["trade_id"] and lvls["15"]["trade_id"] and not lvls["20"]["trade_id"]


def test_one_popper_per_mile_marker(pp):
    """Brock's scenario, ladder edition: dip to -15.5 fires -10 and -15; wander
    -20 / -10 / back to -15.5 adds only the -20 marker once and NO duplicates;
    -31 births the -30 popper."""
    pp.on_parent_open(_parent(), "setup_x")
    pp.tick(NOW, set(), {"EUR_USD"}, _pricing(1.09845))          # -15.5 -> #10 #15
    assert pp.open_popper_count() == 2
    oanda_open = set(pp.poppers.keys())                          # all stay open
    pp.tick(NOW, oanda_open, {"EUR_USD"}, _pricing(1.09800))     # -20 -> #20 fires
    oanda_open = set(pp.poppers.keys())
    pp.tick(NOW, oanda_open, {"EUR_USD"}, _pricing(1.09900))     # back to -10
    pp.tick(NOW, oanda_open, {"EUR_USD"}, _pricing(1.09845))     # back to -15.5
    assert pp.open_popper_count() == 3                           # no duplicates
    assert len(pp.broker.orders) == 3
    pp.tick(NOW, oanda_open, {"EUR_USD"}, _pricing(1.09690))     # -31 -> #30
    assert pp.open_popper_count() == 4
    lvls = pp.grids["EUR_USD"].levels
    assert all(lvls[k]["trade_id"] for k in ("10", "15", "20", "30"))
    assert not lvls["40"]["trade_id"]


def test_rearm_after_close_and_recross(pp):
    pp.on_parent_open(_parent(), "setup_x")
    pp.tick(NOW, set(), {"EUR_USD"}, _pricing(1.09895))          # fire -10
    tid = next(iter(pp.poppers))
    pp.tick(NOW, set(), {"EUR_USD"}, _pricing(1.09895))          # closed server-side
    assert tid not in pp.poppers
    lv = pp.grids["EUR_USD"].levels["10"]
    assert lv["trade_id"] is None and not lv["armed"]
    n_orders = len(pp.broker.orders)
    pp.tick(NOW, set(), {"EUR_USD"}, _pricing(1.09950))          # re-cross above -10
    assert pp.grids["EUR_USD"].levels["10"]["armed"]
    pp.tick(NOW, set(), {"EUR_USD"}, _pricing(1.09895))          # dip again -> re-fire
    assert len(pp.broker.orders) == n_orders + 1
    assert pp.grids["EUR_USD"].fired_total == 2


def test_popper_ratchet_gear(pp):
    pp.on_parent_open(_parent(), "setup_x")
    pp.tick(NOW, set(), {"EUR_USD"}, _pricing(1.09895))
    mgr = next(iter(pp.poppers.values()))
    assert mgr.position.exit_params.trigger_pips == 8.5
    assert mgr.position.exit_params.trail_pips == 2.5             # lock = +6


def test_trade_cap_blocks_fire(pp, tmp_path, monkeypatch):
    monkeypatch.setattr(ppm, "_CONFIG_PATH", _cfg(tmp_path, max_total_trades=1))
    pp.on_parent_open(_parent(), "setup_x")
    pp.tick(NOW, set(), {"EUR_USD"}, _pricing(1.09845))
    assert pp.open_popper_count() == 0


def test_kill_switch_blocks_fire_but_keeps_grid(pp, tmp_path, monkeypatch):
    pp.on_parent_open(_parent(), "setup_x")
    monkeypatch.setattr(ppm, "_CONFIG_PATH", _cfg(tmp_path, enabled=False))
    pp.tick(NOW, set(), {"EUR_USD"}, _pricing(1.09845))
    assert pp.open_popper_count() == 0
    assert "EUR_USD" in pp.grids


def test_per_cell_switch_blocks_grid_and_fires(pp, tmp_path, monkeypatch):
    monkeypatch.setattr(ppm, "_CONFIG_PATH", _cfg(
        tmp_path, per_cell={"EUR_USD|london|setup_x": False}))
    pp.on_parent_open(_parent(), "setup_x")
    assert "EUR_USD" not in pp.grids
    monkeypatch.setattr(ppm, "_CONFIG_PATH", _cfg(tmp_path))
    pp.on_parent_open(_parent(), "setup_x")
    assert "EUR_USD" in pp.grids
    monkeypatch.setattr(ppm, "_CONFIG_PATH", _cfg(
        tmp_path, per_cell={"EUR_USD": False}))
    pp.tick(NOW, set(), {"EUR_USD"}, _pricing(1.09845))
    assert pp.open_popper_count() == 0
    monkeypatch.setattr(ppm, "_CONFIG_PATH", _cfg(tmp_path))
    pp.tick(NOW, set(), {"EUR_USD"}, _pricing(1.09845))
    assert pp.open_popper_count() == 2                            # -10 and -15


def test_pp_cell_enabled_hierarchy():
    cfg = {"per_cell": {"EUR_USD": False, "EUR_USD|london": True,
                        "EUR_USD|london|bad_setup": False}}
    assert ppm.pp_cell_enabled(cfg, "EUR_USD", "london", "good") is True
    assert ppm.pp_cell_enabled(cfg, "EUR_USD", "london", "bad_setup") is False
    assert ppm.pp_cell_enabled(cfg, "EUR_USD", "ny", "any") is False
    assert ppm.pp_cell_enabled(cfg, "GBP_USD", "ny", "any") is True


def test_recover_offset_era(pp):
    trade = {
        "instrument": "EUR_USD", "currentUnits": "1000", "price": "1.09800",
        "id": "777", "openTime": "2026-07-20T09:00:00.000000Z",
        "clientExtensions": {"tag": "pp_v1", "comment": json.dumps(
            {"sl": 60.0, "tr": 8.5, "tp": 2.5, "lvl": 20.0, "anc": 1.10000,
             "su": "pp_v1"})},
        "stopLossOrder": {"price": "1.09200"},
    }
    pp.recover(trade)
    assert "777" in pp.poppers
    g = pp.grids["EUR_USD"]
    assert g.anchor == pytest.approx(1.10000)
    assert g.levels["20"]["trade_id"] == "777"
    assert pp._popper_grid["777"] == ("EUR_USD", 20.0)


def test_recover_index_era_migrates(pp):
    """Pre-ladder comments carried the level INDEX (15p step): lvl 2 -> -30p."""
    trade = {
        "instrument": "GBP_USD", "currentUnits": "-1000", "price": "1.35000",
        "id": "888", "openTime": "2026-07-20T09:00:00.000000Z",
        "clientExtensions": {"tag": "pp_v1", "comment": json.dumps(
            {"sl": 60.0, "tr": 8.5, "tp": 2.5, "lvl": 2, "anc": 1.34700,
             "su": "pp_v1"})},
    }
    pp.recover(trade)
    assert pp._popper_grid["888"] == ("GBP_USD", 30.0)
    assert pp.grids["GBP_USD"].levels["30"]["trade_id"] == "888"


def test_state_persistence_roundtrip(pp, tmp_path):
    pp.on_parent_open(_parent(), "setup_x")
    pp.tick(NOW, set(), {"EUR_USD"}, _pricing(1.09845))          # fire -10, -15
    pp2 = ppm.PartyPackage(FakeBroker(), dry_run=False)          # fresh boot
    g = pp2.grids["EUR_USD"]
    assert g.levels["10"]["trade_id"] is None                    # cleared pending recover
    assert g.fired_total == 2
    assert sorted(g.levels.keys(), key=float)[:3] == ["10", "15", "20"]


def test_pre_ladder_state_migration(pp, tmp_path, monkeypatch):
    """Old pp_state.json (index-keyed, no fmt flag) maps 1..N -> 15p steps."""
    state = {"grids": [{"pair": "USD_JPY", "side": "long", "anchor": 163.10,
                        "created": "2026-07-22T15:56:00+00:00",
                        "parent_setup": "control_atr5m_60",
                        "levels": {"1": {"armed": True, "trade_id": None},
                                   "2": {"armed": False, "trade_id": None}},
                        "greens": 1, "knives": 0, "green_pips": 9.8,
                        "knife_pips": 0.0, "fired_total": 1}]}
    (tmp_path / "pp_state.json").write_text(json.dumps(state))
    pp2 = ppm.PartyPackage(FakeBroker(), dry_run=False)
    g = pp2.grids["USD_JPY"]
    assert set(g.levels.keys()) == {"15", "30"}
    assert g.levels["15"]["armed"] and not g.levels["30"]["armed"]
    assert g.greens == 1 and g.fired_total == 1


def test_dashboard_state_shape(pp):
    pp.on_parent_open(_parent(), "setup_x")
    pp.tick(NOW, set(), {"EUR_USD"}, _pricing(1.09845))
    st = pp.state()
    assert st["enabled"] is True and st["open_poppers"] == 2
    g = st["grids"][0]
    assert g["pair"] == "EUR_USD" and g["level_prices"]["10"]
    assert sorted(p["level"] for p in g["open"]) == [10.0, 15.0]
