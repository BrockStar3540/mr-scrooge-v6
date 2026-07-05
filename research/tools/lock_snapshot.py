#!/usr/bin/env python3
"""research/tools/lock_snapshot.py — Capture governance snapshot for locked cells.

Usage:
  python3 research/tools/lock_snapshot.py          # print JSON to stdout
  python3 research/tools/lock_snapshot.py --write  # update config/locked_cells.json in place

For each locked cell, attaches a "snapshot" object with:
  - taken: UTC ISO timestamp
  - governance: (pair, session)-scoped live config values
  - throttle: { max_opens_per_session: 2 }
  - code_fingerprint: sha256 of canonical code/profile inputs

Also ensures top-level "overrides": [] key exists in the file.

The snapshot preserves all existing keys (baseline, alert_rules, lock_ts, etc.).
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# --- Repo root on sys.path so we can import config/modules ---
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from config.pairs import PAIR_SESSIONS
from config.sessions import SESSIONS
from modules.management.ratchet import _load_config as _exit_load
from modules.playmaker.playmaker import _pm_load
from modules.playmaker.lock_guard import compute_code_fingerprint

_LOCK_PATH = REPO / "config" / "locked_cells.json"


def _build_snapshot(cell: dict, pm: dict) -> dict:
    """Compute a fresh snapshot for one locked cell from current live config."""
    pair    = cell["pair"]
    session = cell["session"]

    # ── Governance ──────────────────────────────────────────────────────────

    # inverted_live: (pair, session) in inverted_live_cells
    ilc = pm.get("inverted_live_cells", frozenset())
    inverted_live = (pair, session) in ilc

    # inverted_directions: list of native directions direction-inverted for this cell
    # Captures which native directions in (pair, session) are in inverted_live_directions.
    # Stored as a list (JSON-serialisable); pick_best locked branch reads gov["inverted_directions"].
    ild = pm.get("inverted_live_directions", frozenset())
    inverted_directions = sorted(
        d for d in ("long", "short") if (pair, session, d) in ild
    )

    # disabled_long / disabled_short by native direction
    dc = pm.get("disabled_cells", frozenset())
    disabled_long  = (pair, session, "long")  in dc
    disabled_short = (pair, session, "short") in dc

    # session_enabled: session in PAIR_SESSIONS[pair]
    session_enabled = session in PAIR_SESSIONS.get(pair, [])

    # per-pair merged effective config (defaults + per_pair override)
    defaults  = dict(pm.get("defaults", {}))
    per_pair  = pm.get("per_pair", {})
    eff       = dict(defaults)
    eff.update(per_pair.get(pair) or {})
    min_direction_score = float(eff.get("min_direction_score", 0.25))
    min_dir_certainty   = float(eff.get("min_dir_certainty",   0.30))
    min_mom_certainty   = float(eff.get("min_mom_certainty",   0.25))
    cooldown_after_sl   = float(eff.get("cooldown_after_sl_min", 0.0))

    # per_cell_dir_cert_min/max: keyed (pair, session)
    pcdn = pm.get("per_cell_dir_cert_min", {})
    pcdx = pm.get("per_cell_dir_cert_max", {})
    dir_cert_min = pcdn.get((pair, session))
    dir_cert_max = pcdx.get((pair, session))

    # per_cell_mom_cert_min/max: keyed (pair, session)
    pcmn = pm.get("per_cell_mom_cert_min", {})
    pcmx = pm.get("per_cell_mom_cert_max", {})
    mom_cert_min = pcmn.get((pair, session))
    mom_cert_max = pcmx.get((pair, session))

    # per_cell_willr_range: keyed (pair, session, direction)
    pcwr = pm.get("per_cell_willr_range", {})
    _wl  = pcwr.get((pair, session, "long"))
    _ws  = pcwr.get((pair, session, "short"))
    willr_range_long  = list(_wl) if _wl is not None else None
    willr_range_short = list(_ws) if _ws is not None else None

    # per_cell_kc_up_range: keyed (pair, session, direction)
    pckur = pm.get("per_cell_kc_up_range", {})
    _kl   = pckur.get((pair, session, "long"))
    _ks   = pckur.get((pair, session, "short"))
    kc_up_range_long  = list(_kl) if _kl is not None else None
    kc_up_range_short = list(_ks) if _ks is not None else None

    # per_cell_aroon_range: keyed (pair, session, direction)
    # 2026-07-02: new field. Null if no aroon gate configured for this cell.
    pcar = pm.get("per_cell_aroon_range", {})
    _al  = pcar.get((pair, session, "long"))
    _as_ = pcar.get((pair, session, "short"))
    aroon_range_long  = list(_al)  if _al  is not None else None
    aroon_range_short = list(_as_) if _as_ is not None else None

    # initial_sl_pips from exit_config for this pair
    exit_cfg      = _exit_load(pair)
    initial_sl_pips = float(exit_cfg["initial_sl_pips"])

    governance = {
        "inverted_live":        inverted_live,
        "inverted_directions":  inverted_directions,
        "disabled_long":        disabled_long,
        "disabled_short":       disabled_short,
        "session_enabled":      session_enabled,
        "min_direction_score":  min_direction_score,
        "min_dir_certainty":    min_dir_certainty,
        "min_mom_certainty":    min_mom_certainty,
        "dir_cert_min":         dir_cert_min,
        "dir_cert_max":         dir_cert_max,
        "mom_cert_min":         mom_cert_min,
        "mom_cert_max":         mom_cert_max,
        "willr_range_long":     willr_range_long,
        "willr_range_short":    willr_range_short,
        "kc_up_range_long":     kc_up_range_long,
        "kc_up_range_short":    kc_up_range_short,
        "aroon_range_long":     aroon_range_long,
        "aroon_range_short":    aroon_range_short,
        "cooldown_after_sl_min": cooldown_after_sl,
        "initial_sl_pips":      initial_sl_pips,
    }

    # ── Code fingerprint ────────────────────────────────────────────────────
    fingerprint = compute_code_fingerprint(pair, session)

    return {
        "taken":            datetime.now(timezone.utc).isoformat(),
        "governance":       governance,
        "throttle":         {"max_opens_per_session": 2},
        "code_fingerprint": fingerprint,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true",
                    help="Update config/locked_cells.json in place (default: print to stdout)")
    args = ap.parse_args()

    # Load locked_cells.json
    try:
        data = json.loads(_LOCK_PATH.read_text())
    except Exception as exc:
        print(f"ERROR: cannot read {_LOCK_PATH}: {exc}", file=sys.stderr)
        sys.exit(1)

    # Ensure top-level "overrides" key exists
    if "overrides" not in data:
        data["overrides"] = []

    # Load live playmaker config once
    pm = _pm_load()

    # Build snapshots for each cell
    updated_cells = []
    for cell in data.get("cells", []):
        new_cell = dict(cell)
        snap = _build_snapshot(cell, pm)
        new_cell["snapshot"] = snap
        updated_cells.append(new_cell)

    data["cells"] = updated_cells

    if args.write:
        _LOCK_PATH.write_text(json.dumps(data, indent=2))
        print(f"Updated {_LOCK_PATH}", file=sys.stderr)
        # Print the result to stdout too for verification
        print(json.dumps(data, indent=2))
    else:
        print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
