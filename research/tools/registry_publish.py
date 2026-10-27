#!/usr/bin/env python3
"""research/tools/registry_publish.py — the PUBLIC hypothesis registry (issue #9).

The governor has kept `data/hypothesis_registry.json` since D-6: every
(pair, session, setup) it has ever scored, first-seen time and config hashes,
"so the deflation denominator is explicit and public". It was not public:
`data/*` is gitignored. This tool writes a public copy under research/registry/
and adds each setup's score at each governor decision. ops/state_commit.py runs
it hourly (:20) and commits the directory.

Outputs (research/registry/):
  registry.json        every setup ever registered: first_seen, cfg hashes,
                       status now, strikes, ever-seated flag, decision counts,
                       latest bar score. Rewritten every run.
  decisions.jsonl      every non-dry-run governor/operator ledger decision,
                       with the scores the ledger recorded parsed into fields.
                       Rebuilt from data/governor_ledger.jsonl every run.
  bar_scores/YYYY-MM.jsonl
                       the ordinary-lane bar evidence (era n, day-blocks, net
                       avg, block LCB, BH q, promotable, failure codes) for
                       EVERY setup, taken from the dashboard's Shadowboard (the
                       same engine and inputs the governor uses). A row is
                       written only when a setup's evidence changed.
  cheater_scores/YYYY-MM.jsonl
                       the Cheater-lane score from data/score_snapshots.jsonl
                       (status, heat, trust, cycles, eligible, promoted), one
                       row per setup per UTC day, written only on change.

Read-only towards everything the trader uses: it reads the ledger, the snapshot
file, the registry and config/cells, and the dashboard's cached board over
localhost. Cursor and last-written state live in data/registry_publish_state.json.
Fail-soft: any missing input skips that output for this run.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BOARD_URL = "http://127.0.0.1:8084/api/shadowboard"
SCHEMA = 1
# First row of bar_scores/: before this, the governor logged bar evidence only
# for setups it acted on, so every setup first seen earlier has a score gap.
BAR_SCORES_SINCE = "2026-10-21T20:49:20+00:00"

SEAT_STATUSES = ("PROBE", "ACTIVE")
# ledger actions that are about a setup's evidence or seat
SETUP_ACTIONS = {
    "PROMOTE", "PROMOTE-GATED", "PROMOTE-GATED-TRUTH", "CHEATER-PROBE",
    "CHEATER-HELD-T20S", "GRADUATE", "DEMOTE", "ERA-RESET", "METRIC-ERA-RESET",
    "FAM-GEAR-CHANGE", "GOVERNOR-FLIP", "OPERATOR-FLIP", "OPERATOR-SHED",
    "OPERATOR-RESEAT-PREP",
}
# ledger actions whose free text is a fixed governor format (kept verbatim)
_KEEP_WHY = {"PROMOTE", "PROMOTE-GATED", "PROMOTE-GATED-TRUTH", "CHEATER-PROBE",
             "CHEATER-HELD-T20S", "GRADUATE", "DEMOTE", "ERA-RESET",
             "METRIC-ERA-RESET", "FAM-GEAR-CHANGE", "GOVERNOR-FLIP"}
DEFAULT_TO = {"PROMOTE": "PROBE", "CHEATER-PROBE": "PROBE", "GRADUATE": "ACTIVE",
              "DEMOTE": "SHADOW", "OPERATOR-SHED": "DISABLED"}

# ── sanitizer: the repo is public and trades real money ─────────────────────
_REDACT = [
    re.compile(r"\b(?!127\.0\.0\.1\b)(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?\b"),   # IPv4 (not loopback)
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),          # e-mail
    re.compile(r"\b\d{3}-\d{3}-\d{7}-\d{3}\b"),                             # broker account id
    re.compile(r"\b(?:ghp|gho|github_pat|sk|xox[abp])[-_][A-Za-z0-9_-]{16,}"),  # tokens
    re.compile(r"\b[A-Za-z0-9_-]{40,}\b"),                                  # any long opaque string
]


def sanitize(text):
    if not isinstance(text, str):
        return text
    for rx in _REDACT:
        text = rx.sub("[redacted]", text)
    return text


# ── ledger → decisions ───────────────────────────────────────────────────────
_RX_V2 = re.compile(
    r"v2 n=(\d+) days=(\d+) net_avg=([+-]?[\d.]+)p blcb=(None|[+-]?[\d.]+) "
    r"q=(None|[\d.]+) 7d=(None|[+-]?[\d.]+)\((\d+)\)")
_RX_FAM = re.compile(r"family n=(\d+) net=([+-]?[\d.]+)p")
_RX_VC = re.compile(r"vc ([+-]?[\d.]+)p/cyc CONTRADICTS broker \$([+-]?[\d.]+) "
                    r"over (\d+) fill")


def _num(s):
    return None if s in (None, "None") else float(s)


def parse_scores(why):
    """Structured scores from a governor `why` string (None when absent)."""
    out = {}
    if not isinstance(why, str):
        return out
    m = _RX_V2.search(why)
    if m:
        out["bar"] = {"n": int(m[1]), "days": int(m[2]), "net_avg": float(m[3]),
                      "block_lcb": _num(m[4]), "q": _num(m[5]),
                      "recent_avg": _num(m[6]), "recent_n": int(m[7])}
    m = _RX_FAM.search(why)
    if m:
        out["family"] = {"n": int(m[1]), "net_pips": float(m[2])}
    m = _RX_VC.search(why)
    if m:
        out["truth_gate"] = {"virtual_pips_per_cycle": float(m[1]),
                             "broker_usd": float(m[2]), "fills": int(m[3])}
    return out


def mark_seated(seated, key, t, source):
    """Keep the EARLIEST evidence that a setup held a PROBE/ACTIVE seat."""
    cur = seated.get(key)
    if cur is None or (t and str(t) < str(cur.get("t") or "")):
        seated[key] = {"t": t, "source": source}


def ledger_key(d):
    if d.get("key"):
        return d["key"]
    if d.get("pair") and d.get("session") and d.get("setup"):
        return f'{d["pair"]}|{d["session"]}|{d["setup"]}'
    return None


def status_after(d):
    res = d.get("result") if isinstance(d.get("result"), dict) else {}
    st = d.get("new_status") or res.get("status")
    if st:
        return st
    if res.get("ok") or d.get("action") in ("CHEATER-PROBE",):
        return DEFAULT_TO.get(d.get("action"))
    return None


def decision_row(seq, d):
    action = d.get("action")
    key = ledger_key(d)
    row = {"seq": seq, "t": d.get("t"), "action": action, "key": key,
           "by": "operator" if str(d.get("actor", "")).startswith("operator")
           else (d.get("actor") or "governor").split(" ")[0]}
    if key is None or action not in SETUP_ACTIONS:
        row["scope"] = "book"
    sa = status_after(d)
    if sa:
        row["status_after"] = sa
    if "strikes" in d:
        row["strikes"] = d["strikes"]
    row.update(parse_scores(d.get("why")))
    why = d.get("why")
    if isinstance(why, str):
        row["why"] = sanitize(why if action in _KEEP_WHY or row.get("scope") == "book"
                              or row["by"] == "operator" else why[:400])
    return row


def build_decisions(ledger_path):
    """(rows, stats). Dry runs are counted, never published as decisions."""
    rows, dry, bad = [], 0, 0
    seq = 0
    try:
        fh = open(ledger_path)
    except OSError:
        return [], {"dry_run_rows": 0, "unparseable_rows": 0, "missing": True}
    with fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            seq += 1
            try:
                d = json.loads(line)
            except ValueError:
                bad += 1
                continue
            if d.get("dry_run") is True:
                dry += 1
                continue
            rows.append(decision_row(seq, d))
    return rows, {"dry_run_rows": dry, "unparseable_rows": bad}


# ── score_snapshots → daily cheater-lane rows ────────────────────────────────
def _r(x, dp=3):
    return None if x is None else round(float(x), dp)


def cheater_tuple(a):
    return [a.get("status"), _r(a.get("heat")), _r(a.get("trust")),
            a.get("n_cycles"), bool(a.get("eligible")), bool(a.get("promoted"))]


def scan_snapshots(path, cursor, today, last, counts, seated):
    """Aggregate complete UTC days from `cursor` on. Returns (new_rows,
    new_cursor). The current (incomplete) day is left for the next run."""
    rows = []
    try:
        fh = open(path, "rb")
    except OSError:
        return rows, cursor
    day_buf, day_date, day_start = {}, None, cursor

    def flush():
        for key in sorted(day_buf):
            a = day_buf[key]
            tup = cheater_tuple(a)
            if last.get(key) != tup:
                last[key] = tup
                rows.append({"date": day_date, "key": key, "status": tup[0],
                             "heat": tup[1], "trust": tup[2], "n_cycles": tup[3],
                             "eligible": tup[4], "promoted": tup[5]})

    with fh:
        fh.seek(cursor)
        pos = cursor
        for raw in fh:
            if not raw.endswith(b"\n"):
                break                      # partial line being written
            line_start, pos = pos, pos + len(raw)
            try:
                d = json.loads(raw)
            except ValueError:
                continue
            date = str(d.get("t", ""))[:10]
            if date >= today:
                pos = line_start
                break
            if date != day_date:
                if day_date is not None:
                    flush()
                day_buf, day_date, day_start = {}, date, line_start
            key = d.get("key")
            a = day_buf.setdefault(key, {"eligible": False, "promoted": False})
            for f in ("status", "heat", "trust", "n_cycles"):
                a[f] = d.get(f)
            a["eligible"] = a["eligible"] or bool(d.get("eligible"))
            a["promoted"] = a["promoted"] or bool(d.get("promoted"))
            c = counts.setdefault(key, [0, 0, 0, None, None])
            c[0] += 1
            c[1] += bool(d.get("eligible"))
            c[2] += bool(d.get("promoted"))
            c[3] = c[3] or d.get("t")
            c[4] = d.get("t")
            if d.get("status") in SEAT_STATUSES:
                mark_seated(seated, key, d.get("t"), "score_snapshots")
        if day_date is not None:
            flush()
    return rows, pos


# ── dashboard board → bar-score rows ─────────────────────────────────────────
def fetch_board(url=BOARD_URL, timeout=30):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read())


def bar_tuple(row):
    e = row.get("era") or {}
    return [row.get("status"), row.get("strikes"), e.get("n"), e.get("days"),
            e.get("avg"), e.get("lcb"), e.get("q"), e.get("promotable"),
            list(e.get("codes") or [])]


def board_rows(board):
    """{key: row} — one row per registry key; a retired side (EX-SIDE) never
    shadows the live one."""
    out = {}
    for r in board.get("rows") or []:
        cell, setup = r.get("cell", ""), r.get("setup")
        if "/" not in cell or not setup:
            continue
        key = cell.replace("/", "|", 1) + "|" + setup
        if key in out and r.get("status") == "EX-SIDE":
            continue
        out[key] = r
    return out


def bar_rows(board, last):
    gen = board.get("generated")
    rows = []
    for key, r in sorted(board_rows(board).items()):
        tup = bar_tuple(r)
        if last.get(key) != tup:
            last[key] = tup
            rows.append({"t": gen, "key": key, "status": tup[0], "strikes": tup[1],
                         "n": tup[2], "days": tup[3], "net_avg": tup[4],
                         "block_lcb": tup[5], "q": tup[6], "promotable": tup[7],
                         "codes": tup[8]})
    return rows


# ── config status ────────────────────────────────────────────────────────────
def config_status(repo):
    out = {}
    for f in sorted((repo / "config" / "cells").glob("*.json")):
        try:
            d = json.loads(f.read_text())
        except (OSError, ValueError):
            continue
        for sess, b in (d.get("sessions") or {}).items():
            for su in (b.get("setups") or []):
                out[f'{d.get("pair") or f.stem}|{sess}|{su.get("id")}'] = su.get("status", "?")
    return out


# ── output helpers ───────────────────────────────────────────────────────────
def _append_monthly(dirpath, rows, tfield):
    if not rows:
        return
    dirpath.mkdir(parents=True, exist_ok=True)
    by_month = {}
    for r in rows:
        by_month.setdefault(str(r.get(tfield) or "unknown")[:7], []).append(r)
    for month, rs in sorted(by_month.items()):
        with open(dirpath / f"{month}.jsonl", "a") as fh:
            for r in rs:
                fh.write(json.dumps(r, sort_keys=True) + "\n")


def _write_if_changed(path, text):
    try:
        if path.read_text() == text:
            return False
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    tmp.replace(path)
    return True


def load_state(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def score_gap(first_seen, bar_score):
    """(score_missing, score_missing_before) for one setup. A gap is never a
    zero: readers must skip the period, not score it (issue #9)."""
    try:
        early = datetime.fromisoformat(str(first_seen)) < datetime.fromisoformat(BAR_SCORES_SINCE)
    except ValueError:
        early = True                              # unknown first_seen: assume the gap
    now_missing = not bar_score or bar_score.get("n") is None
    return early or now_missing, (BAR_SCORES_SINCE if early else None)


def publish(repo=REPO, now=None, board=None, fetch=fetch_board):
    """One publish pass. Returns a short summary dict, or None when this
    checkout has no governor registry (a test or contributor clone)."""
    data, out = repo / "data", repo / "research" / "registry"
    reg_path = data / "hypothesis_registry.json"
    if not reg_path.exists():
        return None
    try:
        reg = json.loads(reg_path.read_text())
    except (OSError, ValueError):
        return {"skipped": "registry unreadable (mid-write)"}
    now = now or datetime.now(timezone.utc)
    st_path = data / "registry_publish_state.json"
    st = load_state(st_path)
    seated = st.setdefault("seated_seen", {})
    summary = {}

    # 1. ledger → decisions (deterministic rebuild)
    decisions, dstats = build_decisions(data / "governor_ledger.jsonl")
    dec_text = "".join(json.dumps(r, sort_keys=True) + "\n" for r in decisions)
    _write_if_changed(out / "decisions.jsonl", dec_text)
    summary["decisions"] = len(decisions)
    by_key = {}
    for r in decisions:
        k = r.get("key")
        if not k or r.get("scope") == "book":
            continue
        e = by_key.setdefault(k, {"counts": Counter(), "last": None})
        e["counts"][r["action"]] += 1
        e["last"] = {"t": r["t"], "action": r["action"]}
        if r.get("status_after") in SEAT_STATUSES:
            mark_seated(seated, k, r["t"], "ledger")

    # 2. score_snapshots → cheater-lane daily rows (incremental)
    counts = st.setdefault("snapshot_counts", {})
    last_ch = st.setdefault("cheater_last", {})
    ch_rows, cursor = scan_snapshots(data / "score_snapshots.jsonl",
                                     int(st.get("snapshot_cursor", 0)),
                                     now.strftime("%Y-%m-%d"), last_ch, counts, seated)
    _append_monthly(out / "cheater_scores", ch_rows, "date")
    st["snapshot_cursor"] = cursor
    summary["cheater_rows"] = len(ch_rows)

    # 3. live board → bar-score rows (only when the board was rebuilt)
    last_bar = st.setdefault("bar_last", {})
    try:
        board = board if board is not None else fetch()
    except Exception as exc:                      # dashboard down: skip, retry next hour
        board = None
        summary["board"] = f"unavailable ({type(exc).__name__})"
    b_rows = []
    if board and board.get("generated") and board.get("generated") != st.get("board_generated"):
        b_rows = bar_rows(board, last_bar)
        _append_monthly(out / "bar_scores", b_rows, "t")
        st["board_generated"] = board.get("generated")
    summary["bar_rows"] = len(b_rows)

    # 4. registry.json
    status = config_status(repo)
    for k, s in status.items():
        if s in SEAT_STATUSES:
            mark_seated(seated, k, now.isoformat(), "config")
    try:
        gcfg = json.loads((repo / "config" / "governor_config.json").read_text())
    except (OSError, ValueError):
        gcfg = {}
    setups = {}
    for k in sorted(reg):
        e = reg[k]
        dk = by_key.get(k, {})
        c = counts.get(k)
        lb = last_bar.get(k)
        setups[k] = {
            "first_seen": e.get("first_seen"),
            "cfg_hashes": list(e.get("hashes") or []),
            "status": status.get(k, "REMOVED"),
            "ever_seated": k in seated,
            "first_seated": (seated.get(k) or {}).get("t"),
            "seated_source": (seated.get(k) or {}).get("source"),
            "decisions": dict(sorted((dk.get("counts") or {}).items())),
            "last_decision": dk.get("last"),
            "snapshot_runs": ({"runs": c[0], "eligible": c[1], "promoted": c[2],
                               "first": c[3], "last": c[4]} if c else None),
            "bar_score": ({"t": st.get("board_generated"), "status": lb[0],
                           "strikes": lb[1], "n": lb[2], "days": lb[3],
                           "net_avg": lb[4], "block_lcb": lb[5], "q": lb[6],
                           "promotable": lb[7], "codes": lb[8]} if lb else None),
        }
        setups[k]["score_missing"], setups[k]["score_missing_before"] = score_gap(
            setups[k]["first_seen"], setups[k]["bar_score"])
    sc = Counter(v["status"] for v in setups.values())
    doc = {
        "schema": SCHEMA,
        "about": "Public copy of the Bar Governor's hypothesis registry. "
                 "See research/registry/README.md.",
        "registry_mtime": datetime.fromtimestamp(reg_path.stat().st_mtime,
                                                 timezone.utc).isoformat(),
        "board_generated": st.get("board_generated"),
        "bar_scores_since": BAR_SCORES_SINCE,
        "counts": {
            "M_ever": len(reg),
            "M_live": sum(1 for v in setups.values() if v["status"] in ("ACTIVE", "SHADOW")),
            "config_versions": sum(len(v["cfg_hashes"]) for v in setups.values()),
            "ever_seated": sum(1 for v in setups.values() if v["ever_seated"]),
            "score_missing": sum(1 for v in setups.values() if v["score_missing"]),
            "status": dict(sorted(sc.items())),
            "decisions_published": len(decisions),
            **dstats,
        },
        "bar": {k: gcfg.get(k) for k in (
            "allow_promotions", "allow_demotions", "min_raw_episodes",
            "min_independent_days", "bar_avg", "lcb_min", "bootstrap_reps",
            "bootstrap_confidence", "fdr_q", "fdr_family", "slippage_pips",
            "redemption_min_raw_episodes", "redemption_min_independent_days",
            "cheater_promotion_enabled")},
        "first_seen_by_date": dict(sorted(Counter(
            str(v["first_seen"])[:10] for v in setups.values()).items())),
        "setups": setups,
    }
    _write_if_changed(out / "registry.json", json.dumps(doc, indent=1, sort_keys=False) + "\n")
    st["last_run"] = now.isoformat()
    tmp = st_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(st))
    tmp.replace(st_path)
    summary["M_ever"] = len(reg)
    return summary


def seed_episode_seats(repo, episodes_path):
    """One-off backfill (run where the CPU is cheap, not on the live box):
    setups seated before the ledger existed show up only as episodes stamped
    while ACTIVE/PROBE. Adds them to the publisher state's ever-seated map."""
    st_path = repo / "data" / "registry_publish_state.json"
    st = load_state(st_path)
    seated = st.setdefault("seated_seen", {})
    try:
        aliases = {(r["cell"], r["setup"], r["side"]): r["as"] for r in
                   json.loads((repo / "config" / "setup_aliases.json").read_text())}
    except (OSError, ValueError):
        aliases = {}
    before = len(seated)
    for ep in json.loads(Path(episodes_path).read_text())["episodes"].values():
        if ep.get("status") not in SEAT_STATUSES:
            continue
        pair, sess = (ep["cell"].split("/") + ["?"])[:2]
        sid = aliases.get((ep["cell"], ep["setup"], ep["side"]), ep["setup"])
        mark_seated(seated, f"{pair}|{sess}|{sid}", ep.get("t"), "episode_stamp")
    st_path.write_text(json.dumps(st))
    return len(seated) - before


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="publish research/registry/")
    ap.add_argument("--seed-episode-seats", metavar="SHADOWBOARD_JSON",
                    help="one-off: add setups stamped ACTIVE/PROBE to ever-seated")
    a = ap.parse_args(argv)
    if a.seed_episode_seats:
        print(f"registry_publish: {seed_episode_seats(REPO, a.seed_episode_seats)} "
              "setup(s) added from episode stamps")
    s = publish()
    print(f"registry_publish: {s}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
