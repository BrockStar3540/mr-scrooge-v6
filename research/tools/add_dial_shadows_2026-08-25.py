#!/usr/bin/env python3
"""research/tools/add_dial_shadows_2026-08-25.py — the 🎯 DIAL slate
(operator, 2026-08-25): narrowed-gate shadow twins from two same-day harvests.

  A. DIAL-IN FARM (4,250 scored episodes joined to stamped gate values):
     inside the earners' ranges, winners cluster — cut the slice that bleeds.
  B. STRUCK-CELL AUTOPSY (359 episodes, features reconstructed via the live
     view_at_time path): every strike was an EDGE-of-range kill around a live
     core — the core is a new, narrower hypothesis that has never auditioned.

Each variant clones its parent's conditions, then tightens/adds the named
gates. New ids = new cells: ZERO authority, standard bar, no inherited
strikes (the struck PARENTS stay struck — three-strikes is untouched).
Overfit risk is real (terciles mined from the killing data; bands widened a
touch from the raw terciles) — which is exactly why these are shadows.
Exits: parents' unified two-phase gear, copied. Idempotent."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2] if "research" in str(Path(__file__).resolve()) else Path.home() / "mr-scrooge-v6"
sys.path.insert(0, str(REPO))
TODAY = datetime.now(timezone.utc).strftime("%Y-%m-%d")
PAIRS = {"EUR_USD", "GBP_USD", "AUD_USD", "USD_CHF", "USD_CAD",
         "USD_JPY", "EUR_JPY", "AUD_JPY"}

SRC = ("DIAL slate 2026-08-25: dial-in farm (4,250 eps w/ stamped gate values) + "
       "struck-cell autopsy (359 eps, reconstructed features). Sub-range structure "
       "was material and consistent; bands widened from raw terciles to blunt "
       "overfit. Zero prior authority; parents' strike records untouched.")

# (parent_setup_id, variant_suffix, {feature: (new_min, new_max)})  None = keep parent bound
VARIANTS = [
    ("echo_box_fade_short",        "_g_dial", {"bb_pos": (None, 0.95)}),
    ("echo_box_fade_counter_long", "_g_dial", {"bb_pos": (0.90, None)}),
    ("mr2_bb_reversion_short",     "_g_dial", {"rsi14": (66.0, None), "bb_pos": (0.90, None),
                                               "zscore_5m": (1.6, None), "spread_pips": (None, 1.8)}),
    ("rg1_range_scalp_counter_long", "_g_dial", {"bb_pos": (0.91, None), "ret_5m": (-0.4, None),
                                                 "rsi14": (66.0, None)}),
    ("fvg_fill_long",              "_g_dial", {"fvg_bull_dist_pips": (1.8, None)}),
    ("ps_ceil_fade_short",         "_g_appr", {"ps_pos": (0.91, 0.974)}),
    ("timing_lean_30",             "_g_hot",  {"atr_h1_relative": (1.4, None)}),
    ("control_rvol_60",            "_g_core", {"rvol_5bar": (0.70, 0.76)}),
    ("control_atrconc_60",         "_g_core", {"atr_conc": (0.215, 0.24)}),
    ("classic_box_break_short",    "_g_slice", {"bb_pos": (-0.07, 0.0)}),
]

def build_variant(parent, suffix, tweaks):
    v = json.loads(json.dumps(parent))          # deep copy
    v["id"] = parent["id"] + suffix
    v["status"] = "SHADOW"
    v["wired"] = TODAY
    v["watch"] = "\U0001f3af"                   # 🎯
    v["sizing"] = {"risk_pct": 0.2}
    v.pop("shed", None)
    conds = {c["feature"]: c for c in (v.get("conditions") or [])}
    for feat, (mn, mx) in tweaks.items():
        c = conds.get(feat)
        if c is None:
            c = {"feature": feat, "note": "added by dial slate"}
            v.setdefault("conditions", []).append(c)
            conds[feat] = c
        if mn is not None:
            c["min"] = mn
        if mx is not None:
            c["max"] = mx
        c["note"] = ((c.get("note") or "") + " | dial 2026-08-25").strip(" |")
    v["evidence"] = {"ev_seq": 0.0, "source": SRC}
    v["notes"] = "🎯 dial variant: narrowed gates from same-day range harvests; earns via ordinary bars"
    return v

added, skipped = 0, 0
targets = {pid: (sfx, tw) for pid, sfx, tw in VARIANTS}
for f in sorted((REPO / "config" / "cells").glob("*.json")):
    cfg = json.loads(f.read_text())
    if cfg.get("pair", f.stem) not in PAIRS:
        continue
    dirty = False
    for sess, b in (cfg.get("sessions") or {}).items():
        setups = b.get("setups") or []
        have = {s.get("id") for s in setups}
        for s in list(setups):
            pid = s.get("id")
            if pid not in targets or "_t20s" in pid:
                continue
            sfx, tw = targets[pid]
            vid = pid + sfx
            if vid in have:
                skipped += 1
                continue
            setups.append(build_variant(s, sfx, tw))
            have.add(vid)
            added += 1
            dirty = True
    if dirty:
        f.write_text(json.dumps(cfg, indent=2) + "\n")

print(f"added {added} 🎯 dial shadows, skipped {skipped} existing")
with (REPO / "data" / "governor_ledger.jsonl").open("a") as fh:
    fh.write(json.dumps({
        "t": datetime.now(timezone.utc).isoformat(),
        "action": "OPERATOR-SLATE",
        "actor": "operator (Brock, via claude-code)",
        "why": f"🎯 DIAL slate: {added} narrowed-gate shadow twins from the dial-in farm + struck-cell autopsy; zero authority, ordinary bars; struck parents remain struck",
        "dry_run": False,
        "result": {"ok": True, "added": added},
    }) + "\n")
from config.cell_schema import validate_file
bad = [f.name for f in (REPO / "config" / "cells").glob("*.json")
       if (getattr(validate_file(f), "errors", None) or [])]
print("validation:", "CLEAN" if not bad else f"INVALID: {bad}")
sys.exit(0 if not bad else 1)
