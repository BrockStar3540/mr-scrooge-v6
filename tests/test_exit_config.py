"""tests/test_exit_config.py — sanity of the deployed config/exit_config.json.

This is the fallback exit geometry used for any trade without a per-setup exit
block (recovery-adopted trades). We read the actual file and assert the
currently-deployed defaults + structural invariants, rather than hardcoding a
whole expected blob.
"""
import json
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_CFG = _ROOT / "config" / "exit_config.json"


def _defaults():
    raw = json.loads(_CFG.read_text())
    assert raw.get("schema") == "v2", "exit_config schema drifted from v2"
    d = raw.get("defaults")
    assert isinstance(d, dict), "exit_config missing 'defaults'"
    return raw, d


def test_exit_config_exists():
    assert _CFG.exists(), f"missing {_CFG}"


def test_deployed_engage_and_trail_values():
    """Deployed gear (Brock 2026-08-18, v6.30.0 two-phase): early engage 7.5
    locking 6.0, then step machine 9.0/2.0/2.0 (9->7, 11->9, ...).
    Previous era: 8.5/2.5 single-phase (Brock 2026-07-19)."""
    _, d = _defaults()
    assert d["step_trigger_pips"] == pytest.approx(9.0)
    assert d["step_trail_pips"] == pytest.approx(2.0)
    assert d["step_engage_pips"] == pytest.approx(7.5)
    assert d["step_engage_lock_pips"] == pytest.approx(6.0)


def test_defaults_all_present_and_numeric():
    _, d = _defaults()
    for k in ("initial_sl_pips", "step_engage_min", "step_cadence_min",
              "step_trigger_pips", "step_trail_pips", "step_size_pips"):
        assert k in d, f"exit_config defaults missing {k}"
        assert isinstance(d[k], (int, float)), f"{k} non-numeric"


def test_defaults_ranges_sane():
    _, d = _defaults()
    assert d["initial_sl_pips"] > 0
    assert d["step_trigger_pips"] > 0
    assert d["step_trail_pips"] > 0
    assert d["step_size_pips"] > 0
    assert d["step_cadence_min"] > 0            # a 0 cadence would busy-loop stop moves
    assert d["step_engage_min"] >= 0
    # Trail tighter than trigger -> first engaged lock above breakeven (B-090).
    assert d["step_trail_pips"] < d["step_trigger_pips"]
    # Initial hard stop should sit wider than the first engaged lock.
    assert d["initial_sl_pips"] > d["step_trigger_pips"]


def test_per_pair_overrides_well_formed():
    raw, _ = _defaults()
    per_pair = raw.get("per_pair", {})
    assert isinstance(per_pair, dict)
    for pair, ov in per_pair.items():
        assert isinstance(ov, dict), f"per_pair[{pair}] not an object"
        for k, v in ov.items():
            if k.startswith("_"):
                continue
            assert isinstance(v, (int, float, bool)), f"per_pair[{pair}].{k} bad type"
