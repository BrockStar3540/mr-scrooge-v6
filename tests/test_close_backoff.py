"""tests/test_close_backoff.py — B-134: engine close paths must back off.

B-119 gave the party-package poppers BOTH halves of the close discipline: a
rejected close keeps the trade tracked AND sets a retry timer. The two engine
paths (stale-red reaper, parent local-detect) shipped with only the first half,
so a close the broker refuses was re-submitted every manage tick.

Live cost, 2026-09-05/06: trade 10908 (AUD_USD) crossed the 72h reaper cap at
Sat 13:33Z with the market shut. 9,820 MARKET_HALTED order cancels in 15h —
one every 5.5s — a third of that account's entire transaction history.

These tests drive Engine._manage directly with fakes; the real broker/feed/PP
are never touched.
"""
import collections
from datetime import datetime, timedelta, timezone

import pytest

from core.engine import Engine
from core.broker.oanda import CloseRejected

NOW = datetime(2026, 9, 5, 13, 33, tzinfo=timezone.utc)
TID = "10908"
PAIR = "AUD_USD"


class _Ticket:
    direction = "short"


class _Pos:
    def __init__(self):
        self.oanda_trade_id = TID
        self.entry_price = 0.71587
        self.entry_time = NOW - timedelta(hours=73)   # past the 72h cap
        self.ticket = _Ticket()


class _Mgr:
    """Red, stale, and never signals on its own — isolates the reaper path."""
    def __init__(self, signal=None):
        self.position = _Pos()
        self._signal = signal
        self.updates = 0

    def net_pips(self, mid):
        return -45.2

    def update(self, mid, now):
        self.updates += 1
        return self._signal


class _Broker:
    def __init__(self, exc, open_ids=(TID,)):
        self.exc = exc
        self.close_calls = 0
        self.open_ids = set(open_ids)

    def open_positions(self):
        return [{"id": i, "instrument": PAIR} for i in sorted(self.open_ids)]

    def close_position(self, trade_id, units="ALL"):
        self.close_calls += 1
        if self.exc:
            raise self.exc


class _Feed:
    def pricing(self, pair):
        return 0.72039, 0.72052


class _PP:
    poppers: dict = {}
    grids: dict = {}

    def tick(self, *a, **k):
        return None


def _engine(broker, mgr):
    e = Engine.__new__(Engine)
    e.feed, e.broker, e.dry_run = _Feed(), broker, False
    e.managers = {PAIR: mgr}
    e._sl_history, e._cell_opens, e._close_backoff = {}, {}, {}
    e.recent_events = collections.deque(maxlen=40)
    e.last_manage_time = None
    e._last_reconcile = NOW          # reconcile not due — isolate the close path
    e.pp = _PP()
    return e


@pytest.fixture(autouse=True)
def _reaper_on(monkeypatch):
    monkeypatch.setattr("core.engine.reaper_config",
                        lambda: {"enabled": True, "hours": 72.0})


# ── the regression: one attempt per 30 min, not one per tick ─────────────────

@pytest.mark.parametrize("signal", [None, "exit"], ids=["reaper", "parent"])
def test_rejected_close_backs_off_instead_of_hammering(signal, monkeypatch):
    """A refused close must be retried once, then not again for 30 minutes."""
    if signal == "exit":
        # parent path: reaper disabled so the local-detect branch is the one
        # under test, and the manager signals an exit every tick.
        monkeypatch.setattr("core.engine.reaper_config",
                            lambda: {"enabled": False, "hours": 72.0})
        sig = type("S", (), {"reason": "trail", "net_pips": -45.2})()
    else:
        sig = None
    broker = _Broker(CloseRejected(TID, "MARKET_HALTED"))
    e = _engine(broker, _Mgr(sig))

    # 180 ticks at the live 5s manage cadence = 15 minutes
    for i in range(180):
        e._manage(NOW + timedelta(seconds=5 * i))

    assert broker.close_calls == 1, "backoff must suppress re-submission"
    assert PAIR in e.managers, "B-119: a rejected close keeps the manager"
    assert e._close_backoff[TID] == pytest.approx((NOW + timedelta(seconds=1800)).timestamp())

    # still inside the window at +29 min
    e._manage(NOW + timedelta(minutes=29))
    assert broker.close_calls == 1
    # window expires -> exactly one more attempt
    e._manage(NOW + timedelta(minutes=31))
    assert broker.close_calls == 2
    assert PAIR in e.managers


def test_backoff_is_keyed_by_trade_not_pair():
    """A fresh trade on the same pair must not inherit a dead trade's timer."""
    broker = _Broker(CloseRejected(TID, "MARKET_HALTED"))
    e = _engine(broker, _Mgr())
    e._manage(NOW)
    assert broker.close_calls == 1

    broker.exc = None
    mgr2 = _Mgr()
    mgr2.position.oanda_trade_id = "11999"      # new trade, same pair
    broker.open_ids.add("11999")                # broker sees it too
    e.managers[PAIR] = mgr2
    e._manage(NOW + timedelta(seconds=5))
    assert broker.close_calls == 2, "new trade id must not be gated"
    assert PAIR not in e.managers, "confirmed close books the exit"


def test_generic_failure_uses_the_short_backoff():
    broker = _Broker(RuntimeError("connection reset"))
    e = _engine(broker, _Mgr())
    e._manage(NOW)
    assert e._close_backoff[TID] == pytest.approx((NOW + timedelta(seconds=300)).timestamp())
    e._manage(NOW + timedelta(seconds=5))
    assert broker.close_calls == 1
    e._manage(NOW + timedelta(seconds=301))
    assert broker.close_calls == 2


# ── the discipline the backoff must not break ────────────────────────────────

def test_successful_close_books_the_exit_and_clears_the_timer():
    broker = _Broker(None)
    e = _engine(broker, _Mgr())
    e._manage(NOW)
    assert broker.close_calls == 1
    assert PAIR not in e.managers
    assert TID not in e._close_backoff
    assert any("REAP" in ev for ev in e.recent_events)


def test_already_gone_trade_books_the_exit():
    broker = _Broker(RuntimeError("404 trade does not exist"))
    e = _engine(broker, _Mgr())
    e._manage(NOW)
    assert PAIR not in e.managers, "a genuinely-gone trade is booked, not backed off"
    assert TID not in e._close_backoff


def test_backoff_does_not_announce_the_exit_every_tick():
    """recent_events is a 40-slot deque the dashboard reads — a refused close
    re-announcing itself every tick wiped the feed. Only real attempts announce."""
    broker = _Broker(CloseRejected(TID, "MARKET_HALTED"))
    e = _engine(broker, _Mgr())
    for i in range(180):
        e._manage(NOW + timedelta(seconds=5 * i))
    assert len(e.recent_events) == 0, "a rejected reap books no REAP event"
