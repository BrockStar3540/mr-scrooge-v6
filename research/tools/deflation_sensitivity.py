#!/usr/bin/env python3
"""research/tools/deflation_sensitivity.py — closed-market sensitivity for the
issue #9 deflation test.

Post-hoc and NOT part of the pre-registered verdict. Asked for on issue #9
(2026-10-22): re-run the bar replica's PBO with the closed-market episodes
dropped. If PBO_bar = 0.03 holds, the data issue is moot.

The registered script (research/tools/deflation_test.py) is not modified.
This tool writes a filtered copy of the frozen episode file and runs that
script's own run() on it, once per filter:

  saturday  drop episodes stamped on a Saturday (UTC), the 1,421 / 2.0%
            figure quoted in RESULTS.md.
  closed    drop every episode stamped while FX was shut: New York time
            Fri 16:55 -> Sun 17:00, the calendar form of the live scorer's
            test (ops/shadowboard._market_closed_at: no M5 bar opening
            within 30 min after the stamp, or none closing within 30 min
            before it). The last M5 bar of the week opens Fri 16:55 NY and
            the first opens Sun 17:00 NY.

    python research/tools/deflation_sensitivity.py \
        --episodes /path/to/shadowboard_frozen.json \
        --registry REG.json --decisions DEC.jsonl --cells config/cells \
        --aliases config/setup_aliases.json --cutoff 2026-10-21 \
        --out research/deflation/sensitivity_closed_market.json
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import tempfile
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from research.tools import deflation_test as dt  # noqa: E402

NY = ZoneInfo("America/New_York")
FRI, SAT, SUN = 4, 5, 6
LAST_BAR_OPEN = time(16, 55)   # NY, Friday
FIRST_BAR_OPEN = time(17, 0)   # NY, Sunday


def _utc(t: str) -> datetime:
    return datetime.fromisoformat(t.replace("Z", "+00:00"))


def is_saturday(t: str) -> bool:
    return _utc(t).weekday() == SAT


def is_closed_market(t: str) -> bool:
    ny = _utc(t).astimezone(NY)
    wd, hm = ny.weekday(), ny.time()
    if wd == SAT:
        return True
    if wd == FRI:
        return hm > LAST_BAR_OPEN
    if wd == SUN:
        return hm < FIRST_BAR_OPEN
    return False


FILTERS = {"saturday": is_saturday, "closed": is_closed_market}


def split_episodes(eps: dict, drop) -> tuple[dict, int]:
    """Keep the episodes `drop` rejects; count the dropped ones that the
    deflation run would otherwise have used (resolved v2, net240 set)."""
    kept, n = {}, 0
    for k, ep in eps.items():
        if drop(ep["t"]):
            sc = ep.get("scores") or {}
            n += sc.get("mv") == 2 and sc.get("net240") is not None
            continue
        kept[k] = ep
    return kept, n


def rank_pct(median_logit: float) -> float:
    """Invert the CSCV logit: the selected set's relative out-of-sample rank."""
    return 1 / (1 + math.exp(-median_logit))


def headline(res: dict) -> dict:
    ps = res["promoted_set"]["dsr_all_ever_seated"]
    c16, c8 = res["cscv_S16"], res["cscv_S8"]
    return {
        "episodes_used": res["inputs"]["episodes_used"],
        "median_dsr_ever_seated": ps.get("median_dsr"),
        "pbo_bar_S16": c16["pbo_bar"], "pbo_bar_S8": c8["pbo_bar"],
        "pbo_max_sr_S16": c16["pbo_max_sr"],
        "median_logit_bar_S16": c16["median_logit_bar"],
        "selected_oos_rank_pct_S16": rank_pct(c16["median_logit_bar"]),
        "mean_oos_sr_selected_S16": c16["mean_oos_sr_selected"],
        "mean_oos_sr_rest_S16": c16["mean_oos_sr_rest"],
        "verdict_rule_output": res["verdict"],
    }


def run_filtered(a, name: str, eps: dict) -> dict:
    kept, dropped = split_episodes(eps, FILTERS[name])
    with tempfile.TemporaryDirectory() as td:
        ep_path = Path(td) / "episodes.json"
        ep_path.write_text(json.dumps({"episodes": kept}))
        res = dt.run(argparse.Namespace(**{**vars(a), "episodes": str(ep_path)}))
    return {"dropped_episodes": dropped, **headline(res)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--episodes", required=True)
    ap.add_argument("--registry", default=str(REPO / "research/registry/registry.json"))
    ap.add_argument("--decisions", default=str(REPO / "research/registry/decisions.jsonl"))
    ap.add_argument("--cells", default=str(REPO / "config/cells"))
    ap.add_argument("--aliases", default=str(REPO / "config/setup_aliases.json"))
    ap.add_argument("--cutoff", required=True)
    ap.add_argument("--min-days", type=int, default=10)
    ap.add_argument("--min-split-days", type=int, default=5)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)

    eps = json.loads(Path(a.episodes).read_text())["episodes"]
    base = dt.run(a)
    out = {
        "about": "Post-hoc sensitivity for issue #9; not part of the pre-registered verdict.",
        "generated": datetime.now().astimezone().isoformat(),
        "inputs": base["inputs"],
        "baseline": {"dropped_episodes": 0, **headline(base)},
        **{name: run_filtered(a, name, eps) for name in FILTERS},
    }
    Path(a.out).write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps({k: v for k, v in out.items() if k not in ("inputs",)}, indent=1))


if __name__ == "__main__":
    main()
