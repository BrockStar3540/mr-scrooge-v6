"""tests/test_fail_closed.py — safety controls fail CLOSED (external review).

A corrupted pause file must never restart trading; a corrupted popper config
must never re-arm grids or erase per-cell opt-outs; a corrupted governor
config must never run the governor. Policy under test: valid value wins and
becomes last-known-good; corruption returns the LKG; corruption with no LKG
returns the SAFE state (paused / poppers off / governor disabled).
"""
import importlib
import json

import pytest

import config.runtime as runtime
import modules.management.party_package as pp


@pytest.fixture()
def rt(tmp_path, monkeypatch):
    path = tmp_path / "runtime.json"
    monkeypatch.setattr(runtime, "RUNTIME_PATH", path)
    runtime._runtime_lkg.forget()
    runtime._last_warn["t"] = 0.0
    return path


def test_runtime_valid_values_respected(rt):
    rt.write_text('{"trading_enabled": false}')
    assert runtime.trading_enabled() is False
    rt.write_text('{"trading_enabled": true}')
    assert runtime.trading_enabled() is True


def test_runtime_corruption_returns_last_known_good_pause(rt):
    rt.write_text('{"trading_enabled": false}')
    assert runtime.trading_enabled() is False
    rt.write_text('{"trading_enabled": fal')          # corrupted mid-write
    assert runtime.trading_enabled() is False, \
        "a corrupted pause file must never restart trading"


def test_runtime_corruption_with_no_lkg_pauses(rt):
    rt.write_text("NOT JSON {{{")
    assert runtime.trading_enabled() is False


def test_runtime_malformed_value_fails_closed(rt):
    rt.write_text('{"trading_enabled": "banana"}')
    assert runtime.trading_enabled() is False


def test_runtime_missing_file_is_fresh_install_default(rt):
    assert runtime.trading_enabled() is True          # never configured
    rt.write_text('{"trading_enabled": false}')
    assert runtime.trading_enabled() is False
    rt.unlink()                                       # deleted after a pause →
    assert runtime.trading_enabled() is False         # LKG (paused) must win


@pytest.fixture()
def ppcfg(tmp_path, monkeypatch):
    path = tmp_path / "pp_config.json"
    monkeypatch.setattr(pp, "_CONFIG_PATH", path)
    pp._pp_lkg.forget()
    return path


def test_pp_corruption_returns_last_known_good(ppcfg):
    ppcfg.write_text(json.dumps({"enabled": True,
                                 "per_cell": {"GBP_USD|london": False}}))
    good = pp.pp_config()
    assert good["enabled"] is True and good["per_cell"] == {"GBP_USD|london": False}
    ppcfg.write_text("{corrupt")
    again = pp.pp_config()
    assert again["enabled"] is True, "LKG should survive corruption"
    assert again["per_cell"] == {"GBP_USD|london": False}, \
        "corruption must not erase per-cell opt-outs (B-096 class)"


def test_pp_corruption_with_no_lkg_disables_poppers(ppcfg):
    ppcfg.write_text("{corrupt")
    cfg = pp.pp_config()
    assert cfg["enabled"] is False, \
        "corrupted pp config with no LKG must fail closed (poppers off)"


def test_governor_corrupted_config_fails_closed(tmp_path, monkeypatch):
    import importlib.util
    from pathlib import Path
    REPO = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("governor", REPO / "ops" / "governor.py")
    gov = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gov)
    bad = tmp_path / "governor_config.json"
    bad.write_text("]]] not json")
    monkeypatch.setattr(gov, "CFG_F", bad)
    assert gov.cfg()["enabled"] is False, \
        "a corrupted governor config must not run the governor"
    missing = tmp_path / "absent.json"
    monkeypatch.setattr(gov, "CFG_F", missing)
    assert gov.cfg()["enabled"] is True   # never configured → defaults


@pytest.mark.parametrize("value,expected", [
    ("true", True), ("false", False), (1, True), (0, False),
    ("yes", True), ("off", False),
])
def test_runtime_coercions(rt, value, expected):
    rt.write_text(json.dumps({"trading_enabled": value}))
    assert runtime.trading_enabled() is expected


def test_runtime_null_value_is_corruption_not_default(rt):
    # review round 2: a PRESENT key with null is corruption -> fail closed
    rt.write_text(json.dumps({"trading_enabled": None}))
    assert runtime.trading_enabled() is False


def test_runtime_absent_key_in_valid_file_is_default_enabled(rt):
    rt.write_text(json.dumps({"_note": "no gate key"}))
    assert runtime.trading_enabled() is True
