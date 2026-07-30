"""B-113: the SHADOW board's serve-time status overlay.

The board payload is cached up to 15 minutes, but a setup's status must never
be stale — Brock flipped three shadows ACTIVE by hand and every dashboard
refresh inside the cache window kept showing them as SHADOW while the engine
was already trading them.  get_board() now re-joins config/cells at serve
time and patches status/tier in place.
"""
import ops.shadowboard as sb


def _row(cell, setup, side, status, tier, era=None, lcb=1.0):
    return {"cell": cell, "setup": setup, "side": side, "status": status,
            "era": era, "lcb": lcb, "avg_net240": 1.0,
            "gov": {"tier": tier, "verdict": "x", "reason": "x", "score": 1.0,
                    "family": None}}


def test_overlay_promotes_stale_shadow_row(monkeypatch):
    data = {"rows": [_row("EUR_JPY/ny", "timing_lean_30", "short", "SHADOW", 4,
                          era={"n": 5})]}
    monkeypatch.setattr(sb, "_config_status",
                        lambda: {("EUR_JPY", "ny", "timing_lean_30"):
                                 ("ACTIVE", "short")})
    sb._overlay_live_status(data)
    r = data["rows"][0]
    assert r["status"] == "ACTIVE"
    assert r["flip_pending"] is True
    assert r["gov"]["tier"] == 2 and r["gov"]["verdict"] == "HOLDING"


def test_overlay_demotes_and_resorts(monkeypatch):
    active = _row("USD_JPY/london", "timing_lean_30", "long", "ACTIVE", 1)
    shadow = _row("AUD_JPY/ny", "other", "long", "SHADOW", 4)
    data = {"rows": [active, shadow]}
    monkeypatch.setattr(sb, "_config_status",
                        lambda: {("USD_JPY", "london", "timing_lean_30"):
                                 ("SHADOW", "long"),
                                 ("AUD_JPY", "ny", "other"):
                                 ("SHADOW", "long")})
    sb._overlay_live_status(data)
    assert active["status"] == "SHADOW"
    assert active["gov"]["verdict"] == "QUEUED"     # no era on the row
    assert data["rows"][0] is shadow                 # tier 4 before tier 5


def test_overlay_leaves_ex_side_and_matching_rows(monkeypatch):
    exs = _row("GBP_USD/ny", "old_fade", "long", "EX-SIDE", 7)
    same = _row("EUR_USD/asia", "box", "long", "ACTIVE", 1)
    data = {"rows": [same, exs]}
    monkeypatch.setattr(sb, "_config_status",
                        lambda: {("GBP_USD", "ny", "old_fade"): ("ACTIVE", "short"),
                                 ("EUR_USD", "asia", "box"): ("ACTIVE", "long")})
    sb._overlay_live_status(data)
    assert exs["status"] == "EX-SIDE" and "flip_pending" not in exs
    assert "flip_pending" not in same


def test_overlay_side_retired_row_untouched(monkeypatch):
    # config side flipped since build — the build-time EX-SIDE join owns it
    r = _row("CAD_JPY/asia", "ceil", "short", "SHADOW", 4)
    data = {"rows": [r]}
    monkeypatch.setattr(sb, "_config_status",
                        lambda: {("CAD_JPY", "asia", "ceil"): ("ACTIVE", "long")})
    sb._overlay_live_status(data)
    assert r["status"] == "SHADOW" and "flip_pending" not in r


def test_invalidate_marks_cache_stale():
    sb._CACHE["ts"] = 9e9
    sb.invalidate()
    assert sb._CACHE["ts"] == 0.0
