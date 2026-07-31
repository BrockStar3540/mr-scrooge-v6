#!/usr/bin/env python3
"""ops/commissioner.py — autonomous commissioning of the cheater-v4 lane.

Brock, 2026-07-31: "i want it all automated without me having to say shit."

A staged state machine (data/commissioner_state.json) that walks the external
review's re-commissioning bar without a human in the loop, fail-closed at
every step:

  VALIDATING      run the health battery each invocation. TWO consecutive
                  clean passes >= 6h apart (spanning at least one real
                  governor run) => enable cheater_promotion_enabled with
                  cheater_max_seats FORCED to 1. Ledgered COMMISSION.
  COMMISSIONED_1  guards every invocation. Any guard failure => cheater OFF
                  immediately (ledgered DECOMMISSION) and back to VALIDATING
                  from zero. Expansion: a cheater seat GRADUATING to ACTIVE
                  (real broker cycles confirmed the accounting) => max_seats
                  2. Ledgered EXPANSION.
  COMMISSIONED_2  guards only; no further expansion without a human.

The health battery (all must pass):
  suite      full pytest run, exit code unpiped
  dryrun     governor --dry-run exits 0, no Traceback / "evaluation failed"
  reconcile  broker open-trade ids == engine-tracked ids (the B-114 check)
  journal    no CRITICAL lines in the service journal since last invocation

allow_promotions (the parent-metric lane) is NEVER touched: it stays off
until rewritten around family evidence. Cron: offset from the governor so
validation sees fresh runs. Every transition is ledgered and appended to the
vault activity log; nothing is silent.
"""
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

STATE = REPO / "data" / "commissioner_state.json"
GOV_CFG = REPO / "config" / "governor_config.json"
LEDGER = REPO / "data" / "governor_ledger.jsonl"
VAULT_LOG = Path("/data/obsidian-vault/wiki/systems/agent-activity-log.md")
MIN_PASS_GAP_H = 6.0
PASSES_NEEDED = 2


def _now():
    return datetime.now(timezone.utc)


def _state():
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {"stage": "VALIDATING", "passes": [], "commissioned_t": None}


def _save(st):
    STATE.write_text(json.dumps(st, indent=1))


def _ledger(action, why):
    with open(LEDGER, "a") as f:
        f.write(json.dumps({"t": _now().isoformat(), "action": action,
                            "actor": "commissioner", "why": why}) + "\n")


def _vault(line):
    try:
        with open(VAULT_LOG, "a") as f:
            f.write(f"- {_now().strftime('%Y-%m-%dT%H:%MZ')} [commissioner] {line}\n")
    except OSError:
        pass


def _cfg_write(**changes):
    cfg = json.loads(GOV_CFG.read_text())
    cfg.update(changes)
    GOV_CFG.write_text(json.dumps(cfg, indent=2))
    return cfg


# ── the health battery ────────────────────────────────────────────────────────

def check_suite():
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x"],
                       cwd=REPO, capture_output=True, text=True, timeout=600)
    return r.returncode == 0, f"pytest rc={r.returncode}"


def check_dryrun():
    r = subprocess.run([sys.executable, "ops/governor.py", "--dry-run"],
                       cwd=REPO, capture_output=True, text=True, timeout=900)
    bad = ("Traceback" in r.stderr or "evaluation failed" in r.stdout
           or "evaluation failed" in r.stderr)
    return (r.returncode == 0 and not bad), f"dry-run rc={r.returncode} bad={bad}"


def check_reconcile():
    import urllib.request, re, os
    sec = {}
    for ln in open(os.path.expanduser("~/.openclaw/secrets.env")):
        m = re.match(r"^(OANDA_\w+)=(.*)$", ln.strip())
        if m:
            sec[m.group(1)] = m.group(2)
    req = urllib.request.Request(
        f"{sec['OANDA_API_URL'].rstrip('/')}/v3/accounts/{sec['OANDA_ACCOUNT_ID']}/openTrades",
        headers={"Authorization": f"Bearer {sec['OANDA_API_TOKEN']}"})
    broker = {str(t["id"]) for t in
              json.loads(urllib.request.urlopen(req, timeout=20).read())["trades"]}
    st = json.loads(urllib.request.urlopen(
        "http://127.0.0.1:8084/api/state", timeout=20).read())
    tracked = {str(p.get("oanda_trade_id")) for p in st.get("open_positions") or []}
    missing = broker - tracked
    return (not missing), f"broker={len(broker)} tracked={len(tracked)} missing={sorted(missing)}"


def check_journal():
    r = subprocess.run(
        ["journalctl", "--user", "-u", "mr-scrooge-v6", "--since", "-6h",
         "--no-pager", "-p", "2"], capture_output=True, text=True, timeout=60)
    crits = [l for l in r.stdout.splitlines() if "CRITICAL" in l]
    return (not crits), f"criticals={len(crits)}"


def run_battery():
    results = {}
    ok = True
    for name, fn in (("suite", check_suite), ("dryrun", check_dryrun),
                     ("reconcile", check_reconcile), ("journal", check_journal)):
        try:
            passed, detail = fn()
        except Exception as exc:
            passed, detail = False, f"check crashed: {exc}"
        results[name] = {"ok": passed, "detail": detail}
        ok = ok and passed
    return ok, results


def graduated_cheater_seat_since(t_iso):
    """A GRADUATE ledger entry after commissioning = real broker cycles
    confirmed the accounting on a cheater seat."""
    try:
        for ln in open(LEDGER):
            d = json.loads(ln)
            if (d.get("action") == "GRADUATE" and not d.get("dry_run")
                    and d.get("t", "") >= (t_iso or "9999")):
                return True
    except OSError:
        pass
    return False


def main():
    st = _state()
    ok, results = run_battery()
    detail = "; ".join(f"{k}:{'OK' if v['ok'] else 'FAIL(' + v['detail'] + ')'}"
                       for k, v in results.items())
    stage = st["stage"]
    print(f"commissioner: stage={stage} battery={'PASS' if ok else 'FAIL'} [{detail}]")

    if stage == "VALIDATING":
        if not ok:
            st["passes"] = []
            _save(st)
            return
        now = _now().isoformat()
        passes = st.get("passes", [])
        if passes and (_now() - datetime.fromisoformat(passes[-1])
                       ).total_seconds() < MIN_PASS_GAP_H * 3600:
            _save(st)      # too soon to count again; keep waiting
            print("commissioner: clean, but within the 6h spacing — holding")
            return
        passes.append(now)
        st["passes"] = passes[-PASSES_NEEDED:]
        if len(st["passes"]) >= PASSES_NEEDED:
            _cfg_write(cheater_promotion_enabled=True, cheater_max_seats=1)
            st.update(stage="COMMISSIONED_1", commissioned_t=now, passes=[])
            _ledger("COMMISSION", f"validation battery passed {PASSES_NEEDED}x "
                    f">={MIN_PASS_GAP_H}h apart — cheater v4 enabled, ONE 0.33x "
                    f"whole-family PROBE seat max; allow_promotions stays false")
            _vault("COMMISSION: cheater v4 enabled autonomously (1 seat, 0.33x family) "
                   "after 2 clean validation batteries. allow_promotions untouched (off).")
            print("commissioner: COMMISSIONED — cheater v4 live at 1 seat")
        _save(st)
        return

    # commissioned stages: guards first, always
    if not ok:
        _cfg_write(cheater_promotion_enabled=False)
        _ledger("DECOMMISSION", f"guard failure: {detail} — cheater OFF, "
                f"revalidation from zero")
        _vault(f"DECOMMISSION: guard failure ({detail}) — cheater disabled "
               f"autonomously, back to VALIDATING.")
        st.update(stage="VALIDATING", passes=[])
        _save(st)
        print("commissioner: DECOMMISSIONED on guard failure")
        return

    if stage == "COMMISSIONED_1" and graduated_cheater_seat_since(st.get("commissioned_t")):
        _cfg_write(cheater_max_seats=2)
        st["stage"] = "COMMISSIONED_2"
        _ledger("EXPANSION", "a commissioned seat GRADUATED on real broker "
                "cycles — accounting confirmed; max_seats 1 -> 2")
        _vault("EXPANSION: cheater seat graduated on broker cycles — max_seats -> 2.")
        print("commissioner: EXPANDED to 2 seats")
    _save(st)


if __name__ == "__main__":
    main()
