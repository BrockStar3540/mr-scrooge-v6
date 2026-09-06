"""tests/test_reaper.py — STALE-RED REAPER (v6.27.0, operator feature).

Covers config/runtime.py (reaper_config fail-closed parsing, set_reaper
round-trip preserving other keys, reap_due pure decision) and the server
POST /api/reaper handler (validation + LIVE confirm friction). The decision
input for both close sites is reap_due, covered here.

B-134 correction: this file used to claim the engine and party-package close
paths "reuse the audited B-119 close discipline verbatim". They did not — the
engine sites got the keep-the-manager half without the retry timer, and the
claim is why nobody looked. The close paths themselves are covered by
tests/test_close_backoff.py (engine) and tests/test_party_package.py (PP).
"""
import json
from datetime import datetime, timedelta, timezone

import pytest

from config import runtime
from ops import server


@pytest.fixture
def runtime_path(tmp_path, monkeypatch):
    p = tmp_path / "runtime.json"
    monkeypatch.setattr(runtime, "RUNTIME_PATH", p)
    return p


# ── reaper_config: FAIL-CLOSED parsing ───────────────────────────────────────

def test_absent_file_means_disabled(runtime_path):
    assert runtime.reaper_config() == {"enabled": False, "hours": 72.0}


def test_missing_key_means_disabled(runtime_path):
    runtime_path.write_text(json.dumps({"trading_enabled": True}))
    assert runtime.reaper_config()["enabled"] is False


@pytest.mark.parametrize("raw", [
    "yes",                          # not a dict
    {"enabled": "true"},            # non-bool enabled
    {"enabled": True, "hours": 0},  # hours < 1
    {"enabled": True, "hours": -5},
    {"enabled": True, "hours": "nan"},
    {"enabled": True, "hours": float("nan")},
])
def test_malformed_means_disabled(runtime_path, raw):
    runtime_path.write_text(json.dumps({"reaper": raw}, default=str))
    assert runtime.reaper_config()["enabled"] is False


def test_valid_config_parses(runtime_path):
    runtime_path.write_text(json.dumps({"reaper": {"enabled": True, "hours": 48}}))
    assert runtime.reaper_config() == {"enabled": True, "hours": 48.0}


# ── set_reaper: round-trip, preserves siblings ───────────────────────────────

def test_set_reaper_round_trip_preserves_trading_flag(runtime_path):
    runtime.set_trading_enabled(False)
    cfg = runtime.set_reaper(True, 36)
    assert cfg == {"enabled": True, "hours": 36.0}
    assert runtime.reaper_config() == {"enabled": True, "hours": 36.0}
    assert runtime.trading_enabled() is False          # sibling key untouched
    runtime.set_reaper(False)                          # hours kept when omitted
    assert runtime.reaper_config() == {"enabled": False, "hours": 36.0}


def test_set_reaper_bad_hours_falls_back_to_default(runtime_path):
    assert runtime.set_reaper(True, "junk")["hours"] == 72.0


# ── reap_due: the pure decision ──────────────────────────────────────────────

NOW = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)
CFG = {"enabled": True, "hours": 72.0}


def _age(hours):
    return NOW - timedelta(hours=hours)


def test_red_and_old_reaps():
    assert runtime.reap_due(_age(73), NOW, -4.2, CFG) is True


def test_red_but_young_survives():
    assert runtime.reap_due(_age(71), NOW, -40.0, CFG) is False


def test_green_and_old_survives():
    assert runtime.reap_due(_age(200), NOW, +0.1, CFG) is False


def test_flat_survives():
    assert runtime.reap_due(_age(200), NOW, 0.0, CFG) is False


def test_disabled_never_reaps():
    assert runtime.reap_due(_age(500), NOW, -50.0, {"enabled": False, "hours": 72.0}) is False


def test_defensive_on_naive_aware_mix():
    naive = datetime(2026, 8, 1, 0, 0)                 # no tzinfo
    assert runtime.reap_due(naive, NOW, -10.0, CFG) is False


def test_defensive_on_none_net():
    assert runtime.reap_due(_age(100), NOW, None, CFG) is False


# ── POST /api/reaper handler ─────────────────────────────────────────────────

def test_post_rejects_bad_body(runtime_path):
    code, body = server._set_reaper({"enabled": "yes"})
    assert code == 400 and body["ok"] is False
    code, body = server._set_reaper(None)
    assert code == 400


def test_post_rejects_bad_hours(runtime_path):
    code, body = server._set_reaper({"enabled": True, "hours": 0})
    assert code == 400
    code, body = server._set_reaper({"enabled": True, "hours": "x"})
    assert code == 400


def test_post_live_mode_requires_confirm(runtime_path, monkeypatch):
    from config import credentials
    monkeypatch.setattr(credentials, "load_local", lambda: {"mode": "live"})
    code, body = server._set_reaper({"enabled": True})
    assert code == 400 and "REAP" in body["error"]
    code, body = server._set_reaper({"enabled": True, "confirm": "REAP"})
    assert code == 200 and body["reaper"]["enabled"] is True
    # disabling is the safe direction — never needs confirm
    code, body = server._set_reaper({"enabled": False})
    assert code == 200 and body["reaper"]["enabled"] is False


def test_post_practice_mode_no_confirm_needed(runtime_path, monkeypatch):
    from config import credentials
    monkeypatch.setattr(credentials, "load_local", lambda: {"mode": "practice"})
    code, body = server._set_reaper({"enabled": True, "hours": 24})
    assert code == 200 and body["reaper"] == {"enabled": True, "hours": 24.0}


# ── B-125: every dashboard status flip is attributed + ledgered ──────────────

def test_flip_ledger_entry_attributed(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_GOVERNOR_LEDGER", tmp_path / "ledger.jsonl")
    res = {"pair": "EUR_USD", "session": "ny", "setup_id": "rg1_range_scalp_short",
           "old_status": "PROBE", "status": "SHADOW"}
    server._ledger_status_flip(res, "dashboard-ui", "1.2.3.4:5")
    line = json.loads((tmp_path / "ledger.jsonl").read_text())
    assert line["action"] == "OPERATOR-FLIP" and line["actor"] == "dashboard-ui"
    assert line["source"] == "1.2.3.4:5" and line["setup"] == "rg1_range_scalp_short"
    assert "PROBE -> SHADOW" in line["why"]


def test_flip_ledger_governor_actor(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_GOVERNOR_LEDGER", tmp_path / "ledger.jsonl")
    server._ledger_status_flip({"pair": "X", "session": "s", "setup_id": "y",
                                "old_status": "SHADOW", "status": "PROBE"},
                               "governor", "127.0.0.1:1")
    assert json.loads((tmp_path / "ledger.jsonl").read_text())["action"] == "GOVERNOR-FLIP"


def test_flip_ledger_failure_never_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_GOVERNOR_LEDGER", tmp_path)   # a DIRECTORY: open() fails
    server._ledger_status_flip({"pair": "X"}, "dashboard-ui", "?")   # must not raise
