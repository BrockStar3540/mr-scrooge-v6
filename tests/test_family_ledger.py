"""tests/test_family_ledger.py — the FAMILY RULE (Brock, 2026-07-28).

A parent setup and the poppers its grid fired are ONE economic unit tracked in
broker net pips. The 7/16→7/28 forward test proved per-leg views mislead both
ways: kc_up_long_lean parents were red (−$74) inside a +$718 family, while
rvol_low_240's small parent leg (−$130, n=2) hid a −$858 family — invisible to
the old cell_v1-only fills rule. Covers: psu stamping on popper fires, psu
recovery, family attribution (psu + anchor-join backfill), era re-clocking,
and the governor's demote/defend verdict.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

import modules.management.party_package as ppm
import ops.governor as gov
import research.tools.broker_setup_audit as audit
from core.trial_evidence import SetupEvidence
from modules.management.base import Position
from modules.playmaker.playmaker import TradeTicket

NOW = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)
LADDER = [10.0, 15.0, 20.0, 30.0, 40.0, 60.0]


class FakeBroker:
    def __init__(self):
        self.orders = []
        self.next_id = 100

    def size_units(self, pair, direction, margin_pct=None, **kw):
        return 1000

    def place_market(self, pair, direction, units, entry_price=None,
                     sl_pips=None, client_ext=None, tp_pips=0.0):
        self.next_id += 1
        self.orders.append({"pair": pair, "direction": direction, "units": units,
                            "sl_pips": sl_pips, "client_ext": client_ext})
        return {"id": str(self.next_id)}

    def close_position(self, trade_id, units="ALL"):
        return {}

    def move_stop(self, trade_id, new_sl_price, pair):
        return {}

    def account_balance(self):
        return 10_000.0


@pytest.fixture
def pp(tmp_path, monkeypatch):
    cfg = {"enabled": True, "marker_pips": LADDER, "sl_pips": 60.0,
           "trigger_pips": 8.5, "trail_pips": 2.5, "max_levels": 8,
           "max_total_trades": 8, "max_margin_pct_total": 0.8,
           "grid_max_age_days": 7.0}
    p = tmp_path / "pp_config.json"
    p.write_text(json.dumps(cfg))
    monkeypatch.setattr(ppm, "_CONFIG_PATH", p)
    monkeypatch.setattr(ppm, "_STATE_PATH", tmp_path / "pp_state.json")
    return ppm.PartyPackage(FakeBroker(), dry_run=False)


def _parent(pair="GBP_USD", direction="long", entry=1.35000):
    ticket = TradeTicket(pair=pair, session="london", direction=direction,
                         score=0.0, dir_certainty=0.0, mom_certainty=0.0,
                         vol_regime="x", expected_pips=0.0,
                         timestamp=NOW, reads={})
    return Position(ticket=ticket, entry_price=entry, entry_time=NOW,
                    units=1000, oanda_trade_id="1", pip_size=0.0001)


# ── psu stamping ─────────────────────────────────────────────────────────────

def test_popper_client_ext_carries_parent_setup():
    cfg = {"sl_pips": 60.0, "trigger_pips": 8.5, "trail_pips": 2.5}
    ext = ppm._popper_client_ext(cfg, 15.0, 1.35000, "rvol_low_240")
    meta = json.loads(ext["comment"])
    assert meta["psu"] == "rvol_low_240"
    assert meta["su"] == "pp_v1" and ext["tag"] == "pp_v1"
    assert len(ext["comment"]) <= 128    # OANDA comment cap


def test_popper_client_ext_omits_unknown_parent():
    cfg = {"sl_pips": 60.0, "trigger_pips": 8.5, "trail_pips": 2.5}
    for unknown in ("", "?", "recovered"):
        meta = json.loads(ppm._popper_client_ext(cfg, 15.0, 1.35, unknown)["comment"])
        assert "psu" not in meta


def test_popper_client_ext_truncates_long_setup_within_cap():
    cfg = {"sl_pips": 60.0, "trigger_pips": 8.5, "trail_pips": 2.5}
    ext = ppm._popper_client_ext(cfg, 15.0, 1.35, "x" * 200)
    meta = json.loads(ext["comment"])
    assert meta["psu"] == "x" * 40
    assert len(ext["comment"]) <= 128


def test_fired_popper_order_carries_psu(pp):
    pp.on_parent_open(_parent(), setup_id="rvol_low_240")
    g = pp.grids["GBP_USD"]
    price = g.level_price(15.0)
    pp.tick(NOW, set(), {"GBP_USD"},
            lambda pair: (price - 0.00001, price + 0.00001))
    orders = pp.broker.orders
    assert orders, "marker cross should fire a popper"
    meta = json.loads(orders[0]["client_ext"]["comment"])
    assert meta["psu"] == "rvol_low_240"


def test_recovery_adopts_psu_as_parent_setup(pp):
    trade = {"instrument": "GBP_USD", "currentUnits": "1000", "price": "1.34900",
             "openTime": "2026-07-20T10:00:00.000000000Z", "id": "555",
             "clientExtensions": {"tag": "pp_v1", "comment": json.dumps(
                 {"sl": 60.0, "tr": 8.5, "tp": 2.5, "lvl": 15.0,
                  "anc": 1.35000, "su": "pp_v1", "psu": "rvol_low_240"})}}
    pp.recover(trade)
    assert pp.grids["GBP_USD"].parent_setup == "rvol_low_240"


# ── family attribution (broker_setup_audit) ──────────────────────────────────

_PARENTS = [{"instrument": "GBP_USD", "dir": 1, "price": 1.35000,
             "su": "rvol_low_240", "tag": "cell_v1"},
            {"instrument": "GBP_USD", "dir": -1, "price": 1.36000,
             "su": "short_setup", "tag": "cell_v1"}]


def test_family_setup_parent_is_itself():
    assert audit.family_setup(_PARENTS[0], _PARENTS) == "rvol_low_240"


def test_family_setup_popper_via_psu():
    op = {"instrument": "GBP_USD", "dir": 1, "tag": "pp_v1", "su": "pp_v1",
          "psu": "rvol_low_240", "anc": None}
    assert audit.family_setup(op, _PARENTS) == "rvol_low_240"


def test_family_setup_popper_via_anchor_join():
    op = {"instrument": "GBP_USD", "dir": 1, "tag": "pp_v1", "su": "pp_v1",
          "psu": None, "anc": 1.35010}     # 1p from the long parent's entry
    assert audit.family_setup(op, _PARENTS) == "rvol_low_240"


def test_family_setup_anchor_join_respects_direction_and_distance():
    far = {"instrument": "GBP_USD", "dir": 1, "tag": "pp_v1", "su": "pp_v1",
           "psu": None, "anc": 1.36000}    # 100p away from the only long parent
    assert audit.family_setup(far, _PARENTS) == "?"
    no_anc = {"instrument": "GBP_USD", "dir": 1, "tag": "pp_v1", "su": "pp_v1",
              "psu": None, "anc": None}
    assert audit.family_setup(no_anc, _PARENTS) == "?"


# ── governor: era re-clock + verdict ─────────────────────────────────────────

_CFG = {"family_min_trades": 5, "family_demote_pips": -60.0,
        "family_defend_pips": 60.0, "bar_avg": 2.0}


def _fam(n, net_pips):
    return {"n": n, "net_pips": net_pips, "net_usd": net_pips * 2.6}


def _ev(raw_n, net_avg):
    return SetupEvidence(key=("GBP_USD", "london", "x"), raw_n=raw_n,
                         effective_n=float(raw_n), independent_days=raw_n // 2,
                         net_avg=net_avg, recent_n=0, recent_avg=None,
                         block_lcb=None, p_value=None)


def test_family_era_view_filters_pre_era_trades():
    fam = {"trades": [{"t": "2026-07-19T10:00", "pips": -60.0, "usd": -156.0},
                      {"t": "2026-07-25T10:00", "pips": 6.0, "usd": 15.6}]}
    v = gov.family_era_view(fam, "2026-07-24T00:00:00+00:00")
    assert v["n"] == 1 and v["net_pips"] == 6.0


def test_family_red_demotes_regardless_of_stamps():
    # the rvol_low_240 shape: real trades deep red, stamps fine
    demote, why = gov.active_verdict(_ev(25, 5.0), _fam(20, -330.0), _CFG, 20)
    assert demote and why == "family_red"


def test_family_green_defends_against_bar_lost():
    # broker-green family, red simulator: seat is SAFE
    demote, why = gov.active_verdict(_ev(25, -3.0), _fam(24, 103.0), _CFG, 20)
    assert not demote and why == "family_green"


def test_bar_lost_still_applies_without_family_evidence():
    demote, why = gov.active_verdict(_ev(25, 1.0), None, _CFG, 20)
    assert demote and why == "bar_lost"
    demote, _ = gov.active_verdict(_ev(19, 1.0), None, _CFG, 20)
    assert not demote                       # below min_raw: no evidence, no verdict


def test_small_family_neither_convicts_nor_defends():
    # n below family_min_trades: family says nothing; stamps decide
    demote, why = gov.active_verdict(_ev(25, 1.0), _fam(2, -80.0), _CFG, 20)
    assert demote and why == "bar_lost"
    demote, _ = gov.active_verdict(_ev(25, 5.0), _fam(2, -80.0), _CFG, 20)
    assert not demote


def test_healthy_family_holds_seat():
    demote, why = gov.active_verdict(_ev(10, 5.0), _fam(8, 20.0), _CFG, 20)
    assert not demote and why == "hold"
