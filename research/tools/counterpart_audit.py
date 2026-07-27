#!/usr/bin/env python3
"""research/tools/counterpart_audit.py — the MAE-flip counterpart audit.

Doctrine (Brock, 2026-07-27): a losing setup whose adverse excursion outsizes its
favorable excursion is a right-signal/wrong-wiring candidate — it earns a
COUNTERPART setup firing the opposite direction at the same trigger. Sides are
never flipped in place; the counterpart gets its own honest name
(<base>_counter_<side>), SHADOW status, a fresh era clock, and the governor
decides if the mirror is real.

Signature (config-side scored episodes, shadowboard store):
  episodes >= 5  AND  avg net240 < 0  AND  med_MAE >= 1.5 x med_MFE

Skipped: _t20s gear variants (not independent strategies), setups already
carrying a same-trigger opposite-side counterpart, DISABLED setups.

Usage:
  python3 research/tools/counterpart_audit.py           # report only
  python3 research/tools/counterpart_audit.py --wire    # append counterparts
"""
from __future__ import annotations
import argparse, copy, json, sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
CELLS = REPO / "config" / "cells"

MIN_EPS = 5
MAE_RATIO = 1.5


def board_rows():
    from ops import shadowboard as sb
    return sb._aggregate(sb._load())


def cond_key(conds):
    """Trigger identity: conditions minus prose."""
    clean = []
    for c in conds or []:
        clean.append({k: v for k, v in sorted(c.items())
                      if k not in ("note", "lineage")})
    return json.dumps(clean, sort_keys=True)


def counter_id(base_id, new_side):
    parts = base_id.split("_")
    if parts[-1] in ("long", "short"):
        parts = parts[:-1]
    return "_".join(parts) + f"_counter_{new_side}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wire", action="store_true")
    args = ap.parse_args()

    configs = {}
    for f in CELLS.glob("*.json"):
        try:
            configs[f.stem] = json.loads(f.read_text())
        except Exception:
            pass

    # index: (pair, sess) -> list of (setup dict) and trigger index
    trig_index = {}
    for pair, d in configs.items():
        for sess, b in (d.get("sessions") or {}).items():
            for su in (b.get("setups") or []):
                trig_index.setdefault((pair, sess), []).append(su)

    proposals = []
    for r in board_rows():
        if r.get("queued") or r["episodes"] < MIN_EPS:
            continue
        if r["setup"].endswith("_t20s") or r["status"] in ("DISABLED", "EX-SIDE"):
            continue
        if r["avg_net240"] is None or r["avg_net240"] >= 0:
            continue
        mfe, mae = r.get("med_mfe") or 0.0, r.get("med_mae") or 0.0
        if mfe <= 0 or mae < MAE_RATIO * mfe:
            continue
        pair, sess = r["cell"].split("/")
        base = next((s for s in trig_index.get((pair, sess), [])
                     if s.get("id") == r["setup"] and s.get("side") == r["side"]), None)
        if base is None:      # side no longer in config (aliased/renamed) — skip
            continue
        new_side = "short" if base["side"] == "long" else "long"
        tk = cond_key(base.get("conditions"))
        has_counter = any(s.get("side") == new_side and cond_key(s.get("conditions")) == tk
                          for s in trig_index[(pair, sess)])
        if has_counter:
            continue
        proposals.append((pair, sess, base, new_side, r))

    if not proposals:
        print("audit clean: no losing MAE-heavy setup lacks a counterpart")
        return

    hdr = "%-10s %-7s %-30s -> %-34s eps=%-3s avg=%-7s medMFE/MAE=%s/%s"
    for pair, sess, base, new_side, r in proposals:
        print(hdr % (pair, sess, base["id"], counter_id(base["id"], new_side),
                     r["episodes"], r["avg_net240"], r["med_mfe"], r["med_mae"]))

    if not args.wire:
        print(f"\n{len(proposals)} counterpart(s) proposed — rerun with --wire to append")
        return

    touched = set()
    for pair, sess, base, new_side, r in proposals:
        d = configs[pair]
        cp = copy.deepcopy(base)
        cp["id"] = counter_id(base["id"], new_side)
        cp["side"] = new_side
        cp["status"] = "SHADOW"
        cp["evidence"] = {
            "ev_seq": None,
            "source": (f"MAE-flip counterpart audit 2026-07-27: {base['id']} ({base['side']}) "
                       f"ran {r['episodes']} eps @ {r['avg_net240']}p/ep with medMFE/MAE "
                       f"{r['med_mfe']}/{r['med_mae']} — mirror is hypothesis, not validation"),
            "drift": "UNKNOWN",
            "n_floor_status": "fresh era — activation bar governs promotion",
        }
        cp["notes"] = (f"Counterpart of {base['id']} (which keeps its name-true side): same "
                       f"trigger, opposite direction, per the no-in-place-flips policy. "
                       f"The governor judges.")
        d["sessions"][sess]["setups"].append(cp)
        touched.add(pair)
        print(f"wired: {pair}/{sess}/{cp['id']}")
    for pair in touched:
        (CELLS / f"{pair}.json").write_text(json.dumps(configs[pair], indent=2) + "\n")
    print(f"{len(proposals)} counterpart(s) wired across {len(touched)} pair file(s)")


if __name__ == "__main__":
    main()
