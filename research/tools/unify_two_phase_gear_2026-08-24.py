#!/usr/bin/env python3
"""research/tools/unify_two_phase_gear_2026-08-24.py — operator order
(Brock): "I want ALL strategies and probes, shadows, etc to engage 7.5 and
lock in 6.0" — with the t20 experiment kept (pre-registered wider-engage
trial; its gear IS its identity; scoreboard: wiki t20-shadow-scoreboard).

Every setup exit block (all statuses incl. DISABLED, so re-enables are
uniform) gets the deployed two-phase gear: engage 7.5 -> lock 6.0, then
steps trigger 9.0 / trail 2.0 (peak-2). sl_pips stays range-sized per
setup; mode/_class/trail_mult/min/max untouched. `_t20s` cells excluded.

Known cost (accepted by operator): per-cell cfg-hash changes reset stamp-era
clocks at the next governor tick — the promotion sample rebuilds under the
new gear (~500 eps/day book-wide; V-CYC re-replays itself on the 6h cron).
This unifies sim and live mechanics book-wide: mechanics-matched scoring
now measures the gear the cell would actually trade. Idempotent.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2] if "research" in str(Path(__file__).resolve()) else Path.home() / "mr-scrooge-v6"
sys.path.insert(0, str(REPO))

GEAR = {"trigger_pips": 9.0, "trail_pips": 2.0,
        "engage_pips": 7.5, "engage_lock_pips": 6.0}

changed, skipped_t20, untouched = 0, 0, 0
pairs_changed = set()
for f in sorted((REPO / "config" / "cells").glob("*.json")):
    cfg = json.loads(f.read_text())
    dirty = False
    for sess, b in (cfg.get("sessions") or {}).items():
        for s in (b.get("setups") or []):
            if "_t20s" in str(s.get("id", "")):
                skipped_t20 += 1
                continue
            ex = s.get("exit")
            if not isinstance(ex, dict):
                untouched += 1          # no override -> deployed defaults already
                continue
            if all(ex.get(k) == v for k, v in GEAR.items()):
                untouched += 1
                continue
            ex.update(GEAR)
            changed += 1
            dirty = True
    if dirty:
        f.write_text(json.dumps(cfg, indent=2) + "\n")
        pairs_changed.add(f.stem)

print(f"unified: {changed} setups | t20 kept: {skipped_t20} | already-uniform/no-override: {untouched}")
print(f"pairs touched: {len(pairs_changed)}")

ledger = REPO / "data" / "governor_ledger.jsonl"
with ledger.open("a") as fh:
    fh.write(json.dumps({
        "t": datetime.now(timezone.utc).isoformat(),
        "action": "OPERATOR-GEAR-UNIFY",
        "actor": "operator (Brock, via claude-code)",
        "why": (f"book-wide two-phase gear: engage 7.5 -> lock 6.0, steps 9/-2 on "
                f"{changed} setups (t20 twins kept: {skipped_t20}). Era clocks reset "
                "per cfg-hash policy and rebuild under the new gear - accepted cost; "
                "sim and live mechanics now match book-wide."),
        "dry_run": False,
        "result": {"ok": True, "setups_changed": changed, "t20_kept": skipped_t20},
    }) + "\n")
print("ledgered OPERATOR-GEAR-UNIFY")

from config.cell_schema import validate_file
bad = [f.name for f in (REPO / "config" / "cells").glob("*.json")
       if (getattr(validate_file(f), "errors", None) or [])]
print("validation:", "CLEAN" if not bad else f"INVALID: {bad}")
sys.exit(0 if not bad else 1)
