"""THE CHAMBER (v6.33.0): stamp form feeds the ranked selector."""
import json

from core import execution_score as xs


def test_form_prefers_recent_then_era_then_neutral():
    forms = {"A|ny|hot":   {"form7": 12.0, "n7": 5, "era_avg": -3.0, "era_n": 20},
             "B|ny|era":   {"form7": None, "n7": 0, "era_avg": 8.0,  "era_n": 10},
             "C|ny|thin":  {"form7": 4.0,  "n7": 1, "era_avg": None, "era_n": 0},
             "D|ny|cold":  {"form7": -30.0, "n7": 6, "era_avg": 5.0, "era_n": 9}}
    assert xs.stamp_form("A|ny|hot", forms) == 0.5          # 12/20 clamped? no: 0.6 -> clamp 0.5
    assert xs.stamp_form("B|ny|era", forms) == 0.4          # era fallback 8/20
    assert xs.stamp_form("C|ny|thin", forms) == 0.0         # n too thin everywhere
    assert xs.stamp_form("D|ny|cold", forms) == -0.5        # losses sink, clamped
    assert xs.stamp_form("E|ny|none", forms) == 0.0         # unknown = neutral


def test_execution_score_ranks_hot_form_first(tmp_path, monkeypatch):
    cf = tmp_path / "chamber_scores.json"
    cf.write_text(json.dumps({"t": "x", "forms": {
        "EUR_USD|ny|hot":  {"form7": 10.0, "n7": 4, "era_avg": None, "era_n": 0},
        "GBP_USD|ny|cold": {"form7": -10.0, "n7": 4, "era_avg": None, "era_n": 0},
    }}))
    monkeypatch.setattr(xs, "_CHAMBER_FILE", cf)
    monkeypatch.setattr(xs, "_FORM_CACHE", {"mtime": None, "forms": {}})
    hot = xs.execution_score("EUR_USD|ny|hot", "long", "EUR_USD", {}, {})
    cold = xs.execution_score("GBP_USD|ny|cold", "long", "GBP_USD", {}, {})
    assert hot > 0 > cold and hot - cold == 1.0


def test_missing_chamber_file_is_neutral(monkeypatch, tmp_path):
    monkeypatch.setattr(xs, "_CHAMBER_FILE", tmp_path / "nope.json")
    monkeypatch.setattr(xs, "_FORM_CACHE", {"mtime": None, "forms": {}})
    assert xs.load_chamber_form() == {}
    assert xs.execution_score("X|ny|y", "long", "EUR_USD", {}, {}) == 0.0
