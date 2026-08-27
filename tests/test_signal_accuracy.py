"""tests/test_signal_accuracy.py — consensus-call recording + forward grading.

Covers: snapshot row writing (FLAT skipped, formula hash carried), episode
assembly (gap split, direction flip, per-pair interleaving, run metadata),
executable checkpoint scoring both directions with partial-path tolerance,
the full run() cycle (store write, re-run idempotence, formula-hash sample
segregation, calls-file pruning, dead-episode marking), and aggregates.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ops import signal_accuracy as sa
from ops import signal_snapshots as ss
from ops.signal_center import formula_hash

T0 = datetime(2026, 8, 27, 12, 0, 0, tzinfo=timezone.utc)
PIP = 0.0001


def _row(ts, pair="EUR_USD", d="LONG", conf=50, fhash=None):
    return json.dumps({"ts": ts.isoformat(), "pair": pair, "dir": d,
                       "conf": conf, "net": 3.0, "gross": 3.0, "agree": 1.0,
                       "dist": 5.0, "hold_min": 60.0, "n_sig": 2,
                       "counts": {"SHADOW": 2},
                       "fhash": fhash or formula_hash()})


def _candles(t0, n, spread_pips=2.0, step_pips=10.0):
    """Synthetic rising M5 BA candles: bid.o climbs step_pips per bar,
    bid.c = bid.o + 5p, ask = bid + spread."""
    out = []
    for i in range(n):
        bo = 1.1000 + i * step_pips * PIP
        bc = bo + 5 * PIP
        s = spread_pips * PIP
        out.append({"time": (t0 + timedelta(minutes=5 * i)).isoformat(),
                    "complete": True,
                    "bid": {"o": "%.5f" % bo, "c": "%.5f" % bc},
                    "ask": {"o": "%.5f" % (bo + s), "c": "%.5f" % (bc + s)}})
    return out


# ── snapshots ────────────────────────────────────────────────────────────────

def test_snapshot_writes_rows_and_skips_flat(tmp_path, monkeypatch):
    calls = tmp_path / "calls.jsonl"
    monkeypatch.setattr(ss, "CALLS", calls)
    center = {"generated_at": T0.isoformat(), "formula_hash": "abc",
              "pairs": [
                  {"pair": "EUR_USD", "direction": "LONG", "confidence": 40,
                   "net": 2.0, "gross": 2.0, "agreement": 1.0,
                   "distance_pips": 4.0, "hold_min": 90.0,
                   "signals": [1, 2], "counts": {"SHADOW": 2}},
                  {"pair": "AUD_USD", "direction": "FLAT", "confidence": 0,
                   "net": 0.0, "gross": 0.0, "agreement": 0.0,
                   "distance_pips": 0.0, "hold_min": None,
                   "signals": [1], "counts": {"SHADOW": 1}}]}
    assert ss.snapshot(center) == 1
    rows = [json.loads(l) for l in calls.read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]["pair"] == "EUR_USD" and rows[0]["fhash"] == "abc"
    assert rows[0]["n_sig"] == 2


# ── episode assembly ─────────────────────────────────────────────────────────

def test_assemble_groups_runs_and_tracks_metadata(tmp_path):
    p = tmp_path / "c.jsonl"
    p.write_text("\n".join([
        _row(T0, conf=30), _row(T0 + timedelta(minutes=5), conf=55),
        _row(T0 + timedelta(minutes=10), conf=41)]) + "\n")
    eps = sa.assemble_episodes(sa.load_calls(p))
    assert len(eps) == 1
    ep = list(eps.values())[0]
    assert ep["conf"] == 30           # the CALL is the first snapshot
    assert ep["max_conf"] == 55 and ep["n_snaps"] == 3


def test_assemble_splits_on_gap_flip_and_pair(tmp_path):
    p = tmp_path / "c.jsonl"
    p.write_text("\n".join([
        _row(T0),
        _row(T0 + timedelta(minutes=5), d="SHORT"),          # flip ⇒ new ep
        _row(T0 + timedelta(minutes=40), d="SHORT"),         # 35m gap ⇒ new ep
        _row(T0 + timedelta(minutes=5), pair="USD_JPY"),     # other pair
        "not json at all",
    ]) + "\n")
    eps = sa.assemble_episodes(sa.load_calls(p))
    assert len(eps) == 4


# ── scoring ──────────────────────────────────────────────────────────────────

def test_score_long_checkpoints_pip_math():
    ep = {"pair": "EUR_USD", "dir": "LONG", "ts": T0.isoformat()}
    s = sa.score_episode(ep, _candles(T0, 51))
    # entry = ask open bar0 = 1.1002; p30 exits bid close bar5 = 1.1055
    assert s["entry"] == pytest.approx(1.1002)
    assert s["p30"] == pytest.approx(53.0)
    assert s["p60"] == pytest.approx(113.0)   # bar11 bid close
    assert s["p240"] == pytest.approx(473.0)  # bar47
    assert "p480" not in s                    # path too short — waits


def test_score_short_flips_sides():
    ep = {"pair": "EUR_USD", "dir": "SHORT", "ts": T0.isoformat()}
    s = sa.score_episode(ep, _candles(T0, 10))
    # entry = bid open bar0 = 1.1000; p30 exit ask close bar5 = 1.1057 ⇒ −57p
    assert s["p30"] == pytest.approx(-57.0)


def test_score_no_candles_or_before_call_returns_empty():
    ep = {"pair": "EUR_USD", "dir": "LONG", "ts": T0.isoformat()}
    assert sa.score_episode(ep, []) == {}
    old = _candles(T0 - timedelta(hours=10), 5)
    assert sa.score_episode(ep, old) == {}


# ── full run ─────────────────────────────────────────────────────────────────

def _paths(tmp_path):
    return tmp_path / "calls.jsonl", tmp_path / "store.json"


def test_run_scores_prunes_and_is_idempotent(tmp_path):
    calls, store = _paths(tmp_path)
    stale = T0 - timedelta(days=sa.PRUNE_DAYS + 1)
    calls.write_text("\n".join([
        _row(stale, pair="USD_CHF"),              # prunable, but scored first
        _row(T0), _row(T0 + timedelta(minutes=5))]) + "\n")
    fetches = []

    def fetch(pair, t0, n):
        fetches.append(pair)
        return _candles(t0, n)

    now = T0 + timedelta(hours=9)
    out = sa.run(now=now, fetch=fetch, calls_path=calls, store_path=store)
    assert out["episodes"] == 2 and out["scored_now"] == 2
    d = json.loads(store.read_text())
    ep = next(e for e in d["episodes"].values() if e["pair"] == "EUR_USD")
    assert ep["scores"]["p480"] == pytest.approx(953.0)
    # calls pruned: stale row gone, fresh rows kept
    kept = calls.read_text()
    assert "USD_CHF" not in kept and "EUR_USD" in kept
    # aggregates over current formula
    ag = d["aggregates"]
    assert ag["n_calls"] == 2
    assert ag["checkpoints"]["p60"]["n"] == 2
    assert ag["pairs"]["EUR_USD"]["dirs"]["LONG"]["p60"]["hit"] == 1.0
    # second run: nothing pending, no new fetches
    n_f = len(fetches)
    out2 = sa.run(now=now, fetch=fetch, calls_path=calls, store_path=store)
    assert out2["scored_now"] == 0 and len(fetches) == n_f


def test_run_segregates_formula_hashes(tmp_path):
    calls, store = _paths(tmp_path)
    calls.write_text("\n".join([
        _row(T0, fhash="oldformula"),
        _row(T0, pair="USD_JPY")]) + "\n")
    out = sa.run(now=T0 + timedelta(hours=9),
                 fetch=lambda p, t, n: _candles(t, n),
                 calls_path=calls, store_path=store)
    d = json.loads(store.read_text())
    assert out["episodes"] == 2
    assert d["aggregates"]["n_calls"] == 1          # old formula excluded
    assert list(d["aggregates"]["pairs"]) == ["USD_JPY"]


def test_run_waits_when_immature_and_marks_dead(tmp_path):
    calls, store = _paths(tmp_path)
    calls.write_text(_row(T0) + "\n")
    # 10 min after call: earliest checkpoint (30m) can't exist — no fetch
    out = sa.run(now=T0 + timedelta(minutes=10),
                 fetch=lambda *a: (_ for _ in ()).throw(AssertionError),
                 calls_path=calls, store_path=store)
    assert out["scored_now"] == 0
    # 4 days later with NO candle data at all ⇒ dead
    out = sa.run(now=T0 + timedelta(days=4), fetch=lambda p, t, n: [],
                 calls_path=calls, store_path=store)
    assert out["dead_now"] == 1
    d = json.loads(store.read_text())
    assert list(d["episodes"].values())[0]["dead"] == "no_data"


def test_aggregates_bands():
    eps = {}
    for i, (conf, p60) in enumerate([(10, 5.0), (30, -2.0), (60, 4.0),
                                     (80, 1.0), (90, -1.0)]):
        eps["e%d" % i] = {"pair": "EUR_USD", "dir": "LONG", "conf": conf,
                          "fhash": "f", "scores": {"p60": p60}}
    ag = sa.aggregates(eps, "f")
    assert ag["bands"]["0-25"]["p60"]["n"] == 1
    assert ag["bands"]["75-100"]["n_calls"] == 2
    assert ag["bands"]["75-100"]["p60"]["hit"] == 0.5
    assert ag["checkpoints"]["p60"]["avg"] == pytest.approx(1.4)
    assert sa.aggregates(eps, "other")["n_calls"] == 0
