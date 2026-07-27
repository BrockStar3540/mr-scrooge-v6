"""tests/test_exec_truth.py — D-5 execution truth (external review).

The broker fill is the only true entry; the server-side SL anchors to the fill
(distance form), and management uses the executable side, never mid.
"""
import json

import pytest

from core.exec_truth import adopt_fill, executable_price
from core.broker.oanda import OandaBroker


# ── adopt_fill ───────────────────────────────────────────────────────────────

def test_adopt_fill_long_pays_slippage_when_filled_higher():
    entry, slip = adopt_fill(1.10000, {"price": "1.10012"}, "long", 0.0001)
    assert entry == 1.10012
    assert slip == pytest.approx(1.2)


def test_adopt_fill_short_pays_slippage_when_filled_lower():
    entry, slip = adopt_fill(1.10000, {"price": "1.09990"}, "short", 0.0001)
    assert entry == 1.09990
    assert slip == pytest.approx(1.0)


def test_adopt_fill_favorable_slippage_is_negative():
    entry, slip = adopt_fill(163.500, {"price": "163.490"}, "long", 0.01)
    assert entry == 163.490
    assert slip == pytest.approx(-1.0)


@pytest.mark.parametrize("bad", ["", None, "n/a", "0", "-1", {}])
def test_adopt_fill_missing_or_garbage_falls_back_to_quote(bad):
    entry, slip = adopt_fill(1.23456, {"price": bad}, "long", 0.0001)
    assert entry == 1.23456
    assert slip is None, "fallback must be loud (None), never a silent zero"


def test_adopt_fill_empty_trade_dict():
    entry, slip = adopt_fill(1.23456, {}, "short", 0.0001)
    assert (entry, slip) == (1.23456, None)


# ── executable_price ─────────────────────────────────────────────────────────

def test_longs_exit_at_bid_shorts_at_ask():
    assert executable_price(1.1000, 1.1002, "long") == 1.1000
    assert executable_price(1.1000, 1.1002, "short") == 1.1002


# ── place_market sends a fill-anchored SL distance ───────────────────────────

def _broker_with_captured_requests(captured, fill_price="1.10005", trade_id="42"):
    b = object.__new__(OandaBroker)          # skip __init__ (no creds in tests)
    b._base, b._token, b._acct = "https://test", "t", "acct"

    def fake_req(method, path, body=None):
        captured.append((method, path, body))
        return {"orderFillTransaction": {
            "price": fill_price,
            "tradeOpened": {"tradeID": trade_id}}}

    b._req = fake_req
    return b


def test_place_market_sends_sl_as_distance_not_price():
    captured = []
    b = _broker_with_captured_requests(captured)
    out = b.place_market("EUR_USD", "long", units=1000,
                         sl_pips=50.0, entry_price=1.10000)
    order = captured[-1][2]["order"]
    assert "distance" in order["stopLossOnFill"], \
        "SL must be fill-anchored (distance), not quote-anchored (price)"
    assert "price" not in order["stopLossOnFill"]
    assert order["stopLossOnFill"]["distance"] == "0.00500"
    assert out["id"] == "42" and out["price"] == "1.10005"


def test_place_market_jpy_distance_precision():
    captured = []
    b = _broker_with_captured_requests(captured, fill_price="163.502")
    b.place_market("USD_JPY", "short", units=1000,
                   sl_pips=60.0, entry_price=163.500)
    order = captured[-1][2]["order"]
    assert order["stopLossOnFill"]["distance"] == "0.600"
    assert order["units"] == "-1000"


# ── stage D: order intent ids + timeout reconciliation ───────────────────────

def test_orders_carry_unique_intent_ids():
    captured = []
    b = _broker_with_captured_requests(captured)
    b.place_market("EUR_USD", "long", units=1000, sl_pips=50, entry_price=1.1)
    b.place_market("EUR_USD", "long", units=1000, sl_pips=50, entry_price=1.1)
    ids = [c[2]["order"]["clientExtensions"]["id"] for c in captured
           if c[0] == "POST"]
    assert len(ids) == 2 and ids[0] != ids[1]
    assert all(i.startswith("sv6-") for i in ids)


def test_timeout_after_accepted_order_reconciles_to_fill(monkeypatch):
    import socket
    from core.broker.oanda import OandaBroker
    b = object.__new__(OandaBroker)
    b._base, b._token, b._acct = "https://test", "t", "acct"
    calls = []

    def fake_req(method, path, body=None):
        calls.append((method, path))
        if method == "POST":
            raise socket.timeout("simulated transport loss after send")
        if "/orders/@sv6-" in path:
            return {"order": {"state": "FILLED", "fillingTransactionID": "777"}}
        if "/transactions/777" in path:
            return {"transaction": {"price": "1.10008",
                                    "tradeOpened": {"tradeID": "888"}}}
        raise AssertionError(f"unexpected call {method} {path}")

    b._req = fake_req
    monkeypatch.setattr("core.broker.oanda.time.sleep", lambda s: None)
    out = b.place_market("EUR_USD", "long", units=1000, sl_pips=50,
                         entry_price=1.10000)
    assert out["id"] == "888" and out["price"] == "1.10008", \
        "an accepted-then-timeout order must be adopted, not orphaned"


def test_timeout_with_no_order_at_broker_raises(monkeypatch):
    import socket
    import urllib.error
    from core.broker.oanda import OandaBroker
    b = object.__new__(OandaBroker)
    b._base, b._token, b._acct = "https://test", "t", "acct"

    def fake_req(method, path, body=None):
        if method == "POST":
            raise socket.timeout("simulated")
        raise urllib.error.HTTPError(path, 404, "not found", {}, None)

    b._req = fake_req
    monkeypatch.setattr("core.broker.oanda.time.sleep", lambda s: None)
    import pytest as _pytest
    with _pytest.raises(RuntimeError, match="safe to treat as not placed"):
        b.place_market("EUR_USD", "long", units=1000, sl_pips=50,
                       entry_price=1.10000)
