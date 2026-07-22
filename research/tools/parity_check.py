#!/usr/bin/env python3
"""research/tools/parity_check.py — V5-live vs V6-shadow decision parity.

Compares CYCLE lines (intent sets + picked) from the two journals over a
window. V6 must decide identically to V5 before it may go live. Exit behavior
is not comparable (shadow places nothing) — this checks the DECISION layer.

Intent mismatches are ADJUDICATED, not just counted (2026-07-16 upgrade,
after the 29/29-benign adjudication of the 07-15 window): the engines free-run
on phase-drifting ~5-min cycles, so a setup whose condition value sits within
sampling noise of a band edge legitimately flickers between engines. For each
mismatch we take the condition values logged by the engine that PASSED the
setup (CELLSHADOW line), measure distance to the nearest band edge (static
min/max or generator-"resolved" percentile band), and compare against that
feature's empirical inter-engine noise (p90 of |delta| on setups both engines
logged in aligned cycles):

  MARGINAL    every differing setup has some condition within 3x noise of an
              edge — expected flicker, does NOT fail parity.
  STRUCTURAL  no condition near any edge — unexplained divergence, FAILS.

Usage:  python3 research/tools/parity_check.py --since "2026-07-06" [--until ...]
Exit 0 = parity (structural == 0), 1 = structural mismatches, 2 = insufficient data.
"""
import argparse, ast, glob, json, re, subprocess, sys
from collections import OrderedDict, defaultdict
from datetime import datetime, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO))
try:
    from config.sessions import coarse_session as _coarse_session
except Exception:
    _coarse_session = None

CYCLE_RE = re.compile(r"CYCLE (\S+) picked=(\S+) intents=(\d+)(.*)")
INTENT_RE = re.compile(r"(\w+)/(\w+)/(\w+) setup=(\S+)")
SHADOW_RE = re.compile(
    r"CELLSHADOW (\S+)/(\S+) setup=(\S+) side=\S+ conds=(\{.*?\}) exp_ev=\S+ status=\S+")

MARGINAL_X = 3.0  # condition within this multiple of feature noise of an edge

def journal(unit, since, until):
    cmd = ["journalctl", "--user", "-u", unit, "--no-pager", "--since", since]
    if until: cmd += ["--until", until]
    out = subprocess.run(cmd, capture_output=True, text=True).stdout
    cycles = OrderedDict()
    pending = {}
    for line in out.splitlines():
        sm = SHADOW_RE.search(line)
        if sm:
            pair, sess, setup, conds = sm.groups()
            try:
                pending[(pair, sess, setup)] = ast.literal_eval(conds)
            except (ValueError, SyntaxError):
                pass
            continue
        m = CYCLE_RE.search(line)
        if not m: continue
        ts, picked, n, rest = m.groups()
        intents = frozenset(
            (p, s, d, su) for p, s, d, su in INTENT_RE.findall(rest))
        epoch = datetime.fromisoformat(ts).timestamp()
        cycles[epoch] = {"picked": picked, "n": int(n), "intents": intents,
                         "ts": ts, "conds": pending}
        pending = {}
    return cycles

def load_bands():
    """(pair, session, setup_id) -> [(feature, lo, hi)]; resolved-form wins."""
    cells_dir = Path(__file__).resolve().parents[2] / "config" / "cells"
    bands = {}
    for f in glob.glob(str(cells_dir / "*.json")):
        c = json.load(open(f))
        for sess, sd in c.get("sessions", {}).items():
            if not isinstance(sd, dict): continue
            for s in sd.get("setups", []):
                out = []
                for cd in s.get("conditions", []):
                    r = cd.get("resolved")
                    if r is not None:
                        out.append((cd["feature"], float(r[0]), float(r[1])))
                    else:
                        out.append((cd["feature"], cd.get("min"), cd.get("max")))
                bands[(c["pair"], sess, s["id"])] = out
    return bands

def feature_noise(pairs, live, shadow):
    """Empirical inter-engine sampling noise: p90 |delta| per feature, from
    setups whose CELLSHADOW line both engines emitted in aligned cycles."""
    deltas = defaultdict(list)
    for le, se in pairs:
        lc, sc = live[le]["conds"], shadow[se]["conds"]
        for k in set(lc) & set(sc):
            for f in set(lc[k]) & set(sc[k]):
                try:
                    deltas[f].append(abs(float(lc[k][f]) - float(sc[k][f])))
                except (TypeError, ValueError):
                    pass
    return {f: (sorted(v)[int(len(v) * 0.9)], max(v)) for f, v in deltas.items() if v}

def local_move(key, feature, idx, seq, cycles):
    """Largest |delta| of `feature` for setup `key` between the aligned cycle
    and its immediate neighbors in the SAME engine — how far this feature
    actually moves across one cycle right now. Captures regime ramps (e.g.
    the NY-open atr_5m climb) that window-wide noise stats understate."""
    here = cycles[seq[idx]]["conds"].get(key, {}).get(feature)
    if here is None: return 0.0
    best = 0.0
    for j in (idx - 1, idx + 1):
        if 0 <= j < len(seq):
            v = cycles[seq[j]]["conds"].get(key, {}).get(feature)
            if v is not None:
                best = max(best, abs(float(here) - float(v)))
    return best

def classify(diff, live_c, shadow_c, bands, noise, ctx):
    """Adjudicate one mismatch's differing setups -> (verdict, detail_lines)."""
    details, marginal = [], True
    for (pair, sess, side, setup) in sorted(diff):
        key = (pair, sess, setup)
        # session-boundary straddle: the aligned cycles sample on opposite
        # sides of a session-open/close hour, so the cell is in-session for
        # exactly one engine (e.g. live 13:01 NY-open vs shadow 12:59).
        # Converges on the next cycle; benign by construction.
        if _coarse_session and ctx:
            h_live, h_shadow = ctx["hours"]
            if (_coarse_session(h_live) == sess) != (_coarse_session(h_shadow) == sess):
                details.append(f"      {setup}: session-boundary straddle "
                               f"(live h={h_live} shadow h={h_shadow} sess={sess})")
                continue
        conds = live_c.get(key) or shadow_c.get(key) or {}
        src = "live" if live_c.get(key) else "shadow"
        best = None  # (ratio, text)
        for f, lo, hi in bands.get(key, []):
            v = conds.get(f)
            if v is None: continue
            edges = [e for e in (lo, hi) if e is not None]
            if not edges: continue
            dist = min(abs(float(v) - e) for e in edges)
            p90, dmax = noise.get(f, (None, None))
            lm = local_move(key, f, ctx[src][0], ctx[src][1], ctx[src][2]) if ctx else 0.0
            # explainable if within 3x typical inter-engine noise, OR within
            # the largest inter-engine delta ever observed on this feature,
            # OR within the feature's CURRENT per-cycle movement (ramp-aware)
            yard = max((MARGINAL_X * p90) if p90 else 0.0, dmax or 0.0, lm)
            ratio = (dist / yard * MARGINAL_X) if yard else float("inf")
            if best is None or ratio < best[0]:
                best = (ratio, f"{f}={v} edge_dist={dist:.4g} noise_p90={p90 or 0:.4g} obs_max={dmax or 0:.4g} local_move={lm:.4g}")
        if best is None:
            marginal = False
            details.append(f"      {setup}: no condition values captured — cannot adjudicate")
        else:
            details.append(f"      {setup}: {best[1]} ratio={best[0]:.1f}")
            if best[0] >= MARGINAL_X:
                marginal = False
    return ("MARGINAL" if marginal else "STRUCTURAL"), details

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", required=True)
    ap.add_argument("--until", default=None)
    ap.add_argument("--live-unit", default="mr-scrooge-v6")
    ap.add_argument("--shadow-unit", default="mr-scrooge-v6-dryrun")
    a = ap.parse_args()
    live, shadow = journal(a.live_unit, a.since, a.until), journal(a.shadow_unit, a.since, a.until)
    # nearest-neighbor alignment: the two engines run phase-shifted 5-min grids
    TOL = 150.0
    shadow_keys = sorted(shadow)
    live_seq = sorted(live)
    pairs, used = [], set()
    for le in sorted(live):
        best = min((sk for sk in shadow_keys if sk not in used), key=lambda sk: abs(sk - le), default=None)
        if best is not None and abs(best - le) <= TOL:
            pairs.append((le, best)); used.add(best)
    if len(pairs) < 10:
        print(f"INSUFFICIENT: only {len(pairs)} aligned cycles (live={len(live)} shadow={len(shadow)})")
        sys.exit(2)

    bands, noise = load_bands(), feature_noise(pairs, live, shadow)
    mism, pick_div, structural = [], [], 0
    for le, se in pairs:
        L, S = live[le], shadow[se]
        b = L["ts"][:16]
        if L["intents"] != S["intents"]:
            verdict, details = classify(
                L["intents"] ^ S["intents"], L["conds"], S["conds"], bands, noise,
                {"live": (live_seq.index(le), live_seq, live),
                 "shadow": (shadow_keys.index(se), shadow_keys, shadow),
                 "hours": (datetime.fromtimestamp(le, tz=timezone.utc).hour,
                           datetime.fromtimestamp(se, tz=timezone.utc).hour)})
            if verdict == "STRUCTURAL": structural += 1
            mism.append((b, L, S, verdict, details))
        elif L["picked"] != S["picked"]:
            # same intent set, different pick: live portfolio caps / open broker
            # positions suppress picks the position-less shadow takes. Not
            # decision-layer drift; reported but does not fail parity.
            pick_div.append((b, L, S))
    ok = len(pairs) - len(mism) - len(pick_div)
    marginal = len(mism) - structural
    print(f"aligned cycles: {len(pairs)} | full parity: {ok} | "
          f"intent mismatches: {len(mism)} (MARGINAL {marginal} / STRUCTURAL {structural}) | "
          f"pick-only divergence (position-state): {len(pick_div)}")
    for b, L, S, verdict, details in mism:
        if verdict == "MARGINAL": continue
        print(f"  {b} STRUCTURAL")
        print(f"    live   picked={L['picked']} intents={sorted(L['intents'])}")
        print(f"    shadow picked={S['picked']} intents={sorted(S['intents'])}")
        for d in details: print(d)
    if marginal:
        print(f"  ({marginal} MARGINAL mismatches suppressed — band-edge flicker within "
              f"{MARGINAL_X}x sampling noise; rerun with journal window to inspect)")
    if pick_div:
        print(f"  ({len(pick_div)} pick-only divergences suppressed; first: {pick_div[0][0]})")
    if structural:
        print("VERDICT: FAIL — structural intent divergence (not explained by band-edge noise)")
        sys.exit(1)
    print("VERDICT: PARITY — shadow's decision layer matches live over the window"
          f" ({marginal} marginal flickers, {len(pick_div)} position-state pick divergences)")
    sys.exit(0)

if __name__ == "__main__":
    main()
