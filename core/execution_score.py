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
CORR_PENALTY = 0.10         # per open SAME-DIRECTION currency leg (compounding
                            # exposure penalized; offsetting exposure is not —
                            # external review 2026-07-31)
# (the old flat exposure-cost term was identical for every candidate in a
# selection round and therefore could never affect a ranking — removed)


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


def candidate_legs(pair: str, side: str):
    """The signed currency legs this candidate would ADD: long BASE/QUOTE =
    (BASE, long) + (QUOTE, short); short = the mirror."""
    base, quote = pair.split("_")
    if side == "long":
        return ((base, "long"), (quote, "short"))
    return ((base, "short"), (quote, "long"))


def execution_score(key: str, side: str, pair: str, scores: dict,
                    open_legs: dict = None,
                    n_open: int = 0, cap: int = 6) -> float:
    """open_legs: {(currency, 'long'|'short'): count} of legs already open.
    Only SAME-direction overlap is penalized — a candidate that OFFSETS
    existing exposure adds no compounding risk (n_open/cap accepted for
    back-compat; a flat per-round constant cannot affect ranking)."""
    me = scores.get(key) or {}
    rel = relative_heat(key, side, scores)
    trust_floor = TRUST_FLOOR if (me.get("trusted")
                                  and not me.get("decaying")) else 0.0
    corr = 0.0
    if open_legs:
        for leg in candidate_legs(pair, side):
            corr += CORR_PENALTY * int(open_legs.get(leg, 0))
    return round(rel + trust_floor - corr, 4)
