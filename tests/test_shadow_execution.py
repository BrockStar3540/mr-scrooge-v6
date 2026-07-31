"""tests/test_shadow_execution.py — D-7 stages A+B: versioned stamps and
setup-specific shadow exit simulation on executable prices."""
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from core.trial_events import (METRIC_V2, TrialStamp, make_stamp,
                               mechanics_hash, parse_stamp)
from core.shadow_execution import (ShadowOutcome, executable_candle,
                                   simulate_shadow_exit)

PIP = 0.0001


def _setup(**over):
    base = {"id": "s1", "side": "long", "class": "control", "status": "SHADOW",
            "horizon_min": 240,
            "conditions": [{"feature": "rsi14", "max": 30.0}],
            "exit": {"mode": "ratchet", "sl_pips": 50.0, "trigger_pips": 8.5,
                     "trail_pips": 2.5},
            "sizing": {"risk_pct": 0.2},
            "evidence": {"ev_seq": None, "source": "x"},
            "notes": "prose"}
    base.update(over)
    return base


def _view(bid=1.1000, ask=1.1002):
    return SimpleNamespace(bid=bid, ask=ask, spread_pips=(ask - bid) / PIP)


# ── stamps ───────────────────────────────────────────────────────────────────

def test_stamp_entry_is_executable_side():
    now = datetime.now(timezone.utc)
    long_stamp = make_stamp(now=now, pair="EUR_USD", session="london",
                            setup=_setup(side="long"), status="SHADOW", view=_view())
    short_stamp = make_stamp(now=now, pair="EUR_USD", session="london",
                             setup=_setup(side="short"), status="SHADOW", view=_view())
    assert long_stamp.entry == 1.1002      # long enters at ask
    assert short_stamp.entry == 1.1000     # short enters at bid


def test_stamp_roundtrip_through_journal_line():
    now = datetime.now(timezone.utc)
    st = make_stamp(now=now, pair="EUR_USD", session="ny",
                    setup=_setup(), status="ACTIVE", view=_view())
    line = "2026-07-28 INFO v5.cells  TRIALSTAMP " + st.to_json()
    parsed = parse_stamp(line)
    assert parsed is not None
    assert parsed["entry"] == st.entry
    assert parsed["exit_config"]["sl_pips"] == 50.0
    assert parsed["mechanics_hash"] == mechanics_hash(_setup())


def test_mechanics_hash_ignores_prose_but_not_mechanics():
    a = mechanics_hash(_setup())
    assert a == mechanics_hash(_setup(notes="different prose", status="ACTIVE"))
    assert a != mechanics_hash(_setup(exit={"mode": "ratchet", "sl_pips": 60.0,
                                            "trigger_pips": 8.5, "trail_pips": 2.5}))
    assert a != mechanics_hash(_setup(side="short"))


def test_stamp_degrades_to_none_without_prices():
    now = datetime.now(timezone.utc)
    assert make_stamp(now=now, pair="X", session="s", setup=_setup(),
                      status="SHADOW", view=SimpleNamespace()) is None


# ── candle helpers ───────────────────────────────────────────────────────────

def _ba(o, h, l, c, spread=2 * PIP):
    return {"bid": {"o": o, "h": h, "l": l, "c": c},
            "ask": {"o": o + spread, "h": h + spread, "l": l + spread,
                    "c": c + spread}}


def test_executable_candle_sides():
    c = _ba(1.1000, 1.1010, 1.0990, 1.1005)
    assert executable_candle(c, "long")["h"] == 1.1010          # bid path
    assert executable_candle(c, "short")["l"] == 1.0992         # ask path


# ── ratchet simulation ───────────────────────────────────────────────────────

def _stamp(side="long", entry=1.1002, horizon=240, exit_cfg=None):
    return {"side": side, "entry": entry, "horizon_min": horizon,
            "exit_config": exit_cfg or {"mode": "ratchet", "sl_pips": 50.0,
                                        "trigger_pips": 8.5, "trail_pips": 2.5}}


def test_runner_exits_at_horizon_close():
    # steady riser: +2p per bar on the bid, never returns to entry
    bars = [_ba(1.1000 + i * 2 * PIP, 1.1002 + i * 2 * PIP,
                1.0999 + i * 2 * PIP, 1.1002 + i * 2 * PIP) for i in range(48)]
    out = simulate_shadow_exit(_stamp(), bars, PIP)
    assert out.exit_reason == "horizon"
    assert out.net_pips > 50
    assert not out.ambiguous_bar


def test_trail_out_exits_at_lock():
    # rise to +12p by bar 4 (cadence at 20min = 4 bars → lock = 8.5+trailmath),
    # then collapse: exit must be AT the lock, not the close
    up = [_ba(1.1000 + i * 3 * PIP, 1.1004 + i * 3 * PIP,
              1.0999 + i * 3 * PIP, 1.1004 + i * 3 * PIP) for i in range(4)]
    down = [_ba(1.1010, 1.1010, 1.0950, 1.0951)]
    out = simulate_shadow_exit(_stamp(), up + down, PIP)
    # LIVE gear (2026-07-31): step 2p, cadence 0.5min = every bar.
    # peak ≈ 11 → lock = floor((11-8.5)/2)*2 + 8.5 - 2.5 = 8.0
    # (the old expected 6.0 was the 5p/20min SIM-ONLY gear — charter defect #2)
    assert out.exit_reason == "stop"
    assert out.net_pips == pytest.approx(8.0)


def test_immediate_dump_hits_initial_stop():
    bars = [_ba(1.1000, 1.1001, 1.0930, 1.0935), _ba(1.0935, 1.0940, 1.0930, 1.0935)]
    out = simulate_shadow_exit(_stamp(), bars, PIP)
    assert out.exit_reason == "initial_stop"
    assert out.net_pips == pytest.approx(-50.0)


def test_same_bar_spike_and_dump_is_worst_case_ambiguous():
    # bar 0 both spikes +30p and dumps −60p: stop first, flagged ambiguous
    bars = [_ba(1.1000, 1.1032, 1.0940, 1.0950), _ba(1.0950, 1.0955, 1.0945, 1.0950)]
    out = simulate_shadow_exit(_stamp(), bars, PIP)
    assert out.exit_reason == "initial_stop"
    assert out.net_pips == pytest.approx(-50.0)
    assert out.ambiguous_bar


def test_short_side_symmetric():
    # short from 1.1000 (bid), price falls 2p/bar on ask path → runner
    bars = [_ba(1.1000 - i * 2 * PIP, 1.1002 - i * 2 * PIP,
                1.0998 - i * 2 * PIP, 1.0999 - i * 2 * PIP) for i in range(48)]
    out = simulate_shadow_exit(_stamp(side="short", entry=1.1000), bars, PIP)
    assert out.exit_reason == "horizon"
    assert out.net_pips > 40


def test_horizon_respects_setup_minutes():
    bars = [_ba(1.1000, 1.1003, 1.0999, 1.1001)] * 48
    out = simulate_shadow_exit(_stamp(horizon=60), bars, PIP)
    assert out.exit_bar == 11        # 60min / 5m = 12 bars → last index 11


# ── bracket simulation ───────────────────────────────────────────────────────

def test_bracket_tp_and_sl_and_timeout():
    cfg = {"mode": "bracket", "sl_pips": 12.0, "tp_pips": 10.0, "timeout_min": 30}
    tp_bars = [_ba(1.1000, 1.1015, 1.0999, 1.1012)] + [_ba(1.1, 1.1, 1.1, 1.1)]
    out = simulate_shadow_exit(_stamp(exit_cfg=cfg), tp_bars, PIP)
    assert out.exit_reason == "tp" and out.net_pips == pytest.approx(10.0)

    sl_bars = [_ba(1.1000, 1.1001, 1.0985, 1.0990)] + [_ba(1.1, 1.1, 1.1, 1.1)]
    out2 = simulate_shadow_exit(_stamp(exit_cfg=cfg), sl_bars, PIP)
    assert out2.exit_reason == "initial_stop" and out2.net_pips == pytest.approx(-12.0)

    flat = [_ba(1.1000, 1.1002, 1.0999, 1.1001)] * 10
    out3 = simulate_shadow_exit(_stamp(exit_cfg=cfg), flat, PIP)
    assert out3.exit_reason == "timeout" and out3.exit_bar == 5


def test_metric_version_marked():
    bars = [_ba(1.1000, 1.1002, 1.0999, 1.1001)] * 4
    out = simulate_shadow_exit(_stamp(), bars, PIP)
    assert out.metric_version == METRIC_V2


# ── charter defect #2 fixes (2026-07-31): live knobs + censoring ─────────────

def test_stamped_cadence_and_step_are_honored():
    # a stamp carrying the OLD coarse gear must still sim under that gear
    st = _stamp()
    st["exit_config"]["step_size_pips"] = 5.0
    st["exit_config"]["step_cadence_min"] = 20.0
    up = [_ba(1.1000 + i * 3 * PIP, 1.1004 + i * 3 * PIP,
              1.0999 + i * 3 * PIP, 1.1004 + i * 3 * PIP) for i in range(4)]
    down = [_ba(1.1010, 1.1010, 1.0950, 1.0951)]
    out = simulate_shadow_exit(st, up + down, PIP)
    assert out.net_pips == pytest.approx(6.0)      # the old-gear lock


def test_default_gear_matches_live_exit_config():
    import json
    from pathlib import Path
    from core import shadow_execution as se
    d = json.loads((Path(se.__file__).resolve().parents[1] / "config" /
                    "exit_config.json").read_text())["defaults"]
    assert se.DEFAULT_STEP_SIZE_PIPS == d["step_size_pips"]
    assert se.DEFAULT_CADENCE_MIN == d["step_cadence_min"]


def test_stamp_carries_live_step_knobs():
    from core.trial_events import _stamped_exit
    ex = _stamped_exit({"exit": {"mode": "ratchet", "sl_pips": 40.0,
                                 "trigger_pips": 8.5}}, "GBP_USD")
    assert ex["step_size_pips"] == 2.0
    assert ex["step_cadence_min"] == 0.5
    assert ex["sl_pips"] == 40.0                   # setup fields untouched
