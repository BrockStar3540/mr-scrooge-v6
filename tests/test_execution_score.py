"""ExecutionScore selector (charter, 2026-07-31)."""
from core.execution_score import execution_score, relative_heat

S = {"GBP_USD|ny|hot_one":  {"heat": 0.50, "trust": 0.40, "side": "short",
                             "trusted": False, "decaying": False},
     "GBP_USD|ny|cold_one": {"heat": -0.10, "trust": 0.05, "side": "short",
                             "trusted": False, "decaying": False},
     "GBP_USD|asia|steady": {"heat": 0.10, "trust": 0.30, "side": "long",
                             "trusted": True, "decaying": False},
     "USD_JPY|ny|decayer":  {"heat": -0.40, "trust": 0.25, "side": "long",
                             "trusted": True, "decaying": True}}


def test_relative_heat_vs_pair_side_peers():
    # self excluded: hot_one vs peer median (-0.10) -> +0.60
    assert relative_heat("GBP_USD|ny|hot_one", "short", S) == 0.60
    assert relative_heat("GBP_USD|ny|cold_one", "short", S) == -0.60
    # no heat -> neutral, never a penalty for being unmeasured
    assert relative_heat("EUR_USD|ny|unknown", "long", S) == 0.0
    # a lone cell's relative heat IS its absolute heat
    assert relative_heat("USD_JPY|ny|decayer", "long", S) == -0.40


def test_trust_floor_only_when_not_decaying():
    steady = execution_score("GBP_USD|asia|steady", "long", "GBP_USD", S)
    decayer = execution_score("USD_JPY|ny|decayer", "long", "USD_JPY", S)
    assert steady > 0                     # trusted floor counts
    assert decayer < 0                    # decaying: no floor, negative heat


def test_correlation_is_directional():
    base = execution_score("GBP_USD|ny|hot_one", "short", "GBP_USD", S)
    # candidate short GBP_USD adds (GBP,short)+(USD,long): 3 open USD-longs
    # and 1 GBP-short COMPOUND -> penalized
    comp = execution_score("GBP_USD|ny|hot_one", "short", "GBP_USD", S,
                           open_legs={("USD", "long"): 3, ("GBP", "short"): 1})
    import pytest
    assert base - comp == pytest.approx(0.40)   # 4 same-direction legs x 0.10
    # the same open book OFFSET by the candidate: no penalty at all
    offset = execution_score("GBP_USD|ny|hot_one", "short", "GBP_USD", S,
                             open_legs={("USD", "short"): 3, ("GBP", "long"): 1})
    assert offset == base                 # offsetting exposure is free


def test_missing_heat_file_degrades_to_zero():
    assert execution_score("X|y|z", "long", "EUR_USD", {}) == 0.0
