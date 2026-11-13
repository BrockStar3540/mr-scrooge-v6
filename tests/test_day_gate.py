"""Day-gate: FX trading day = New York clock + 7h; Thu/Fri + event days skipped, exempt families kept."""
from datetime import datetime, timezone
from config import day_gate as dg

U = lambda y, mo, d, h, mi: datetime(y, mo, d, h, mi, tzinfo=timezone.utc)
CFG = {"enabled": True, "skip_weekdays": [3, 4], "exempt_families": ["rg1_range_scalp", "control_atr5m_60"],
       "event_days": {"2026-12-09": ["ALL"], "2026-12-02": ["USD"]}}
R = lambda now, pair="EUR_USD", sid="echo_box_fade_long": dg.reason(now, pair, sid, CFG)

def test_trading_day_rolls_at_ny_1700():
    assert dg.fx_trading_day(U(2026, 11, 12, 21, 59)).isoformat() == "2026-11-12"   # Thu 16:59 EST
    assert dg.fx_trading_day(U(2026, 11, 12, 22, 1)).isoformat() == "2026-11-13"    # Thu 17:01 EST -> Friday
    assert dg.fx_trading_day(U(2026, 8, 12, 20, 59)).isoformat() == "2026-08-12"    # EDT: 16:59
    assert dg.fx_trading_day(U(2026, 8, 12, 21, 1)).isoformat() == "2026-08-13"

def test_weekdays():
    assert R(U(2026, 11, 12, 15, 0)) == "weekday-Thu" and R(U(2026, 11, 13, 15, 0)) == "weekday-Fri"
    assert R(U(2026, 11, 11, 15, 0)) is None and R(U(2026, 11, 9, 15, 0)) is None     # Wed, Mon
    assert R(U(2026, 11, 15, 22, 5)) is None                                          # Sun 17:05 EST = Monday day

def test_friday_close_boundary():
    assert R(U(2026, 11, 13, 21, 50)) == "weekday-Fri" and R(U(2026, 11, 12, 21, 50)) == "weekday-Thu"

def test_exempt_families():
    t = U(2026, 11, 12, 15, 0)
    assert dg.reason(t, "EUR_USD", "rg1_range_scalp_short", CFG) is None
    assert dg.reason(t, "EUR_USD", "control_atr5m_60_t20s", CFG) is None
    assert dg.reason(t, "EUR_USD", "control_atrconc_60", CFG) == "weekday-Thu"        # different family
    assert dg.reason(t, "EUR_USD", "rg1_range_scalping", CFG) == "weekday-Thu"        # prefix needs "_"

def test_event_days_by_currency():
    assert R(U(2026, 12, 9, 15, 0), "AUD_NZD") == "event-2026-12-09"                   # ALL
    assert R(U(2026, 12, 2, 15, 0), "EUR_USD") == "event-2026-12-02" and R(U(2026, 12, 2, 15, 0), "EUR_GBP") is None

def test_disabled_and_missing_cfg():
    assert dg.reason(U(2026, 11, 12, 15, 0), "EUR_USD", "x", {"enabled": False, "skip_weekdays": [3]}) is None
    assert dg.reason(U(2026, 11, 12, 15, 0), "EUR_USD", "x", {}) is None

def test_filter_intents():
    class I:
        def __init__(s, p, sid): s.pair, s.setup_id = p, sid
    keep = dg.filter_intents([I("EUR_USD", "rg1_range_scalp_short"), I("EUR_USD", "echo_box_fade_long")], U(2026, 11, 11, 15, 0))
    assert len(keep) == 2                                                             # Wednesday: nothing gated


def test_skip_log_carries_replay_fields(caplog):
    import logging
    class EP: sl_pips, trigger_pips, trail_pips, engage_pips, engage_lock_pips, mode = 50.0, 5.0, 2.0, 5.0, 4.0, "ratchet"
    class I: pair, setup_id, side, horizon_min, exit_params, probe = "EUR_USD", "echo_box_fade_long", "long", 60, EP(), False
    dg._seen.clear()
    real = dg.reason; dg.reason = lambda now, pair, sid, cfg=None: real(now, pair, sid, CFG)
    try:
        with caplog.at_level(logging.INFO, logger="v6.daygate"):
            out = dg.filter_intents([I()], U(2026, 11, 12, 15, 0))
    finally:
        dg.reason = real
    assert out == []
    line = [r.getMessage() for r in caplog.records if "DAYGATE skip" in r.getMessage()][0]
    assert "t=2026-11-12T15:00:00Z" in line and "side=long" in line and "sl=50.0" in line and "trail=2.0" in line and "englock=4.0" in line
