"""tests/test_edge_rank.py — EDGE LAB ranking (operator, 2026-09-08).

Two display defects made the board unreadable as a leaderboard:

  1. BROKER TRUTH sorted worst-first, so the account's strongest cell sat at
     the BOTTOM of the page and the biggest loser led. It also ranked on
     DOLLARS, which score the seat size rather than the signal (operator,
     2026-09-08: "the $ size of pips can change, but not the amount").
  2. The CHEATER hot-hand lane returned tier 3 / "PROMOTE READY" — a label
     that reads "passes the full bar" — for rows that had bypassed the bar,
     and scored them on CUMULATIVE pips while the genuine lane scored on LCB.
     cum is unbounded and grows with volume, so all 90 bar-bypassed rows
     sorted above all 78 qualified ones. Every row the operator inspected off
     the top of that section was a cheater row.

These tests pin the ranking, not the cosmetics.
"""
import pytest

from ops import shadowboard as sb


# ── broker truth: sample-aware, best first ──────────────────────────────────

def test_one_lucky_cycle_cannot_outrank_a_repeater():
    """The real case: es_trend_long/asia made +86p in a SINGLE cycle;
    control_atr5m_60 made +151p over ELEVEN. Raw totals put them side by
    side; the shrunk score must not."""
    lucky = {"pips": 86.0, "cycles": 1}
    proven = {"pips": 151.0, "cycles": 11}
    assert sb._btruth_score(proven) > sb._btruth_score(lucky)
    # and the gap must be decisive, not a rounding accident
    assert sb._btruth_score(proven) > 3 * sb._btruth_score(lucky)


def test_shrink_is_monotonic_in_cycles():
    prev = None
    for cyc in (1, 2, 3, 5, 8, 11, 20):
        v = sb._btruth_score({"pips": 100.0, "cycles": cyc})
        if prev is not None:
            assert v > prev
        prev = v
    # never credits more than the dollars actually earned
    assert sb._btruth_score({"pips": 100.0, "cycles": 999}) < 100.0


def test_no_completed_cycle_scores_neutral():
    """judge-when-flat: an unfinished family is neither credited nor condemned."""
    assert sb._btruth_score({"pips": 500.0, "cycles": 0}) == 0.0
    assert sb._btruth_score({"pips": -500.0, "cycles": 0}) == 0.0
    assert sb._btruth_score({"pips": None, "cycles": 4}) == 0.0


def test_losses_shrink_toward_zero_too():
    assert sb._btruth_score({"pips": -100.0, "cycles": 1}) > \
           sb._btruth_score({"pips": -100.0, "cycles": 11})


def test_dollars_do_not_decide_the_rank():
    """Identical pip performance, different seat size: a 0.50x PROBE earns half
    the dollars of a full ACTIVE seat for exactly the same signal. Ranked on
    pips they tie; ranked on dollars the fatter seat wins for no merit."""
    probe = {"pips": 120.0, "usd": 40.0, "cycles": 6}     # 0.50x seat
    active = {"pips": 120.0, "usd": 80.0, "cycles": 6}    # full seat
    assert sb._btruth_score(probe) == sb._btruth_score(active)


def test_a_thin_pip_edge_on_a_fat_pair_cannot_buy_the_lead():
    """A JPY-cross pip is worth several times a EUR/USD pip in dollars. The
    weaker signal must not lead just because its pips price higher."""
    weak_but_rich = {"pips": 40.0, "usd": 200.0, "cycles": 8}
    strong_but_cheap = {"pips": 150.0, "usd": 60.0, "cycles": 8}
    assert sb._btruth_score(strong_but_cheap) > sb._btruth_score(weak_but_rich)


def test_broker_truth_ranks_best_first(monkeypatch):
    def _fam(setup, usd, cycles, pips=None):
        pips = usd if pips is None else pips
        return {"instrument": "EUR_JPY", "session": "ny", "setup": setup,
                "n": cycles, "greens": cycles, "usd": usd, "pips": pips,
                "n_parents": 1, "n_poppers": 0, "n_open": 0,
                "open_upl": 0.0, "open_floor_usd": 0.0,
                "n_cycles": cycles, "cycle_bps": 0.0,
                "cycles": [{"pips": usd / cycles, "usd": usd / cycles,
                            "end": "2026-08-0%d T00:00" % (i + 1)}
                           for i in range(cycles)]}
    monkeypatch.setitem(sb._FAM_CACHE, "full", {
        "since": "2026-07-19T00:00:00Z",
        # real_edge earns FEWER dollars than fat_seat but far more pips: the
        # ranking must follow the pips.
        "families": [_fam("big_loser", -220.0, 7, pips=-135.0),
                     _fam("one_hit_wonder", 64.99, 1, pips=86.0),
                     _fam("fat_seat", 90.0, 11, pips=40.0),
                     _fam("real_edge", 67.39, 11, pips=151.0)],
        "account": {"window_realized_usd": 0.0, "attributed_usd": 0.0,
                    "pre_era_usd": 0.0, "unattributed_usd": 0.0},
        "excluded_pre_era_closes": 0})
    rows = sb.broker_truth()["rows"]
    assert [r["setup"] for r in rows] == \
        ["real_edge", "fat_seat", "one_hit_wonder", "big_loser"]
    assert rows[0]["edge_score"] > 0 and rows[-1]["edge_score"] < 0
    # the pip twins of the cycle stats must be published for the board to show
    assert rows[0]["avg_cycle_pips"] is not None
    assert rows[0]["worst_cycle_pips"] is not None
    assert rows[0]["best_cycle_pips"] is not None


# ── the cheater lane must stop wearing the promotion badge ──────────────────

GC = {"cheater_promotion_enabled": True, "cheater_min_n": 3,
      "cheater_cum_pips": 100.0}


def _era(n=65, days=25, avg=11.4, lcb=1.88, promotable=False, codes=("FDR",)):
    return {"n": n, "days": days, "avg": avg, "lcb": lcb, "q": 0.19,
            "promotable": promotable, "req_n": 10, "req_days": 5,
            "codes": list(codes)}


def test_bar_bypassed_row_does_not_claim_promote_ready():
    """kc_up_long_lean_t20s: cum +741p, promotable False on FDR."""
    tier, verdict, reason, score = sb._gov_verdict(
        "SHADOW", _era(), None, None, GC, 10)
    assert tier == 6, "must leave the PROMOTE READY tier"
    assert verdict == "CHEATER — BAR BYPASSED"
    assert "PROMOTE READY" not in verdict
    # the reason must carry WHY it is not qualified, so the row is self-explaining
    assert "n=65/10" in reason and "days=25/5" in reason and "fails: FDR" in reason


def test_bar_bypassed_row_ranks_on_lcb_not_cumulative():
    """The ordering bug: cum (hundreds) vs lcb (single digits) in one tier."""
    _, _, _, score = sb._gov_verdict("SHADOW", _era(lcb=1.88), None, None, GC, 10)
    assert score == pytest.approx(1.88), "scored on cum, the ranking breaks again"


def test_a_genuinely_promotable_row_keeps_the_badge():
    tier, verdict, _, score = sb._gov_verdict(
        "SHADOW", _era(promotable=True, codes=(), lcb=4.11), None, None, GC, 10)
    assert tier == 3 and verdict == "PROMOTE READY"
    assert score == pytest.approx(4.11)


def test_qualified_outranks_bar_bypassed_even_with_far_fewer_pips():
    """A +4.11 LCB on 46 episodes must beat a +741p cumulative that failed FDR."""
    good = {"gov": dict(zip(("tier", "verdict", "reason", "score"),
                            sb._gov_verdict("SHADOW", _era(promotable=True, codes=(),
                                                           lcb=4.11, avg=7.04, n=46),
                                            None, None, GC, 10))),
            "lcb": 4.11, "avg_net240": 7.04}
    cheat = {"gov": dict(zip(("tier", "verdict", "reason", "score"),
                             sb._gov_verdict("SHADOW", _era(), None, None, GC, 10))),
             "lcb": 1.88, "avg_net240": 11.4}
    assert sb._row_key(good) < sb._row_key(cheat)


def test_tier_order_slots_the_cheater_lane_after_promote_ready():
    o = sb._TIER_ORDER
    assert o[0] < o[1] < o[2] < o[3] < o[6] < o[4] < o[5] < o[7], \
        "DEMOTE DUE, DEFENDED, ACTIVE, PROMOTE READY, CHEATER, BUILDING, QUEUED, RETIRED"


def test_cheater_lane_has_an_honest_label():
    lbl = sb.TIER_LABELS[6]
    assert "BAR BYPASSED" in lbl
    assert "passes the full bar" not in lbl
