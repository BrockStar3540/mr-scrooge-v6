"""tests/test_registry_publish.py — the public hypothesis registry (issue #9).

research/tools/registry_publish.py turns the gitignored governor registry,
ledger and score snapshots into research/registry/. The repo is public and
trades real money, so the sanitizer is tested as hard as the parsing.
"""
import json
from datetime import datetime, timezone

import pytest

from research.tools import registry_publish as rp

T0 = "2026-10-20T06:35:00+00:00"


def test_sanitize_redacts_ips_accounts_tokens_and_mail():
    s = rp.sanitize("from 100.64.1.2:8084 acct 101-001-1234567-001 tok ghp_"
                    "abcdefghijklmnopqrstuvwxyz0123 mail a.b@example.com ok")
    for leaked in ("100.64.1.2", "101-001-1234567-001", "ghp_abc", "a.b@example.com"):
        assert leaked not in s
    assert s.endswith(" ok")
    assert rp.sanitize("127.0.0.1:38938") == "127.0.0.1:38938"


def test_parse_scores_reads_the_governor_format():
    why = ("v2 n=13 days=8 net_avg=+6.17p blcb=+5.19 q=0.004 7d=6.2(4) "
           "[executable-exit-v2]; family n=7 net=-205.1p ($-84.27) [broker]")
    s = rp.parse_scores(why)
    assert s["bar"] == {"n": 13, "days": 8, "net_avg": 6.17, "block_lcb": 5.19,
                        "q": 0.004, "recent_avg": 6.2, "recent_n": 4}
    assert s["family"] == {"n": 7, "net_pips": -205.1}


def test_parse_scores_handles_none_fields_and_truth_gate():
    s = rp.parse_scores("v2 n=1 days=1 net_avg=-0.20p blcb=None q=None 7d=-0.2(1) [x]")
    assert s["bar"]["block_lcb"] is None and s["bar"]["q"] is None
    t = rp.parse_scores("vc +10.1p/cyc CONTRADICTS broker $-0.32 over 2 fill(s)")
    assert t["truth_gate"] == {"virtual_pips_per_cycle": 10.1, "broker_usd": -0.32, "fills": 2}


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "data").mkdir()
    cells = tmp_path / "config" / "cells"
    cells.mkdir(parents=True)
    cells.joinpath("EUR_USD.json").write_text(json.dumps({"pair": "EUR_USD", "sessions": {
        "ny": {"setups": [{"id": "a_short", "status": "PROBE"},
                          {"id": "b_long", "status": "SHADOW"}]}}}))
    (tmp_path / "config" / "governor_config.json").write_text(json.dumps({"fdr_q": 0.1}))
    reg = {"EUR_USD|ny|a_short": {"first_seen": T0, "hashes": ["h1", "h2"]},
           "EUR_USD|ny|b_long": {"first_seen": T0, "hashes": ["h3"]},
           "EUR_USD|ny|gone": {"first_seen": T0, "hashes": ["h4"]}}
    (tmp_path / "data" / "hypothesis_registry.json").write_text(json.dumps(reg))
    led = [
        {"t": T0, "action": "PROMOTE", "pair": "EUR_USD", "session": "ny", "setup": "a_short",
         "why": "v2 n=13 days=8 net_avg=+6.17p blcb=+5.19 q=0.004 7d=6.2(4) [x]",
         "dry_run": False, "result": {"ok": True, "status": "PROBE"}},
        {"t": T0, "action": "PROMOTE", "pair": "EUR_USD", "session": "ny", "setup": "b_long",
         "why": "v2 n=10 days=5 net_avg=+3.00p blcb=+1.00 q=0.050 7d=1.0(2) [x]",
         "dry_run": True, "result": {"ok": True, "dry_run": True}},
        {"t": T0, "action": "GOVERNOR-FLIP", "actor": "governor", "source": "127.0.0.1:1",
         "pair": "EUR_USD", "session": "ny", "setup": "gone", "dry_run": False,
         "result": {"ok": True, "old_status": "SHADOW", "status": "ACTIVE"}},
        {"t": T0, "action": "OPERATOR-SLATE", "actor": "operator (x)", "why": "added 140",
         "dry_run": False},
    ]
    (tmp_path / "data" / "governor_ledger.jsonl").write_text(
        "".join(json.dumps(x) + "\n" for x in led) + "{broken\n")
    snaps = []
    for t in ("2026-10-19T01:35:00+00:00", "2026-10-19T02:35:00+00:00",
              "2026-10-20T01:35:00+00:00", "2026-10-21T01:35:00+00:00"):
        for k in ("EUR_USD|ny|a_short", "EUR_USD|ny|b_long"):
            snaps.append({"t": t, "key": k, "status": "SHADOW", "heat": None, "trust": None,
                          "n_cycles": 0, "eligible": k.endswith("b_long"), "promoted": False})
    (tmp_path / "data" / "score_snapshots.jsonl").write_text(
        "".join(json.dumps(x) + "\n" for x in snaps))
    return tmp_path


BOARD = {"generated": "2026-10-21T00:19:00+00:00", "rows": [
    {"cell": "EUR_USD/ny", "setup": "a_short", "side": "short", "status": "PROBE", "strikes": 0,
     "era": {"n": 21, "days": 9, "avg": 8.83, "lcb": 6.12, "q": 0.0014, "promotable": True,
             "codes": []}},
    {"cell": "EUR_USD/ny", "setup": "b_long", "side": "long", "status": "SHADOW", "strikes": 1,
     "era": None},
]}
NOW = datetime(2026, 10, 21, 0, 20, tzinfo=timezone.utc)


def _read(p):
    return [json.loads(x) for x in p.read_text().splitlines()]


def test_no_registry_means_no_publish(tmp_path):
    assert rp.publish(repo=tmp_path, board={}) is None
    assert not (tmp_path / "research").exists()


def test_publish_writes_registry_decisions_and_scores(repo):
    s = rp.publish(repo=repo, now=NOW, board=BOARD)
    out = repo / "research" / "registry"
    doc = json.loads((out / "registry.json").read_text())
    assert doc["counts"]["M_ever"] == 3
    assert doc["counts"]["config_versions"] == 4
    assert doc["counts"]["dry_run_rows"] == 1 and doc["counts"]["unparseable_rows"] == 1
    a = doc["setups"]["EUR_USD|ny|a_short"]
    assert a["status"] == "PROBE" and a["ever_seated"] and a["decisions"] == {"PROMOTE": 1}
    assert a["bar_score"]["block_lcb"] == 6.12 and a["bar_score"]["promotable"] is True
    assert doc["setups"]["EUR_USD|ny|gone"]["status"] == "REMOVED"
    assert doc["setups"]["EUR_USD|ny|gone"]["ever_seated"]          # flipped ACTIVE once
    assert doc["setups"]["EUR_USD|ny|b_long"]["ever_seated"] is False
    dec = _read(out / "decisions.jsonl")
    assert [d["action"] for d in dec] == ["PROMOTE", "GOVERNOR-FLIP", "OPERATOR-SLATE"]
    assert dec[0]["bar"]["q"] == 0.004 and dec[0]["status_after"] == "PROBE"
    assert dec[2]["scope"] == "book" and dec[2]["by"] == "operator"
    assert "source" not in dec[1]
    bars = _read(out / "bar_scores" / "2026-10.jsonl")
    assert {b["key"] for b in bars} == {"EUR_USD|ny|a_short", "EUR_USD|ny|b_long"}
    # only complete UTC days (< 10-21) are summarised; one row per changed day
    ch = _read(out / "cheater_scores" / "2026-10.jsonl")
    assert sorted({c["date"] for c in ch}) == ["2026-10-19"]
    assert doc["setups"]["EUR_USD|ny|b_long"]["snapshot_runs"]["eligible"] == 3
    assert s["bar_rows"] == 2


def test_second_publish_is_incremental_and_quiet(repo):
    rp.publish(repo=repo, now=NOW, board=BOARD)
    out = repo / "research" / "registry"
    before = (out / "bar_scores" / "2026-10.jsonl").read_text()
    s = rp.publish(repo=repo, now=NOW, board=BOARD)               # same board: nothing new
    assert s["bar_rows"] == 0 and s["cheater_rows"] == 0
    assert (out / "bar_scores" / "2026-10.jsonl").read_text() == before
    b2 = json.loads(json.dumps(BOARD))
    b2["generated"] = "2026-10-21T01:19:00+00:00"
    b2["rows"][0]["era"]["n"] = 22                                  # one setup's evidence moved
    later = datetime(2026, 10, 22, 0, 20, tzinfo=timezone.utc)
    s = rp.publish(repo=repo, now=later, board=b2)
    assert s["bar_rows"] == 1
    # 10-21 is now complete and counted once; earlier days are not re-counted
    doc = json.loads((out / "registry.json").read_text())
    assert doc["setups"]["EUR_USD|ny|b_long"]["snapshot_runs"]["runs"] == 4


def test_board_outage_is_fail_soft(repo):
    def boom():
        raise OSError("refused")
    s = rp.publish(repo=repo, now=NOW, fetch=boom)
    assert s["board"].startswith("unavailable") and s["bar_rows"] == 0
    assert (repo / "research" / "registry" / "registry.json").exists()


def test_published_tree_has_no_secret_shapes(repo):
    rp.publish(repo=repo, now=NOW, board=BOARD)
    blob = "".join(p.read_text() for p in (repo / "research" / "registry").rglob("*.json*"))
    for rx in rp._REDACT[:4]:
        assert not rx.search(blob.replace("127.0.0.1", ""))


# ── the pre-push hook treats registry-only pushes as data ───────────────────
def _hook_data_only(tmp_path, files):
    import subprocess
    from pathlib import Path
    hook = Path(__file__).resolve().parents[1] / "ops" / "hooks" / "pre-push"
    fn = hook.read_text().split("data_only_push() {", 1)[1].split("\n}\n", 1)[0]
    run = lambda *a: subprocess.run(a, cwd=tmp_path, capture_output=True, text=True)
    run("git", "init", "-q")
    run("git", "config", "user.email", "t@t")
    run("git", "config", "user.name", "t")
    (tmp_path / "seed").write_text("x")
    run("git", "add", "-A")
    run("git", "commit", "-q", "-m", "seed")
    base = run("git", "rev-parse", "HEAD").stdout.strip()
    for f in files:
        p = tmp_path / f
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("y")
    run("git", "add", "-A")
    run("git", "commit", "-q", "-m", "c")
    head = run("git", "rev-parse", "HEAD").stdout.strip()
    script = ("ZERO=0000000000000000000000000000000000000000\n"
              f"REFS='refs/heads/main {head} refs/heads/main {base}'\n"
              "data_only_push() {" + fn + "\n}\ndata_only_push")
    return run("bash", "-c", script).returncode == 0


def test_prepush_registry_only_push_is_data_only(tmp_path):
    assert _hook_data_only(tmp_path, ["research/registry/registry.json",
                                      "research/registry/bar_scores/2026-10.jsonl"])


def test_prepush_registry_plus_code_runs_the_suite(tmp_path):
    assert not _hook_data_only(tmp_path, ["research/registry/registry.json",
                                          "research/tools/registry_publish.py"])
