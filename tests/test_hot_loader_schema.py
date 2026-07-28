"""tests/test_hot_loader_schema.py — the LIVE loader enforces the schema and
retains the last valid config (external review round 2).

Acceptance list from the review: valid loads; invalid JSON retains prior;
structurally invalid retains prior; first-ever invalid disables the pair;
corrected file reloads; unknown fields and bad statuses are rejected live.
"""
import json
import os
import time

import pytest

import modules.cells.cell as cell


VALID = {
    "pair": "EUR_USD",
    "generated": "2026-07-28T00:00:00Z",
    "generator": "test",
    "sessions": {
        "london": {
            "enabled": True,
            "structure": {"tier": None, "rh_offer_rate_60m": None,
                          "dead_rate_60m": None, "lineage": "test"},
            "setups": [{
                "id": "s1", "side": "long", "class": "control",
                "status": "SHADOW", "horizon_min": 240,
                "conditions": [{"feature": "rsi14", "max": 30.0}],
                "exit": {"sl_pips": 50.0, "trigger_pips": 8.5, "trail_pips": 2.5},
                "sizing": {"risk_pct": 0.2},
                "evidence": {"ev_seq": None, "source": "test"},
            }],
        },
    },
}


@pytest.fixture()
def cells_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(cell, "_CELLS_DIR", tmp_path)
    cell._config_cache.clear()
    cell._mtime_cache.clear()
    yield tmp_path
    cell._config_cache.clear()
    cell._mtime_cache.clear()


def _write(dirp, data, raw=None):
    p = dirp / "EUR_USD.json"
    p.write_text(raw if raw is not None else json.dumps(data))
    # force a distinct mtime so the hot-reload check sees a change
    st = p.stat()
    os.utime(p, (st.st_atime, st.st_mtime + 1 + time.time() % 1))
    return p


def test_valid_config_loads(cells_dir):
    _write(cells_dir, VALID)
    data = cell._load_pair_config("EUR_USD")
    assert data is not None and "sessions" in data


def test_invalid_json_retains_prior_valid(cells_dir):
    _write(cells_dir, VALID)
    assert cell._load_pair_config("EUR_USD") is not None
    _write(cells_dir, None, raw="{ not json")
    data = cell._load_pair_config("EUR_USD")
    assert data is not None, "a bad hot edit must not dark the pair"
    assert data["sessions"]["london"]["setups"][0]["id"] == "s1"


def test_structurally_invalid_retains_prior_valid(cells_dir):
    _write(cells_dir, VALID)
    assert cell._load_pair_config("EUR_USD") is not None
    bad = json.loads(json.dumps(VALID))
    bad["sessions"]["london"]["setups"][0]["status"] = "ACTVE"   # the review's typo
    _write(cells_dir, bad)
    data = cell._load_pair_config("EUR_USD")
    assert data is not None
    assert data["sessions"]["london"]["setups"][0]["status"] == "SHADOW", \
        "the typo'd config must never replace the valid one"


def test_unknown_exit_field_rejected_live(cells_dir):
    _write(cells_dir, VALID)
    assert cell._load_pair_config("EUR_USD") is not None
    bad = json.loads(json.dumps(VALID))
    bad["sessions"]["london"]["setups"][0]["exit"]["trail_pisp"] = 2.5
    _write(cells_dir, bad)
    data = cell._load_pair_config("EUR_USD")
    assert "trail_pisp" not in data["sessions"]["london"]["setups"][0]["exit"]


def test_first_ever_invalid_disables_pair(cells_dir):
    _write(cells_dir, None, raw="{ never valid")
    assert cell._load_pair_config("EUR_USD") is None


def test_corrected_file_reloads(cells_dir):
    _write(cells_dir, VALID)
    assert cell._load_pair_config("EUR_USD") is not None
    _write(cells_dir, None, raw="{ broken")
    assert cell._load_pair_config("EUR_USD") is not None      # prior retained
    fixed = json.loads(json.dumps(VALID))
    fixed["sessions"]["london"]["setups"][0]["id"] = "s1_fixed"
    _write(cells_dir, fixed)
    data = cell._load_pair_config("EUR_USD")
    assert data["sessions"]["london"]["setups"][0]["id"] == "s1_fixed"


def test_broken_file_not_reparsed_every_call(cells_dir, monkeypatch):
    _write(cells_dir, VALID)
    assert cell._load_pair_config("EUR_USD") is not None
    _write(cells_dir, None, raw="{ broken")
    assert cell._load_pair_config("EUR_USD") is not None
    calls = {"n": 0}
    real_loads = json.loads

    def counting_loads(*a, **k):
        calls["n"] += 1
        return real_loads(*a, **k)

    monkeypatch.setattr(cell.json, "loads", counting_loads)
    cell._load_pair_config("EUR_USD")     # same broken mtime — no re-parse
    assert calls["n"] == 0
