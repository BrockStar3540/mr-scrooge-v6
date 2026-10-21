#!/usr/bin/env python3
"""ops/state_commit.py — commit machine-written config state (B-126).

The governor, the commissioner, dashboard flips and the counterpart-audit cron
all WRITE tracked files under config/ (cell setup statuses, the popper per_cell
map) but nothing ever COMMITTED them: the livelog cron stages only livelog/ +
README.md. Machine state stranded in the working tree for days, and a
`git checkout -- config/` (deploy reset, clone refresh) would silently
resurrect demoted cells. This cron closes that gap: hourly, any modified
tracked file under config/ is committed with a message that names the actual
per-setup status flips (diffed semantically vs HEAD — the JSON re-serialization
churn is thousands of lines of key-reorder noise per flip).

Commits only ` M` (tracked, modified) paths under config/ — never untracked
files, never anything another process staged. Fail-soft everywhere: an
unreadable file (mid-write race) or a push failure leaves the tree for the
next hourly run.

Since 2026-10-21 (issue #9) the same run also refreshes the PUBLIC hypothesis
registry (research/tools/registry_publish.py -> research/registry/) and commits
that directory on its own, path-limited, so nothing else staged rides along.
Registry-only pushes are data-only for the pre-push hook (no suite run).
"""
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _git(*args, **kw):
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True,
                          text=True, **kw)


def modified_config_paths():
    """Tracked-and-modified paths under config/ (ignores untracked/staged)."""
    out = _git("status", "--porcelain", "--", "config/").stdout
    paths = []
    for ln in out.splitlines():
        if ln[:2] == " M":
            paths.append(ln[3:].strip())
    return paths


def _setups_by_id(cell_doc):
    """{session: {setup_id: setup}} for a cell-config document."""
    out = {}
    for sess, body in (cell_doc.get("sessions") or {}).items():
        out[sess] = {}
        for s in body.get("setups", []):
            sid = s.get("id") or s.get("setup_id") or s.get("name")
            if sid:
                out[sess][sid] = s
    return out


def summarize_cell(path, old_doc, new_doc):
    """Human lines for what actually changed in one cell config."""
    pair = Path(path).stem
    lines = []
    old_s, new_s = _setups_by_id(old_doc), _setups_by_id(new_doc)
    for sess in sorted(set(old_s) | set(new_s)):
        so, sn = old_s.get(sess, {}), new_s.get(sess, {})
        for sid in sorted(set(so) | set(sn)):
            a, b = so.get(sid), sn.get(sid)
            if a is None:
                lines.append(f"{pair}/{sess}/{sid}: + new "
                             f"({b.get('status', '?')})")
            elif b is None:
                lines.append(f"{pair}/{sess}/{sid}: removed")
            elif a.get("status") != b.get("status"):
                lines.append(f"{pair}/{sess}/{sid}: "
                             f"{a.get('status')} -> {b.get('status')}")
    return lines


def summarize_pp(old_doc, new_doc):
    """Human lines for popper per_cell map changes."""
    po = (old_doc.get("per_cell") or {})
    pn = (new_doc.get("per_cell") or {})
    lines = []
    for k in sorted(set(po) | set(pn)):
        if k not in po:
            lines.append(f"pp per_cell + {k}={pn[k]}")
        elif k not in pn:
            lines.append(f"pp per_cell - {k}")
        elif po[k] != pn[k]:
            lines.append(f"pp per_cell {k}: {po[k]} -> {pn[k]}")
    return lines


def build_summary(paths):
    """(commit_message, committable_paths). Paths that fail to parse are
    dropped from THIS run (mid-write race) and picked up next hour."""
    lines, ok_paths = [], []
    for p in paths:
        head = _git("show", f"HEAD:{p}")
        if head.returncode != 0:
            continue  # not in HEAD (shouldn't happen for ' M') — skip
        try:
            old_doc = json.loads(head.stdout)
            new_doc = json.loads((REPO / p).read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if p.startswith("config/cells/"):
            changed = summarize_cell(p, old_doc, new_doc)
            lines += changed
            if not changed:
                lines.append(f"{Path(p).stem}: serialization churn only")
        elif p.endswith("pp_config.json"):
            changed = summarize_pp(old_doc, new_doc)
            lines += changed or [f"{p}: changed"]
        else:
            lines.append(f"{p}: changed")
        ok_paths.append(p)
    if not ok_paths:
        return None, []
    flips = [ln for ln in lines if " -> " in ln or ": + new" in ln]
    head_line = (f"state: {len(flips)} setup change(s) across "
                 f"{len(ok_paths)} file(s)" if flips else
                 f"state: sync {len(ok_paths)} machine-written config file(s)")
    body = "\n".join(lines)
    return head_line + "\n\n" + body, ok_paths


REGISTRY_DIR = "research/registry"
_CODE_ROOT = Path(__file__).resolve().parents[1]


def publish_registry():
    """Refresh research/registry/ (issue #9). Fail-soft: a publisher error
    never blocks the config commit."""
    if str(_CODE_ROOT) not in sys.path:
        sys.path.insert(0, str(_CODE_ROOT))
    try:
        from research.tools import registry_publish
        return registry_publish.publish(repo=REPO)
    except Exception as exc:  # noqa: BLE001 — fail-soft by contract
        print(f"state_commit: registry publish failed: {exc}", file=sys.stderr)
        return None


def registry_paths():
    """This run's own outputs under research/registry/ (new or modified)."""
    out = _git("status", "--porcelain", "--untracked-files=all", "--",
               REGISTRY_DIR).stdout
    return [ln[3:].strip() for ln in out.splitlines()
            if ln[:2] in (" M", "??", "M ", "A ", "AM", "MM")]


def commit_registry(summary):
    """Commit research/registry/ alone. Returns True if a commit landed."""
    paths = registry_paths()
    if not paths:
        return False
    _git("add", "--", *paths)
    s = summary or {}
    msg = (f"registry: M_ever={s.get('M_ever', '?')}, "
           f"{s.get('bar_rows', 0)} bar-score change(s), "
           f"{s.get('cheater_rows', 0)} cheater-score row(s), "
           f"{s.get('decisions', '?')} decisions")
    r = _git("commit", "-q", "-m", msg,
             "-m", "Auto-committed by ops/state_commit.py (issue #9 public registry).",
             "--", *paths)
    if r.returncode != 0:
        print(f"state_commit: registry commit failed: {r.stderr.strip()}",
              file=sys.stderr)
        return False
    return True


def commit_config():
    """Commit machine-written config state. Returns True if a commit landed."""
    paths = modified_config_paths()
    if not paths:
        print("state_commit: clean")
        return False
    msg, ok_paths = build_summary(paths)
    if not ok_paths:
        print("state_commit: all candidates unreadable this run — deferring")
        return False
    _git("add", "--", *ok_paths)
    if _git("diff", "--cached", "--quiet").returncode == 0:
        print("state_commit: nothing staged")
        return False
    r = _git("commit", "-q", "-m", msg,
             "-m", "Auto-committed by ops/state_commit.py (B-126).")
    if r.returncode != 0:
        print(f"state_commit: commit failed: {r.stderr.strip()}",
              file=sys.stderr)
        return False
    print(f"state_commit: committed {len(ok_paths)} file(s)")
    return True


def main():
    committed = commit_config()
    if commit_registry(publish_registry()):
        print("state_commit: committed research/registry/")
        committed = True
    if not committed:
        return 0
    p = _git("push", "-q")
    if p.returncode != 0:
        print(f"state_commit: push failed (will retry via next commit): "
              f"{p.stderr.strip()}", file=sys.stderr)
        return 0
    print("state_commit: pushed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
