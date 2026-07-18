"""tests/test_cell_controls.py — dashboard per-cell controls.

Covers the two new write endpoints' server-side logic:
  • POST /api/cell/status → _set_cell_status (flip ACTIVE/SHADOW/DISABLED)
  • POST /api/cell/exit   → _set_cell_exit   (per-cell exit geometry)

Both must round-trip, validate, and MERGE — never dropping other setups, other
sessions, structure, or unedited exit sub-keys (mode/trail_min/trail_max/_class).
"""
import json

import pytest

from ops import server


_SAMPLE = {
    "pair": "EUR_USD",
    "generated": "2026-07-04T08:00:04Z",
    "sessions": {
        "asia": {
            "enabled": True,
            "structure": {"tier": 3, "ev_gross_long": -5.4},
            "setups": [
                {
                    "id": "ps_floor_fade_long",
                    "side": "long",
                    "status": "SHADOW",
                    "horizon_min": 240,
                    "conditions": [{"feature": "ps_pos", "max": 0.15}],
                    "exit": {"mode": "ratchet", "sl_pips": 40.0, "trigger_pips": 7.5,
                             "trail_pips": 2.5, "trail_mult": 0.0, "trail_min": 2.5,
                             "trail_max": 10.0, "_class": "RANGE_SIZED"},
                    "sizing": {"risk_pct": 0.2},
                    "notes": "keep me",
                },
            ],
            "notes": "cell note stays",
        },
        "ny": {
            "enabled": True,
            "setups": [{"id": "ps_ceil_fade_short", "side": "short", "status": "SHADOW",
                        "exit": {"mode": "ratchet", "sl_pips": 50.0, "trigger_pips": 7.5,
                                 "trail_pips": 2.5}}],
        },
    },
}


@pytest.fixture
def cells_dir(tmp_path, monkeypatch):
    d = tmp_path / "cells"
    d.mkdir()
    (d / "EUR_USD.json").write_text(json.dumps(_SAMPLE, indent=2))
    monkeypatch.setattr(server, "_CELLS_DIR", d)
    return d


def _reload(cells_dir):
    return json.loads((cells_dir / "EUR_USD.json").read_text())


# ── status flips ──────────────────────────────────────────────────────────────
def test_status_flip_round_trips(cells_dir):
    res = server._set_cell_status("EUR_USD", "asia", "ps_floor_fade_long", "ACTIVE")
    assert res["old_status"] == "SHADOW" and res["status"] == "ACTIVE"
    on_disk = _reload(cells_dir)
    setup = on_disk["sessions"]["asia"]["setups"][0]
    assert setup["status"] == "ACTIVE"
    # everything else preserved
    assert setup["notes"] == "keep me"
    assert setup["exit"]["sl_pips"] == 40.0
    assert on_disk["sessions"]["asia"]["notes"] == "cell note stays"
    assert on_disk["sessions"]["asia"]["structure"]["tier"] == 3
    # the OTHER session's setup is untouched
    assert on_disk["sessions"]["ny"]["setups"][0]["status"] == "SHADOW"


@pytest.mark.parametrize("bad", ["ON", "active", "enabled", "", "TRADE", None])
def test_status_rejects_bad_value(cells_dir, bad):
    with pytest.raises(ValueError):
        server._set_cell_status("EUR_USD", "asia", "ps_floor_fade_long", bad)
    # disk untouched after a rejected write
    assert _reload(cells_dir)["sessions"]["asia"]["setups"][0]["status"] == "SHADOW"


def test_status_rejects_unknown_pair_session_setup(cells_dir):
    with pytest.raises(ValueError):
        server._set_cell_status("XXX_YYY", "asia", "ps_floor_fade_long", "ACTIVE")
    with pytest.raises(ValueError):
        server._set_cell_status("EUR_USD", "tokyo", "ps_floor_fade_long", "ACTIVE")
    with pytest.raises(ValueError):
        server._set_cell_status("EUR_USD", "asia", "no_such_setup", "ACTIVE")


# ── per-cell exit edits ───────────────────────────────────────────────────────
def test_exit_save_merges_and_preserves_subkeys(cells_dir):
    res = server._set_cell_exit("EUR_USD", "asia", "ps_floor_fade_long",
                                {"sl_pips": 60.0, "trigger_pips": 12.0})
    assert res["exit"]["sl_pips"] == 60.0 and res["exit"]["trigger_pips"] == 12.0
    ex = _reload(cells_dir)["sessions"]["asia"]["setups"][0]["exit"]
    # edited
    assert ex["sl_pips"] == 60.0 and ex["trigger_pips"] == 12.0
    # untouched sub-keys preserved (merge, not replace)
    assert ex["mode"] == "ratchet"
    assert ex["trail_min"] == 2.5 and ex["trail_max"] == 10.0
    assert ex["_class"] == "RANGE_SIZED"
    assert ex["trail_pips"] == 2.5   # not in the patch → kept


@pytest.mark.parametrize("patch", [
    {"sl_pips": 3.0},          # below 5
    {"sl_pips": 500.0},        # above 200
    {"trigger_pips": 99.0},    # above 50
    {"trail_pips": 40.0},      # above 30
    {"trail_mult": 5.0},       # above 3
    {"sl_pips": "abc"},        # not a number
    {"bogus_field": 1.0},      # unknown field
    {},                        # nothing to save
])
def test_exit_rejects_out_of_range_and_unknown(cells_dir, patch):
    with pytest.raises(ValueError):
        server._set_cell_exit("EUR_USD", "asia", "ps_floor_fade_long", patch)
    # atomic: disk unchanged
    assert _reload(cells_dir)["sessions"]["asia"]["setups"][0]["exit"]["sl_pips"] == 40.0


def test_exit_rejects_trail_ge_trigger(cells_dir):
    # trail must stay < trigger (first ratchet lock > 0). Existing trigger is 7.5.
    with pytest.raises(ValueError):
        server._set_cell_exit("EUR_USD", "asia", "ps_floor_fade_long", {"trail_pips": 8.0})


def test_exit_fields_advertised():
    for k in ("sl_pips", "trigger_pips", "trail_pips", "trail_mult"):
        assert k in server._CELL_EXIT_FIELDS
