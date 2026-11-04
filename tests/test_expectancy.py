"""tests/test_expectancy.py — the edge-verdict report (ops/expectancy.py).

Guards the arithmetic that the go/no-go decision rests on: the break-even win
rate implied by the payoff geometry, the break-even levers, and the bootstrap
verdict. A silent error here would let a negative-expectancy config read as a
winner, which is exactly the failure this report exists to prevent.
"""
import csv
import math

import pytest

from ops import expectancy as ex


def _tape(tmp_path, pnl, units=10_000, name="t.csv"):
    """Synthetic broker tape with a known P/L series."""
    path = tmp_path / name
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["close_utc", "instrument", "direction", "units", "realized_usd", "source"])
        for i, p in enumerate(pnl):
            day = 1 + i // 20
            w.writerow([f"2026-08-{day:02d}T0{i % 10}:00:00Z", "EUR_USD",
                        "long", units, f"{p}", "parent"])
    return path


# ------------------------------------------------------------------ geometry

def test_break_even_win_rate_is_the_payoff_identity():
    """BE = 1/(1+payoff): 4 wins of 1 against 1 loss of 4 is exactly break-even."""
    g = ex.geometry([1.0, 1.0, 1.0, 1.0, -4.0])
    assert g["payoff"] == pytest.approx(0.25)
    assert g["break_even_win_rate"] == pytest.approx(0.80)
    assert g["win_rate"] == pytest.approx(0.80)
    assert g["margin_pp"] == pytest.approx(0.0)
    assert g["expectancy"] == pytest.approx(0.0)
    assert g["profit_factor"] == pytest.approx(1.0)


def test_high_win_rate_can_still_be_negative_expectancy():
    """The whole point of the report: 90% wins with a 0.05 payoff loses money."""
    g = ex.geometry([1.0] * 9 + [-20.0])
    assert g["win_rate"] == pytest.approx(0.90)
    assert g["break_even_win_rate"] > g["win_rate"]
    assert g["expectancy"] < 0


def test_zero_pnl_trade_counts_as_a_loss_not_a_win():
    """A scratch is not a win; counting it as one would flatter the win rate."""
    g = ex.geometry([1.0, 0.0])
    assert g["wins"] == 1 and g["losses"] == 1


def test_levers_each_independently_reach_break_even():
    pnl = [5.0] * 8 + [-30.0] * 2
    g = ex.geometry(pnl)
    lv = ex.levers(g)
    wr, aw, al = g["win_rate"], g["avg_win"], g["avg_loss"]
    # applying any single lever must zero the expectancy
    assert lv["win_rate_needed"] * aw - (1 - lv["win_rate_needed"]) * al == pytest.approx(0.0)
    assert wr * lv["avg_win_needed"] - (1 - wr) * al == pytest.approx(0.0)
    assert wr * aw - (1 - wr) * lv["avg_loss_allowed"] == pytest.approx(0.0)


# ---------------------------------------------------------------- statistics

def test_wilson_brackets_the_point_estimate_and_stays_in_range():
    lo, hi = ex.wilson(90, 101)
    assert 0.0 <= lo < 90 / 101 < hi <= 1.0
    # a wider sample must tighten the interval
    lo2, hi2 = ex.wilson(900, 1010)
    assert (hi2 - lo2) < (hi - lo)


def test_wilson_handles_degenerate_samples():
    assert ex.wilson(0, 0) == (0.0, 0.0)
    lo, hi = ex.wilson(10, 10)
    assert hi <= 1.0 and lo < 1.0


def test_required_n_grows_as_the_margin_shrinks():
    wide = ex.required_n(0.81, 0.89)
    narrow = ex.required_n(0.854, 0.89)
    assert 0 < wide < narrow
    assert ex.required_n(0.90, 0.85) == -1   # no edge to size for


def test_bootstrap_ci_is_deterministic_and_brackets_the_mean():
    vals = [5.0] * 80 + [-30.0] * 20
    lo, hi = ex.bootstrap_mean_ci(vals, iters=2000)
    assert (lo, hi) == ex.bootstrap_mean_ci(vals, iters=2000)   # seeded
    assert lo < sum(vals) / len(vals) < hi


def test_bootstrap_ci_undefined_for_singletons():
    assert all(math.isnan(v) for v in ex.bootstrap_mean_ci([1.0]))


# ------------------------------------------------------------------- verdict

def test_verdict_proven_disproven_and_inconclusive():
    winner = [10.0] * 90 + [-10.0] * 10
    loser = [1.0] * 80 + [-30.0] * 20
    thin = [1.0, -1.0] * 4
    assert ex.verdict(winner, ex.geometry(winner))[0].startswith("EDGE PROVEN")
    assert ex.verdict(loser, ex.geometry(loser))[0].startswith("EDGE DISPROVEN")
    assert ex.verdict(thin, ex.geometry(thin))[0].startswith("INCONCLUSIVE")


# ---------------------------------------------------------------------- tape

def test_per_unit_normalization_is_sizing_invariant(tmp_path):
    """Halving the account halves every dollar figure but must not move the
    normalized payoff — the bug that makes era-over-era comparison lie."""
    pnl = [5.0] * 8 + [-30.0] * 2
    big = ex.analyse(_tape(tmp_path, pnl, units=20_000, name="big.csv"), "big")
    small = ex.analyse(_tape(tmp_path, [p / 2 for p in pnl], units=10_000, name="small.csv"), "small")
    assert big["usd"]["avg_win"] == pytest.approx(2 * small["usd"]["avg_win"])
    assert big["per_unit"]["payoff"] == pytest.approx(small["per_unit"]["payoff"])
    assert big["per_unit"]["break_even_win_rate"] == pytest.approx(
        small["per_unit"]["break_even_win_rate"])


def test_zero_unit_rows_are_dropped_not_divided_by(tmp_path):
    path = _tape(tmp_path, [5.0, -30.0])
    with open(path, "a", newline="") as fh:
        csv.writer(fh).writerow(["2026-08-02T00:00:00Z", "EUR_USD", "long", 0, "0.0", "parent"])
    assert len(ex.load_tape(path)) == 2


def test_empty_tape_is_an_error_not_a_zero_division(tmp_path):
    with pytest.raises(SystemExit):
        ex.load_tape(_tape(tmp_path, []))


def test_short_side_units_normalize_by_magnitude(tmp_path):
    """OANDA reports short units negative; normalizing by a signed value would
    flip the sign of every short trade's per-unit P/L."""
    path = tmp_path / "short.csv"
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["close_utc", "instrument", "direction", "units", "realized_usd", "source"])
        w.writerow(["2026-08-01T00:00:00Z", "EUR_USD", "short", -10_000, "5.0", "parent"])
    assert ex.load_tape(path)[0]["per_unit"] > 0


# ----------------------------------------------------------- the real tapes

@pytest.mark.parametrize("tape", [ex.LIVE_TAPE, ex.PRACTICE_TAPE])
def test_shipped_tapes_analyse_cleanly(tape):
    if not tape.exists():
        pytest.skip(f"{tape} not present")
    r = ex.analyse(tape, tape.stem)
    assert r["usd"]["n"] > 0
    assert 0.0 <= r["usd"]["win_rate"] <= 1.0
    assert r["usd"]["total"] == pytest.approx(
        r["usd"]["expectancy"] * r["usd"]["n"], rel=1e-6)
    lo, hi = r["expectancy_ci"]
    assert lo <= r["usd"]["expectancy"] <= hi


def test_main_renders_both_tapes(capsys):
    assert ex.main([]) == 0
    out = capsys.readouterr().out
    assert "BREAK-EVEN WIN RATE" in out
    assert "DRIFT PRACTICE -> LIVE" in out


def test_main_json_is_parseable(capsys):
    import json
    assert ex.main(["--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert {"verdict", "usd", "per_unit"} <= set(payload[0])
