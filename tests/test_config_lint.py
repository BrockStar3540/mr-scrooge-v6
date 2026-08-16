"""tests/test_config_lint.py — B-128: structurally impossible condition sets.

tc_vwapbb_* required `bb_pos <= 0.08` (price ~1.7 sigma BELOW the 20-bar M5
mean) AND `ema20_dist_pct >= 0` (price ABOVE the same-window M5 EMA) — both
computed from the same 20 M5 bars, so the AND was satisfiable only in freak
V-shape edge cases. 24 cells sat structurally mute for 13 days with zero
journal trace (the B-124 lesson, one layer up: a gate nobody can pass is a
mute button nobody can hear).

This lint walks EVERY setup in config/cells and fails on the known-impossible
combination: a same-timeframe Bollinger-band excursion paired with an
opposite-side M5 EMA20 distance requirement. The higher-TF trend filter
(ema20_1h_dist) is the legitimate replacement and is not flagged.
"""
import json
from pathlib import Path

CELLS = Path(__file__).parents[1] / "config" / "cells"


def _setups():
    for f in sorted(CELLS.glob("*.json")):
        doc = json.loads(f.read_text())
        for sess, body in (doc.get("sessions") or {}).items():
            for s in (body or {}).get("setups", []):
                yield f.name, sess, s


def _cond_map(setup):
    out = {}
    for c in setup.get("conditions", []):
        out.setdefault(c.get("feature"), []).append(c)
    return out


def test_no_same_tf_band_vs_ema_contradiction():
    bad = []
    for fname, sess, s in _setups():
        cm = _cond_map(s)
        if "bb_pos" not in cm or "ema20_dist_pct" not in cm:
            continue
        for bb in cm["bb_pos"]:
            for ema in cm["ema20_dist_pct"]:
                # lower-band dip + above same-TF EMA (or the mirror) = mute cell
                low_dip = bb.get("max") is not None and float(bb["max"]) <= 0.2
                hi_exc = bb.get("min") is not None and float(bb["min"]) >= 0.8
                above = ema.get("min") is not None and float(ema["min"]) >= 0.0
                below = ema.get("max") is not None and float(ema["max"]) <= 0.0
                if (low_dip and above) or (hi_exc and below):
                    bad.append(f"{fname}/{sess}/{s.get('id')}")
    assert not bad, f"structurally impossible band-vs-EMA condition sets: {bad}"


def test_tc_vwapbb_cells_carry_the_h1_trend_filter():
    seen = 0
    for fname, sess, s in _setups():
        if not str(s.get("id", "")).startswith("tc_vwapbb"):
            continue
        seen += 1
        feats = {c.get("feature") for c in s.get("conditions", [])}
        assert "ema20_1h_dist" in feats, f"{fname}/{sess}/{s['id']} missing H1 trend filter"
        assert "ema20_dist_pct" not in feats, f"{fname}/{sess}/{s['id']} still has the M5 contradiction"
    assert seen == 24, f"expected 24 tc_vwapbb cells, found {seen}"


def test_every_orb_setup_carries_the_formation_gate():
    """v6.28.0: orb_range_pips is 0.0 while the session's first 15 min are
    still forming — a `min` gate on it is what keeps ORB setups from firing
    on a half-built range. An ORB setup without that gate is a mute-button
    bug's mirror image: it fires when it must not."""
    seen = 0
    for fname, sess, s in _setups():
        if not str(s.get("id", "")).startswith("orb_"):
            continue
        seen += 1
        gates = [c for c in s.get("conditions", [])
                 if c.get("feature") == "orb_range_pips"
                 and c.get("min") is not None and float(c["min"]) > 0]
        assert gates, f"{fname}/{sess}/{s.get('id')} lacks the orb_range_pips formation gate"
    assert seen == 60, f"expected 60 ORB cells, found {seen}"
