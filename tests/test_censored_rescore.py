"""tests/test_censored_rescore.py — B-129 / B-130: censored episodes must
resolve eventually, and stamped-but-unresolved must never render as absence.

B-129: episodes were scored exactly once, minutes after horizon — the 5-day
follow-to-exit could only see candles existing at that moment, so drifting
trades were censored-forever (the v6.24 bias, resurrected). _needs_score now
re-selects censored episodes until resolved or truly past FOLLOW_MAX_DAYS.

B-130: groups whose every episode was censored emitted no row; the board
backfilled QUEUED placeholders and 108 real cells displayed as never-fired.
"""
from datetime import datetime, timedelta, timezone

from ops import shadowboard as sb


def _ep(age_hours, scores):
    t0 = datetime.now(timezone.utc) - timedelta(hours=age_hours)
    return {"cell": "EUR_USD/ny", "setup": "x", "side": "short",
            "status": "SHADOW", "t": t0.isoformat(), "mv": 2,
            "horizon_min": 240, "scores": scores, "spread": 1.0}


NOW = datetime.now(timezone.utc)


def test_unscored_mature_episode_selected():
    assert sb._needs_score(_ep(5, None), NOW)


def test_unscored_immature_episode_waits():
    assert not sb._needs_score(_ep(1, None), NOW)


def test_resolved_episode_never_rescored():
    assert not sb._needs_score(_ep(30, {"net240": 5.0}), NOW)


def test_censored_episode_is_rescored():
    assert sb._needs_score(_ep(30, {"net240": None, "censored": True}), NOW)


def test_censored_final_is_left_alone():
    assert not sb._needs_score(
        _ep(200, {"net240": None, "censored": True, "censored_final": True}), NOW)


def test_all_censored_group_still_emits_a_row(monkeypatch, tmp_path):
    """B-130: two censored episodes, zero resolved — the row must exist and
    carry its censored count instead of vanishing into a QUEUED placeholder."""
    cells = tmp_path / "cells"; cells.mkdir()
    monkeypatch.setattr(sb, "_CELLS_DIR", cells, raising=False)
    db = {"episodes": {
        "k1": _ep(48, {"mv": 2, "net240": None, "mfe240": 1.0, "mae240": 9.0,
                       "censored": True, "exit_reason": "horizon"}),
        "k2": _ep(24, {"mv": 2, "net240": None, "mfe240": 2.0, "mae240": 7.0,
                       "censored": True, "exit_reason": "horizon"}),
    }}
    data = sb._aggregate(db)
    allrows = data["rows"] if isinstance(data, dict) else data
    rows = [r for r in allrows if r["setup"] == "x"]
    assert rows, "all-censored group emitted no row (B-130 regression)"
    r = rows[0]
    assert r["n_censored"] == 2
    assert r["episodes"] == 0          # resolved count stays honest
    assert not r.get("queued")
