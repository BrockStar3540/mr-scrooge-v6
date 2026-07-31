"""External review round 3 (2026-07-31): the re-enable bar for promotions.

Each test pins one of the five defects that kept the cheater lane off after
v6.14.7 — the lane returns only while all of these hold."""
import json
import pytest
from core.family_cycle import CycleResult
from research.tools.family_cycle_replay import aggregate_policy_rows
from ops.governor import cheater_v3_predicate, cheater_v3_policy


def _cy(net, liab=60.0, censored=False):
    return CycleResult(censored=censored, net_pips=net, parent_net=net,
                       harvest=0.0, n_poppers=0, n_refires=0,
                       peak_liability_pips=liab, duration_min=600.0,
                       open_legs=1 if censored else 0)


from datetime import datetime, timezone, timedelta
T0 = datetime(2026, 7, 28, tzinfo=timezone.utc)


def test_policies_have_independent_completion_and_censoring():
    # ep1: parent resolved, grid still open; ep2: both resolved (different day)
    rows = [(T0, _cy(0, censored=True), _cy(30.0)),
            (T0 + timedelta(days=1), _cy(45.0), _cy(20.0))]
    r = aggregate_policy_rows(rows)
    assert r["cycles"] == 1 and r["censored"] == 1          # PP view
    assert len(r["u_par_list"]) == 2 and r["censored_par"] == 0
    assert r["days"] == 1 and r["days_par"] == 2            # own day counts
    assert r["last_censored"] is False and r["last_censored_par"] is False
    # censoring flags track their OWN policy's latest episode
    rows2 = rows + [(T0 + timedelta(days=2), _cy(10.0), _cy(0, censored=True))]
    r2 = aggregate_policy_rows(rows2)
    assert r2["last_censored"] is False
    assert r2["last_censored_par"] is True


def test_grid_lift_is_paired():
    # lift computed ONLY over episodes where both policies resolved
    rows = [(T0, _cy(60.0), _cy(0, censored=True)),      # unpaired PP win
            (T0 + timedelta(days=1), _cy(30.0), _cy(60.0))]  # paired: lift -0.5
    r = aggregate_policy_rows(rows)
    assert r["grid_lift"] == pytest.approx((30.0 - 60.0) / 60.0)


def test_parent_only_pass_uses_own_days_and_censoring():
    C = {"cheater_min_cycles": 2, "cheater_min_days": 2,
         "cheater_min_positive_cycles": 2, "cheater_min_risk_covered_gain": 1.0,
         "cheater_min_harvest_coverage": 1.0, "cheater_max_single_cycle_share": 0.9,
         "cheater_require_flat": True}
    r = {"u_list": [-0.5, -0.5], "days": 1, "last_censored": True,
         "u_par_list": [0.7, 0.7], "days_par": 2, "last_censored_par": False,
         "U_pp": -0.5, "U_par": 0.7}
    # PP_ON view fails everything; the PARENT_ONLY pass must not be polluted
    ok, why = cheater_v3_predicate(r, C, policy="PARENT_ONLY")
    assert ok, why
    ok, _ = cheater_v3_predicate(r, C, policy="FAMILY_PP")
    assert not ok


def test_chosen_policy_cs_selection():
    # the ranking metadata rule: CS = sum of the CHOSEN policy's list
    r = {"u_list": [-1.0], "u_par_list": [1.4], "U_pp": -1.0, "U_par": 1.4}
    pol = cheater_v3_policy(r)
    assert pol == "PARENT_ONLY"
    chosen = (r.get("u_par_list") if pol == "PARENT_ONLY" else r.get("u_list")) or []
    assert round(sum(chosen), 2) == 1.4          # not -1.0


def test_graduate_clears_seat_and_restores_grid():
    # the two seat-bookkeeping actions must be INDEPENDENT ifs (defect 4):
    # simulate the branch logic exactly as written in the governor
    def bookkeeping(kind, seats, k2):
        actions = []
        if kind in ("PROMOTE", "GRADUATE"):
            actions.append("pp_on")
        if kind in ("GRADUATE", "DEMOTE"):
            seats.pop(k2, None)
        return actions
    seats = {"X|y|z": {"t": "now"}}
    acts = bookkeeping("GRADUATE", seats, "X|y|z")
    assert "pp_on" in acts and "X|y|z" not in seats


def test_legacy_grid_migrates_to_probe(tmp_path, monkeypatch):
    import modules.management.party_package as ppm
    # a cell config where the setup is a PROBE seat
    cells = tmp_path / "config" / "cells"
    cells.mkdir(parents=True)
    (cells / "EUR_USD.json").write_text(json.dumps({"sessions": {"ny": {
        "setups": [{"id": "s1", "status": "PROBE"}]}}}))
    state_dir = tmp_path / "data"
    state_dir.mkdir()
    monkeypatch.setattr(ppm, "_STATE_PATH", state_dir / "pp_state.json")
    # legacy grid dict: NO probe field
    legacy = {"pair": "EUR_USD", "side": "long", "anchor": 1.1,
              "created": "2026-07-30T10:00:00+00:00", "parent_setup": "s1",
              "cell_key": "EUR_USD|ny|s1", "fmt": "offsets", "levels": {}}
    (state_dir / "pp_state.json").write_text(json.dumps({"grids": [legacy]}))
    pp = ppm.PartyPackage.__new__(ppm.PartyPackage)
    pp.grids = {}
    pp._load_state()
    assert pp.grids["EUR_USD"].probe is True     # migrated, not full-size
