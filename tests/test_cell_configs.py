"""tests/test_cell_configs.py — schema validation over every config/cells/*.json.

The cell configs ARE the strategy in the cell era; a malformed exit block or an
out-of-range knob would silently mis-size stops on the live book. These tests
assert required keys, value types, sane ranges, well-formed exit blocks, and the
trail < trigger invariant that keeps engaged ratchet stops above breakeven
(B-090). Data-driven so a new cell is covered automatically.
"""
import glob
import json
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_CELL_FILES = sorted(glob.glob(str(_ROOT / "config" / "cells" / "*.json")))

# PROBE joined the on-disk statuses 2026-08-03 when the admission lane went
# live (charter: every promotion lands as a 0.33x PROBE audition seat).
_STATUSES = {"ACTIVE", "PROBE", "SHADOW", "DISABLED"}
_SIDES = {"long", "short"}
_EXIT_MODES = {"ratchet", "bracket"}


def test_cell_files_exist():
    assert _CELL_FILES, "no config/cells/*.json found"


def _iter_setups():
    for f in _CELL_FILES:
        d = json.loads(Path(f).read_text())
        name = Path(f).name
        for sess, sd in d.get("sessions", {}).items():
            for st in sd.get("setups", []):
                yield name, sess, st


@pytest.mark.parametrize("path", _CELL_FILES, ids=lambda p: Path(p).name)
def test_top_level_shape(path):
    d = json.loads(Path(path).read_text())
    assert d.get("pair"), f"{path}: missing 'pair'"
    assert Path(path).stem == d["pair"], f"{path}: filename != pair {d['pair']}"
    assert isinstance(d.get("sessions"), dict) and d["sessions"], f"{path}: no sessions"
    for sess, sd in d["sessions"].items():
        assert "enabled" in sd, f"{path}/{sess}: session missing 'enabled'"
        assert isinstance(sd.get("setups", []), list), f"{path}/{sess}: setups not a list"


def test_every_setup_has_required_keys():
    required = ("id", "side", "class", "status", "horizon_min", "conditions", "exit", "sizing")
    for name, sess, st in _iter_setups():
        where = f"{name}/{sess}/{st.get('id','?')}"
        for k in required:
            assert k in st, f"{where}: missing setup key '{k}'"
        assert st["side"] in _SIDES, f"{where}: bad side {st['side']}"
        assert st["status"] in _STATUSES, f"{where}: bad status {st['status']}"
        assert isinstance(st["horizon_min"], (int, float)) and st["horizon_min"] > 0, where
        assert isinstance(st["conditions"], list), f"{where}: conditions not a list"


def test_conditions_well_formed():
    # A condition is bounded either absolutely (min/max) or by rolling
    # percentile (pct_lo/pct_hi from the formula-rolling-pct configs).
    _abs = ("min", "max")
    _pct = ("pct_lo", "pct_hi")
    for name, sess, st in _iter_setups():
        where = f"{name}/{sess}/{st.get('id','?')}"
        for c in st["conditions"]:
            assert c.get("feature"), f"{where}: condition missing feature"
            has_bound = any(k in c for k in _abs + _pct)
            assert has_bound, f"{where}: condition {c.get('feature')} has no min/max/pct bound"
            for bound in _abs + _pct:
                if c.get(bound) is not None:
                    assert isinstance(c[bound], (int, float)), f"{where}: {bound} not numeric"


def test_exit_blocks_well_formed_and_in_range():
    for name, sess, st in _iter_setups():
        where = f"{name}/{sess}/{st.get('id','?')}"
        ex = st["exit"]
        assert ex.get("mode") in _EXIT_MODES, f"{where}: bad exit mode {ex.get('mode')}"
        sl, trig, trail = ex.get("sl_pips"), ex.get("trigger_pips"), ex.get("trail_pips")
        for k, v in (("sl_pips", sl), ("trigger_pips", trig), ("trail_pips", trail)):
            assert isinstance(v, (int, float)), f"{where}: {k} missing/non-numeric"
            assert v > 0, f"{where}: {k}={v} must be > 0"
        # Sane bounds (deployed configs live well inside these).
        assert 1.0 <= sl <= 200.0, f"{where}: sl_pips {sl} out of range"
        assert 1.0 <= trig <= 100.0, f"{where}: trigger_pips {trig} out of range"
        assert 0.5 <= trail <= 50.0, f"{where}: trail_pips {trail} out of range"


def test_trail_less_than_trigger_breakeven_invariant():
    """B-090: a fixed trail must be tighter than the trigger so the first engaged
    ratchet lock (trigger - trail) sits above breakeven."""
    for name, sess, st in _iter_setups():
        where = f"{name}/{sess}/{st.get('id','?')}"
        ex = st["exit"]
        assert ex["trail_pips"] < ex["trigger_pips"], (
            f"{where}: trail_pips {ex['trail_pips']} >= trigger_pips {ex['trigger_pips']} "
            f"would park the engaged stop at/below breakeven")


def test_atr_trail_scaling_bounds_when_used():
    """If a setup opts into ATR-scaled trail (trail_mult > 0), the clamp bounds
    must be well-formed. All deployed cells currently ship trail_mult == 0.0
    (fixed trail), which is the B-090-safe state."""
    for name, sess, st in _iter_setups():
        where = f"{name}/{sess}/{st.get('id','?')}"
        ex = st["exit"]
        mult = ex.get("trail_mult", 0.0) or 0.0
        assert mult >= 0.0, f"{where}: trail_mult negative"
        if mult > 0:
            tmin, tmax = ex.get("trail_min"), ex.get("trail_max")
            assert isinstance(tmin, (int, float)) and isinstance(tmax, (int, float)), \
                f"{where}: ATR trail needs numeric trail_min/trail_max"
            assert 0 < tmin <= tmax, f"{where}: bad trail clamp {tmin}..{tmax}"


def test_sizing_risk_pct_sane():
    for name, sess, st in _iter_setups():
        where = f"{name}/{sess}/{st.get('id','?')}"
        rp = st["sizing"].get("risk_pct")
        assert isinstance(rp, (int, float)) and 0 < rp <= 5.0, f"{where}: risk_pct {rp} out of range"
