"""tests/test_state_commit_registry.py — the :20 state commit also publishes
the public hypothesis registry (issue #9), path-limited and fail-soft."""
import json
import subprocess

import pytest

import ops.state_commit as sc


def _run(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    _run(tmp_path, "init", "-q")
    _run(tmp_path, "config", "user.email", "t@t")
    _run(tmp_path, "config", "user.name", "t")
    (tmp_path / "config" / "cells").mkdir(parents=True)
    (tmp_path / "config" / "cells" / "EUR_USD.json").write_text(json.dumps({"sessions": {}}))
    (tmp_path / "other.txt").write_text("a")
    _run(tmp_path, "add", "-A")
    _run(tmp_path, "commit", "-q", "-m", "seed")
    monkeypatch.setattr(sc, "REPO", tmp_path)
    return tmp_path


def _fake_publish(repo):
    def pub():
        d = repo / "research" / "registry" / "bar_scores"
        d.mkdir(parents=True, exist_ok=True)
        (repo / "research" / "registry" / "registry.json").write_text("{}\n")
        (d / "2026-10.jsonl").write_text("{}\n")
        return {"M_ever": 3, "bar_rows": 2, "cheater_rows": 0, "decisions": 5}
    return pub


def test_registry_committed_alone_leaving_other_staged_work(repo, monkeypatch):
    monkeypatch.setattr(sc, "publish_registry", _fake_publish(repo))
    (repo / "other.txt").write_text("b")
    _run(repo, "add", "other.txt")                         # someone else's staged change
    assert sc.main() == 0                                  # push fails (no remote): fail-soft
    log = _run(repo, "log", "-1", "--format=%s").stdout
    assert log.startswith("registry: M_ever=3, 2 bar-score change(s)")
    shown = _run(repo, "show", "--name-only", "--format=", "HEAD").stdout.split()
    assert sorted(shown) == ["research/registry/bar_scores/2026-10.jsonl",
                             "research/registry/registry.json"]
    assert _run(repo, "diff", "--cached", "--name-only").stdout.split() == ["other.txt"]


def test_unchanged_registry_makes_no_commit(repo, monkeypatch):
    monkeypatch.setattr(sc, "publish_registry", _fake_publish(repo))
    sc.main()
    head = _run(repo, "rev-parse", "HEAD").stdout
    sc.main()
    assert _run(repo, "rev-parse", "HEAD").stdout == head


def test_publisher_crash_is_fail_soft(repo, monkeypatch):
    import research.tools.registry_publish as rp

    def boom(**_):
        raise RuntimeError("bad input")
    monkeypatch.setattr(rp, "publish", boom)
    assert sc.publish_registry() is None
    assert sc.main() == 0
    assert "seed" in _run(repo, "log", "-1", "--format=%s").stdout
