"""tests/test_shadowboard_fold.py — D-7 stage C: one journal scan, two stamp
formats, zero double-counting; costs are metric-version aware."""
from datetime import datetime, timedelta, timezone

import pytest

from core.trial_stats import episode_net
from ops.shadowboard import _fold_stamps

T0 = datetime(2026, 7, 28, 12, 0, 0, tzinfo=timezone.utc)


def _v2(entry=1.1002, spread=2.0, mech="abc123"):
    return {"pair": "EUR_USD", "session": "london", "setup_id": "s1",
            "side": "long", "status": "SHADOW", "bid": 1.1000, "ask": 1.1002,
            "entry": entry, "spread_pips": spread, "horizon_min": 240,
            "exit_config": {"mode": "ratchet", "sl_pips": 50.0},
            "mechanics_hash": mech}


def _cs(t, spread=2.0):
    return (t, "EUR_USD/london", "s1", "long", "SHADOW", spread, None)


def _ts(t, **kw):
    return (t, "EUR_USD/london", "s1", "long", "SHADOW", 2.0, _v2(**kw))


def test_paired_lines_make_one_v2_episode():
    eps = _fold_stamps([_cs(T0), _ts(T0 + timedelta(seconds=1))], {})
    assert len(eps) == 1
    ep = next(iter(eps.values()))
    assert ep["mv"] == 2 and ep["entry"] == 1.1002
    assert ep["mech"] == "abc123"
    assert ep["exit_config"]["sl_pips"] == 50.0


def test_within_episode_restamps_dont_duplicate_or_reanchor():
    rows = [_cs(T0), _ts(T0 + timedelta(seconds=1))]
    for m in (5, 10, 15):   # 5-min cycle restamps inside the same episode
        rows += [_cs(T0 + timedelta(minutes=m)),
                 _ts(T0 + timedelta(minutes=m), entry=9.9999)]
    eps = _fold_stamps(rows, {})
    assert len(eps) == 1
    assert next(iter(eps.values()))["entry"] == 1.1002, \
        "the entry anchors at the OPENING stamp, never a later restamp"


def test_gap_over_30min_opens_new_episode():
    eps = _fold_stamps([_cs(T0), _ts(T0),
                        _cs(T0 + timedelta(minutes=45)),
                        _ts(T0 + timedelta(minutes=45))], {})
    assert len(eps) == 2
    assert all(e["mv"] == 2 for e in eps.values())


def test_trialstamp_alone_creates_v2_episode():
    eps = _fold_stamps([_ts(T0)], {})
    assert len(eps) == 1 and next(iter(eps.values()))["mv"] == 2


def test_legacy_only_episode_stays_legacy():
    eps = _fold_stamps([_cs(T0)], {})
    ep = next(iter(eps.values()))
    assert "mv" not in ep and ep["scores"] is None


def test_late_trialstamp_does_not_upgrade_old_episode():
    # a TRIALSTAMP 10 min into an episode opened legacy (e.g. deploy landed
    # mid-episode) must not claim an entry anchored minutes after the open
    eps = _fold_stamps([_cs(T0), _ts(T0 + timedelta(minutes=10))], {})
    assert "mv" not in next(iter(eps.values()))


def test_fold_is_idempotent_across_rescans():
    rows = [_cs(T0), _ts(T0 + timedelta(seconds=1))]
    eps = _fold_stamps(rows, {})
    again = _fold_stamps(rows, dict(eps))
    assert again == eps


# ── version-aware cost ───────────────────────────────────────────────────────

def test_episode_net_v2_pays_slippage_only():
    # v2 already crossed the spread inside its geometry: don't double-charge
    assert episode_net(10.0, 2.0, "EUR_USD", slippage_pips=0.5,
                       executable=True) == pytest.approx(9.5)


def test_episode_net_legacy_pays_spread_and_slippage():
    assert episode_net(10.0, 2.0, "EUR_USD", slippage_pips=0.5,
                       executable=False) == pytest.approx(7.5)


def test_episode_net_legacy_fallback_spread():
    assert episode_net(10.0, None, "EUR_USD", slippage_pips=0.5) == pytest.approx(8.0)
    assert episode_net(10.0, None, "EUR_CHF", slippage_pips=0.5) == pytest.approx(6.5)
