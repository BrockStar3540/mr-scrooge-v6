"""The Commissioner (Brock, 2026-07-31: 'all automated'): staged, fail-closed
autonomous commissioning. Tests drive the PRODUCTION main() with the battery
and filesystem stubbed — no snippet reproduction."""
import json
from datetime import datetime, timedelta, timezone
import ops.commissioner as com


def _setup(tmp_path, monkeypatch, battery_ok=True, stage="VALIDATING",
           passes=None, commissioned_t=None, ledger_lines=None,
           evidence=True, orphans=0):
    state = tmp_path / "commissioner_state.json"
    cfg = tmp_path / "governor_config.json"
    ledger = tmp_path / "ledger.jsonl"
    cfg.write_text(json.dumps({"cheater_promotion_enabled": False,
                               "cheater_max_seats": 1,
                               "allow_promotions": False}))
    state.write_text(json.dumps({"stage": stage, "passes": passes or [],
                                 "commissioned_t": commissioned_t}))
    ledger.write_text("".join(json.dumps(l) + "\n" for l in (ledger_lines or [])))
    monkeypatch.setattr(com, "STATE", state)
    monkeypatch.setattr(com, "GOV_CFG", cfg)
    monkeypatch.setattr(com, "LEDGER", ledger)
    monkeypatch.setattr(com, "VAULT_LOG", tmp_path / "vault.md")
    monkeypatch.setattr(com, "run_battery",
                        lambda: (battery_ok, evidence,
                                 {"stub": {"ok": battery_ok, "detail": ""}}))
    monkeypatch.setattr(com, "reconciler_orphans_since", lambda t: orphans)
    return state, cfg, ledger


def _iso(hours_ago):
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


def test_two_spaced_passes_commission_at_one_seat(tmp_path, monkeypatch):
    state, cfg, ledger = _setup(tmp_path, monkeypatch, passes=[_iso(7)])
    com.main()
    c = json.loads(cfg.read_text())
    s = json.loads(state.read_text())
    assert c["cheater_promotion_enabled"] is True
    assert c["cheater_max_seats"] == 1            # FORCED, not inherited
    assert c["allow_promotions"] is False         # never touched
    assert s["stage"] == "COMMISSIONED_1"
    assert any(json.loads(l)["action"] == "COMMISSION"
               for l in ledger.read_text().splitlines())


def test_pass_within_six_hours_does_not_count(tmp_path, monkeypatch):
    state, cfg, _ = _setup(tmp_path, monkeypatch, passes=[_iso(2)])
    com.main()
    assert json.loads(cfg.read_text())["cheater_promotion_enabled"] is False
    assert len(json.loads(state.read_text())["passes"]) == 1   # unchanged


def test_battery_failure_resets_validation(tmp_path, monkeypatch):
    state, cfg, _ = _setup(tmp_path, monkeypatch, battery_ok=False,
                           passes=[_iso(7)])
    com.main()
    assert json.loads(state.read_text())["passes"] == []
    assert json.loads(cfg.read_text())["cheater_promotion_enabled"] is False


def test_guard_failure_decommissions_immediately(tmp_path, monkeypatch):
    state, cfg, ledger = _setup(tmp_path, monkeypatch, battery_ok=False,
                                stage="COMMISSIONED_1", commissioned_t=_iso(24))
    cfg.write_text(json.dumps({"cheater_promotion_enabled": True,
                               "cheater_max_seats": 1,
                               "allow_promotions": False}))
    com.main()
    assert json.loads(cfg.read_text())["cheater_promotion_enabled"] is False
    assert json.loads(state.read_text())["stage"] == "VALIDATING"
    assert any(json.loads(l)["action"] == "DECOMMISSION"
               for l in ledger.read_text().splitlines())


def test_graduation_expands_to_two_seats(tmp_path, monkeypatch):
    t0 = _iso(24)
    state, cfg, ledger = _setup(
        tmp_path, monkeypatch, stage="COMMISSIONED_1", commissioned_t=t0,
        ledger_lines=[{"t": _iso(1), "action": "GRADUATE", "dry_run": False}])
    cfg.write_text(json.dumps({"cheater_promotion_enabled": True,
                               "cheater_max_seats": 1,
                               "allow_promotions": False}))
    com.main()
    assert json.loads(cfg.read_text())["cheater_max_seats"] == 2
    assert json.loads(state.read_text())["stage"] == "COMMISSIONED_2"


def test_pre_commission_graduation_does_not_expand(tmp_path, monkeypatch):
    state, cfg, _ = _setup(
        tmp_path, monkeypatch, stage="COMMISSIONED_1", commissioned_t=_iso(1),
        ledger_lines=[{"t": _iso(48), "action": "GRADUATE", "dry_run": False}])
    cfg.write_text(json.dumps({"cheater_promotion_enabled": True,
                               "cheater_max_seats": 1,
                               "allow_promotions": False}))
    com.main()
    assert json.loads(cfg.read_text())["cheater_max_seats"] == 1


# ── review round 5: health permits evaluation; EVIDENCE permits the probe ────

def test_health_alone_never_commissions(tmp_path, monkeypatch):
    # two spaced clean batteries, ZERO current qualifiers: healthy-but-
    # uncommissioned is the correct terminal state, indefinitely
    state, cfg, _ = _setup(tmp_path, monkeypatch, passes=[_iso(7)],
                           evidence=False)
    com.main()
    assert json.loads(cfg.read_text())["cheater_promotion_enabled"] is False
    s = json.loads(state.read_text())
    assert s["stage"] == "VALIDATING"
    assert len(s["passes"]) == 2          # health accrues; commission waits


def test_evidence_after_standing_health_commissions(tmp_path, monkeypatch):
    # health already proven (2 passes on file); a qualifier appearing NOW
    # commissions on this very invocation
    state, cfg, _ = _setup(tmp_path, monkeypatch,
                           passes=[_iso(14), _iso(7)], evidence=True)
    com.main()
    assert json.loads(cfg.read_text())["cheater_promotion_enabled"] is True
    assert json.loads(cfg.read_text())["cheater_max_seats"] == 1
    assert json.loads(state.read_text())["stage"] == "COMMISSIONED_1"


def test_expansion_blocked_by_reconciler_orphans(tmp_path, monkeypatch):
    state, cfg, _ = _setup(
        tmp_path, monkeypatch, stage="COMMISSIONED_1", commissioned_t=_iso(48),
        evidence=True, orphans=2,
        ledger_lines=[{"t": _iso(1), "action": "GRADUATE", "dry_run": False}])
    cfg.write_text(json.dumps({"cheater_promotion_enabled": True,
                               "cheater_max_seats": 1,
                               "allow_promotions": False}))
    com.main()
    assert json.loads(cfg.read_text())["cheater_max_seats"] == 1   # blocked


def test_expansion_blocked_without_second_qualifier(tmp_path, monkeypatch):
    state, cfg, _ = _setup(
        tmp_path, monkeypatch, stage="COMMISSIONED_1", commissioned_t=_iso(48),
        evidence=False, orphans=0,
        ledger_lines=[{"t": _iso(1), "action": "GRADUATE", "dry_run": False}])
    cfg.write_text(json.dumps({"cheater_promotion_enabled": True,
                               "cheater_max_seats": 1,
                               "allow_promotions": False}))
    com.main()
    assert json.loads(cfg.read_text())["cheater_max_seats"] == 1   # blocked
