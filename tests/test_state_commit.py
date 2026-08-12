"""tests/test_state_commit.py — B-126: machine-written config state must be
committed, not stranded.

The governor/commissioner/dashboard/counterpart-audit all write tracked files
under config/ that nothing committed (the livelog cron stages only livelog/ +
README.md); a `git checkout -- config/` would have resurrected demoted cells.
ops/state_commit.py commits them hourly with a semantic per-setup summary.
"""
import json
import subprocess

import pytest

import ops.state_commit as sc


def _run(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True,
                          text=True)


CELL = {
    "sessions": {
        "ny": {
            "notes": "x",
            "setups": [
                {"id": "alpha_fade_short", "status": "SHADOW", "side": "short"},
                {"id": "beta_lean_long", "status": "ACTIVE", "side": "long"},
            ],
        }
    }
}
PP = {"enabled": True, "per_cell": {"EUR_USD|ny|alpha_fade_short": False}}


@pytest.fixture
def repo(tmp_path, monkeypatch):
    _run(tmp_path, "init", "-q")
    _run(tmp_path, "config", "user.email", "t@t")
    _run(tmp_path, "config", "user.name", "t")
    cells = tmp_path / "config" / "cells"
    cells.mkdir(parents=True)
    (cells / "EUR_USD.json").write_text(json.dumps(CELL))
    (tmp_path / "config" / "pp_config.json").write_text(json.dumps(PP))
    _run(tmp_path, "add", "-A")
    _run(tmp_path, "commit", "-q", "-m", "seed")
    monkeypatch.setattr(sc, "REPO", tmp_path)
    return tmp_path


def _flip_status(repo, setup_id, new_status):
    p = repo / "config" / "cells" / "EUR_USD.json"
    doc = json.loads(p.read_text())
    for s in doc["sessions"]["ny"]["setups"]:
        if s["id"] == setup_id:
            s["status"] = new_status
    p.write_text(json.dumps(doc, sort_keys=True))  # reorder churn, like live


def test_clean_tree_is_noop(repo):
    assert sc.modified_config_paths() == []
    assert sc.main() == 0
    assert "seed" in _run(repo, "log", "-1", "--format=%s").stdout


def test_status_flip_named_in_summary(repo):
    _flip_status(repo, "alpha_fade_short", "PROBE")
    paths = sc.modified_config_paths()
    assert paths == ["config/cells/EUR_USD.json"]
    msg, ok = sc.build_summary(paths)
    assert ok == paths
    assert "EUR_USD/ny/alpha_fade_short: SHADOW -> PROBE" in msg
    assert "beta_lean_long" not in msg  # untouched setup stays out


def test_serialization_churn_only_still_commits_with_honest_message(repo):
    p = repo / "config" / "cells" / "EUR_USD.json"
    p.write_text(json.dumps(json.loads(p.read_text()), sort_keys=True))
    if not sc.modified_config_paths():  # seed happened to already be sorted
        pytest.skip("no churn produced")
    msg, ok = sc.build_summary(sc.modified_config_paths())
    assert "serialization churn only" in msg


def test_pp_per_cell_addition_named(repo):
    p = repo / "config" / "pp_config.json"
    doc = json.loads(p.read_text())
    doc["per_cell"]["GBP_USD|ny|beta_lean_long"] = False
    p.write_text(json.dumps(doc))
    msg, ok = sc.build_summary(sc.modified_config_paths())
    assert "pp per_cell + GBP_USD|ny|beta_lean_long=False" in msg


def test_new_setup_named(repo):
    p = repo / "config" / "cells" / "EUR_USD.json"
    doc = json.loads(p.read_text())
    doc["sessions"]["ny"]["setups"].append(
        {"id": "gamma_counter_long", "status": "SHADOW", "side": "long"})
    p.write_text(json.dumps(doc))
    msg, _ = sc.build_summary(sc.modified_config_paths())
    assert "EUR_USD/ny/gamma_counter_long: + new (SHADOW)" in msg


def test_main_commits_flip_and_survives_push_failure(repo):
    _flip_status(repo, "alpha_fade_short", "PROBE")
    assert sc.main() == 0  # push fails (no remote) but must stay fail-soft
    log = _run(repo, "log", "-1", "--format=%B").stdout
    assert "SHADOW -> PROBE" in log
    assert _run(repo, "status", "--porcelain", "--",
                "config/").stdout.strip() == ""


def test_midwrite_race_defers_without_commit(repo):
    (repo / "config" / "cells" / "EUR_USD.json").write_text('{"sessions": {tr')
    assert sc.main() == 0
    assert "seed" in _run(repo, "log", "-1", "--format=%s").stdout
    # file untouched for the next hourly run to retry
    assert sc.modified_config_paths() == ["config/cells/EUR_USD.json"]


def test_untracked_and_staged_files_never_touched(repo):
    (repo / "config" / "new_thing.json").write_text("{}")  # untracked
    assert sc.modified_config_paths() == []
