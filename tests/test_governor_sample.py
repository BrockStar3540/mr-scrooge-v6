"""tests/test_governor_sample.py — FUNCTIONAL-DATA RULE (2026-08-04, operator).

The board's stat columns must use the exact sample the governor promotes on.
The lifetime blend (legacy-v1 frictionless metric + dead config eras) put the
wrong sign on 15 of 174 rows — losers dressed as winners and vice versa.
"""
from ops.shadowboard import governor_sample


def _r(t, mv=2, mech="abc"):
    return {"t": t, "mech": mech, "scores": {"mv": mv, "net240": 1.0}}


def test_v1_metric_is_excluded():
    rows = [_r("2026-08-01", mv=1), _r("2026-08-01", mv=2)]
    assert len(governor_sample(rows, "2026-07-19", None)) == 1


def test_pre_era_episodes_are_excluded():
    rows = [_r("2026-07-01"), _r("2026-08-01")]
    out = governor_sample(rows, "2026-07-19", None)
    assert [r["t"] for r in out] == ["2026-08-01"]


def test_mechanics_mismatch_is_excluded():
    rows = [_r("2026-08-01", mech="old"), _r("2026-08-01", mech="cur")]
    out = governor_sample(rows, "2026-07-19", "cur")
    assert len(out) == 1 and out[0]["mech"] == "cur"


def test_missing_mech_or_hash_is_kept():
    # exactly mirrors core.trial_evidence.current_era_evidence: the mech test
    # only applies when BOTH sides are present
    rows = [{"t": "2026-08-01", "scores": {"mv": 2}}]
    assert len(governor_sample(rows, "2026-07-19", "cur")) == 1
    assert len(governor_sample([_r("2026-08-01", mech="old")],
                               "2026-07-19", None)) == 1


def test_no_era_clock_means_no_time_filter():
    rows = [_r("2026-01-01")]
    assert len(governor_sample(rows, "", None)) == 1
