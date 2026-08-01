#!/usr/bin/env python3
"""research/tools/add_external_strategy_shadows.py — the external-repo trial
docket (2026-07-31, Brock: "add those strategies as shadows which can earn
their spot if worthwhile").

From the six-repo audit (see docs/slates/external_repos_audit_2026-07-31.md):
only two entry ideas deserved the experiment, and NEITHER carries a prior —
every cell enters at zero authority and earns promotion exclusively through
Scrooge's family-cycle geometry:

  tc_vwapbb_*   TradeClaw's trend-conditioned VWAP–EMA–Bollinger pullback
                (MIT; github.com/naimkatiman/tradeclaw): buy a lower-band
                excursion while above session VWAP in an EMA uptrend; mirror
                short. Its own costed BTC H1 experiment was NEGATIVE
                (PF 0.809, −11.12%) — this is a hypothesis, not an edge.
  es_trend / es_meanrev / es_breakout
                EuroScope's regime-routed split (MIT; github.com/
                logiccrafterdz/EuroScope): ADX-gated trend-following,
                range-regime RSI/BB mean-reversion fade, prev-day-high
                breakout. Its committed "performance report" was a one-trade
                smoke test — zero prior granted.

Feed features added for these trials: vwap_dist_pips (session-anchored VWAP)
and adx14 (H1 Wilder ADX). Idempotent: existing ids are skipped.
"""
import copy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")
EXIT = {"mode": "ratchet", "sl_pips": 50.0, "trigger_pips": 8.5,
        "trail_pips": 2.5, "trail_mult": 0.0, "trail_min": 2.5,
        "trail_max": 10.0, "_class": "RANGE_SIZED"}

TC_SRC = ("external-repo trial 2026-07-31: TradeClaw VWAP-EMA-BB pullback "
          "(MIT). Source's own costed test was NEGATIVE - zero prior, must "
          "earn the seat via family cycles")
ES_SRC = ("external-repo trial 2026-07-31: EuroScope regime-routed rules "
          "(MIT). No performance evidence in source - zero prior")

TC_PAIRS = ["AUD_USD", "EUR_USD", "GBP_USD", "USD_CAD"]
ES_PAIRS = ["EUR_USD", "GBP_USD"]
SESSIONS = ["asia", "london", "ny"]


def tc_setups():
    yield ("tc_vwapbb_long", "long", [
        {"feature": "bb_pos", "max": 0.08,
         "note": "lower-band excursion (TradeClaw: BB touch leg)"},
        {"feature": "vwap_dist_pips", "min": 0.0,
         "note": "still above session VWAP (trend condition)"},
        {"feature": "ema20_dist_pct", "min": 0.0,
         "note": "M5 EMA20 uptrend agreement"}])
    yield ("tc_vwapbb_short", "short", [
        {"feature": "bb_pos", "min": 0.92,
         "note": "upper-band excursion"},
        {"feature": "vwap_dist_pips", "max": 0.0,
         "note": "below session VWAP"},
        {"feature": "ema20_dist_pct", "max": 0.0,
         "note": "EMA20 downtrend agreement"}])


def es_setups():
    yield ("es_trend_long", "long", [
        {"feature": "adx14", "min": 25.0,
         "note": "EuroScope trend regime: ADX >= 25"},
        {"feature": "trend_4h", "min": 0.5, "note": "4h trend up"},
        {"feature": "ema20_dist_pct", "min": 0.0, "note": "price above EMA20"}])
    yield ("es_meanrev_short", "short", [
        {"feature": "adx14", "max": 20.0,
         "note": "EuroScope range regime: ADX <= 20"},
        {"feature": "rsi14", "min": 68.0, "note": "RSI extreme"},
        {"feature": "bb_pos", "min": 0.90, "note": "upper-band touch — fade"}])
    yield ("es_breakout_long", "long", [
        {"feature": "pdh_dist", "min": 0.0,
         "note": "above the previous day high (breakout leg)"},
        {"feature": "adx14", "min": 20.0, "note": "expansion regime"},
        {"feature": "rsi14", "min": 50.0, "note": "momentum side of 50"}])


def wire(pairs, gen, src_note):
    added = []
    for pair in pairs:
        path = REPO / "config" / "cells" / f"{pair}.json"
        d = json.loads(path.read_text())
        changed = False
        for sess in SESSIONS:
            block = d.get("sessions", {}).get(sess)
            if block is None:
                continue
            setups = block.setdefault("setups", [])
            have = {s["id"] for s in setups}
            for sid, side, conds in gen():
                if sid in have:
                    continue
                setups.append({
                    "id": sid, "side": side, "class": "book_replay",
                    "status": "SHADOW", "wired": TODAY,
                    "horizon_min": 240,
                    "conditions": copy.deepcopy(conds),
                    "exit": dict(EXIT),
                    "sizing": {"risk_pct": 0.2},
                    "evidence": {"ev_seq": 0.0, "source": src_note},
                    "notes": "zero-authority external-strategy trial; "
                             "promotion only via family-cycle evidence",
                })
                added.append(f"{pair}/{sess}/{sid}")
                changed = True
        if changed:
            path.write_text(json.dumps(d, indent=2))
    return added


def main():
    a = wire(TC_PAIRS, tc_setups, TC_SRC)
    b = wire(ES_PAIRS, es_setups, ES_SRC)
    print(f"TradeClaw shadows added: {len(a)}")
    print(f"EuroScope shadows added: {len(b)}")
    print(f"total: {len(a) + len(b)}")


if __name__ == "__main__":
    main()
