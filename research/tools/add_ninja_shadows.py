#!/usr/bin/env python3
"""research/tools/add_ninja_shadows.py — the 🥷 NINJA slate (2026-08-30).

Source: two PDFs from ninjagex.com supplied by Brock — "The Ninja GEX System"
(12pp) and "The A+ Setup Checklist" (3pp). An OPTIONS system for SPY built on
four components: (1) a clean, spaced 9/21/50 EMA stack agreeing across
timeframes, (2) GEX dealer-gamma pivot levels, (3) a flag or compression
pattern forming AT that pivot, (4) volume expansion confirming the break.

WHAT TRANSFERS AND WHAT DOES NOT — stated up front, because the honest
answer changes what this slate can claim:

  EMA stack     TRANSFERS. ema_trend_pips (M5 EMA14-EMA40) carries both the
                stack direction AND the "spaced, not tangled" requirement:
                near zero IS the messy/crossed state the checklist refuses to
                trade. ema20_1h_dist supplies the higher-timeframe agreement
                the checklist demands ("conflicting timeframes = sit out").

  GEX levels    DOES NOT TRANSFER. Spot FX has no centralised options open
                interest, so no dealer-gamma map exists for EUR_USD. The PDF
                calls these levels "what make this system different from
                everything else" — so the component with the actual claimed
                edge is exactly the one we cannot replicate. Two honest
                substitutions, neither of which inherits that claim:
                  · the LEVEL becomes prior-session ceiling/floor
                    (ps_high_dist / ps_low_dist), a price-structure level,
                    not a positioning level;
                  · the GAMMA REGIME becomes a VOLATILITY regime
                    (atr_h1_relative), which reproduces the PDF's described
                    BEHAVIOUR (positive gamma = stabilising/mean-reverting,
                    negative gamma = amplifying/explosive) without any claim
                    about dealer positioning. Arms C1/C2 below test exactly
                    that behavioural claim.

  Pattern       PARTIALLY. Compression becomes a coiled-not-dead volatility
                band; the flag becomes pole (ret_1h) + tight pullback
                (ret_5m) with the stack intact. No candlestick-pattern
                features exist, so the checklist's "confirmation candle" item
                is simply absent.

  Volume        WEAKLY. FX tick "volume" is a tick count, not size — the
                feed's own docstring says so. The checklist's premise is
                INSTITUTIONAL PARTICIPATION, which tick count cannot see.
                Also, "1.5x-3x average" is an equities number: in FX tick
                volume 1.5x is the top ~5% of bars, so the raw threshold
                would be far more selective than intended. Translated by
                PERCENTILE instead: rvol_5bar >= 1.35 is p90 (measured).

THRESHOLDS ARE MEASURED, NOT GUESSED. Pip-denominated gates are PER PAIR,
from 1,119 london+ny M5 views per pair (~3 weeks, 8 majors) replayed through
the live feed's own _compute_features (research/ninja_thresholds_2026-08-30
.json is the artifact). A flat +2p spacing gate would have been the top
quartile on AUD_USD and nowhere near it on USD_JPY (measured p75 of
|ema_trend_pips|: 2.64 vs 5.60) — that asymmetry silently mutes half a slate,
which is the B-128 failure mode. Self-normalising gates (atr_h1_relative,
rvol_5bar, efficiency_10) keep one global threshold.

FIRE RATES measured on the same corpus (% of bar-sides, london+ny):
  A stack_break 0.83% · B flag 0.93% · C1 amp_break 0.61% · C2 stab_fade 2.12%
Arms were tuned to COMPARABLE rates so no arm floods the journal and none is
too rare to ever reach the bar; C2 accrues ~3x faster than C1 and will get
its verdict first. Slate adds ~146 stamps/day (~2% of current volume).

THE ONE GENUINELY NEW TEST: C1 and C2 sit at the IDENTICAL location (within
6 pips of the prior-session ceiling/floor) and differ ONLY in volatility
regime and the action it implies — break WITH the stack when amplifying,
FADE back into range when stabilising. That is a controlled 2x2 on the PDF's
gamma claim, translated into the one form FX can actually express.

CAVEATS: three weeks is one regime, not a sample; thresholds are quantiles of
that window and will drift; arms A/B overlap the existing breakout and
trend_pullback families (the cluster filter already grants at most one seat
per pair/side, so this competes rather than stacks); C2 overlaps the existing
ps_ceil/ps_floor fade family deliberately — it asks whether the vol-regime
gate IMPROVES that family. Brock's own confirmation-depth sweep (2026-08-19,
GBP_USD) found bought confirmation never crossed zero at any depth, which is
a NEGATIVE prior on arm A specifically (it pays for volume confirmation);
arm B is its anticipation-entry counterpart, so the pair tests that finding
head-on. Zero authority: SHADOW only, earns a PROBE seat through the
ordinary bars and family-cycle evidence or dies in shadow.

Idempotent: existing ids are skipped.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")

PAIRS = ["EUR_USD", "GBP_USD", "AUD_USD", "USD_CHF", "USD_CAD",
         "USD_JPY", "EUR_JPY", "AUD_JPY"]
SESSIONS = ("london", "ny")          # asia excluded: dead-vol is the known
                                     # negative quintile (P3a, eater slate)

# Per-pair pip gates — p75 of |ema_trend_pips|, p85 of |ret_1h|, p75 of
# |ret_5m| over 1,119 london+ny views/pair (2026-08-30 corpus).
T = {
    "EUR_USD": {"spread": 3.00, "pole": 7.4,  "pull": 1.8},
    "GBP_USD": {"spread": 3.74, "pole": 10.0, "pull": 2.4},
    "AUD_USD": {"spread": 2.64, "pole": 6.0,  "pull": 1.4},
    "USD_CHF": {"spread": 3.41, "pole": 8.4,  "pull": 1.9},
    "USD_CAD": {"spread": 3.80, "pole": 9.3,  "pull": 2.1},
    "USD_JPY": {"spread": 5.60, "pole": 13.4, "pull": 2.8},
    "EUR_JPY": {"spread": 4.30, "pole": 11.4, "pull": 2.5},
    "AUD_JPY": {"spread": 3.73, "pole": 9.4,  "pull": 1.9},
}
# Global, self-normalising gates (measured percentiles in the comments)
COIL_LO, COIL_HI = 0.80, 1.15   # atr_h1_relative p25..p78 — coiled, not dead
RVOL_EXPAND = 1.35              # p90 — percentile translation of "1.5-3x"
RVOL_DRY = 1.00                 # ~p60 — volume dries inside the flag
AMP_MIN = 1.25                  # p90 — amplifying ("negative gamma"-like)
STAB_MAX = 0.85                 # p25 — stabilising ("positive gamma"-like)
EFF_CHOP = 0.13                 # p25 — mean-reverting, no move carrying
NEAR = 6.0                      # pips: "AT" the prior-session level

EXIT = {"mode": "ratchet", "sl_pips": 50.0, "trigger_pips": 9.0,
        "trail_pips": 2.0, "trail_mult": 0.0, "trail_min": 2.5,
        "trail_max": 10.0, "_class": "RANGE_SIZED",
        "engage_pips": 7.5, "engage_lock_pips": 6.0}

SRC = ("NINJA slate 2026-08-30: ninjagex.com 'Ninja GEX System' + A+ checklist "
       "(Brock-supplied PDFs), translated to FX. GEX dealer-gamma levels DO NOT "
       "EXIST in spot FX — the PDF's own claimed differentiator is the one part "
       "not replicated; level := prior-session ceiling/floor (price structure, "
       "not positioning) and gamma regime := volatility regime (behavioural "
       "analogue only). FX tick volume is a tick count, not participation, so "
       "the volume gate is a p90 percentile translation, not the PDF's 1.5-3x. "
       "Per-pair pip thresholds measured on 1,119 london+ny views/pair through "
       "the live feed's own _compute_features (research/"
       "ninja_thresholds_2026-08-30.json). Arms tuned to comparable fire rates "
       "(0.6-2.1%). C1/C2 are a controlled 2x2 at an identical location testing "
       "regime-flips-the-action. Arm A carries a NEGATIVE prior from the "
       "2026-08-19 confirmation-depth sweep. One 3-week regime, quantiles will "
       "drift — zero prior, earns via family cycles or dies in shadow.")


def _stack(side, t):
    """EMA stack aligned AND spaced (near zero = the tangled state the
    checklist refuses) + higher-timeframe agreement."""
    s = t["spread"]
    return [
        {"feature": "ema_trend_pips",
         **({"min": s} if side == "long" else {"max": -s}),
         "note": "9/21/50 stack proxy: M5 EMA14-EMA40 aligned AND spaced "
                 "(|x| >= this pair's p75); near zero = tangled = no trade"},
        {"feature": "ema20_1h_dist",
         **({"min": 0.0} if side == "long" else {"max": 0.0}),
         "note": "higher-timeframe agreement — conflicting timeframes sit out"},
    ]


def ninja_setups(pair):
    t = T[pair]
    for side in ("long", "short"):
        lvl_break = ({"feature": "ps_high_dist", "min": -NEAR,
                      "note": "at/through the prior-session ceiling"}
                     if side == "long" else
                     {"feature": "ps_low_dist", "max": NEAR,
                      "note": "at/through the prior-session floor"})
        # A — compression that breaks, with volume expansion (confirmation entry)
        yield (f"ninja_stack_break_{side}", side, _stack(side, t) + [
            {"feature": "atr_h1_relative", "min": COIL_LO, "max": COIL_HI,
             "note": "compression: coiled vs its own norm, but not dead vol"},
            {"feature": "rvol_5bar", "min": RVOL_EXPAND,
             "note": "volume expansion p90 (percentile translation of 1.5-3x; "
                     "FX tick volume is not participation)"},
            lvl_break,
        ])
        # B — flag: pole, tight orderly pullback, volume dry (anticipation entry)
        pull_lo, pull_hi = ((-2.0 * t["pull"], 0.5 * t["pull"]) if side == "long"
                            else (-0.5 * t["pull"], 2.0 * t["pull"]))
        yield (f"ninja_flag_{side}", side, _stack(side, t) + [
            {"feature": "ret_1h",
             **({"min": t["pole"]} if side == "long" else {"max": -t["pole"]}),
             "note": "the flag pole: 1h move >= this pair's p85"},
            {"feature": "ret_5m", "min": round(pull_lo, 2), "max": round(pull_hi, 2),
             "note": "tight orderly pullback — pausing, not surging or collapsing"},
            {"feature": "rvol_5bar", "max": RVOL_DRY,
             "note": "volume dries up during the flag consolidation"},
        ])
        # C1 — amplifying regime: break WITH the stack at the level
        lvl_at = ({"feature": "ps_high_dist", "min": -NEAR, "max": NEAR,
                   "note": "AT the prior-session ceiling (identical location to "
                           "ninja_stab_fade_short — the controlled pair)"}
                  if side == "long" else
                  {"feature": "ps_low_dist", "min": -NEAR, "max": NEAR,
                   "note": "AT the prior-session floor (identical location to "
                           "ninja_stab_fade_long — the controlled pair)"})
        yield (f"ninja_amp_break_{side}", side, [
            {"feature": "atr_h1_relative", "min": AMP_MIN,
             "note": "amplifying regime (p90) — the negative-gamma ANALOGUE: "
                     "moves get extended, breaks carry"},
            _stack(side, t)[0],
            lvl_at,
        ])
        # C2 — stabilising regime: FADE the same level (mirror side)
        fade_lvl = ({"feature": "ps_low_dist", "min": -NEAR, "max": NEAR,
                     "note": "AT the prior-session floor — fade back up"}
                    if side == "long" else
                    {"feature": "ps_high_dist", "min": -NEAR, "max": NEAR,
                     "note": "AT the prior-session ceiling — fade back down"})
        yield (f"ninja_stab_fade_{side}", side, [
            {"feature": "atr_h1_relative", "max": STAB_MAX,
             "note": "stabilising regime (p25) — the positive-gamma ANALOGUE: "
                     "price mean-reverts at the level"},
            {"feature": "efficiency_10", "max": EFF_CHOP,
             "note": "chop (p25): nothing is carrying, so fade not break"},
            fade_lvl,
        ])


def main(write=True):
    added = skipped = 0
    for pair in PAIRS:
        p = REPO / "config" / "cells" / f"{pair}.json"
        cfg = json.loads(p.read_text())
        for sname, sess in cfg["sessions"].items():
            if sname not in SESSIONS:
                continue
            setups = sess.setdefault("setups", [])
            have = {s.get("id") for s in setups}
            for sid, side, conds in ninja_setups(pair):
                if sid in have:
                    skipped += 1
                    continue
                setups.append({
                    "id": sid, "side": side, "class": "market_structure",
                    "status": "SHADOW", "wired": TODAY, "horizon_min": 240,
                    "conditions": conds, "exit": dict(EXIT),
                    "evidence": {"ev_seq": 0.0, "source": SRC},
                    "sizing": {"risk_pct": 0.2},
                    "watch": "\U0001f977",    # 🥷
                })
                added += 1
        if write:
            p.write_text(json.dumps(cfg, indent=2) + "\n")
    print(f"added {added} ninja shadows, skipped {skipped} existing")
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
