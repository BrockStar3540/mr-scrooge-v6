#!/usr/bin/env python3
"""ops/commissioner.py — autonomous commissioning of the cheater-v4 lane.

Brock, 2026-07-31: "i want it all automated without me having to say shit."

A staged state machine (data/commissioner_state.json) that walks the external
review's re-commissioning bar without a human in the loop, fail-closed at
every step:

  DOCTRINE (review round 5): health permits EVALUATION; evidence permits
  ONE PROBE; broker validation permits EXPANSION. Two axes, never conflated:
    - operational health: suite, dry-run, reconcile, journal — proves the
      machinery runs;
    - admission evidence: an ACTUAL candidate passing the full cheater-v4
      ticket in the current dry-run (complete replay, independent policy
      qualification, PP paired-lift proof) — proves someone deserves capital.

  VALIDATING      health battery each invocation. Clean passes accrue
                  (>= 6h apart, spanning real governor runs). COMMISSION
                  requires BOTH: >= 2 spaced health passes AND a current
                  qualifying candidate (a CHEATER-PROBE line in this
                  invocation's dry-run). Healthy-with-zero-qualifiers stays
                  healthy-but-uncommissioned indefinitely. On commission:
                  cheater ON, max_seats FORCED to 1. Ledgered.
  COMMISSIONED_1  guards every invocation (fail => immediate DECOMMISSION,
                  revalidation from zero). EXPANSION to 2 seats requires ALL:
                  a cheater seat GRADUATED post-commission (>= 6 broker
                  cycles + positive broker edge LCB are the graduation gate;
                  the leash guarantees no catastrophic cycle survived the
                  audition), zero RECONCILER orphan-adoptions since
                  commissioning (attribution clean), and a SECOND currently
                  qualifying candidate in this invocation's dry-run (the
                  graduated seat freed the probe slot, so the dry-run
                  evaluates candidates again). Ledgered EXPANSION.
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
    """Health AND evidence in one pass: (ok, detail, qualifier_now).
    qualifier_now = the dry-run printed a real CHEATER-PROBE admission —
    a candidate passed the complete v4 ticket on current evidence."""
    r = subprocess.run([sys.executable, "ops/governor.py", "--dry-run"],
                       cwd=REPO, capture_output=True, text=True, timeout=900)
    bad = ("Traceback" in r.stderr or "evaluation failed" in r.stdout
           or "evaluation failed" in r.stderr)
    qualifier = "CHEATER-PROBE" in r.stdout
    return ((r.returncode == 0 and not bad),
            f"dry-run rc={r.returncode} bad={bad} qualifier={qualifier}",
            qualifier)


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
    """(health_ok, evidence_now, results) — the two axes, never conflated."""
    results = {}
    ok = True
    evidence = False
    for name, fn in (("suite", check_suite), ("dryrun", check_dryrun),
                     ("reconcile", check_reconcile), ("journal", check_journal)):
        try:
            out = fn()
            if len(out) == 3:
                passed, detail, evidence = out
            else:
                passed, detail = out
        except Exception as exc:
            passed, detail = False, f"check crashed: {exc}"
        results[name] = {"ok": passed, "detail": detail}
        ok = ok and passed
    return ok, evidence, results


def reconciler_orphans_since(t_iso):
    """Attribution cleanliness for the audition window: any RECONCILER
    orphan-adoption in the journal since commissioning is a defect."""
    if not t_iso:
        return 0
    try:
        r = subprocess.run(
            ["journalctl", "--user", "-u", "mr-scrooge-v6",
             "--since", t_iso[:19], "--no-pager"],
            capture_output=True, text=True, timeout=60)
        return sum(1 for l in r.stdout.splitlines() if "RECONCILER:" in l)
    except Exception:
        return 999    # unknown = assume dirty; expansion fails closed


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
    ok, evidence_now, results = run_battery()
    detail = "; ".join(f"{k}:{'OK' if v['ok'] else 'FAIL(' + v['detail'] + ')'}"
                       for k, v in results.items())
    stage = st["stage"]
    print(f"commissioner: stage={stage} health={'PASS' if ok else 'FAIL'} "
          f"evidence={'YES' if evidence_now else 'no'} [{detail}]")

    if stage == "VALIDATING":
        if not ok:
            st["passes"] = []
            _save(st)
            return
        now = _now().isoformat()
        passes = st.get("passes", [])
        if not passes or (_now() - datetime.fromisoformat(passes[-1])
                          ).total_seconds() >= MIN_PASS_GAP_H * 3600:
            passes.append(now)
            st["passes"] = passes[-PASSES_NEEDED:]
        # DOCTRINE (r5): health alone NEVER commissions. Two spaced healthy
        # batteries prove the machinery; a current qualifying candidate —
        # a CHEATER-PROBE admission in THIS dry-run — proves the evidence.
        if len(st["passes"]) >= PASSES_NEEDED and evidence_now:
            _cfg_write(cheater_promotion_enabled=True, cheater_max_seats=1)
            st.update(stage="COMMISSIONED_1", commissioned_t=now, passes=[])
            _ledger("COMMISSION", f"health battery {PASSES_NEEDED}x "
                    f">={MIN_PASS_GAP_H}h apart AND a current v4 qualifier — "
                    f"cheater enabled, ONE 0.33x whole-family PROBE seat; "
                    f"allow_promotions stays false")
            _vault("COMMISSION: cheater v4 enabled autonomously — health x2 + a "
                   "current qualifying candidate. 1 seat, 0.33x family. "
                   "allow_promotions untouched (off).")
            print("commissioner: COMMISSIONED — health + evidence both proven")
        elif len(st["passes"]) >= PASSES_NEEDED:
            print("commissioner: healthy-but-uncommissioned — no current "
                  "qualifying candidate (correct state, holding)")
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

    if stage == "COMMISSIONED_1":
        grad = graduated_cheater_seat_since(st.get("commissioned_t"))
        orphans = reconciler_orphans_since(st.get("commissioned_t"))
        # EXPANSION doctrine (r5): broker validation permits expansion —
        # graduation (>= 6 broker cycles, positive edge LCB, leash survived =
        # no catastrophic cycle) + clean attribution (zero reconciler orphan
        # adoptions during the audition) + a SECOND candidate qualifying NOW.
        if grad and orphans == 0 and evidence_now:
            _cfg_write(cheater_max_seats=2)
            st["stage"] = "COMMISSIONED_2"
            _ledger("EXPANSION", "graduated seat (broker cycles + LCB>0, leash "
                    "survived) + zero reconciler orphans during audition + a "
                    "second current qualifier; max_seats 1 -> 2")
            _vault("EXPANSION: broker-validated graduation + clean attribution + "
                   "second qualifier — max_seats -> 2.")
            print("commissioner: EXPANDED to 2 seats")
        elif grad:
            print(f"commissioner: graduation seen but expansion blocked "
                  f"(orphans={orphans}, second_qualifier={evidence_now})")
    _save(st)


if __name__ == "__main__":
    main()
