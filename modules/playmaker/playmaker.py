"""modules/playmaker/playmaker.py — Selects the best trade from active pair tickets.

The playmaker receives one PairTicket per active pair (already stamped by direction
and momentum modules) and picks the highest-quality setup to fire.

CERTAINTY FLOORS — derived from dm_04 raw factor sweep (not exit-management calibrated):

  MIN_DIRECTION_SCORE = 0.25
    The direction module emits "block" at |score| < 0.15.  Score 0.15–0.25 is
    technically non-block but directionally weak (D6-D7 territory on primary
    indicator with poor supporting signal).  0.25+ means the weighted factor
    composite is committed to a side with meaningful conviction.

  MIN_DIR_CERTAINTY = 0.30
    Certainty = factor_extremity × (0.4 + 0.6 × agreement).
    From dm_04: h1_ret_1bar at D9 (norm≈0.85) + 4 supporting factors at D7
    (norm≈0.45) → certainty ≈ 0.30.  Below that, the signal is not consistently
    above the noise floor established by the sweep.  The is_actionable property
    in PairTicket already gates on certainty > 0.25; this adds the stricter
    playmaker-level bar.

  MIN_MOM_CERTAINTY = 0.25
    Momentum certainty 0.25 = ATR is at least 25% of the way from the center of
    the normal regime toward a boundary (low/normal or normal/high).  Below 0.25
    the vol regime is ambiguous and expected_pips estimates are unreliable.

BEST-EDGE PRIORITY when multiple pairs pass all gates simultaneously:
  Primary rank:   abs(composite_score) = abs(direction.score) × dir_certainty × mom_certainty
  Secondary rank: expected_pips        — higher-magnitude setup wins on ties
  This means a moderately strong signal with high dual-certainty beats a raw
  signal with middling certainties, which is the correct preference.
"""
from __future__ import annotations
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from ..signals.base import PairTicket
from config.pairs import PAIR_SESSIONS
from . import lock_guard



# ── Live config (PLAYMAKER tab) ──────────────────────────────────────────────
import json as _json
from pathlib import Path as _Path
_PM_CONFIG_PATH = _Path(__file__).resolve().parents[2] / "config" / "playmaker_config.json"
_PM_DEFAULTS = {
    "enabled":             True,
    "min_direction_score": 0.25,
    "min_dir_certainty":   0.30,
    "min_mom_certainty":   0.25,
    "cooldown_after_sl_min": 0.0,
    "profile_shadow_enabled": True,
}
_PM_ACCT_DEFAULTS = {
    "margin_pct_per_trade":  0.005,   # fraction of BALANCE used as margin per trade
    "max_concurrent_trades": 3,
    "max_per_currency_direction": 1,  # max concurrent same-sign positions per CURRENCY
}

def _pm_load() -> dict:
    """Return {"account":..., "defaults":..., "per_pair":..., "disabled_cells":...} with safe fallbacks."""
    try:
        raw = _json.loads(_PM_CONFIG_PATH.read_text())
        acct = dict(raw.get("account") or {})
        if "margin_pct_per_trade" not in acct and "risk_pct_per_trade" in acct:
            acct["margin_pct_per_trade"] = acct.pop("risk_pct_per_trade")
        # disabled_cells: list of [pair, session, direction] triples → frozenset of tuples
        dc_raw = raw.get("disabled_cells") or []
        dc = frozenset(tuple(x) for x in dc_raw if len(x) == 3)
        # inverted_shadow_cells: list of [pair, session] pairs → frozenset of tuples
        isc_raw = raw.get("inverted_shadow_cells") or []
        isc = frozenset(tuple(x) for x in isc_raw if len(x) == 2)
        # inverted_live_cells: list of [pair, session] pairs → frozenset of tuples
        # When the winning ticket's (pair, session) is in this set, the trade direction
        # is FLIPPED before execution (long signal → short trade, short signal → long).
        ilc_raw = raw.get("inverted_live_cells") or []
        ilc = frozenset(tuple(x) for x in ilc_raw if len(x) == 2)
        # inverted_live_directions: list of [pair, session, native_direction] triples →
        # frozenset of tuples.  When the winning candidate's (pair, session, NATIVE bias)
        # is in this set, the executed trade direction is flipped — exactly like cell-level
        # inversion but scoped to one native direction.
        # Interaction rule: effective_inverted = cell_level_inverted XOR direction_level_inverted.
        # In practice these should not be combined on the same (pair, session).
        ild_raw = raw.get("inverted_live_directions") or []
        ild = frozenset(tuple(x) for x in ild_raw if len(x) == 3)
        # random_pick: when True, pick_best randomizes among actionable candidates
        # instead of ranking by |composite_score|. Used to spread fire rate across
        # cells while we collect per-cycle ticket data to evaluate alternative rankings.
        random_pick = bool(raw.get("random_pick", False))
        # per_cell_mom_cert_max: dict of "pair/session" -> float CEILING on m_cert.
        # Brock reframe 2026-06-23: low m_cert predicts BIG directional moves; high
        # m_cert predicts small contained moves. For cells whose edge IS the big-move
        # tail, block trades where m_cert exceeds the ceiling (keep only big-move setups).
        # First use: AUD_JPY/asia ceiling 0.50 (5 of 6 trades there had m_cert <= 0.50,
        # and the inverted-mistake losses showed low m_cert + big move dynamic).
        pcmm_raw = raw.get("per_cell_mom_cert_max") or {}
        per_cell_mom_cert_max = {tuple(k.split("/")): float(v) for k, v in pcmm_raw.items()
                                  if "/" in k and len(k.split("/")) == 2}
        # per_cell_mom_cert_min: dict of "pair/session" -> float FLOOR on m_cert.
        # Mirror of the ceiling. Used for cells where the OPPOSITE pattern holds:
        # high m_cert → big MFE (the move is contained AND directional). Block
        # trades below the floor so only high-conviction setups fire.
        # First use: GBP_USD/ny floor 0.40 (Brock obs: 9186 m_cert 0.39 won only +6p;
        # 9148/9159/9170/9176 m_cert 0.41-0.84 all bigger MFEs 9.3-13.8p).
        pcmn_raw = raw.get("per_cell_mom_cert_min") or {}
        per_cell_mom_cert_min = {tuple(k.split("/")): float(v) for k, v in pcmn_raw.items()
                                  if "/" in k and len(k.split("/")) == 2}
        # per_cell_dir_cert_min: dict of "pair/session" -> float FLOOR on d_cert.
        # 2026-06-24 deep-dive on GBP_USD/ny inverted (n=11): both losses had d_cert
        # 0.49/0.50, 8 of 9 winners had d_cert >= 0.54 (one win at 0.49). Clean gap at
        # 0.51-0.53. Floor 0.52 catches both losses, costs 1 winning trade — net
        # +31.45p over n=11. Mirror of per_cell_mom_cert_min on direction certainty.
        pcdn_raw = raw.get("per_cell_dir_cert_min") or {}
        per_cell_dir_cert_min = {tuple(k.split("/")): float(v) for k, v in pcdn_raw.items()
                                  if "/" in k and len(k.split("/")) == 2}
        # per_cell_dir_cert_max: dict of "pair/session" -> float CEILING on d_cert.
        # Mirror of per_cell_dir_cert_min. Used with min for range filters when only
        # mid-range direction conviction works for the cell (extremes go either way).
        # 2026-06-25 first use: USD_CHF/ny + USD_CHF/london = 0.55 (paired with min 0.35).
        pcdx_raw = raw.get("per_cell_dir_cert_max") or {}
        per_cell_dir_cert_max = {tuple(k.split("/")): float(v) for k, v in pcdx_raw.items()
                                  if "/" in k and len(k.split("/")) == 2}
        # per_cell_willr_range: dict of "pair/session/direction" -> [min, max] on willr_m5.
        # 2026-06-23 backtest finding (EUR_JPY/ny/short): willr in [-85, -7] gives
        # +8.48p/70.2% WR vs baseline +6.95p/64.8% (1999 V5-actionable bars).
        # Per (pair, session, direction) granularity since willr behavior is direction-asymmetric.
        pcwr_raw = raw.get("per_cell_willr_range") or {}
        per_cell_willr_range = {}
        for k, v in pcwr_raw.items():
            parts = k.split("/")
            if len(parts) == 3 and isinstance(v, (list, tuple)) and len(v) == 2:
                per_cell_willr_range[tuple(parts)] = (float(v[0]), float(v[1]))
        # per_cell_kc_up_range: dict of "pair/session/direction" -> [min, max] on kc_up_dist_pips.
        # 2026-06-23 backtest finding (AUD_USD/london/short): kc_up in [-15, 0] gives
        # +4.22p/69% WR vs baseline +2.86p/65% on 1120 V5-actionable bars. Deep-below
        # bucket kc_up < -20 was a LOSING zone (-4.02p mean, 54% WR).
        pckur_raw = raw.get("per_cell_kc_up_range") or {}
        per_cell_kc_up_range = {}
        for k, v in pckur_raw.items():
            parts = k.split("/")
            if len(parts) == 3 and isinstance(v, (list, tuple)) and len(v) == 2:
                per_cell_kc_up_range[tuple(parts)] = (float(v[0]), float(v[1]))
        # per_cell_aroon_range: dict of "pair/session/direction" -> [min, max] on aroonosc_h1.
        # 2026-07-02 backtest finding (USD_CAD/london/short): aroonosc_h1 <= -85 separates
        # dead trade 9724 (aroon -57) from winners (aroon -86); [lo, hi] gate mirrors
        # per_cell_willr_range exactly (same JSON encoding, same gate placement).
        pcar_raw = raw.get("per_cell_aroon_range") or {}
        per_cell_aroon_range = {}
        for k, v in pcar_raw.items():
            parts = k.split("/")
            if len(parts) == 3 and isinstance(v, (list, tuple)) and len(v) == 2:
                per_cell_aroon_range[tuple(parts)] = (float(v[0]), float(v[1]))
        return {
            "account":         {**_PM_ACCT_DEFAULTS, **acct},
            "defaults":        {**_PM_DEFAULTS,      **(raw.get("defaults") or {})},
            "per_pair":        raw.get("per_pair") or {},
            "disabled_cells":  dc,
            "inverted_shadow_cells": isc,
            "inverted_live_cells":   ilc,
            "inverted_live_directions": ild,
            "random_pick":     random_pick,
            "per_cell_mom_cert_max": per_cell_mom_cert_max,
            "per_cell_mom_cert_min": per_cell_mom_cert_min,
            "per_cell_dir_cert_min": per_cell_dir_cert_min,
            "per_cell_dir_cert_max": per_cell_dir_cert_max,
            "per_cell_willr_range":  per_cell_willr_range,
            "per_cell_kc_up_range":  per_cell_kc_up_range,
            "per_cell_aroon_range":  per_cell_aroon_range,
        }
    except Exception:
        return {"account": dict(_PM_ACCT_DEFAULTS), "defaults": dict(_PM_DEFAULTS),
                "per_pair": {}, "disabled_cells": frozenset(),
                "inverted_shadow_cells": frozenset(),
                "inverted_live_cells":   frozenset(),
                "inverted_live_directions": frozenset(),
                "random_pick":     False,
                "per_cell_mom_cert_max": {},
                "per_cell_mom_cert_min": {},
                "per_cell_dir_cert_min": {},
                "per_cell_dir_cert_max": {},
                "per_cell_willr_range":  {},
                "per_cell_kc_up_range":  {},
                "per_cell_aroon_range":  {}}

def _pm_for_pair(cfg: dict, pair: str) -> dict:
    eff = dict(cfg["defaults"])
    eff.update(cfg["per_pair"].get(pair) or {})
    return eff

def pm_margin_pct() -> float:
    """Fraction of BALANCE used as margin per trade (V1 model)."""
    return float(_pm_load()["account"]["margin_pct_per_trade"])

def pm_adaptive_selector() -> bool:
    """ExecutionScore RANKING on/off (account.adaptive_selector_enabled,
    default False — external review 2026-07-31: diagnostic-only until a true
    candidate-set walk-forward validates it; scores are always LOGGED)."""
    try:
        return bool(_pm_load()["account"].get("adaptive_selector_enabled", False))
    except Exception:
        return False


def pm_probe_mult() -> float:
    """PROBE-seat sizing multiplier (fraction of the normal margin_pct).
    Config: account.probe_sizing_mult, default 0.33 (charter, 2026-07-31)."""
    try:
        return float(_pm_load()["account"].get("probe_sizing_mult", 0.33))
    except Exception:
        return 0.33

# Back-compat alias
pm_risk_pct = pm_margin_pct

def pm_max_concurrent() -> int:
    return int(_pm_load()["account"]["max_concurrent_trades"])

def pm_max_per_currency_direction() -> int:
    """Max concurrent open positions exposing the same (currency, sign).

    2026-07-02 panel-unanimous risk cap: the engine held three long-yen-pair
    positions into a JPY crash — one macro bet at 3x size. A position exposes
    two currencies with opposite signs (long BASE_QUOTE = long BASE + short
    QUOTE); this caps how many open positions may share any single exposure."""
    return int(_pm_load()["account"]["max_per_currency_direction"])

def _currency_legs(pair: str, direction: str) -> tuple[tuple[str, str], tuple[str, str]]:
    """The two (currency, sign) exposures of a position.

    long BASE_QUOTE  = long BASE + short QUOTE
    short BASE_QUOTE = short BASE + long QUOTE"""
    base, quote = pair.split("_")
    if direction == "long":
        return ((base, "long"), (quote, "short"))
    return ((base, "short"), (quote, "long"))

def currency_exposure(open_positions) -> dict[tuple[str, str], int]:
    """(currency, sign) -> count of open positions carrying that exposure.

    open_positions: iterable of (pair, direction) tuples, direction = traded
    direction ("long"|"short"). Also surfaced on /api/state for the dashboard."""
    exp: dict[tuple[str, str], int] = {}
    for pair, direction in (open_positions or []):
        for leg in _currency_legs(pair, direction):
            exp[leg] = exp.get(leg, 0) + 1
    return exp

def pm_inverted_shadow_cells() -> frozenset:
    """(pair, session) cells whose signal stream is shadow-logged for invert evaluation."""
    return _pm_load().get("inverted_shadow_cells", frozenset())

def pm_inverted_live_cells() -> frozenset:
    """(pair, session) cells whose live trade direction is FLIPPED at execution."""
    return _pm_load().get("inverted_live_cells", frozenset())

def pm_random_pick() -> bool:
    """True when pick_best randomizes among actionable candidates."""
    return bool(_pm_load().get("random_pick", False))

def pm_profile_shadow_enabled() -> bool:
    """True when the corrected-profile shadow dual-stamp logs SHADOW_PROFILE lines.

    2026-07-02: engine stamps every scanned bar through a SECOND direction stack
    built from the 2026-audit corrected profile assignment (mostly reversion) —
    logging only, execution unchanged. See modules/signals/profile_shadow.py."""
    return bool(_pm_load()["defaults"].get("profile_shadow_enabled", True))

def pm_calibration_log_enabled() -> bool:
    """True when CAL lines are emitted each scan cycle (kill-switch, hot-reload).

    Logging only -- no gating, no change to entries or exits.
    See modules/signals/calibration.py and config/cell_calibration.json."""
    return bool(_pm_load()["defaults"].get("calibration_log_enabled", True))

def pm_formula_shadow_enabled() -> bool:
    """True when FORMULA shadow stamps are logged each scan cycle (kill-switch, hot-reload).

    Logging only -- no gating, no change to entries or exits.
    See modules/signals/formula_shadow.py and research/tools/formula_shadow_score.py."""
    return bool(_pm_load()["defaults"].get("formula_shadow_enabled", True))

def pm_cell_shadow_enabled() -> bool:
    """True when CELLSHADOW stamps are emitted each scan cycle (kill-switch, hot-reload).

    Logging only -- execution unchanged until CELL_EXECUTION_ENABLED=True.
    See modules/cells/ and research/tools/cell_setup_score.py."""
    return bool(_pm_load()["defaults"].get("cell_shadow_enabled", True))

# ── Certainty floors (dm_04-derived, see module docstring) ──────────────────
MIN_DIRECTION_SCORE = 0.25   # |direction.score| minimum
MIN_DIR_CERTAINTY   = 0.30   # direction.certainty minimum
MIN_MOM_CERTAINTY   = 0.25   # momentum.certainty minimum

# ── Position and spread limits ───────────────────────────────────────────────
# MAX_OPEN_POSITIONS deleted 2026-07-03 — was unused; position limit is
# max_concurrent_trades in playmaker_config.json / _PM_ACCT_DEFAULTS["max_concurrent_trades"].
# Confirmed zero references in repo before deletion.

# Maximum spread to accept a trade (pips).  Above these levels the spread
# consumes too much of the expected edge.
# GATE SEMANTICS (2026-07-03 fix): spread_pips <= 0 means a pricing hiccup
# (bid==ask or feed glitch) — treated as GATE FAILURE (candidate skipped) so a
# zero-spread anomaly cannot bypass the protection. The feed (core/feed/oanda.py)
# always populates spread_pips = (ask-bid)/pip from a live OANDA pricing call;
# 0.0 only occurs if OANDA returns identical bid/ask, which is a bad tick.
# Rate-limit tracker for spread=0 warnings (pair → last warning monotonic time)
_SPREAD_WARN_TS: dict[str, float] = {}

_MAX_SPREAD: dict[str, float] = {
    "EUR_USD": 2.5,
    "GBP_USD": 3.0,
    "USD_JPY": 2.0,
    "AUD_USD": 2.5,
    "USD_CAD": 3.0,
    "USD_CHF": 3.0,
    "EUR_JPY": 3.5,
    "AUD_JPY": 4.0,
}
_DEFAULT_MAX_SPREAD = 3.0


@dataclass
class TradeTicket:
    """What the playmaker emits — consumed by trade management, not signal modules."""
    pair:          str
    session:       str
    direction:     str     # "long" | "short"
    score:         float   # composite_score at fire time
    dir_certainty: float   # direction module certainty
    mom_certainty: float   # momentum module certainty
    vol_regime:    str     # from momentum stamp
    expected_pips: float   # from momentum stamp
    timestamp:     datetime
    reads:         dict    # direction.reads + momentum.reads for logging/debug
    rivals:        int = 0 # how many other candidates passed all gates this cycle
    inverted_live: bool = False  # True when direction was flipped by inverted_live_cells
    cell:          object = None  # CellIntent when engine=cell_v1 (Phase D); None on recovery stubs


def _passes_gates(t: PairTicket, pcfg: dict) -> bool:
    """All certainty + spread gates the playmaker requires (beyond is_actionable).
    pcfg: per-pair effective config (defaults + override) from _pm_for_pair()."""
    d, m = t.direction, t.momentum

    if not pcfg.get("enabled", True):
        return False
    if not t.is_actionable:
        return False
    if abs(d.score) < float(pcfg["min_direction_score"]):
        return False
    if d.certainty < float(pcfg["min_dir_certainty"]):
        return False
    if m.certainty < float(pcfg["min_mom_certainty"]):
        return False
    # Spread gate: skip candidate on bad tick (spread_pips <= 0) or excessive spread.
    # A zero/negative spread = pricing hiccup, not "feed not yet live" — the feed
    # always provides a real spread from OANDA. Fail CLOSED on anomalies.
    if t.spread_pips <= 0.0:
        import logging as _logging
        _spread_log = _logging.getLogger("v5.playmaker")
        # Rate-limit: one warning per pair per 5 minutes (use module-level dict)
        _now = time.monotonic()
        _last = _SPREAD_WARN_TS.get(t.pair, 0.0)
        if _now - _last >= 300.0:
            _SPREAD_WARN_TS[t.pair] = _now
            _spread_log.warning(
                "spread=0 for %s — pricing hiccup? candidate skipped", t.pair
            )
        return False
    max_spread = _MAX_SPREAD.get(t.pair, _DEFAULT_MAX_SPREAD)
    if t.spread_pips > max_spread:
        return False
    return True

def _edge_rank(t: PairTicket) -> tuple:
    """Higher is better.  Primary: composite magnitude.  Secondary: expected move."""
    return (abs(t.composite_score), t.momentum.expected_pips)


def pick_best(
    tickets:       list[PairTicket],
    hour_utc:      int,
    open_pairs:    set[str],
    max_positions: Optional[int] = None,
    now:           Optional[datetime] = None,
    sl_history:    Optional[dict] = None,
    cell_opens:    Optional[dict] = None,
    open_positions: Optional[list] = None,
) -> Optional[TradeTicket]:
    """Select the best-edge trade ticket from active pair tickets.

    open_positions: list of (pair, direction) tuples for currently open trades —
    feeds the per-currency directional exposure cap (max_per_currency_direction).
    open_pairs is kept alongside for compatibility (position limit + 1-per-pair).

    Returns None when:
      - position limit is already reached (max_concurrent_trades from playmaker config), or
      - no ticket passes per-pair certainty + spread gates, or
      - pair is under cooldown after a recent losing exit, or
      - every remaining candidate is excluded by the per-currency exposure cap.

    When multiple tickets pass (group arrival), picks the one with the highest
    abs(composite_score), breaking ties by expected_pips.
    """
    pm = _pm_load()
    max_positions = int(max_positions if max_positions is not None
                        else pm["account"]["max_concurrent_trades"])
    if len(open_pairs) >= max_positions:
        return None

    # Step 1: session + position + enabled + cooldown
    # For LOCKED cells, every gate is resolved from the frozen governance snapshot
    # instead of live config; drift is logged once per hour per field.
    eligible = []
    for t in tickets:
        if t.pair in open_pairs:
            continue

        # ── Lock guard: load frozen governance for this (pair, session) ───────
        gov = lock_guard.locked_governance(t.pair, t.session)

        # Session eligibility
        if gov is not None:
            _gov_sess_en = gov.get("session_enabled", True)
            _live_sess_en = t.session in PAIR_SESSIONS.get(t.pair, [])
            if _live_sess_en != _gov_sess_en:
                lock_guard.log_drift(t.pair, t.session, "session_enabled",
                                     _live_sess_en, _gov_sess_en)
            if not _gov_sess_en:
                continue
        else:
            if t.session not in PAIR_SESSIONS.get(t.pair, []):
                continue

        pcfg = _pm_for_pair(pm, t.pair)

        # Per-pair enabled
        if not pcfg.get("enabled", True):
            continue

        # Disabled-cell check (uses NATIVE direction, before any inversion)
        if gov is not None:
            _gov_dis = gov.get("disabled_long" if t.direction.bias == "long" else "disabled_short", False)
            _live_dis = (t.pair, t.session, t.direction.bias) in pm.get("disabled_cells", frozenset())
            if _live_dis != _gov_dis:
                lock_guard.log_drift(t.pair, t.session,
                                     f"disabled_{t.direction.bias}", _live_dis, _gov_dis)
            if _gov_dis:
                continue
        else:
            # 2026-06-21 Master Matrix: per-cell disable for cells with negative ML edge + no live evidence
            if (t.pair, t.session, t.direction.bias) in pm.get("disabled_cells", frozenset()):
                continue

        # m_cert CEILING gate
        if gov is not None:
            _gov_mcmax = gov.get("mom_cert_max")
            _live_mcmax = pm.get("per_cell_mom_cert_max", {}).get((t.pair, t.session))
            if _gov_mcmax != _live_mcmax:
                lock_guard.log_drift(t.pair, t.session, "mom_cert_max", _live_mcmax, _gov_mcmax)
            if _gov_mcmax is not None and t.momentum.certainty > _gov_mcmax:
                continue
        else:
            # 2026-06-23 per-cell m_cert CEILING (Brock reframe): block trades with m_cert
            # above the cell's ceiling. Low m_cert = big-move setup; high m_cert = small
            # contained move. For cells whose edge IS the big-move tail, filter out the
            # small-move trades that would dilute the cell's average.
            _pcmm = pm.get("per_cell_mom_cert_max", {})
            _cell_max = _pcmm.get((t.pair, t.session))
            if _cell_max is not None and t.momentum.certainty > _cell_max:
                continue

        # m_cert FLOOR gate
        if gov is not None:
            _gov_mcmin = gov.get("mom_cert_min")
            _live_mcmin = pm.get("per_cell_mom_cert_min", {}).get((t.pair, t.session))
            if _gov_mcmin != _live_mcmin:
                lock_guard.log_drift(t.pair, t.session, "mom_cert_min", _live_mcmin, _gov_mcmin)
            if _gov_mcmin is not None and t.momentum.certainty < _gov_mcmin:
                continue
        else:
            # 2026-06-23 per-cell m_cert FLOOR: mirror of above for cells where the pattern
            # is opposite (high m_cert correlates with big MFE). Block low-cert trades so
            # only high-conviction setups fire.
            _pcmn = pm.get("per_cell_mom_cert_min", {})
            _cell_min = _pcmn.get((t.pair, t.session))
            if _cell_min is not None and t.momentum.certainty < _cell_min:
                continue

        # d_cert FLOOR gate
        if gov is not None:
            _gov_dcmin = gov.get("dir_cert_min")
            _live_dcmin = pm.get("per_cell_dir_cert_min", {}).get((t.pair, t.session))
            if _gov_dcmin != _live_dcmin:
                lock_guard.log_drift(t.pair, t.session, "dir_cert_min", _live_dcmin, _gov_dcmin)
            if _gov_dcmin is not None and t.direction.certainty < _gov_dcmin:
                continue
        else:
            # 2026-06-24 per-cell d_cert FLOOR: mirror on direction certainty.
            # First use: GBP_USD/ny=0.52 (both n=11 inverted losses had d_cert 0.49/0.50;
            # 8 of 9 winners had d_cert >= 0.54; clean gap at 0.51-0.53).
            _pcdn = pm.get("per_cell_dir_cert_min", {})
            _cell_dmin = _pcdn.get((t.pair, t.session))
            if _cell_dmin is not None and t.direction.certainty < _cell_dmin:
                continue

        # d_cert CEILING gate
        if gov is not None:
            _gov_dcmax = gov.get("dir_cert_max")
            _live_dcmax = pm.get("per_cell_dir_cert_max", {}).get((t.pair, t.session))
            if _gov_dcmax != _live_dcmax:
                lock_guard.log_drift(t.pair, t.session, "dir_cert_max", _live_dcmax, _gov_dcmax)
            if _gov_dcmax is not None and t.direction.certainty > _gov_dcmax:
                continue
        else:
            # 2026-06-25 per-cell d_cert CEILING: mirror of min for range filters.
            # First use: USD_CHF/ny + london = 0.55 (paired with min 0.35).
            _pcdx = pm.get("per_cell_dir_cert_max", {})
            _cell_dmax = _pcdx.get((t.pair, t.session))
            if _cell_dmax is not None and t.direction.certainty > _cell_dmax:
                continue

        # willr_m5 range gate
        if gov is not None:
            _gov_willr = gov.get(f"willr_range_{t.direction.bias}")  # [lo, hi] or null
            _live_willr = pm.get("per_cell_willr_range", {}).get((t.pair, t.session, t.direction.bias))
            _live_willr_l = list(_live_willr) if _live_willr is not None else None
            if _gov_willr != _live_willr_l:
                lock_guard.log_drift(t.pair, t.session, f"willr_range_{t.direction.bias}",
                                     _live_willr_l, _gov_willr)
            if _gov_willr is not None:
                _willr = getattr(t, "willr_m5", 0.0)
                if _willr < _gov_willr[0] or _willr > _gov_willr[1]:
                    continue
        else:
            # 2026-06-23 per-cell willr_m5 range gate (per pair/session/direction).
            # 2026 backtest finding: EUR_JPY/ny/short willr in [-85, -7] = +8.5p/70% WR
            # vs baseline +6.9p/65% on 1999 V5-actionable bars. Block bars outside the range.
            _pcwr = pm.get("per_cell_willr_range", {})
            _willr_rng = _pcwr.get((t.pair, t.session, t.direction.bias))
            if _willr_rng is not None:
                _willr = getattr(t, "willr_m5", 0.0)
                if _willr < _willr_rng[0] or _willr > _willr_rng[1]:
                    continue

        # kc_up range gate
        if gov is not None:
            _gov_kc = gov.get(f"kc_up_range_{t.direction.bias}")  # [lo, hi] or null
            _live_kc = pm.get("per_cell_kc_up_range", {}).get((t.pair, t.session, t.direction.bias))
            _live_kc_l = list(_live_kc) if _live_kc is not None else None
            if _gov_kc != _live_kc_l:
                lock_guard.log_drift(t.pair, t.session, f"kc_up_range_{t.direction.bias}",
                                     _live_kc_l, _gov_kc)
            if _gov_kc is not None:
                _kc = getattr(t, "kc_up_dist_pips", 0.0)
                if _kc < _gov_kc[0] or _kc > _gov_kc[1]:
                    continue
        else:
            # 2026-06-23 per-cell kc_up_dist_pips range gate (mirror of willr_range).
            # AUD_USD/london/short backtest: kc_up in [-15, 0] = +4.22p/69% WR vs baseline
            # +2.86p/65% on 1120 V5-actionable bars. Deep-below (<-20) is a LOSING zone.
            _pckur = pm.get("per_cell_kc_up_range", {})
            _kc_rng = _pckur.get((t.pair, t.session, t.direction.bias))
            if _kc_rng is not None:
                _kc = getattr(t, "kc_up_dist_pips", 0.0)
                if _kc < _kc_rng[0] or _kc > _kc_rng[1]:
                    continue

        # aroonosc_h1 range gate (per pair/session/direction)
        # 2026-07-02 MAE-flip doctrine (USD_CAD/london/short): aroon <= -85 separates
        # dead trade 9724 (aroon -57) from winners (aroon -86); rival separators
        # kc_up <= -32, efi <= -0.9 tracked. Mirrors per_cell_willr_range exactly.
        if gov is not None:
            _gov_aroon = gov.get(f"aroon_range_{t.direction.bias}")  # [lo, hi] or null
            _live_aroon = pm.get("per_cell_aroon_range", {}).get((t.pair, t.session, t.direction.bias))
            _live_aroon_l = list(_live_aroon) if _live_aroon is not None else None
            if _gov_aroon != _live_aroon_l:
                lock_guard.log_drift(t.pair, t.session, f"aroon_range_{t.direction.bias}",
                                     _live_aroon_l, _gov_aroon)
            if _gov_aroon is not None:
                _aroon = getattr(t, "aroonosc_h1", 0.0)
                if _aroon < _gov_aroon[0] or _aroon > _gov_aroon[1]:
                    continue
        else:
            _pcar = pm.get("per_cell_aroon_range", {})
            _aroon_rng = _pcar.get((t.pair, t.session, t.direction.bias))
            if _aroon_rng is not None:
                _aroon = getattr(t, "aroonosc_h1", 0.0)
                if _aroon < _aroon_rng[0] or _aroon > _aroon_rng[1]:
                    continue

        # Cooldown gate
        if gov is not None:
            _gov_cd = float(gov.get("cooldown_after_sl_min", 0) or 0)
            _live_cd = float(pcfg.get("cooldown_after_sl_min", 0) or 0)
            if _gov_cd != _live_cd:
                lock_guard.log_drift(t.pair, t.session, "cooldown_after_sl_min", _live_cd, _gov_cd)
            cd_min = _gov_cd
        else:
            cd_min = float(pcfg.get("cooldown_after_sl_min", 0) or 0)
        if cd_min > 0 and now is not None and sl_history and t.pair in sl_history:
            elapsed_min = (now - sl_history[t.pair]).total_seconds() / 60.0
            if elapsed_min < cd_min:
                continue

        # Build overridden pcfg for _passes_gates when locked
        if gov is not None:
            pcfg_eff = dict(pcfg)
            for _fld, _gk in (
                ("min_direction_score", "min_direction_score"),
                ("min_dir_certainty",   "min_dir_certainty"),
                ("min_mom_certainty",   "min_mom_certainty"),
            ):
                _gv = gov.get(_gk)
                if _gv is not None and pcfg_eff.get(_fld) != _gv:
                    lock_guard.log_drift(t.pair, t.session, _fld, pcfg_eff.get(_fld), _gv)
                    pcfg_eff[_fld] = _gv
        else:
            pcfg_eff = pcfg

        eligible.append((t, pcfg_eff, gov))
    if not eligible:
        return None

    # Step 2: certainty + spread gates per pair
    candidates = [t for (t, pcfg_eff, _gov) in eligible if _passes_gates(t, pcfg_eff)]
    if not candidates:
        return None

    # Steps 3-5: winner selection, throttle-aware — a capped locked cell must not
    # block other candidates from firing. Pick the winner, resolve inversion,
    # check the throttle; if throttled, drop it from the pool and re-pick.
    if pm.get("random_pick", False):
        import random
    best = None
    signal_dir = trade_dir = None
    inverted = False
    pick_method = "edge_rank"
    # Per-currency directional exposure state (Step 6) — computed once per call;
    # open_positions does not change while we re-pick within the pool.
    _ccy_cap = int(pm["account"]["max_per_currency_direction"])
    _ccy_exp = currency_exposure(open_positions)
    pool = list(candidates)
    while pool:
        if pm.get("random_pick", False):
            cand = random.choice(pool)
            pick_method = "random"
        else:
            cand = max(pool, key=_edge_rank)
            pick_method = "edge_rank"
        # Step 4: inversion — resolve cell-level and direction-level inversions.
        # effective_inverted = cell_level_inverted XOR direction_level_inverted.
        # In practice they should not be combined on the same (pair, session).
        signal_dir = cand.direction.bias
        cand_gov = lock_guard.locked_governance(cand.pair, cand.session)
        if cand_gov is not None:
            # Locked branch: use frozen governance for both inversion fields.
            _gov_inv = cand_gov.get("inverted_live", False)
            _live_inv = (cand.pair, cand.session) in pm.get("inverted_live_cells", frozenset())
            if _gov_inv != _live_inv:
                lock_guard.log_drift(cand.pair, cand.session, "inverted_live", _live_inv, _gov_inv)
            cell_inv = _gov_inv
            # inverted_directions: list of native dirs frozen direction-inverted for this cell
            _gov_inv_dirs = cand_gov.get("inverted_directions", [])  # [] if key absent (old snapshot)
            _live_inv_dirs = [d for d in [signal_dir]
                              if (cand.pair, cand.session, d) in pm.get("inverted_live_directions", frozenset())]
            _gov_inv_dirs_set = set(_gov_inv_dirs)
            if _gov_inv_dirs_set != set(_live_inv_dirs):
                lock_guard.log_drift(cand.pair, cand.session, "inverted_directions",
                                     _live_inv_dirs, _gov_inv_dirs)
            dir_inv = signal_dir in _gov_inv_dirs_set
        else:
            # Unlocked branch: use live config for both inversion fields.
            cell_inv = (cand.pair, cand.session) in pm.get("inverted_live_cells", frozenset())
            dir_inv  = (cand.pair, cand.session, signal_dir) in pm.get("inverted_live_directions", frozenset())
        # XOR: if both are set, they cancel out (no net flip)
        inverted = cell_inv != dir_inv
        trade_dir = ("short" if signal_dir == "long" else "long") if inverted else signal_dir

        # Step 5: THROTTLE — locked cells cap opens per session-instance.
        # A capped candidate is excluded and selection falls through to next-best.
        if cell_opens is not None and now is not None:
            _cap = lock_guard.throttle_cap(cand.pair, cand.session)
            if (_cap is not None
                    and trade_dir in lock_guard.locked_traded_directions(cand.pair, cand.session)):
                _inst_key = lock_guard.session_instance_key(cand.session, now)
                _opens_key = f"{cand.pair}|{cand.session}|{trade_dir}|{_inst_key}"
                _opens_n = cell_opens.get(_opens_key, 0)
                if _opens_n >= _cap:
                    import logging as _lg
                    _lg.getLogger("v5.playmaker").warning(
                        "LOCK_GUARD throttle %s/%s/%s opens=%d cap=%d — holding fire this session",
                        cand.pair, cand.session, trade_dir, _opens_n, _cap
                    )
                    pool.remove(cand)
                    continue

        # Step 6: PER-CURRENCY DIRECTIONAL EXPOSURE CAP (2026-07-02 panel-unanimous).
        # Motivation: 2026-07-02 the engine held three long-yen-pair positions into a
        # JPY crash — three "independent" trades were one macro bet at 3x size.
        # A position exposes two currencies with opposite signs (long BASE_QUOTE =
        # long BASE + short QUOTE); block the candidate when opening it would push
        # any single (currency, sign) count past max_per_currency_direction across
        # open positions + the candidate. Checked on trade_dir (post-inversion) —
        # what we EXPOSE, not what the signal said.
        # Lock-guard interaction: NONE by design — this is a portfolio-level
        # constraint like max_concurrent_trades, applied after per-cell governance;
        # LOCKED cells are subject to it (it constrains the portfolio, not the cell).
        # Same fallthrough as the throttle: a capped candidate must not block others.
        _capped_leg = None
        for _leg in _currency_legs(cand.pair, trade_dir):
            if _ccy_exp.get(_leg, 0) + 1 > _ccy_cap:
                _capped_leg = _leg
                break
        if _capped_leg is not None:
            import logging as _lg
            _lg.getLogger("v5.playmaker").warning(
                "RISK_CAP currency=%s dir=%s open=%d cap=%d — skipping %s",
                _capped_leg[0], _capped_leg[1], _ccy_exp.get(_capped_leg, 0),
                _ccy_cap, cand.pair
            )
            pool.remove(cand)
            continue
        best = cand
        break
    if best is None:
        return None
    # Determine annotation for inversion type in reads
    if inverted:
        if cell_inv and not dir_inv:
            _inv_type = "INVERTED_CELL"
        elif dir_inv and not cell_inv:
            _inv_type = "INVERTED_DIR"
        else:
            _inv_type = "INVERTED_XOR"  # both set, shouldn't happen in practice
    else:
        _inv_type = None
    return TradeTicket(
        pair=best.pair,
        session=best.session,
        direction=trade_dir,
        score=round(best.composite_score, 4),
        dir_certainty=round(best.direction.certainty, 4),
        mom_certainty=round(best.momentum.certainty, 4),
        vol_regime=best.momentum.vol_regime,
        expected_pips=best.momentum.expected_pips,
        timestamp=best.timestamp,
        reads={
            "direction": best.direction.reads,
            "momentum":  best.momentum.reads,
            "signal_direction": signal_dir,  # what the engine SAW pre-inversion
            "pick_method":      pick_method, # "random" or "edge_rank"
            "inversion_type":   _inv_type,   # INVERTED_CELL / INVERTED_DIR / None
        },
        rivals=len(candidates) - 1,
        inverted_live=inverted,
    )
