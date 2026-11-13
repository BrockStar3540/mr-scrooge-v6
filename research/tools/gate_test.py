#!/usr/bin/env python3
"""Scorer for the PRE-REGISTERED live test of the bad-day gate (v6.32.0, registered 2026-11-13).
Rule text: docs/LIVE_TEST_BAD_DAY_GATE.md in the public repo. Do not edit the decision rule; change anything else
only with a new registration time.

usage: gate_test.py --trades out/scrooge_trades.csv --gatelog raw/daygate_all.txt --m1 raw/m1_gate.json.gz [--null 4000]
       gate_test.py --selftest

What it does
 1. KEPT: every V6 trade (parents + poppers) entered after the gate went live and now closed: real fills, real pips.
 2. SKIPPED: each `DAYGATE skip` journal line (first refused signal of a pair/setup/day) replayed on M1 bid/ask with
    the live exit rules (stop, ratchet gear from the log line, 24h any-red reaper), entry at the last complete bar's
    ask (long) or bid (short), exit-side prices, so the spread is paid. An ESTIMATE of what the gate refused.
    Poppers of refused parents cannot be replayed, so the random-day benchmark uses PARENTS only (documented in the
    public live-test doc); the positive-total criterion uses all kept trades.
 3. BENCHMARK: the replayed no-gate stream of parents (kept + replayed skipped). Random sets of whole FX trading days
    (same number of gated days as the real gate had) are "gated" instead, removing the non-exempt parents on them.
 4. FIDELITY: the replay engine and the entry-price approximation are checked on the kept trades.
 5. VERDICT per the frozen rule, only once 150 closed gate-era trades or 2027-02-05 is reached.
"""
import argparse, bisect, csv, gzip, json, math, re, sys, datetime as dt
from zoneinfo import ZoneInfo
import numpy as np

GATE_START = dt.datetime(2026, 11, 13, 3, 11, 0)          # UTC, v6.32.0 restart
END_DATE = dt.date(2027, 2, 5)
N_DECISION = 150
EXEMPT = ("liq_sweep_fade", "classic_willr_fade", "control_atr5m_60", "rg1_range_scalp")
SKIP_WEEKDAYS = (3, 4)
EVENT_DAYS = {"2026-12-09": ["ALL"]}                        # mirror of config/day_gate.json at registration
NY = ZoneInfo("America/New_York"); UTC = dt.timezone.utc
EPOCH = dt.datetime(2026, 1, 1)
F = lambda x: float(x) if x not in ("", None) else 0.0
pipsz = lambda inst: 0.01 if inst.endswith("JPY") else 0.0001
tmin = lambda s: int((dt.datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S") - EPOCH).total_seconds() // 60)


def exempt(setup):
    return any(setup == f or setup.startswith(f + "_") for f in EXEMPT)


def fx_day(t_utc_naive):
    return (t_utc_naive.replace(tzinfo=UTC).astimezone(NY) + dt.timedelta(hours=7)).date()


def gated_day(d, pair=""):
    if d.weekday() in SKIP_WEEKDAYS:
        return True
    cur = EVENT_DAYS.get(d.isoformat())
    return bool(cur and ("ALL" in cur or set(pair.split("_")) & set(cur)))


# ----------------------------------------------------------------------------- journal lines
LINE = re.compile(r"DAYGATE skip (?P<pair>[A-Z]{3}_[A-Z]{3}) setup=(?P<setup>\S+) reason=(?P<reason>\S+)(?P<rest>.*?)\s*\| engine=day_gate")


def parse_gatelog(text):
    """-> list of dicts. Lines without t=/side= (none expected after 2026-11-13 05:25 UTC) are counted as unreplayable."""
    out = {}
    for ln in text.splitlines():
        m = LINE.search(ln)
        if not m:
            continue
        d = {"pair": m["pair"], "setup": m["setup"], "reason": m["reason"]}
        for k, v in re.findall(r"(\w+)=(\S+)", m["rest"]):
            d[k] = v
        out[(d["pair"], d["setup"], d.get("t") or ln[:15], d["reason"])] = d
    return list(out.values())


# ----------------------------------------------------------------------------- replay engine (mirrors replay_grid.py)
def lock_fn(E, L, T, S, R):
    def f(peak):
        best = None
        if E > 0 and L > 0 and peak >= E:
            best = L
        if T and peak >= T:
            c = math.floor((peak - T) / S) * S + T - R
            best = c if best is None or c > best else best
        return best
    return f


def replay(bars, times, inst, long, entry, t0, stop, gear, reap_h=24.0):
    """bars: [(tmin, bh, bl, bc, ah, al, ac)]; returns (pips, how). Stop/lock checked against the exit side."""
    ps = pipsz(inst); lf = lock_fn(*gear); i = bisect.bisect_right(times, t0)
    peak = -1e9; lock = None; n = len(bars)
    while i < n:
        t, bh, bl, bc, ah, al, ac = bars[i]
        if long:
            fav = (bh - entry) / ps; adv = (bl - entry) / ps; cur = (bc - entry) / ps
        else:
            fav = (entry - al) / ps; adv = (entry - ah) / ps; cur = (entry - ac) / ps
        lvl = -abs(stop) if lock is None else max(-abs(stop), lock)
        if adv <= lvl:
            return lvl, "stop"
        peak = max(peak, fav)
        nl = lf(peak)
        if nl is not None and (lock is None or nl > lock):
            lock = nl
        if reap_h and (t - t0) / 60.0 >= reap_h and cur < 0:
            return cur, "reap"
        i += 1
    b = bars[-1]
    return (((b[3] - entry) / ps) if long else ((entry - b[6]) / ps)), "open"


def load_m1(path):
    raw = json.load(gzip.open(path, "rt"))
    B, T = {}, {}
    for p, v in raw.items():
        B[p] = [(tmin(b[0]), b[1], b[2], b[3], b[4], b[5], b[6]) for b in v]; T[p] = [b[0] for b in B[p]]
    return B, T


def replay_skip(sig, B, T):
    p = sig["pair"]
    if p not in B or "side" not in sig or "t" not in sig:
        return None, "no-fields"
    if sig.get("mode", "ratchet") != "ratchet":
        return None, "bracket-mode"
    t0 = tmin(sig["t"]); j = bisect.bisect_right(T[p], t0 - 1) - 1          # last complete bar before the signal
    if j < 0 or t0 - T[p][j] > 15:
        return None, "no-bars"
    long = sig["side"] == "long"; bar = B[p][j]
    entry = bar[6] if long else bar[3]                                       # ask close (long) / bid close (short)
    gear = (float(sig.get("eng", 0)), float(sig.get("englock", 0)), float(sig.get("trig", 0)), 2.0, float(sig.get("trail", 2)))
    pips, how = replay(B[p], T[p], p, long, entry, t0 - 1, float(sig.get("sl", 50)), gear)
    return pips, how


# ----------------------------------------------------------------------------- main
def selftest():
    B = {"EUR_USD": [(0, 1, 1, 1, 1, 1, 1)]}                                  # padding
    mk = lambda t, bh, bl, bc, ah, al, ac: (t, bh, bl, bc, ah, al, ac)
    e = 1.1000
    up = [mk(1 + k, e + 0.0011 * (k + 1) / 1, e, e + 0.0011 * (k + 1), e + 0.0012, e, e + 0.0012) for k in range(1)]  # +11 pips
    back = [mk(2, e + 0.0011, e + 0.0007, e + 0.0008, e + 0.0012, e + 0.0008, e + 0.0009)]                           # falls to +7 lock
    bars = [(0, e, e, e, e, e, e)] + up + back
    T = [b[0] for b in bars]
    p, how = replay(bars, T, "EUR_USD", True, e, 0, 50, (5, 4, 7, 2, 2))
    assert how == "stop" and abs(p - 9.0) < 1e-6, (p, how)                    # peak 11: lock = floor((11-7)/2)*2 + 7 - 2 = 9
    print("selftest replay: peak 11 pips then retrace ->", p, how)
    bars2 = [(0, e, e, e, e, e, e), (1, e, e - 0.0051, e - 0.0050, e, e - 0.0051, e)]
    p2, how2 = replay(bars2, [0, 1], "EUR_USD", True, e, 0, 50, (5, 4, 7, 2, 2))
    assert how2 == "stop" and abs(p2 + 50) < 1e-6
    lines = ("Nov 13 06:00:01 h python3[1]: 2026-11-13 06:00:01,1 INFO v6.daygate  DAYGATE skip EUR_USD setup=echo_box_fade_long reason=weekday-Fri "
             "t=2026-11-13T06:00:00Z side=long h=60 sl=50.0 trig=7.0 trail=2.0 eng=5.0 englock=4.0 mode=ratchet probe=0 | engine=day_gate\n"
             "Nov 13 06:05:01 h python3[1]: ... DAYGATE skip GBP_USD setup=x reason=weekday-Fri | engine=day_gate\n")
    s = parse_gatelog(lines)
    assert len(s) == 2 and s[0]["side"] == "long" and s[0]["sl"] == "50.0" and "side" not in s[1]
    assert exempt("rg1_range_scalp_short") and not exempt("rg1_range_scalping")
    print("selftest parse/exempt: ok")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trades"); ap.add_argument("--gatelog"); ap.add_argument("--m1")
    ap.add_argument("--null", type=int, default=4000); ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    now = dt.datetime.utcnow()
    rows = [r for r in csv.DictReader(open(a.trades, encoding="utf-8")) if r["Era"].startswith("V6")]
    rows.sort(key=lambda r: (r["Entry time UTC"], r["Trade ID"]))
    P = lambda s: dt.datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
    gate_rows = [r for r in rows if P(r["Entry time UTC"]) >= GATE_START]
    closed = [r for r in gate_rows if r["Status"] == "Closed"]
    n_open = len(gate_rows) - len(closed)
    pips = np.array([F(r["Pips (fill to fill)"]) for r in closed]); usd = np.array([F(r["Realized P/L (USD)"]) + F(r["Financing (USD)"]) for r in closed])
    big = np.array([F(r["Realized P/L (USD)"]) <= -15 for r in closed])
    print(f"GATE TEST  (gate live since {GATE_START:%Y-%m-%d %H:%M} UTC; read at {N_DECISION} closed trades or {END_DATE}); now {now:%Y-%m-%d %H:%M} UTC")
    print("\n1. KEPT = real gate-era trades (parents + poppers), closed:")
    if len(closed):
        print(f"   n {len(closed)} (+{n_open} still open) | win {(pips > 0).mean()*100:.0f}% | avg {pips.mean():+.2f} pips | total {pips.sum():+.0f} pips | net ${usd.sum():+.0f} after financing | big losses {int(big.sum())}")
        print(f"   baseline before the gate: -2.10 pips/trade over 1,170 trades; sd about 23 pips/trade -> 95% interval on the mean +/-{1.96*23.2/math.sqrt(max(len(closed),1)):.1f} pips at this n")
    else:
        print(f"   none closed yet (+{n_open} open)")
    # --- skipped
    sigs = parse_gatelog(open(a.gatelog).read()) if a.gatelog else []
    sigs = [s for s in sigs if "t" not in s or dt.datetime.strptime(s["t"], "%Y-%m-%dT%H:%M:%SZ") >= GATE_START]
    B, T = load_m1(a.m1) if a.m1 else ({}, {})
    rep, why = [], {}
    for s in sigs:
        pp, how = replay_skip(s, B, T)
        if pp is None:
            why[how] = why.get(how, 0) + 1; continue
        t = dt.datetime.strptime(s["t"], "%Y-%m-%dT%H:%M:%SZ")
        rep.append({"day": fx_day(t), "pips": pp, "exempt": exempt(s["setup"]), "how": how, "pair": s["pair"], "setup": s["setup"]})
    print(f"\n2. SKIPPED = {len(sigs)} DAYGATE lines (first refused signal per pair/setup/day); replayed {len(rep)}; unreplayable {why or 0}")
    if rep:
        rp = np.array([r["pips"] for r in rep])
        print(f"   replayed skipped parents: win {(rp > 0).mean()*100:.0f}% | avg {rp.mean():+.2f} pips | total {rp.sum():+.0f} pips | still open {sum(r['how']=='open' for r in rep)} (marked to market)")
        print("   (estimate only: no cap/cooldown limits applied, poppers not replayed, entry at last bar's ask/bid)")
    # --- fidelity: replay of kept parents with their actual entry and stop
    if B:
        d1 = []
        for r in closed:
            if r["Type"] != "Parent" or r["Pair"] not in B or not r["Initial stop distance (pips)"]:
                continue
            long = r["Direction"].lower() == "long"; t0 = tmin(r["Entry time UTC"].replace(" ", "T"))
            pp, how = replay(B[r["Pair"]], T[r["Pair"]], r["Pair"], long, F(r["Entry price"]), t0 - 1, abs(F(r["Initial stop distance (pips)"])), (5, 4, 7, 2, 2))
            if how != "open" and r["Exit time UTC"]:
                d1.append((pp, F(r["Pips (fill to fill)"])))
        if d1:
            x = np.array(d1); print(f"\n3. FIDELITY on {len(x)} kept closed parents (replay with their real entry/stop vs real result): mean diff {np.mean(x[:,0]-x[:,1]):+.2f} pips, within 3 pips {np.mean(np.abs(x[:,0]-x[:,1])<=3)*100:.0f}%")
    # --- benchmark
    kept_par = [{"day": fx_day(P(r["Entry time UTC"])), "pips": F(r["Pips (fill to fill)"]), "exempt": exempt(r["Setup (strategy)"])} for r in closed if r["Type"] == "Parent"]
    stream = kept_par + rep
    days = sorted({s["day"] for s in stream})
    gdays = [d for d in days if gated_day(d)]
    print(f"\n4. BENCHMARK (parents only): stream of {len(stream)} = {len(kept_par)} kept + {len(rep)} replayed skipped over {len(days)} FX days, {len(gdays)} of them gated")
    if len(days) < 8 or len(gdays) < 2 or not rep:
        print("   too little data for the random-day benchmark yet.")
        p_val = None
    else:
        obs = sum(s["pips"] for s in stream if not (gated_day(s["day"]) and not s["exempt"]))
        rng = np.random.default_rng(5); k = len(gdays)
        ds = np.array([[s["day"].toordinal(), s["pips"], s["exempt"]] for s in stream], float)
        total = ds[:, 1].sum(); idx = {d.toordinal(): i for i, d in enumerate(days)}
        day_non = np.zeros(len(days))
        for o, pp, ex in ds:
            if not ex: day_non[idx[int(o)]] += pp
        null = np.array([total - day_non[rng.choice(len(days), k, replace=False)].sum() for _ in range(a.null)])
        p_val = float((null >= obs).mean())
        print(f"   gate rule on this stream: {obs:+.0f} pips | {a.null} random sets of {k} whole days: mean {null.mean():+.0f}, 95th pct {np.percentile(null,95):+.0f} | chance random does as well {p_val:.3f}")
        print(f"   no gate at all: {total:+.0f} pips")
    # --- verdict
    due = len(closed) >= N_DECISION or now.date() >= END_DATE
    print(f"\n5. DECISION RULE (frozen): keep iff kept total > 0 pips AND beats random day-skipping at p < 0.05; read at {N_DECISION} closed trades or {END_DATE}.")
    if not due:
        print(f"   INTERIM, not due: {len(closed)}/{N_DECISION} closed gate-era trades; due by {END_DATE} at the latest. No decision.")
    elif len(closed) < 100 and now.date() >= END_DATE:
        print("   INCONCLUSIVE: fewer than 100 trades at 12 weeks; gate stays on until 150.")
    else:
        ok = len(closed) and pips.sum() > 0 and p_val is not None and p_val < 0.05
        print(f"   VERDICT: {'KEEP' if ok else 'SWITCH OFF (set enabled:false in config/day_gate.json)'} | kept total {pips.sum():+.0f} pips | p {p_val}")


if __name__ == "__main__":
    main()
