"""core/execution_score.py — the seat selector's ranking (charter, 2026-07-31).

  ExecutionScore = RelativeHeat + TrustFloor − CorrelationPenalty − ExposureCost

Replaces first-qualifying-in-config-order (within a cell) and ev_seq-then-
alphabetical (across pairs). Heat/Trust come from data/heat_scores.json,
written by the governor each run (empty file / missing key => score 0 terms:
behavior degrades gracefully to the old ordering, never blocks a trade).

Pure functions + a tiny mtime-cached reader; no network.
"""
from __future__ import annotations

import json
import os
import statistics
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_HEAT_FILE = _REPO / "data" / "heat_scores.json"
_CACHE = {"mtime": None, "scores": {}}

TRUST_FLOOR = 0.25          # a trusted, non-decaying seat's floor bonus
CORR_PENALTY = 0.10         # per open trade sharing a currency
EXPO_COST = 0.10            # * n_open/cap — a fuller book raises the bar


def load_heat_scores() -> dict:
    """{'PAIR|sess|setup': {...}} — cached by file mtime; {} when absent."""
    try:
        m = os.path.getmtime(_HEAT_FILE)
    except OSError:
        return {}
    if _CACHE["mtime"] != m:
        try:
            _CACHE["scores"] = json.loads(_HEAT_FILE.read_text()).get("scores", {})
            _CACHE["mtime"] = m
        except (OSError, ValueError):
            return _CACHE["scores"] or {}
    return _CACHE["scores"]


def relative_heat(key: str, side: str, scores: dict) -> float:
    """Heat minus the (pair, side) peer median — one market move must not
    make twelve near-identical setups look independently hot."""
    me = scores.get(key) or {}
    heat = me.get("heat")
    if heat is None:
        return 0.0
    pair = key.split("|", 1)[0]
    peers = [v.get("heat") for k, v in scores.items()
             if k != key and k.split("|", 1)[0] == pair
             and v.get("side") == side and v.get("heat") is not None]
    # no peers: relative = absolute (a lone hot cell IS the cluster's best;
    # a lone cold cell must not hide behind an empty comparison)
    med = statistics.median(peers) if peers else 0.0
    return round(heat - med, 4)


def execution_score(key: str, side: str, pair: str, scores: dict,
                    open_currencies: dict = None,
                    n_open: int = 0, cap: int = 6) -> float:
    me = scores.get(key) or {}
    rel = relative_heat(key, side, scores)
    trust_floor = TRUST_FLOOR if (me.get("trusted")
                                  and not me.get("decaying")) else 0.0
    corr = 0.0
    if open_currencies:
        for ccy in pair.split("_"):
            corr += CORR_PENALTY * int(open_currencies.get(ccy, 0))
    expo = EXPO_COST * (n_open / cap if cap else 0.0)
    return round(rel + trust_floor - corr - expo, 4)
