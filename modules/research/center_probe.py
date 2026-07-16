"""modules/research/center_probe.py — box direction-discovery probes (LOG-ONLY).

Ported from V5 (Brock 2026-07-10). Three zones of the previous-session box,
each a pure sensor that fires when price reaches it, records the FULL indicator
vector with NO direction commitment, and lets the forward path decide what
happened:

  center   (ps_pos 0.42-0.58) — which wall does the wave ride to?
  ceiling  (ps_pos >= 0.88)   — break out above, or reverse back down?
  floor    (ps_pos <= 0.12)   — break down below, or bounce back up?

box >= 16p on every zone (half-width >= 8p -> ratchet room for the 5-6p min
lock). Never trades. Scorer research/tools/center_probe_score.py mines, per
zone, which indicators separate the outcomes (breakout vs reversal, up vs down).
"""
from __future__ import annotations
import json, logging, threading
from pathlib import Path

log = logging.getLogger("v6.center_probe")
_LOG  = Path(__file__).resolve().parent.parent.parent / "data" / "center_probe_log.jsonl"
_LOCK = threading.Lock()
_last: dict = {}
_GAP_S   = 1800
_MIN_BOX = 16.0

_FEATURES = ["atr_5m","atr_1h","atr_conc","atr_h1_relative","rvol_5bar","rvol_12bar",
             "range_5bar","range_12bar","bb_pos","bb_width","zscore_5m","willr_m5",
             "rsi14","rsi_slope","ema20_dist_pct","ema5_dist_pips","ema50_dist_pct",
             "ema_cross_pips","ret_5m","ret_15m","ret_30m","ret_1h","h1_ret_1bar",
             "h1_ret_4bar","htf_pct_20","htf_pct_60","close_pos_daily","adr_consumed",
             "d_ret","kc_up_dist_pips","vortex_diff_h1","trend_4h","aroonosc_h1",
             "pdh_dist","pdl_dist","ps_high_dist","ps_low_dist","ps_pos"]

def _zone(pos: float) -> str | None:
    if 0.42 <= pos <= 0.58: return "center"
    if pos >= 0.88:         return "ceiling"
    if pos <= 0.12:         return "floor"
    return None

def observe(views, now) -> None:
    """Called each scan cycle. Log-only — never returns intents, never trades."""
    for v in views:
        try:
            box = float(getattr(v, "ps_low_dist", 0.0)) - float(getattr(v, "ps_high_dist", 0.0))
            pos = float(getattr(v, "ps_pos", 0.5))
            zone = _zone(pos)
            if box < _MIN_BOX or zone is None:
                continue
            key = (v.pair, v.session, zone)
            t = now.timestamp()
            if t - _last.get(key, 0.0) < _GAP_S:
                continue
            _last[key] = t
            bid = float(getattr(v, "bid", 0.0)); ask = float(getattr(v, "ask", 0.0))
            rec = {"ts": now.isoformat(), "pair": v.pair, "session": v.session,
                   "zone": zone, "mid": round((bid + ask) / 2.0, 5) if bid and ask else None,
                   "box": round(box, 1)}
            for f in _FEATURES:
                val = getattr(v, f, None)
                rec[f] = round(float(val), 5) if isinstance(val, (int, float)) else None
            with _LOCK:
                _LOG.parent.mkdir(exist_ok=True)
                with open(_LOG, "a") as fh:
                    fh.write(json.dumps(rec) + "\n")
        except Exception as exc:
            log.warning("box_probe observe failed %s: %s", getattr(v, "pair", "?"), exc)
