#!/usr/bin/env python3
"""research/tools/add_eater_shadows.py — the 🦈 EATER slate (2026-08-19,
Brock: "build similar ones with the enhanced momentum indicators with a dead
volume filter... made to sit and eat, like a trap door spider").

Origin: 2026-08-19 churn-map session (vault note
note_session_2026-08-19-confirmation-depth-sweep). Chain of evidence, all
correlational, ZERO authority granted:

  P2.1 (8yr corpus, walk-forward, partial vs ATR level): q_yzv 8/8 pairs,
       adr_consumed 7-8/8, atr_h1_relative 5-6/8 predict swing AMPLITUDE
       in pips. Swing COUNT is unpredictable. Hurst/entropy: nulls.
  P3a  (9,114 LIVE shadow episodes 07-06→08-19): amplitude replicates
       (+54% Q1→Q5); net240 climbs both dials (yz spread +2.4p, adr +3.8p);
       the DEAD-VOL bottom quintile is the only negative one; FADE family
       peaks MID-dial (hot vol runs fades over), NON-FADE peaks at MAX heat.

Design maps those three findings onto three archetypes, every one carrying a
dead-vol filter (the trap-door spider only opens the door when the wire is
moving). Live features only (adr_consumed, atr_h1_relative already in the
feed) — config-only slate, no code in the live loop. yz_pct as a live
feature is a possible v2 if this slate earns attention.

Caveats stated up front: P3a episodes overlap in time (naive n overstates
independence); single 6-week era; thresholds are round-number translations
of quintile bands, deliberately weak priors. These cells must earn any seat
exclusively through family-cycle evidence and the ordinary bars.

Idempotent: existing ids are skipped.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")

EXIT = {"mode": "ratchet", "sl_pips": 50.0, "trigger_pips": 8.5,
        "trail_pips": 2.5, "trail_mult": 0.0, "trail_min": 2.5,
        "trail_max": 10.0, "_class": "RANGE_SIZED"}

SRC = ("EATER slate 2026-08-19: churn-map session (P2.1 corpus walk-forward "
       "+ P3a on 9,114 live episodes). Amplitude is predictable, count is "
       "not; dead-vol Q1 drags; fades peak mid-heat, momentum peaks max-heat; "
       "adr_consumed>0.9 continuation beat the exhaustion-fade heuristic. "
       "Correlational only, overlapping episodes, one era — zero prior, "
       "earns via family cycles or dies in shadow.")

PAIRS = ["EUR_USD", "GBP_USD", "AUD_USD", "USD_CHF", "USD_CAD",
         "USD_JPY", "EUR_JPY", "AUD_JPY"]

DEAD_VOL = {"feature": "atr_h1_relative", "min": 0.8,
            "note": "dead-vol filter: P3a Q1 (quiet H1 vol) was the only negative quintile"}


def eater_setups(session):
    """Yield (id, side, sessions-this-belongs-to, conditions) tuples."""
    # 1. momentum eaters — non-fade family peaked at MAX heat (P3a Q5 +4.0p)
    for side, tsign, esign in (("long", 0.5, 1.0), ("short", -0.5, -1.0)):
        if session in ("london", "ny"):
            yield (f"shark_momo_run_{side}", side, [
                {"feature": "atr_h1_relative", "min": 1.3,
                 "note": "max heat: non-fade P3a Q5 was best (+4.0p)"},
                {"feature": "adr_consumed", "min": 0.5, "max": 2.0,
                 "note": "day is moving; adr dial positive 7-8/8 pairs"},
                {"feature": "trend_4h",
                 **({"min": tsign} if side == "long" else {"max": tsign}),
                 "note": "4h direction agreement"},
                {"feature": "ema_trend_pips",
                 **({"min": esign} if side == "long" else {"max": esign}),
                 "note": "M5 impulse aligned"},
            ])
    # 2. fade eaters — fade family peaked MID-dial (P3a Q3-Q4 ~+2p, Q5 decays)
    for side in ("long", "short"):
        pos_gate = ({"feature": "ps_pos", "max": 0.10,
                     "note": "at prev-session floor"} if side == "long" else
                    {"feature": "ps_pos", "min": 0.90,
                     "note": "at prev-session ceiling"})
        yield (f"shark_fade_mid_{side}", side, [
            {"feature": "atr_h1_relative", "min": 0.8, "max": 1.3,
             "note": "MID heat band: fades die in dead vol AND under max heat (P3a)"},
            {"feature": "adr_consumed", "min": 0.25,
             "note": "not a dead day"},
            pos_gate,
        ])
    # 3. adr-late continuation — the anti-exhaustion bet (P3a adr Q5 +3.15p)
    for side, dsign in (("long", 5.0), ("short", -5.0)):
        if session == "ny":
            yield (f"shark_adr_late_{side}", side, [
                {"feature": "adr_consumed", "min": 0.9, "max": 2.5,
                 "note": "day mostly consumed: a day that moved keeps moving (P2.1/P3a)"},
                {"feature": "d_ret",
                 **({"min": dsign} if side == "long" else {"max": dsign}),
                 "note": "continue the day's direction"},
                dict(DEAD_VOL),
            ])


def main(write=True):
    added, skipped = 0, 0
    for pair in PAIRS:
        p = REPO / "config" / "cells" / f"{pair}.json"
        cfg = json.loads(p.read_text())
        for sname, sess in cfg["sessions"].items():
            setups = sess.setdefault("setups", [])
            have = {s.get("id") for s in setups}
            for sid, side, conds in eater_setups(sname):
                if sid in have:
                    skipped += 1
                    continue
                setups.append({
                    "id": sid, "side": side, "class": "control",
                    "status": "SHADOW", "wired": TODAY, "horizon_min": 240,
                    "conditions": conds, "exit": dict(EXIT),
                    "evidence": {"ev_seq": 0.0, "source": SRC},
                    "sizing": {"risk_pct": 0.2},
                    "watch": "\U0001f988",   # 🦈
                })
                added += 1
        if write:
            p.write_text(json.dumps(cfg, indent=2) + "\n")
    print(f"added {added} eater shadows, skipped {skipped} existing")
    # validate everything we touched
    from config.cell_schema import validate_file
    bad = 0
    for pair in PAIRS:
        r = validate_file(REPO / "config" / "cells" / f"{pair}.json")
        errs = getattr(r, "errors", None) or []
        if errs:
            bad += 1
            print(f"INVALID {pair}: {list(errs)[:5]}")
    print("validation:", "CLEAN" if bad == 0 else f"{bad} FILES INVALID")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
