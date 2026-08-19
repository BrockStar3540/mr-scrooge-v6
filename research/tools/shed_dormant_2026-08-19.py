#!/usr/bin/env python3
"""research/tools/shed_dormant_2026-08-19.py — operator-ordered shed of the
dormant book (audit 2026-08-19, Brock: "shed the 94").

Source list: shadow_audit.py run 2026-08-19 07:23Z (/tmp/shadow_audit_full.txt,
archived in Dropbox session folder). Categories NEVER FIRED + STALLED + WENT
QUIET. Every flip: SHADOW -> DISABLED, guarded (only flips cells still SHADOW),
and ledgered as OPERATOR-SHED with attribution (B-125: no unattributed flips).
DISABLED rows remain on the board as tier-7 autopsies; the governor's docket
and the hypothesis registry stop paying for them. Manual re-enable only.

Note: this retires tc_vwapbb before the B-128 rewire ever produced a stamp —
operator decision: 18 days of silence post-fix is the verdict on the gate, not
the wiring.
"""
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path.home() / "mr-scrooge-v6"
AUDIT = Path("/tmp/shadow_audit_full.txt")

SECTIONS = ("STALLED", "WENT QUIET", "NEVER FIRED")

def parse_targets():
    text = AUDIT.read_text()
    targets = []
    current = None
    for line in text.splitlines():
        m = re.match(r"── ([A-Z ()\-]+?) \(\d+\)", line.strip("─ ").strip()) if line.startswith("──") else None
        if line.startswith("──"):
            name = line.strip("─ ").split("(")[0].strip()
            current = name if name in SECTIONS else None
            continue
        if current is None:
            continue
        m = re.match(r"\s+([A-Z]{3}_[A-Z]{3})/(\w+)/(\S+)", line)
        if m:
            sid = re.sub(r"eps0$", "", m.group(3))  # report glues eps0 onto long ids
            targets.append((m.group(1), m.group(2), sid))
    return targets

def main():
    targets = parse_targets()
    print(f"parsed {len(targets)} shed targets from audit report")
    now = datetime.now(timezone.utc).isoformat()
    ledger = REPO / "data" / "governor_ledger.jsonl"
    flipped, skipped = [], []
    by_pair = {}
    for pair, sess, sid in targets:
        by_pair.setdefault(pair, []).append((sess, sid))
    for pair, items in sorted(by_pair.items()):
        p = REPO / "config" / "cells" / f"{pair}.json"
        cfg = json.loads(p.read_text())
        changed = False
        for sess, sid in items:
            found = False
            for su in (cfg["sessions"].get(sess, {}).get("setups") or []):
                if su.get("id") == sid:
                    found = True
                    if su.get("status") == "SHADOW":
                        su["status"] = "DISABLED"
                        su["notes"] = ((su.get("notes") or "") +
                            " | SHED 2026-08-19 dormant-audit (operator); "
                            "DISABLED, manual re-enable only").strip(" |")
                        changed = True
                        flipped.append((pair, sess, sid))
                    else:
                        skipped.append((pair, sess, sid, su.get("status")))
            if not found:
                skipped.append((pair, sess, sid, "NOT-FOUND"))
        if changed:
            p.write_text(json.dumps(cfg, indent=2) + "\n")
    with ledger.open("a") as f:
        for pair, sess, sid in flipped:
            f.write(json.dumps({
                "t": now, "action": "OPERATOR-SHED",
                "actor": "operator (Brock, via claude-code audit session)",
                "pair": pair, "session": sess, "setup": sid,
                "why": ("dormant-book audit 2026-08-19: zero/stalled evidence "
                        "(NEVER FIRED / STALLED / WENT QUIET); SHADOW -> DISABLED, "
                        "manual re-enable only"),
                "dry_run": False,
                "result": {"ok": True, "old_status": "SHADOW", "status": "DISABLED"},
            }) + "\n")
    print(f"flipped {len(flipped)} SHADOW -> DISABLED; skipped {len(skipped)}")
    for s in skipped[:10]:
        print("  skipped:", s)
    # validate
    sys.path.insert(0, str(REPO))
    from config.cell_schema import validate_file
    bad = [f.name for f in (REPO / "config" / "cells").glob("*.json")
           if (getattr(validate_file(f), "errors", None) or [])]
    print("validation:", "CLEAN" if not bad else f"INVALID: {bad}")

if __name__ == "__main__":
    main()
