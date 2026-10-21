#!/usr/bin/env python3
"""research/tools/deflation_test.py — deflated Sharpe + PBO/CSCV for issue #9.

Pre-registered in research/deflation/PREREGISTRATION.md (committed before
this was run). That document is the spec; this file implements it and
nothing else. Heavy-ish (numpy over ~1,700 trials x 12,870 splits): run it
on the Mac mini against a frozen copy of the data, never on the live box.

    python research/tools/deflation_test.py \
        --episodes /path/to/frozen/shadowboard.json \
        --registry research/registry/registry.json \
        --decisions research/registry/decisions.jsonl \
        --cells config/cells --aliases config/setup_aliases.json \
        --cutoff 2026-10-22 --out research/deflation/results.json

References: Bailey & Lopez de Prado (2014), "The Deflated Sharpe Ratio";
Bailey, Borwein, Lopez de Prado & Zhu (2017), "The Probability of Backtest
Overfitting" (CSCV).
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import NormalDist

import numpy as np

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core.trial_evidence import benjamini_hochberg  # noqa: E402  (the governor's BH)
from core.trial_stats import episode_net            # noqa: E402  (the governor's cost model)

EULER_GAMMA = 0.5772156649015329
_N = NormalDist()
SEAT = ("ACTIVE", "PROBE")


# ── statistics ───────────────────────────────────────────────────────────────
def expected_max_sr(n_trials: float, var_sr: float) -> float:
    """E[max SR] of n_trials independent zero-skill trials whose Sharpe
    estimates have cross-sectional variance var_sr (Bailey & LdP 2014, eq. 6
    via the false-strategy theorem)."""
    if n_trials <= 1 or var_sr <= 0:
        return 0.0
    n = float(n_trials)
    return math.sqrt(var_sr) * ((1 - EULER_GAMMA) * _N.inv_cdf(1 - 1 / n)
                                + EULER_GAMMA * _N.inv_cdf(1 - 1 / (n * math.e)))


def psr(sr: float, sr0: float, t: int, skew: float, kurt: float) -> float:
    """Probabilistic Sharpe ratio: P(true SR > sr0) given a per-period SR
    estimate from t observations with skewness and (non-excess) kurtosis."""
    if t < 2:
        return float("nan")
    den = 1 - skew * sr + (kurt - 1) / 4 * sr * sr
    if den <= 0:
        den = 1e-12
    return _N.cdf((sr - sr0) * math.sqrt(t - 1) / math.sqrt(den))


def moments(x: np.ndarray):
    """(mean, sd ddof=1, SR, skew, non-excess kurtosis) of a 1-d series."""
    x = np.asarray(x, dtype=float)
    t = x.size
    if t < 2:
        return float("nan"), float("nan"), float("nan"), 0.0, 3.0
    m, sd = float(x.mean()), float(x.std(ddof=1))
    if sd == 0:
        return m, 0.0, 0.0, 0.0, 3.0
    z = (x - m) / x.std(ddof=0)
    return m, sd, m / sd, float((z ** 3).mean()), float((z ** 4).mean())


def participation_ratio(corr: np.ndarray) -> float:
    """Effective number of independent trials: (sum l)^2 / sum l^2 over the
    eigenvalues of a correlation matrix."""
    w = np.linalg.eigvalsh(corr)
    w = np.clip(w, 0, None)
    return float(w.sum() ** 2 / (w ** 2).sum())


def logit(w: float) -> float:
    w = min(max(w, 1e-9), 1 - 1e-9)
    return math.log(w / (1 - w))


def contiguous_blocks(n_rows: int, s: int):
    """Partition row indices 0..n_rows-1 into s contiguous, near-equal blocks."""
    edges = np.linspace(0, n_rows, s + 1).round().astype(int)
    return [np.arange(edges[i], edges[i + 1]) for i in range(s)]


# ── data ─────────────────────────────────────────────────────────────────────
def load_cells(cells_dir: Path):
    side, status = {}, {}
    for f in sorted(cells_dir.glob("*.json")):
        d = json.loads(f.read_text())
        for sess, b in (d.get("sessions") or {}).items():
            for su in (b.get("setups") or []):
                k = f'{d.get("pair") or f.stem}|{sess}|{su.get("id")}'
                side[k] = su.get("side")
                status[k] = su.get("status")
    return side, status


def load_aliases(path: Path):
    try:
        return {(r["cell"], r["setup"], r["side"]): r["as"]
                for r in json.loads(path.read_text())}
    except (OSError, ValueError):
        return {}


def load_episodes(path: Path, aliases, cfg_side, slippage: float, cutoff: str):
    """Resolved executable-exit-v2 episodes -> {key: [(date, net_pips)]} plus
    the set of keys ever stamped ACTIVE/PROBE (with first time)."""
    eps = json.loads(path.read_text())["episodes"]
    out = defaultdict(list)
    stamped_seat = {}
    dropped_side = 0
    for ep in eps.values():
        sc = ep.get("scores") or {}
        if sc.get("mv") != 2 or sc.get("net240") is None:
            continue
        if ep["t"][:10] >= cutoff:
            continue
        pair, sess = (ep["cell"].split("/") + ["?"])[:2]
        sid = aliases.get((ep["cell"], ep["setup"], ep["side"]), ep["setup"])
        key = f"{pair}|{sess}|{sid}"
        if cfg_side.get(key) and ep.get("side") != cfg_side[key]:
            dropped_side += 1
            continue
        net = episode_net(sc["net240"], ep.get("spread"), pair,
                          slippage_pips=slippage, executable=True)
        out[key].append((ep["t"][:10], float(net)))
        if ep.get("status") in SEAT:
            if key not in stamped_seat or ep["t"] < stamped_seat[key]:
                stamped_seat[key] = ep["t"]
    return out, stamped_seat, dropped_side


def end_dates(decisions_path: Path):
    """key -> first time it was set DISABLED (no fires afterwards)."""
    out = {}
    try:
        fh = open(decisions_path)
    except OSError:
        return out
    with fh:
        for ln in fh:
            r = json.loads(ln)
            if r.get("key") and r.get("status_after") == "DISABLED":
                out.setdefault(r["key"], r["t"])
    return out


def bar_promoted(decisions_path: Path):
    out = {}
    with open(decisions_path) as fh:
        for ln in fh:
            r = json.loads(ln)
            if r.get("key") and r.get("action") in ("PROMOTE", "CHEATER-PROBE"):
                out.setdefault(r["key"], r["t"])
    return out


def build_matrix(ep_by_key, keys, days, first_seen, end_at):
    """Daily net pips (T x N) with NaN outside each trial's alive window, and
    per-day episode stats for the bar replica: count, sum, and day-means."""
    di = {d: i for i, d in enumerate(days)}
    T, N = len(days), len(keys)
    R = np.full((T, N), np.nan)
    E_n = np.zeros((T, N))
    E_sum = np.zeros((T, N))
    for j, k in enumerate(keys):
        lo = str(first_seen.get(k) or days[0])[:10]
        hi = str(end_at.get(k) or "9999")[:10]
        alive = np.array([(lo <= d <= hi) for d in days])
        R[alive, j] = 0.0
        for d, net in ep_by_key.get(k, ()):
            i = di.get(d)
            if i is None:
                continue
            if np.isnan(R[i, j]):
                R[i, j] = 0.0                      # fired => alive that day
            R[i, j] += net
            E_n[i, j] += 1
            E_sum[i, j] += net
    return R, E_n, E_sum


def sr_columns(R: np.ndarray, min_days: int):
    """Per-column SR over non-NaN rows; NaN where < min_days or sd == 0."""
    C = (~np.isnan(R)).sum(0)
    X = np.nan_to_num(R)
    S1, S2 = X.sum(0), (X * X).sum(0)
    with np.errstate(invalid="ignore", divide="ignore"):
        m = S1 / C
        var = (S2 - C * m * m) / (C - 1)
        sr = m / np.sqrt(var)
    sr[(C < min_days) | ~(var > 0)] = np.nan
    return sr, C


# ── CSCV ─────────────────────────────────────────────────────────────────────
class BlockStats:
    """Per-(block, trial) sufficient statistics so each split is a sum."""

    def __init__(self, R, E_n, E_sum, blocks):
        X = np.nan_to_num(R)
        alive = ~np.isnan(R)
        with np.errstate(invalid="ignore", divide="ignore"):
            dm = np.where(E_n > 0, E_sum / np.where(E_n > 0, E_n, 1), 0.0)
        has = E_n > 0
        self.c = np.stack([alive[b].sum(0) for b in blocks])          # alive days
        self.s1 = np.stack([X[b].sum(0) for b in blocks])             # daily pips sum
        self.s2 = np.stack([(X[b] ** 2).sum(0) for b in blocks])
        self.en = np.stack([E_n[b].sum(0) for b in blocks])           # episodes
        self.es = np.stack([E_sum[b].sum(0) for b in blocks])         # episode nets sum
        self.bd = np.stack([has[b].sum(0) for b in blocks])           # day-blocks fired
        self.bm1 = np.stack([dm[b].sum(0) for b in blocks])           # sum of day means
        self.bm2 = np.stack([(dm[b] ** 2).sum(0) for b in blocks])

    def sr(self, idx, min_days):
        c, s1, s2 = self.c[idx].sum(0), self.s1[idx].sum(0), self.s2[idx].sum(0)
        with np.errstate(invalid="ignore", divide="ignore"):
            m = s1 / c
            var = (s2 - c * m * m) / (c - 1)
            sr = m / np.sqrt(var)
        ok = (c >= min_days) & (var > 1e-12)
        return np.where(ok, sr, np.nan)

    def bar(self, idx, cfg):
        """The governor's ordinary-lane predicate on the in-sample blocks
        (normal approximation to the day-block bootstrap; see prereg §4)."""
        n = self.en[idx].sum(0)
        es = self.es[idx].sum(0)
        B = self.bd[idx].sum(0)
        m1, m2 = self.bm1[idx].sum(0), self.bm2[idx].sum(0)
        with np.errstate(invalid="ignore", divide="ignore"):
            avg = es / n
            M = m1 / B
            var = (m2 - B * M * M) / (B - 1)
            se = np.sqrt(np.clip(var, 0, None) / B)
        z = _N.inv_cdf(cfg["bootstrap_confidence"])
        lcb = M - z * se
        docket = (n >= cfg["min_raw_episodes"]) & (B >= cfg["min_independent_days"]) & (B >= 2)
        pv = {}
        for j in np.flatnonzero(docket):
            if se[j] > 0:
                pv[int(j)] = 1 - _N.cdf(M[j] / se[j])
            else:
                pv[int(j)] = 0.0 if M[j] > 0 else 1.0
        q = benjamini_hochberg(pv) if pv else {}
        sel = [j for j, qv in q.items()
               if qv <= cfg["fdr_q"] and avg[j] >= cfg["bar_avg"] and lcb[j] > cfg["lcb_min"]]
        return np.array(sorted(sel), dtype=int), int(docket.sum())


def cscv(bs: BlockStats, s: int, min_days: int, cfg, with_bar=True):
    combos = list(itertools.combinations(range(s), s // 2))
    lam_max, lam_bar, oos_sr_star, n_sel, sel_oos_mean, rest_oos_mean = [], [], [], [], [], []
    no_sel = 0
    for is_idx in combos:
        is_idx = list(is_idx)
        oos_idx = [b for b in range(s) if b not in is_idx]
        sr_is, sr_oos = bs.sr(is_idx, min_days), bs.sr(oos_idx, min_days)
        elig = ~np.isnan(sr_is) & ~np.isnan(sr_oos)
        ne = int(elig.sum())
        if ne < 2:
            continue
        cols = np.flatnonzero(elig)
        oos_rank = np.empty(bs.c.shape[1])
        oos_rank[:] = np.nan
        oos_rank[cols] = sr_oos[cols].argsort().argsort() + 1     # 1 = worst
        star = cols[np.nanargmax(sr_is[cols])]
        lam_max.append(logit(oos_rank[star] / (ne + 1)))
        oos_sr_star.append(float(sr_oos[star]))
        if with_bar:
            sel, _ = bs.bar(is_idx, cfg)
            sel = np.array([j for j in sel if elig[j]], dtype=int)
            if sel.size == 0:
                no_sel += 1
            else:
                w = float(np.mean(oos_rank[sel] / (ne + 1)))
                lam_bar.append(logit(w))
                n_sel.append(int(sel.size))
                rest = np.setdiff1d(cols, sel)
                sel_oos_mean.append(float(np.nanmean(sr_oos[sel])))
                rest_oos_mean.append(float(np.nanmean(sr_oos[rest])) if rest.size else float("nan"))
    lam_max = np.array(lam_max)
    out = {"splits": len(combos), "splits_scored": int(lam_max.size),
           "pbo_max_sr": float((lam_max <= 0).mean()) if lam_max.size else None,
           "median_logit_max_sr": float(np.median(lam_max)) if lam_max.size else None,
           "p_oos_sr_star_le_0": float((np.array(oos_sr_star) <= 0).mean()) if oos_sr_star else None,
           "median_oos_sr_star": float(np.median(oos_sr_star)) if oos_sr_star else None}
    if with_bar:
        lb = np.array(lam_bar)
        out.update({
            "pbo_bar": float((lb <= 0).mean()) if lb.size else None,
            "median_logit_bar": float(np.median(lb)) if lb.size else None,
            "splits_with_selection": int(lb.size), "splits_without_selection": no_sel,
            "median_selected": float(np.median(n_sel)) if n_sel else 0,
            "mean_oos_sr_selected": float(np.nanmean(sel_oos_mean)) if sel_oos_mean else None,
            "mean_oos_sr_rest": float(np.nanmean(rest_oos_mean)) if rest_oos_mean else None,
            "p_selected_oos_sr_le_0": float((np.array(sel_oos_mean) <= 0).mean()) if sel_oos_mean else None,
        })
    return out


# ── the run ──────────────────────────────────────────────────────────────────
def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run(a):
    reg = json.loads(Path(a.registry).read_text())
    setups = reg["setups"]
    bar_cfg = {"min_raw_episodes": 10, "min_independent_days": 5, "bar_avg": 2.0,
               "lcb_min": 0.0, "fdr_q": 0.10, "bootstrap_confidence": 0.95}
    for k in bar_cfg:                      # the published bar wins if present
        if reg.get("bar", {}).get(k) is not None:
            bar_cfg[k] = float(reg["bar"][k])
    slip = float(reg.get("bar", {}).get("slippage_pips") or 0.5)
    cfg_side, cfg_status = load_cells(Path(a.cells))
    ep_by_key, stamped_seat, dropped_side = load_episodes(
        Path(a.episodes), load_aliases(Path(a.aliases)), cfg_side, slip, a.cutoff)

    days = sorted({d for v in ep_by_key.values() for d, _ in v})
    keys = sorted(k for k in setups if ep_by_key.get(k))
    first_seen = {k: setups[k].get("first_seen") for k in keys}
    end_at = end_dates(Path(a.decisions))
    for k in keys:                          # removed from config: alive until last fire
        if setups[k].get("status") == "REMOVED" and k not in end_at:
            end_at[k] = max(d for d, _ in ep_by_key[k])
    R, E_n, E_sum = build_matrix(ep_by_key, keys, days, first_seen, end_at)

    # ── the promoted set
    promoted_bar = bar_promoted(Path(a.decisions))
    P = sorted(k for k in keys if setups[k].get("ever_seated") or k in stamped_seat)
    B = sorted(k for k in keys if k in promoted_bar)
    P_no_data = sorted(k for k, v in setups.items()
                       if (v.get("ever_seated") or k in stamped_seat) and k not in ep_by_key)

    # ── DSR
    sr, cnt = sr_columns(R, a.min_days)
    valid = ~np.isnan(sr)
    var_sr = float(np.var(sr[valid], ddof=1))
    Xz = np.nan_to_num(R[:, valid])
    sd = Xz.std(0)
    corr = np.corrcoef(Xz[:, sd > 0].T)
    n_eff = participation_ratio(np.nan_to_num(corr))
    N_variants = {"M_ever (primary)": reg["counts"]["M_ever"],
                  "trials_with_data": int(len(keys)),
                  "config_versions": reg["counts"]["config_versions"],
                  "effective_N (participation ratio)": round(n_eff, 1)}
    sr0 = {name: expected_max_sr(n, var_sr) for name, n in N_variants.items()}
    sr0_primary = sr0["M_ever (primary)"]
    kidx = {k: j for j, k in enumerate(keys)}

    def per_setup(k):
        j = kidx[k]
        x = R[~np.isnan(R[:, j]), j]
        m, s, s_r, g3, g4 = moments(x)
        row = {"key": k, "T": int(x.size), "episodes": int(E_n[:, j].sum()),
               "mean_pips_day": round(m, 3), "sr_daily": None if math.isnan(s_r) else round(s_r, 4),
               "bar_promoted": k in promoted_bar}
        if x.size >= a.min_days and s > 0:
            row["psr"] = round(psr(s_r, 0.0, x.size, g3, g4), 4)
            row["dsr"] = round(psr(s_r, sr0_primary, x.size, g3, g4), 4)
            row["excess_sr"] = round(s_r - sr0_primary, 4)
            row["dsr_by_N"] = {n: round(psr(s_r, v, x.size, g3, g4), 4) for n, v in sr0.items()}
        return row

    rows = [per_setup(k) for k in P]
    scored = [r for r in rows if "dsr" in r]

    def summary(rs):
        if not rs:
            return {"n": 0}
        d = np.array([r["dsr"] for r in rs])
        ex = np.array([r["excess_sr"] for r in rs])
        return {"n": len(rs), "median_dsr": round(float(np.median(d)), 4),
                "median_excess_sr": round(float(np.median(ex)), 4),
                "n_dsr_ge_0.95": int((d >= 0.95).sum()), "n_dsr_gt_0.5": int((d > 0.5).sum()),
                "median_psr": round(float(np.median([r["psr"] for r in rs])), 4),
                "median_dsr_by_N": {n: round(float(np.median([r["dsr_by_N"][n] for r in rs])), 4)
                                    for n in N_variants}}

    # book (secondary): equal weight over alive promoted members each day
    PJ = [kidx[k] for k in P]
    book = np.nanmean(R[:, PJ], axis=1) if PJ else np.array([])
    book = book[~np.isnan(book)]
    bm, bsd, bsr, bg3, bg4 = moments(book)
    best_j = int(np.nanargmax(sr))
    bx = R[~np.isnan(R[:, best_j]), best_j]
    _, _, best_sr, b3, b4 = moments(bx)

    # ── CSCV
    blocks16 = contiguous_blocks(len(days), 16)
    bs16 = BlockStats(R, E_n, E_sum, blocks16)
    cscv16 = cscv(bs16, 16, a.min_split_days, bar_cfg)
    bs8 = BlockStats(R, E_n, E_sum, contiguous_blocks(len(days), 8))
    cscv8 = cscv(bs8, 8, a.min_split_days, bar_cfg)
    full = [j for j, k in enumerate(keys) if str(first_seen[k])[:10] <= days[0] and k not in end_at]
    cscv_full = None
    if len(full) >= 2:
        bsf = BlockStats(R[:, full], E_n[:, full], E_sum[:, full], blocks16)
        cscv_full = cscv(bsf, 16, a.min_split_days, bar_cfg, with_bar=False)
        cscv_full["trials"] = len(full)

    # ── pre-registered verdict (PREREGISTRATION.md §5)
    med_dsr = summary(scored).get("median_dsr")
    pbo_bar = cscv16.get("pbo_bar")
    if med_dsr is None or pbo_bar is None:
        verdict = "INCONCLUSIVE (insufficient data)"
    elif med_dsr <= 0.5 or pbo_bar >= 0.5:
        verdict = "MEASURES THE SEARCH"
    elif pbo_bar <= 0.25:
        verdict = "THE BAR IS DOING WORK"
    else:
        verdict = "INCONCLUSIVE"

    return {
        "generated": datetime.now(timezone.utc).isoformat(),
        "spec": "research/deflation/PREREGISTRATION.md",
        "inputs": {"episodes_sha256": sha256(Path(a.episodes)),
                   "registry_sha256": sha256(Path(a.registry)),
                   "decisions_sha256": sha256(Path(a.decisions)),
                   "cutoff_exclusive": a.cutoff, "first_day": days[0], "last_day": days[-1],
                   "market_days": len(days), "episodes_used": int(E_n.sum()),
                   "episodes_dropped_retired_side": dropped_side,
                   "slippage_pips": slip, "bar_replica": bar_cfg,
                   "min_days_dsr": a.min_days, "min_days_per_cscv_half": a.min_split_days},
        "registry": {"M_ever": reg["counts"]["M_ever"], "trials_with_data": len(keys),
                     "config_versions": reg["counts"]["config_versions"],
                     "effective_N": round(n_eff, 1), "var_sr_daily": round(var_sr, 6),
                     "trials_in_var": int(valid.sum()),
                     "expected_max_sr_by_N": {n: round(v, 4) for n, v in sr0.items()}},
        "promoted_set": {"ever_seated_with_data": len(P), "ever_seated_without_data": len(P_no_data),
                         "bar_promoted_with_data": len(B),
                         "dsr_all_ever_seated": summary(scored),
                         "dsr_bar_promoted_only": summary([r for r in scored if r["bar_promoted"]])},
        "book_equal_weight": {"T": int(book.size), "mean_pips_day": round(bm, 3),
                              "sr_daily": round(bsr, 4),
                              "psr": round(psr(bsr, 0, book.size, bg3, bg4), 4),
                              "dsr_M_ever": round(psr(bsr, sr0_primary, book.size, bg3, bg4), 4)},
        "best_trial": {"key": keys[best_j], "sr_daily": round(best_sr, 4), "T": int(bx.size),
                       "dsr_M_ever": round(psr(best_sr, sr0_primary, bx.size, b3, b4), 4)},
        "cscv_S16": cscv16, "cscv_S8": cscv8, "cscv_S16_complete_series_only": cscv_full,
        "verdict": verdict,
        "per_setup": sorted(rows, key=lambda r: (r.get("dsr") is None, -(r.get("dsr") or 0))),
    }


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--episodes", required=True)
    ap.add_argument("--registry", default=str(REPO / "research/registry/registry.json"))
    ap.add_argument("--decisions", default=str(REPO / "research/registry/decisions.jsonl"))
    ap.add_argument("--cells", default=str(REPO / "config/cells"))
    ap.add_argument("--aliases", default=str(REPO / "config/setup_aliases.json"))
    ap.add_argument("--cutoff", required=True, help="first EXCLUDED UTC date, YYYY-MM-DD")
    ap.add_argument("--min-days", type=int, default=10)
    ap.add_argument("--min-split-days", type=int, default=5)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    res = run(a)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(res, indent=1) + "\n")
    print(json.dumps({k: res[k] for k in ("registry", "promoted_set", "book_equal_weight",
                                          "best_trial", "verdict")}, indent=1))
    print(json.dumps({"cscv_S16": res["cscv_S16"], "cscv_S8": res["cscv_S8"],
                      "cscv_S16_complete_series_only": res["cscv_S16_complete_series_only"]},
                     indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
