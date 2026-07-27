#!/usr/bin/env python3
"""One-shot builder: SHADOW-only cell configs for the 4 March-replay CAD crosses.

Setups are copies of the book's validated shapes (ps_floor_fade_long asia,
ps_ceil_fade_short ny) plus the discovery-engine trend-pullback (london+ny),
exactly the three entry geometries the 2026-03-23..26 winners had
(txns 209-324). Everything status=SHADOW: stamps only, promotable solely
through the activation bar. Lineage marked so nobody mistakes these for
truth-matrix-derived cells.
"""
import json
from pathlib import Path

OUT = Path("config/cells")
GEN = "march-2026-replay hand-authored 2026-07-27 (SHADOW-only; NOT generate_cell_configs.py)"

CROSSES = ["CAD_JPY", "AUD_CAD", "EUR_CAD", "GBP_CAD"]

EVIDENCE = {
    "ev_seq": None,
    "source": ("march-2026 replay (acct txns 209-324): fade/floor/pullback shapes on CAD "
               "crosses, 8 green / 1 red fills, descriptive n=9 — hypothesis, not validation"),
    "drift": "UNKNOWN",
    "n_floor_status": "no current-era sample — activation bar governs promotion",
}
TRIPWIRES = {"fast": {"last_n": 20, "min_ev": -0.5, "action": "suspend"}}
SIZING = {"risk_pct": 0.2}

def exit_block(sl):
    return {"mode": "ratchet", "sl_pips": float(sl), "trigger_pips": 8.5,
            "trail_pips": 2.5, "trail_mult": 0.0, "trail_min": 2.5,
            "trail_max": 10.0, "_class": "RANGE_SIZED"}

def setup(sid, side, cls, horizon, conds, sl, note):
    return {"id": sid, "side": side, "class": cls, "status": "SHADOW",
            "horizon_min": horizon, "conditions": conds, "exit": exit_block(sl),
            "sizing": SIZING, "tripwires": TRIPWIRES, "evidence": dict(EVIDENCE),
            "notes": note}

FLOOR = lambda sl: setup(
    "ps_floor_fade_long", "long", "session_structure", 240,
    [{"feature": "ps_pos", "max": 0.15},
     {"feature": "ps_low_dist", "min": 0.0,
      "note": "at prev session floor, unbroken -> buy the test (copied from EUR_USD/asia)"}],
    sl, "March-replay: txn 242 AUD_CAD long at psPos 0.00 won +$2.5k. Same conditions as the majors' validated floor fade.")

CEIL = lambda sl: setup(
    "ps_ceil_fade_short", "short", "session_structure", 240,
    [{"feature": "ps_pos", "min": 0.85},
     {"feature": "ps_high_dist", "max": 0.0,
      "note": "at prev session ceiling, unbroken -> fade (copied from GBP_USD/ny)"}],
    sl, "March-replay: txns 228/270 shorted range tops (psPos 1.00/0.91) and won. Same conditions as the majors' ceil fade.")

PULLBACK = lambda sl: setup(
    "trend_pullback_long", "long", "trend_pullback", 240,
    [{"feature": "trend_4h", "min": 0.5, "note": "4h trend up"},
     {"feature": "h1_ret_4bar", "min": 10.0, "note": "real H1 momentum, not drift"},
     {"feature": "willr_m5", "max": -85.0,
      "note": "M5 washed out — buy the dip, not the chase"}],
    sl, "March-replay: txn 280 AUD_USD long (t4h up, h1r4 +32, willr -94.6) won +$4.2k — the discovery engine's one robust entry shape (2026-06-14), first time wired as a setup.")

def cell(pair):
    sessions = {
        "asia":   {"enabled": True, "structure": s_note(), "setups": [FLOOR(40)],
                   "notes": "march-replay shadow cell"},
        "london": {"enabled": True, "structure": s_note(), "setups": [PULLBACK(50)],
                   "notes": "march-replay shadow cell"},
        "ny":     {"enabled": True, "structure": s_note(), "setups": [CEIL(60), PULLBACK(60)],
                   "notes": "march-replay shadow cell"},
    }
    return {"pair": pair, "generated": "2026-07-27T04:45:00Z", "generator": GEN,
            "sessions": sessions}

def s_note():
    return {"tier": None, "rh_offer_rate_60m": None, "dead_rate_60m": None,
            "ev_gross_long": None, "ev_gross_short": None,
            "lineage": "NONE — new-pair hypothesis, no truth-matrix evidence; crosses pay 2-3x major spread toll (measure before believing)"}

for p in CROSSES:
    path = OUT / f"{p}.json"
    if path.exists():
        raise SystemExit(f"refusing to overwrite existing {path}")
    path.write_text(json.dumps(cell(p), indent=2) + "\n")
    print("wrote", path)
