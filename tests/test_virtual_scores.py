"""tests/test_virtual_scores.py — VIRTUAL FAMILY-CYCLE board feed (2026-08-04).

The parent/horizon stamp sim agreed with broker sign on only 3/10 families;
the board's accurate shadow metric is the virtual family cycle. This pins the
replay-JSON -> board-document transform and the loader's freshness contract.
"""
from ops.virtual_scores import transform


def test_transform_keys_and_cycle_wr():
    d = {"since": "2026-07-28", "rows": [{
        "cell": "USD_JPY/asia", "setup": "box_pdl_short", "side": "short",
        "cycles": 6, "censored": 0, "net_pips_mean": 65.7,
        "harvest_mean": 48.7, "u_list": [0.12, 0.44, -0.2, 0.44, 0.634, 0.6],
        "U_pp": 0.446, "U_par": 0.34, "grid_lift": 0.106,
        "grid_lift_lcb": -0.01, "coverage": 6.35, "worst": 0.12,
        "days": 5, "episodes_scored": 6}]}
    doc = transform(d)
    r = doc["rows"]["USD_JPY/asia|box_pdl_short|short"]
    assert r["cycles"] == 6
    assert r["net_mean"] == 65.7
    assert r["wr"] == round(5 / 6, 3)
    assert r["harvest_mean"] == 48.7
    assert doc["since"] == "2026-07-28"


def test_transform_empty():
    assert transform({})["rows"] == {}
