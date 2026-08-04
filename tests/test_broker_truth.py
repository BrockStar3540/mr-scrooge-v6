"""tests/test_broker_truth.py — BROKER TRUTH scoreboard (2026-08-04, operator:
"I need functional data"). Every number from broker fills; cache-only serving;
account reconciliation must expose any attribution gap."""
from ops import shadowboard as sb

FULL = {"since": "2026-07-19T00:00:00Z",
        "families": [{"instrument": "EUR_JPY", "session": "ny", "setup": "x",
                      "n": 3, "greens": 2, "usd": -50.0, "pips": -100.0,
                      "n_parents": 1, "n_poppers": 2, "n_open": 1,
                      "open_upl": -2.5, "open_floor_usd": -10.0,
                      "n_cycles": 2, "cycle_bps": -5.0,
                      "cycles": [
                          {"pips": 10, "usd": 5.0, "end": "2026-08-01T00:00"},
                          {"pips": -30, "usd": -55.0, "end": "2026-08-02T00:00"}]}],
        "account": {"window_realized_usd": -50.0, "attributed_usd": -50.0,
                    "pre_era_usd": 0.0, "unattributed_usd": 0.0},
        "excluded_pre_era_closes": 0}


def test_rows_cycle_stats_and_totals(monkeypatch):
    monkeypatch.setitem(sb._FAM_CACHE, "full", FULL)
    out = sb.broker_truth()
    r = out["rows"][0]
    assert r["cycle_wr"] == 0.5
    assert r["worst_cycle_usd"] == -55.0 and r["best_cycle_usd"] == 5.0
    assert r["avg_cycle_usd"] == -25.0
    assert r["last_close"] == "2026-08-02T00:00"
    assert out["totals"] == {"usd": -50.0, "pips": -100.0, "legs": 3,
                             "cycles": 2, "open": 1}
    assert out["account"]["unattributed_usd"] == 0.0


def test_empty_cache_serves_gracefully(monkeypatch):
    monkeypatch.setitem(sb._FAM_CACHE, "full", {})
    out = sb.broker_truth()
    assert out["rows"] == []
    assert out["totals"]["usd"] == 0
