"""ops/standard.py — the broker-truth STANDARD (Brock, 2026-10-21).

The simulator's verdicts did not match real trading (per-setup correlation of
virtual-cycle net vs broker net was 0.07 over 75 setups; sign agreement 37/75).
So seats are judged ONLY on their own real broker family cycles (a parent plus
the poppers its grid fired = one cycle), against the profile of the five best
live setups: win rate 85-96%, +7..+15p per cycle, profit factor >= 2.7, worst
cycle no deeper than one stop (-60p), <= 1.5 losses per 10 cycles.

  STAY (seated)    last `window_cycles` cycles, judged at >= `min_cycles`:
                   win rate, pips/cycle, profit factor and worst cycle all
                   at or above the `stay` floor.
  ENTER (graduate) PROBE -> ACTIVE at >= `min_cycles` meeting `enter`
                   (the top-5 profile).
  TRIPWIRE         any cycle in the window worse than `tripwire_pips`
                   demotes immediately, whatever the sample size.
  PROBE LIMIT      a PROBE that reaches `max_probe_cycles` without meeting
                   ENTER goes back to SHADOW.

Windows count cycles, not days: a top setup fires 2-3 cycles a week, so ten
days is 3-4 cycles and one normal stop would fail a true-90% setup 34% of
the time; 20 cycles at an 80% floor falsely demotes it ~4% of the time.
Pure functions only; ops/governor.py executes the decisions.
"""
from __future__ import annotations

DEFAULTS = {
    "enabled": False,
    "window_cycles": 20,
    "min_cycles": 10,
    "stay": {"wr": 0.80, "exp_pips": 3.0, "pf": 1.5, "worst_pips": -90.0},
    "enter": {"wr": 0.85, "exp_pips": 5.0, "pf": 2.5, "worst_pips": -65.0},
    "tripwire_pips": -90.0,
    "max_probe_cycles": 20,
    "max_auditions": 3,
    "audition_min_sim_cycles": 8,
    "audition_min_sim_wr": 0.85,
    "cooldown_days": 30,
}


def merged(cfg: dict | None) -> dict:
    out = {**DEFAULTS, **(cfg or {})}
    for k in ("stay", "enter"):
        out[k] = {**DEFAULTS[k], **((cfg or {}).get(k) or {})}
    return out


def cycle_stats(pips: list) -> dict:
    """Win rate, pips/cycle, profit factor, worst cycle, losses per 10."""
    n = len(pips)
    if not n:
        return {"n": 0, "wr": None, "exp": None, "pf": None, "worst": None,
                "loss_per_10": None, "net": 0.0}
    wins = [p for p in pips if p > 0]
    losses = [p for p in pips if p <= 0]
    gl = -sum(losses)
    return {"n": n, "wr": len(wins) / n, "exp": sum(pips) / n,
            "pf": (sum(wins) / gl) if gl > 0 else float("inf"),
            "worst": min(pips), "loss_per_10": 10 * len(losses) / n,
            "net": sum(pips)}


def meets(s: dict, floor: dict) -> bool:
    return (s["n"] > 0 and s["wr"] >= floor["wr"] and s["exp"] >= floor["exp_pips"]
            and s["pf"] >= floor["pf"] and s["worst"] >= floor["worst_pips"])


def window(cycles: list, n: int) -> list:
    """Pips of the last n COMPLETED cycles, oldest first (by end time)."""
    done = sorted((c for c in cycles or [] if c.get("end") and c.get("pips") is not None),
                  key=lambda c: c["end"])
    return [float(c["pips"]) for c in done[-n:]]


def fmt(s: dict) -> str:
    if not s["n"]:
        return "0 cycles"
    pf = "inf" if s["pf"] == float("inf") else f"{s['pf']:.1f}"
    return (f"{s['n']} cycles wr={s['wr']*100:.0f}% {s['exp']:+.1f}p/cyc "
            f"pf={pf} worst={s['worst']:+.1f}p")


def verdict(status: str, cycles: list, cfg: dict) -> tuple:
    """(action, reason) for one seated setup. action: KEEP | DEMOTE | GRADUATE."""
    c = merged(cfg)
    s = cycle_stats(window(cycles, int(c["window_cycles"])))
    if s["n"] and s["worst"] < float(c["tripwire_pips"]):
        return "DEMOTE", f"TRIPWIRE: a cycle hit {s['worst']:+.1f}p (< {c['tripwire_pips']:+.0f}p); {fmt(s)}"
    if s["n"] < int(c["min_cycles"]):
        return "KEEP", f"too few to judge ({fmt(s)}; needs {c['min_cycles']})"
    if not meets(s, c["stay"]):
        return "DEMOTE", f"below STAY floor: {fmt(s)}"
    if status == "PROBE":
        if meets(s, c["enter"]):
            return "GRADUATE", f"meets the top-5 standard: {fmt(s)}"
        if s["n"] >= int(c["max_probe_cycles"]):
            return "DEMOTE", f"PROBE limit {c['max_probe_cycles']} cycles without the standard: {fmt(s)}"
    return "KEEP", f"holds the standard: {fmt(s)}"


def broker_veto(cycles: list, cfg: dict) -> bool:
    """Real fills outrank the simulator: a SHADOW whose own broker cycles
    (last window) hit the tripwire, net negative, or fail STAY at a judgeable
    sample may not audition."""
    c = merged(cfg)
    s = cycle_stats(window(cycles, int(c["window_cycles"])))
    if not s["n"]:
        return False
    if s["worst"] < float(c["tripwire_pips"]) or s["net"] < 0:
        return True
    return s["n"] >= int(c["min_cycles"]) and not meets(s, c["stay"])


def pick_auditions(candidates: list, open_slots: int, cfg: dict) -> list:
    """Choose SHADOWs for 0.20x PROBE auditions on real fills.

    candidates: dicts {key, side, sim_cycles, sim_wr, sim_net, cooldown, strikes_ok,
    pair_side_seated, broker_cycles}. The simulator only ORDERS the queue (it
    cannot prove anything); real fills decide every promotion after that, and
    a candidate's own past real fills veto it (see broker_veto).
    """
    c = merged(cfg)
    if open_slots <= 0:
        return []
    ok = [x for x in candidates
          if x.get("strikes_ok") and not x.get("cooldown") and not x.get("pair_side_seated")
          and (x.get("sim_cycles") or 0) >= int(c["audition_min_sim_cycles"])
          and (x.get("sim_wr") or 0) >= float(c["audition_min_sim_wr"])
          and (x.get("sim_net") or 0) > 0
          and not broker_veto(x.get("broker_cycles") or [], c)]
    ok.sort(key=lambda x: -(x["sim_net"]))
    out, taken = [], set()
    for x in ok:
        ps = (x["key"][0], x.get("side"))
        if ps in taken:
            continue
        out.append(x)
        taken.add(ps)
        if len(out) >= max(0, open_slots):
            break
    return out
