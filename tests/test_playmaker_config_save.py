"""tests/test_playmaker_config_save.py — the dashboard PLAYMAKER save must
round-trip EVERY field of config/playmaker_config.json.

Regression (2026-07-15): the save path rebuilt the file from only
{schema, account, defaults, per_pair}, silently dropping
account.max_per_currency_direction (→ reverted the live per-currency risk cap to
the code default of 1), all disabled_cells, the inverted_live/shadow sets, every
per_cell_* range and the _note* annotations.  These tests pin the round-trip.
"""
import json

import pytest

from ops import server


# A realistic on-disk config: the three editable blocks PLUS the full governance
# layer + risk cap + note annotations that a naive save used to wipe.
_FULL = {
    "schema": "v1",
    "account": {
        "max_concurrent_trades": 4,
        "margin_pct_per_trade": 0.2,
        "max_per_currency_direction": 4,
    },
    "defaults": {
        "enabled": True,
        "min_direction_score": 0.25,
        "min_dir_certainty": 0.30,
        "min_mom_certainty": 0.25,
        "cooldown_after_sl_min": 0.0,
        "profile_shadow_enabled": True,
        "calibration_log_enabled": True,
    },
    "per_pair": {
        "USD_CHF": {"enabled": False, "_note": "kill USD_CHF entirely"},
        "USD_CAD": {"min_dir_certainty": 0.25, "_note": "floor 0.30->0.25"},
    },
    "_note": "Per-cell disable list rationale — MUST survive a dashboard save.",
    "disabled_cells": [["EUR_JPY", "london", "short"], ["USD_CHF", "ny", "long"]],
    "inverted_shadow_cells": [],
    "inverted_live_cells": [["USD_JPY", "asia"], ["GBP_USD", "ny"]],
    "random_pick": False,
    "per_cell_mom_cert_max": {"AUD_JPY/asia": 0.5},
    "per_cell_dir_cert_min": {"GBP_USD/ny": 0.52},
    "per_cell_willr_range": {"EUR_JPY/ny/short": [-100, -80]},
    "_note_2026-07-02": "annotation two",
}


@pytest.fixture
def cfg_path(tmp_path, monkeypatch):
    p = tmp_path / "playmaker_config.json"
    p.write_text(json.dumps(_FULL, indent=2))
    monkeypatch.setattr(server, "_PM_CONFIG_PATH", p)
    return p


def _save_and_reload(cfg_path, payload):
    server._write_playmaker_config(payload)
    return json.loads(cfg_path.read_text())


def test_dashboard_style_save_preserves_governance_and_caps(cfg_path):
    """A minimal dashboard payload (the 3 editable blocks, panel-style) must NOT
    drop the currency cap, disabled_cells, inversions, per_cell_* or _notes."""
    payload = {
        "schema": "v1",
        "account": {"margin_pct_per_trade": 0.15, "max_concurrent_trades": 5,
                    "max_per_currency_direction": 3},
        "defaults": {"enabled": True, "min_direction_score": 0.30,
                     "min_dir_certainty": 0.30, "min_mom_certainty": 0.25,
                     "cooldown_after_sl_min": 0.0},
        "per_pair": {"USD_CHF": {"enabled": False},
                     "USD_CAD": {"min_dir_certainty": 0.22}},
    }
    out = _save_and_reload(cfg_path, payload)
    # edited fields applied
    assert out["account"]["margin_pct_per_trade"] == pytest.approx(0.15)
    assert out["account"]["max_concurrent_trades"] == 5
    assert out["account"]["max_per_currency_direction"] == 3   # editable + round-trips
    assert out["defaults"]["min_direction_score"] == pytest.approx(0.30)
    assert out["per_pair"]["USD_CAD"]["min_dir_certainty"] == pytest.approx(0.22)
    # governance preserved verbatim
    assert out["disabled_cells"] == _FULL["disabled_cells"]
    assert out["inverted_live_cells"] == _FULL["inverted_live_cells"]
    assert out["inverted_shadow_cells"] == _FULL["inverted_shadow_cells"]
    assert out["per_cell_mom_cert_max"] == _FULL["per_cell_mom_cert_max"]
    assert out["per_cell_dir_cert_min"] == _FULL["per_cell_dir_cert_min"]
    assert out["per_cell_willr_range"] == _FULL["per_cell_willr_range"]
    assert out["random_pick"] is False
    # governance-defaults toggles preserved
    assert out["defaults"]["profile_shadow_enabled"] is True
    assert out["defaults"]["calibration_log_enabled"] is True
    # note annotations preserved
    assert out["_note"] == _FULL["_note"]
    assert out["_note_2026-07-02"] == _FULL["_note_2026-07-02"]
    # per-pair _note annotations preserved (unknown sub-keys not stripped)
    assert out["per_pair"]["USD_CHF"]["_note"] == _FULL["per_pair"]["USD_CHF"]["_note"]
    assert out["per_pair"]["USD_CAD"]["_note"] == _FULL["per_pair"]["USD_CAD"]["_note"]


def test_currency_cap_omitted_from_payload_keeps_disk_value(cfg_path):
    """If the panel omits the currency cap, the on-disk value must be kept (never
    reverted to the code default of 1)."""
    payload = {"account": {"margin_pct_per_trade": 0.1, "max_concurrent_trades": 4}}
    out = _save_and_reload(cfg_path, payload)
    assert out["account"]["max_per_currency_direction"] == 4


def test_int_coercion(cfg_path):
    out = _save_and_reload(cfg_path, {"account": {"max_per_currency_direction": 3.0,
                                                  "max_concurrent_trades": 6.0}})
    assert out["account"]["max_per_currency_direction"] == 3
    assert isinstance(out["account"]["max_per_currency_direction"], int)
    assert out["account"]["max_concurrent_trades"] == 6
    assert isinstance(out["account"]["max_concurrent_trades"], int)


def test_out_of_range_rejected_and_disk_untouched(cfg_path):
    with pytest.raises(ValueError):
        server._write_playmaker_config({"account": {"max_per_currency_direction": 99}})
    on_disk = json.loads(cfg_path.read_text())
    assert on_disk["account"]["max_per_currency_direction"] == 4   # failed write is atomic


def test_unknown_pair_rejected(cfg_path):
    with pytest.raises(ValueError):
        server._write_playmaker_config({"per_pair": {"XXX_YYY": {"enabled": True}}})


def test_acct_fields_exposed_for_dashboard():
    """The GET schema must advertise the currency cap so the panel renders an
    editable input for it."""
    assert "max_per_currency_direction" in server._PM_ACCT_FIELDS
    assert server._PM_ACCT_FIELDS["max_per_currency_direction"].get("int") is True
