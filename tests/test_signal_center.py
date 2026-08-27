"""tests/test_signal_center.py — Signal Command Center data layer.

Covers: TRIALSTAMP journal parsing into the firing registry, on-air run
splitting, the live-window cutoff (trigger window closes ⇒ signal drops off),
evidence blending + shrinkage, per-pair aggregation (direction, confidence,
distance, hold estimate), the MAE-flip contra rule, hold-time extraction from
the episode store, and JSON-serializability of the API payload.
"""
import json
import math
from datetime import datetime, timedelta, timezone

import pytest

from ops import signal_center as sc

NOW = datetime(2026, 8, 27, 15, 45, 0, tzinfo=timezone.utc)


def _line(ts, pair="GBP_USD", session="ny", setup="alpha_long", side="long",
          status="SHADOW", spread=1.5):
    payload = {
        "version": 2, "timestamp": ts.isoformat(), "pair": pair,
        "session": session, "setup_id": setup, "side": side, "status": status,
        "bid": 1.35, "ask": 1.3502, "entry": 1.3502, "spread_pips": spread,
        "horizon_min": 240,
        "exit_config": {"trigger_pips": 9.0, "sl_pips": 40.0},
        "mechanics_hash": "abc123",
    }
    return ("2026-08-27T15:43:50+00:00 host python3[1]: 2026-08-27 15:43:50,168 "
            "INFO v5.cells  TRIALSTAMP " + json.dumps(payload, default=str))


# ── Registry / runs / live window ────────────────────────────────────────────

def test_registry_builds_runs_and_splits_on_gap():
    lines = [
        _line(NOW - timedelta(seconds=3600)),   # old run
        _line(NOW - timedelta(seconds=3300)),
        # gap > RUN_GAP_S (900) ⇒ new run
        _line(NOW - timedelta(seconds=600)),
        _line(NOW - timedelta(seconds=300)),
        _line(NOW),
    ]
    reg = sc.build_registry(lines)
    assert len(reg) == 1
    rec = reg[("GBP_USD", "ny", "alpha_long", "long")]
    assert rec["n_run"] == 3                      # current run only
    assert rec["run_start"] == NOW - timedelta(seconds=600)
    assert rec["last"] == NOW
    assert rec["trigger_pips"] == 9.0 and rec["sl_pips"] == 40.0


def test_small_gap_does_not_split_run():
    lines = [_line(NOW - timedelta(seconds=890)), _line(NOW)]
    reg = sc.build_registry(lines)
    rec = reg[("GBP_USD", "ny", "alpha_long", "long")]
    assert rec["n_run"] == 2


def test_live_window_drops_closed_triggers():
    lines = [
        _line(NOW - timedelta(seconds=sc.LIVE_S + 60), setup="stale_one"),
        _line(NOW - timedelta(seconds=120), setup="fresh_one"),
    ]
    live = sc.live_signals(sc.build_registry(lines), NOW)
    assert list(k[2] for k in live) == ["fresh_one"]


def test_malformed_lines_ignored():
    lines = ["garbage", "TRIALSTAMP {not json", _line(NOW)]
    assert len(sc.build_registry(lines)) == 1


def test_latest_stamp_status_wins():
    lines = [_line(NOW - timedelta(seconds=300), status="SHADOW"),
             _line(NOW, status="PROBE")]
    reg = sc.build_registry(lines)
    assert reg[("GBP_USD", "ny", "alpha_long", "long")]["status"] == "PROBE"


# ── Evidence blending ────────────────────────────────────────────────────────

def test_evidence_blends_era_and_form_with_shrinkage():
    ev = sc.evidence_pips({"era_avg": 10.0, "era_n": 8,
                           "form7": 20.0, "n7": 8})
    # shrink = n/(n+8) = 0.5 ⇒ 0.6*5 + 0.4*10 = 7.0
    assert ev == pytest.approx(7.0)


def test_evidence_missing_parts_renormalize_and_empty_is_zero():
    assert sc.evidence_pips({"era_avg": 10.0, "era_n": 8}) == pytest.approx(5.0)
    assert sc.evidence_pips({"form7": 10.0, "n7": 8}) == pytest.approx(5.0)
    assert sc.evidence_pips({}) == 0.0
    assert sc.evidence_pips({"era_avg": 10.0, "era_n": 0}) == 0.0


# ── Aggregation ──────────────────────────────────────────────────────────────

def _live(pair, sess, setup, side, status, ago_s=60, run_s=1800):
    return {(pair, sess, setup, side): {
        "last": NOW - timedelta(seconds=ago_s),
        "run_start": NOW - timedelta(seconds=run_s), "n_run": run_s // 300,
        "status": status, "spread": 1.5, "horizon_min": 240,
        "trigger_pips": 9.0, "sl_pips": 40.0, "mech": "abc"}}


def test_aggregate_direction_confidence_and_distance():
    live = {}
    live.update(_live("GBP_USD", "ny", "a1", "long", "ACTIVE"))
    live.update(_live("GBP_USD", "ny", "a2", "long", "PROBE"))
    forms = {"GBP_USD|ny|a1": {"era_avg": 10.0, "era_n": 8},   # ev 5.0 ⇒ c +5.0
             "GBP_USD|ny|a2": {"era_avg": 10.0, "era_n": 8}}   # ev 5.0 ⇒ c +3.0
    holds = {"GBP_USD|ny|a1": {"hold_med_min": 60.0, "hold_n": 20},
             "GBP_USD|ny|a2": {"hold_med_min": 220.0, "hold_n": 10}}
    pairs = sc.aggregate(live, forms, holds, {}, NOW)
    assert len(pairs) == 1
    p = pairs[0]
    assert p["pair"] == "GBP_USD" and p["direction"] == "LONG"
    assert p["net"] == pytest.approx(8.0) and p["gross"] == pytest.approx(8.0)
    assert p["agreement"] == 1.0
    expect_conf = round(100 * math.tanh(8.0 / sc.CONF_SCALE))
    assert p["confidence"] == expect_conf
    assert p["distance_pips"] == pytest.approx(5.0, abs=0.1)
    # hold = (5*60 + 3*220)/8 = 120m ⇒ "~2.0h"
    assert p["hold_min"] == pytest.approx(120.0, abs=0.5)
    assert p["hold_label"] == "~2.0h"
    assert p["counts"] == {"ACTIVE": 1, "PROBE": 1}


def test_negative_evidence_is_contra_maeflip():
    live = {}
    live.update(_live("EUR_USD", "ny", "good_long", "long", "ACTIVE"))
    live.update(_live("EUR_USD", "ny", "bad_long", "long", "ACTIVE"))
    forms = {"EUR_USD|ny|good_long": {"era_avg": 4.0, "era_n": 8},   # +2.0
             "EUR_USD|ny|bad_long": {"era_avg": -12.0, "era_n": 8}}  # −6.0
    p = sc.aggregate(live, forms, {}, {}, NOW)[0]
    # bad long setup firing pushes SHORT harder than good pushes LONG
    assert p["direction"] == "SHORT"
    assert p["net"] == pytest.approx(-4.0)
    assert p["agreement"] == pytest.approx(0.5)
    contribs = {s["setup_id"]: s["contribution"] for s in p["signals"]}
    assert contribs["bad_long"] < 0 < contribs["good_long"]


def test_short_side_signs_flip():
    live = _live("USD_JPY", "asia", "s1", "short", "ACTIVE")
    forms = {"USD_JPY|asia|s1": {"era_avg": 8.0, "era_n": 8}}
    p = sc.aggregate(live, forms, {}, {}, NOW)[0]
    assert p["direction"] == "SHORT" and p["net"] < 0


def test_zero_evidence_book_shows_but_flat_zero_confidence():
    live = _live("AUD_USD", "london", "fresh", "long", "SHADOW")
    p = sc.aggregate(live, {}, {}, {}, NOW)[0]
    assert p["confidence"] == 0 and p["direction"] == "FLAT"
    assert len(p["signals"]) == 1
    assert p["hold_min"] is None


def test_hold_falls_back_to_horizon():
    live = _live("NZD_USD", "ny", "h1", "long", "ACTIVE")
    forms = {"NZD_USD|ny|h1": {"era_avg": 8.0, "era_n": 8}}
    p = sc.aggregate(live, forms, {}, {}, NOW)[0]
    assert p["hold_min"] == pytest.approx(240.0)      # horizon_min fallback
    assert p["hold_label"] == "~4.0h"


def test_strikes_joined():
    live = _live("EUR_JPY", "ny", "tl30", "short", "PROBE")
    p = sc.aggregate(live, {}, {}, {"EUR_JPY|ny|tl30": 2}, NOW)[0]
    assert p["signals"][0]["strikes"] == 2


def test_fmt_hold():
    assert sc._fmt_hold(35) == "~35m"
    assert sc._fmt_hold(89.4) == "~89m"
    assert sc._fmt_hold(120) == "~2.0h"
    assert sc._fmt_hold(None) is None


# ── Hold stats from the episode store ────────────────────────────────────────

def test_hold_stats_median_excludes_censored_and_horizon(tmp_path):
    eps = {}
    for i, (bar, censored, reason) in enumerate([
            (6, False, "trail"), (12, False, "sl"), (24, False, "trail"),
            (48, True, "horizon"),          # censored ⇒ excluded
            (11, False, "horizon")]):       # horizon exit ⇒ excluded
        eps["k%d" % i] = {"cell": "GBP_USD/ny", "setup": "a1", "side": "long",
                          "mv": 2, "t": "2026-08-27T10:00:00+00:00",
                          "scores": {"exit_bar": bar, "censored": censored,
                                     "exit_reason": reason}}
    eps["legacy"] = {"cell": "GBP_USD/ny", "setup": "a1", "mv": 1,
                     "scores": {"exit_bar": 99, "censored": False,
                                "exit_reason": "trail"}}
    store = tmp_path / "shadowboard.json"
    store.write_text(json.dumps({"episodes": eps}))
    sc._HOLD_CACHE.update({"mtime": None, "holds": {}})
    holds = sc.hold_stats(store)
    assert holds == {"GBP_USD|ny|a1": {"hold_med_min": 60.0, "hold_n": 3}}


def test_hold_stats_missing_store_empty(tmp_path):
    sc._HOLD_CACHE.update({"mtime": None, "holds": {}})
    assert sc.hold_stats(tmp_path / "absent.json") == {}


# ── Full build + serializability ─────────────────────────────────────────────

def test_build_center_serializable(monkeypatch, tmp_path):
    lines = [_line(NOW - timedelta(seconds=120), status="ACTIVE"),
             _line(NOW - timedelta(seconds=100), pair="USD_JPY",
                   session="asia", setup="s2", side="short")]
    monkeypatch.setattr(sc, "_strikes", lambda: {})
    monkeypatch.setattr(sc, "hold_stats", lambda store=None: {})
    monkeypatch.setattr("core.execution_score.load_chamber_form",
                        lambda: {"GBP_USD|ny|alpha_long":
                                 {"era_avg": 6.0, "era_n": 10,
                                  "form7": 4.0, "n7": 5}})
    data = sc.build_center(now=NOW, lines=lines)
    s = json.dumps(data)                      # must be serializable as-is
    assert data["totals"]["live_signals"] == 2
    assert data["totals"]["pairs_live"] == 2
    assert data["totals"]["tracked_48h"] == 2
    top = data["pairs"][0]
    assert top["pair"] == "GBP_USD"           # evidence-backed sorts first
    assert top["confidence"] > 0
    assert "signals" in top and top["signals"][0]["setup_id"] == "alpha_long"
    assert "hold_label" in top


def test_get_center_first_call_returns_building_placeholder(monkeypatch):
    monkeypatch.setattr(sc, "_CACHE", {"ts": 0.0, "data": None})
    monkeypatch.setattr(sc, "_LATCH", {"t": 0.0})
    calls = []
    monkeypatch.setattr(sc.threading, "Thread",
                        lambda **kw: type("T", (), {"start":
                                                    lambda self: calls.append(1)})())
    out = sc.get_center()
    assert out.get("building") is True and calls == [1]


# ── Broker-truth evidence + strike discount (v6.36.0) ────────────────────────

def test_evidence_broker_term_leads():
    form = {"era_avg": 2.0, "era_n": 8}              # shrunk sim part = 1.0
    broker = {"trust": 0.25, "n_cycles": 4}          # 0.25·60·(4/8) = 7.5
    # (0.5·7.5 + 0.3·1.0) / 0.8 = 5.0625 — banked cycles dominate the sim
    assert sc.evidence_pips(form, broker) == pytest.approx(5.0625)
    assert sc.evidence_pips({}, broker) == pytest.approx(7.5)


def test_evidence_broker_needs_cycles_and_trust():
    assert sc.evidence_pips({}, {"trust": None, "n_cycles": 3}) == 0.0
    assert sc.evidence_pips({}, {"trust": 0.5, "n_cycles": 0}) == 0.0
    assert sc.evidence_pips({}, None) == 0.0


def test_evidence_negative_broker_counts_against():
    broker = {"trust": -0.2, "n_cycles": 4}          # −0.2·60·0.5 = −6.0
    assert sc.evidence_pips({}, broker) == pytest.approx(-6.0)


def test_strike_discount_applies_per_strike():
    live = _live("EUR_JPY", "ny", "tl30", "short", "PROBE")
    forms = {"EUR_JPY|ny|tl30": {"era_avg": 10.0, "era_n": 8}}   # ev 5.0
    c0 = sc.aggregate(live, forms, {}, {}, NOW)[0]["signals"][0]["contribution"]
    c2 = sc.aggregate(live, forms, {},
                      {"EUR_JPY|ny|tl30": 2}, NOW)[0]["signals"][0]["contribution"]
    assert c0 == pytest.approx(-3.0)                 # 0.6 · 5.0, short side
    assert c2 == pytest.approx(c0 * sc.STRIKE_DISCOUNT ** 2)


def test_broker_cycles_in_signal_payload_and_weighting():
    live = _live("USD_JPY", "ny", "atr5", "long", "ACTIVE")
    heats = {"USD_JPY|ny|atr5": {"trust": 0.3, "n_cycles": 5, "heat": 0.2}}
    p = sc.aggregate(live, {}, {}, {}, NOW, heats=heats)[0]
    s = p["signals"][0]
    assert s["n_cycles"] == 5 and s["trust"] == 0.3
    # broker-only evidence: 0.3·60·(5/9) = 10.0; ACTIVE weight 1.0
    assert s["evidence_pips"] == pytest.approx(10.0, abs=0.01)
    assert p["net"] == pytest.approx(10.0, abs=0.01)


def test_broker_backed_seat_outranks_perfect_thin_shadow():
    """The Brock case: a real-money winner must out-say a 100%-WR shadow on a
    thin sample, and a struck shadow must say less than a clean one."""
    live = {}
    live.update(_live("USD_JPY", "ny", "atr5", "long", "ACTIVE"))
    live.update(_live("USD_JPY", "ny", "lucky", "short", "SHADOW"))
    forms = {"USD_JPY|ny|lucky": {"era_avg": 12.0, "era_n": 3}}   # 100% WR, n=3
    heats = {"USD_JPY|ny|atr5": {"trust": 0.3, "n_cycles": 5}}
    p = sc.aggregate(live, forms, {}, {}, NOW, heats=heats)[0]
    by = {s["setup_id"]: s["contribution"] for s in p["signals"]}
    assert by["atr5"] > abs(by["lucky"])             # +10.0 vs −0.82
    assert p["direction"] == "LONG"
    # same thin shadow with a strike says even less
    p2 = sc.aggregate(live, forms, {}, {"USD_JPY|ny|lucky": 1}, NOW,
                      heats=heats)[0]
    by2 = {s["setup_id"]: s["contribution"] for s in p2["signals"]}
    assert abs(by2["lucky"]) == pytest.approx(abs(by["lucky"]) * 0.6, abs=0.01)
