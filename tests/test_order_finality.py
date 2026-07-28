"""tests/test_order_finality.py — broker uncertainty is quarantined, never
guessed (external review round 2).

Acceptance list: HTTP 400 is a broker response, not transport; timeout→fill
adopts; timeout→cancel returns rejected (empty id); timeout→endless-404 and
timeout→PENDING produce OrderUncertain + quarantine; a proven rejection
clears quarantine; empty parent fills create no manager; quarantine blocks
new entries and popper fires.
"""
import socket
import urllib.error
from types import SimpleNamespace

import pytest

from core.broker.oanda import OandaBroker, OrderUncertain


def _broker(fake_req):
    b = object.__new__(OandaBroker)
    b._base, b._token, b._acct = "https://test", "t", "acct"
    b._quarantine = {}
    b._req = fake_req
    return b


@pytest.fixture(autouse=True)
def _fast_sleep(monkeypatch):
    monkeypatch.setattr("core.broker.oanda.time.sleep", lambda s: None)


def _place(b):
    return b.place_market("EUR_USD", "long", units=1000, sl_pips=50,
                          entry_price=1.10000)


def test_http_error_is_broker_response_not_transport():
    calls = []

    def fake_req(method, path, body=None):
        calls.append((method, path))
        if method == "POST":
            raise urllib.error.HTTPError(path, 400, "insufficient margin", {}, None)
        raise AssertionError("reconciliation must NOT run for an HTTP response")

    b = _broker(fake_req)
    with pytest.raises(urllib.error.HTTPError):
        _place(b)
    assert all(m == "POST" for m, _ in calls)
    assert not b.quarantined


def test_timeout_then_fill_adopts():
    def fake_req(method, path, body=None):
        if method == "POST":
            raise socket.timeout("boom")
        if "/orders/@sv6-" in path:
            return {"order": {"state": "FILLED", "fillingTransactionID": "9"}}
        if "/transactions/9" in path:
            return {"transaction": {"price": "1.10007",
                                    "tradeOpened": {"tradeID": "42"}}}
        raise AssertionError(path)

    b = _broker(fake_req)
    out = _place(b)
    assert out["id"] == "42" and out["price"] == "1.10007"
    assert not b.quarantined


def test_timeout_then_cancel_is_rejected_no_fill():
    def fake_req(method, path, body=None):
        if method == "POST":
            raise socket.timeout("boom")
        if "/orders/@sv6-" in path:
            return {"order": {"state": "CANCELLED"}}
        raise AssertionError(path)

    b = _broker(fake_req)
    out = _place(b)
    assert out["id"] == "", "a proven cancel is a no-fill, not an exception"
    assert not b.quarantined


def test_timeout_then_endless_404_quarantines():
    def fake_req(method, path, body=None):
        if method == "POST":
            raise socket.timeout("boom")
        raise urllib.error.HTTPError(path, 404, "nf", {}, None)

    b = _broker(fake_req)
    with pytest.raises(OrderUncertain):
        _place(b)
    assert len(b.quarantined) == 1, \
        "404 is not proof of non-delivery — the intent must be quarantined"


def test_timeout_then_pending_quarantines():
    def fake_req(method, path, body=None):
        if method == "POST":
            raise socket.timeout("boom")
        if "/orders/@sv6-" in path:
            return {"order": {"state": "PENDING"}}
        raise AssertionError(path)

    b = _broker(fake_req)
    with pytest.raises(OrderUncertain):
        _place(b)
    assert b.quarantined


def test_retry_quarantine_clears_on_proven_rejection():
    def fake_req(method, path, body=None):
        if "/orders/@lost-1" in path:
            return {"order": {"state": "CANCELLED"}}
        raise AssertionError(path)

    b = _broker(fake_req)
    b._quarantine["lost-1"] = {"pair": "EUR_USD"}
    b.retry_quarantine()
    assert not b.quarantined


def test_retry_quarantine_keeps_filled_flagged():
    def fake_req(method, path, body=None):
        if "/orders/@lost-2" in path:
            return {"order": {"state": "FILLED", "fillingTransactionID": "5"}}
        if "/transactions/5" in path:
            return {"transaction": {"tradeOpened": {"tradeID": "77"}}}
        raise AssertionError(path)

    b = _broker(fake_req)
    b._quarantine["lost-2"] = {"pair": "EUR_USD"}
    b.retry_quarantine()
    assert "lost-2" in b.quarantined, \
        "a filled orphan stays flagged (and entries blocked) until restart adopts it"


# ── engine guards ────────────────────────────────────────────────────────────

def _engine_stub(broker):
    from core.engine import Engine
    e = object.__new__(Engine)
    e.broker = broker
    e.managers = {}
    e.recent_events = []
    return e


def _ticket():
    return SimpleNamespace(pair="EUR_USD", direction="long", cell=None,
                           session="london")


def _views():
    return [SimpleNamespace(pair="EUR_USD", ask=1.1, bid=1.0998,
                            spread_pips=2.0)]


def test_quarantine_blocks_new_entries():
    placed = []
    broker = SimpleNamespace(quarantined={"lost": {}},
                             place_market=lambda *a, **k: placed.append(1))
    e = _engine_stub(broker)
    from datetime import datetime, timezone
    e._open_trade(_ticket(), _views(), datetime.now(timezone.utc))
    assert not placed and not e.managers


def test_empty_parent_fill_creates_no_manager():
    broker = SimpleNamespace(
        quarantined={},
        size_units=lambda *a, **k: 1000,
        place_market=lambda *a, **k: {"id": "", "price": "", "raw": {}})
    e = _engine_stub(broker)
    from datetime import datetime, timezone
    e._open_trade(_ticket(), _views(), datetime.now(timezone.utc))
    assert not e.managers, "Position(oanda_trade_id='') must be impossible"
