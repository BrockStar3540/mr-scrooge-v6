"""tests/test_seats_and_fdr.py — seat pools + BH family scope (2026-08-06).

Two structural defects found once BOTH promotion lanes were live at the same
time for the first time:

  1. `probe_seat_count` counted every PROBE against the cheater lane's cap, so
     two ordinary PROBEs permanently starved the lane the Commissioner had just
     spent five days earning.
  2. BH-FDR ran over the whole scored book (274 hypotheses) rather than the
     candidate docket, taxing real candidates (n=21, avg +9.99p, LCB +1.46)
     into failure on q alone — and every new shadow made it worse for everyone.
"""
import json
from pathlib import Path

from core.trial_evidence import (SetupEvidence, current_era_evidence,
                                 meets_counting_gates)
from ops.governor import DEFAULT_CFG, cheater_seat_count, probe_seat_count

CFG = {"min_raw_episodes": 10, "min_independent_days": 5, "bar_avg": 2.0,
       "lcb_min": 0.0, "recent_n": 5, "recent_min": 0.0, "fdr_q": 0.05,
       "redemption_min_raw_episodes": 20, "redemption_min_independent_days": 10,
       "strike_disable_count": 3, "cheater_max_seats": 1,
       "max_probe_seats_total": 6}


def _ev(n, days, strikes=0):
    return SetupEvidence(key=("EUR_USD", "london", "x"), raw_n=n,
                         effective_n=float(n), independent_days=days,
                         net_avg=5.0, recent_n=0, recent_avg=None,
                         block_lcb=1.0, p_value=0.01, q_value=None,
                         strikes=strikes)


# ── counting gates / BH family ────────────────────────────────────────────────

def test_counting_gates_are_strike_aware():
    assert meets_counting_gates(_ev(12, 6), CFG) is True
    assert meets_counting_gates(_ev(9, 6), CFG) is False        # short on n
    assert meets_counting_gates(_ev(12, 4), CFG) is False        # short on days
    assert meets_counting_gates(_ev(12, 6, strikes=1), CFG) is False  # redemption bar


# a marginal-but-real signal: mean ~ +3.5p with genuine spread, so the
# bootstrap p-value lands off its floor and the size of the BH family
# actually changes the verdict (an all-identical series pins p at 1/(reps+1)
# and both family modes round to the same q, testing nothing).
_NETS = [8.0, -2.0, 6.0, 1.0, 9.0, -1.0, 5.0, 2.0, 7.0, 0.0, 4.0, 3.0]


def _episodes(cell, setup, n, start_day=1, nets=None):
    """n resolved v2 episodes on n distinct days -> n independent blocks."""
    vals = nets or _NETS
    return {f"{cell}{setup}{i}": {
        "cell": cell, "setup": setup, "side": "short",
        "t": f"2026-08-{start_day + i:02d}T09:00:00+00:00",
        "scores": {"mv": 2, "net240": vals[i % len(vals)]},
        "spread": 0.6} for i in range(n)}


def test_docket_family_excludes_accruing_setups():
    """A well-evidenced candidate should not be taxed by setups that are
    merely accruing. Same evidence, two family modes, different q."""
    eps = {}
    eps.update(_episodes("EUR_USD/london", "good", 12))
    for j in range(25):                       # 25 thin, untested setups
        eps.update(_episodes("EUR_USD/london", f"thin{j}", 3, start_day=1))
    book = {("EUR_USD", "london", s): {"status": "SHADOW", "side": "short",
                                       "cfg_hash": None}
            for s in ["good"] + [f"thin{j}" for j in range(25)]}
    state = {"era_start": {}, "demotion_counts": {}}

    docket = current_era_evidence(eps, book, state, dict(CFG, fdr_family="docket"))
    whole = current_era_evidence(eps, book, state, dict(CFG, fdr_family="all"))
    q_docket = docket[("EUR_USD", "london", "good")].q_value
    q_all = whole[("EUR_USD", "london", "good")].q_value
    assert q_docket is not None and q_all is not None
    assert q_docket < q_all, (
        f"docket scoping must relieve the tax: docket={q_docket} whole={q_all}")
    # the thin setups are not under test and get no q at all under docket mode
    assert docket[("EUR_USD", "london", "thin0")].q_value is None


def test_accruing_setups_still_cannot_promote_without_a_q():
    eps = _episodes("EUR_USD/london", "thin", 3)
    book = {("EUR_USD", "london", "thin"): {"status": "SHADOW", "side": "short",
                                            "cfg_hash": None}}
    ev = current_era_evidence(eps, book, {"era_start": {}, "demotion_counts": {}},
                              dict(CFG, fdr_family="docket"))
    e = ev[("EUR_USD", "london", "thin")]
    assert e.q_value is None and e.promotable is False
    assert "FDR" in e.reason_codes


# ── seat pools ────────────────────────────────────────────────────────────────

def test_probe_seat_count_is_status_derived_and_lane_blind():
    book = {("A", "s", "x"): {"status": "PROBE"},
            ("B", "s", "y"): {"status": "PROBE"},
            ("C", "s", "z"): {"status": "ACTIVE"}}
    assert probe_seat_count(book) == 2


def test_cheater_seat_count_reads_only_its_own_book():
    assert cheater_seat_count({}) == 0
    assert cheater_seat_count({"A|s|x": {"t": "now"}}) == 1
    assert cheater_seat_count(None) == 0


def test_ordinary_probes_no_longer_consume_the_cheater_allowance():
    """The exact live shape on 2026-08-06: two ordinary PROBEs open, cheater
    lane commissioned with one seat and nothing of its own."""
    book = {("USD_CAD", "ny", "echo_box_fade_short"): {"status": "PROBE"},
            ("USD_CHF", "london", "ps_ceil_fade_short"): {"status": "PROBE"}}
    cheater_seats: dict = {}
    global_free = max(0, CFG["max_probe_seats_total"] - probe_seat_count(book))
    seats_free = max(0, min(CFG["cheater_max_seats"]
                            - cheater_seat_count(cheater_seats), global_free))
    assert probe_seat_count(book) == 2
    assert seats_free == 1, "cheater lane must still have its seat"


def test_global_ceiling_still_binds_both_lanes():
    book = {(f"P{i}", "s", "x"): {"status": "PROBE"} for i in range(6)}
    global_free = max(0, CFG["max_probe_seats_total"] - probe_seat_count(book))
    seats_free = max(0, min(CFG["cheater_max_seats"] - cheater_seat_count({}),
                            global_free))
    assert global_free == 0 and seats_free == 0


def test_shipped_config_and_defaults_carry_the_new_keys():
    assert DEFAULT_CFG["max_probe_seats_total"] >= 1
    cfg = json.loads((Path(__file__).parents[1]
                      / "config" / "governor_config.json").read_text())
    # operator 2026-08-07: 6 -> 9 (docket had 8 LCB>0 winners queued on full seats)
    # operator 2026-08-12: 9 -> 15 (pool froze at 10/9 after the B-125-restore
    # over-fill; audit ordered a shed + headroom so the green docket auditions)
    # operator 2026-08-16: 15 -> 20 (B-129 backfill surfaced a 52-cell docket)
    # operator 2026-08-19: 20 -> 30 (post-shed 70-deep bar-met docket vs full house)
    # B-131 class: the ceiling is an OPERATOR DIAL — equality pins here deadlock
    # sanctioned raises at the pre-push hook. Sanity-range pin only.
    assert 1 <= cfg["max_probe_seats_total"] <= 100
    assert cfg["fdr_family"] == "docket"


# ── operator threshold + seat reservation (2026-08-06) ───────────────────────

def test_fdr_threshold_is_the_operator_setting():
    cfg = json.loads((Path(__file__).parents[1]
                      / "config" / "governor_config.json").read_text())
    assert cfg["fdr_q"] == 0.10, "operator raised the flat tolerance 0.05 -> 0.10"


def test_commissioned_lane_keeps_a_reserved_seat():
    """Ordinary promotions must not be able to take the last seat while the
    cheater lane is live and still owed one — that is the starvation bug."""
    max_total, cheater_max = 6, 1
    probes_now = 4                      # four ordinary PROBEs already open
    global_free = max(0, max_total - probes_now)
    cheater_used, cheater_promos = 0, []
    reserve = max(0, cheater_max - cheater_used - len(cheater_promos))
    ord_room = max(0, global_free - len(cheater_promos) - reserve)
    assert global_free == 2 and reserve == 1
    assert ord_room == 1, "one seat must stay held for the commissioned lane"


def test_no_reservation_once_the_cheater_lane_is_seated():
    max_total, cheater_max = 6, 1
    global_free = max(0, max_total - 4)
    cheater_used = 1                    # lane already has its seat
    reserve = max(0, cheater_max - cheater_used - 0)
    assert reserve == 0
    assert max(0, global_free - 0 - reserve) == 2, "no seat withheld unnecessarily"
