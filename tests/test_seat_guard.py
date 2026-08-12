"""tests/test_seat_guard.py — B-127: /api/cell/status must account for seats.

The 2026-08-10 operator restore flipped a cell to PROBE through the dashboard
endpoint with no seat accounting and silently over-filled the pool to 10/9 —
every docket candidate then deferred for ~4 days while the ledger showed
nothing wrong. The guard: a flip INTO a PROBE seat that would exceed
max_probe_seats_total is refused unless explicitly confirmed with
confirm="OVERSEAT" (the reaper's typed-confirm pattern); confirmed overrides
are flagged for the ledger. Seat-reducing and lateral flips are NEVER guarded
— demotions must always work — and an unreadable governor config fails CLOSED
for seat entry only.
"""
import json

import pytest

from ops import server


def _cell(pair, statuses):
    return {
        "pair": pair,
        "sessions": {
            "ny": {
                "enabled": True,
                "setups": [
                    {"id": f"setup_{i}", "side": "short", "status": st,
                     "exit": {"mode": "ratchet", "sl_pips": 50.0,
                              "trigger_pips": 7.5, "trail_pips": 2.5}}
                    for i, st in enumerate(statuses)
                ],
            }
        },
    }


@pytest.fixture
def seat_world(tmp_path, monkeypatch):
    """Two cell files, 3 PROBEs on disk, ceiling parameterized per-test."""
    cells = tmp_path / "cells"
    cells.mkdir()
    (cells / "EUR_USD.json").write_text(
        json.dumps(_cell("EUR_USD", ["PROBE", "SHADOW", "ACTIVE"])))
    (cells / "GBP_USD.json").write_text(
        json.dumps(_cell("GBP_USD", ["PROBE", "PROBE", "SHADOW"])))
    gov = tmp_path / "governor_config.json"
    monkeypatch.setattr(server, "_CELLS_DIR", cells)
    monkeypatch.setattr(server, "_GOVERNOR_CFG", gov)

    def set_ceiling(n):
        gov.write_text(json.dumps({"max_probe_seats_total": n}))
    return set_ceiling


def test_probe_count_is_status_derived_across_files(seat_world):
    assert server._count_probe_seats() == 3


def test_entry_under_ceiling_passes(seat_world):
    seat_world(4)
    res = server._set_cell_status("EUR_USD", "ny", "setup_1", "PROBE")
    assert res["status"] == "PROBE" and "over_ceiling" not in res


def test_entry_at_ceiling_refused_with_override_hint(seat_world):
    seat_world(3)
    with pytest.raises(ValueError, match="OVERSEAT"):
        server._set_cell_status("EUR_USD", "ny", "setup_1", "PROBE")
    # refused = nothing written
    assert server._count_probe_seats() == 3


def test_confirmed_override_applies_and_is_flagged(seat_world):
    seat_world(3)
    res = server._set_cell_status("EUR_USD", "ny", "setup_1", "PROBE",
                                  confirm="OVERSEAT")
    assert res["status"] == "PROBE" and res["over_ceiling"] is True
    assert server._count_probe_seats() == 4


def test_wrong_confirm_token_still_refused(seat_world):
    seat_world(3)
    with pytest.raises(ValueError, match="seat ceiling"):
        server._set_cell_status("EUR_USD", "ny", "setup_1", "PROBE",
                                confirm="yes please")


def test_demotion_never_guarded_even_over_ceiling(seat_world):
    seat_world(1)  # already 3 probes on disk: pool is far over this ceiling
    res = server._set_cell_status("GBP_USD", "ny", "setup_0", "SHADOW")
    assert res["status"] == "SHADOW"
    assert server._count_probe_seats() == 2


def test_lateral_probe_to_probe_never_guarded(seat_world):
    seat_world(1)
    res = server._set_cell_status("EUR_USD", "ny", "setup_0", "PROBE")
    assert res["status"] == "PROBE"


def test_active_entry_is_not_probe_guarded(seat_world):
    seat_world(1)  # ACTIVE is not a probe seat; ceiling must not apply
    res = server._set_cell_status("EUR_USD", "ny", "setup_1", "ACTIVE")
    assert res["status"] == "ACTIVE"


def test_unreadable_governor_config_fails_closed_for_entry_only(seat_world):
    # no set_ceiling call -> governor config file does not exist
    with pytest.raises(ValueError, match="refusing PROBE entry"):
        server._set_cell_status("EUR_USD", "ny", "setup_1", "PROBE")
    # ...but demotions are unaffected
    res = server._set_cell_status("GBP_USD", "ny", "setup_0", "SHADOW")
    assert res["status"] == "SHADOW"


def test_ledger_entry_carries_the_override_flag(seat_world, tmp_path,
                                                monkeypatch):
    seat_world(3)
    ledger = tmp_path / "governor_ledger.jsonl"
    monkeypatch.setattr(server, "_GOVERNOR_LEDGER", ledger)
    res = server._set_cell_status("EUR_USD", "ny", "setup_1", "PROBE",
                                  confirm="OVERSEAT")
    server._ledger_status_flip(res, "operator (test)", "unit:1")
    entry = json.loads(ledger.read_text().strip())
    assert entry["result"]["over_ceiling"] is True
    assert entry["action"] == "OPERATOR-FLIP"
