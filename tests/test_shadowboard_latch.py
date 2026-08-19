"""B-133: a hung refresh latch must be taken over after its lease expires."""
import time

from ops import shadowboard as sb


class _FakeThread:
    def __init__(self, *a, **k):
        pass

    def start(self):
        _FakeThread.started += 1


def _prime_cache(monkeypatch, data):
    monkeypatch.setitem(sb._CACHE, "data", data)
    monkeypatch.setitem(sb._CACHE, "ts", 0.0)   # long stale


def test_hung_latch_recovers(monkeypatch):
    _FakeThread.started = 0
    monkeypatch.setattr(sb.threading, "Thread", _FakeThread)
    _prime_cache(monkeypatch, {"rows": [], "meta": {}, "tiers": {},
                               "active_median": None, "pending": 0,
                               "generated": "x"})
    monkeypatch.setitem(sb._REFRESHING, "on", True)
    monkeypatch.setitem(sb._REFRESHING, "since",
                        time.time() - (sb._LATCH_TIMEOUT_S + 5))
    sb.get_board()
    assert _FakeThread.started == 1, "expired lease must start a new worker"


def test_live_latch_respected(monkeypatch):
    _FakeThread.started = 0
    monkeypatch.setattr(sb.threading, "Thread", _FakeThread)
    _prime_cache(monkeypatch, {"rows": [], "meta": {}, "tiers": {},
                               "active_median": None, "pending": 0,
                               "generated": "x"})
    monkeypatch.setitem(sb._REFRESHING, "on", True)
    monkeypatch.setitem(sb._REFRESHING, "since", time.time())  # fresh lease
    sb.get_board()
    assert _FakeThread.started == 0, "a live worker must not be duplicated"
