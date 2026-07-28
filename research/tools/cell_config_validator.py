#!/usr/bin/env python3
"""research/tools/cell_config_validator.py — CLI shim over the canonical schema.

The schema itself lives in config/cell_schema.py (review round 2: production
code must not import from research/tools/, and there must be exactly ONE
implementation). This file keeps the CLI and the historical import surface.

Usage:
    python cell_config_validator.py config/cells/GBP_USD.json
    python cell_config_validator.py --all
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from config.cell_schema import (  # noqa: F401,E402  (re-exported surface)
    SchemaResult, ValidationErrors, VALID_CLASSES, VALID_PAIRS,
    VALID_SESSIONS, VALID_SIDES, VALID_STATUSES,
    validate_file, validate_pair_config,
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*", help="cell config JSON files")
    ap.add_argument("--all", action="store_true",
                    help="Validate all *.json files in config/cells/")
    ap.add_argument("--cells-dir", default=None,
                    help="Override path to config/cells/ directory")
    args = ap.parse_args()

    cells_dir = (Path(args.cells_dir) if args.cells_dir
                 else Path(__file__).resolve().parents[2] / "config" / "cells")
    files = (sorted(cells_dir.glob("*.json")) if args.all
             else [Path(f) for f in args.files])
    if not files:
        ap.error("no files given (use --all or list files)")

    fails = 0
    for f in files:
        errs = validate_file(f)
        if errs.errors:
            fails += 1
            print(f"FAIL {f}")
            for e in errs.errors:
                print(f"    • {e}")
        else:
            print(f"OK  {f}")
    print(f"\nSummary: {len(files) - fails} OK / {fails} FAIL / {len(files)} total")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
