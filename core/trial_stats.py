"""core/trial_stats.py — honest statistics for the trial system (D-6).

Three corrections from the 2026-07-27 external review, shared by the governor
and the Shadowboard so promotion and display always use the SAME math:

1. OVERLAP-AWARE EFFECTIVE SAMPLE SIZE. Episodes are deduped at 30-minute
   gaps but scored on 240-minute forward windows, so adjacent episodes share
   up to 7/8 of their label — treating them as independent makes any
   confidence bound overconfident. Each episode contributes
   min(1, gap_to_previous / label_window); the first contributes 1.
   (A cheap, conservative cousin of block/Newey-West adjustment.)

2. COST-ADJUSTED UTILITY. Stamp scores measure frictionless mid drift; live
   fills pay spread + slippage. The same haircut — the stamped entry-time
   spread (or a per-pair default for pre-D-6 stamps) plus a slippage
   constant — is applied before ANY verdict, so promotion (stamps) and
   demotion (fills) finally speak the same currency.

3. DEFLATED CONFIDENCE. With ~150+ hypotheses examined daily, a 95% bound
   per test is a false-discovery machine. The promotion z is configurable
   (governor config `z_promote`, default 2.33 ≈ 99% one-sided) — partial
   deflation, chosen over full Šidák (z≈3.7 at M=150) which would freeze
   promotion entirely at reachable sample sizes; the hypothesis-registry
   count is reported in every ledger line so the knob can be tuned on
   evidence. See Bailey & López de Prado (PBO / Deflated Sharpe).
"""
from __future__ import annotations

import math
import statistics
from datetime import datetime
from typing import Optional, Sequence

DEFAULT_SLIPPAGE_PIPS = 0.5
LABEL_MINUTES = 240.0


def default_spread(pair: str) -> float:
    """Fallback entry spread (pips) for stamps that predate spread stamping.
    Deliberately a touch pessimistic — the stamped live spread supersedes
    this for all post-D-6 episodes."""
    base, _, quote = pair.partition("_")
    if "USD" in (base, quote):
        return 1.5    # USD majors
    return 3.0        # crosses


def effective_n(times: Sequence[str], label_minutes: float = LABEL_MINUTES) -> float:
    """Overlap-aware effective sample size from ISO episode timestamps."""
    if not times:
        return 0.0
    ts = sorted(datetime.fromisoformat(t).timestamp() for t in times)
    n_eff = 1.0
    for prev, cur in zip(ts, ts[1:]):
        gap_min = (cur - prev) / 60.0
        n_eff += max(0.0, min(1.0, gap_min / label_minutes))
    return round(n_eff, 2)


def cost_adjusted_nets(nets: Sequence[float],
                       spreads: Sequence[Optional[float]],
                       pair: str,
                       slippage_pips: float = DEFAULT_SLIPPAGE_PIPS) -> list[float]:
    """Gross stamp nets → net-of-cost (per-episode stamped spread when known)."""
    fallback = default_spread(pair)
    out = []
    for net, spr in zip(nets, spreads):
        cost = (spr if isinstance(spr, (int, float)) and spr > 0 else fallback)
        out.append(net - cost - slippage_pips)
    return out


def episode_net(gross: float, spread: Optional[float], pair: str,
                slippage_pips: float = DEFAULT_SLIPPAGE_PIPS,
                executable: bool = False) -> float:
    """One episode's net-of-cost pips, metric-version aware (D-7).

    executable=True  — the executable-exit-v2 metric already PAID the spread
                       inside its geometry (entry at ask/bid, exit on the
                       liquidation side), so deducting the stamped spread
                       again would double-charge; only slippage remains.
    executable=False — legacy-mid-v1 mid-drift scores never touched the
                       spread; deduct stamped spread (or per-pair fallback)
                       plus slippage, exactly as D-6 defined."""
    if gross is None:
        return None          # CENSORED episode (still open) — not an outcome
    if executable:
        return gross - slippage_pips
    return cost_adjusted_nets([gross], [spread], pair, slippage_pips)[0]


def lcb(values: Sequence[float], n_eff: float, z: float) -> Optional[float]:
    """One-sided lower confidence bound on the mean, with the OVERLAP-adjusted
    sample size in the denominator (variance still estimated from raw values).
    None when there's no meaningful sample (fewer than 2 values or n_eff<=1)."""
    if len(values) < 2 or n_eff is None or n_eff <= 1.0:
        return None
    avg = sum(values) / len(values)
    sd = statistics.stdev(values)
    return round(avg - z * sd / math.sqrt(n_eff), 2)
