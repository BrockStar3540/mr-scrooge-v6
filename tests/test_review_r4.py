"""Cheater v4: production-path invariants for safe commissioning."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys

import pytest

from core.family_cycle import CycleResult
from modules.management.party_package import Grid, PartyPackage
from ops.governor import (
    DEFAULT_CFG,
    build_cheater_candidates,
    cheater_v3_decision,
    prepare_grid_transition,
    probe_leash_breached,
    probe_seat_count,
    selected_policy_cs,
    stage_era_reset,
    update_cheater_seat_book,
)
from research.tools.family_cycle_replay import aggregate_policy_rows


T0 = datetime(2026, 7, 20, tzinfo=timezone.utc)


def _cy(net, censored=False, liab=60.0):
    return CycleResult(
        censored=censored, net_pips=net, parent_net=net, harvest=0.0,
        n_poppers=0, n_refires=0, peak_liability_pips=liab,
        duration_min=60.0, open_legs=1 if censored else 0,
    )


def test_unresolved_pp_cycles_cannot_disappear_into_completed_only_pass():
    rows = []
    # Three slow family paths remain unresolved after their parents lost 1R.
    for i in range(3):
        rows.append((T0 + timedelta(days=i), _cy(0, True), _cy(-60)))
    # Three later fast family winners; the grid still harmed every paired case.
    for i in range(3, 6):
        rows.append((T0 + timedelta(days=i), _cy(30), _cy(60)))
    r = aggregate_policy_rows(rows)
    assert r["grid_lift"] == -0.5 and r["censored"] == 3
    policy, why, diag = cheater_v3_decision(r, DEFAULT_CFG)
    assert policy == "NONE"
    assert not diag["FAMILY_PP"]["passes"]
    assert "unresolved" in diag["FAMILY_PP"]["why"]


def test_missing_replay_data_cannot_silently_shrink_the_sample():
    rows = [(T0 + timedelta(days=i), _cy(36), _cy(36)) for i in range(3)]
    r = aggregate_policy_rows(rows)
    r["missing_cycles"] = 1
    policy, why, diag = cheater_v3_decision(r, DEFAULT_CFG)
    assert policy == "NONE"
    assert "missing data" in diag["FAMILY_PP"]["why"]
    assert "missing data" in diag["PARENT_ONLY"]["why"]


def test_pp_requires_independent_ticket_and_positive_paired_lift_lcb():
    rows = [(T0 + timedelta(days=i), _cy(36), _cy(12)) for i in range(3)]
    r = aggregate_policy_rows(rows)
    policy, why, diag = cheater_v3_decision(r, DEFAULT_CFG)
    assert policy == "FAMILY_PP", (why, diag)
    assert r["grid_lift_lcb"] > 0 and r["grid_lift_n"] == 3
    assert selected_policy_cs(r, policy) == pytest.approx(1.8)


def test_parent_policy_wins_when_it_passes_and_grid_lift_is_not_proven():
    rows = [(T0 + timedelta(days=i), _cy(12), _cy(36)) for i in range(3)]
    r = aggregate_policy_rows(rows)
    policy, why, diag = cheater_v3_decision(r, DEFAULT_CFG)
    assert policy == "PARENT_ONLY", (why, diag)
    assert r["grid_lift_lcb"] < 0
    assert selected_policy_cs(r, policy) == pytest.approx(1.8)


def test_raw_censored_episodes_reach_candidacy_without_parent_evidence():
    key = ("EUR_USD", "ny", "slow_parent")
    bmap = {key: {"status": "SHADOW", "side": "long", "manual_only": False}}
    db = {"episodes": {
        f"e{i}": {"cell": "EUR_USD/ny", "setup": "slow_parent",
                  "side": "long", "t": (T0 + timedelta(days=i)).isoformat(),
                  "scores": {"mv": 2, "net240": None}}
        for i in range(3)
    }}
    got = build_cheater_candidates(bmap, {}, T0.isoformat(), db, 3)
    assert [item[0] for item in got] == [key]
    assert got[0][1] is None  # no parent SetupEvidence object is involved


def test_grid_transition_is_quiesce_retire_policy_then_status_ready():
    calls = []

    def off(*args):
        calls.append("off")
        return {"ok": True}

    def retire(*args):
        calls.append("retire")
        return {"ok": True, "retired": True}

    def on(*args):
        calls.append("on")
        return {"ok": True}

    out = prepare_grid_transition(
        "CHEATER-PROBE", "EUR_USD", "ny", "s1", False,
        policy="FAMILY_PP", pp_off_fn=off, pp_retire_fn=retire, pp_on_fn=on)
    assert out["ok"] and calls == ["off", "retire", "on"]

    calls.clear()
    out = prepare_grid_transition(
        "CHEATER-PROBE", "EUR_USD", "ny", "s1", False,
        policy="PARENT_ONLY", pp_off_fn=off, pp_retire_fn=retire, pp_on_fn=on)
    assert out["ok"] and calls == ["off", "retire"]


def test_grid_transition_failure_aborts_before_policy_enable():
    calls = []

    def off(*args):
        calls.append("off")
        return {"ok": True}

    def retire(*args):
        calls.append("retire")
        return {"ok": False, "error": "grid-not-flat"}

    def on(*args):
        calls.append("on")
        return {"ok": True}

    out = prepare_grid_transition(
        "CHEATER-PROBE", "EUR_USD", "ny", "s1", False,
        policy="FAMILY_PP", pp_off_fn=off, pp_retire_fn=retire, pp_on_fn=on)
    assert not out["ok"] and out["stage"] == "retire"
    assert calls == ["off", "retire"]


def test_exact_flat_grid_retirement_and_busy_fail_closed(monkeypatch):
    pp = PartyPackage.__new__(PartyPackage)
    pp.grids, pp.poppers, pp._popper_grid = {}, {}, {}
    monkeypatch.setattr(pp, "_save_state", lambda: None)
    key = "EUR_USD|ny|s1"
    g = Grid("EUR_USD", "long", 1.1, T0, "s1", key, "old-parent",
             probe=False)
    g.levels = {"10": {"armed": False, "trade_id": "99"}}
    pp.grids["EUR_USD"] = g
    pp.poppers["99"] = object()
    pp._popper_grid["99"] = ("EUR_USD", 10)
    blocked = pp.retire_cell_grid(key, parent_pairs=set())
    assert not blocked["ok"] and blocked["error"] == "grid-not-flat"
    assert blocked["quiesced"] and g.quiesced

    g.levels["10"]["trade_id"] = None
    pp.poppers.clear(); pp._popper_grid.clear()
    retired = pp.retire_cell_grid(key, parent_pairs=set())
    assert retired["ok"] and retired["retired"]
    assert "EUR_USD" not in pp.grids


def test_unknown_legacy_grid_owner_is_quiesced_not_guessed(monkeypatch):
    pp = PartyPackage.__new__(PartyPackage)
    pp.grids, pp.poppers, pp._popper_grid = {}, {}, {}
    monkeypatch.setattr(pp, "_save_state", lambda: None)
    g = Grid("EUR_USD", "long", 1.1, T0, "s1", "", "legacy")
    g.levels = {"10": {"armed": False, "trade_id": "99"}}
    pp.grids["EUR_USD"] = g
    result = pp.retire_cell_grid("EUR_USD|ny|s1", parent_pairs=set())
    assert not result["ok"]
    assert result["error"] == "grid-owner-unknown-quiesced"
    assert g.quiesced

    g.levels["10"]["trade_id"] = None
    result = pp.retire_cell_grid("EUR_USD|ny|s1", parent_pairs=set())
    assert result["ok"] and result["reason"] == "legacy-owner-unknown-flat"
    assert "EUR_USD" not in pp.grids


def test_other_exact_cell_grid_is_not_retired_or_quiesced(monkeypatch):
    pp = PartyPackage.__new__(PartyPackage)
    pp.grids, pp.poppers, pp._popper_grid = {}, {}, {}
    monkeypatch.setattr(pp, "_save_state", lambda: None)
    g = Grid("EUR_USD", "long", 1.1, T0, "s2", "EUR_USD|ny|s2", "2")
    pp.grids["EUR_USD"] = g
    result = pp.retire_cell_grid("EUR_USD|ny|s1", parent_pairs=set())
    assert result["ok"] and result["reason"] == "other-cell-grid"
    assert pp.grids["EUR_USD"] is g and not g.quiesced


def test_quiesced_grid_manages_but_cannot_fire(monkeypatch):
    import modules.management.party_package as ppm

    pp = PartyPackage.__new__(PartyPackage)
    pp.dry_run = False
    pp.grids, pp.poppers, pp._popper_grid = {}, {}, {}
    g = Grid("EUR_USD", "long", 1.1, T0, "s1", "EUR_USD|ny|s1", "1",
             quiesced=True)
    g.levels = {"10": {"armed": True, "trade_id": None}}
    pp.grids["EUR_USD"] = g
    fired = []
    monkeypatch.setattr(pp, "_fire", lambda *args: fired.append(args))
    monkeypatch.setattr(pp, "_save_state", lambda: None)
    cfg = dict(ppm._DEFAULTS)
    cfg["marker_pips"] = [10.0]
    monkeypatch.setattr(ppm, "pp_config", lambda: cfg)
    monkeypatch.setattr(ppm, "trading_enabled", lambda: True)
    pp.tick(T0 + timedelta(minutes=5), set(), {"EUR_USD"},
            lambda pair: (1.09885, 1.09895))
    assert fired == []


def test_explicit_full_size_grid_reconciles_down_when_cell_is_probe(
        tmp_path, monkeypatch):
    import modules.management.party_package as ppm

    cells = tmp_path / "config" / "cells"
    cells.mkdir(parents=True)
    (cells / "EUR_USD.json").write_text(json.dumps({"sessions": {"ny": {
        "setups": [{"id": "s1", "status": "PROBE"}]}}}))
    state = tmp_path / "data"
    state.mkdir()
    monkeypatch.setattr(ppm, "_STATE_PATH", state / "pp_state.json")
    persisted = {"pair": "EUR_USD", "side": "long", "anchor": 1.1,
                 "created": T0.isoformat(), "parent_setup": "s1",
                 "cell_key": "EUR_USD|ny|s1", "gid": "old-active-parent",
                 "probe": False, "fmt": "offsets", "levels": {}}
    (state / "pp_state.json").write_text(json.dumps({"grids": [persisted]}))
    pp = ppm.PartyPackage.__new__(ppm.PartyPackage)
    pp.grids = {}
    pp._load_state()
    assert pp.grids["EUR_USD"].probe is True
    assert pp.grids["EUR_USD"].quiesced is False


def test_grid_owned_by_shadow_is_quiesced_on_restart(tmp_path, monkeypatch):
    import modules.management.party_package as ppm

    cells = tmp_path / "config" / "cells"
    cells.mkdir(parents=True)
    (cells / "EUR_USD.json").write_text(json.dumps({"sessions": {"ny": {
        "setups": [{"id": "s1", "status": "SHADOW"}]}}}))
    state = tmp_path / "data"
    state.mkdir()
    monkeypatch.setattr(ppm, "_STATE_PATH", state / "pp_state.json")
    persisted = {"pair": "EUR_USD", "side": "long", "anchor": 1.1,
                 "created": T0.isoformat(), "parent_setup": "s1",
                 "cell_key": "EUR_USD|ny|s1", "gid": "old-parent",
                 "probe": False, "fmt": "offsets", "levels": {}}
    (state / "pp_state.json").write_text(json.dumps({"grids": [persisted]}))
    pp = ppm.PartyPackage.__new__(ppm.PartyPackage)
    pp.grids = {}
    pp._load_state()
    assert pp.grids["EUR_USD"].quiesced is True


def test_seat_bookkeeping_exercises_production_helper():
    seats = {}
    update_cheater_seat_book("CHEATER-PROBE", seats, "X|y|z", "now",
                             {"policy": "FAMILY_PP", "cs": 1.5})
    assert seats["X|y|z"]["policy"] == "FAMILY_PP"
    update_cheater_seat_book("GRADUATE", seats, "X|y|z", "later")
    assert "X|y|z" not in seats


def test_probe_cap_and_leash_do_not_depend_on_auxiliary_state():
    bmap = {
        ("EUR_USD", "ny", "a"): {"status": "PROBE"},
        ("GBP_USD", "ny", "b"): {"status": "SHADOW"},
    }
    assert probe_seat_count(bmap) == 1
    assert probe_leash_breached([-46.0], DEFAULT_CFG)
    assert probe_leash_breached([20.0, -30.0], DEFAULT_CFG)
    assert probe_leash_breached([-1.0, -1.0], DEFAULT_CFG)
    assert not probe_leash_breached([20.0, -5.0], DEFAULT_CFG)


def test_era_reset_is_staged_before_status_truth_can_change():
    st = {"era_start": {"X|y|z": "old"},
          "last_eval_blocks": {"X|y|z": 12}}
    stage_era_reset(st, "X|y|z", "new")
    assert st["era_start"]["X|y|z"] == "new"
    assert "X|y|z" not in st["last_eval_blocks"]


def test_commissioning_config_is_locked_to_one_seat():
    cfg = json.loads((Path(__file__).parents[1]
                      / "config" / "governor_config.json").read_text())
    # Parent-metric lane switched ON by operator decision 2026-08-03
    # (bar 10 episodes / 5 days). The CODE default stays fail-closed.
    assert cfg["allow_promotions"] is True
    assert DEFAULT_CFG["allow_promotions"] is False
    # `cheater_promotion_enabled` is the COMMISSIONER's switch, not a constant:
    # it legitimately flips to true on reaching COMMISSIONED_1 (first observed
    # 2026-08-06T12:56Z after the B-120 deadlock fix). Asserting it stays false
    # was asserting that autonomy never works. What must ALWAYS hold is the
    # blast radius — one seat, v4 ticket, full replay window — plus the code
    # default staying fail-closed for a fresh install.
    assert DEFAULT_CFG["cheater_promotion_enabled"] is False
    assert cfg["cheater_metric_version"] == "family-cycle-v4"
    # B-131 (2026-08-18): the Commissioner holds EXPANSION authority ("broker
    # validation permits expansion") and may legitimately raise this to 2 while
    # COMMISSIONED. The absolute ==1 pin turned a sanctioned expansion into a
    # red suite, which blocked every push AND triggered the Commissioner's own
    # suite-health guard — it decommissioned itself over the disagreement.
    # Pin the ROOF (blast radius), not the exact value.
    assert cfg["cheater_max_seats"] in (1, 2)
    assert cfg["cheater_replay_days"] >= 8.0
    assert cfg["truth_check_gate"] is True


def test_cheater_diagnostic_refuses_non_dry_run():
    repo = Path(__file__).parents[1]
    run = subprocess.run(
        [sys.executable, str(repo / "ops" / "governor.py"),
         "--cheater-diagnostic"], capture_output=True, text=True, cwd=repo)
    assert run.returncode == 2
    assert "requires --dry-run" in run.stderr
