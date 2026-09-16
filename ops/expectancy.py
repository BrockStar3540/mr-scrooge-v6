#!/usr/bin/env python3
"""ops/expectancy.py — the edge verdict: does this tape actually make money?

One question, answered from the broker tape and nothing else: is the realized
edge positive, and is the sample big enough to say so? A high win rate is not
an edge. The system's payoff geometry (average win / average loss) sets a
BREAK-EVEN WIN RATE; only the distance between the realized win rate and that
hurdle is edge, and that distance has to clear its own sampling noise.

Two independent readings, because they fail differently:

  win-rate vs hurdle   intuitive, and how the go/no-go calls have been framed.
                       Weakness: the hurdle is itself estimated from the same
                       sample, so its CI comparison is indicative, not exact.

  bootstrap expectancy  resampled mean P/L per trade with a percentile CI.
                       Makes no distributional assumption and needs no hurdle
                       estimate. This is the one that decides the verdict.

Dollar stats drift with account size — as NAV falls, fixed-percent sizing
shrinks every win AND loss, so a dollar payoff read across eras compares two
different account sizes. Every cross-era comparison here is therefore run on
P/L PER UNIT, which is sizing-invariant.

Usage:
    python3 -m ops.expectancy                     # live tape vs the archived practice tape
    python3 -m ops.expectancy --tape PATH.csv     # any single tape
    python3 -m ops.expectancy --json              # machine-readable

Tape schema: close_utc, instrument, direction, units, realized_usd, source.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LIVE_TAPE = REPO / "livelog" / "trades.csv"
PRACTICE_TAPE = REPO / "forward-test-100" / "trades.csv"

BOOTSTRAP_N = 20_000
BOOTSTRAP_SEED = 20260729  # live cutover date; fixed so the verdict is reproducible


# ---------------------------------------------------------------- statistics

def wilson(hits: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a proportion — behaves at the extremes where
    the normal approximation does not, which matters at 80-90% win rates."""
    if n == 0:
        return (0.0, 0.0)
    p = hits / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def bootstrap_mean_ci(values: list[float], iters: int = BOOTSTRAP_N,
                      alpha: float = 0.05, seed: int = BOOTSTRAP_SEED) -> tuple[float, float]:
    """Percentile CI for the mean of a sample, by resampling with replacement.

    P/L per trade is violently non-normal (a capped-upside body plus a stop-loss
    spike), so the textbook t-interval understates the tail. Resampling makes no
    shape assumption.
    """
    if len(values) < 2:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    n = len(values)
    means = sorted(st.fmean(rng.choices(values, k=n)) for _ in range(iters))
    lo = means[int(alpha / 2 * iters)]
    hi = means[min(iters - 1, int((1 - alpha / 2) * iters))]
    return (lo, hi)


def required_n(p_null: float, p_alt: float, alpha: float = 0.05, power: float = 0.80) -> int:
    """Trades needed to show a win rate of p_alt beats a hurdle of p_null,
    one-sided. This is the number a go-live test should have been sized to."""
    if p_alt <= p_null:
        return -1
    z_a = 1.6448536269514722   # one-sided 95%
    z_b = 0.8416212335729143   # 80% power
    num = z_a * math.sqrt(p_null * (1 - p_null)) + z_b * math.sqrt(p_alt * (1 - p_alt))
    return math.ceil((num / (p_alt - p_null)) ** 2)


# ---------------------------------------------------------------------- tape

def load_tape(path: Path) -> list[dict]:
    """Read a broker tape. Zero-unit rows carry no normalizable P/L and are dropped."""
    rows = []
    with open(path, newline="") as fh:
        for r in csv.DictReader(fh):
            units = abs(float(r["units"]))
            if units == 0:
                continue
            pl = float(r["realized_usd"])
            rows.append({
                "close_utc": r["close_utc"],
                "day": r["close_utc"][:10],
                "instrument": r["instrument"],
                "source": r.get("source", ""),
                "units": units,
                "usd": pl,
                # P/L per 10k units: sizing-invariant, comparable across eras
                "per_unit": pl / units * 1e4,
            })
    if not rows:
        raise SystemExit(f"no usable trades in {path}")
    return rows


def geometry(values: list[float]) -> dict:
    """Payoff geometry of a P/L series, in whatever unit it is denominated."""
    wins = [v for v in values if v > 0]
    losses = [v for v in values if v <= 0]
    n = len(values)
    avg_win = st.fmean(wins) if wins else 0.0
    avg_loss = abs(st.fmean(losses)) if losses else 0.0
    win_rate = len(wins) / n
    # payoff b = avg_win / avg_loss; break-even win rate = 1 / (1 + b)
    payoff = (avg_win / avg_loss) if avg_loss else float("inf")
    be_win_rate = (avg_loss / (avg_win + avg_loss)) if (avg_win + avg_loss) else 0.0
    gross_win, gross_loss = sum(wins), abs(sum(losses))
    return {
        "n": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": win_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "payoff": payoff,
        "break_even_win_rate": be_win_rate,
        "margin_pp": (win_rate - be_win_rate) * 100,
        "profit_factor": (gross_win / gross_loss) if gross_loss else float("inf"),
        "expectancy": st.fmean(values),
        "total": sum(values),
    }


def levers(g: dict) -> dict:
    """What each single lever must reach for expectancy to hit zero, holding
    the other two fixed. Shows which one is actually reachable."""
    wr, aw, al = g["win_rate"], g["avg_win"], g["avg_loss"]
    out = {"win_rate_needed": g["break_even_win_rate"]}
    out["avg_win_needed"] = (al * (1 - wr) / wr) if wr else float("inf")
    out["avg_loss_allowed"] = (aw * wr / (1 - wr)) if wr < 1 else float("inf")
    return out


def verdict(values: list[float], g: dict) -> tuple[str, tuple[float, float]]:
    """Decide on the bootstrap CI of expectancy, not on the win rate."""
    lo, hi = bootstrap_mean_ci(values)
    if lo > 0:
        return "EDGE PROVEN — expectancy CI entirely above zero", (lo, hi)
    if hi < 0:
        return "EDGE DISPROVEN — expectancy CI entirely below zero", (lo, hi)
    return "INCONCLUSIVE — expectancy CI straddles zero (sample cannot tell)", (lo, hi)


def worst_days(rows: list[dict], k: int = 5) -> list[tuple[str, float, int, int]]:
    by_day: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        by_day[r["day"]].append(r["usd"])
    ranked = sorted(by_day.items(), key=lambda kv: sum(kv[1]))[:k]
    return [(d, sum(v), len(v), sum(1 for x in v if x <= 0)) for d, v in ranked]


def analyse(path: Path, label: str) -> dict:
    rows = load_tape(path)
    usd = [r["usd"] for r in rows]
    per_unit = [r["per_unit"] for r in rows]
    g_usd, g_unit = geometry(usd), geometry(per_unit)
    v, (blo, bhi) = verdict(usd, g_usd)
    wlo, whi = wilson(g_usd["wins"], g_usd["n"])
    day_pnl = defaultdict(float)
    for r in rows:
        day_pnl[r["day"]] += r["usd"]
    worst5 = worst_days(rows)
    return {
        "label": label,
        "tape": str(path.relative_to(REPO)) if path.is_relative_to(REPO) else str(path),
        "span": (rows[0]["close_utc"][:10], rows[-1]["close_utc"][:10]),
        "usd": g_usd,
        "per_unit": g_unit,
        "levers": levers(g_usd),
        "win_rate_ci": (wlo, whi),
        "expectancy_ci": (blo, bhi),
        "verdict": v,
        "required_n": required_n(g_usd["break_even_win_rate"], g_usd["win_rate"]),
        "worst_days": worst5,
        "worst_days_share": (sum(p for _, p, _, _ in worst5) / g_usd["total"] * 100)
                            if g_usd["total"] else float("nan"),
        "trading_days": len(day_pnl),
    }


# ------------------------------------------------------------------ printing

def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def render(report: dict, out=None) -> None:
    # resolved at call time, not import time, so a redirected stdout is honoured
    out = sys.stdout if out is None else out
    g, u, lv = report["usd"], report["per_unit"], report["levers"]
    w = out.write
    w(f"\n{report['label']}  ({report['tape']})\n")
    w(f"  window        {report['span'][0]} -> {report['span'][1]}  "
      f"({report['trading_days']} trading days)\n")
    w(f"  trades        {g['n']}  ({g['wins']}W / {g['losses']}L)\n")
    w(f"  realized      ${g['total']:,.2f}   profit factor {g['profit_factor']:.2f}\n")
    w("\n  PAYOFF GEOMETRY (the hurdle you set for yourself)\n")
    w(f"    avg win     ${g['avg_win']:.2f}        avg loss  ${g['avg_loss']:.2f}\n")
    w(f"    payoff      {g['payoff']:.3f}  ->  BREAK-EVEN WIN RATE {_pct(g['break_even_win_rate'])}\n")
    w(f"    actual      {_pct(g['win_rate'])}   95% CI [{_pct(report['win_rate_ci'][0])}, "
      f"{_pct(report['win_rate_ci'][1])}]\n")
    w(f"    MARGIN      {g['margin_pp']:+.2f} percentage points\n")
    w("\n  NORMALIZED (P/L per 10k units — sizing-invariant, safe across eras)\n")
    w(f"    avg win     {u['avg_win']:.2f}        avg loss  {u['avg_loss']:.2f}\n")
    w(f"    payoff      {u['payoff']:.3f}  ->  break-even {_pct(u['break_even_win_rate'])}  "
      f"margin {u['margin_pp']:+.2f}pp\n")
    w("\n  VERDICT\n")
    w(f"    expectancy  ${g['expectancy']:+.3f}/trade  "
      f"95% CI [${report['expectancy_ci'][0]:+.3f}, ${report['expectancy_ci'][1]:+.3f}]\n")
    w(f"    {report['verdict']}\n")
    rn = report["required_n"]
    if rn > 0:
        w(f"    a win rate of {_pct(g['win_rate'])} needs n>={rn} to beat "
          f"{_pct(g['break_even_win_rate'])} at 95%/80% power (this tape: n={g['n']})\n")
    w("\n  TO REACH BREAK-EVEN, ONE OF THESE (others held fixed)\n")
    w(f"    win rate    {_pct(g['win_rate'])} -> {_pct(lv['win_rate_needed'])}  "
      f"({(lv['win_rate_needed'] - g['win_rate']) * 100:+.2f}pp)\n")
    w(f"    avg win     ${g['avg_win']:.2f} -> ${lv['avg_win_needed']:.2f}  "
      f"({(lv['avg_win_needed'] / g['avg_win'] - 1) * 100:+.0f}%)\n")
    w(f"    avg loss    ${g['avg_loss']:.2f} -> ${lv['avg_loss_allowed']:.2f}  "
      f"({(lv['avg_loss_allowed'] / g['avg_loss'] - 1) * 100:+.0f}%)\n")
    w("\n  LOSS CONCENTRATION (correlated-book exposure)\n")
    for d, pnl, n, losers in report["worst_days"]:
        w(f"    {d}  ${pnl:>9,.2f}  {n:>2d} trades, {losers:>2d} losers\n")
    share = report["worst_days_share"]
    if not math.isnan(share):
        w(f"    these 5 days are {share:.0f}% of the period's net result\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tape", type=Path, help="analyse one tape instead of the default pair")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of the card")
    args = ap.parse_args(argv)

    if args.tape:
        targets = [(args.tape, args.tape.stem)]
    else:
        targets = [(PRACTICE_TAPE, "PRACTICE (the tape that sent it live)"),
                   (LIVE_TAPE, "LIVE (real money)")]

    reports = [analyse(p, label) for p, label in targets if p.exists()]
    if not reports:
        print("no tapes found", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(reports, indent=2, default=str))
        return 0

    for r in reports:
        render(r)
    if len(reports) == 2:
        a, b = reports
        print("\n  DRIFT PRACTICE -> LIVE (normalized, sizing-invariant)")
        print(f"    win rate    {_pct(a['usd']['win_rate'])} -> {_pct(b['usd']['win_rate'])}  "
              f"({(b['usd']['win_rate'] - a['usd']['win_rate']) * 100:+.1f}pp)")
        print(f"    payoff      {a['per_unit']['payoff']:.3f} -> {b['per_unit']['payoff']:.3f}")
        print(f"    hurdle      {_pct(a['per_unit']['break_even_win_rate'])} -> "
              f"{_pct(b['per_unit']['break_even_win_rate'])}")
        print(f"    margin      {a['per_unit']['margin_pp']:+.2f}pp -> "
              f"{b['per_unit']['margin_pp']:+.2f}pp")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
