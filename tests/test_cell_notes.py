"""tests/test_cell_notes.py — the notes counts sentence must track reality.

The "N ACTIVE, M SHADOW setups." sentence in config/cells session notes was
written at wiring time and never updated by status flips; 10 cells were lying
on the dashboard when the EUR_JPY/ny demotion made it visible (2026-08-04).
Every flip now regenerates it, and hand-written notes are left alone.
"""
from ops.server import _refresh_session_notes


def _scfg(notes, statuses):
    return {"notes": notes, "setups": [{"status": s} for s in statuses]}


def test_counts_sentence_is_rewritten_from_actual_statuses():
    scfg = _scfg("1 ACTIVE, 0 SHADOW setups. Tier=2 ev=-0.8.",
                 ["SHADOW", "SHADOW"])
    _refresh_session_notes(scfg)
    assert scfg["notes"] == "2 SHADOW setups. Tier=2 ev=-0.8."


def test_probe_and_disabled_are_counted():
    scfg = _scfg("2 ACTIVE, 0 SHADOW setups. rest",
                 ["ACTIVE", "PROBE", "SHADOW", "DISABLED"])
    _refresh_session_notes(scfg)
    assert scfg["notes"].startswith(
        "1 ACTIVE, 1 PROBE, 1 SHADOW, 1 DISABLED setups. ")


def test_handwritten_notes_left_untouched():
    scfg = _scfg("marching-band cell — see slate 07-31.", ["SHADOW"])
    _refresh_session_notes(scfg)
    assert scfg["notes"] == "marching-band cell — see slate 07-31."


def test_missing_notes_is_a_noop():
    scfg = {"setups": [{"status": "SHADOW"}]}
    _refresh_session_notes(scfg)
    assert "notes" not in scfg
