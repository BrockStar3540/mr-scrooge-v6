"""core/trial_evidence.py — ONE era-aware evidence engine (D-7 stages D/E).

The governor filtered by era clocks; the shadowboard aggregated lifetime; the
dashboard could show a trophy the governor would reject. This module is the
single source of truth both now consume: the same episode selection, the same
statistics, the same promotion predicate — a trophy IS promotability.

STATISTICS (external review round 2):
- Day/session BLOCK bootstrap replaces the gap-weighted n_eff as the promotion
  denominator. Volatility and liquidity cluster within a session's day;
  resampling whole "YYYY-MM-DD|session" blocks keeps that dependence instead
  of assuming 48 overlapping episodes are 48 draws. n_eff remains a display
  diagnostic only.
- The bootstrap seed derives from the sorted block ids — deterministic: the
  same evidence always yields the same LCB and p-value, so ledger lines are
  reproducible and re-runs can't promote on a lucky reroll.
- Benjamini–Hochberg across the run's whole candidate docket turns the
  hypothesis registry from a printed number into an actual decision input:
  a setup promotes only if its q-value clears fdr_q.

METRIC-VERSION ISOLATION (D-7): promotion evidence counts ONLY
executable-exit-v2 episodes whose mechanics hash matches the setup's CURRENT
config. Legacy-mid-v1 mid-drift scores measured a different (frictionless)
quantity; mixing metrics in one sample would let the optimistic metric carry
the pessimistic one over the bar.
"""
from __future__ import annotations

import hashlib
import random
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence

from core.trial_events import METRIC_V2
from core.trial_stats import effective_n, episode_net


@dataclass(frozen=True)
class TrialObservation:
    key: tuple                 # (pair, session, setup_id)
    timestamp: str             # ISO-8601
    block_id: str              # "YYYY-MM-DD|session"
    net_pips: float
    metric_version: str


@dataclass(frozen=True)
class BlockInference:
    mean: float
    lcb: Optional[float]
    p_value: Optional[float]
    independent_blocks: int


def block_bootstrap_mean(observations: Sequence[TrialObservation], *,
                         null_mean: float = 0.0, confidence: float = 0.95,
                         reps: int = 10_000) -> BlockInference:
    """Bootstrap the mean by resampling whole day/session blocks. Deterministic:
    seeded from the sorted block ids, so identical evidence → identical bounds."""
    groups: dict[str, list[float]] = defaultdict(list)
    for obs in observations:
        groups[obs.block_id].append(obs.net_pips)
    block_means = [statistics.fmean(v) for v in groups.values()]
    if len(block_means) < 2:
        return BlockInference(
            mean=statistics.fmean(block_means) if block_means else 0.0,
            lcb=None, p_value=None, independent_blocks=len(block_means))
    seed = int.from_bytes(
        hashlib.sha256("|".join(sorted(groups)).encode()).digest()[:8], "big")
    rng = random.Random(seed)
    n = len(block_means)
    samples = sorted(
        statistics.fmean(block_means[rng.randrange(n)] for _ in range(n))
        for _ in range(reps))
    alpha = 1.0 - confidence
    lcb = samples[max(0, int(alpha * reps) - 1)]
    # one-sided bootstrap probability of failing to clear the null
    p_value = (1 + sum(x <= null_mean for x in samples)) / (reps + 1)
    return BlockInference(mean=statistics.fmean(block_means), lcb=round(lcb, 2),
                          p_value=round(p_value, 5), independent_blocks=n)


def benjamini_hochberg(p_values: dict) -> dict:
    """Monotone BH-adjusted q-values across the docket."""
    ranked = sorted(p_values.items(), key=lambda kv: kv[1])
    m = len(ranked)
    adjusted, running = {}, 1.0
    for rank_from_end, (key, p) in enumerate(reversed(ranked), start=1):
        rank = m - rank_from_end + 1
        running = min(running, p * m / rank)
        adjusted[key] = min(1.0, round(running, 5))
    return adjusted


@dataclass
class SetupEvidence:
    key: tuple
    raw_n: int
    effective_n: float
    independent_days: int
    net_avg: Optional[float]
    recent_n: int
    recent_avg: Optional[float]
    block_lcb: Optional[float]
    p_value: Optional[float]
    q_value: Optional[float] = None
    promotable: bool = False
    reason_codes: tuple = ()


def promotion_predicate(e: SetupEvidence, cfg: dict) -> tuple:
    """THE shared bar. Returns (ok, failure_codes). The dashboard trophy and
    the governor's promote decision both call exactly this."""
    failures = []
    if e.raw_n < int(cfg.get("min_raw_episodes", cfg.get("bar_n", 20))):
        failures.append("RAW_N")
    if e.independent_days < int(cfg.get("min_independent_days", 10)):
        failures.append("INDEPENDENT_DAYS")
    if e.net_avg is None or e.net_avg < float(cfg.get("bar_avg", 2.0)):
        failures.append("AVG")
    if e.block_lcb is None or e.block_lcb <= float(cfg.get("lcb_min", 0.0)):
        failures.append("LCB")
    if (e.recent_n >= int(cfg.get("recent_n", 5))
            and e.recent_avg is not None
            and e.recent_avg < float(cfg.get("recent_min", 0.0))):
        failures.append("RECENT")
    if e.q_value is None or e.q_value > float(cfg.get("fdr_q", 0.05)):
        failures.append("FDR")
    return not failures, tuple(failures)


def current_era_evidence(episodes: dict, book_map: dict, governor_state: dict,
                         governor_cfg: dict, aliases: Optional[dict] = None,
                         now: Optional[datetime] = None) -> dict:
    """Single source of truth for governor AND shadowboard.

    episodes  — shadowboard db["episodes"]
    book_map  — governor book(): (pair, sess, sid) -> {status, side, cfg_hash,…}
    governor_state — data/governor_state.json (era_start clocks)
    aliases   — (cell, setup, side) -> new sid (rename continuity)
    Returns {key: SetupEvidence} with q-values and promotability filled in.
    """
    now = now or datetime.now(timezone.utc)
    eras = (governor_state or {}).get("era_start", {})
    default_era = str(governor_cfg.get("default_era_start",
                                       "2026-07-19T00:00:00+00:00"))
    slip = float(governor_cfg.get("slippage_pips", 0.5))
    reps = int(governor_cfg.get("bootstrap_reps", 10_000))
    conf = float(governor_cfg.get("bootstrap_confidence", 0.95))
    aliases = aliases or {}

    obs_by_key: dict[tuple, list[TrialObservation]] = defaultdict(list)
    for ep in (episodes or {}).values():
        sc = ep.get("scores")
        if not sc:
            continue
        # METRIC-VERSION ISOLATION: v2 only, mechanics matching current config
        if sc.get("mv") != 2:
            continue
        pair, sess = (ep["cell"].split("/") + ["?"])[:2]
        sid = aliases.get((ep["cell"], ep["setup"], ep["side"]), ep["setup"])
        key = (pair, sess, sid)
        meta = book_map.get(key)
        if meta is None or ep.get("side") != meta.get("side"):
            continue
        if (ep.get("mech") and meta.get("cfg_hash")
                and ep["mech"] != meta["cfg_hash"]):
            continue
        if ep["t"] < eras.get("|".join(key), default_era):
            continue
        net = episode_net(sc["net240"], ep.get("spread"), pair,
                          slippage_pips=slip, executable=True)
        obs_by_key[key].append(TrialObservation(
            key=key, timestamp=ep["t"], block_id=f'{ep["t"][:10]}|{sess}',
            net_pips=net, metric_version=METRIC_V2))

    cutoff7 = (now - timedelta(days=7)).isoformat()
    evidence: dict[tuple, SetupEvidence] = {}
    for key, obs in obs_by_key.items():
        obs.sort(key=lambda o: o.timestamp)
        nets = [o.net_pips for o in obs]
        recent = [o.net_pips for o in obs if o.timestamp >= cutoff7]
        binf = block_bootstrap_mean(obs, reps=reps, confidence=conf)
        evidence[key] = SetupEvidence(
            key=key, raw_n=len(obs),
            effective_n=effective_n([o.timestamp for o in obs]),
            independent_days=binf.independent_blocks,
            net_avg=round(sum(nets) / len(nets), 2),
            recent_n=len(recent),
            recent_avg=round(sum(recent) / len(recent), 2) if recent else None,
            block_lcb=binf.lcb, p_value=binf.p_value)

    q = benjamini_hochberg({k: e.p_value for k, e in evidence.items()
                            if e.p_value is not None})
    for k, e in evidence.items():
        e.q_value = q.get(k)
        e.promotable, e.reason_codes = promotion_predicate(e, governor_cfg)
    return evidence
