"""tests/test_trading_pause.py — soft TRADING PAUSE switch.

Covers config/runtime.py (flag round-trip + fail-safe defaults), the server
POST /api/trading handler (confirm friction in live mode), and that /api/state
exposes the flag. The engine entry-path guard is documented + smoke-checked for
the code path (a full engine run needs a broker/feed, out of scope for a unit).
"""
import json

import pytest

from config import runtime
from ops import server


@pytest.fixture
def runtime_path(tmp_path, monkeypatch):
    p = tmp_path / "runtime.json"
    monkeypatch.setattr(runtime, "RUNTIME_PATH", p)
    return p


# ── flag file round-trip + fail-safe ──────────────────────────────────────────
def test_defaults_true_when_file_absent(runtime_path):
    assert not runtime_path.exists()
    assert runtime.trading_enabled() is True          # fresh clone trades


def test_round_trip(runtime_path):
    runtime.set_trading_enabled(False)
    assert json.loads(runtime_path.read_text())["trading_enabled"] is False
    assert runtime.trading_enabled() is False
    runtime.set_trading_enabled(True)
    assert runtime.trading_enabled() is True


def test_set_preserves_other_keys(runtime_path):
    runtime_path.write_text(json.dumps({"trading_enabled": True, "_note": "keep me"}))
    runtime.set_trading_enabled(False)
    on_disk = json.loads(runtime_path.read_text())
    assert on_disk["trading_enabled"] is False
    assert on_disk["_note"] == "keep me"


def test_fail_closed_on_unreadable_file(runtime_path):
    # DOCTRINE REVERSED 2026-07-27 (external review): a corrupted pause file
    # must NEVER restart trading. No last-known-good -> PAUSED.
    runtime._runtime_lkg.forget()
    runtime_path.write_text("{ this is not json")
    assert runtime.trading_enabled() is False
    # ...and with a last-known-good, corruption preserves the last state:
    runtime_path.write_text(json.dumps({"trading_enabled": True}))
    assert runtime.trading_enabled() is True
    runtime_path.write_text("{ corrupted again")
    assert runtime.trading_enabled() is True


@pytest.mark.parametrize("val,expected", [
    (True, True), (False, False), (1, True), (0, False),
    ("true", True), ("off", False), ("yes", True),
    (None, False),  # review round 2: a PRESENT null is corruption -> fail closed
])
def test_tolerant_value_parsing(runtime_path, val, expected):
    runtime_path.write_text(json.dumps({"trading_enabled": val}))
    assert runtime.trading_enabled() is expected


# ── POST /api/trading handler ─────────────────────────────────────────────────
def test_pause_is_unconfirmed(runtime_path):
    code, body = server._set_trading({"enabled": False})
    assert code == 200 and body["ok"] and body["trading_enabled"] is False
    assert runtime.trading_enabled() is False


def test_resume_in_practice_is_unconfirmed(runtime_path, monkeypatch):
    monkeypatch.setattr("config.credentials.load_local", lambda: {"mode": "practice"})
    code, body = server._set_trading({"enabled": True})
    assert code == 200 and body["trading_enabled"] is True


def test_resume_in_live_requires_confirm(runtime_path, monkeypatch):
    monkeypatch.setattr("config.credentials.load_local", lambda: {"mode": "live"})
    code, body = server._set_trading({"enabled": True})            # no confirm
    assert code == 400 and "TRADE REAL MONEY" in body["error"]
    assert runtime.trading_enabled() is True                       # unchanged (was default)
    code, body = server._set_trading({"enabled": True, "confirm": "TRADE REAL MONEY"})
    assert code == 200 and body["trading_enabled"] is True


def test_pause_in_live_needs_no_confirm(runtime_path, monkeypatch):
    monkeypatch.setattr("config.credentials.load_local", lambda: {"mode": "live"})
    code, body = server._set_trading({"enabled": False})
    assert code == 200 and body["trading_enabled"] is False


def test_bad_payload_rejected(runtime_path):
    for bad in [{}, {"enabled": "yes"}, {"enabled": 1}, "notadict"]:
        code, body = server._set_trading(bad)
        assert code == 400 and not body["ok"]


# ── engine entry-path guard (contract check) ──────────────────────────────────
def test_engine_reads_flag_and_guards_entries():
    """The engine imports trading_enabled and gates the open loop on it. This
    pins the wiring so the guard can't be silently removed."""
    import inspect
    from core import engine
    assert engine.trading_enabled is runtime.trading_enabled
    src = inspect.getsource(engine.Engine._cycle)
    # management runs unconditionally; the open loop is gated by the flag
    assert "self._manage(now)" in src
    assert "trading_enabled()" in src
    assert "if not _trading_on:" in src
