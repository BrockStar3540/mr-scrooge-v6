"""core/family_cycle.py — family-cycle-v3 virtual replay (charter, 2026-07-31).

One completed GRID FAMILY CYCLE is the unit of evidence: a parent selection
event, the grid it arms, every popper that grid fires (with re-arms), walked
over executable bid/ask candles under the LIVE mechanics until the grid
retires flat — no artificial horizon. A cycle still open when data ends is
CENSORED, never an outcome.

Mechanics mirrored from the live modules (rule sources cited inline):
  * ratchet: floor-step lock, step/cadence from exit_config — live 2p/0.5min
    means every M5 bar (modules/management/ratchet.py, core/shadow_execution)
  * markers fire on MID crossing measured from the grid anchor (= the
    parent's executable entry, party_package.on_parent_open); re-arm when
    mid re-crosses to the favorable side (tick() crossed_back); one popper
    per marker while open
  * fire gate: max_total_trades cap (book-wide margin caps are out of scope
    for a single-family replay)
  * grid retirement: family flat AND (mid back above the shallowest marker
    OR grid age > grid_max_age_days) (tick() retire rule)
  * executable prices: long manages/exits at BID, short at ASK; entries pay
    the spread (parent enters at ask-open for longs; poppers at marker mid
    plus half-spread)
  * worst-case bar ordering: stops before fires before locks
    (shadow_execution adverse-first doctrine)

Variants:
  FAMILY_PP   — parent + the full popper grid (the live system)
  PARENT_ONLY — parent alone; GridLift = U_family − U_parent

Pure logic, no network: callers feed M5 bid/ask candles
({"bid": {o,h,l,c}, "ask": {o,h,l,c}}, floats or numeric strings).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

BAR_MIN = 5.0


def floor_step_lock(peak: float, trigger: float, step: float,
                    trail: float) -> Optional[float]:
    """The live ratchet's lock level (ratchet.py / shadow_execution.py)."""
    if peak < trigger:
        return None
    return math.floor((peak - trigger) / step) * step + trigger - trail


@dataclass
class _Leg:
    kind: str                   # "parent" | "popper"
    marker: float               # 0.0 for the parent
    entry: float                # executable entry price (spread paid)
    sl_pips: float
    trigger: float
    trail: float
    step: float
    born_bar: int = -1          # bar index the leg was created on
    lock: Optional[float] = None    # profit-direction pips; None = initial SL
    peak: float = 0.0
    done: bool = False
    net: float = 0.0
    exit_reason: str = ""


@dataclass
class CycleResult:
    censored: bool
    net_pips: float             # completed legs only; censored => open legs excluded
    parent_net: float
    harvest: float              # popper contribution
    n_poppers: int
    n_refires: int              # fires at a marker that had already fired (re-arms)
    peak_liability_pips: float  # worst sum of stops-execute losses while open
    duration_min: float
    open_legs: int              # >0 only when censored
    legs: list = field(default_factory=list)


def _f(x) -> float:
    return float(x)


def replay_family_cycle(bars: list, side: str, pip: float,
                        parent_gear: dict, pp_cfg: dict,
                        variant: str = "FAMILY_PP",
                        max_total_trades: int = 8) -> Optional[CycleResult]:
    if side not in ("long", "short") or len(bars) < 2:
        return None
    sgn = 1 if side == "long" else -1
    try:
        entry = _f(bars[0]["ask" if side == "long" else "bid"]["o"])
    except (KeyError, TypeError, ValueError):
        return None

    step = _f(parent_gear.get("step_size_pips", 2.0) or 2.0)
    parent = _Leg("parent", 0.0, entry,
                  _f(parent_gear.get("sl_pips", 60.0) or 60.0),
                  _f(parent_gear.get("trigger_pips", 8.5) or 8.5),
                  _f(parent_gear.get("trail_pips", 2.5) or 2.5), step)
    legs = [parent]
    anchor = entry                       # pp anchors the grid at the parent entry
    markers = (sorted(_f(m) for m in pp_cfg.get("marker_pips", []))
               if variant == "FAMILY_PP" else [])
    marker_px = {m: anchor - sgn * m * pip for m in markers}
    armed = {m: True for m in markers}
    open_at: dict = {m: None for m in markers}
    fired = set()
    pp_sl = _f(pp_cfg.get("sl_pips", 60.0))
    pp_trig = _f(pp_cfg.get("trigger_pips", 8.5))
    pp_trail = _f(pp_cfg.get("trail_pips", 2.5))
    pp_step = _f(pp_cfg.get("step_size_pips", step) or step)
    max_age_bars = _f(pp_cfg.get("grid_max_age_days", 7.0)) * 1440.0 / BAR_MIN
    n_refires = 0
    peak_liab = 0.0

    def liability() -> float:
        return sum(max(0.0, -(u.lock if u.lock is not None else -u.sl_pips))
                   for u in legs if not u.done)

    def result(censored: bool, bars_used: int) -> CycleResult:
        done = [u for u in legs if u.done]
        pn = sum(u.net for u in done if u.kind == "parent")
        hv = sum(u.net for u in done if u.kind == "popper")
        return CycleResult(
            censored=censored, net_pips=round(pn + hv, 2),
            parent_net=round(pn, 2), harvest=round(hv, 2),
            n_poppers=sum(1 for u in legs if u.kind == "popper"),
            n_refires=n_refires,
            peak_liability_pips=round(peak_liab, 1),
            duration_min=bars_used * BAR_MIN,
            open_legs=sum(1 for u in legs if not u.done),
            legs=[{"kind": u.kind, "marker": u.marker,
                   "net": round(u.net, 2) if u.done else None,
                   "reason": u.exit_reason, "done": u.done} for u in legs])

    for i, bar in enumerate(bars):
        try:
            b, a = bar["bid"], bar["ask"]
            ex_h, ex_l = (_f(b["h"]), _f(b["l"])) if sgn > 0 else (_f(a["h"]), _f(a["l"]))
            ex_c = _f(b["c"]) if sgn > 0 else _f(a["c"])
            m_h = (_f(b["h"]) + _f(a["h"])) / 2.0
            m_l = (_f(b["l"]) + _f(a["l"])) / 2.0
            m_c = (_f(b["c"]) + _f(a["c"])) / 2.0
            half_spread = abs(_f(a["o"]) - _f(b["o"])) / 2.0
        except (KeyError, TypeError, ValueError):
            continue
        adverse_exec = ex_l if sgn > 0 else ex_h
        favor_exec = ex_h if sgn > 0 else ex_l
        adverse_mid = m_l if sgn > 0 else m_h
        favor_mid = m_h if sgn > 0 else m_l

        # liability high-water at bar START — a leg that dies on this very
        # bar was still RISKING its full stop coming into it; measuring
        # after the stop check erased first-bar deaths from the denominator
        peak_liab = max(peak_liab, liability())
        # 1) stops first — worst case within the bar
        for u in legs:
            if u.done:
                continue
            stop_level = u.lock if u.lock is not None else -u.sl_pips
            worst = sgn * (adverse_exec - u.entry) / pip
            if worst <= stop_level:
                u.net, u.done = round(stop_level, 2), True
                u.exit_reason = "stop" if u.lock is not None else "initial_stop"
                for m, leg in open_at.items():
                    if leg is u:
                        open_at[m] = None
        # 2) marker machinery (mid-based, from the anchor)
        for m in markers:
            px = marker_px[m]
            if open_at[m] is not None:
                continue
            crossed_back = (favor_mid > px) if sgn > 0 else (favor_mid < px)
            crossed_into = (adverse_mid <= px) if sgn > 0 else (adverse_mid >= px)
            if not armed[m]:
                if crossed_back:
                    armed[m] = True
                continue
            if not crossed_into:
                continue
            if sum(1 for u in legs if not u.done) >= max_total_trades:
                continue
            pop = _Leg("popper", m, px + sgn * half_spread,
                       pp_sl, pp_trig, pp_trail, pp_step, born_bar=i)
            legs.append(pop)
            if m in fired:
                n_refires += 1
            fired.add(m)
            open_at[m] = pop
            armed[m] = False
        # liability high-water AFTER fires, BEFORE locks: the stacked
        # unlocked exposure is exactly what the family risks at this moment
        peak_liab = max(peak_liab, liability())
        # 3) peaks + floor-step locks (0.5-min cadence => every M5 bar).
        # A leg BORN this bar must not inherit the bar's earlier favorable
        # extreme — it fired on the way down; the high preceded it. Its
        # first peak reads from the bar CLOSE only (pessimistic, matching
        # the worst-case adverse-first doctrine).
        for u in legs:
            if u.done:
                continue
            fav = sgn * ((ex_c if u.born_bar == i else favor_exec) - u.entry) / pip
            if fav > u.peak:
                u.peak = fav
            new_lock = floor_step_lock(u.peak, u.trigger, u.step, u.trail)
            if new_lock is not None and (u.lock is None or new_lock > u.lock):
                u.lock = new_lock
        # 4) retirement check
        peak_liab = max(peak_liab, liability())
        if all(u.done for u in legs):
            if not markers:
                return result(False, i + 1)
            shallowest = marker_px[min(markers)]
            back_in_zone = (m_c > shallowest) if sgn > 0 else (m_c < shallowest)
            if back_in_zone or i >= max_age_bars:
                return result(False, i + 1)

    # data exhausted: flat = complete (retirement pending is bookkeeping,
    # the economics are final); any open leg = CENSORED
    return result(censored=not all(u.done for u in legs), bars_used=len(bars))
