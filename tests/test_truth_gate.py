"""tests/test_truth_gate.py — TRUTH-CHECK PROMOTION GATE (2026-08-04, operator).

A shadow whose virtual family-cycle sign contradicts its own broker fills is
proven-wrong sim and cannot promote, no matter how good the stamps look.
Era resets never erase real fills — the gate reads the FULL broker window.
"""
import json
from pathlib import Path

from ops.governor import DEFAULT_CFG, truth_gate


def test_no_virtual_cycles_passes():
    ok, why = truth_gate(None, {"n": 5, "usd": -100.0})
    assert ok and "no virtual cycles" in why
    ok, _ = truth_gate({"cycles": 0}, {"n": 5, "usd": -100.0})
    assert ok


def test_no_broker_fills_passes():
    ok, why = truth_gate({"cycles": 6, "net_mean": 50.0}, None)
    assert ok and "no broker fills" in why
    ok, _ = truth_gate({"cycles": 6, "net_mean": 50.0}, {"n": 0})
    assert ok


def test_contradiction_blocks():
    ok, why = truth_gate({"cycles": 8, "net_mean": 90.8},
                         {"n": 28, "usd": -131.79})
    assert not ok and "CONTRADICTS" in why


def test_agreement_passes_both_signs():
    ok, _ = truth_gate({"cycles": 8, "net_mean": 27.5}, {"n": 10, "usd": 167.89})
    assert ok
    ok, _ = truth_gate({"cycles": 6, "net_mean": -37.7}, {"n": 5, "usd": -8.1})
    assert ok


def test_gate_is_on_in_default_and_shipped_config():
    assert DEFAULT_CFG["truth_check_gate"] is True
    cfg = json.loads((Path(__file__).parents[1]
                      / "config" / "governor_config.json").read_text())
    assert cfg["truth_check_gate"] is True
